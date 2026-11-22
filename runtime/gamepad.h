/* nesrecomp runtime: game controllers as NES controllers (gamepad.c). */
#ifndef NESRECOMP_GAMEPAD_H
#define NESRECOMP_GAMEPAD_H
#include <stdint.h>

union SDL_Event;

int gamepad_init(void);                         /* 0 on success */
void gamepad_event(const union SDL_Event *e);   /* plugging in and out */
uint8_t gamepad_buttons(int player);            /* NES buttons, player 0-3 */
/* Buttons held now are ignored until let go (the menu closing). */
void gamepad_ignore_held(void);

/* What the controllers ask for besides the game's buttons, once a frame
   (PLAN-pause.md step 2). `now` in milliseconds; `menu_open` whether the
   pause menu is open. The keys are menu.h's MENU_UP to MENU_BACK. */
struct pad_wants {
    int open;                   /* 1-4: that controller opened the menu */
    int keys[16], nkeys;        /* for the open menu */
    int rewind, fast;           /* a shoulder held (menu closed) */
};
void gamepad_frame(uint32_t now, int menu_open, struct pad_wants *w);
/* --test-gamepads: check the mapping with virtual controllers; prints
   PASS or FAIL lines and returns the exit status. */
int gamepad_self_test(void);

#endif
