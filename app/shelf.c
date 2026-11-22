/* nesrecomp app: the library, the shelf of games (see shelf.h). */
#include "shelf.h"
#include "os.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

const uint32_t shelf_colours[SHELF_COLOURS] = {
    0x8C1E32,   /* red */
    0x1E783C,   /* green */
    0xA09632,   /* olive */
    0x788CBE,   /* blue-grey */
    0x2846C8,   /* blue */
    0x1E2D6E,   /* navy */
    0xD2A032,   /* gold */
    0x5A2882,   /* purple */
    0xE6781E,   /* orange */
    0x3C3C4B,   /* dark grey (SHELF_GREY): no colour to go by */
    0xB41437,   /* crimson */
    0x8C50D2,   /* violet */
};

#define TITLE_SIZE (12 + 256 * 240 * 3)

void shelf_shrink(const uint8_t *rgb, int sw, int sh, uint32_t *out, int dw, int dh) {
    for (int dy = 0; dy < dh; dy++) {
        double y0 = (double)dy * sh / dh, y1 = (double)(dy + 1) * sh / dh;
        for (int dx = 0; dx < dw; dx++) {
            double x0 = (double)dx * sw / dw, x1 = (double)(dx + 1) * sw / dw;
            double sum[3] = { 0, 0, 0 }, area = 0;
            for (int y = (int)y0; y < sh && y < y1; y++) {
                double wy = (y + 1 < y1 ? y + 1 : y1) - (y > y0 ? y : y0);
                for (int x = (int)x0; x < sw && x < x1; x++) {
                    double w = wy * ((x + 1 < x1 ? x + 1 : x1) - (x > x0 ? x : x0));
                    const uint8_t *p = rgb + ((size_t)y * sw + x) * 3;
                    for (int c = 0; c < 3; c++) sum[c] += p[c] * w;
                    area += w;
                }
            }
            uint32_t v = 0;
            for (int c = 0; c < 3; c++) v = v << 8 | (uint32_t)(sum[c] / area + 0.5);
            out[dy * dw + dx] = v;
        }
    }
}

int shelf_colour_of(const uint8_t *rgb) {
    /* The most common colour, in buckets of 16 levels a channel, leaving
       out black, white and greys (the channels within 48 of each other). */
    static int count[4096];
    static long sum[4096][3];
    memset(count, 0, sizeof count);
    memset(sum, 0, sizeof sum);
    for (int i = 0; i < 256 * 240; i++) {
        int r = rgb[i * 3], g = rgb[i * 3 + 1], b = rgb[i * 3 + 2];
        int hi = r > g ? (r > b ? r : b) : (g > b ? g : b);
        int lo = r < g ? (r < b ? r : b) : (g < b ? g : b);
        if (hi - lo < 48) continue;
        int k = (r >> 4) << 8 | (g >> 4) << 4 | (b >> 4);
        count[k]++;
        sum[k][0] += r; sum[k][1] += g; sum[k][2] += b;
    }
    int best = -1;
    for (int k = 0; k < 4096; k++)
        if (count[k] && (best < 0 || count[k] > count[best])) best = k;
    if (best < 0) return SHELF_GREY;
    int r = (int)(sum[best][0] / count[best]), g = (int)(sum[best][1] / count[best]),
        b = (int)(sum[best][2] / count[best]);
    /* The nearest box colour (not the grey: there was a colour). */
    int pick = 0;
    long nearest = -1;
    for (int i = 0; i < SHELF_COLOURS; i++) {
        if (i == SHELF_GREY) continue;
        int cr = shelf_colours[i] >> 16 & 255, cg = shelf_colours[i] >> 8 & 255, cb = shelf_colours[i] & 255;
        long d = 2L * (r - cr) * (r - cr) + 4L * (g - cg) * (g - cg) + 3L * (b - cb) * (b - cb);
        if (nearest < 0 || d < nearest) { nearest = d; pick = i; }
    }
    return pick;
}

static int is_music(const char *rom) {
    unsigned char h[5] = { 0 };
    FILE *f = fopen(rom, "rb");
    if (f) {
        size_t n = fread(h, 1, 5, f);
        fclose(f);
        return n == 5 && !memcmp(h, "NESM\x1a", 5);
    }
    size_t n = strlen(rom);
    return n > 4 && (!strcmp(rom + n - 4, ".nsf") || !strcmp(rom + n - 4, ".NSF"));
}

void shelf_title(struct shelf *s, int i) {
    struct shelf_game *g = &s->games[i];
    char path[PATH_MAX + 300];
    snprintf(path, sizeof path, "%s/%s.title", s->dir, g->name);
    g->has_title = 0;
    g->colour = SHELF_GREY;
    g->music = is_music(g->rom);
    static uint8_t buf[TITLE_SIZE + 1];
    FILE *f = fopen(path, "rb");
    if (!f) return;
    size_t n = fread(buf, 1, sizeof buf, f);
    fclose(f);
    if (n != TITLE_SIZE || memcmp(buf, "NRTITLE1", 8) || buf[8] != 0 || buf[9] != 1 || buf[10] != 240 ||
        buf[11] != 0) {
        printf("shelf: %s.title isn't a title picture (left out)\n", g->name);
        return;
    }
    shelf_shrink(buf + 12, 256, 240, g->thumb, THUMB_W, THUMB_H);
    shelf_shrink(buf + 12, 256, 240, g->preview, PREVIEW_W, PREVIEW_H);
    g->colour = shelf_colour_of(buf + 12);
    g->has_title = 1;
}

int shelf_find(const struct shelf *s, const char *name) {
    for (int i = 0; i < s->count; i++)
        if (!strcmp(s->games[i].name, name)) return i;
    return -1;
}

/* ---- filling from the builds already there (their stamps) ---- */
struct stamps { struct shelf *s; double when[SHELF_MAX]; };

static void add_stamp(const char *file, void *arg) {
    struct stamps *st = arg;
    struct shelf *s = st->s;
    size_t n = strlen(file);
    if (n <= 6 || strcmp(file + n - 6, ".stamp") || s->count >= SHELF_MAX) return;
    char path[PATH_MAX + 300], line[PATH_MAX * 2 + 256];
    snprintf(path, sizeof path, "%s/%s", s->dir, file);
    FILE *f = fopen(path, "r");
    if (!f) return;
    if (!fgets(line, sizeof line, f)) line[0] = 0;
    fclose(f);
    /* "[app V ]rom PATH SIZE TIME missed ...": PATH may have spaces. */
    char *rom = strstr(line, "rom ");
    char *end = rom ? strstr(rom, " missed ") : NULL;
    if (!rom || !end) return;
    rom += 4;
    *end = 0;
    for (int k = 0; k < 2; k++) {               /* drop SIZE and TIME */
        char *sp = strrchr(rom, ' ');
        if (!sp) return;
        *sp = 0;
    }
    struct shelf_game *g = &s->games[s->count];
    memset(g, 0, sizeof *g);
    snprintf(g->name, sizeof g->name, "%.*s", (int)(n - 6), file);
    snprintf(g->rom, sizeof g->rom, "%s", rom);
    st->when[s->count] = os_mtime(path);
    s->count++;
}

static void from_stamps(struct shelf *s) {
    static struct stamps st;
    st.s = s;
    s->count = 0;
    os_list(s->dir, add_stamp, &st);
    /* Newest build first. */
    for (int i = 1; i < s->count; i++)
        for (int j = i; j > 0 && st.when[j] > st.when[j - 1]; j--) {
            struct shelf_game t = s->games[j];
            s->games[j] = s->games[j - 1];
            s->games[j - 1] = t;
            double w = st.when[j]; st.when[j] = st.when[j - 1]; st.when[j - 1] = w;
        }
}

void shelf_load(struct shelf *s, const char *dir) {
    snprintf(s->dir, sizeof s->dir, "%s", dir);
    s->count = 0;
    char path[PATH_MAX + 32];
    snprintf(path, sizeof path, "%s/library.txt", dir);
    FILE *f = fopen(path, "r");
    if (!f) {
        from_stamps(s);
        for (int i = 0; i < s->count; i++) shelf_title(s, i);
        printf("shelf: no library.txt yet: %d game(s) already built put on it\n", s->count);
        if (s->count) shelf_save(s);
        return;
    }
    char line[PATH_MAX + 400];
    const char *why = NULL;
    if (!fgets(line, sizeof line, f) || strcmp(line, "version 1\n")) why = "not version 1";
    while (!why && fgets(line, sizeof line, f)) {
        size_t n = strlen(line);
        if (n && line[n - 1] == '\n') line[--n] = 0;
        if (!n) continue;
        char *t1 = strchr(line, '\t'), *t2 = t1 ? strchr(t1 + 1, '\t') : NULL;
        char *num_end = NULL;
        long long played = t1 ? strtoll(t1 + 1, &num_end, 10) : 0;
        if (!t1 || !t2 || t1 == line || num_end != t2 || played < 0 || !t2[1] || strchr(t2 + 1, '\t') ||
            (size_t)(t1 - line) >= sizeof s->games[0].name) {
            why = "a line that isn't NAME, a time and a path";
            break;
        }
        *t1 = 0;
        if (shelf_find(s, line) >= 0) { why = "a game twice"; break; }
        if (s->count >= SHELF_MAX) break;
        struct shelf_game *g = &s->games[s->count++];
        memset(g, 0, sizeof *g);
        snprintf(g->name, sizeof g->name, "%s", line);
        snprintf(g->rom, sizeof g->rom, "%s", t2 + 1);
        g->played = played;
    }
    fclose(f);
    if (why) {
        s->count = 0;
        printf("shelf: library.txt not read (%s): an empty shelf\n", why);
        return;
    }
    for (int i = 0; i < s->count; i++) shelf_title(s, i);
    printf("shelf: %d game(s)\n", s->count);
}

int shelf_save(const struct shelf *s) {
    char path[PATH_MAX + 32];
    snprintf(path, sizeof path, "%s/library.txt", s->dir);
    FILE *f = fopen(path, "w");
    if (!f) { printf("shelf: can't write %s\n", path); return -1; }
    fprintf(f, "version 1\n");
    for (int i = 0; i < s->count; i++)
        fprintf(f, "%s\t%lld\t%s\n", s->games[i].name, s->games[i].played, s->games[i].rom);
    return fclose(f) == 0 ? 0 : -1;
}

int shelf_played(struct shelf *s, const char *name, const char *rom, long long now) {
    int i = shelf_find(s, name);
    struct shelf_game g;
    if (i >= 0) {
        g = s->games[i];
        memmove(&s->games[1], &s->games[0], (size_t)i * sizeof g);
        printf("shelf: %s to the front\n", name);
    } else {
        memset(&g, 0, sizeof g);
        snprintf(g.name, sizeof g.name, "%s", name);
        int n = s->count < SHELF_MAX ? s->count : SHELF_MAX - 1;   /* full: the last one goes */
        memmove(&s->games[1], &s->games[0], (size_t)n * sizeof g);
        s->count = n + 1;
        printf("shelf: %s added\n", name);
    }
    snprintf(g.rom, sizeof g.rom, "%s", rom);
    g.played = now;
    s->games[0] = g;
    shelf_title(s, 0);
    shelf_save(s);
    return 0;
}

/* ---- the self-test ---- */

static void write_file(const char *path, const char *text) {
    FILE *f = fopen(path, "w");
    if (f) { fputs(text, f); fclose(f); }
}

/* A made-up title picture: all colour bg, with a block of colour fg
   (rows y0 to y1). */
static uint8_t made[256 * 240 * 3];
static const uint8_t *picture(uint32_t bg, uint32_t fg, int y0, int y1) {
    for (int i = 0; i < 256 * 240; i++) {
        uint32_t c = (i / 256 >= y0 && i / 256 < y1) ? fg : bg;
        made[i * 3] = c >> 16; made[i * 3 + 1] = c >> 8 & 255; made[i * 3 + 2] = c & 255;
    }
    return made;
}

static void write_title(const char *dir, const char *name, const uint8_t *rgb) {
    char path[PATH_MAX + 300];
    snprintf(path, sizeof path, "%s/%s.title", dir, name);
    FILE *f = fopen(path, "wb");
    if (!f) return;
    fwrite("NRTITLE1\x00\x01\xF0\x00", 1, 12, f);
    fwrite(rgb, 1, 256 * 240 * 3, f);
    fclose(f);
}

int shelf_test(const char *dir) {
    static struct shelf s, t;
    int fails = 0;
    char path[PATH_MAX + 64], text[PATH_MAX * 2];
#define CHECK(what, ok) do { int ok_ = (ok); printf("%s  shelf: %s\n", ok_ ? "ok  " : "FAIL", what); \
                             fails += !ok_; } while (0)
    os_make_dirs(dir);
    const char *files[] = { "library.txt", "alpha.stamp", "beta.stamp", "alpha.title", "beta.title",
                            "gamma.title", "tune.title" };
    for (size_t k = 0; k < sizeof files / sizeof *files; k++) {
        snprintf(path, sizeof path, "%s/%s", dir, files[k]);
        os_remove(path);
    }
    /* 1. Colours. */
    CHECK("all black: the grey box", shelf_colour_of(picture(0x000000, 0x000000, 0, 0)) == SHELF_GREY);
    CHECK("greys and white only: the grey box", shelf_colour_of(picture(0x7C7C7C, 0xFCFCFC, 0, 100)) == SHELF_GREY);
    int red = shelf_colour_of(picture(0x000000, 0xA81000, 40, 80));
    CHECK("black with a red logo: red (or crimson)", red == 0 || red == 10);
    CHECK("a blue sky with a green ground: blue (the most of it)",
          shelf_colour_of(picture(0x3CBCFC, 0x00A800, 180, 240)) == 3 ||
          shelf_colour_of(picture(0x3CBCFC, 0x00A800, 180, 240)) == 4);
    CHECK("mostly green: green", shelf_colour_of(picture(0x00A800, 0x3CBCFC, 200, 240)) == 1);
    CHECK("orange: orange", shelf_colour_of(picture(0xE45C10, 0x000000, 0, 0)) == 8);
    /* 2. The shrink: averaging, not skipping. Stripes of black and white,
       a pixel each, average to grey. */
    for (int i = 0; i < 256 * 240; i++) made[i * 3] = made[i * 3 + 1] = made[i * 3 + 2] = (i % 2) ? 255 : 0;
    static uint32_t small[THUMB_W * THUMB_H];
    shelf_shrink(made, 256, 240, small, THUMB_W, THUMB_H);
    int grey = 1;
    for (int i = 0; i < THUMB_W * THUMB_H; i++) {
        int v = small[i] & 255;
        if (v < 120 || v > 135) grey = 0;
    }
    CHECK("1-pixel stripes shrink to grey (averaged)", grey);
    picture(0x000000, 0xFFFFFF, 120, 240);
    shelf_shrink(made, 256, 240, small, THUMB_W, THUMB_H);
    CHECK("the top half black, the bottom white: so in the box",
          small[0] == 0 && small[THUMB_W * THUMB_H - 1] == 0xFFFFFF);
    /* 3. No library.txt: the builds already there, newest first. */
    snprintf(path, sizeof path, "%s/alpha.stamp", dir);
    write_file(path, "rom /games/my alpha game.nes 40976 1.0 missed 0 0.0 recomp 1.0 runtime 1.0\n");
    snprintf(path, sizeof path, "%s/beta.stamp", dir);
    write_file(path, "app 2.0 rom /games/beta.nes 24592 1.0 missed 0 0.0 recomp 1.0 runtime 1.0 sdl 1.0\n");
    write_title(dir, "alpha", picture(0x000000, 0xA81000, 40, 80));
    shelf_load(&s, dir);
    int ai = shelf_find(&s, "alpha"), bi = shelf_find(&s, "beta");
    CHECK("no library.txt: the two games built, from their stamps", s.count == 2 && ai >= 0 && bi >= 0);
    CHECK("a stamp's path with spaces read whole", ai >= 0 && !strcmp(s.games[ai].rom, "/games/my alpha game.nes"));
    CHECK("a newer stamp's path read", bi >= 0 && !strcmp(s.games[bi].rom, "/games/beta.nes"));
    CHECK("alpha's picture read: its colour red", ai >= 0 && s.games[ai].has_title &&
          s.games[ai].colour == red);
    CHECK("beta has no picture yet: grey", bi >= 0 && !s.games[bi].has_title && s.games[bi].colour == SHELF_GREY);
    snprintf(path, sizeof path, "%s/library.txt", dir);
    CHECK("and library.txt written", os_exists(path));
    /* 4. Played: to the front; a new one added in front. */
    shelf_played(&s, "beta", "/games/beta.nes", 1000);
    CHECK("beta played: first", !strcmp(s.games[0].name, "beta") && s.games[0].played == 1000);
    write_title(dir, "gamma", picture(0x00A800, 0x3CBCFC, 200, 240));
    shelf_played(&s, "gamma", "/games/gamma.nes", 2000);
    CHECK("gamma built and played: added, first, with its picture",
          s.count == 3 && !strcmp(s.games[0].name, "gamma") && s.games[0].has_title && s.games[0].colour == 1);
    shelf_played(&s, "alpha", "/games/my alpha game.nes", 3000);
    CHECK("alpha played: first, then gamma, then beta",
          !strcmp(s.games[0].name, "alpha") && !strcmp(s.games[1].name, "gamma") && !strcmp(s.games[2].name, "beta"));
    /* 5. Read back. */
    shelf_load(&t, dir);
    int same = t.count == 3;
    for (int i = 0; same && i < 3; i++)
        same = !strcmp(t.games[i].name, s.games[i].name) && !strcmp(t.games[i].rom, s.games[i].rom) &&
               t.games[i].played == s.games[i].played;
    CHECK("library.txt read back: the same games, order, paths and times", same);
    /* 6. A game whose picture appears after it played. */
    write_title(dir, "beta", picture(0xE45C10, 0x000000, 0, 0));
    shelf_title(&t, 2);
    CHECK("beta's picture read again after it played: orange", t.games[2].has_title && t.games[2].colour == 8);
    /* 7. A music file: a note, no picture. */
    snprintf(path, sizeof path, "%s/tune.nsf", dir);
    write_file(path, "NESM\x1a and the rest");
    shelf_played(&t, "tune", path, 4000);
    CHECK("a music file: marked as music", t.games[0].music && !t.games[0].has_title);
    /* 8. Bad files: an empty shelf, not a crash. */
    const char *bad[] = {
        "", "version 2\nalpha\t1\t/a.nes\n", "alpha\t1\t/a.nes\n", "version 1\nalpha 1 /a.nes\n",
        "version 1\nalpha\tsoon\t/a.nes\n", "version 1\nalpha\t1\t\n", "version 1\n\t1\t/a.nes\n",
        "version 1\nalpha\t1\t/a.nes\nalpha\t2\t/b.nes\n", "version 1\nalpha\t-5\t/a.nes\n",
        "version 1\nalpha\t1\t/a.nes\textra\n", "\x89PNG\r\n\x1a\n\x00\x00garbage",
        /* a garbled line among good ones: the whole file is refused,
           not the good lines kept and the bad one dropped unsaid */
        "version 1\nalpha\t1\t/a.nes\nbeta 2 /b.nes\ngamma\t3\t/c.nes\n",
        "version 1\nalpha\t1\t/a.nes\ngamma\tlater\t/c.nes\n",
    };
    int empty = 0;
    snprintf(path, sizeof path, "%s/library.txt", dir);
    for (size_t k = 0; k < sizeof bad / sizeof *bad; k++) {
        write_file(path, bad[k]);
        shelf_load(&t, dir);
        empty += t.count == 0;
    }
    CHECK("13 bad library.txt files (2 with good lines too): an empty shelf each",
          empty == (int)(sizeof bad / sizeof *bad));
    snprintf(text, sizeof text, "version 1\nalpha\t5\t/games/a b.nes\n\nbeta\t4\t/games/b.nes\n");
    write_file(path, text);
    shelf_load(&t, dir);
    CHECK("a blank line is fine", t.count == 2 && !strcmp(t.games[0].rom, "/games/a b.nes"));
    printf("%s\n", fails ? "shelf self-test: FAILED" : "shelf self-test: all pass");
    return fails ? 1 : 0;
#undef CHECK
}
