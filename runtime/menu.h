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

/* The menu's keys, from the window or an input script. */
enum { MENU_UP = 1, MENU_DOWN, MENU_LEFT, MENU_RIGHT, MENU_OK, MENU_BACK, MENU_SHOT };

/* Open it at the end of this frame. */
void menu_request(void);
int menu_wanted(void);
int menu_is_open(void);
/* A key for the menu (MENU_SHOT: save the menu's picture to `path`). */
void menu_key(int key, const char *path);
/* From frame_done: the menu, until it closes. `fb` is the frame shown. */
void menu_run(const uint16_t *fb);

/* main.c: what the menu needs from the rest of the program. */
int runtime_slot(void);                     /* 1-4 */
void runtime_set_slot(int n);
const char *runtime_slot_path(void);        /* the slot's file */
void runtime_menu_save(void);               /* as Cmd+S */
void runtime_menu_load(void);               /* as Cmd+L */
void runtime_menu_reset(void);              /* as R */
int runtime_headless(void);
unsigned long long runtime_frame(void);    /* the PPU's frame number */
/* The menu's picture to the window (it waits for the next 60th of a
   second and reads the keys), or nothing headless. */
void runtime_menu_present(const uint16_t *fb);

#endif
