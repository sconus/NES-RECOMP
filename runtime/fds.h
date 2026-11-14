/* nesrecomp runtime: the Famicom Disk System (see fds.c). */
#ifndef FDS_H
#define FDS_H

#include <stdint.h>
#include <stdio.h>

/* cart.mapper for a disk image (not an iNES mapper number). */
#define MAPPER_FDS 0x1001

/* From cart_load, for a .fds image: keep the disk, set up the cart
   (the BIOS as PRG, 32 KB of RAM, 8 KB of CHR RAM). */
void fds_load(const char *path, FILE *f);
void fds_print_info(const char *path);
/* The RAM adapter, from mapper_init. */
void fds_reset(void);
void fds_write(uint16_t addr, uint8_t val);         /* $8000-$FFFF */
void fds_write_low(uint16_t addr, uint8_t val);     /* $4020-$5FFF */
int fds_read_low(uint16_t addr);                    /* -1: open bus */

/* The sound channel ($4040-$408A, read-backs $4040-$407F, $4090-$4097).
   fds_sound_on mirrors $4023 bit 1: while it is 0 the channel is held
   silent and reset. An NSF player has it on. */
extern int fds_sound_on;
void fds_sound_reset(void);
void fds_sound_write(uint16_t addr, uint8_t val);
int fds_sound_read(uint16_t addr);          /* -1: not a sound register */
float fds_audio_step(uint64_t cycle);

#endif
