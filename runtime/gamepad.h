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
   (PLAN-pause.md step 2). `now` in milliseconds; `menu_open` 0 when the
   pause menu is closed, 1 when it's open, 2 on its button test
   (PLAN-controllers.md: there the buttons only light up, and only
   Home or Select+Start held leave). The keys are menu.h's MENU_UP to
   MENU_LEAVE. */
struct pad_wants {
    int open;                   /* 1-4: that controller opened the menu */
    int keys[16], nkeys;        /* for the open menu */
    int rewind, fast;           /* a shoulder held (menu closed) */
};
void gamepad_frame(uint32_t now, int menu_open, struct pad_wants *w);
/* What a slot (0-3) holds, for the Controllers page. */
struct pad_info {
    int present;
    char name[40];              /* SDL's name for it, in capitals */
    const char *brand;          /* "XBOX", "PS5", "SWITCH PRO", ... or NULL */
    uint8_t nes;                /* the NES buttons it presses (no menu mask) */
    int lb, rb, home;           /* the shoulders and Home / Guide */
};
void gamepad_info(int player, struct pad_info *p);

/* The PADS page (PLAN-controllers.md step 4) waiting for a pad button:
   gamepad_watch_start as it starts (buttons held then don't count),
   then gamepad_watch gives a button any pad has freshly pressed (an
   SDL_GameControllerButton, not Home) or -1. gamepad_layout_changed
   after a remap, so a button held then isn't a fresh menu press. */
void gamepad_watch_start(void);
int gamepad_watch(void);
void gamepad_layout_changed(void);

/* For the tests (an input script's menu line, pad=2:a+start): a virtual
   controller in slot `player` (0-3), plugged in if it isn't there yet,
   holding `buttons` (bits of PAD_TEST_*). gamepad_parse_virtual reads
   "2:a+start" (or "2:none"); 0 if it can't. */
enum { PAD_TEST_A = 1, PAD_TEST_B = 2, PAD_TEST_SELECT = 4, PAD_TEST_START = 8,
       PAD_TEST_UP = 16, PAD_TEST_DOWN = 32, PAD_TEST_LEFT = 64, PAD_TEST_RIGHT = 128,
       PAD_TEST_LB = 256, PAD_TEST_RB = 512, PAD_TEST_HOME = 1024,
       PAD_TEST_X = 2048, PAD_TEST_Y = 4096, PAD_TEST_LS = 8192, PAD_TEST_RS = 16384 };
int gamepad_parse_virtual(const char *spec, int *player, unsigned *buttons);
void gamepad_virtual(int player, unsigned buttons);

/* --test-gamepads: check the mapping with virtual controllers; prints
   PASS or FAIL lines and returns the exit status. */
int gamepad_self_test(void);

#endif
