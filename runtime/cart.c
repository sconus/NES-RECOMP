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

void cart_load(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); exit(1); }
    uint8_t h[16];
    if (fread(h, 1, 16, f) != 16) fail(path, "not an iNES or NSF file");
    if (!memcmp(h, "NESM\x1a", 5)) {            /* an NSF music file */
        nsf_load(path, f);
        fclose(f);
        return;
    }
    if (memcmp(h, "NES\x1a", 4)) fail(path, "not an iNES or NSF file");

    cart.mapper = (h[6] >> 4) | (h[7] & 0xF0);
    if ((h[7] & 0x0C) == 0x08)                  /* NES 2.0 header */
        cart.mapper |= (h[8] & 0x0F) << 8;
    else if (h[12] | h[13] | h[14] | h[15])     /* junk in old dumps */
        cart.mapper &= 0x0F;
    cart.mirroring = (h[6] & 8) ? MIRROR_FOUR_SCREEN
                   : (h[6] & 1) ? MIRROR_VERTICAL : MIRROR_HORIZONTAL;
    cart.battery = (h[6] & 2) != 0;
    if (h[6] & 4) fseek(f, 512, SEEK_CUR);      /* skip the trainer */

    cart.prg_size = (size_t)h[4] * 0x4000;
    if (cart.prg_size == 0) fail(path, "header lists no PRG ROM");
    cart.prg = malloc(cart.prg_size);
    if (fread(cart.prg, 1, cart.prg_size, f) != cart.prg_size)
        fail(path, "truncated PRG data");

    cart.chr_size = (size_t)h[5] * 0x2000;
    cart.chr_is_ram = cart.chr_size == 0;
    if (cart.chr_is_ram) cart.chr_size = 0x2000;
    cart.chr = calloc(1, cart.chr_size);
    if (!cart.chr_is_ram &&
        fread(cart.chr, 1, cart.chr_size, f) != cart.chr_size)
        fail(path, "truncated CHR data");
    fclose(f);
}

/* Battery-backed carts keep the 8 KB at $6000-$7FFF when switched off;
   we keep it in <rom>.sav next to the ROM. */
static void save_path(char *out, size_t size, const char *rom_path) {
    snprintf(out, size, "%s.sav", rom_path);
}

void cart_load_save(const char *rom_path) {
    char path[1024];
    save_path(path, sizeof path, rom_path);
    FILE *f = fopen(path, "rb");
    if (!f) return;                 /* first run: nothing saved yet */
    size_t n = fread(cart.prg_ram, 1, sizeof cart.prg_ram, f);
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
    int ok = fwrite(cart.prg_ram, 1, sizeof cart.prg_ram, f) == sizeof cart.prg_ram;
    ok &= fclose(f) == 0;
    if (ok && rename(tmp, path) == 0)
        fprintf(stderr, "saved RAM to %s\n", path);
    else
        perror(path);
}

void cart_print_info(const char *path) {
    if (cart.mapper == MAPPER_NSF) { nsf_print_info(path); return; }
    static const char *mir[] = { "horizontal", "vertical", "four-screen",
                                 "single-screen", "single-screen" };
    printf("%s\n  mapper %d, PRG %zu KB, CHR %zu KB %s, %s mirroring%s\n",
           path, cart.mapper, cart.prg_size / 1024, cart.chr_size / 1024,
           cart.chr_is_ram ? "RAM" : "ROM", mir[cart.mirroring],
           cart.battery ? ", battery" : "");
}
