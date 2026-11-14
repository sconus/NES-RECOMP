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

/* A controller's buttons (player 0-3) from the keyboard (players 0 and
   1 only) and game controllers, as of the last video_present. */
uint8_t video_buttons(int player);

/* The mouse, as of the last video_present, for a paddle: *x from 0 at
   the window's left edge to 1 at its right, *button the left button.
   Returns 0 (and sets nothing) until the mouse has moved over the window. */
int video_mouse(double *x, int *button);

/* Save a frame as a PNG file. Returns 0 on success. */
int video_save_png(const uint16_t *framebuffer, const char *path);

#endif
