/* nesrecomp app: a window to drop a ROM onto (PLAN-gui.md).

   The window and its screens. The picture (app/art.h, from
   tools/make_app_art.py) is a 320x180 canvas, drawn into the window at
   the largest whole-number scale that fits and centred, with the rest
   of the window in a dark border, so the pixels stay square and sharp.
   The window's pixels are counted in real pixels (a Retina screen has
   twice as many as its points).

   The idle animation: the TV screen's glow rises and falls over about
   four seconds, its scanlines shimmer, and the console's power light
   blinks once a second (fast while a ROM is being built).

   The screens, all on the TV:
     drop    "DROP YOUR NES ROM FILE HERE"
     build   the file's name, "RECOMPILING IN PROGRESS", the loading bar
             and the stage (build.c does the work, on its own thread, so
             the window stays responsive)
     error   "CAN'T RECOMPILE" and why (a wrong file, or the tool's
             message); the whole output is in build/NAME.log
     done    "DONE!": the program is built
     play    the game runs in its own window (play.c) and this one hides;
             when the game quits, back to the drop screen, or, if it
             stopped or crashed, "THE GAME STOPPED" and why
   From the error and done screens, another drop starts again.

       nesrecomp-app [ROM]                    open the window (and build ROM)
       nesrecomp-app --build ROM              build it with no window,
                                              printing each stage
       nesrecomp-app --build ROM --trace-progress
           the same, on the build thread as the window does it, printing
           the loading bar's value every 20 ms
       nesrecomp-app --screenshot F [--frames N] [--size WxH]
                     [--show drop|build|error|done] [--rom NAME]
                     [--stage N] [--progress P] [--message M]
           draw a screen into a window of W x H pixels (default 320x180)
           and save it as a PNG, with no window: for tests/check_app.py
       nesrecomp-app --build ROM --then-play [--play-args "ARGS"]
           build it, then play it (with ARGS for the game, such as
           "--headless --frames 600"), and say how the game ended
       nesrecomp-app --play-only EXE ROM [--play-args "ARGS"]
           just play: run EXE on ROM as the app does, and say how it
           ended (for the checks)
       nesrecomp-app --progress-model
           print the loading bar's value for each stage over a long range
           of times (and runtime file counts), for tests/check_app.py
       --build-dir D   where builds go (default: build/ in the project)
   The project (recomp.py, runtime/) is where `make app` was run, or
   $NESRECOMP_ROOT. */
#include <SDL.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>
#include "art.h"
#include "build.h"
#include "play.h"

#ifndef PROJECT_ROOT
#define PROJECT_ROOT "."
#endif

static uint32_t canvas[ART_H][ART_W];

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

/* sx, sy: the font's pixels are sx wide and sy tall (the build screen's
   tall letters are 1 x 2). */
static void text_pass(const char *s, int cx, int y, int sx, int sy, uint32_t colour, int grow) {
    int len = (int)strlen(s), x0 = cx - (len * 6 * sx - sx) / 2;
    for (int i = 0; i < len; i++) {
        int ch = (unsigned char)s[i];
        if (ch >= 'a' && ch <= 'z') ch -= 32;
        if (ch < 0x20 || ch > 0x5F) ch = '?';
        const unsigned char *g = art_font[ch - 0x20];
        for (int r = 0; r < 7; r++)
            for (int c = 0; c < 5; c++)
                if (g[r] & (0x10 >> c))
                    for (int dy = -grow; dy < sy + grow; dy++)
                        for (int dx = -grow; dx < sx + grow; dx++) {
                            int x = x0 + i * 6 * sx + c * sx + dx, yy = y + r * sy + dy;
                            if (x >= 0 && x < ART_W && yy >= 0 && yy < ART_H)
                                canvas[yy][x] = colour;
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
    const char *base = strrchr(path, '/');
    base = base ? base + 1 : path;
    if (strlen(base) <= LINE_CHARS) snprintf(out, n, "%s", base);
    else snprintf(out, n, "%.*s..", LINE_CHARS - 2, base);
}

static void draw_drop(long n) {
    draw_room(n, 0);
    int cx = SCREEN_CX;
    int top = ART_SCREEN_Y + (ART_SCREEN_H - (3 * 14 + 2 * 6)) / 2;
    uint32_t white = ink(INK_TEXT);
    text("DROP YOUR", cx, top, 2, white, 1);
    text("NES ROM", cx, top + 20, 2, white, 1);
    text("FILE HERE", cx, top + 40, 2, white, 1);
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

static void draw_done(long n, const char *name) {
    draw_room(n, 0);
    uint32_t white = ink(INK_TEXT), dim = ink(INK_MANE_HI);
    int y = ART_SCREEN_Y;
    text(name, SCREEN_CX, y + 8, 1, dim, 1);
    text("DONE!", SCREEN_CX, y + 24, 2, white, 1);
    text("BUILT AND READY", SCREEN_CX, y + 48, 1, white, 1);
    text("DROP ANOTHER FILE", SCREEN_CX, y + 70, 1, dim, 1);
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
static void present(uint32_t *out, int w, int h) {
    int sx = w / ART_W, sy = h / ART_H, scale = sx < sy ? sx : sy;
    if (scale < 1) scale = 1;
    int ox = (w - ART_W * scale) / 2, oy = (h - ART_H * scale) / 2;
    uint32_t border = ink(INK_LETTERBOX);
    for (int y = 0; y < h; y++) {
        int cy = y - oy;
        uint32_t *row = out + (size_t)y * w;
        if (cy < 0 || cy >= ART_H * scale) {
            for (int x = 0; x < w; x++) row[x] = border;
            continue;
        }
        const uint32_t *src = canvas[cy / scale];
        for (int x = 0; x < w; x++) {
            int cx = x - ox;
            row[x] = (cx < 0 || cx >= ART_W * scale) ? border : src[cx / scale];
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
    const char *show, *rom, *message;
    int stage;
    double progress;
} shot_opts = { "drop", "GAME.NES", "NOT AN NES ROM", ST_RECOMP, 0.5 };

static int screenshot(const char *path, long frame, int w, int h) {
    uint32_t *out = malloc((size_t)w * h * 4);
    char name[64];
    screen_name(shot_opts.rom, name, sizeof name);
    if (!strcmp(shot_opts.show, "build")) draw_build(frame, name, shot_opts.stage, shot_opts.progress);
    else if (!strcmp(shot_opts.show, "error")) draw_error(frame, "CAN'T RECOMPILE", shot_opts.message);
    else if (!strcmp(shot_opts.show, "stopped")) draw_error(frame, "THE GAME STOPPED", shot_opts.message);
    else if (!strcmp(shot_opts.show, "done")) draw_done(frame, name);
    else if (!strcmp(shot_opts.show, "play")) draw_play(frame, name);
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
enum { S_DROP, S_BUILD, S_ERROR, S_DONE, S_PLAY, S_STOPPED };
static struct build job;
static int screen = S_DROP;
static char error_msg[512], shown_name[64], game_log[PATH_MAX + 16];
static pid_t game = -1;

/* Split ARGS at spaces into a NULL-ended list (for the game). */
static char **split_args(const char *s) {
    static char buf[1024];
    static char *list[32];
    int n = 0;
    snprintf(buf, sizeof buf, "%s", s ? s : "");
    for (char *p = strtok(buf, " "); p && n < 31; p = strtok(NULL, " ")) list[n++] = p;
    list[n] = NULL;
    return list;
}

/* Play exe on rom, wait for it, and say how it ended: 0 when well. */
static int play_and_wait(const char *exe, const char *rom, const char *args, const char *log) {
    char why[512];
    pid_t pid = play_start(exe, rom, split_args(args), log);
    if (pid < 0) {
        printf("error: couldn't start the game (%s)\n", exe);
        return 1;
    }
    int r = play_poll(pid, log, 1, why, sizeof why);
    if (r > 0) printf("played: the game ended well\n");
    else printf("error: %s\n", why);
    return r > 0 ? 0 : 1;
}

/* A file arrived (dropped, or on the command line). */
static void take(const char *path) {
    if (screen == S_BUILD || screen == S_PLAY) return;     /* busy: ignore it */
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
    int trace = 0, model = 0, then_play = 0;
    const char *play_args = NULL, *play_exe = NULL, *play_rom = NULL;
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
        else if (!strcmp(argv[i], "--build") && more) build_rom = argv[++i];
        else if (!strcmp(argv[i], "--build-dir") && more) bdir = argv[++i];
        else if (!strcmp(argv[i], "--trace-progress")) trace = 1;
        else if (!strcmp(argv[i], "--progress-model")) model = 1;
        else if (!strcmp(argv[i], "--then-play")) then_play = 1;
        else if (!strcmp(argv[i], "--play-args") && more) play_args = argv[++i];
        else if (!strcmp(argv[i], "--play-only") && i + 2 < argc) {
            play_exe = argv[++i];
            play_rom = argv[++i];
        }
        else if (argv[i][0] != '-' && !open_rom) open_rom = argv[i];
        else usage(argv[0]);
    }
    if (shot) return screenshot(shot, frames, sw, sh) ? 1 : 0;
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

    const char *root = getenv("NESRECOMP_ROOT");
    if (!root || !*root) root = PROJECT_ROOT;
    char defdir[PATH_MAX];
    snprintf(defdir, sizeof defdir, "%s/build", root);
    build_setup(root, bdir ? bdir : defdir);
    if (play_exe) {
        snprintf(game_log, sizeof game_log, "%s.game.log", play_exe);
        return play_and_wait(play_exe, play_rom, play_args, game_log);
    }
    if (build_rom) {
        job.verbose = 1;
        if (then_play) {
            if (build_run(&job, build_rom)) return 1;
            snprintf(game_log, sizeof game_log, "%s.game.log", job.out);
            return play_and_wait(job.out, job.rom, play_args, game_log);
        }
        if (!trace) return build_run(&job, build_rom) ? 1 : 0;
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
    SDL_Window *win = SDL_CreateWindow("nesrecomp", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                                       ART_W * 3, ART_H * 3,
                                       SDL_WINDOW_RESIZABLE | SDL_WINDOW_ALLOW_HIGHDPI);
    SDL_Renderer *ren = win ? SDL_CreateRenderer(win, -1, SDL_RENDERER_PRESENTVSYNC) : NULL;
    if (!ren) {
        fprintf(stderr, "can't open a window: %s\n", SDL_GetError());
        return 1;
    }
    SDL_SetWindowMinimumSize(win, ART_W, ART_H);
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
            if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_ESCAPE) goto done;
            if (e.type == SDL_DROPFILE) {
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
        if (screen == S_BUILD) {
            int st = atomic_load(&job.state);
            if (st == B_DONE) {
                /* Built: play it, with this window out of the way. */
                snprintf(game_log, sizeof game_log, "%s.game.log", job.out);
                game = play_start(job.out, job.rom, NULL, game_log);
                if (game < 0) {
                    snprintf(error_msg, sizeof error_msg, "couldn't start the game");
                    screen = S_STOPPED;
                } else {
                    screen = S_PLAY;
                    SDL_HideWindow(win);
                }
            }
            else if (st == B_FAILED) {
                snprintf(error_msg, sizeof error_msg, "%s", job.error);
                screen = S_ERROR;
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
            if (r > 0) screen = S_DROP;
            else {
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
        case S_DONE: draw_done(n, shown_name); break;
        case S_PLAY: draw_play(n, shown_name); break;
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
