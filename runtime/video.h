/* nesrecomp runtime: showing frames in a window, and saving them. */
#ifndef NESRECOMP_VIDEO_H
#define NESRECOMP_VIDEO_H
#include <stdint.h>

/* Open a window `scale` times the NES's 256x240. Exits on failure. */
void video_init(int scale, const char *title);
/* Show one frame, handle window events, and wait so frames come at the
   NES's 60.1 per second. Closing the window or pressing Escape exits. */
void video_present(const uint16_t *framebuffer);

/* Sound: open the audio device, then hand it each frame's samples.
   M in the window toggles mute; R presses the reset button. */
void video_init_audio(void);
void video_queue_audio(const int16_t *samples, int n);
int video_audio_queued(void);           /* samples waiting, or -1 */

/* Controller 1 buttons from the keyboard, as of the last video_present:
   arrows, X = A, Z = B, Return = Start, Right Shift = Select. */
uint8_t video_buttons(void);

/* Save a frame as a PNG file. Returns 0 on success. */
int video_save_png(const uint16_t *framebuffer, const char *path);

#endif
