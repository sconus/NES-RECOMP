/* nesrecomp runtime: NSF music files (see nsf.h). */
#include <stdlib.h>
#include <string.h>
#include "nsf.h"
#include "cart.h"
#include "mapper.h"
#include "rt.h"

struct nsf nsf;

#define CPU_HZ 1789772.727          /* NTSC: 21.477 MHz / 12 */
#define PLAY_DUE 0x41F0             /* driver register: is play due? */

static void fail(const char *path, const char *why) {
    fprintf(stderr, "%s: %s\n", path, why);
    exit(1);
}

static void copy_text(char *out, const uint8_t *in) {
    memcpy(out, in, 32);
    out[32] = 0;
}

void nsf_load(const char *path, FILE *f) {
    uint8_t h[0x80];
    if (fseek(f, 0, SEEK_SET) || fread(h, 1, sizeof h, f) != sizeof h)
        fail(path, "truncated NSF header");
    nsf.songs = h[6] ? h[6] : 1;
    nsf.start_song = h[7] >= 1 && h[7] <= nsf.songs ? h[7] : 1;
    nsf.load = (uint16_t)(h[8] | h[9] << 8);
    nsf.init = (uint16_t)(h[0x0A] | h[0x0B] << 8);
    nsf.play = (uint16_t)(h[0x0C] | h[0x0D] << 8);
    copy_text(nsf.title, h + 0x0E);
    copy_text(nsf.artist, h + 0x2E);
    copy_text(nsf.copyright, h + 0x4E);
    nsf.speed_ntsc = (unsigned)(h[0x6E] | h[0x6F] << 8);
    memcpy(nsf.banks, h + 0x70, 8);
    nsf.pal_flags = h[0x7A];
    nsf.chips = h[0x7B];

    nsf.banked = 0;
    for (int i = 0; i < 8; i++) nsf.banked |= nsf.banks[i] != 0;
    if (nsf.banked) {
        /* The whole file, cut into 4 KB banks; the first bank starts at
           the load address's offset within 4 KB. */
        long here = ftell(f);
        fseek(f, 0, SEEK_END);
        long len = ftell(f) - here;
        fseek(f, here, SEEK_SET);
        if (len <= 0) fail(path, "NSF has no program data");
        size_t off = nsf.load & 0xFFF;
        cart.prg_size = (off + (size_t)len + 0xFFF) & ~(size_t)0xFFF;
        cart.prg = calloc(1, cart.prg_size);
        if (fread(cart.prg + off, 1, (size_t)len, f) != (size_t)len)
            fail(path, "truncated NSF data");
    } else {
        if (nsf.load < 0x8000) fail(path, "NSF loads below $8000");
        cart.prg_size = 0x8000;
        cart.prg = calloc(1, cart.prg_size);
        size_t room = 0x10000 - nsf.load;
        size_t n = fread(cart.prg + (nsf.load - 0x8000), 1, room, f);
        if (n == 0) fail(path, "NSF has no program data");
    }
    cart.chr_size = 0x2000;
    cart.chr_is_ram = 1;
    cart.chr = calloc(1, cart.chr_size);
    cart.mirroring = MIRROR_HORIZONTAL;
    cart.mapper = MAPPER_NSF;
    cart.battery = 0;
}

void nsf_print_info(const char *path) {
    printf("%s\n  NSF: \"%s\" by %s (%s)\n"
           "  %d song(s), starting at %d; load $%04X, init $%04X, play $%04X\n"
           "  play every %u us%s%s%s%s\n",
           path, nsf.title, nsf.artist, nsf.copyright, nsf.songs,
           nsf.start_song, nsf.load, nsf.init, nsf.play,
           nsf.speed_ntsc ? nsf.speed_ntsc : 16639,
           nsf.speed_ntsc ? "" : " (the header says 0: using 60 Hz)",
           nsf.pal_flags & 1 ? ", PAL" : "",
           nsf.banked ? ", bank switched" : "",
           nsf.chips ? ", uses expansion sound" : "");
}

/* The driver, assembled by hand. SONG is patched in by nsf_start. */
static uint8_t driver[0x80];
static uint64_t play_period, next_play;

static int put(int at, const uint8_t *b, int n) {
    memcpy(driver + at, b, (size_t)n);
    return at + n;
}

uint16_t nsf_start(int song) {
    if (song < 1 || song > nsf.songs) song = nsf.start_song;
    int p = 0;
    const uint8_t clear[] = {
        0xA9, 0x00,                 /* LDA #0                           */
        0xA2, 0x13,                 /* LDX #$13                         */
        0x9D, 0x00, 0x40,           /* STA $4000,X  (sound registers)   */
        0xCA,                       /* DEX                              */
        0x10, 0xFA,                 /* BPL back                         */
        0xA9, 0x0F, 0x8D, 0x15, 0x40, /* LDA #$0F; STA $4015            */
        0xA9, 0x40, 0x8D, 0x17, 0x40, /* LDA #$40; STA $4017            */
    };
    p = put(p, clear, sizeof clear);
    if (nsf.banked)                 /* the header's starting banks */
        for (int i = 0; i < 8; i++) {
            const uint8_t set[] = { 0xA9, nsf.banks[i],     /* LDA #bank */
                                    0x8D, (uint8_t)(0xF8 + i), 0x5F };
            p = put(p, set, sizeof set);                    /* STA $5FF8+i */
        }
    const uint8_t call_init[] = {
        0xA9, (uint8_t)(song - 1),  /* LDA #song (from 0)               */
        0xA2, 0x00,                 /* LDX #0 (NTSC)                    */
        0x20, (uint8_t)nsf.init, (uint8_t)(nsf.init >> 8),  /* JSR init */
    };
    p = put(p, call_init, sizeof call_init);
    uint16_t wait = (uint16_t)(NSF_DRIVER + p);
    const uint8_t loop[] = {
        0xAD, (uint8_t)PLAY_DUE, (uint8_t)(PLAY_DUE >> 8),  /* LDA due  */
        0xF0, 0xFB,                 /* BEQ back                         */
        0x20, (uint8_t)nsf.play, (uint8_t)(nsf.play >> 8),  /* JSR play */
        0x4C, (uint8_t)wait, (uint8_t)(wait >> 8),          /* JMP wait */
    };
    p = put(p, loop, sizeof loop);

    unsigned us = nsf.speed_ntsc ? nsf.speed_ntsc : 16639;
    play_period = (uint64_t)(us * CPU_HZ / 1e6 + 0.5);
    next_play = cycles + play_period;
    return NSF_DRIVER;
}

/* Bank switching. The CPU reads $8000-$FFFF through four 8 KB slots
   (mapper.prg), but here each 4 KB half can hold any bank, so the
   program is read through a 32 KB copy, refreshed 4 KB at a time. */
static uint8_t window[0x8000];

static void set_slot_4k(int slot, int bank) {
    int count = (int)(cart.prg_size / 0x1000);
    bank %= count;
    if (mapper.prg_bank_4k[slot] != bank) mapper.bank_changed = 1;
    mapper.prg_bank_4k[slot] = bank;
    memcpy(window + slot * 0x1000, cart.prg + (size_t)bank * 0x1000, 0x1000);
}

void nsf_mapper_reset(void) {
    if (!nsf.banked) return;
    mapper.code_4k = 1;
    for (int s = 0; s < 4; s++) {
        mapper.prg[s] = window + s * 0x2000;
        mapper.prg_bank[s] = s;
    }
    /* Banks in order until the driver writes the header's starting
       banks to $5FF8-$5FFF, before init, as a hardware player does. */
    for (int s = 0; s < 8; s++) {
        mapper.prg_bank_4k[s] = -1;
        set_slot_4k(s, s);
    }
}

int nsf_read_low(uint16_t addr) {
    if (addr == PLAY_DUE) {
        /* The play timer ticks on a fixed grid; ticks missed while play
           was running late are merged into one. */
        if (cycles < next_play) return 0;
        while (next_play <= cycles) next_play += play_period;
        return 1;
    }
    if (addr >= NSF_DRIVER && addr < NSF_DRIVER + sizeof driver)
        return driver[addr - NSF_DRIVER];
    return -1;
}

void nsf_write_low(uint16_t addr, uint8_t val) {
    if (nsf.banked && addr >= 0x5FF8) set_slot_4k(addr - 0x5FF8, val);
}
