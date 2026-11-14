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
    /* The rest of the header (NES 2.0; with iNES 1.0, the values the
       runtime has always assumed). Sizes are in bytes, 0 for none. */
    int nes2;              /* 1: read as an NES 2.0 header */
    int submapper;         /* the board variant, 0-15 */
    size_t prg_ram_size, prg_nvram_size;    /* $6000 work RAM, battery RAM */
    size_t chr_ram_size, chr_nvram_size;
    int timing;            /* 0 NTSC, 1 PAL, 2 multi-region, 3 Dendy */
    int console;           /* 0 NES/Famicom, 1 Vs. System, 2 PlayChoice-10,
                              3 extended (console_ext says which) */
    int console_ext;       /* byte 13, for a Vs. System or extended type */
    int misc_roms;         /* how many extra ROMs follow CHR ROM */
    int exp_device;        /* the default expansion device, byte 15 */
};

extern struct cart cart;

void cart_load(const char *path);
void cart_print_info(const char *path);
/* Battery saves: load/write the $6000-$7FFF RAM as <rom>.sav. */
void cart_load_save(const char *rom_path);
void cart_write_save(const char *rom_path);

#endif
