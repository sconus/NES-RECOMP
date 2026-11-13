/* nesrecomp runtime: NSF music files.

   An NSF holds a music program without a picture or reset vector: the
   header names an init routine (called once per song with the song
   number in A and 0 = NTSC in X) and a play routine (called at a fixed
   rate, normally 60 times a second). The runtime plays the NSF player's
   part with a small 6502 driver at $4100, an address no NSF uses: it
   resets the sound registers, sets the starting banks (for an NSF that
   switches banks), calls init, and then waits for the play timer and
   calls play, over and over. Waiting by polling, not by an
   interrupt, means play never cuts into init or into itself: if init
   never returns (some test NSFs run entirely in init), play is never
   called. */
#ifndef NESRECOMP_NSF_H
#define NESRECOMP_NSF_H
#include <stdint.h>
#include <stdio.h>

/* cart.mapper for an NSF (outside the iNES mapper numbers). */
#define MAPPER_NSF 0x1000
#define NSF_DRIVER 0x4100

struct nsf {
    int songs, start_song;          /* start_song counts from 1 */
    uint16_t load, init, play;
    unsigned speed_ntsc;            /* play period, microseconds */
    uint8_t banks[8], pal_flags, chips;
    int banked;                     /* bank switching at $5FF8-$5FFF */
    char title[33], artist[33], copyright[33];
};
extern struct nsf nsf;

/* From cart_load, for a file starting "NESM": read the header and lay
   the program out in cart.prg: 32 KB at $8000-$FFFF, or for a
   bank-switched NSF, 4 KB banks. */
void nsf_load(const char *path, FILE *f);
void nsf_print_info(const char *path);
/* Set up the driver for song (1-based; 0 = the header's start song) and
   return the address to start the CPU at. */
uint16_t nsf_start(int song);
/* Set up the program's slots (from mapper_init). */
void nsf_mapper_reset(void);
/* $4020-$5FFF for the NSF "mapper": the driver, its play timer, and the
   bank registers. */
int nsf_read_low(uint16_t addr);
void nsf_write_low(uint16_t addr, uint8_t val);

#endif
