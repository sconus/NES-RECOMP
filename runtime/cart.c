/* nesrecomp runtime: iNES loader. Bank switching lives in mapper.c. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cart.h"
#include "nsf.h"

struct cart cart;

static void fail(const char *path, const char *why) {
    fprintf(stderr, "%s: %s\n", path, why);
    exit(1);
}

/* A ROM size from an NES 2.0 header: the LSB byte and the 4-bit MSB in
   `unit`s, or, when the MSB is $F, the exponent form EEEEEEMM: 2^E x
   (MM*2+1) bytes. */
static size_t rom_size(const char *path, int lsb, int msb, size_t unit) {
    if (msb == 0xF) {
        int e = lsb >> 2, mm = lsb & 3;
        if (e > 30) fail(path, "ROM size in the header is too large");
        return ((size_t)1 << e) * (size_t)(mm * 2 + 1);
    }
    return (size_t)(msb << 8 | lsb) * unit;
}

/* A RAM size nibble from bytes 10-11: 0 for none, else 64 << n. */
static size_t ram_size(int shift) { return shift ? (size_t)64 << shift : 0; }

/* Read an iNES header as iNES 1.0 or NES 2.0 (nesdev wiki "NES 2.0",
   "INES"), the same way recomp.py's read_header does;
   tests/check_headers.py compares the two. */
static void read_header(const char *path, const uint8_t *h, long file_size) {
    cart.battery = (h[6] & 2) != 0;
    cart.mirroring = (h[6] & 8) ? MIRROR_FOUR_SCREEN
                   : (h[6] & 1) ? MIRROR_VERTICAL : MIRROR_HORIZONTAL;
    long head = 16 + ((h[6] & 4) ? 512 : 0);
    cart.nes2 = (h[7] & 0x0C) == 0x08;
    size_t prg = 0, chr = 0;
    if (cart.nes2) {
        prg = rom_size(path, h[4], h[9] & 0x0F, 0x4000);
        chr = rom_size(path, h[5], h[9] >> 4, 0x2000);
        if ((double)head + prg + chr > (double)file_size)
            cart.nes2 = 0;                      /* the wiki: then not NES 2.0 */
    }
    int clean = cart.nes2 || !(h[12] | h[13] | h[14] | h[15]);
    cart.mapper = (h[6] >> 4) | (h[7] & 0xF0);
    cart.submapper = 0;
    cart.console = clean ? h[7] & 3 : 0;
    cart.console_ext = cart.timing = cart.misc_roms = cart.exp_device = 0;
    if (cart.nes2) {
        cart.mapper |= (h[8] & 0x0F) << 8;
        cart.submapper = h[8] >> 4;
        cart.prg_size = prg;
        cart.chr_size = chr;
        cart.prg_ram_size = ram_size(h[10] & 0x0F);
        cart.prg_nvram_size = ram_size(h[10] >> 4);
        cart.chr_ram_size = ram_size(h[11] & 0x0F);
        cart.chr_nvram_size = ram_size(h[11] >> 4);
        cart.timing = h[12] & 3;
        cart.misc_roms = h[14] & 3;
        cart.exp_device = h[15] & 0x7F;
        if (cart.console == 1 || cart.console == 3) cart.console_ext = h[13];
    } else {
        if (!clean) cart.mapper &= 0x0F;        /* junk in old dumps */
        cart.prg_size = (size_t)h[4] * 0x4000;
        cart.chr_size = (size_t)h[5] * 0x2000;
        cart.prg_ram_size = cart.battery ? 0 : 0x2000;
        cart.prg_nvram_size = cart.battery ? 0x2000 : 0;
        cart.chr_ram_size = h[5] ? 0 : 0x2000;
        cart.chr_nvram_size = 0;
    }
    cart.chr_rom_size = cart.chr_size;
    if (cart.prg_size == 0) fail(path, "header lists no PRG ROM");
    if (cart.prg_size % 0x2000)
        fail(path, "PRG ROM is not a whole number of 8 KB banks");
    if (cart.chr_size % 0x400)
        fail(path, "CHR ROM is not a whole number of 1 KB banks");
    /* What the runtime reads but doesn't model. */
    static const char *timing[] = { "NTSC", "PAL", "multi-region", "Dendy" };
    if (cart.timing == 1 || cart.timing == 3)
        fprintf(stderr, "%s: made for a %s console; it runs at NTSC speed\n",
                path, timing[cart.timing]);
    static const char *console[] = { "NES/Famicom", "Vs. System",
                                     "PlayChoice-10", "extended console type" };
    if (cart.console)
        fprintf(stderr, "%s: made for a %s, run as an NES\n",
                path, console[cart.console]);
    if (cart.misc_roms)
        fprintf(stderr, "%s: %d extra ROM(s) after CHR ROM are ignored\n",
                path, cart.misc_roms);
}

/* Allocate the $6000 RAM the header declared (at least 8 KB, so the
   $6000 protocol readers and MMC5's first bank always have memory). */
static void alloc_prg_ram(void) {
    size_t n = cart.prg_ram_size + cart.prg_nvram_size;
    cart.prg_ram_alloc = n < 0x2000 ? 0x2000 : n;
    cart.prg_ram = calloc(1, cart.prg_ram_alloc);
}

void cart_load(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); exit(1); }
    uint8_t h[16];
    if (fread(h, 1, 16, f) != 16) fail(path, "not an iNES or NSF file");
    if (!memcmp(h, "NESM\x1a", 5)) {            /* an NSF music file */
        nsf_load(path, f);
        fclose(f);
        cart.prg_ram_size = 0x2000;             /* NSF players have 8 KB */
        alloc_prg_ram();
        return;
    }
    if (memcmp(h, "NES\x1a", 4)) fail(path, "not an iNES or NSF file");
    fseek(f, 0, SEEK_END);
    long file_size = ftell(f);
    fseek(f, 16, SEEK_SET);
    read_header(path, h, file_size);
    if (h[6] & 4) fseek(f, 512, SEEK_CUR);      /* skip the trainer */

    cart.prg = malloc(cart.prg_size);
    if (fread(cart.prg, 1, cart.prg_size, f) != cart.prg_size)
        fail(path, "truncated PRG data");

    alloc_prg_ram();
    /* Without CHR ROM: the CHR RAM the header declares (iNES 1.0: 8 KB),
       at least 1 KB (the smallest bank), mirrored by the mapper's bank
       arithmetic. With neither, 8 KB of zeros that can't be written. */
    int no_chr = cart.chr_size == 0;
    if (no_chr) {
        size_t ram = cart.chr_ram_size + cart.chr_nvram_size;
        cart.chr_is_ram = ram != 0;
        cart.chr_size = !ram ? 0x2000 : ram < 0x400 ? 0x400 : ram;
    } else {
        cart.chr_is_ram = 0;
    }
    cart.chr = calloc(1, cart.chr_size);
    if (!cart.chr_is_ram && !no_chr &&
        fread(cart.chr, 1, cart.chr_size, f) != cart.chr_size)
        fail(path, "truncated CHR data");
    fclose(f);
}

/* Battery-backed carts keep their NVRAM (the part of the $6000 RAM after
   the plain RAM; iNES 1.0: all 8 KB) when switched off; we keep it in
   <rom>.sav next to the ROM. */
static void save_path(char *out, size_t size, const char *rom_path) {
    snprintf(out, size, "%s.sav", rom_path);
}

void cart_load_save(const char *rom_path) {
    char path[1024];
    save_path(path, sizeof path, rom_path);
    FILE *f = fopen(path, "rb");
    if (!f) return;                 /* first run: nothing saved yet */
    size_t n = fread(cart.prg_ram + cart.prg_ram_size, 1, cart.prg_nvram_size, f);
    fclose(f);
    fprintf(stderr, "loaded %zu bytes of saved RAM from %s\n", n, path);
}

void cart_write_save(const char *rom_path) {
    char path[1024], tmp[1040];
    save_path(path, sizeof path, rom_path);
    /* Write a temporary file, then rename: a crash mid-write can't leave
       a half-written save behind. */
    snprintf(tmp, sizeof tmp, "%s.tmp", path);
    FILE *f = fopen(tmp, "wb");
    if (!f) { perror(tmp); return; }
    int ok = fwrite(cart.prg_ram + cart.prg_ram_size, 1, cart.prg_nvram_size, f)
             == cart.prg_nvram_size;
    ok &= fclose(f) == 0;
    if (ok && rename(tmp, path) == 0)
        fprintf(stderr, "saved RAM to %s\n", path);
    else
        perror(path);
}

/* A size for --info: "8 KB", "512 bytes" or "none". */
static const char *size_text(char *buf, size_t n) {
    if (!n) return "none";
    if (n % 1024) snprintf(buf, 24, "%zu bytes", n);
    else snprintf(buf, 24, "%zu KB", n / 1024);
    return buf;
}

/* The default expansion devices (byte 15) the runtime has, by name; the
   rest aren't supported. main.c plugs these in when no input option is
   given. */
const char *cart_device_name(int d) {
    switch (d) {
    case 0x00: return "unspecified";
    case 0x01: return "standard controllers";
    case 0x02: return "Four Score";
    case 0x03: return "Famicom four players";
    case 0x08: return "Zapper on $4017";
    case 0x0F: return "Arkanoid paddle (NES)";
    case 0x10: return "Arkanoid paddle (Famicom)";
    case 0x49: return "Zapper on $4016";
    default:   return "not supported: standard controllers";
    }
}

void cart_print_info(const char *path) {
    if (cart.mapper == MAPPER_NSF) { nsf_print_info(path); return; }
    static const char *mir[] = { "horizontal", "vertical", "four-screen",
                                 "single-screen", "single-screen" };
    static const char *timing[] = { "NTSC", "PAL", "multi-region", "Dendy" };
    static const char *console[] = { "NES/Famicom", "Vs. System",
                                     "PlayChoice-10", "extended" };
    char a[24], b[24], c[24], d[24], e[24], g[24];
    printf("%s\n  mapper %d, PRG %s, CHR %s %s, %s mirroring%s\n",
           path, cart.mapper, size_text(a, cart.prg_size),
           size_text(b, cart.chr_size),
           cart.chr_is_ram ? "RAM" : cart.chr_rom_size ? "ROM" : "(none)",
           mir[cart.mirroring],
           cart.battery ? ", battery" : "");
    printf("  %s header: submapper %d\n", cart.nes2 ? "NES 2.0" : "iNES 1.0",
           cart.submapper);
    printf("  PRG ROM %s, CHR ROM %s; PRG RAM %s, PRG NVRAM %s, CHR RAM %s,"
           " CHR NVRAM %s\n",
           size_text(a, cart.prg_size), size_text(b, cart.chr_rom_size),
           size_text(c, cart.prg_ram_size), size_text(d, cart.prg_nvram_size),
           size_text(e, cart.chr_ram_size), size_text(g, cart.chr_nvram_size));
    printf("  timing %s, console %s (byte 13 $%02X), extra ROMs %d,"
           " expansion device $%02X (%s)\n",
           timing[cart.timing], console[cart.console], cart.console_ext,
           cart.misc_roms, cart.exp_device, cart_device_name(cart.exp_device));
}
