/* nesrecomp runtime: which keys and pad buttons are the NES buttons
   (PLAN-controllers.md steps 3 and 4).

   Two keyboard players, each with eight keys (SDL scancodes). The pause
   menu's KEYBOARD 1 and 2 pages change them; --controls FILE keeps them
   between runs. Only the window's keyboard reads them (video_buttons),
   never an input script, so a remap can't change what a test or a
   recording plays. Keys the window itself uses can't be chosen
   (controls_reserved); choosing a key another button has swaps the two.

   The pads (step 4) share one layout, by position (SDL lines Xbox,
   PlayStation and Switch pads up that way): which of twelve pad buttons
   is each NES button. Home and the shoulders (the menu, rewind,
   fast-forward) and the left stick (always the D-pad's directions) stay
   as they are. */
#ifndef NESRECOMP_CONTROLS_H
#define NESRECOMP_CONTROLS_H
#include <stdint.h>

/* The buttons, in the order the KEYBOARD pages list them. */
enum { CB_UP, CB_DOWN, CB_LEFT, CB_RIGHT, CB_B, CB_A, CB_SELECT, CB_START, CB_COUNT };
extern const char *const controls_button_names[CB_COUNT];   /* "UP" ... "START" */

int controls_key(int player, int button);           /* player 0-1: its scancode */
/* The key's name in capitals ("RIGHT SHIFT"), or "?" */
const char *controls_key_name(int scancode);
/* A key the window keeps for itself (Esc, M, R, V, P, 0-9, Backspace,
   the fast-forward key, Cmd/Ctrl...), or one SDL has no name for. */
int controls_reserved(int scancode);

/* Give `button` the key: 0 refused (reserved), 1 done, 2 done and swapped
   (the button that had it, *other_player / *other_button, gets the old
   key). Writes the file (controls_use_file) when something changed. */
int controls_set(int player, int button, int scancode, int *other_player, int *other_button);
void controls_defaults(int player);                 /* and writes the file */

/* The NES buttons a keyboard state holds for a player (state indexed by
   scancode, as SDL_GetKeyboardState). */
uint8_t controls_buttons(int player, const uint8_t *state, int nkeys);

/* --controls FILE: read it now (missing, older or garbled: the defaults,
   said in the terminal), and write it when a key changes. */
void controls_use_file(const char *path);

/* A key from its name, as a script writes it ("k", "right_shift"), or 0. */
int controls_scancode(const char *name);

/* The pads' layout. Pad buttons are SDL_GameControllerButton values. */
int controls_pad(int button);                       /* the pad button for it */
/* Its name on the PADS page ("BOTTOM BUTTON"), or "?" */
const char *controls_pad_name(int pad_button);
/* As controls_set, for the pads: 0 refused (Home, a shoulder, a button
   SDL has but not every pad), 1 done, 2 done and swapped with
   *other_button. Writes the file when something changed. */
int controls_pad_set(int button, int pad_button, int *other_button);
void controls_pad_defaults(void);                   /* and writes the file */
/* The NES buttons for the pad buttons held (held[SDL button], up to
   n of them). */
uint8_t controls_pad_buttons(const uint8_t *held, int n);
/* A pad button from its name in a file or script ("bottom",
   "dpad_up"), or -1. */
int controls_pad_from_name(const char *name);

int controls_self_test(void);                       /* --test-controls */

#endif
