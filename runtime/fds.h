/* nesrecomp runtime: the Famicom Disk System (see fds.c). */
#ifndef FDS_H
#define FDS_H

#include <stdint.h>

/* The sound channel ($4040-$408A, read-backs $4040-$407F, $4090-$4097).
   fds_sound_on mirrors $4023 bit 1: while it is 0 the channel is held
   silent and reset. An NSF player has it on. */
extern int fds_sound_on;
void fds_sound_reset(void);
void fds_sound_write(uint16_t addr, uint8_t val);
int fds_sound_read(uint16_t addr);          /* -1: not a sound register */
float fds_audio_step(uint64_t cycle);

#endif
