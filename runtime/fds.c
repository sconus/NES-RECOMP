/* nesrecomp runtime: the Famicom Disk System.

   ---- Its sound (nesdev wiki "FDS audio") ----
   One wavetable channel with frequency modulation:
     $4040-$407F  64 samples, 6 bits each; written only while $4089 bit
                  7 is set; read back with bits 7-6 = 01 (with $4089 bit 7
                  clear, any of them reads the sample being played)
     $4080        volume envelope: bit 7 off (bits 5-0 are then the gain),
                  bit 6 up (else down), bits 5-0 speed
     $4082/3      12-bit frequency; $4083 bit 7 stops the wave (and resets
                  its position to 0), bit 6 stops both envelopes (and
                  resets their timers)
     $4084        modulation envelope, laid out as $4080
     $4085        the modulation counter, 7-bit signed
     $4086/7      12-bit modulation frequency; $4087 bit 7 stops the
                  modulation table (and opens $4088), bit 6 steps it every
                  tick
     $4088        modulation table write: 3 bits at the table position,
                  which then moves on one entry (only while $4087 bit 7)
     $4089        bit 7 wavetable write (the output holds its level, the
                  wave keeps moving), bits 1-0 master volume: 1, 2/3,
                  2/4, 2/5
     $408A        envelope speed multiplier (0 stops both envelopes)
     $4090/$4092  the volume / modulation gain; $4091 the wave
                  accumulator's bits 12-19; $4097 the modulation counter
   The wave and the modulation table move every 16 CPU cycles:
   - The modulation table (32 entries, each used twice, so 64 positions)
     is a position plus a 12-bit accumulator. Each tick adds the
     modulation frequency; a carry out of the accumulator (or $4087 bit
     6) applies the entry at the position to the counter and moves on.
     Entries: 0, +1, +2, +4, reset to 0, -4, -2, -1.
   - The wave's step is the frequency scaled by the counter times the
     modulation gain, rounded as the wiki gives it. A 24-bit accumulator
     adds it each tick, and its top 6 bits are the wave position.
   An envelope ticks every 8 * (speed + 1) * ($408A + 1) CPU cycles,
   moving its gain one step towards 0 or 32. A new volume gain is heard
   from the next time the wave passes position 0. The output is sample
   * min(volume gain, 32) * master volume, through a one-pole low-pass
   near 2 kHz. Full scale is 2.4 times an APU square's.
   Where the wiki's sources disagree, this follows the wiki:
   - with $4083 bit 7 set, the output is sample 0 (not silence), and the
     envelopes run 4 times as fast;
   - $4089 bit 7 holds the output level (rather than silencing it);
   - the counter keeps changing the pitch while the table is stopped. */
#include <math.h>
#include <string.h>
#include "fds.h"
#include "rt.h"

#define CPU_HZ 1789772.727
#define LOWPASS_HZ 2000.0
/* 63 * 32 at full master volume = 2.4 APU squares (0.1494 each). */
#define FDS_UNIT (2.4f * 0.1494f / 2016.0f)

static struct {
    uint8_t wave[64], mod_table[32];
    uint8_t vol_ctrl, mod_ctrl;     /* $4080, $4084 */
    uint8_t vol_gain, mod_gain;
    int vol_timer, mod_timer;       /* CPU cycles to the next envelope tick */
    uint16_t freq, mod_freq;        /* 12 bits each */
    uint8_t wave_flags, mod_flags;  /* $4083, $4087 bits 7-6 */
    int counter;                    /* -64..63 */
    uint32_t wave_acc;              /* 24 bits; bits 23-18 the position */
    uint32_t mod_acc;               /* 12 bits */
    int mod_pos;                    /* 0-63; entry mod_pos / 2 */
    uint8_t write_mode, master, env_speed;
    uint8_t vol_out;                /* the gain heard, at most 32 */
    int tick;                       /* CPU cycles to the next 16-cycle tick */
    int held;                       /* the level while $4089 bit 7 is set */
    float filtered;
    uint64_t now;                   /* the CPU cycle the state is at */
} fs;

int fds_sound_on = 1;

static int env_period(uint8_t ctrl) {
    int p = 8 * ((ctrl & 0x3F) + 1) * (fs.env_speed + 1);
    return (fs.wave_flags & 0x80) ? p / 4 : p;
}

void fds_sound_reset(void) {
    memset(&fs, 0, sizeof fs);
    /* As the BIOS leaves them: envelope off, speed multiplier $E8. */
    fs.vol_ctrl = fs.mod_ctrl = 0x80;
    fs.env_speed = 0xE8;
    fs.vol_timer = env_period(fs.vol_ctrl);
    fs.mod_timer = env_period(fs.mod_ctrl);
    fs.tick = 16;
    fs.now = cycles;
}

static void envelope(uint8_t ctrl, uint8_t *gain, int *timer) {
    if ((ctrl & 0x80) || (fs.wave_flags & 0x40) || fs.env_speed == 0) return;
    if (--*timer > 0) return;
    *timer = env_period(ctrl);
    if (ctrl & 0x40) { if (*gain < 32) ++*gain; }
    else if (*gain > 0) --*gain;
}

/* The wave's step for one tick: the frequency scaled by the
   modulation (nesdev wiki "FDS audio", the pitch computation). */
static uint32_t wave_step(void) {
    int temp = fs.counter * fs.mod_gain;
    if ((temp & 0x0F) && !(temp & 0x800)) temp += 0x20;
    temp += 0x400;
    temp = (temp >> 4) & 0xFF;
    return ((uint32_t)fs.freq * (uint32_t)temp) & 0xFFFFF;
}

static void tick16(void) {
    /* The modulation table. */
    if (!(fs.mod_flags & 0x80) && !(fs.wave_flags & 0x80)) {
        fs.mod_acc += fs.mod_freq;
        int step = (fs.mod_acc >> 12) != 0 || (fs.mod_flags & 0x40);
        fs.mod_acc &= 0xFFF;
        if (step) {
            static const int8_t delta[8] = { 0, 1, 2, 4, 0, -4, -2, -1 };
            uint8_t e = fs.mod_table[fs.mod_pos >> 1];
            int c = e == 4 ? 0 : fs.counter + delta[e];
            c &= 0x7F;
            fs.counter = c >= 64 ? c - 128 : c;
            fs.mod_pos = (fs.mod_pos + 1) & 63;
        }
    }
    /* The wave. */
    if (fs.wave_flags & 0x80) {
        fs.wave_acc = 0;
        fs.vol_out = fs.vol_gain < 32 ? fs.vol_gain : 32;
    } else {
        uint32_t old = fs.wave_acc;
        fs.wave_acc = (fs.wave_acc + wave_step()) & 0xFFFFFF;
        if (fs.wave_acc < old)          /* passed position 0 */
            fs.vol_out = fs.vol_gain < 32 ? fs.vol_gain : 32;
    }
}

/* Bring the envelopes, the modulation and the wave up to CPU cycle
   `upto`. They run whether or not sound is being made, since the CPU can
   read them back. */
static void run(uint64_t upto) {
    while (fs.now < upto) {
        fs.now++;
        if (!fds_sound_on) continue;
        envelope(fs.vol_ctrl, &fs.vol_gain, &fs.vol_timer);
        envelope(fs.mod_ctrl, &fs.mod_gain, &fs.mod_timer);
        if (--fs.tick <= 0) { fs.tick = 16; tick16(); }
    }
}

float fds_audio_step(uint64_t cycle) {
    run(cycle + 1);
    if (!fds_sound_on) return 0;
    if (!fs.write_mode) fs.held = fs.wave[fs.wave_acc >> 18] * fs.vol_out;
    static const float master[4] = { 1.0f, 2.0f / 3, 2.0f / 4, 2.0f / 5 };
    float x = (float)fs.held * master[fs.master];
    static float k = 0;
    if (k == 0) k = (float)(1 - exp(-2 * M_PI * LOWPASS_HZ / CPU_HZ));
    fs.filtered += (x - fs.filtered) * k;
    return fs.filtered * FDS_UNIT;
}

void fds_sound_write(uint16_t addr, uint8_t val) {
    run(cycles);
    if (addr >= 0x4040 && addr < 0x4080) {
        if (fs.write_mode) fs.wave[addr - 0x4040] = val & 0x3F;
        return;
    }
    switch (addr) {
    case 0x4080:
        fs.vol_ctrl = val;
        if (val & 0x80) fs.vol_gain = val & 0x3F;
        fs.vol_timer = env_period(val);
        break;
    case 0x4082: fs.freq = (uint16_t)((fs.freq & 0xF00) | val); break;
    case 0x4083:
        fs.freq = (uint16_t)((fs.freq & 0xFF) | (val & 0x0F) << 8);
        fs.wave_flags = val & 0xC0;
        if (val & 0x80) fs.wave_acc = 0;
        if (val & 0x40) {
            fs.vol_timer = env_period(fs.vol_ctrl);
            fs.mod_timer = env_period(fs.mod_ctrl);
        }
        break;
    case 0x4084:
        fs.mod_ctrl = val;
        if (val & 0x80) fs.mod_gain = val & 0x3F;
        fs.mod_timer = env_period(val);
        break;
    case 0x4085: fs.counter = (val & 0x40) ? (val & 0x7F) - 128 : val & 0x3F; break;
    case 0x4086: fs.mod_freq = (uint16_t)((fs.mod_freq & 0xF00) | val); break;
    case 0x4087:
        fs.mod_freq = (uint16_t)((fs.mod_freq & 0xFF) | (val & 0x0F) << 8);
        fs.mod_flags = val & 0xC0;
        if (val & 0x80) { fs.mod_acc = 0; fs.mod_pos &= ~1; }
        break;
    case 0x4088:
        if (fs.mod_flags & 0x80) {
            fs.mod_table[fs.mod_pos >> 1] = val & 7;
            fs.mod_pos = (fs.mod_pos + 2) & 63;
        }
        break;
    case 0x4089: fs.write_mode = val >> 7; fs.master = val & 3; break;
    case 0x408A: fs.env_speed = val; break;
    }
}

int fds_sound_read(uint16_t addr) {
    run(cycles);
    if (addr >= 0x4040 && addr < 0x4080)
        return 0x40 | fs.wave[fs.write_mode ? addr - 0x4040 : fs.wave_acc >> 18];
    switch (addr) {
    case 0x4090: return 0x40 | fs.vol_gain;
    case 0x4091: return (int)((fs.wave_acc >> 12) & 0xFF);
    case 0x4092: return 0x40 | fs.mod_gain;
    case 0x4097: return fs.counter & 0x7F;
    }
    return -1;
}

/* ---- The disk image and the RAM adapter -----------------------------
   (nesdev wiki "Family Computer Disk System", "FDS disk format", "FDS
   file format", "FDS BIOS")

   A .fds image: an optional 16-byte header ("FDS\x1a", the number of
   sides), then 65500 bytes per side, with the gaps and CRCs left out. A
   side is block 1 (disk info, 56 bytes: "*NINTENDO-HVC*" at 1, the boot
   file code at $19), block 2 (the file count), then per file block 3
   (16 bytes: number, ID, name, load address, size, type 0 PRG / 1 CHR /
   2 nametable) and block 4 (the data).

   Memory: 32 KB of RAM at $6000-$DFFF, the BIOS at $E000-$FFFF, 8 KB of
   CHR RAM. The RAM adapter's registers:
     $4020/1  timer reload (works with disk I/O off)
     $4022    timer: bit 1 on (loads the counter from the reload value),
              bit 0 repeat; ignored while $4023 bit 0 is clear
     $4023    bit 0 disk I/O (clear: timer off, its IRQ acknowledged,
              $4025 = $06), bit 1 sound I/O (clear: sound reset, silent)
     $4025    bit 3 nametable arrangement: 0 vertical mirroring, 1
              horizontal (the drive's bits come in a later step)
     $4030    read: bit 0 timer IRQ, bit 3 a copy of $4025 bit 3;
              acknowledges the timer IRQ
     $4032    read: drive status (a disk is in; not ready: no drive yet)
     $4033    read: bit 7 battery good
     $4028    not on the real hardware: requests from nesrecomp's BIOS
              (fds_bios.h), here the boot load
   The timer, once on, counts down one per CPU cycle; the cycle after it
   reads 0 it raises the IRQ and starts again from the reload value, or
   stops if repeat is off. (The wiki's "at 0 it raises an IRQ" could also
   mean a cycle sooner; fdsirqtests passes either way, and firing a
   cycle later fails it.) */
#include <stdio.h>
#include <stdlib.h>
#include "cart.h"
#include "mapper.h"
#include "event.h"
#include "ppu.h"
#include "apu.h"
#include "fds_bios.h"

#define SIDE_BYTES 65500
/* Registers the real hardware doesn't have, for the project's BIOS:
   SERVICE takes a request (BOOT_LOAD or one of the file routines); ARG
   takes the routine's A before it, and both ARG and RESULT_Y give back
   the routine's results after it. */
#define SERVICE 0x4028
#define ARG 0x4029
#define RESULT_Y 0x402A
enum { BOOT_LOAD = 1, LOAD_FILES, WRITE_FILE, CHECK_FILE_COUNT, ADJUST_FILE_COUNT,
       SET_FILE_COUNT1, SET_FILE_COUNT, GET_DISK_INFO };

static struct {
    uint8_t *image;                 /* the sides as they are now */
    uint8_t *orig;                  /* as the image file holds them */
    int sides, side;                /* side in the drive */
    int ejected;
    int insert_side, insert_wait;   /* a side change from a key */
    int changed;                    /* written since loading */
    uint8_t arg, res_a, res_y;      /* ARG, RESULT_Y */
    uint16_t reload, counter;
    uint8_t timer_on, repeat, irq;
    uint64_t timer_time;            /* the cycle the counter is at */
    uint8_t io, ctrl;               /* $4023, $4025 */
} fds;

static void fail(const char *path, const char *why) {
    fprintf(stderr, "%s: %s\n", path, why);
    exit(1);
}

/* Block offsets within a side: the file count (block 2) is at 56; files
   follow. Returns the number of files found (up to the count, stopping
   at anything that isn't a file header). */
struct fds_file { int number, id, type; uint16_t addr, size; const uint8_t *data; char name[9]; };

static int files_in(const uint8_t *s, struct fds_file *out, int max) {
    if (s[56] != 2) return 0;
    int count = s[57], n = 0, at = 58;
    while (n < count && n < max && at + 17 <= SIDE_BYTES && s[at] == 3) {
        struct fds_file *f = &out[n];
        f->number = s[at + 1];
        f->id = s[at + 2];
        memcpy(f->name, s + at + 3, 8);
        f->name[8] = 0;
        f->addr = (uint16_t)(s[at + 11] | s[at + 12] << 8);
        f->size = (uint16_t)(s[at + 13] | s[at + 14] << 8);
        f->type = s[at + 15];
        at += 16;
        if (s[at] != 4 || at + 1 + f->size > SIDE_BYTES) break;
        f->data = s + at + 1;
        at += 1 + f->size;
        n++;
    }
    return n;
}

static uint8_t *side_at(int side) { return fds.image + (size_t)side * SIDE_BYTES; }

static int side_files(int side, struct fds_file *out, int max) {
    return files_in(side_at(side), out, max);
}

void fds_load(const char *path, FILE *f) {
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *data = malloc((size_t)len);
    if (!data || fread(data, 1, (size_t)len, f) != (size_t)len) fail(path, "can't read the disk image");
    long skip = memcmp(data, "FDS\x1a", 4) ? 0 : 16;
    fds.sides = (int)((len - skip) / SIDE_BYTES);
    if (fds.sides < 1 || (len - skip) % SIDE_BYTES)
        fail(path, "not a whole number of 65500-byte disk sides");
    fds.image = data + skip;
    for (int i = 0; i < fds.sides; i++) {
        const uint8_t *s = fds.image + (size_t)i * SIDE_BYTES;
        if (s[0] != 1 || memcmp(s + 1, "*NINTENDO-HVC*", 14) || s[56] != 2)
            fail(path, "a disk side doesn't start with the standard disk info"
                       " and file count blocks");
    }
    fds.orig = malloc((size_t)fds.sides * SIDE_BYTES);
    memcpy(fds.orig, fds.image, (size_t)fds.sides * SIDE_BYTES);
    fds.side = 0;
    fds.insert_side = -1;
    /* The BIOS at $E000 of a 32 KB "PRG", so slots 0-2 ($8000-$DFFF) can
       point into the RAM instead. */
    cart.prg_size = 0x8000;
    cart.prg = calloc(1, cart.prg_size);
    memcpy(cart.prg + 0x6000, fds_bios, sizeof fds_bios);
    cart.prg_ram_size = 0x8000;
    cart.prg_ram_alloc = 0x8000;
    cart.prg_ram = calloc(1, cart.prg_ram_alloc);
    cart.chr_size = 0x2000;
    cart.chr_is_ram = 1;
    cart.chr = calloc(1, cart.chr_size);
    cart.mirroring = MIRROR_HORIZONTAL;
    cart.mapper = MAPPER_FDS;
    cart.battery = 0;
}

void fds_print_info(const char *path) {
    printf("%s\n  Famicom Disk System image, %d side(s)\n", path, fds.sides);
    static const char *type[] = { "PRG", "CHR", "nametable" };
    for (int i = 0; i < fds.sides; i++) {
        const uint8_t *s = side_at(i);
        struct fds_file files[256];
        int n = side_files(i, files, 256);
        printf("  side %d: \"%.3s\" version %d, side %c, boot files: IDs up to %d;"
               " %d of %d file(s)\n", i + 1, (const char *)s + 0x10, s[0x14],
               s[0x15] ? 'B' : 'A', s[0x19], n, s[57]);
        for (int k = 0; k < n; k++)
            printf("    %3d  ID %3d  %-8s  %-9s $%04X  %5u bytes\n", files[k].number,
                   files[k].id, files[k].name, type[files[k].type < 2 ? files[k].type : 2],
                   files[k].addr, files[k].size);
    }
}

/* ---- saving: a disk the program wrote to is kept in <image>.sav, the
   whole disk (every side, no header); the image itself is left alone ---- */

static void sav_path(char *out, size_t size, const char *rom_path) {
    snprintf(out, size, "%s.sav", rom_path);
}

void fds_load_save(const char *rom_path) {
    char path[1024];
    sav_path(path, sizeof path, rom_path);
    FILE *f = fopen(path, "rb");
    if (!f) return;
    size_t want = (size_t)fds.sides * SIDE_BYTES;
    uint8_t *buf = malloc(want + 1);
    size_t n = fread(buf, 1, want + 1, f);
    fclose(f);
    if (n != want) {
        fprintf(stderr, "%s: not %d disk side(s); ignored\n", path, fds.sides);
    } else {
        memcpy(fds.image, buf, want);
        fprintf(stderr, "loaded the disk as saved in %s\n", path);
    }
    free(buf);
}

void fds_write_save(const char *rom_path) {
    if (!fds.changed) return;
    char path[1024], tmp[1040];
    sav_path(path, sizeof path, rom_path);
    snprintf(tmp, sizeof tmp, "%s.tmp", path);
    FILE *f = fopen(tmp, "wb");
    if (!f) { perror(tmp); return; }
    size_t want = (size_t)fds.sides * SIDE_BYTES;
    int ok = fwrite(fds.image, 1, want, f) == want;
    ok &= fclose(f) == 0;
    if (ok && rename(tmp, path) == 0)
        fprintf(stderr, "saved the disk to %s\n", path);
    else
        perror(path);
}

/* ---- the drive: ejecting and inserting sides ---- */

static void say_side(void) {
    if (fds.ejected) fprintf(stderr, "disk: ejected\n");
    else fprintf(stderr, "disk: side %d in (disk %d side %c)\n", fds.side + 1,
                 fds.side / 2 + 1, 'A' + fds.side % 2);
}

int fds_sides(void) { return fds.sides; }

void fds_eject(void) {
    fds.ejected = 1;
    fds.insert_side = -1;
    say_side();
}

void fds_insert(int side) {
    if (side < 0 || side >= fds.sides) return;
    fds.side = side;
    fds.ejected = 0;
    fds.insert_side = -1;
    say_side();
}

/* From a key: 0 ejects; n ejects, then puts in side n half a second
   later, so the program sees the disk out. */
void fds_key(int n) {
    if (n > fds.sides) return;
    fds_eject();
    if (n > 0) { fds.insert_side = n - 1; fds.insert_wait = 30; }
}

void fds_frame(void) {
    if (fds.insert_side >= 0 && --fds.insert_wait <= 0) fds_insert(fds.insert_side);
}

/* ---- files ---- */

/* Files are numbered for code_owner (rt.h) as the recompiler numbers
   them: every file of every side of the image file, in disk order, from
   FDS_FIRST_TAG; 0 (untranslated) past 255, and for a file that isn't
   the image file's any more (the program wrote it, or a .sav did). */
int fds_file_tag(int side, int index) {
    static struct fds_file was[256], now[256];
    int tag = FDS_FIRST_TAG;
    for (int i = 0; i < side; i++) tag += files_in(fds.orig + (size_t)i * SIDE_BYTES, was, 256);
    int n = files_in(fds.orig + (size_t)side * SIDE_BYTES, was, 256);
    int m = side_files(side, now, 256);
    if (index >= n || index >= m) return 0;
    const struct fds_file *a = &was[index], *b = &now[index];
    if (a->addr != b->addr || a->size != b->size || a->type != b->type ||
        memcmp(a->data, b->data, a->size))
        return 0;
    tag += index;
    return tag <= 255 ? tag : 0;
}

int fds_code_banks(void) {
    static struct fds_file files[256];
    int tag = FDS_FIRST_TAG;
    for (int i = 0; i < fds.sides; i++) tag += files_in(fds.orig + (size_t)i * SIDE_BYTES, files, 256);
    return tag < 256 ? tag : 256;
}

/* Load one file as LoadFiles does: PRG files through the CPU's bus (so a
   file loaded to $2000 writes PPUCTRL), CHR and nametable files into
   PPU memory. A "dummy load" writes nothing: a file that would run past
   $FFFF, or a PRG file loaded below $2000 except to $0200-$07FF (or its
   mirror $1200-$17FF), as the wiki describes the real BIOS. */
static void load_file(const struct fds_file *f, int side, int index) {
    if ((uint32_t)f->addr + f->size > 0x10000) return;
    if (f->type == 0) {
        uint16_t a = f->addr;
        if (a < 0x2000 && !((a >= 0x0200 && a < 0x0800) || (a >= 0x1200 && a < 0x1800)))
            return;
        for (unsigned i = 0; i < f->size; i++) wr((uint16_t)(a + i), f->data[i]);
        /* The RAM now holds this file's bytes, as translated. */
        code_owner_set(a, f->size, (uint8_t)fds_file_tag(side, index));
    } else {
        for (unsigned i = 0; i < f->size; i++)
            ppu_mem_write((f->addr + i) & 0x3FFF, f->data[i]);
    }
}

/* LoadFiles' choice of files: the IDs in a list of up to 20 that ends
   with $FF, or with the list empty (just $FF) every file whose ID is at
   most the side's boot code. In disk order. Returns how many. */
static int load_files(int boot, uint16_t list) {
    struct fds_file files[256];
    int n = side_files(fds.side, files, 256), loaded = 0;
    const uint8_t *s = side_at(fds.side);
    uint8_t ids[20];
    int len = 0;
    while (!boot && len < 20 && (ids[len] = peek((uint16_t)(list + len))) != 0xFF) len++;
    for (int k = 0; k < n; k++) {
        int match = 0;
        if (len == 0) match = files[k].id <= s[0x19];
        for (int i = 0; i < len; i++) match |= files[k].id == ids[i];
        if (!match) continue;
        load_file(&files[k], fds.side, k);
        loaded++;
    }
    return loaded;
}

/* The boot: LoadFiles with the empty list. */
static void boot_load(void) {
    if (!fds.ejected) load_files(1, 0);
}
/* ---- the BIOS's file routines (nesdev wiki "FDS BIOS"), done here
   against the disk image, at once ----
   The BIOS's entry points ask for them through SERVICE, after storing
   A in ARG (see tools/make_fds_bios.py). Their pointers come after the
   JSR, so the return address on the stack is moved past them. Each
   gives back an error number in A (0: none). */

static int disk_check(uint16_t id) {
    if (fds.ejected) return 0x01;                   /* no disk */
    const uint8_t *s = side_at(fds.side);
    if (memcmp(s + 1, "*NINTENDO-HVC*", 14)) return 0x21;
    /* The 10 bytes of the disk ID against disk info $0F-$18, field by
       field; $FF in the expected ID skips a byte. */
    static const uint8_t err[10] = { 0x04, 0x05, 0x05, 0x05, 0x05, 0x06, 0x07, 0x08, 0x09, 0x10 };
    for (int i = 0; i < 10; i++) {
        uint8_t want = peek((uint16_t)(id + i));
        if (want != 0xFF && want != s[0x0F + i]) return err[i];
    }
    return 0;
}

static void set_count(int n) {
    uint8_t *s = side_at(fds.side);
    if (s[57] != n) { s[57] = (uint8_t)n; fds.changed = 1; }
}

/* WriteFile: the file the header describes, as file `pos` of the side
   ($FF: after the last, AppendFile). The side's count becomes pos + 1,
   hiding any files after it. */
static int write_file(int pos, uint16_t hdr) {
    uint8_t *s = side_at(fds.side);
    struct fds_file files[256];
    int n = side_files(fds.side, files, 256);
    if (pos == 0xFF) pos = n;
    if (pos > n) return 0x24;                       /* no such file to write over */
    size_t at = pos < n ? (size_t)(files[pos].data - s) - 17
                        : n ? (size_t)(files[n - 1].data - s) + files[n - 1].size : 58;
    uint16_t size = (uint16_t)(peek((uint16_t)(hdr + 0x0B)) | peek((uint16_t)(hdr + 0x0C)) << 8);
    if (at + 17 + size > SIDE_BYTES) return 0x29;   /* the disk is full */
    s[at] = 3;
    s[at + 1] = (uint8_t)pos;
    for (int i = 0; i < 14; i++) s[at + 2 + i] = peek((uint16_t)(hdr + i));
    s[at + 16] = 4;
    uint16_t src = (uint16_t)(peek((uint16_t)(hdr + 0x0E)) | peek((uint16_t)(hdr + 0x0F)) << 8);
    int vram = peek((uint16_t)(hdr + 0x10)) != 0;
    for (unsigned i = 0; i < size; i++)
        s[at + 17 + i] = vram ? ppu_mem_read((src + i) & 0x3FFF) : peek((uint16_t)(src + i));
    memset(s + at + 17 + size, 0, SIDE_BYTES - (at + 17 + size));
    s[57] = (uint8_t)(pos + 1);
    fds.changed = 1;
    return 0;
}

/* GetDiskInfo: the disk ID, the file count, each file's ID and name,
   then the disk's size (high byte first): every file's size plus 261. */
static void disk_info(uint16_t out) {
    const uint8_t *s = side_at(fds.side);
    struct fds_file files[256];
    int n = side_files(fds.side, files, 256);
    for (int i = 0; i < 10; i++) wr(out++, s[0x0F + i]);
    wr(out++, (uint8_t)n);
    unsigned total = 0;
    for (int k = 0; k < n; k++) {
        wr(out++, (uint8_t)files[k].id);
        for (int i = 0; i < 8; i++) wr(out++, (uint8_t)files[k].name[i]);
        total += files[k].size + 261u;
    }
    wr(out++, (uint8_t)(total >> 8));
    wr(out, (uint8_t)total);
}

static void file_routine(int code) {
    /* The pointers after the JSR: the return address on the stack is the
       JSR's last byte. */
    static const int pointers[] = { [LOAD_FILES] = 2, [WRITE_FILE] = 2,
        [CHECK_FILE_COUNT] = 1, [ADJUST_FILE_COUNT] = 1, [SET_FILE_COUNT1] = 1,
        [SET_FILE_COUNT] = 1, [GET_DISK_INFO] = 1 };
    uint16_t lo = 0x100 | (uint8_t)(SP + 1), hi = 0x100 | (uint8_t)(SP + 2);
    uint16_t ret = (uint16_t)(peek(lo) | peek(hi) << 8), p[2] = { 0, 0 };
    for (int i = 0; i < pointers[code]; i++) {
        uint16_t at = (uint16_t)(ret + 1 + 2 * i);
        p[i] = (uint16_t)(peek(at) | peek((uint16_t)(at + 1)) << 8);
    }
    ret = (uint16_t)(ret + 2 * pointers[code]);
    wr(lo, (uint8_t)ret);
    wr(hi, (uint8_t)(ret >> 8));

    uint8_t a = fds.arg;
    int err = 0, count = side_at(fds.side)[57];
    if (code == GET_DISK_INFO) {
        if (fds.ejected) err = 0x01;
        else disk_info(p[0]);
    } else if ((err = disk_check(p[0])) == 0) {
        switch (code) {
        case LOAD_FILES: fds.res_y = (uint8_t)load_files(0, p[1]); break;
        case WRITE_FILE: err = write_file(a, p[1]); break;
        case CHECK_FILE_COUNT:
            if (a > count) err = 0x31;
            else set_count(a);
            break;
        case ADJUST_FILE_COUNT:
            if (a > count) err = 0x31;
            else set_count(count - a);
            break;
        case SET_FILE_COUNT1: set_count((a + 1) & 0xFF); break;
        case SET_FILE_COUNT: set_count(a); break;
        }
    }
    if (code == LOAD_FILES && err) fds.res_y = 0;
    fds.res_a = (uint8_t)err;
}

/* ---- the timer IRQ ---- */

static void timer_catch_up(void) {
    uint64_t now = cycles;
    if (fds.timer_on && now > fds.timer_time) {
        uint64_t n = now - fds.timer_time;
        if (n > fds.counter) {
            /* It fires on the cycle after reading 0. */
            uint64_t fire = fds.timer_time + fds.counter;
            n -= (uint64_t)fds.counter + 1;
            if (fds.repeat) {
                uint64_t period = (uint64_t)fds.reload + 1;
                fire += n / period * period;
                fds.counter = (uint16_t)(fds.reload - n % period);
            } else {
                fds.timer_on = 0;
                fds.counter = fds.reload;
            }
            fds.irq = 1;
            cpu_set_irq_at(IRQ_MAPPER, 1, fire * 3);
        } else {
            fds.counter = (uint16_t)(fds.counter - n);
        }
    }
    fds.timer_time = now;
}

static void timer_schedule(void) {
    if (fds.timer_on) schedule_event(fds.timer_time + fds.counter + 1);
}

static void timer_ack(void) {
    fds.irq = 0;
    cpu_set_irq(IRQ_MAPPER, 0);
}

/* ---- the registers ---- */

void fds_write_low(uint16_t addr, uint8_t val) {
    if (addr >= 0x4040 && addr <= 0x408A) {
        if (fds.io & 2) { apu_catch_up(); fds_sound_write(addr, val); }
        return;
    }
    timer_catch_up();
    switch (addr) {
    case 0x4020: fds.reload = (uint16_t)((fds.reload & 0xFF00) | val); break;
    case 0x4021: fds.reload = (uint16_t)((fds.reload & 0x00FF) | val << 8); break;
    case 0x4022:
        if (!(fds.io & 1)) break;
        fds.repeat = val & 1;
        fds.timer_on = (val >> 1) & 1;
        if (fds.timer_on) fds.counter = fds.reload;
        else timer_ack();
        break;
    case 0x4023:
        if (!(val & 1)) {
            /* Disk I/O off: the timer stops, and $4025 becomes $06. */
            fds.timer_on = 0;
            timer_ack();
            fds.ctrl = 0x06;
            ppu_catch_up();
            cart.mirroring = MIRROR_VERTICAL;
        }
        if ((fds.io & 2) && !(val & 2)) { apu_catch_up(); fds_sound_reset(); }
        fds.io = val;
        apu_catch_up();
        fds_sound_on = (val >> 1) & 1;
        break;
    case 0x4025:
        if (!(fds.io & 1)) break;
        fds.ctrl = val;
        ppu_catch_up();
        cart.mirroring = (val & 8) ? MIRROR_HORIZONTAL : MIRROR_VERTICAL;
        break;
    case SERVICE:
        if (val == BOOT_LOAD) boot_load();
        else if (val >= LOAD_FILES && val <= GET_DISK_INFO) file_routine(val);
        break;
    case ARG: fds.arg = val; break;
    }
    timer_schedule();
}

int fds_read_low(uint16_t addr) {
    if (addr >= 0x4040 && addr <= 0x4097) {
        apu_catch_up();
        return fds_sound_read(addr);
    }
    switch (addr) {
    case 0x4030: {
        timer_catch_up();
        int v = fds.irq | (fds.ctrl & 8);
        timer_ack();
        timer_schedule();
        return v;
    }
    /* A disk in, not ready (the drive isn't modelled yet); ejected:
       bit 0 no disk, bit 2 "write protected" too, as the wiki says. */
    case 0x4032: return fds.ejected ? 0x40 | 0x07 : 0x40 | 0x02;
    case ARG: return fds.res_a;
    case RESULT_Y: return fds.res_y;
    case 0x4033: return 0x80;           /* battery good */
    }
    return -1;
}

/* CPU writes to $8000-$FFFF: RAM below $E000; the BIOS is ROM. */
void fds_write(uint16_t addr, uint8_t val) {
    if (addr < 0xE000) code_ram_write(&mapper.prg[(addr >> 13) & 3][addr & 0x1FFF], addr, val);
}

void fds_reset(void) {
    for (int s = 0; s < 3; s++) {
        mapper.prg[s] = cart.prg_ram + 0x2000 + s * 0x2000;
        mapper.prg_bank[s] = s;
    }
    mapper.prg[3] = cart.prg + 0x6000;
    mapper.prg_bank[3] = 3;
    mapper.ram6000 = cart.prg_ram;
    mapper.ram6000_size = 0x2000;
    fds.reload = fds.counter = 0;
    fds.timer_on = fds.repeat = fds.irq = 0;
    fds.io = 0;
    fds.ctrl = 0x06;
    fds.timer_time = cycles;
    fds_sound_reset();
    fds_sound_on = 0;
    mapper.catch_up = timer_catch_up;
    mapper.schedule = timer_schedule;
    mapper.audio_step = fds_audio_step;
}
