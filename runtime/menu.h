/* nesrecomp runtime: the pause menu (PLAN-pause.md).

   Esc in the window asks for it (menu_request); at the end of the
   frame (frame_done in main.c) menu_run takes over: it draws the menu
   over the last picture, darkened, and reads keys, and no 6502 code
   runs until it closes, so pausing can't change the game. What the
   menu does to the game (save, load, reset) it only asks for, through
   main.c, and that happens at the next instruction boundary, as the
   keys' own requests do. */
#ifndef NESRECOMP_MENU_H
#define NESRECOMP_MENU_H
#include <stdint.h>

/* The menu's keys, from the window or an input script. MENU_BACK (Z, a
   pad's B) goes back a page; MENU_LEAVE (Esc, Home) too, and is the
   only way off the button test, where every other button lights up.
   MENU_VPAD (scripts only) sets a virtual controller's buttons.
   MENU_SCAN is a key as it is (a scancode, menu_key_code), for a
   KEYBOARD page waiting for one; MENU_WAIT (scripts only) is that many
   60ths of a second of nothing, as the window would show. */
enum { MENU_UP = 1, MENU_DOWN, MENU_LEFT, MENU_RIGHT, MENU_OK, MENU_BACK, MENU_SHOT,
       MENU_LEAVE, MENU_VPAD, MENU_SCAN, MENU_WAIT };

/* Open it at the end of this frame. */
void menu_request(void);
int menu_wanted(void);
int menu_is_open(void);
/* 0 closed, 1 open, 2 on the button test or waiting for a key
   (gamepad_frame's menu_open: the pads only leave). */
int menu_mode(void);
/* A KEYBOARD page is waiting for a key: the window sends every key
   pressed as menu_key_code(MENU_SCAN, scancode), Esc as MENU_LEAVE. */
int menu_wants_scancode(void);
/* A key for the menu (MENU_SHOT: save the menu's picture to `path`). */
void menu_key(int key, const char *path);
void menu_key_code(int key, int code);
/* Which system's pairing help to show: 0 the Mac's, 1 Windows'
   (default: the one this was built for; --pairing-for, for the tests). */
void menu_set_pairing(int windows);
/* From frame_done: the menu, until it closes. `fb` is the frame shown. */
void menu_run(const uint16_t *fb);

/* main.c: what the menu needs from the rest of the program. */
int runtime_slot(void);                     /* 1-4 */
void runtime_set_slot(int n);
const char *runtime_slot_path(void);        /* the slot's file */
void runtime_menu_save(void);               /* as Cmd+S */
void runtime_menu_load(void);               /* as Cmd+L */
void runtime_menu_reset(void);              /* as R */
int runtime_sound(void);                    /* 1-10, or 0: off */
void runtime_sound_step(int d);             /* -1 quieter (to OFF), +1 louder */
void runtime_sound_toggle(void);            /* as M */
int runtime_window(void);                   /* the size in steps, or 0: full screen */
void runtime_window_step(int d);            /* -1 smaller, +1 bigger (to FULL) */
void runtime_window_toggle(void);           /* as Cmd+F */
int runtime_headless(void);
uint8_t runtime_keyboard_buttons(int player);  /* 0-1, as held, for the button test */
unsigned long long runtime_frame(void);    /* the PPU's frame number */
/* The menu's picture to the window (it waits for the next 60th of a
   second and reads the keys), or nothing headless. */
void runtime_menu_present(const uint16_t *fb);

#endif
