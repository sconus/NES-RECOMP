/* nesrecomp runtime: game controllers as NES controllers (gamepad.c). */
#ifndef NESRECOMP_GAMEPAD_H
#define NESRECOMP_GAMEPAD_H
#include <stdint.h>

union SDL_Event;

int gamepad_init(void);                         /* 0 on success */
void gamepad_event(const union SDL_Event *e);   /* plugging in and out */
uint8_t gamepad_buttons(int player);            /* NES buttons, player 0-3 */
/* --test-gamepads: check the mapping with virtual controllers; prints
   PASS or FAIL lines and returns the exit status. */
int gamepad_self_test(void);

#endif
