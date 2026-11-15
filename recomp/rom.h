/* nesrecomp's recompiler, in C (PLAN-standalone.md): reading a ROM.
   The C version of recomp.py's read_header, MAPPERS and class Rom, made
   to read every file exactly as recomp.py does (tests/check_recomp.py
   compares the two with --dump-rom). */
#ifndef RECOMP_ROM_H
#define RECOMP_ROM_H
#include <stddef.h>
#include <stdint.h>

#define NSF_MAPPER 0x1000            /* runtime/nsf.h: MAPPER_NSF */
#define FDS_MAPPER 0x1001            /* runtime/fds.h: MAPPER_FDS */
#define FDS_SIDE 65500
#define FDS_FIRST_TAG 4              /* runtime/fds.h */
#define NO_BANK (-1)                 /* recomp.py's None for a bank */

/* An iNES header, as iNES 1.0 or NES 2.0 (recomp.py's read_header). */
struct header {
    int nes2, battery, trainer, mapper, submapper, console, console_ext;
    int timing, misc_roms, exp_device;
    int64_t prg_size, chr_size, prg_ram, prg_nvram, chr_ram, chr_nvram;
};

/* One PRG file of a disk image, in RAM: its bytes at lo.. */
struct fds_file {
    int lo, len;
    const uint8_t *data;
};

struct rom {
    int is_nsf, is_fds;
    struct header header;            /* an iNES file only */
    int mapper;
    const char *mapper_name;
    int unit;                        /* slots switching together, or 0: never */
    int slot_bits, banks, ram_top, high_writes;
    int low_lo, low_hi;              /* registers below $8000, or -1 */
    int nslots;                      /* 4 (8 KB) or 8 (4 KB) */
    int power_on[8];
    int fixed[8];                    /* the bank, or NO_BANK: it switches */
    uint8_t *prg;
    size_t prg_len;
    /* an NSF */
    int nsf_load, nsf_init, nsf_play, nsf_chips;
    /* JSR targets that return past pointers after the JSR (an FDS's
       BIOS): the count, or -1: it never returns there. */
    int n_inline;
    int inline_addr[16], inline_count[16];
    /* an FDS */
    struct fds_file files[256];      /* by tag; len 0: none */
    int has_file[256];
    int files_count;
    uint8_t boot_ram[0x8000], boot_owner[0x8000];
    uint8_t *data;                   /* the whole file, which files point into */
    size_t size;
};

/* Read the file. On a file recomp.py refuses, prints its message to
   stderr and exits with status 1, as recomp.py's sys.exit does. */
void rom_load(struct rom *r, const char *path);

int rom_slot(const struct rom *r, long addr);
int rom_read(const struct rom *r, int bank, long addr);
int rom_read16(const struct rom *r, long addr);
/* The bank code at (fbank, faddr) finds at addr, or NO_BANK. */
int rom_resolve(const struct rom *r, int fbank, long faddr, long addr);
int rom_translatable(const struct rom *r, int bank, long addr);
/* The tag code in RAM must have (code_owner), or -1 for ROM. */
int rom_guard_tag(const struct rom *r, int bank, long addr);
int rom_guarded(const struct rom *r);
int rom_switches(const struct rom *r, long addr);
/* (power-on bank, addr) */
int rom_power_on_bank(const struct rom *r, long addr);
/* The program's vectors after an FDS boot load: up to 5 (bank, addr). */
int rom_fds_entries(const struct rom *r, int *banks, long *addrs);

#endif
