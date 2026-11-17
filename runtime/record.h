/* nesrecomp runtime: recording gameplay to a movie (PLAN-standalone.md
   step 6), with Apple's AVFoundation (record_mac.m); on Windows with
   Media Foundation, to an .mp4 with AAC sound (record_win.c,
   PLAN-windows.md step 3).

   One .mov file: the picture in H.264, the NES's 256x240 at 4x with sharp
   pixels (1024x960), at the NES's 60.0988 frames a second; the sound in
   the same file, 48 kHz mono 16-bit, uncompressed. The movie runs on game
   time: frame N is at N / 60.0988 seconds and sample K at K / 48000, so
   picture and sound stay together even if the Mac stutters. The file is
   only playable once finished (record_stop), which the runtime does when
   it exits. */
#ifndef NESRECOMP_RECORD_H
#define NESRECOMP_RECORD_H
#include <stdint.h>

/* Start recording to path (an existing file is replaced). Returns 0, or
   -1 with the reason printed. */
int record_start(const char *path);
/* The frame just finished, and the sound made during it. */
void record_frame(const uint16_t *framebuffer);
void record_audio(const int16_t *samples, int n);
/* Finish the file (waits until it's written); says where it went. */
void record_stop(void);
int record_active(void);
/* What a movie's name ends with: "mov" on the Mac, "mp4" on Windows. */
const char *record_ext(void);

#endif
