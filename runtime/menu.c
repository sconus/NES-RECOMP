/* nesrecomp runtime: the pause menu (menu.h, PLAN-pause.md). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/stat.h>
#include "menu.h"
#include "video.h"

/* The layout, in NES pixels (tests/check_menu.py reads these). */
#define MENU_BOX_X 36
#define MENU_BOX_Y 50
#define MENU_BOX_W 184
#define MENU_BOX_H 140
#define MENU_TITLE_Y 60
#define MENU_ITEM_X 64
#define MENU_CURSOR_X 54
#define MENU_ITEM_Y 78
#define MENU_LINE_H 13
#define MENU_INFO_X 136                     /* the slot's EMPTY / date */

/* NES colours (the picture holds palette indexes). */
#define INK_BOX 0x0F                        /* black */
#define INK_EDGE 0x00                       /* dark grey */
#define INK_TITLE 0x30                      /* white */
#define INK_ITEM 0x10                       /* light grey */
#define INK_PICKED 0x30                     /* white */
#define INK_CURSOR 0x21                     /* light blue */

enum { ITEM_RESUME, ITEM_SAVE, ITEM_LOAD, ITEM_SLOT, ITEM_RESET, ITEM_SOUND, ITEM_WINDOW,
       ITEM_QUIT, ITEM_COUNT };
static const char *const item_names[ITEM_COUNT] = {
    "RESUME", "SAVE STATE", "LOAD STATE", "SLOT", "RESET", "SOUND", "WINDOW", "QUIT",
};

static int wanted, is_open, cursor;

#define MAX_KEYS 64
static struct { int key; const char *path; } keys[MAX_KEYS];
static int key_count, key_at;

void menu_request(void) { wanted = 1; }
int menu_wanted(void) { return wanted; }
int menu_is_open(void) { return is_open; }

void menu_key(int key, const char *path) {
    if (key_count == MAX_KEYS) return;
    keys[key_count].key = key;
    keys[key_count].path = path;
    key_count++;
}

/* Darker by two steps of the NES palette's brightness; the darkest row
   and the blacks become black (0x0F, never 0x0D). */
static uint16_t darker(uint16_t c) {
    int v = c & 0x3F;
    if ((v & 0x0F) >= 0x0D || v < 0x20) return 0x0F;
    return (uint16_t)(v - 0x20);
}

static void box(uint16_t *fb, int x0, int y0, int w, int h, uint16_t ink) {
    for (int y = y0; y < y0 + h; y++)
        for (int x = x0; x < x0 + w; x++)
            if (x >= 0 && x < 256 && y >= 0 && y < 240) fb[y * 256 + x] = ink;
}

/* What the slot holds: EMPTY, or when it was saved ("21 NOV 09:14"). */
static void slot_info(char *out, size_t size) {
    struct stat st;
    const char *path = runtime_slot_path();
    if (!path || stat(path, &st) != 0) { snprintf(out, size, "EMPTY"); return; }
    static const char *const months[12] = { "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                                            "JUL", "AUG", "SEP", "OCT", "NOV", "DEC" };
    time_t t = st.st_mtime;
    struct tm *tm = localtime(&t);
    if (!tm) { snprintf(out, size, "SAVED"); return; }
    snprintf(out, size, "%d %s %02d:%02d", tm->tm_mday, months[tm->tm_mon % 12],
             tm->tm_hour, tm->tm_min);
}

static void draw(uint16_t *out, const uint16_t *fb) {
    for (int i = 0; i < 256 * 240; i++) out[i] = darker(fb[i]);
    box(out, MENU_BOX_X - 1, MENU_BOX_Y - 1, MENU_BOX_W + 2, MENU_BOX_H + 2, INK_EDGE);
    box(out, MENU_BOX_X, MENU_BOX_Y, MENU_BOX_W, MENU_BOX_H, INK_BOX);
    const char *title = "PAUSED";
    draw_text_5x7(out, 128 - ((int)strlen(title) * 6 - 1) / 2, MENU_TITLE_Y, title, INK_TITLE);
    for (int i = 0; i < ITEM_COUNT; i++) {
        int y = MENU_ITEM_Y + i * MENU_LINE_H;
        char line[32];
        if (i == ITEM_SLOT) snprintf(line, sizeof line, "SLOT  < %d >", runtime_slot());
        else if (i == ITEM_SOUND) {
            int v = runtime_sound();
            if (v) snprintf(line, sizeof line, "SOUND < %d >", v);
            else snprintf(line, sizeof line, "SOUND < OFF >");
        } else if (i == ITEM_WINDOW) {
            int w = runtime_window();
            if (w) snprintf(line, sizeof line, "WINDOW < %dX >", w);
            else snprintf(line, sizeof line, "WINDOW < FULL >");
        } else snprintf(line, sizeof line, "%s", item_names[i]);
        draw_text_5x7(out, MENU_ITEM_X, y, line, i == cursor ? INK_PICKED : INK_ITEM);
        if (i == ITEM_SLOT) {
            char info[32];
            slot_info(info, sizeof info);
            draw_text_5x7(out, MENU_INFO_X, y, info, INK_ITEM);
        }
    }
    draw_text_5x7(out, MENU_CURSOR_X, MENU_ITEM_Y + cursor * MENU_LINE_H, ">", INK_CURSOR);
}

/* The menu's picture, for the tests: a PNG, or the 256x240 palette
   indexes as they are (2 bytes each, little-endian). */
static void shot(const uint16_t *pic, const char *path) {
    size_t n = strlen(path);
    if (n > 4 && !strcmp(path + n - 4, ".png")) { video_save_png(pic, path); return; }
    FILE *f = fopen(path, "wb");
    if (!f) { fprintf(stderr, "can't write %s\n", path); return; }
    for (int i = 0; i < 256 * 240; i++) {
        uint8_t b[2] = { (uint8_t)pic[i], (uint8_t)(pic[i] >> 8) };
        fwrite(b, 1, 2, f);
    }
    fclose(f);
}

/* A key: returns 0 when it closes the menu, and what was chosen. */
static int press(int key, int *chosen) {
    switch (key) {
    case MENU_UP:   cursor = (cursor + ITEM_COUNT - 1) % ITEM_COUNT; break;
    case MENU_DOWN: cursor = (cursor + 1) % ITEM_COUNT; break;
    case MENU_LEFT: case MENU_RIGHT:
        if (cursor == ITEM_SLOT)
            runtime_set_slot((runtime_slot() + (key == MENU_LEFT ? 2 : 0)) % 4 + 1);
        else if (cursor == ITEM_SOUND) runtime_sound_step(key == MENU_LEFT ? -1 : 1);
        else if (cursor == ITEM_WINDOW) runtime_window_step(key == MENU_LEFT ? -1 : 1);
        break;
    case MENU_BACK: *chosen = ITEM_RESUME; return 0;
    case MENU_OK:
        if (cursor == ITEM_SLOT) {          /* OK on the slot: the next one */
            runtime_set_slot(runtime_slot() % 4 + 1);
            break;
        }
        if (cursor == ITEM_SOUND) { runtime_sound_toggle(); break; }    /* as M */
        if (cursor == ITEM_WINDOW) { runtime_window_toggle(); break; }  /* as Cmd+F */
        *chosen = cursor;
        return 0;
    }
    return 1;
}

void menu_run(const uint16_t *fb) {
    static uint16_t pic[256 * 240];
    wanted = 0;
    is_open = 1;
    cursor = ITEM_RESUME;
    int chosen = ITEM_RESUME;
    unsigned long long frame = runtime_frame();
    fprintf(stderr, "frame %llu: MENU\n", frame);
    video_pause_audio(1);
    while (is_open) {
        while (is_open && key_at < key_count) {
            int k = keys[key_at].key;
            const char *path = keys[key_at].path;
            key_at++;
            if (k == MENU_SHOT) { draw(pic, fb); shot(pic, path); }
            else if (!press(k, &chosen)) is_open = 0;
        }
        if (key_at == key_count) key_at = key_count = 0;
        if (!is_open) break;
        if (runtime_headless()) {           /* a script's keys ran out: close */
            is_open = 0;
            break;
        }
        draw(pic, fb);
        runtime_menu_present(pic);
    }
    key_at = key_count = 0;
    video_pause_audio(0);
    fprintf(stderr, "frame %llu: MENU CLOSED (%s)\n", runtime_frame(), item_names[chosen]);
    switch (chosen) {
    case ITEM_SAVE:  runtime_menu_save(); break;
    case ITEM_LOAD:  runtime_menu_load(); break;
    case ITEM_RESET: runtime_menu_reset(); break;
    case ITEM_QUIT:  exit(0);               /* at_exit writes the saves, the movie */
    default: break;
    }
}
