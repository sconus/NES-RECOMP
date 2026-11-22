/* nesrecomp runtime: the pause menu (menu.h, PLAN-pause.md). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/stat.h>
#include "menu.h"
#include "video.h"
#include "gamepad.h"
#include "input.h"

/* The layout, in NES pixels (tests/check_menu.py reads these). */
#define MENU_BOX_X 36
#define MENU_BOX_Y 43
#define MENU_BOX_W 184
#define MENU_BOX_H 153
#define MENU_TITLE_Y 53
#define MENU_ITEM_X 64
#define MENU_CURSOR_X 54
#define MENU_ITEM_Y 71
#define MENU_LINE_H 13
#define MENU_INFO_X 136                     /* the slot's EMPTY / date */

/* NES colours (the picture holds palette indexes). */
#define INK_BOX 0x0F                        /* black */
#define INK_EDGE 0x00                       /* dark grey */
#define INK_TITLE 0x30                      /* white */
#define INK_ITEM 0x10                       /* light grey */
#define INK_PICKED 0x30                     /* white */
#define INK_CURSOR 0x21                     /* light blue */

/* The CONTROLLERS page (PLAN-controllers.md): in the same box, its
   lines, then what each slot holds. */
#define CTRL_LIST_Y 110                     /* "1 XBOX WIRELESS CONTROLLER" */
#define CTRL_LIST_H 12
#define CTRL_LIST_CHARS 25                  /* of the name */

/* The button test: a bigger box, six small pads (controllers 1-4, then
   the keyboard's two players), two to a row. */
#define TEST_BOX_X 8
#define TEST_BOX_Y 14
#define TEST_BOX_W 240
#define TEST_BOX_H 212
#define TEST_TITLE_Y 20
#define TEST_COL0 16
#define TEST_COL1 132
#define TEST_ROW0 34
#define TEST_ROW_H 56
#define TEST_PAD_DY 10                      /* the pad below its label */
#define TEST_LABEL_CHARS 18
#define TEST_FOOT_Y 210
#define TEST_BODY_X 0                       /* the pad's body, from its top left */
#define TEST_BODY_Y 6
#define TEST_BODY_W 108
#define TEST_BODY_H 34
#define INK_BODY 0x00                       /* dark grey */
#define INK_OFF 0x0F                        /* a button on the body: black */
#define INK_OFF_OUT 0x00                    /* a shoulder, off the body: dark grey */
#define INK_LIT 0x2A                        /* green */
#define INK_NONE 0x00                       /* "NO CONTROLLER" */

/* The pad's parts (tests/check_menu.py reads these): each one's
   rectangle from the pad's top left. MID is the D-pad's middle, never
   lit. */
enum { PART_UP, PART_DOWN, PART_LEFT, PART_RIGHT, PART_MID, PART_SELECT, PART_START,
       PART_B, PART_A, PART_LB, PART_RB, PART_HOME, PART_COUNT };
static const struct { int part, x, y, w, h; } pad_parts[PART_COUNT] = {
    { PART_UP, 16, 11, 8, 8 },
    { PART_DOWN, 16, 27, 8, 8 },
    { PART_LEFT, 8, 19, 8, 8 },
    { PART_RIGHT, 24, 19, 8, 8 },
    { PART_MID, 16, 19, 8, 8 },
    { PART_SELECT, 40, 26, 12, 5 },
    { PART_START, 56, 26, 12, 5 },
    { PART_B, 76, 20, 10, 10 },
    { PART_A, 92, 20, 10, 10 },
    { PART_LB, 8, 0, 24, 4 },
    { PART_RB, 76, 0, 24, 4 },
    { PART_HOME, 50, 12, 8, 6 },
};
static const char *const part_names[PART_COUNT] = {
    "UP", "DOWN", "LEFT", "RIGHT", "", "SELECT", "START", "B", "A", "LB", "RB", "HOME",
};

enum { ITEM_RESUME, ITEM_SAVE, ITEM_LOAD, ITEM_SLOT, ITEM_RESET, ITEM_SOUND, ITEM_WINDOW,
       ITEM_CONTROLLERS, ITEM_QUIT, ITEM_COUNT };
static const char *const item_names[ITEM_COUNT] = {
    "RESUME", "SAVE STATE", "LOAD STATE", "SLOT", "RESET", "SOUND", "WINDOW", "CONTROLLERS",
    "QUIT",
};

/* The pages: the menu itself, CONTROLLERS, and its button test. */
enum { PAGE_MAIN, PAGE_CONTROLLERS, PAGE_TEST };
enum { CTRL_TEST, CTRL_BACK, CTRL_COUNT };
static const char *const ctrl_names[CTRL_COUNT] = { "BUTTON TEST", "BACK" };

static int wanted, is_open, cursor, page, ctrl_cursor;

#define MAX_KEYS 64
static struct { int key; const char *path; } keys[MAX_KEYS];
static int key_count, key_at;

void menu_request(void) { wanted = 1; }
int menu_wanted(void) { return wanted; }
int menu_is_open(void) { return is_open; }
int menu_mode(void) { return !is_open ? 0 : page == PAGE_TEST ? 2 : 1; }

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

static void centred(uint16_t *out, int y, const char *s, uint16_t ink) {
    draw_text_5x7(out, 128 - ((int)strlen(s) * 6 - 1) / 2, y, s, ink);
}

/* What one pad holds now, as the button test shows it: a bit per part. */
static unsigned pad_lit(const struct pad_info *p) {
    static const struct { uint8_t btn; int part; } nes[8] = {
        { BTN_UP, PART_UP }, { BTN_DOWN, PART_DOWN }, { BTN_LEFT, PART_LEFT },
        { BTN_RIGHT, PART_RIGHT }, { BTN_SELECT, PART_SELECT }, { BTN_START, PART_START },
        { BTN_B, PART_B }, { BTN_A, PART_A },
    };
    unsigned lit = 0;
    for (int i = 0; i < 8; i++)
        if (p->nes & nes[i].btn) lit |= 1u << nes[i].part;
    if (p->lb) lit |= 1u << PART_LB;
    if (p->rb) lit |= 1u << PART_RB;
    if (p->home) lit |= 1u << PART_HOME;
    return lit;
}

/* The six pads: controllers 1-4, then keyboard players 1 and 2. */
#define TEST_PADS 6
static void test_read(struct pad_info *p) {
    for (int i = 0; i < 4; i++) gamepad_info(i, &p[i]);
    for (int k = 0; k < 2; k++) {
        memset(&p[4 + k], 0, sizeof p[4 + k]);
        p[4 + k].present = 1;
        p[4 + k].nes = runtime_keyboard_buttons(k);
    }
}

static void test_label(char *out, size_t size, int i, const struct pad_info *p) {
    if (i >= 4) snprintf(out, size, "KEYBOARD %d", i - 3);
    else if (!p->present) snprintf(out, size, "%d -", i + 1);
    else snprintf(out, size, "%d %.*s", i + 1, TEST_LABEL_CHARS - 2, p->brand ? p->brand : p->name);
}

static void draw_test(uint16_t *out) {
    box(out, TEST_BOX_X - 1, TEST_BOX_Y - 1, TEST_BOX_W + 2, TEST_BOX_H + 2, INK_EDGE);
    box(out, TEST_BOX_X, TEST_BOX_Y, TEST_BOX_W, TEST_BOX_H, INK_BOX);
    centred(out, TEST_TITLE_Y, "BUTTON TEST", INK_TITLE);
    struct pad_info p[TEST_PADS];
    test_read(p);
    for (int i = 0; i < TEST_PADS; i++) {
        int x = i % 2 ? TEST_COL1 : TEST_COL0, y = TEST_ROW0 + (i / 2) * TEST_ROW_H;
        char label[48];
        test_label(label, sizeof label, i, &p[i]);
        unsigned lit = p[i].present ? pad_lit(&p[i]) : 0;
        draw_text_5x7(out, x, y, label, lit ? INK_PICKED : INK_ITEM);
        if (!p[i].present) {
            draw_text_5x7(out, x, y + TEST_PAD_DY + TEST_BODY_Y + 13, "NO CONTROLLER", INK_NONE);
            continue;
        }
        int px = x, py = y + TEST_PAD_DY;
        box(out, px + TEST_BODY_X, py + TEST_BODY_Y, TEST_BODY_W, TEST_BODY_H, INK_BODY);
        for (int k = 0; k < PART_COUNT; k++) {
            int on = (lit >> pad_parts[k].part) & 1;
            uint16_t ink = on ? INK_LIT : pad_parts[k].y < TEST_BODY_Y ? INK_OFF_OUT : INK_OFF;
            box(out, px + pad_parts[k].x, py + pad_parts[k].y, pad_parts[k].w, pad_parts[k].h, ink);
        }
    }
    centred(out, TEST_FOOT_Y, "TO LEAVE: ESC, HOME, OR HOLD SEL+START", INK_ITEM);
}

/* The button test says each press in the terminal ("controller 2: A"). */
static unsigned test_prev[TEST_PADS];

static void test_poll(int start) {
    struct pad_info p[TEST_PADS];
    test_read(p);
    for (int i = 0; i < TEST_PADS; i++) {
        unsigned lit = p[i].present ? pad_lit(&p[i]) : 0;
        unsigned fresh = lit & ~test_prev[i];
        test_prev[i] = lit;
        if (start) continue;
        for (int k = 0; k < PART_COUNT; k++)
            if (fresh & (1u << k)) {
                if (i < 4) fprintf(stderr, "controller %d: %s\n", i + 1, part_names[k]);
                else fprintf(stderr, "keyboard %d: %s\n", i - 3, part_names[k]);
            }
    }
}

static void draw_controllers(uint16_t *out) {
    for (int i = 0; i < CTRL_COUNT; i++)
        draw_text_5x7(out, MENU_ITEM_X, MENU_ITEM_Y + i * MENU_LINE_H, ctrl_names[i],
                      i == ctrl_cursor ? INK_PICKED : INK_ITEM);
    draw_text_5x7(out, MENU_CURSOR_X, MENU_ITEM_Y + ctrl_cursor * MENU_LINE_H, ">", INK_CURSOR);
    for (int i = 0; i < 4; i++) {
        struct pad_info p;
        gamepad_info(i, &p);
        char line[48];
        if (p.present) snprintf(line, sizeof line, "%d %.*s", i + 1, CTRL_LIST_CHARS, p.name);
        else snprintf(line, sizeof line, "%d -", i + 1);
        draw_text_5x7(out, MENU_CURSOR_X, CTRL_LIST_Y + i * CTRL_LIST_H, line, INK_ITEM);
    }
}

static void draw(uint16_t *out, const uint16_t *fb) {
    for (int i = 0; i < 256 * 240; i++) out[i] = darker(fb[i]);
    if (page == PAGE_TEST) { draw_test(out); return; }
    box(out, MENU_BOX_X - 1, MENU_BOX_Y - 1, MENU_BOX_W + 2, MENU_BOX_H + 2, INK_EDGE);
    box(out, MENU_BOX_X, MENU_BOX_Y, MENU_BOX_W, MENU_BOX_H, INK_BOX);
    centred(out, MENU_TITLE_Y, page == PAGE_CONTROLLERS ? "CONTROLLERS" : "PAUSED", INK_TITLE);
    if (page == PAGE_CONTROLLERS) { draw_controllers(out); return; }
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

/* A key on the CONTROLLERS page or its button test. */
static void back_to_main(void) {
    page = PAGE_MAIN;
    fprintf(stderr, "frame %llu: MENU\n", runtime_frame());
}

static void press_controllers(int key) {
    if (page == PAGE_TEST) {
        if (key == MENU_LEAVE) {
            page = PAGE_CONTROLLERS;
            fprintf(stderr, "frame %llu: CONTROLLERS\n", runtime_frame());
        }
        return;                             /* every other button only lights up */
    }
    switch (key) {
    case MENU_UP:   ctrl_cursor = (ctrl_cursor + CTRL_COUNT - 1) % CTRL_COUNT; break;
    case MENU_DOWN: ctrl_cursor = (ctrl_cursor + 1) % CTRL_COUNT; break;
    case MENU_BACK: case MENU_LEAVE: back_to_main(); break;
    case MENU_OK:
        if (ctrl_cursor == CTRL_BACK) back_to_main();
        else {
            page = PAGE_TEST;
            test_poll(1);                   /* buttons held now aren't presses */
            fprintf(stderr, "frame %llu: BUTTON TEST\n", runtime_frame());
        }
        break;
    }
}

/* A key: returns 0 when it closes the menu, and what was chosen. */
static int press(int key, int *chosen) {
    if (page != PAGE_MAIN) { press_controllers(key); return 1; }
    switch (key) {
    case MENU_UP:   cursor = (cursor + ITEM_COUNT - 1) % ITEM_COUNT; break;
    case MENU_DOWN: cursor = (cursor + 1) % ITEM_COUNT; break;
    case MENU_LEFT: case MENU_RIGHT:
        if (cursor == ITEM_SLOT)
            runtime_set_slot((runtime_slot() + (key == MENU_LEFT ? 2 : 0)) % 4 + 1);
        else if (cursor == ITEM_SOUND) runtime_sound_step(key == MENU_LEFT ? -1 : 1);
        else if (cursor == ITEM_WINDOW) runtime_window_step(key == MENU_LEFT ? -1 : 1);
        break;
    case MENU_BACK: case MENU_LEAVE: *chosen = ITEM_RESUME; return 0;
    case MENU_OK:
        if (cursor == ITEM_CONTROLLERS) {
            page = PAGE_CONTROLLERS;
            ctrl_cursor = CTRL_TEST;
            fprintf(stderr, "frame %llu: CONTROLLERS\n", runtime_frame());
            break;
        }
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
    page = PAGE_MAIN;
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
            else if (k == MENU_VPAD) {
                int pl;
                unsigned bt;
                if (gamepad_parse_virtual(path, &pl, &bt)) gamepad_virtual(pl, bt);
                if (page == PAGE_TEST) test_poll(0);
            } else if (!press(k, &chosen)) is_open = 0;
        }
        if (key_at == key_count) key_at = key_count = 0;
        if (!is_open) break;
        if (runtime_headless()) {           /* a script's keys ran out: close */
            is_open = 0;
            break;
        }
        if (page == PAGE_TEST) test_poll(0);
        draw(pic, fb);
        runtime_menu_present(pic);
    }
    key_at = key_count = 0;
    page = PAGE_MAIN;
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
