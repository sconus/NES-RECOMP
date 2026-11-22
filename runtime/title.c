/* nesrecomp runtime: the game's title picture (see title.h). */
#include "title.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "palette.h"
#include "ppu.h"

#define PIXELS (NES_WIDTH * NES_HEIGHT)

static struct {
    char path[1024];
    int on, done, start_was;
    int have_spare;                     /* the 10-second picture is kept */
    long spare_frame;
    uint8_t spare[PIXELS * 3];
} t;

/* Is the picture (nearly) one colour: 99% or more of it the same? */
static int one_colour(const uint16_t *fb) {
    static int count[512];
    memset(count, 0, sizeof count);
    int most = 0;
    for (int i = 0; i < PIXELS; i++) {
        int c = ++count[fb[i] & 0x1FF];
        if (c > most) most = c;
    }
    return most * 100 >= PIXELS * 99;
}

static void to_rgb(const uint16_t *fb, uint8_t *out) {
    for (int i = 0; i < PIXELS; i++) {
        uint32_t c = nes_rgb[fb[i] & 0x1FF];
        out[i * 3] = (uint8_t)(c >> 16);
        out[i * 3 + 1] = (uint8_t)(c >> 8);
        out[i * 3 + 2] = (uint8_t)c;
    }
}

static void write_title(const uint8_t *rgb, long frame, const char *why) {
    t.done = 1;
    FILE *f = fopen(t.path, "wb");
    if (!f) {
        fprintf(stderr, "title: can't write %s\n", t.path);
        return;
    }
    uint8_t head[12] = { 'N', 'R', 'T', 'I', 'T', 'L', 'E', '1',
                         NES_WIDTH & 255, NES_WIDTH >> 8, NES_HEIGHT & 255, NES_HEIGHT >> 8 };
    int ok = fwrite(head, 1, sizeof head, f) == sizeof head &&
             fwrite(rgb, 1, PIXELS * 3, f) == PIXELS * 3;
    if (fclose(f) != 0) ok = 0;
    if (ok) fprintf(stderr, "title: saved at frame %ld (%s)\n", frame, why);
    else fprintf(stderr, "title: couldn't finish writing %s\n", t.path);
}

void title_start(const char *path) {
    memset(&t, 0, sizeof t);
    snprintf(t.path, sizeof t.path, "%s", path);
    t.on = 1;
}

void title_frame(const uint16_t *fb, long frame, int start_held) {
    if (!t.on || t.done) return;
    int pressed = start_held && !t.start_was;
    t.start_was = start_held;
    if (pressed && frame <= TITLE_LAST && !one_colour(fb)) {
        static uint8_t rgb[PIXELS * 3];
        to_rgb(fb, rgb);
        write_title(rgb, frame, "Start");
        return;
    }
    if (frame >= TITLE_FALLBACK && !t.have_spare && !one_colour(fb)) {
        to_rgb(fb, t.spare);
        t.have_spare = 1;
        t.spare_frame = frame;
    }
    if (frame >= TITLE_LAST) title_finish();
}

void title_finish(void) {
    if (!t.on || t.done) return;
    if (t.have_spare) {
        write_title(t.spare, t.spare_frame, "10 seconds");
    } else {
        t.done = 1;
        fprintf(stderr, "title: none (no Start, and no picture that isn't one colour by 30 seconds)\n");
    }
}

/* ---- the self-test ---- */

static uint16_t pic[PIXELS];

/* A made-up picture: all colour c, with `marks` pixels of colour m (so
   it can be told apart, and be "one colour" or not). */
static const uint16_t *made(int c, int m, int marks) {
    for (int i = 0; i < PIXELS; i++) pic[i] = (uint16_t)c;
    for (int i = 0; i < marks; i++) pic[i * 7 % PIXELS] = (uint16_t)m;
    return pic;
}

/* The file's picture, or NULL. */
static uint8_t *read_title(const char *path) {
    static uint8_t buf[12 + PIXELS * 3 + 1];
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    size_t n = fread(buf, 1, sizeof buf, f);
    fclose(f);
    if (n != 12 + PIXELS * 3 || memcmp(buf, "NRTITLE1", 8) || buf[8] + 256 * buf[9] != NES_WIDTH ||
        buf[10] + 256 * buf[11] != NES_HEIGHT)
        return NULL;
    return buf + 12;
}

/* Does the file hold made(c, m, marks)? */
static int holds(const char *path, int c, int m, int marks) {
    const uint8_t *got = read_title(path);
    if (!got) return 0;
    static uint8_t want[PIXELS * 3];
    to_rgb(made(c, m, marks), want);
    return !memcmp(got, want, sizeof want);
}

int title_test(const char *dir) {
    char path[1200];
    snprintf(path, sizeof path, "%s/test.title", dir);
    int fails = 0;
#define CHECK(what, ok) do { int ok_ = (ok); printf("%s  title: %s\n", ok_ ? "ok  " : "FAIL", what); \
                             fails += !ok_; } while (0)
    /* 1. Start on a black screen doesn't count; the next press, on a
       picture, does, and holding it on doesn't press it again. */
    remove(path);
    title_start(path);
    long f = 1;
    for (; f < 50; f++) title_frame(made(0x0F, 0, 0), f, 0);
    for (; f < 60; f++) title_frame(made(0x0F, 0, 0), f, 1);          /* pressed at 50: black */
    for (; f < 100; f++) title_frame(made(0x0F, 0, 0), f, 0);
    CHECK("a press on a one-colour screen: nothing yet", !read_title(path));
    for (; f < 200; f++) title_frame(made(0x21, 0x30, 900), f, 0);    /* a picture from 100 */
    title_frame(made(0x21, 0x16, 900), 200, 1);                       /* Start at 200 */
    CHECK("Start on a picture: that picture", holds(path, 0x21, 0x16, 900));
    remove(path);
    for (f = 201; f < 2000; f++) title_frame(made(0x11, 0x16, 900), f, (f / 10) % 2);
    CHECK("then never again (more presses, past 30 seconds)", !read_title(path));
    /* 2. No Start: the picture at 10 seconds, written at 30. */
    title_start(path);
    for (f = 1; f < TITLE_LAST; f++) title_frame(made(0x22, f == TITLE_FALLBACK ? 0x25 : 0x30, 900), f, 0);
    CHECK("no Start: nothing before 30 seconds", !read_title(path));
    title_frame(made(0x22, 0x30, 900), TITLE_LAST, 0);
    CHECK("no Start: at 30 seconds, the picture of 10 seconds", holds(path, 0x22, 0x25, 900));
    /* 3. One colour at 10 seconds: the first picture after it. */
    remove(path);
    title_start(path);
    for (f = 1; f < 700; f++) title_frame(made(0x0F, 0x20, 300), f, 0);   /* 99.5%: one colour */
    for (; f <= TITLE_LAST; f++) title_frame(made(0x0F, f == 700 ? 0x27 : 0x20, 1200), f, 0);
    CHECK("one colour at 10 seconds (99.5% of it): the first picture after", holds(path, 0x0F, 0x27, 1200));
    /* 4. Start after 10 seconds, before 30: Start's picture wins. */
    remove(path);
    title_start(path);
    for (f = 1; f < 1000; f++) title_frame(made(0x13, 0x30, 900), f, 0);
    title_frame(made(0x13, 0x2A, 900), 1000, 1);
    CHECK("Start at 1000 (after 10 seconds): its picture", holds(path, 0x13, 0x2A, 900));
    /* 5. Start after 30 seconds doesn't count: the 10-second picture
       was already written. */
    remove(path);
    title_start(path);
    for (f = 1; f <= TITLE_LAST; f++) title_frame(made(0x14, f == TITLE_FALLBACK ? 0x25 : 0x30, 900), f, 0);
    title_frame(made(0x14, 0x2A, 900), TITLE_LAST + 1, 1);
    CHECK("Start after 30 seconds: still the 10-second picture", holds(path, 0x14, 0x25, 900));
    /* 6. The game ends at 20 seconds: the 10-second picture then. */
    remove(path);
    title_start(path);
    for (f = 1; f < 1200; f++) title_frame(made(0x15, f == TITLE_FALLBACK ? 0x25 : 0x30, 900), f, 0);
    CHECK("ended at 20 seconds: nothing before the end", !read_title(path));
    title_finish();
    CHECK("ended at 20 seconds: the 10-second picture", holds(path, 0x15, 0x25, 900));
    /* 7. Ended before 10 seconds, or one colour all along: no file. */
    remove(path);
    title_start(path);
    for (f = 1; f < 300; f++) title_frame(made(0x16, 0x30, 900), f, 0);
    title_finish();
    CHECK("ended at 5 seconds with no Start: no file", !read_title(path));
    title_start(path);
    for (f = 1; f <= TITLE_LAST; f++) title_frame(made(0x0F, 0x30, 100), f, 0);
    CHECK("one colour for 30 seconds: no file", !read_title(path));
    /* 8. 98% one colour is a picture (a dark title with a little text). */
    title_start(path);
    for (f = 1; f < 10; f++) title_frame(made(0x0F, 0x30, 1229), f, 0);
    title_frame(made(0x0F, 0x30, 1229), 10, 1);
    CHECK("98% one colour counts as a picture", holds(path, 0x0F, 0x30, 1229));
    remove(path);
    /* 9. Without --title-out: nothing written, whatever happens. */
    memset(&t, 0, sizeof t);
    for (f = 1; f <= TITLE_LAST; f++) title_frame(made(0x21, 0x30, 900), f, f == 100);
    title_finish();
    CHECK("without --title-out: no file", !read_title(path));
    printf("%s\n", fails ? "title self-test: FAILED" : "title self-test: all pass");
    return fails ? 1 : 0;
#undef CHECK
}
