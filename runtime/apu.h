/* nesrecomp runtime: the APU (sound): the state the CPU can see, and the
   five channels mixed into 48 kHz samples. */
#ifndef NESRECOMP_APU_H
#define NESRECOMP_APU_H
#include <stdint.h>

void apu_reset(void);                   /* power-on */
void apu_soft_reset(void);              /* the reset button */

/* CPU side: $4000-$4013, $4015, $4017. */
void apu_write(uint16_t addr, uint8_t val);
uint8_t apu_read_status(void);          /* $4015 */

/* Run the APU forward to the CPU's current cycle. */
void apu_catch_up(void);
/* Tell the event system when the APU next needs to run on its own
   (a frame IRQ or a DMC sample event). */
void apu_schedule(void);

/* DMC DMA: the cycle at or after which the next sample fetch pauses the
   CPU (UINT64_MAX if none). The CPU bus calls apu_dma_point on reads of
   $2000-$401F once it's reached (read_addr = the address being read),
   and the event handler at instruction boundaries (read_addr = 0). */
extern uint64_t dmc_dma_due;
#define DMA_CHECK_AHEAD 1               /* = DMA_READ_AT in apu.c */
void apu_dma_point(uint16_t read_addr);
/* Sprite DMA from a $4014 write at `cycles`, with any DMC fetches that
   land in it: returns the cycle the CPU resumes on. */
uint64_t apu_oam_dma(void);

/* Sound output. Off unless enabled (headless tests don't need it). */
void apu_enable_sound(void);
/* Fetch up to `max` finished 48 kHz mono samples. */
int apu_take_samples(int16_t *out, int max);
/* Run the sample clock slightly fast or slow (factor near 1.0), to keep
   playback in step with the video. */
void apu_set_sample_rate_trim(double factor);

#endif
