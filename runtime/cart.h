/* nesrecomp runtime: the cartridge, as loaded from the .nes file. */
#ifndef NESRECOMP_CART_H
#define NESRECOMP_CART_H
#include <stddef.h>
#include <stdint.h>

/* How the PPU's 2 KB of nametable RAM fills its 4 KB nametable space.
   The header gives the starting mode; some mappers change it while
   running, including to one 1 KB table everywhere (single-screen). */
enum mirroring { MIRROR_HORIZONTAL, MIRROR_VERTICAL, MIRROR_FOUR_SCREEN,
                 MIRROR_SINGLE_LOW, MIRROR_SINGLE_HIGH };

struct cart {
    uint8_t *prg;          /* program ROM, seen by the CPU at $8000-$FFFF */
    size_t prg_size;
    uint8_t *chr;          /* pattern data, seen by the PPU at $0000-$1FFF */
    size_t chr_size;
    int chr_is_ram;        /* 1 when the header lists no CHR ROM */
    uint8_t prg_ram[0x2000];   /* $6000-$7FFF work RAM (test ROMs report here) */
    enum mirroring mirroring;      /* current mode; mappers may change it */
    int mapper;
    int battery;
};

extern struct cart cart;

void cart_load(const char *path);
void cart_print_info(const char *path);
/* Battery saves: load/write the $6000-$7FFF RAM as <rom>.sav. */
void cart_load_save(const char *rom_path);
void cart_write_save(const char *rom_path);

#endif
