/* nesrecomp app: a window to drop a ROM onto (PLAN-gui.md).

   The window and its screens. The picture (app/art.h, from
   tools/make_app_art.py) is a 640x360 canvas (PLAN-library.md: the
   living room, the TV on its stand above the shelf), drawn into the window at
   the largest whole-number scale that fits and centred, with the rest
   of the window in a dark border, so the pixels stay square and sharp.
   The window's pixels are counted in real pixels (a Retina screen has
   twice as many as its points).

   The idle animation: the TV screen's glow rises and falls over about
   four seconds, its scanlines shimmer, and the console's power light
   blinks once a second (fast while a ROM is being built).

   The screens, all on the TV:
     drop    a little cartridge with an arrow, "DRAG NES ROM HERE TO
             RECOMPILE"
     build   the file's name, "RECOMPILING IN PROGRESS", the loading bar
             and the stage (build.c does the work, on its own thread, so
             the window stays responsive)
     needcc  no C compiler on this Mac: "NEEDS APPLE'S C COMPILER", "CLICK
             TO INSTALL IT" and the command for Terminal; a click on the
             TV runs `xcode-select --install` (Apple's installer), then
             "WHEN IT'S DONE, DROP THE ROM AGAIN" (PLAN-standalone.md
             step 5)
     error   "CAN'T RECOMPILE" and why (a wrong file, or the tool's
             message); the whole output is in NAME.log in the build
             folder
     done    "DONE!": the program is built
     about   I on the drop, error or done screens: who made it and its
             license, and "SUPPORT IT: PRESS D": D opens the support page
             (support.h); any other key or a drop leaves it
     card    the keys, for a couple of seconds before a game starts (any
             key skips it); a music file (NSF) gets the player's keys
     play    the game runs in its own window (play.c) and this one hides;
             when the game quits, "under the hood", or, if it stopped or
             crashed, "THE GAME STOPPED" and why
     hood    "UNDER THE HOOD" (hood.h, PLAN-standalone.md step 7): for the
             last game, the instructions translated, the share that ran
             as C, its spots this run, and a bar for the spots of each
             run so far; after each game, and with H on the drop screen.
             Any key or a click leaves it
   From the error and done screens, another drop starts again.

       nesrecomp-app [ROM]                    open the window (and build ROM)
       nesrecomp-app --build ROM              build it with no window,
                                              printing each stage
       nesrecomp-app --build ROM --trace-progress
           the same, on the build thread as the window does it, printing
           the loading bar's value every 20 ms
       nesrecomp-app --screenshot F [--frames N] [--size WxH]
                     [--show drop|build|error|done] [--rom NAME]
                     [--stage N] [--progress P] [--message M] [--history FILE]
           draw a screen into a window of W x H pixels (default 640x360)
           and save it as a PNG, with no window: for tests/check_app.py
       nesrecomp-app --build ROM --then-play [--play-args "ARGS"]
           build it, then play it (with ARGS for the game, such as
           "--headless --frames 600"), and say how the game ended; the
           run goes into its history ("hood: run ..." says what)
       nesrecomp-app --play-only EXE ROM [--play-args "ARGS"]
           just play: run EXE on ROM as the app does, and say how it
           ended (for the checks)
       nesrecomp-app --hit-test WxH X Y
           is the pixel (X, Y) of a W x H window on the TV's screen (where
           a click opens the file picker)? Prints "tv" or "outside"
       nesrecomp-app --click-test SCREEN WxH X Y
           what a click at (X, Y) of a W x H window does on SCREEN (drop,
           error, needcc, ...); for the installer, run it (xcode-select
           --install, or $NESRECOMP_XCODE_SELECT) and say how it ended
       nesrecomp-app --support-url
           print the support page's address (support.h)
       nesrecomp-app --key-test about d
           what D on the About screen does, and do it (with
           $NESRECOMP_OPEN for the checks)
       nesrecomp-app --menu-test [--choose-support]
           start SDL with no window, add the support item, and print the
           app menu's titles; and choose the support item
       nesrecomp-app --progress-model
           print the loading bar's value for each stage over a long range
           of times (and runtime file counts), for tests/check_app.py
       nesrecomp-app --sdl-info
           say where the app's own SDL2, recompiler and runtime are, where
           builds go, and where Apple's C compiler is (PLAN-standalone.md
           steps 1, 3, 4 and 5)
       nesrecomp-app --version
           print the app's version
       --build-dir D   where builds go (default: ~/Library/Application
                       Support/NES RECOMP, %LOCALAPPDATA%\NES RECOMP on
                       Windows, or $NESRECOMP_ROOT/build)
   The app needs no project folder (PLAN-standalone.md step 4): SDL2, the
   recompiler (nesrecomp-recomp) and the runtime's sources are found from
   the program's own place (in the bundle, or build/ and ../runtime for
   `make app`). $NESRECOMP_ROOT, set by `make run-app`, takes the runtime
   and builds from a project folder instead.
   What the Mac and Windows do differently is in os.h (PLAN-windows.md
   step 4); on Windows there is no "needs a compiler" screen (the app
   brings its own, step 5), and the support item is in the window's own
   menu (support_win.c). */
#define SDL_MAIN_HANDLED                /* main is the app's own, on Windows too */
#include <SDL.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include <zlib.h>
#ifndef _WIN32
#include <errno.h>
#include <fcntl.h>
#include <spawn.h>
#include <sys/wait.h>
#include <pthread.h>
#endif
#include "os.h"
#include "art.h"
#include "build.h"
#include "code.h"
#include "hood.h"
#include "play.h"
#include "support.h"

static uint32_t canvas[ART_H][ART_W];
/* "The 6502 next to its C" (step 8) uses the whole window at a finer
   grid: a canvas twice the room's size, the font at one pixel. */
#define CODE_W 640
#define CODE_H 360
static uint32_t code_canvas[CODE_H][CODE_W];
/* Where text goes: the room's canvas, or the code view's. */
static uint32_t *tgt = &canvas[0][0];
static int tgt_w = ART_W, tgt_h = ART_H;

static uint32_t rgb(int r, int g, int b) {
    return 0xFF000000u | (uint32_t)r << 16 | (uint32_t)g << 8 | (uint32_t)b;
}

static uint32_t ink(int i) {
    return rgb(art_palette[i][0], art_palette[i][1], art_palette[i][2]);
}

/* Text in the 5x7 font, `scale` canvas pixels a font pixel, a glyph
   every 6 * scale pixels; centred on x = cx. With `outline`, each lit
   pixel first darkens the 8 around it, as the channel's logo letters. */
static void text_pass(const char *s, int cx, int y, int sx, int sy, uint32_t colour, int grow);
static void text_xy(const char *s, int cx, int y, int sx, int sy, uint32_t colour, int outline) {
    if (outline) text_pass(s, cx, y, sx, sy, ink(INK_TEXT_LINE), 1);
    text_pass(s, cx, y, sx, sy, colour, 0);
}
static void text(const char *s, int cx, int y, int scale, uint32_t colour, int outline) {
    text_xy(s, cx, y, scale, scale, colour, outline);
}

/* The font has capitals only. A command for Terminal (step 5) and the
   C of the code view (step 8) must show as they are, so these lowercase
   letters and the rest of ASCII ($60-$7E) are drawn where text_lower is
   set; otherwise a letter is drawn as its capital. Each row: 5 bits, the
   leftmost 0x10. */
static const struct { char ch; unsigned char rows[7]; } lower_font[] = {
    { '`', { 0x10, 0x08, 0x04, 0x00, 0x00, 0x00, 0x00 } },
    { 'a', { 0x00, 0x00, 0x0E, 0x01, 0x0F, 0x11, 0x0F } },
    { 'b', { 0x10, 0x10, 0x16, 0x19, 0x11, 0x11, 0x1E } },
    { 'c', { 0x00, 0x00, 0x0E, 0x10, 0x10, 0x11, 0x0E } },
    { 'd', { 0x01, 0x01, 0x0D, 0x13, 0x11, 0x13, 0x0D } },
    { 'e', { 0x00, 0x00, 0x0E, 0x11, 0x1F, 0x10, 0x0E } },
    { 'f', { 0x06, 0x09, 0x08, 0x1C, 0x08, 0x08, 0x08 } },
    { 'g', { 0x00, 0x00, 0x0F, 0x11, 0x0F, 0x01, 0x0E } },
    { 'h', { 0x10, 0x10, 0x16, 0x19, 0x11, 0x11, 0x11 } },
    { 'i', { 0x04, 0x00, 0x0C, 0x04, 0x04, 0x04, 0x0E } },
    { 'j', { 0x02, 0x00, 0x06, 0x02, 0x02, 0x12, 0x0C } },
    { 'k', { 0x10, 0x10, 0x12, 0x14, 0x18, 0x14, 0x12 } },
    { 'l', { 0x0C, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E } },
    { 'm', { 0x00, 0x00, 0x1A, 0x15, 0x15, 0x11, 0x11 } },
    { 'n', { 0x00, 0x00, 0x16, 0x19, 0x11, 0x11, 0x11 } },
    { 'o', { 0x00, 0x00, 0x0E, 0x11, 0x11, 0x11, 0x0E } },
    { 'p', { 0x00, 0x00, 0x1E, 0x11, 0x1E, 0x10, 0x10 } },
    { 'q', { 0x00, 0x00, 0x0D, 0x13, 0x0F, 0x01, 0x01 } },
    { 'r', { 0x00, 0x00, 0x16, 0x19, 0x10, 0x10, 0x10 } },
    { 's', { 0x00, 0x00, 0x0F, 0x10, 0x0E, 0x01, 0x1E } },
    { 't', { 0x08, 0x08, 0x1C, 0x08, 0x08, 0x09, 0x06 } },
    { 'u', { 0x00, 0x00, 0x11, 0x11, 0x11, 0x13, 0x0D } },
    { 'v', { 0x00, 0x00, 0x11, 0x11, 0x11, 0x0A, 0x04 } },
    { 'w', { 0x00, 0x00, 0x11, 0x11, 0x15, 0x15, 0x0A } },
    { 'x', { 0x00, 0x00, 0x11, 0x0A, 0x04, 0x0A, 0x11 } },
    { 'y', { 0x00, 0x00, 0x11, 0x11, 0x0F, 0x01, 0x0E } },
    { 'z', { 0x00, 0x00, 0x1F, 0x02, 0x04, 0x08, 0x1F } },
    { '{', { 0x02, 0x04, 0x04, 0x08, 0x04, 0x04, 0x02 } },
    { '|', { 0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04 } },
    { '}', { 0x08, 0x04, 0x04, 0x02, 0x04, 0x04, 0x08 } },
    { '~', { 0x00, 0x00, 0x08, 0x15, 0x02, 0x00, 0x00 } },
};
static int text_lower;

/* sx, sy: the font's pixels are sx wide and sy tall (the build screen's
   tall letters are 1 x 2). */
static void text_pass(const char *s, int cx, int y, int sx, int sy, uint32_t colour, int grow) {
    int len = (int)strlen(s), x0 = cx - (len * 6 * sx - sx) / 2;
    for (int i = 0; i < len; i++) {
        int ch = (unsigned char)s[i];
        const unsigned char *g = NULL;
        for (size_t k = 0; text_lower && k < sizeof lower_font / sizeof *lower_font; k++)
            if (lower_font[k].ch == ch) g = lower_font[k].rows;
        if (ch >= 'a' && ch <= 'z') ch -= 32;
        if (ch < 0x20 || ch > 0x5F) ch = '?';
        if (!g) g = art_font[ch - 0x20];
        for (int r = 0; r < 7; r++)
            for (int c = 0; c < 5; c++)
                if (g[r] & (0x10 >> c))
                    for (int dy = -grow; dy < sy + grow; dy++)
                        for (int dx = -grow; dx < sx + grow; dx++) {
                            int x = x0 + i * 6 * sx + c * sx + dx, yy = y + r * sy + dy;
                            if (x >= 0 && x < tgt_w && yy >= 0 && yy < tgt_h)
                                tgt[(size_t)yy * tgt_w + x] = colour;
                        }
    }
}

/* The room at frame n (60 a second): the picture, with the screen's
   glow and scanlines and the power light animated; `busy` blinks the
   light fast. */
static void draw_room(long n, int busy) {
    double t = n / 60.0;
    double glow = 0.5 + 0.5 * sin(t * 2 * M_PI / 4.0);      /* 0-1 every 4 s */
    uint32_t pal[ART_COLOURS];
    for (int i = 0; i < ART_COLOURS; i++) pal[i] = ink(i);
    /* The screen: its colour brightens with the glow; the scanlines
       shimmer between two shades every few frames. */
    const unsigned char *s = art_palette[INK_SCREEN];
    pal[INK_SCREEN] = rgb(s[0] + (int)(14 * glow), s[1] + (int)(20 * glow), s[2] + (int)(34 * glow));
    const unsigned char *k = art_palette[INK_SCAN];
    int shimmer = (n / 6) % 2;
    pal[INK_SCAN] = rgb(k[0] + 4 * shimmer + (int)(8 * glow), k[1] + 4 * shimmer + (int)(12 * glow),
                        k[2] + 6 * shimmer + (int)(20 * glow));
    /* The power light: on for 50 frames of each second, off for 10; while
       building, on and off every 8 frames. */
    if (busy ? (n / 8) % 2 : n % 60 >= 50) pal[INK_LED] = ink(INK_BLACK);
    for (int y = 0; y < ART_H; y++)
        for (int x = 0; x < ART_W; x++)
            canvas[y][x] = pal[art_pixels[y][x]];
}

#define SCREEN_CX (ART_SCREEN_X + ART_SCREEN_W / 2)
#define LINE_CHARS 18                   /* 1x glyphs that fit the screen */

/* A ROM's name for the screen: its file name, cut to fit. */
static void screen_name(const char *path, char *out, size_t n) {
    const char *base = os_last_sep(path);
    base = base ? base + 1 : path;
    if (strlen(base) <= LINE_CHARS) snprintf(out, n, "%s", base);
    else snprintf(out, n, "%.*s..", LINE_CHARS - 2, base);
}

#define DROP_TOP 5                      /* the cartridge, below the screen's top */
#define DROP_TEXT 28                    /* the words, below the cartridge's top */
static void draw_drop(long n) {
    draw_room(n, 0);
    int cx = SCREEN_CX;
    int top = ART_SCREEN_Y + DROP_TOP;
    /* The little cartridge with its arrow, then the words. */
    int x0 = cx - ART_CART_W / 2;
    for (int y = 0; y < ART_CART_H; y++)
        for (int x = 0; x < ART_CART_W; x++)
            if (art_cart[y][x] != 255) canvas[top + y][x0 + x] = ink(art_cart[y][x]);
    uint32_t white = ink(INK_TEXT);
    text_xy("DRAG NES ROM", cx, top + DROP_TEXT, 1, 2, white, 1);
    text_xy("HERE TO", cx, top + DROP_TEXT + 18, 1, 2, white, 1);
    text_xy("RECOMPILE", cx, top + DROP_TEXT + 36, 1, 2, white, 1);
}

/* The loading bar's box on the screen, and its inside. */
#define BAR_W 100
#define BAR_H 8
#define BAR_X (SCREEN_CX - BAR_W / 2)
#define BAR_Y (ART_SCREEN_Y + 58)

static void draw_build(long n, const char *name, int stage, double progress) {
    draw_room(n, 1);
    uint32_t white = ink(INK_TEXT), dim = ink(INK_MANE_HI);
    int y = ART_SCREEN_Y;
    text(name, SCREEN_CX, y + 6, 1, dim, 1);
    text_xy("RECOMPILING", SCREEN_CX, y + 20, 1, 2, white, 1);
    text_xy("IN PROGRESS", SCREEN_CX, y + 38, 1, 2, white, 1);
    /* The bar: an outlined box, filled from the left. */
    for (int yy = BAR_Y - 1; yy < BAR_Y + BAR_H + 1; yy++)
        for (int xx = BAR_X - 1; xx < BAR_X + BAR_W + 1; xx++)
            canvas[yy][xx] = ink(INK_TEXT_LINE);
    if (progress < 0) progress = 0;
    if (progress > 1) progress = 1;
    int fill = (int)(progress * BAR_W);
    for (int yy = BAR_Y; yy < BAR_Y + BAR_H; yy++)
        for (int xx = BAR_X; xx < BAR_X + BAR_W; xx++)
            canvas[yy][xx] = xx - BAR_X < fill ? ink(yy == BAR_Y ? INK_TEXT : INK_NEON)
                                               : ink(INK_SHADOW);
    text(build_stage_name(stage), SCREEN_CX, y + 72, 1, dim, 1);
}

/* Up to `max` lines of at most LINE_CHARS, broken at spaces. */
static int wrap(const char *msg, char lines[][LINE_CHARS + 1], int max) {
    int n = 0;
    const char *p = msg;
    while (*p && n < max) {
        while (*p == ' ') p++;
        int len = (int)strlen(p);
        if (len <= LINE_CHARS) { snprintf(lines[n++], LINE_CHARS + 1, "%s", p); break; }
        int cut = LINE_CHARS;
        while (cut > 0 && p[cut] != ' ') cut--;
        if (cut == 0) cut = LINE_CHARS;
        snprintf(lines[n++], LINE_CHARS + 1, "%.*s", cut, p);
        p += cut;
        if (n == max && *p) {           /* more than fits: say so */
            int l = (int)strlen(lines[n - 1]);
            if (l > LINE_CHARS - 2) l = LINE_CHARS - 2;
            snprintf(lines[n - 1] + l, 3, "..");
        }
    }
    return n;
}

static void draw_error(long n, const char *title, const char *msg) {
    draw_room(n, 0);
    uint32_t white = ink(INK_TEXT), dim = ink(INK_MANE_HI);
    int y = ART_SCREEN_Y;
    text_xy(title, SCREEN_CX, y + 5, 1, 2, white, 1);
    char lines[5][LINE_CHARS + 1];
    int k = wrap(msg, lines, 5);
    for (int i = 0; i < k; i++) text(lines[i], SCREEN_CX, y + 25 + i * 9, 1, white, 1);
    text("DROP ANOTHER FILE", SCREEN_CX, y + 74, 1, dim, 1);
}

/* No C compiler (build.c): what to do. After a click on the TV started
   Apple's installer (`clicked`), what to do when it's done. */
static void draw_needcc(long n, int clicked) {
    draw_room(n, 0);
    uint32_t white = ink(INK_TEXT), dim = ink(INK_MANE_HI);
    int y = ART_SCREEN_Y;
    text_xy("NEEDS APPLE'S", SCREEN_CX, y + 5, 1, 2, white, 1);
    text_xy("C COMPILER", SCREEN_CX, y + 21, 1, 2, white, 1);
    if (clicked) {
        text("WHEN IT'S DONE,", SCREEN_CX, y + 46, 1, white, 1);
        text("DROP THE ROM AGAIN", SCREEN_CX, y + 60, 1, dim, 1);
        return;
    }
    text("CLICK TO INSTALL IT", SCREEN_CX, y + 41, 1, white, 1);
    text("OR IN TERMINAL:", SCREEN_CX, y + 54, 1, dim, 1);
    text_lower = 1;
    text("xcode-select", SCREEN_CX, y + 63, 1, white, 1);
    text("--install", SCREEN_CX, y + 72, 1, white, 1);
    text_lower = 0;
}

/* "UNDER THE HOOD" (hood.h): the last run of a ROM, and the spots of
   its last HOOD_BARS runs as bars, the latest white. */
#define HOOD_BARS 10
#define HOOD_BAR_W 8
#define HOOD_BAR_GAP 3
#define HOOD_BAR_H 12
#define HOOD_BAR_BOTTOM 58                  /* below the screen's top */
static void draw_hood(long n, const struct hood_run *runs, int count) {
    draw_room(n, 0);
    uint32_t white = ink(INK_TEXT), dim = ink(INK_MANE_HI);
    int y = ART_SCREEN_Y;
    char line[40];
    text_xy("UNDER THE HOOD", SCREEN_CX, y + 2, 1, 2, white, 1);
    if (count == 0) {
        text("PLAY A GAME FIRST", SCREEN_CX, y + 40, 1, dim, 1);
        return;
    }
    const struct hood_run *last = &runs[count - 1];
    if (last->translated >= 0) snprintf(line, sizeof line, "TRANSLATED: %ld", last->translated);
    else snprintf(line, sizeof line, "TRANSLATED: ?");
    text(line, SCREEN_CX, y + 19, 1, white, 1);
    char share[16];
    hood_share(last, share, sizeof share);
    snprintf(line, sizeof line, "RAN AS C: %s", share);
    text(line, SCREEN_CX, y + 28, 1, white, 1);
    snprintf(line, sizeof line, "RUN %d, SPOTS: %ld", last->run, last->spots);
    text(line, SCREEN_CX, y + 37, 1, white, 1);
    /* The bars: each run's spots against the most of those shown; a run
       with none still gets a line, so it shows. */
    int first = count > HOOD_BARS ? count - HOOD_BARS : 0, shown = count - first;
    long most = 1;
    for (int i = first; i < count; i++) if (runs[i].spots > most) most = runs[i].spots;
    int width = shown * (HOOD_BAR_W + HOOD_BAR_GAP) - HOOD_BAR_GAP;
    int x0 = SCREEN_CX - width / 2;
    for (int i = first; i < count; i++) {
        int h = (int)((runs[i].spots * HOOD_BAR_H + most - 1) / most);
        if (h < 1) h = 1;
        uint32_t c = i == count - 1 ? white : ink(INK_NEON);
        int bx = x0 + (i - first) * (HOOD_BAR_W + HOOD_BAR_GAP);
        for (int yy = y + HOOD_BAR_BOTTOM - h; yy < y + HOOD_BAR_BOTTOM; yy++)
            for (int xx = bx; xx < bx + HOOD_BAR_W; xx++) canvas[yy][xx] = c;
    }
    text("A SPOT: WHERE THE", SCREEN_CX, y + 60, 1, dim, 1);
    text("INTERPRETER STARTED", SCREEN_CX, y + 69, 1, dim, 1);
    text("C: SEE THE CODE", SCREEN_CX, y + 78, 1, white, 1);
}

/* ---- the 6502 next to its C (code.h; PLAN-standalone.md step 8), on
   the finer canvas: a title bar, then a row for each line of C, each
   instruction's 6502 on the first row of its C (the cursor's rows
   lit), and a bar of keys and the cursor's instruction in plain
   English. ---- */
#define CODE_TOP 33                         /* the first row's y */
#define CODE_ROW 9
#define CODE_ROWS ((CODE_H - 20 - CODE_TOP) / CODE_ROW)
#define CODE_ADDR_X 8
#define CODE_BYTES_X (CODE_ADDR_X + 6 * 6)
#define CODE_TEXT_X (CODE_BYTES_X + 10 * 6)
#define CODE_C_X 212
#define CODE_C_CHARS ((CODE_W - 8 - CODE_C_X) / 6)

static void text_left(const char *s, int x, int y, uint32_t colour) {
    text(s, x + ((int)strlen(s) * 6 - 1) / 2, y, 1, colour, 0);
}

static void fill(int x0, int y0, int x1, int y1, uint32_t colour) {
    for (int y = y0; y < y1; y++)
        for (int x = x0; x < x1; x++) code_canvas[y][x] = colour;
}

static void draw_code(const struct code_view *v, const char *name) {
    tgt = &code_canvas[0][0]; tgt_w = CODE_W; tgt_h = CODE_H;
    text_lower = 1;
    uint32_t white = ink(INK_TEXT), dim = ink(INK_MANE_HI), neon = ink(INK_NEON);
    fill(0, 0, CODE_W, CODE_H, ink(INK_SCREEN));
    fill(0, 0, CODE_W, 18, ink(INK_BLACK));
    fill(0, CODE_H - 18, CODE_W, CODE_H, ink(INK_BLACK));
    text_left("UNDER THE HOOD: THE 6502 AND THE C IT BECAME", 8, 6, white);
    text_left(name, CODE_W - 8 - 6 * (int)strlen(name) + 1, 6, dim);
    text_left("6502", CODE_ADDR_X, 22, dim);
    text_left("C", CODE_C_X, 22, dim);
    int row = 0;
    for (long i = v->top; i < v->n && row < CODE_ROWS; i++) {
        const struct code_insn *in = &v->insns[i];
        long rows = code_rows(v, i);
        int y = CODE_TOP + row * CODE_ROW;
        if (i == v->cursor) {
            long shown = rows < CODE_ROWS - row ? rows : CODE_ROWS - row;
            fill(0, y - 1, CODE_W, y - 1 + (int)shown * CODE_ROW, ink(INK_SHADOW));
        }
        char addr[8];
        snprintf(addr, sizeof addr, "%04lX", in->addr);
        text_left(addr, CODE_ADDR_X, y, in->routine ? neon : white);
        text_left(in->bytes, CODE_BYTES_X, y, dim);
        text_left(in->text, CODE_TEXT_X, y, white);
        long nc = code_c_count(v, i);
        for (long k = 0; k < nc && row + k < CODE_ROWS; k++) {
            char line[CODE_C_CHARS + 1];
            const char *c = code_c_line(v, i, k);
            if ((int)strlen(c) > CODE_C_CHARS) snprintf(line, sizeof line, "%.*s..", CODE_C_CHARS - 2, c);
            else snprintf(line, sizeof line, "%s", c);
            text_left(line, CODE_C_X, y + (int)k * CODE_ROW, k == 0 ? dim : white);
        }
        row += (int)rows;
    }
    text_left("UP, DOWN: SCROLL   TAB: NEXT ROUTINE   ESC: BACK", 8, CODE_H - 12, dim);
    if (v->n) {
        const struct code_insn *in = &v->insns[v->cursor];
        char say[80];
        const char *e = code_english(in->text);
        snprintf(say, sizeof say, "%.*s: %s", in->text[0] == '*' ? 4 : 3, in->text, e);
        if (e[0]) text_left(say, CODE_W - 8 - 6 * (int)strlen(say) + 1, CODE_H - 12, white);
    }
    text_lower = 0;
    tgt = &canvas[0][0]; tgt_w = ART_W; tgt_h = ART_H;
}

static void draw_done(long n, const char *name) {
    draw_room(n, 0);
    uint32_t white = ink(INK_TEXT), dim = ink(INK_MANE_HI);
    int y = ART_SCREEN_Y;
    text(name, SCREEN_CX, y + 8, 1, dim, 1);
    text("DONE!", SCREEN_CX, y + 24, 2, white, 1);
    text("BUILT AND READY", SCREEN_CX, y + 48, 1, white, 1);
    text("DROP ANOTHER FILE", SCREEN_CX, y + 70, 1, dim, 1);
}

static void draw_about(long n) {
    draw_room(n, 0);
    uint32_t white = ink(INK_TEXT), dim = ink(INK_MANE_HI);
    int y = ART_SCREEN_Y;
    text_xy("NES RECOMP", SCREEN_CX, y + 3, 1, 2, white, 1);
    text("FOR EDUCATIONAL", SCREEN_CX, y + 21, 1, dim, 1);
    text("PURPOSES ONLY", SCREEN_CX, y + 30, 1, dim, 1);
    text("BY SERGE AND CLAUDE", SCREEN_CX, y + 42, 1, white, 1);
    text("FREE SOFTWARE UNDER", SCREEN_CX, y + 54, 1, dim, 1);
    text("THE MIT LICENSE", SCREEN_CX, y + 63, 1, dim, 1);
    text("SUPPORT IT: PRESS D", SCREEN_CX, y + 74, 1, ink(INK_NEON), 1);   /* support.h; inside the glass's curve */
}

/* The keys, before a game (or a music file) starts: key, what it does. */
static const char *const card_game[][2] = {
    { "ARROWS", "D-PAD" }, { "X", "A BUTTON" }, { "Z", "B BUTTON" },
    { "RETURN", "START" }, { "R.SHIFT", "SELECT" }, { "M", "MUTE" },
    { "R", "RESET" }, { "V", "RECORD" }, { "ESC", "MENU" }, { NULL, NULL },
};
/* The second card, after a game's controls (PLAN-savestates.md step 5):
   save states, rewind, fast-forward. The keys as each keyboard names
   them: the Mac's Backspace key says "delete". Then a game controller's
   (PLAN-pause.md step 2): the shoulders, and Select+Start held for the
   menu. Last, where the keys and pads are changed: the pause menu's
   CONTROLLERS page (PLAN-controllers.md step 5; CONTROLLERS itself
   doesn't fit the column). */
static const char *const card_states[][2] = {
#ifdef _WIN32
    { "CTRL+S", "SAVE" }, { "CTRL+L", "LOAD" }, { "CTRL+1-4", "SLOT 1-4" },
    { "BKSPACE", "REWIND" },
#else
    { "CMD+S", "SAVE" }, { "CMD+L", "LOAD" }, { "CMD+1-4", "SLOT 1-4" },
    { "DELETE", "REWIND" },
#endif
    { "` KEY", "FAST X4" }, { "PAD LB", "REWIND" }, { "PAD RB", "FAST X4" },
    { "SEL+ST", "MENU" }, { "MENU", "KEYS+PADS" }, { NULL, NULL },
};
static const char *const card_music[][2] = {
    { "LEFT", "LAST SONG" }, { "RIGHT", "NEXT SONG" }, { "R", "RESTART" },
    { "M", "MUTE" }, { "V", "RECORD" }, { "ESC", "QUIT" }, { NULL, NULL },
};
#define CARD_KEY_X (ART_SCREEN_X + 9)       /* the two columns */
#define CARD_DO_X (ART_SCREEN_X + 57)

/* Text starting at x (not centred). */
static void text_at(const char *s, int x, int y, uint32_t colour) {
    text(s, x + ((int)strlen(s) * 6 - 1) / 2, y, 1, colour, 1);
}

/* which: CARD_GAME, CARD_MUSIC or CARD_STATES. */
enum { CARD_GAME, CARD_MUSIC, CARD_STATES };
static void draw_card(long n, int which) {
    draw_room(n, 0);
    uint32_t white = ink(INK_TEXT), dim = ink(INK_MANE_HI);
    int y = ART_SCREEN_Y;
    int music = which == CARD_MUSIC;
    const char *title = music ? "MUSIC PLAYER" : which == CARD_STATES ? "SAVE AND REWIND" : "CONTROLS";
    const char *const (*rows)[2] = music ? card_music : which == CARD_STATES ? card_states : card_game;
    int n_rows = 0;
    while (rows[n_rows][0]) n_rows++;
    /* Nine rows (the game's, with V) only fit under a title of one
       height. */
    int top = 20;
    if (n_rows > 8) {
        text(title, SCREEN_CX, y + 2, 1, white, 1);
        top = 12;
    } else
        text_xy(title, SCREEN_CX, y + 3, 1, 2, white, 1);
    text_lower = 1;                     /* the ` key */
    for (int i = 0; rows[i][0]; i++) {
        text_at(rows[i][0], CARD_KEY_X, y + top + i * 8, white);
        text_at(rows[i][1], CARD_DO_X, y + top + i * 8, dim);
    }
    text_lower = 0;
}

static void draw_play(long n, const char *name) {
    draw_room(n, 0);
    uint32_t white = ink(INK_TEXT), dim = ink(INK_MANE_HI);
    int y = ART_SCREEN_Y;
    text(name, SCREEN_CX, y + 14, 1, dim, 1);
    text_xy("NOW PLAYING", SCREEN_CX, y + 30, 1, 2, white, 1);
    text("QUIT THE GAME TO", SCREEN_CX, y + 58, 1, dim, 1);
    text("COME BACK HERE", SCREEN_CX, y + 67, 1, dim, 1);
}

/* The canvas into a window of w x h pixels: the largest whole-number
   scale that fits (at least 1, cropped if the window is smaller), centred
   on a dark border. */
static void layout_for(int cw, int ch, int w, int h, int *scale, int *ox, int *oy) {
    int sx = w / cw, sy = h / ch;
    *scale = sx < sy ? sx : sy;
    if (*scale < 1) *scale = 1;
    *ox = (w - cw * *scale) / 2;
    *oy = (h - ch * *scale) / 2;
}
static void layout(int w, int h, int *scale, int *ox, int *oy) {
    layout_for(ART_W, ART_H, w, h, scale, ox, oy);
}

/* Is the window pixel (x, y), in a window of w x h pixels, on the TV's
   screen? (A click there opens the file picker.) */
static int on_tv(int x, int y, int w, int h) {
    int scale, ox, oy;
    layout(w, h, &scale, &ox, &oy);
    int cx = (x - ox) / scale - (x < ox), cy = (y - oy) / scale - (y < oy);
    return cx >= ART_SCREEN_X && cx < ART_SCREEN_X + ART_SCREEN_W &&
           cy >= ART_SCREEN_Y && cy < ART_SCREEN_Y + ART_SCREEN_H;
}

static int show_code;                   /* present the code view's canvas */

static void present(uint32_t *out, int w, int h) {
    int cw = show_code ? CODE_W : ART_W, ch = show_code ? CODE_H : ART_H;
    const uint32_t *pix = show_code ? &code_canvas[0][0] : &canvas[0][0];
    int scale, ox, oy;
    layout_for(cw, ch, w, h, &scale, &ox, &oy);
    uint32_t border = ink(INK_LETTERBOX);
    for (int y = 0; y < h; y++) {
        int cy = y - oy;
        uint32_t *row = out + (size_t)y * w;
        if (cy < 0 || cy >= ch * scale) {
            for (int x = 0; x < w; x++) row[x] = border;
            continue;
        }
        const uint32_t *src = pix + (size_t)(cy / scale) * cw;
        for (int x = 0; x < w; x++) {
            int cx = x - ox;
            row[x] = (cx < 0 || cx >= cw * scale) ? border : src[cx / scale];
        }
    }
}

/* ---- a PNG of w x h pixels (RGB), through zlib ---- */

static void put32(uint8_t *p, uint32_t v) {
    p[0] = v >> 24; p[1] = v >> 16; p[2] = v >> 8; p[3] = (uint8_t)v;
}

static void chunk(FILE *f, const char *type, const uint8_t *data, uint32_t len) {
    uint8_t b[4];
    put32(b, len);
    fwrite(b, 1, 4, f);
    fwrite(type, 1, 4, f);
    if (len) fwrite(data, 1, len, f);
    uLong crc = crc32(0, (const Bytef *)type, 4);
    if (len) crc = crc32(crc, data, len);
    put32(b, (uint32_t)crc);
    fwrite(b, 1, 4, f);
}

static int save_png(const char *path, const uint32_t *px, int w, int h) {
    size_t row = 1 + (size_t)w * 3, rawlen = row * h;
    uint8_t *raw = malloc(rawlen);
    for (int y = 0; y < h; y++) {
        uint8_t *r = raw + y * row;
        r[0] = 0;
        for (int x = 0; x < w; x++) {
            uint32_t c = px[(size_t)y * w + x];
            r[1 + x * 3] = c >> 16; r[2 + x * 3] = c >> 8; r[3 + x * 3] = (uint8_t)c;
        }
    }
    uLongf packed_len = compressBound(rawlen);
    uint8_t *packed = malloc(packed_len);
    int ok = compress(packed, &packed_len, raw, rawlen) == Z_OK;
    FILE *f = ok ? fopen(path, "wb") : NULL;
    if (f) {
        fwrite("\x89PNG\r\n\x1a\n", 1, 8, f);
        uint8_t ihdr[13];
        put32(ihdr, (uint32_t)w); put32(ihdr + 4, (uint32_t)h);
        ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = ihdr[11] = ihdr[12] = 0;
        chunk(f, "IHDR", ihdr, 13);
        chunk(f, "IDAT", packed, (uint32_t)packed_len);
        chunk(f, "IEND", NULL, 0);
        ok = fclose(f) == 0;
    } else {
        ok = 0;
    }
    free(raw); free(packed);
    if (!ok) perror(path);
    return ok ? 0 : -1;
}

/* What a screenshot shows. */
static struct {
    const char *show, *rom, *message, *history, *listing, *cfile, *keys;
    int stage;
    double progress;
} shot_opts = { "drop", "GAME.NES", "NOT AN NES ROM", NULL, NULL, NULL, NULL, ST_RECOMP, 0.5 };
static struct code_view code;
static char code_name[64];

/* Keys for the code view, as words: up, down, pgup, pgdn, tab. */
static void code_keys(const char *keys) {
    char buf[1024];
    snprintf(buf, sizeof buf, "%s", keys ? keys : "");
    for (char *k = strtok(buf, " ,"); k; k = strtok(NULL, " ,")) {
        if (!strcmp(k, "up")) code_move(&code, CODE_UP);
        else if (!strcmp(k, "down")) code_move(&code, CODE_DOWN);
        else if (!strcmp(k, "pgup")) code_move(&code, CODE_PAGE_UP);
        else if (!strcmp(k, "pgdn")) code_move(&code, CODE_PAGE_DOWN);
        else if (!strcmp(k, "tab")) code_move(&code, CODE_TAB);
    }
}
static struct hood_run hood_runs[HOOD_MAX];
static int hood_count;

static int screenshot(const char *path, long frame, int w, int h) {
    uint32_t *out = malloc((size_t)w * h * 4);
    char name[64];
    screen_name(shot_opts.rom, name, sizeof name);
    if (!strcmp(shot_opts.show, "build")) draw_build(frame, name, shot_opts.stage, shot_opts.progress);
    else if (!strcmp(shot_opts.show, "error")) draw_error(frame, "CAN'T RECOMPILE", shot_opts.message);
    else if (!strcmp(shot_opts.show, "stopped")) draw_error(frame, "THE GAME STOPPED", shot_opts.message);
    else if (!strcmp(shot_opts.show, "done")) draw_done(frame, name);
    else if (!strcmp(shot_opts.show, "needcc")) draw_needcc(frame, 0);
    else if (!strcmp(shot_opts.show, "code")) {
        if (!shot_opts.listing || !shot_opts.cfile ||
            code_load(&code, shot_opts.listing, shot_opts.cfile, CODE_ROWS)) {
            fprintf(stderr, "--show code needs a --listing and --cfile that can be read\n");
            free(out);
            return 1;
        }
        code_keys(shot_opts.keys);
        draw_code(&code, name);
        show_code = 1;
    }
    else if (!strcmp(shot_opts.show, "hood")) {
        hood_count = shot_opts.history ? hood_load(shot_opts.history, hood_runs, HOOD_MAX) : 0;
        draw_hood(frame, hood_runs, hood_count);
    }
    else if (!strcmp(shot_opts.show, "needcc_clicked")) draw_needcc(frame, 1);
    else if (!strcmp(shot_opts.show, "play")) draw_play(frame, name);
    else if (!strcmp(shot_opts.show, "about")) draw_about(frame);
    else if (!strcmp(shot_opts.show, "card")) draw_card(frame, CARD_GAME);
    else if (!strcmp(shot_opts.show, "card_music")) draw_card(frame, CARD_MUSIC);
    else if (!strcmp(shot_opts.show, "card_states")) draw_card(frame, CARD_STATES);
    else draw_drop(frame);
    present(out, w, h);
    int r = save_png(path, out, w, h);
    free(out);
    return r;
}

static void usage(const char *prog) {
    fprintf(stderr, "usage: %s [ROM] [--build ROM] [--build-dir D]\n"
                    "       %s --screenshot FILE [--frames N] [--size WxH] [--show SCREEN]\n"
                    "          [--rom NAME] [--stage N] [--progress P] [--message M]\n", prog, prog);
    exit(1);
}

/* The window's state. */
enum { S_DROP, S_BUILD, S_ERROR, S_DONE, S_PLAY, S_STOPPED, S_ABOUT, S_CARD, S_NEEDCC, S_HOOD,
       S_CODE };
static const char *const screen_names[] = {
    "drop", "build", "error", "done", "play", "stopped", "about", "card", "needcc", "hood", "code",
};
#define CARD_FRAMES 150                 /* the controls card: 2.5 seconds */
static struct build job;
static int screen = S_DROP;
static char error_msg[512], shown_name[64], game_log[PATH_MAX + 16];
static os_proc game = -1;
static char builds[PATH_MAX];           /* the build folder */

/* After a game: its run into its history, and the last game's name kept
   for H (last-game.txt). */
static int add_run(const struct build *b, const char *log, struct hood_run *added) {
    char last[PATH_MAX + 16];
    snprintf(last, sizeof last, "%s/last-game.txt", builds);
    FILE *f = fopen(last, "w");
    if (f) { fprintf(f, "%s\n", b->name); fclose(f); }
    return hood_add(builds, b->name, b->translated, log, added);
}

/* The last game's history, for H. */
static void load_last_history(void) {
    char last[PATH_MAX + 16], name[256] = "", path[PATH_MAX + 300];
    snprintf(last, sizeof last, "%s/last-game.txt", builds);
    FILE *f = fopen(last, "r");
    if (f) { if (!fgets(name, sizeof name, f)) name[0] = 0; fclose(f); }
    name[strcspn(name, "\r\n")] = 0;
    snprintf(path, sizeof path, "%s/%s.history", builds, name);
    hood_count = name[0] ? hood_load(path, hood_runs, HOOD_MAX) : 0;
    snprintf(code_name, sizeof code_name, "%s", name);
}

/* C on "under the hood": the last game's listing and C. */
static int open_code(void) {
    char lst[PATH_MAX + 300], cf[PATH_MAX + 300];
    snprintf(lst, sizeof lst, "%s/%s.listing", builds, code_name);
    snprintf(cf, sizeof cf, "%s/%s.c", builds, code_name);
    code_free(&code);
    return code_name[0] && code_load(&code, lst, cf, CODE_ROWS) == 0;
}
static long card_until;
static int card_is_music;
static int card_page;                   /* a game's: 0 the controls, 1 save and rewind */
static char prefs[PATH_MAX];            /* app-prefs.txt in the build folder */
static char controls[PATH_MAX];         /* controls.txt beside it: the game's keys */

/* The game window's size (whole steps of 256x240) and the speakers'
   volume (1-10, and whether the sound is off), kept between runs: the
   game writes them on exit (--remember-size), one "name value" a line. */
static struct { int scale, volume, sound_off; } game_prefs;

static void read_game_prefs(void);

/* What a game is started with from the app: the size and volume last
   remembered, where to remember them, and its keys (controls.txt). */
#define GAME_ARGS 12
static void game_args(char **args, const char *files_at, const char *rom) {
    static char scale[16], volume[16];
    read_game_prefs();
    snprintf(scale, sizeof scale, "%d", game_prefs.scale);
    snprintf(volume, sizeof volume, "%d", game_prefs.volume);
    int na = 0;
    args[na++] = "--scale"; args[na++] = scale;
    args[na++] = "--remember-size"; args[na++] = prefs;
    args[na++] = "--volume"; args[na++] = volume;
    args[na++] = "--controls"; args[na++] = controls;
    if (game_prefs.sound_off) args[na++] = "--sound-off";
    if (strcmp(files_at, rom)) { args[na++] = "--files-at"; args[na++] = (char *)files_at; }
    args[na] = NULL;
}

static void read_game_prefs(void) {
    game_prefs.scale = 3;
    game_prefs.volume = 10;
    game_prefs.sound_off = 0;
    FILE *f = fopen(prefs, "r");
    if (!f) return;
    char name[32];
    int v;
    while (fscanf(f, "%31s %d", name, &v) == 2) {
        if (!strcmp(name, "game_scale") && v >= 1 && v <= 16) game_prefs.scale = v;
        else if (!strcmp(name, "volume") && v >= 1 && v <= 10) game_prefs.volume = v;
        else if (!strcmp(name, "sound_off")) game_prefs.sound_off = v != 0;
    }
    fclose(f);
}

/* ---- the file picker (a click on the TV), on a thread of its own: the
   system's standard box (os_pick_file), so the window keeps drawing
   while it is open ---- */
static atomic_int picker;               /* 0 idle, 1 open, 2 a file chosen */
static char picked[PATH_MAX];

static void picker_main(void *arg) {
    (void)arg;
    char line[PATH_MAX];
    if (os_pick_file(line, sizeof line)) {
        snprintf(picked, sizeof picked, "%s", line);
        atomic_store(&picker, 2);
    } else {
        atomic_store(&picker, 0);       /* cancelled */
    }
}

static void open_picker(void) {
    int idle = 0;
    if (!atomic_compare_exchange_strong(&picker, &idle, 1)) return;
    if (os_thread(picker_main, NULL)) atomic_store(&picker, 0);
}

/* Split ARGS at spaces into a NULL-ended list (for the game), then
   --files-at FILES when the game's .missed and .sav aren't beside the
   ROM (build.c). */
static char **split_args(const char *s, const char *rom, const char *files) {
    static char buf[1024];
    static char *list[34];
    int n = 0;
    snprintf(buf, sizeof buf, "%s", s ? s : "");
    for (char *p = strtok(buf, " "); p && n < 31; p = strtok(NULL, " ")) list[n++] = p;
    if (files && files[0] && strcmp(files, rom)) {
        list[n++] = "--files-at";
        list[n++] = (char *)files;
    }
    list[n] = NULL;
    return list;
}

/* Play exe on rom, wait for it, and say how it ended: 0 when well. */
static int play_and_wait(const char *exe, const char *rom, const char *args, const char *files,
                         const char *log) {
    char why[512];
    os_proc pid = play_start(exe, rom, split_args(args, rom, files), log);
    if (pid < 0) {
        printf("error: couldn't start the game (%s)\n", exe);
        return 1;
    }
    int r = play_poll(pid, log, 1, why, sizeof why);
    if (r > 0) printf("played: the game ended well\n");
    else printf("error: %s\n", why);
    return r > 0 ? 0 : 1;
}

static int install_clicked;             /* the needcc screen: Apple's installer started */

/* A key on the About screen: D opens the support page (support.h); any
   other leaves. Returns 1 for D. */
static int about_key_supports(int key) {
    return key == 'd' || key == 'D';
}

/* The screen after a failed build: the compiler's own, or the error. */
static int failed_screen(const struct build *b) {
    return b->no_compiler ? S_NEEDCC : S_ERROR;
}

/* What a click at window pixel (x, y), in a window of w x h pixels, does
   on screen s. */
enum { ACT_NONE, ACT_PICKER, ACT_INSTALL, ACT_LEAVE };
static const char *const act_names[] = { "nothing", "file picker", "install", "leave" };
static int click_action(int s, int x, int y, int w, int h) {
    if (s == S_ABOUT || s == S_HOOD) return ACT_LEAVE;
    if (!on_tv(x, y, w, h)) return ACT_NONE;
    if (s == S_NEEDCC) return ACT_INSTALL;
    if (s == S_DROP || s == S_ERROR || s == S_DONE || s == S_STOPPED) return ACT_PICKER;
    return ACT_NONE;
}

/* Start Apple's installer of the Command Line Tools: `xcode-select
   --install` opens its own box. With `wait`, wait for it and give its
   exit status; otherwise a thread waits, so it leaves no zombie. (On
   Windows there's nothing to install: the app brings its compiler.) */
#ifdef _WIN32
static int install_tools(int wait) { (void)wait; return -1; }
#else
extern char **environ;

static void *reap(void *arg) {
    int status;
    pid_t pid = (pid_t)(intptr_t)arg;
    while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {}
    return NULL;
}
static int install_tools(int wait) {
    char *argv[] = { (char *)build_xcode_select(), "--install", NULL };
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_addopen(&fa, 1, "/dev/null", O_WRONLY, 0);
    posix_spawn_file_actions_addopen(&fa, 2, "/dev/null", O_WRONLY, 0);
    pid_t pid;
    int err = posix_spawn(&pid, argv[0], &fa, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&fa);
    if (err) return -1;
    if (wait) {
        int status;
        while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {}
        return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    }
    pthread_t t;
    if (pthread_create(&t, NULL, reap, (void *)(intptr_t)pid) == 0) pthread_detach(t);
    return 0;
}
#endif

/* A file arrived (dropped, or on the command line). */
static void take(const char *path) {
    if (screen == S_BUILD || screen == S_PLAY || screen == S_CARD) return;  /* busy */
    char why[128];
    screen_name(path, shown_name, sizeof shown_name);
    if (!build_check_file(path, why, sizeof why)) {
        snprintf(error_msg, sizeof error_msg, "%s", why);
        screen = S_ERROR;
        return;
    }
    build_start(&job, path);
    screen = S_BUILD;
}

int main(int argc, char **argv) {
    const char *shot = NULL, *build_rom = NULL, *open_rom = NULL, *bdir = NULL;
    int trace = 0, model = 0, then_play = 0, hit = 0, hw = 0, hh = 0, hx = 0, hy = 0;
    int sdl_info = 0;
    const char *play_args = NULL, *play_exe = NULL, *play_rom = NULL, *click_screen = NULL;
    int click = 0, cw = 0, ch = 0, cx = 0, cy = 0, menu_test = 0, choose_support = 0;
    const char *key_screen = NULL, *key_name = NULL;
    long frames = 0;
    int sw = ART_W, sh = ART_H;
    for (int i = 1; i < argc; i++) {
        int more = i + 1 < argc;
        if (!strcmp(argv[i], "--screenshot") && more) shot = argv[++i];
        else if (!strcmp(argv[i], "--frames") && more) frames = strtol(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--size") && more) {
            if (sscanf(argv[++i], "%dx%d", &sw, &sh) != 2 || sw < 1 || sh < 1) usage(argv[0]);
        }
        else if (!strcmp(argv[i], "--show") && more) shot_opts.show = argv[++i];
        else if (!strcmp(argv[i], "--rom") && more) shot_opts.rom = argv[++i];
        else if (!strcmp(argv[i], "--stage") && more) shot_opts.stage = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--progress") && more) shot_opts.progress = atof(argv[++i]);
        else if (!strcmp(argv[i], "--message") && more) shot_opts.message = argv[++i];
        else if (!strcmp(argv[i], "--history") && more) shot_opts.history = argv[++i];
        else if (!strcmp(argv[i], "--listing") && more) shot_opts.listing = argv[++i];
        else if (!strcmp(argv[i], "--cfile") && more) shot_opts.cfile = argv[++i];
        else if (!strcmp(argv[i], "--keys") && more) shot_opts.keys = argv[++i];
        else if (!strcmp(argv[i], "--build") && more) build_rom = argv[++i];
        else if (!strcmp(argv[i], "--build-dir") && more) bdir = argv[++i];
        else if (!strcmp(argv[i], "--trace-progress")) trace = 1;
        else if (!strcmp(argv[i], "--progress-model")) model = 1;
        else if (!strcmp(argv[i], "--sdl-info")) sdl_info = 1;
        else if (!strcmp(argv[i], "--game-prefs") && more) {
            /* For tests: what the next game would be given from a prefs file. */
            snprintf(prefs, sizeof prefs, "%s", argv[++i]);
            read_game_prefs();
            printf("scale %d volume %d sound_off %d\n", game_prefs.scale, game_prefs.volume,
                   game_prefs.sound_off);
            return 0;
        }
        else if (!strcmp(argv[i], "--game-args") && more) {
            /* For tests: what a game would be started with, from a build folder. */
            const char *d = argv[++i];
            snprintf(prefs, sizeof prefs, "%s/app-prefs.txt", d);
            snprintf(controls, sizeof controls, "%s/controls.txt", d);
            char *args[GAME_ARGS];
            game_args(args, "game.nes", "game.nes");
            for (int k = 0; args[k]; k++) printf("%s%s", k ? " " : "", args[k]);
            printf("\n");
            return 0;
        }
        else if (!strcmp(argv[i], "--version")) { puts(APP_VERSION); return 0; }
        else if (!strcmp(argv[i], "--support-url")) { puts(SUPPORT_URL); return 0; }
        else if (!strcmp(argv[i], "--menu-test")) menu_test = 1;
        else if (!strcmp(argv[i], "--choose-support")) choose_support = 1;
        else if (!strcmp(argv[i], "--key-test") && i + 2 < argc) {
            key_screen = argv[++i];
            key_name = argv[++i];
        }
        else if (!strcmp(argv[i], "--then-play")) then_play = 1;
        else if (!strcmp(argv[i], "--hit-test") && i + 3 < argc) {
            hit = sscanf(argv[i + 1], "%dx%d", &hw, &hh) == 2;
            hx = atoi(argv[i + 2]); hy = atoi(argv[i + 3]);
            i += 3;
            if (!hit) usage(argv[0]);
        }
        else if (!strcmp(argv[i], "--play-args") && more) play_args = argv[++i];
        else if (!strcmp(argv[i], "--click-test") && i + 4 < argc) {
            click_screen = argv[++i];
            click = sscanf(argv[i + 1], "%dx%d", &cw, &ch) == 2;
            cx = atoi(argv[i + 2]); cy = atoi(argv[i + 3]);
            i += 3;
            if (!click) usage(argv[0]);
        }
        else if (!strcmp(argv[i], "--play-only") && i + 2 < argc) {
            play_exe = argv[++i];
            play_rom = argv[++i];
        }
        else if (argv[i][0] != '-' && !open_rom) open_rom = argv[i];
        else usage(argv[0]);
    }
    if (shot) return screenshot(shot, frames, sw, sh) ? 1 : 0;
    if (hit) { puts(on_tv(hx, hy, hw, hh) ? "tv" : "outside"); return 0; }
    if (key_screen) {
        /* A key on a screen, as the window takes it (the About screen's
           D, for now): what it does, and run it. */
        if (!strcmp(key_screen, "about") && about_key_supports(key_name[0]) && !key_name[1])
            printf("key: support (%s), open ended %d\n", SUPPORT_URL, support_open());
        else if (!strcmp(key_screen, "about"))
            printf("key: leave\n");
        else usage(argv[0]);
        return 0;
    }
    if (menu_test) {
        /* The app menu SDL makes, with the support item added: its titles,
           and with --choose-support, what choosing it does. No window. */
        if (SDL_Init(SDL_INIT_VIDEO) != 0) { fprintf(stderr, "SDL_Init: %s\n", SDL_GetError()); return 1; }
        SDL_Window *mw = NULL;
#ifdef _WIN32
        /* Windows's menu is the window's: a window, never shown. */
        mw = SDL_CreateWindow("nesrecomp", 0, 0, ART_W, ART_H, SDL_WINDOW_HIDDEN);
#endif
        int added = support_menu_add(mw);
        char titles[2048];
        support_menu_titles(titles, sizeof titles);
        printf("added %d\n%s", added, titles);
        if (choose_support) printf("chose: %d\n", support_menu_choose());
        if (mw) SDL_DestroyWindow(mw);
        SDL_Quit();
        return 0;
    }
    if (click) {
        /* A click on a screen, as the window takes it: what it does, and
           for the installer, run it and say how it ended. */
        int s = -1;
        for (int k = 0; k < (int)(sizeof screen_names / sizeof *screen_names); k++)
            if (!strcmp(click_screen, screen_names[k])) s = k;
        if (s < 0) usage(argv[0]);
        int a = click_action(s, cx, cy, cw, ch);
        printf("click: %s\n", act_names[a]);
        if (a == ACT_INSTALL) printf("ran: %s --install (exit %d)\n", build_xcode_select(), install_tools(1));
        return 0;
    }
    if (model) {
        /* Each stage, with an estimate of 1 s, from 0 to 60 s; the
           runtime stage at each count of 15 files; then done. */
        atomic_store(&job.state, B_RUNNING);
        for (int st = 0; st < ST_COUNT; st++) {
            atomic_store(&job.stage, st);
            job.stage_start = 0;
            job.estimate = 1.0;
            atomic_store(&job.rt_total, 15);
            for (int k = 0; k <= 600; k++) {
                if (st == ST_RUNTIME) atomic_store(&job.rt_done, k <= 15 ? k : 15);
                printf("%d %.1f %.6f\n", st, k / 10.0, build_progress(&job, k / 10.0));
            }
        }
        atomic_store(&job.state, B_DONE);
        printf("done %.6f\n", build_progress(&job, 0));
        return 0;
    }

    /* Opened from Finder or the Dock, a Mac app may get no PATH at all:
       then the system's, where Apple's cc is. (Every other file it uses
       is given by its full path.) */
#ifndef _WIN32
    const char *path = getenv("PATH");
    if (!path || !*path) setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin", 1);
#endif

    /* Where builds go: the app's folder (in Application Support on the
       Mac, %LOCALAPPDATA% on Windows), or $NESRECOMP_ROOT/build when
       working on the project (make run-app), or --build-dir. */
    const char *root = getenv("NESRECOMP_ROOT");
    char defdir[PATH_MAX];
    if (root && *root) snprintf(defdir, sizeof defdir, "%s/build", root);
    else os_app_dir(defdir, sizeof defdir);
    const char *dir = bdir ? bdir : defdir;
    build_setup(dir);
    /* The app's own SDL2, recompiler and runtime, found from where the
       program is. */
    char exe_real[PATH_MAX];
    if (os_exe_path(exe_real, sizeof exe_real))
        snprintf(exe_real, sizeof exe_real, "%s", argv[0]);
    int have_sdl = build_find_parts(exe_real, root);
    if (sdl_info) {
        printf("sdl2 %s %s\n", have_sdl ? "found" : "missing", build_sdl_lib());
        printf("recompiler %s\n", build_recompiler());
        printf("runtime %s\n", build_runtime());
        printf("builds %s\n", dir);
        char cc_at[PATH_MAX];
        printf("compiler %s\n", build_have_compiler(cc_at, sizeof cc_at) ? cc_at : "missing");
        return have_sdl ? 0 : 1;
    }
    os_make_dirs(dir);                          /* it, and the folders above it */
    snprintf(prefs, sizeof prefs, "%s/app-prefs.txt", dir);
    snprintf(controls, sizeof controls, "%s/controls.txt", dir);
    snprintf(builds, sizeof builds, "%s", dir);
    if (play_exe) {
        snprintf(game_log, sizeof game_log, "%s.game.log", play_exe);
        return play_and_wait(play_exe, play_rom, play_args, NULL, game_log);
    }
    if (build_rom) {
        job.verbose = 1;
        if (then_play) {
            if (build_run(&job, build_rom)) {
                printf("screen: %s\n", screen_names[failed_screen(&job)]);
                return 1;
            }
            snprintf(game_log, sizeof game_log, "%s/%s.game.log", builds, job.name);   /* (no .exe) */
            int pr = play_and_wait(job.out, job.rom, play_args, job.files_at, game_log);
            struct hood_run h;
            if (add_run(&job, game_log, &h) == 0)
                printf("hood: run %d translated %ld spots %ld native %llu interp %llu\n",
                       h.run, h.translated, h.spots, h.native, h.interp);
            return pr;
        }
        if (!trace) {
            if (!build_run(&job, build_rom)) return 0;
            printf("screen: %s\n", screen_names[failed_screen(&job)]);
            return 1;
        }
        build_start(&job, build_rom);
        while (atomic_load(&job.state) == B_RUNNING) {
            printf("progress %.4f stage %d\n", build_progress(&job, build_now()),
                   atomic_load(&job.stage));
            fflush(stdout);
            SDL_Delay(20);
        }
        printf("progress %.4f end\n", build_progress(&job, build_now()));
        return atomic_load(&job.state) == B_DONE ? 0 : 1;
    }

    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
        return 1;
    }
    /* The window opens at twice the canvas (1280x720), or once if that
       doesn't fit the screen (a small laptop's). */
    int open_scale = 2;
    SDL_Rect usable;
    if (SDL_GetDisplayUsableBounds(0, &usable) == 0 && (usable.w < ART_W * 2 || usable.h < ART_H * 2 + 40))
        open_scale = 1;
    SDL_Window *win = SDL_CreateWindow("nesrecomp", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                                       ART_W * open_scale, ART_H * open_scale,
                                       SDL_WINDOW_RESIZABLE | SDL_WINDOW_ALLOW_HIGHDPI);
    SDL_Renderer *ren = win ? SDL_CreateRenderer(win, -1, SDL_RENDERER_PRESENTVSYNC) : NULL;
    if (!ren) {
        fprintf(stderr, "can't open a window: %s\n", SDL_GetError());
        return 1;
    }
    SDL_SetWindowMinimumSize(win, ART_W, ART_H);
    printf("window: %dx%d (%dx the %dx%d room)\n", ART_W * open_scale, ART_H * open_scale, open_scale,
           ART_W, ART_H);
    fflush(stdout);
    support_menu_add(win);              /* "Support NES RECOMP..." in the menu */
    SDL_EventState(SDL_DROPFILE, SDL_ENABLE);
    SDL_Texture *tex = NULL;
    uint32_t *out = NULL;
    int tw = 0, th = 0;
    long n = 0;
    if (open_rom) take(open_rom);
    for (;;) {
        SDL_Event e;
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_QUIT) goto done;
            if (screen == S_CODE && e.type == SDL_KEYDOWN) {
                /* The code view: its own keys; Esc goes back. */
                SDL_Keycode k = e.key.keysym.sym;
                if (k == SDLK_ESCAPE || k == SDLK_BACKSPACE) { screen = S_HOOD; show_code = 0; }
                else if (k == SDLK_UP) code_move(&code, CODE_UP);
                else if (k == SDLK_DOWN) code_move(&code, CODE_DOWN);
                else if (k == SDLK_PAGEUP) code_move(&code, CODE_PAGE_UP);
                else if (k == SDLK_PAGEDOWN || k == SDLK_SPACE) code_move(&code, CODE_PAGE_DOWN);
                else if (k == SDLK_TAB) code_move(&code, CODE_TAB);
                continue;
            }
            if (screen == S_CODE && e.type == SDL_MOUSEWHEEL) {
                for (int k = 0; k < 3; k++) code_move(&code, e.wheel.y > 0 ? CODE_UP : CODE_DOWN);
                continue;
            }
            if (screen == S_CODE && (e.type == SDL_MOUSEBUTTONDOWN || e.type == SDL_DROPFILE)) {
                if (e.type == SDL_DROPFILE) SDL_free(e.drop.file);
                continue;
            }
            if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_ESCAPE) goto done;
            if (e.type == SDL_KEYDOWN && !e.key.repeat) {
                if (screen == S_ABOUT && about_key_supports(e.key.keysym.sym)) support_open();
                else if (screen == S_HOOD && e.key.keysym.sym == SDLK_c) {
                    if (open_code()) { screen = S_CODE; show_code = 1; }
                }
                else if (screen == S_ABOUT || screen == S_HOOD) screen = S_DROP;  /* any key leaves it */
                else if (screen == S_CARD) card_until = 0;  /* any key: the next card, or the game */
                else if (e.key.keysym.sym == SDLK_i &&
                         (screen == S_DROP || screen == S_ERROR || screen == S_DONE ||
                          screen == S_STOPPED || screen == S_NEEDCC))
                    screen = S_ABOUT;
                else if (e.key.keysym.sym == SDLK_h && screen == S_DROP) {
                    load_last_history();
                    screen = S_HOOD;
                }
            }
            if (e.type == SDL_MOUSEBUTTONDOWN && e.button.button == SDL_BUTTON_LEFT) {
                /* Mouse points to window pixels (twice as many on a Retina
                   screen), then what a click there does. */
                int ww, wh, pw, ph;
                SDL_GetWindowSize(win, &ww, &wh);
                SDL_GetRendererOutputSize(ren, &pw, &ph);
                int px = ww ? e.button.x * pw / ww : 0, py = wh ? e.button.y * ph / wh : 0;
                switch (click_action(screen, px, py, pw, ph)) {
                case ACT_LEAVE: screen = S_DROP; break;
                case ACT_PICKER: open_picker(); break;
                case ACT_INSTALL: if (install_tools(0) == 0) install_clicked = 1; break;
                default: break;
                }
            }
            if (e.type == SDL_DROPFILE) {
                if (screen == S_ABOUT) screen = S_DROP;
                take(e.drop.file);
                SDL_free(e.drop.file);
            }
        }
        int w, h;
        SDL_GetRendererOutputSize(ren, &w, &h);
        if (w != tw || h != th) {
            if (tex) SDL_DestroyTexture(tex);
            free(out);
            tex = SDL_CreateTexture(ren, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING, w, h);
            out = malloc((size_t)w * h * 4);
            tw = w; th = h;
        }
        if (atomic_load(&picker) == 2) {
            atomic_store(&picker, 0);
            if (screen == S_ABOUT) screen = S_DROP;
            take(picked);
        }
        if (screen == S_BUILD) {
            int st = atomic_load(&job.state);
            if (st == B_DONE) {
                /* Built: the controls card first, then the game. */
                unsigned char h[5] = { 0 };
                FILE *rf = fopen(job.rom, "rb");
                if (rf) { if (fread(h, 1, 5, rf) != 5) h[0] = 0; fclose(rf); }
                card_is_music = !memcmp(h, "NESM\x1a", 5);
                card_until = n + CARD_FRAMES;
                card_page = 0;
                screen = S_CARD;
            }
            else if (st == B_FAILED) {
                snprintf(error_msg, sizeof error_msg, "%s", job.error);
                screen = failed_screen(&job);
                install_clicked = 0;
            }
        }
        if (screen == S_CARD && n >= card_until && !card_is_music && card_page == 0) {
            card_page = 1;                  /* then save and rewind */
            card_until = n + CARD_FRAMES;
        }
        if (screen == S_CARD && n >= card_until) {
            /* Play it, with this window out of the way, at the size the
               last game's window had. */
            char *args[GAME_ARGS];
            game_args(args, job.files_at, job.rom);
            snprintf(game_log, sizeof game_log, "%s/%s.game.log", builds, job.name);   /* (no .exe) */
            game = play_start(job.out, job.rom, args, game_log);
            if (game < 0) {
                snprintf(error_msg, sizeof error_msg, "couldn't start the game");
                screen = S_STOPPED;
            } else {
                screen = S_PLAY;
                SDL_HideWindow(win);
            }
        }
        if (screen == S_PLAY) {
            char why[512];
            int r = play_poll(game, game_log, 0, why, sizeof why);
            if (r == 0) {
                SDL_Delay(50);                  /* hidden: no need to draw */
                continue;
            }
            game = -1;
            /* Its run into the history; after a game that ended well,
               the numbers. */
            int added = add_run(&job, game_log, NULL) == 0;
            if (r > 0) {
                if (added) { load_last_history(); screen = S_HOOD; }
                else screen = S_DROP;
            } else {
                snprintf(error_msg, sizeof error_msg, "%s", why);
                screen = S_STOPPED;
            }
            SDL_ShowWindow(win);
            SDL_RaiseWindow(win);
        }
        switch (screen) {
        case S_BUILD:
            draw_build(n, shown_name, atomic_load(&job.stage), build_progress(&job, build_now()));
            break;
        case S_ERROR: draw_error(n, "CAN'T RECOMPILE", error_msg); break;
        case S_STOPPED: draw_error(n, "THE GAME STOPPED", error_msg); break;
        case S_NEEDCC: draw_needcc(n, install_clicked); break;
        case S_HOOD: draw_hood(n, hood_runs, hood_count); break;
        case S_CODE: draw_code(&code, code_name); break;
        case S_DONE: draw_done(n, shown_name); break;
        case S_PLAY: draw_play(n, shown_name); break;
        case S_ABOUT: draw_about(n); break;
        case S_CARD: draw_card(n, card_is_music ? CARD_MUSIC : card_page ? CARD_STATES : CARD_GAME); break;
        default: draw_drop(n);
        }
        n++;
        present(out, w, h);
        SDL_UpdateTexture(tex, NULL, out, w * 4);
        SDL_RenderCopy(ren, tex, NULL, NULL);
        SDL_RenderPresent(ren);
    }
done:
    SDL_Quit();
    return 0;
}
