/* nesrecomp app: a window to drop a ROM onto (PLAN-gui.md).

   Step 1: the window and the drop screen. The picture (app/art.h, from
   tools/make_app_art.py) is a 320x180 canvas, drawn into the window at
   the largest whole-number scale that fits and centred, with the rest
   of the window in a dark border, so the pixels stay square and sharp.
   The window's pixels are counted in real pixels (a Retina screen has
   twice as many as its points).

   The idle animation: the TV screen's glow rises and falls over about
   four seconds, its scanlines shimmer, and the console's power light
   blinks once a second.

       nesrecomp-app                          open the window
       nesrecomp-app --screenshot F [--frames N] [--size WxH]
           draw frame N (default 0) of the drop screen into a window of
           W x H pixels (default 320x180) and save it as a PNG, with no
           window: for the checks in tests/check_app.py */
#include <SDL.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>
#include "art.h"

static uint32_t canvas[ART_H][ART_W];

static uint32_t rgb(int r, int g, int b) {
    return 0xFF000000u | (uint32_t)r << 16 | (uint32_t)g << 8 | (uint32_t)b;
}

static uint32_t ink(int i) {
    return rgb(art_palette[i][0], art_palette[i][1], art_palette[i][2]);
}

/* Text in the 5x7 font, `scale` canvas pixels a font pixel, a glyph
   every 6 * scale pixels; centred on x = cx. */
static void text(const char *s, int cx, int y, int scale, uint32_t colour) {
    int len = (int)strlen(s), x0 = cx - (len * 6 * scale - scale) / 2;
    for (int i = 0; i < len; i++) {
        int ch = (unsigned char)s[i];
        if (ch >= 'a' && ch <= 'z') ch -= 32;
        if (ch < 0x20 || ch > 0x5F) ch = '?';
        const unsigned char *g = art_font[ch - 0x20];
        for (int r = 0; r < 7; r++)
            for (int c = 0; c < 5; c++)
                if (g[r] & (0x10 >> c))
                    for (int dy = 0; dy < scale; dy++)
                        for (int dx = 0; dx < scale; dx++) {
                            int x = x0 + i * 6 * scale + c * scale + dx, yy = y + r * scale + dy;
                            if (x >= 0 && x < ART_W && yy >= 0 && yy < ART_H)
                                canvas[yy][x] = colour;
                        }
    }
}

/* The drop screen at frame n (60 a second). */
static void draw_drop(long n) {
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
    /* The power light: on for 50 frames of each second, off for 10. */
    if (n % 60 >= 50) pal[INK_LED] = ink(INK_BLACK);
    for (int y = 0; y < ART_H; y++)
        for (int x = 0; x < ART_W; x++)
            canvas[y][x] = pal[art_pixels[y][x]];
    int cx = ART_SCREEN_X + ART_SCREEN_W / 2;
    int top = ART_SCREEN_Y + (ART_SCREEN_H - (3 * 14 + 2 * 6)) / 2;
    uint32_t white = ink(INK_TEXT);
    text("DROP YOUR", cx, top, 2, white);
    text("NES ROM", cx, top + 20, 2, white);
    text("FILE HERE", cx, top + 40, 2, white);
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

static int screenshot(const char *path, long frame, int w, int h) {
    uint32_t *out = malloc((size_t)w * h * 4);
    draw_drop(frame);
    present(out, w, h);
    int r = save_png(path, out, w, h);
    free(out);
    return r;
}

static void usage(const char *prog) {
    fprintf(stderr, "usage: %s [--screenshot FILE [--frames N] [--size WxH]]\n", prog);
    exit(1);
}

int main(int argc, char **argv) {
    const char *shot = NULL;
    long frames = 0;
    int sw = ART_W, sh = ART_H;
    for (int i = 1; i < argc; i++) {
        int more = i + 1 < argc;
        if (!strcmp(argv[i], "--screenshot") && more) shot = argv[++i];
        else if (!strcmp(argv[i], "--frames") && more) frames = strtol(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--size") && more) {
            if (sscanf(argv[++i], "%dx%d", &sw, &sh) != 2 || sw < 1 || sh < 1) usage(argv[0]);
        } else usage(argv[0]);
    }
    if (shot) return screenshot(shot, frames, sw, sh) ? 1 : 0;

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
    for (;;) {
        SDL_Event e;
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_QUIT) goto done;
            if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_ESCAPE) goto done;
            if (e.type == SDL_DROPFILE) {
                /* Step 2 recompiles it; for now, say what came. */
                printf("dropped: %s\n", e.drop.file);
                fflush(stdout);
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
        draw_drop(n++);
        present(out, w, h);
        SDL_UpdateTexture(tex, NULL, out, w * 4);
        SDL_RenderCopy(ren, tex, NULL, NULL);
        SDL_RenderPresent(ren);
    }
done:
    SDL_Quit();
    return 0;
}
