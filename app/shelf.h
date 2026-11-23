/* nesrecomp app: the library, the shelf of games (PLAN-library.md
   step 4).

   Every game built goes on the shelf, last played first. The list is
   library.txt in the build folder: a "version 1" line, then a line a
   game: its name (the build's NAME), when it was last played (seconds
   since 1970), and its ROM's path, separated by tabs (a path may have
   spaces, never tabs). A missing file gives the games already built
   (their NAME.stamp files hold the ROM's path); a garbled one gives an
   empty shelf, and says why. Each game's picture is its NAME.title
   (runtime/title.h), shrunk for its box and for the TV; its box's colour
   is the picture's most common colour that isn't black, white or grey,
   snapped to one of SHELF_COLOURS box colours. */
#ifndef APP_SHELF_H
#define APP_SHELF_H
#include <limits.h>
#include <stdint.h>

#define SHELF_MAX 512
#define THUMB_W 20                      /* the picture in a box's window */
#define THUMB_H 19
#define PREVIEW_W 77                    /* the picture on the TV (with its name under it) */
#define PREVIEW_H 72
#define SHELF_COLOURS 12
#define SHELF_GREY 9                    /* the box colour with no colour to go by */

struct shelf_game {
    char name[256];
    char rom[PATH_MAX];
    long long played;                   /* seconds since 1970; 0: never (from a stamp) */
    int music;                          /* an NSF: no picture, a note on its box */
    int has_title;                      /* NAME.title was read */
    int missing;                        /* its ROM isn't where it was (step 5) */
    int colour;                         /* 0 .. SHELF_COLOURS-1 */
    uint32_t thumb[THUMB_W * THUMB_H];  /* 0xRRGGBB */
    uint32_t preview[PREVIEW_W * PREVIEW_H];
};

struct shelf {
    char dir[PATH_MAX];                 /* the build folder */
    int count;
    struct shelf_game games[SHELF_MAX];
};

/* The box colours (from the reference's boxes), 0xRRGGBB. */
extern const uint32_t shelf_colours[SHELF_COLOURS];

/* Read the shelf from the build folder (library.txt, or the stamps). It
   says what it did: "shelf: N games" and why if something was wrong. */
void shelf_load(struct shelf *s, const char *dir);
/* Write library.txt. 0 when written. */
int shelf_save(const struct shelf *s);
/* A game built (and about to be played): to the front, played now, its
   picture read again; added if new. Saves. Returns its place (0). */
int shelf_played(struct shelf *s, const char *name, const char *rom, long long now);
/* Read a game's NAME.title again (after it played). */
void shelf_title(struct shelf *s, int i);
/* Is each game's ROM still there? (At the start, when the window comes
   back to the front, after a game.) Says which ones aren't. */
void shelf_check_roms(struct shelf *s);
/* Take game i off the shelf, with its built program and what was made
   with it (NAME, NAME.exe, .c, .o, .listing, .translated, .stamp, .log,
   .game.log, .title, .history); never its ROM, its .sav, .missed or save
   states. Saves. */
void shelf_remove(struct shelf *s, int i);
/* Its index, or -1. */
int shelf_find(const struct shelf *s, const char *name);
/* The colour for a picture (256x240 RGB bytes): an index into
   shelf_colours. */
int shelf_colour_of(const uint8_t *rgb);
/* rgb (sw x sh, RGB bytes) averaged down to dw x dh, 0xRRGGBB: each new
   pixel the mean of the area it covers. */
void shelf_shrink(const uint8_t *rgb, int sw, int sh, uint32_t *out, int dw, int dh);
/* The self-test (--test-shelf DIR, writing in DIR). 0 when all pass. */
int shelf_test(const char *dir);

#endif
