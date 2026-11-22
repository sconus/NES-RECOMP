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
   M in the window toggles mute; R presses the reset button; the number
   keys change an FDS disk's side (0 ejects it, 1-9 put in that side),
   through runtime_disk_key in main.c. */
void runtime_disk_key(int n);
/* V starts and stops a recording, P saves a picture of the screen
   (main.c, PLAN-standalone.md step 6). While recording, a small red REC
   shows in the window's corner; it isn't in the movie. */
void runtime_record_key(void);
void runtime_snap_key(void);
/* Cmd+S saves a state, Cmd+L loads it (Ctrl on Windows; state.h's
   STATE_SAVE, STATE_LOAD), through runtime_state_key in main.c. */
void runtime_state_key(int what);
/* Cmd+1 to Cmd+4 (Ctrl on Windows): which slot saves and loads use. */
void runtime_state_slot(int n);
/* Empty the sound queue and start again from silence (after a load). */
void video_restart_audio(void);
/* The sound off (1) or on (0): nothing queued, and the title says
   "(muted)". main.c keeps the volume and calls it (M, the menu). */
void video_set_muted(int on);
void runtime_sound_toggle(void);
/* The window's size (the pause menu, Cmd+=, Cmd+-, Cmd+F). */
int video_most_scale(void);
int video_full_screen(void);
void video_set_full_screen(int on);
void video_resize_step(int d);
/* A short sound played at once over the paused speakers (the menu's
   blip when the volume changes). */
void video_blip(const int16_t *samples, int n);
/* The speakers paused (1) or going again (0): the pause menu. */
void video_pause_audio(int on);
/* Buttons held now are ignored until let go (the menu closing). */
void video_ignore_held(void);
/* main.c: whether the game has a pause menu (not a music file). */
int runtime_has_menu(void);
/* Text in the runtime's 5x7 font (nsf.c), 6 pixels a character, with
   its top left at (x, y), in NES colour `ink`. */
void draw_text_5x7(uint16_t *fb, int x, int y, const char *s, uint16_t ink);
void video_init_audio(void);
void video_queue_audio(const int16_t *samples, int n);
int video_audio_queued(void);           /* samples waiting, or -1 */

/* A controller's buttons (player 0-3) from the keyboard (players 0 and
   1 only) and game controllers, as of the last video_present. */
uint8_t video_buttons(int player);
/* Backspace (or a controller's left shoulder) held: rewind
   (PLAN-savestates.md step 3; PLAN-pause.md step 2). */
int video_rewind_held(void);
/* ` (backquote, or a controller's right shoulder) held: fast-forward
   (step 4). Frames come `n` times as often (1: normal); a frame not
   drawn still reads the keys and waits. */
int video_fast_held(void);
void video_set_speed(int n);
void video_skip(void);

/* The mouse, as of the last video_present, for a paddle or a Zapper: *x
   and *y from 0 at the window's left or top edge to 1 at its right or
   bottom, *inside whether the pointer is over the window, *button the
   left button. Returns 0 (and sets nothing) until the mouse has moved
   over the window. */
int video_mouse(double *x, double *y, int *inside, int *button);
/* The window's size now, in whole steps of 256x240 (the last one before
   full screen, if it's full screen); 0 with no window. The window can be
   resized by dragging, Cmd+= and Cmd+-, and Cmd+F makes it full screen. */
int video_scale(void);

/* Show the pointer as a cross over the window (for the Zapper). */
void video_crosshair(void);

/* Save a frame as a PNG file. Returns 0 on success. */
int video_save_png(const uint16_t *framebuffer, const char *path);

#endif
