#include <ctype.h>
/* nesrecomp runtime: the CPU memory bus and the program entry point.
   The .nes file is loaded at runtime; the generated code holds only the
   translated instruction logic. */
#include <stdlib.h>
#include <string.h>
#include "rt.h"
#include "apu.h"
#include "event.h"
#include "gamepad.h"
#include "cart.h"
#include "cycles.h"
#include "input.h"
#include "mapper.h"
#include "nsf.h"
#include "palette.h"
#include "ppu.h"
#include "video.h"
#include "wav.h"

uint8_t A, X, Y, SP = 0xFD;
uint8_t C, Z, I = 1, D, V, N;
uint16_t pc;
uint64_t cycles = 7;          /* the reset sequence takes 7 cycles */
int trace_on;
uint16_t insn_pc;
uint64_t insn_start;

static uint8_t ram[0x800];    /* 2 KB of console RAM, mirrored to $1FFF */

/* OAM DMA: writing page number P to $4014 copies $P00-$PFF into sprite
   memory, while the CPU is halted for 513 or 514 cycles (more if the DMC
   fetches a sample byte meanwhile; apu_oam_dma has the timing). */
static void oam_dma(uint8_t page) {
    ppu_catch_up();
    for (int i = 0; i < 256; i++)
        ppu.oam[(uint8_t)(ppu.oam_addr + i)] = rd((uint16_t)(page << 8 | i));
    /* The caller adds the write's own cycle afterwards. */
    cycles = apu_oam_dma() - 1;
}

uint8_t rd(uint16_t a) {
    if (a < 0x2000) return ram[a & 0x7FF];
    if (a < 0x4020 && cycles + DMA_CHECK_AHEAD >= dmc_dma_due) apu_dma_point(a);
    if (a < 0x4000) return ppu_reg_read(a);
    if (a == 0x4015) return apu_read_status();
    if (a == 0x4016 || a == 0x4017) return input_read(a & 1);
    if (a >= 0x8000) return prg_read(a);
    if (a >= 0x6000)
        return mapper.prg_ram_disabled ? 0 : mapper.ram6000[a - 0x6000];
    if (a >= 0x4020) return mapper_read_low(a);
    return 0;                 /* APU and unmapped space: not wired up yet */
}

uint8_t peek(uint16_t a) {
    if (a < 0x2000) return ram[a & 0x7FF];
    if (a >= 0x8000) return prg_read(a);
    if (a >= 0x6000)
        return mapper.prg_ram_disabled ? 0 : mapper.ram6000[a - 0x6000];
    return 0;
}

void wr(uint16_t a, uint8_t v) {
    if (a < 0x2000) ram[a & 0x7FF] = v;
    else if (a < 0x4000) ppu_reg_write(a, v);
    else if (a == 0x4014) oam_dma(v);
    else if (a == 0x4016) input_write_strobe(v);
    else if (a <= 0x4017) apu_write(a, v);      /* $4000-$4013, $4015, $4017 */
    else if (a >= 0x8000) mapper_write(a, v);
    else if (a >= 0x4020 && a < 0x6000) mapper_write_low(a, v);
    else if (a >= 0x6000) {
        if (!mapper.prg_ram_disabled && !mapper.prg_ram_readonly)
            mapper.ram6000[a - 0x6000] = v;
    }
}

/* An NSF's "reset" starts the current song again from the driver, with
   RAM cleared as an NSF player clears it before init. Changing song
   sets nsf_next_song and resets. */
static int nsf_next_song;
static long song_frames;            /* how long the song has played */

uint16_t cpu_reset_target(void) {
    if (cart.mapper != MAPPER_NSF) return rd(0xFFFC) | (rd(0xFFFD) << 8);
    memset(ram, 0, sizeof ram);
    memset(cart.prg_ram, 0, sizeof cart.prg_ram);
    song_frames = 0;
    return nsf_start(nsf_next_song ? nsf_next_song : nsf.song);
}

void trace_step(uint16_t a) {
    if (check_cycles) cycle_check_step(a);
    printf("%04X A:%02X X:%02X Y:%02X P:%02X SP:%02X CYC:%llu\n",
           a, A, X, Y, getP(0), SP, (unsigned long long)cycles);
}

void untranslated(uint16_t a) {
    fprintf(stderr, "stopped: unknown opcode $%02X at $%04X\n", rd(a), a);
}

/* Places where native code handed off to the interpreter, as (8 KB bank,
   address): the same address can hold different code in different banks.
   Saved on exit as "BB:AAAA" lines so the recompiler can translate them
   natively on the next pass. Addresses below $8000 (code in RAM) are
   counted but not saved, since they can't be translated ahead of time. */
static uint8_t *missed;             /* one byte per bank * 32 KB of addresses */
static int missed_count;

/* Banks as the recompiler counts them: 8 KB, or 4 KB for a bank-switched
   NSF (mapper.code_4k). */
static int code_banks(void) {
    return (int)(cart.prg_size / (mapper.code_4k ? 0x1000 : 0x2000));
}
static int code_bank_at(uint16_t a) {
    return mapper.code_4k ? mapper.prg_bank_4k[(a >> 12) & 7]
                          : mapper.prg_bank[(a >> 13) & 3];
}

static uint8_t *missed_slot(int bank, uint16_t a) {
    if (!missed) missed = calloc((size_t)code_banks() * 0x8000, 1);
    return &missed[(size_t)bank * 0x8000 + (a - 0x8000)];
}

void note_missed(uint16_t a) {
    /* The NSF driver (nsf.h) is always interpreted: not worth counting. */
    if (cart.mapper == MAPPER_NSF && a >= NSF_DRIVER && a < 0x4200) return;
    if (a < 0x8000) { missed_count++; return; }
    uint8_t *m = missed_slot(code_bank_at(a), a);
    if (!*m) { *m = 1; missed_count++; }
}

static const char *rom_path;

static void save_missed(void) {
    char path[1024], line[64];
    snprintf(path, sizeof path, "%s.missed", rom_path);
    int banks = code_banks();
    /* Merge with earlier runs so discoveries accumulate across passes.
       Plain "AAAA" lines (the old format) mean the power-on bank. */
    FILE *f = fopen(path, "r");
    if (f) {
        while (fgets(line, sizeof line, f)) {
            unsigned b, a;
            if (sscanf(line, "%x:%x", &b, &a) == 2) { /* BB:AAAA */ }
            else if (sscanf(line, "%x", &a) == 1 && !mapper.code_4k)
                b = (unsigned)mapper.power_on_bank[(a >> 13) & 3];
            else continue;
            if (a >= 0x8000 && a <= 0xFFFF) *missed_slot((int)(b % banks), (uint16_t)a) = 1;
        }
        fclose(f);
    }
    if (!missed) return;
    f = fopen(path, "w");
    if (!f) return;
    for (int b = 0; b < banks; b++)
        for (int a = 0x8000; a <= 0xFFFF; a++)
            if (*missed_slot(b, (uint16_t)a)) fprintf(f, "%02X:%04X\n", b, a);
    fclose(f);
    fprintf(stderr, "%d spot(s) ran in the interpreter; listed in %s\n",
            missed_count, path);
}

/* Blargg-style test ROMs write a status byte at $6000 ($80 = still
   running), the signature DE B0 61 at $6001, and text from $6004. */
static void print_test_result(void) {
    const uint8_t *r = cart.prg_ram;
    if (r[1] != 0xDE || r[2] != 0xB0 || r[3] != 0x61) return;
    fprintf(stderr, "test status at $6000: $%02X%s\n", r[0],
            r[0] == 0x80 ? " (still running)" : r[0] == 0 ? " (passed)" : "");
    fprintf(stderr, "test output:\n%.*s\n", 0x2000 - 4, (const char *)r + 4);
}

static int use_save_file;
static const char *wav_path;
static int speakers, audio_stats;

/* Hand the APU's finished samples to the speakers and/or WAV file. */
static void drain_sound(void) {
    int16_t buf[4096];
    apu_catch_up();
    int n;
    while ((n = apu_take_samples(buf, 4096)) > 0) {
        if (wav_path) wav_write(buf, n);
        if (speakers) video_queue_audio(buf, n);
    }
}

static void at_exit(void) {
    if (wav_path) { drain_sound(); wav_close(); }
    save_missed();
    print_test_result();
    if (use_save_file) cart_write_save(rom_path);
}

/* Scripted input: from frame N on, the controllers hold these buttons.
   File format, one change per line ('#' starts a comment):
       120 start        press Start on controller 1 at frame 120
       126              release everything at frame 126
       200 a right      hold A and Right from frame 200
       300 a 2:start    A on controller 1 and Start on controller 2
                        (3: and 4: for controllers 3 and 4)
       400 knob=160 fire  paddle: knob at 160, button down (2: for the
                        second paddle); the knob stays put until moved
       500 aim=128,100 trigger   Zapper: aimed at pixel (128, 100), the
                        trigger pulled; the aim stays put until moved, and
                        aim=off points it away from the screen */
#define MAX_SCRIPT 4096
static struct {
    long frame;
    uint8_t buttons[4], fire[2], trigger;
    int knob[2];                    /* -1: unchanged */
    int aim_x, aim_y;               /* aim_x: -2 unchanged, -1 off */
} script[MAX_SCRIPT];
static int script_len, script_pos;
static uint8_t script_buttons[4], script_fire[2], script_trigger;

static void load_input_script(const char *path) {
    static const char *names[8] =
        { "a", "b", "select", "start", "up", "down", "left", "right" };
    FILE *f = fopen(path, "r");
    if (!f) { perror(path); exit(1); }
    char line[256];
    int lineno = 0;
    while (fgets(line, sizeof line, f)) {
        lineno++;
        char *hash = strchr(line, '#');
        if (hash) *hash = 0;
        char *tok = strtok(line, " \t\r\n");
        if (!tok) continue;
        if (script_len == MAX_SCRIPT) break;
        long frame = strtol(tok, NULL, 10);
        if (script_len && frame < script[script_len - 1].frame) {
            fprintf(stderr, "%s:%d: frames must go up\n", path, lineno);
            exit(1);
        }
        uint8_t b[4] = { 0, 0, 0, 0 }, fire[2] = { 0, 0 };
        int knob[2] = { -1, -1 }, aim_x = -2, aim_y = 0;
        uint8_t trigger = 0;
        while ((tok = strtok(NULL, " \t\r\n"))) {
            int pad = 0;
            const char *name = tok;
            if (tok[0] >= '2' && tok[0] <= '4' && tok[1] == ':') {
                pad = tok[0] - '1';
                name = tok + 2;
            }
            int paddle = pad < 2;           /* knob and fire: 1 or 2 only */
            if (!strcmp(name, "fire") && paddle) { fire[pad] = 1; continue; }
            if (!strcmp(tok, "trigger")) { trigger = 1; continue; }
            if (!strcmp(tok, "aim=off")) { aim_x = -1; continue; }
            if (!strncmp(tok, "aim=", 4)) {
                int x, y, n = 0;
                if (sscanf(tok + 4, "%d,%d%n", &x, &y, &n) != 2 || tok[4 + n] ||
                    x < 0 || x >= 256 || y < 0 || y >= 240) {
                    fprintf(stderr, "%s:%d: aim needs X,Y (0-255, 0-239) or off: '%s'\n",
                            path, lineno, tok);
                    exit(1);
                }
                aim_x = x; aim_y = y;
                continue;
            }
            if (!strncmp(name, "knob=", 5) && paddle) {
                char *end;
                long n = strtol(name + 5, &end, 10);
                if (*end || end == name + 5 || n < 0 || n > 255) {
                    fprintf(stderr, "%s:%d: knob needs 0-255: '%s'\n",
                            path, lineno, tok);
                    exit(1);
                }
                knob[pad] = (int)n;
                continue;
            }
            int k = 0;
            while (k < 8 && strcmp(name, names[k])) k++;
            if (k == 8) {
                fprintf(stderr, "%s:%d: unknown button '%s'\n", path, lineno, tok);
                exit(1);
            }
            b[pad] |= (uint8_t)(1 << k);
        }
        script[script_len].frame = frame;
        for (int p = 0; p < 4; p++) script[script_len].buttons[p] = b[p];
        script[script_len].trigger = trigger;
        script[script_len].aim_x = aim_x;
        script[script_len].aim_y = aim_y;
        for (int p = 0; p < 2; p++) {
            script[script_len].fire[p] = fire[p];
            script[script_len].knob[p] = knob[p];
        }
        script_len++;
    }
    fclose(f);
}

static int headless;
static long stop_after_frames;      /* 0 = run until the window closes */
static const char *screenshot_path;
static int dump_text;

/* Print the first nametable as text: tile numbers $20-$7E as the ASCII
   character with that code, which is how most test ROMs lay out their
   font. Lets a test runner read results that are only shown on screen. */
static void print_screen_text(void) {
    for (int row = 0; row < 30; row++) {
        char line[33];
        int end = 0;
        for (int col = 0; col < 32; col++) {
            uint8_t t = ppu_mem_read((uint16_t)(0x2000 + row * 32 + col));
            line[col] = (t >= 0x20 && t < 0x7F) ? (char)t : ' ';
            if (line[col] != ' ') end = col + 1;
        }
        if (end) printf("%.*s\n", end, line);
    }
}

/* A $6000-style test has finished when its signature is there and the
   status byte has left "running" ($80) and "press reset" ($81). */
static int test_rom_finished(void) {
    const uint8_t *r = cart.prg_ram;
    return r[1] == 0xDE && r[2] == 0xB0 && r[3] == 0x61 && r[0] < 0x80;
}

static void finish_run(const uint16_t *fb) {
    if (screenshot_path && video_save_png(fb, screenshot_path) == 0)
        fprintf(stderr, "saved frame %llu to %s\n",
                (unsigned long long)ppu.frame, screenshot_path);
    if (dump_text) print_screen_text();
    exit(0);
}

/* NSF: a song change from controller 1 (keyboard arrows, a game
   controller or a script): Left and Right step through the songs. */
static void nsf_controls(void) {
    static uint8_t held;
    uint8_t now = pad_buttons[0], pressed = (uint8_t)(now & ~held);
    held = now;
    int step = (pressed & BTN_RIGHT) ? 1 : (pressed & BTN_LEFT) ? -1 : 0;
    if (!step) return;
    nsf_next_song = (nsf.song - 1 + step + nsf.songs) % nsf.songs + 1;
    cpu_request_reset();
}

/* The first paddle from the mouse: its position across the window turns
   the knob over VAUS_STEPS counts, from vaus_left at the left edge
   (wrapping past 255, as a real knob's reading can), and the left
   button is the paddle's button, as well as any scripted press. The
   knob only follows the mouse once it has moved over the window. Games
   expect different ranges (nesdev wiki): Arkanoid II $4D-$E2, the first
   Arkanoid $62 round to $02; --vaus-left moves the range. */
#define VAUS_STEPS 160
static int vaus_left = 0x4D;

static void paddle_mouse(void) {
    double x;
    int button;
    if (headless || !(port_device[0] == DEV_VAUS || port_device[1] == DEV_VAUS ||
                      famicom_vaus)) return;
    if (!video_mouse(&x, &button)) return;
    vaus[0].knob = (uint8_t)(vaus_left + (int)(x * VAUS_STEPS + 0.5));
    vaus[0].fire |= (uint8_t)button;
}

static void frame_done(const uint16_t *ppu_fb) {
    /* An NSF has no picture of its own: show its screen instead. */
    static uint16_t nsf_screen[256 * 240];
    const uint16_t *fb = ppu_fb;
    if (cart.mapper == MAPPER_NSF) {
        nsf_draw(nsf_screen, song_frames++);
        fb = nsf_screen;
    }
    if (wav_path || speakers) drain_sound();
    if (audio_stats && ppu.frame % 60 == 0)
        fprintf(stderr, "frame %llu: %d samples queued\n",
                (unsigned long long)ppu.frame, video_audio_queued());
    if (!headless) video_present(fb);
    /* Buttons for the next frame: the script, plus the keyboard. */
    while (script_pos < script_len && script[script_pos].frame <= (long)ppu.frame) {
        for (int p = 0; p < 4; p++) script_buttons[p] = script[script_pos].buttons[p];
        script_trigger = script[script_pos].trigger;
        if (script[script_pos].aim_x != -2) {
            zapper.x = script[script_pos].aim_x;
            zapper.y = script[script_pos].aim_y;
        }
        for (int p = 0; p < 2; p++) {
            script_fire[p] = script[script_pos].fire[p];
            if (script[script_pos].knob[p] >= 0)
                vaus[p].knob = (uint8_t)script[script_pos].knob[p];
        }
        script_pos++;
    }
    for (int p = 0; p < 4; p++)
        pad_buttons[p] = script_buttons[p] | (headless ? 0 : video_buttons(p));
    for (int p = 0; p < 2; p++) vaus[p].fire = script_fire[p];
    zapper.trigger = script_trigger;
    paddle_mouse();
    if (cart.mapper == MAPPER_NSF) nsf_controls();
    if (stop_after_frames && (long)ppu.frame >= stop_after_frames)
        finish_run(fb);
    /* Headless runs stop as soon as a $6000 test reports its result. */
    if (headless && test_rom_finished()) finish_run(fb);
    /* Status $81 means "press reset, at least 100 ms from now": in
       headless runs, press it 10 frames (about 170 ms) later. */
    static int reset_wait;
    const uint8_t *r = cart.prg_ram;
    if (headless && r[1] == 0xDE && r[2] == 0xB0 && r[3] == 0x61 &&
        r[0] == 0x81) {
        if (++reset_wait == 10) { cpu_request_reset(); reset_wait = 0; }
    } else {
        reset_wait = 0;
    }
}

static void usage(const char *prog) {
    fprintf(stderr,
        "usage: %s game.nes|music.nsf [options]\n"
        "  --headless         no window (for tests)\n"
        "  --frames N         stop after N frames\n"
        "  --screenshot FILE  with --frames: save the last frame as a PNG\n"
        "  --dump-text        with --frames: print the screen's tiles as text\n"
        "  --no-save          don't load or write <rom>.sav (battery RAM)\n"
        "  --wav FILE         write the sound to a WAV file\n"
        "  --mute             no sound from the speakers (M toggles it)\n"
        "  --audio-stats      print the sound queue depth once a second\n"
        "  --input FILE       scripted button presses (see README.md)\n"
        "  --scale N          window size, N times 256x240 (default 3)\n"
        "  --mmc3-rev A|B     which MMC3 chip to act like (default B)\n"
        "  --port1 pad|vaus|zapper  what controller port 1 holds (default\n"
        "  --port2 pad|vaus|zapper    pad); vaus is the NES Arkanoid paddle\n"
        "  --famicom-zapper   a Famicom Zapper in the expansion port\n"
        "  --famicom-vaus     a Famicom Arkanoid paddle in the expansion port\n"
        "  --four-score       controllers 3 and 4 through an NES Four Score\n"
        "  --famicom-4p       controllers 3 and 4 in the Famicom expansion port\n"
        "  --hori-4p          controllers 1-4 through Hori's Famicom adapter\n"
        "  --vaus-left N      paddle: the knob at the window's left edge, 0-255\n"
        "                     (default 77; the right edge is 160 more)\n"
        "  --song N           NSF: play song N (from 1; default: the file's own)\n"
        "  --info             print the cartridge header and exit\n"
        "(or, with no ROM: --test-gamepads checks the game controller mapping)\n"
        "  --trace            print CPU state before every instruction\n"
        "  --check-cycles     with --trace: check each instruction's cycle map\n"
        "  --start HEX        start here instead of the reset vector\n",
        prog);
    exit(1);
}

int main(int argc, char **argv) {
    /* A self-test of the game controller mapping, with no ROM (make test). */
    if (argc == 2 && !strcmp(argv[1], "--test-gamepads")) return gamepad_self_test();
    if (argc < 2 || argv[1][0] == '-') usage(argv[0]);
    rom_path = argv[1];
    cart_load(rom_path);
    mapper_init();
    uint16_t start = rd(0xFFFC) | (rd(0xFFFD) << 8);
    int scale = 3, no_save = 0, mute = 0, song = 0;
    for (int i = 2; i < argc; i++) {
        const char *a = argv[i];
        int more = i + 1 < argc;
        if (!strcmp(a, "--trace")) trace_on = 1;
        else if (!strcmp(a, "--check-cycles")) check_cycles = 1;
        else if (!strcmp(a, "--headless")) headless = 1;
        else if (!strcmp(a, "--start") && more)
            start = (uint16_t)strtol(argv[++i], NULL, 16);
        else if (!strcmp(a, "--frames") && more)
            stop_after_frames = strtol(argv[++i], NULL, 10);
        else if (!strcmp(a, "--screenshot") && more) screenshot_path = argv[++i];
        else if (!strcmp(a, "--scale") && more) scale = atoi(argv[++i]);
        else if (!strcmp(a, "--input") && more) load_input_script(argv[++i]);
        else if (!strcmp(a, "--dump-text")) dump_text = 1;
        else if (!strcmp(a, "--no-save")) no_save = 1;
        else if (!strcmp(a, "--wav") && more) wav_path = argv[++i];
        else if (!strcmp(a, "--mute")) mute = 1;
        else if (!strcmp(a, "--audio-stats")) audio_stats = 1;
        else if (!strcmp(a, "--mmc3-rev") && more) {
            char r = (char)toupper((unsigned char)argv[++i][0]);
            if (r != 'A' && r != 'B') usage(argv[0]);
            mmc3_revision = r;
        }
        else if (!strcmp(a, "--song") && more) song = atoi(argv[++i]);
        else if ((!strcmp(a, "--port1") || !strcmp(a, "--port2")) && more) {
            const char *d = argv[++i];
            int port = a[6] - '1';
            if (!strcmp(d, "pad")) port_device[port] = DEV_PAD;
            else if (!strcmp(d, "vaus")) port_device[port] = DEV_VAUS;
            else if (!strcmp(d, "zapper")) port_device[port] = DEV_ZAPPER;
            else usage(argv[0]);
        }
        else if (!strcmp(a, "--famicom-vaus")) famicom_vaus = 1;
        else if (!strcmp(a, "--famicom-zapper")) famicom_zapper = 1;
        else if (!strcmp(a, "--four-score")) four_players = FOUR_SCORE;
        else if (!strcmp(a, "--famicom-4p")) four_players = FOUR_FAMICOM;
        else if (!strcmp(a, "--hori-4p")) four_players = FOUR_HORI;
        else if (!strcmp(a, "--vaus-left") && more) {
            char *end;
            long n = strtol(argv[++i], &end, 0);
            if (*end || n < 0 || n > 255) usage(argv[0]);
            vaus_left = (int)n;
        }
        else if (!strcmp(a, "--info")) { cart_print_info(rom_path); return 0; }
        else usage(argv[0]);
    }
    /* An NSF has no reset vector: the runtime's driver calls its routines. */
    if (cart.mapper == MAPPER_NSF) {
        start = nsf_start(song);
        nsf_next_song = nsf.song;
    }
    /* The Four Score holds both ports; the Famicom's players 3 and 4 use
       the expansion port's bit 1, as its paddle does. */
    if (four_players == FOUR_SCORE && (port_device[0] || port_device[1])) {
        fprintf(stderr, "--four-score takes both ports: no --port1/--port2 with it\n");
        return 1;
    }
    if (four_players >= FOUR_FAMICOM && famicom_vaus) {
        fprintf(stderr, "a Famicom 4-player wiring and a paddle can't be plugged in together\n");
        return 1;
    }
    if ((port_device[0] == DEV_ZAPPER) + (port_device[1] == DEV_ZAPPER) +
        famicom_zapper > 1) {
        fprintf(stderr, "only one Zapper can be plugged in\n");
        return 1;
    }
    if ((screenshot_path || dump_text) && !stop_after_frames) {
        fprintf(stderr, "--screenshot and --dump-text need --frames N\n");
        return 1;
    }

    if (cart.battery && !no_save) {
        cart_load_save(rom_path);
        use_save_file = 1;
    }

    palette_init();
    if (!headless) {
        const char *name = strrchr(rom_path, '/');
        name = name ? name + 1 : rom_path;
        if (cart.mapper == MAPPER_NSF && nsf.title[0]) name = nsf.title;
        video_init(scale < 1 ? 1 : scale, name);
    }
    atexit(at_exit);
    ppu_frame_done = frame_done;
    apu_reset();
    if (!headless && !mute) { video_init_audio(); speakers = 1; }
    if (wav_path) wav_open(wav_path);
    if (wav_path || speakers) apu_enable_sound();
    ppu_schedule();
    apu_schedule();

    recomp_run(start);
    fprintf(stderr, "stopped. result bytes $02=%02X $03=%02X\n", ram[2], ram[3]);
    return 0;
}
