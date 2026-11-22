/* nesrecomp runtime: which keys and pad buttons are the NES buttons
   (controls.h, PLAN-controllers.md steps 3 and 4). */
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <SDL.h>
#include "controls.h"
#include "input.h"

const char *const controls_button_names[CB_COUNT] = {
    "UP", "DOWN", "LEFT", "RIGHT", "B", "A", "SELECT", "START",
};
static const uint8_t button_bits[CB_COUNT] = {
    BTN_UP, BTN_DOWN, BTN_LEFT, BTN_RIGHT, BTN_B, BTN_A, BTN_SELECT, BTN_START,
};

/* Today's layout: controller 1 on the arrows and the keys around the
   right hand, controller 2 on WASD and the keys around the left. */
static const int default_keys[2][CB_COUNT] = {
    { SDL_SCANCODE_UP, SDL_SCANCODE_DOWN, SDL_SCANCODE_LEFT, SDL_SCANCODE_RIGHT,
      SDL_SCANCODE_Z, SDL_SCANCODE_X, SDL_SCANCODE_RSHIFT, SDL_SCANCODE_RETURN },
    { SDL_SCANCODE_W, SDL_SCANCODE_S, SDL_SCANCODE_A, SDL_SCANCODE_D,
      SDL_SCANCODE_F, SDL_SCANCODE_G, SDL_SCANCODE_Q, SDL_SCANCODE_E },
};
static int keys[2][CB_COUNT] = {
    { SDL_SCANCODE_UP, SDL_SCANCODE_DOWN, SDL_SCANCODE_LEFT, SDL_SCANCODE_RIGHT,
      SDL_SCANCODE_Z, SDL_SCANCODE_X, SDL_SCANCODE_RSHIFT, SDL_SCANCODE_RETURN },
    { SDL_SCANCODE_W, SDL_SCANCODE_S, SDL_SCANCODE_A, SDL_SCANCODE_D,
      SDL_SCANCODE_F, SDL_SCANCODE_G, SDL_SCANCODE_Q, SDL_SCANCODE_E },
};
static const char *file;

/* The pads' buttons that can be chosen, by position (SDL's A is the
   bottom face button on every brand, its B the right one, and so on):
   the PADS page's name for each, and the file's. Not every pad has the
   others (paddles, Share, the touch pad), so none of those. */
static const struct { int pad; const char *name, *file; } pad_choices[] = {
    { SDL_CONTROLLER_BUTTON_A, "BOTTOM BUTTON", "bottom" },
    { SDL_CONTROLLER_BUTTON_B, "RIGHT BUTTON", "right" },
    { SDL_CONTROLLER_BUTTON_X, "LEFT BUTTON", "left" },
    { SDL_CONTROLLER_BUTTON_Y, "TOP BUTTON", "top" },
    { SDL_CONTROLLER_BUTTON_BACK, "SELECT", "select" },
    { SDL_CONTROLLER_BUTTON_START, "START", "start" },
    { SDL_CONTROLLER_BUTTON_DPAD_UP, "D-PAD UP", "dpad_up" },
    { SDL_CONTROLLER_BUTTON_DPAD_DOWN, "D-PAD DOWN", "dpad_down" },
    { SDL_CONTROLLER_BUTTON_DPAD_LEFT, "D-PAD LEFT", "dpad_left" },
    { SDL_CONTROLLER_BUTTON_DPAD_RIGHT, "D-PAD RIGHT", "dpad_right" },
    { SDL_CONTROLLER_BUTTON_LEFTSTICK, "LEFT STICK IN", "left_stick" },
    { SDL_CONTROLLER_BUTTON_RIGHTSTICK, "RIGHT STICK IN", "right_stick" },
};
#define PAD_CHOICES (int)(sizeof pad_choices / sizeof pad_choices[0])
/* Today's layout (gamepad.c's comment): B on the bottom face button, A
   on the right one, as an NES pad's B is left of its A. */
static const int default_pads[CB_COUNT] = {
    SDL_CONTROLLER_BUTTON_DPAD_UP, SDL_CONTROLLER_BUTTON_DPAD_DOWN,
    SDL_CONTROLLER_BUTTON_DPAD_LEFT, SDL_CONTROLLER_BUTTON_DPAD_RIGHT,
    SDL_CONTROLLER_BUTTON_A, SDL_CONTROLLER_BUTTON_B,
    SDL_CONTROLLER_BUTTON_BACK, SDL_CONTROLLER_BUTTON_START,
};
static int pads[CB_COUNT] = {
    SDL_CONTROLLER_BUTTON_DPAD_UP, SDL_CONTROLLER_BUTTON_DPAD_DOWN,
    SDL_CONTROLLER_BUTTON_DPAD_LEFT, SDL_CONTROLLER_BUTTON_DPAD_RIGHT,
    SDL_CONTROLLER_BUTTON_A, SDL_CONTROLLER_BUTTON_B,
    SDL_CONTROLLER_BUTTON_BACK, SDL_CONTROLLER_BUTTON_START,
};

static int pad_choice(int pad) {
    for (int i = 0; i < PAD_CHOICES; i++)
        if (pad_choices[i].pad == pad) return i;
    return -1;
}

int controls_pad(int button) { return pads[button]; }

const char *controls_pad_name(int pad) {
    int i = pad_choice(pad);
    if (i >= 0) return pad_choices[i].name;
    if (pad == SDL_CONTROLLER_BUTTON_LEFTSHOULDER) return "LEFT SHOULDER";
    if (pad == SDL_CONTROLLER_BUTTON_RIGHTSHOULDER) return "RIGHT SHOULDER";
    if (pad == SDL_CONTROLLER_BUTTON_GUIDE) return "HOME";
    return "?";
}

int controls_pad_from_name(const char *name) {
    for (int i = 0; i < PAD_CHOICES; i++)
        if (!strcmp(name, pad_choices[i].file)) return pad_choices[i].pad;
    return -1;
}

uint8_t controls_pad_buttons(const uint8_t *held, int n) {
    uint8_t out = 0;
    for (int b = 0; b < CB_COUNT; b++)
        if (pads[b] >= 0 && pads[b] < n && held[pads[b]]) out |= button_bits[b];
    return out;
}

int controls_key(int player, int button) { return keys[player & 1][button]; }

const char *controls_key_name(int sc) {
    static char out[32];
    const char *n = sc > 0 && sc < SDL_NUM_SCANCODES ? SDL_GetScancodeName((SDL_Scancode)sc) : "";
    if (!n || !*n) return "?";
    size_t i = 0;
    for (; n[i] && i < sizeof out - 1; i++) out[i] = (char)toupper((unsigned char)n[i]);
    out[i] = 0;
    return out;
}

int controls_reserved(int sc) {
    static const int kept[] = {
        SDL_SCANCODE_ESCAPE, SDL_SCANCODE_M, SDL_SCANCODE_R, SDL_SCANCODE_V, SDL_SCANCODE_P,
        SDL_SCANCODE_BACKSPACE, SDL_SCANCODE_GRAVE, SDL_SCANCODE_NONUSBACKSLASH,
        SDL_SCANCODE_LGUI, SDL_SCANCODE_RGUI, SDL_SCANCODE_LCTRL, SDL_SCANCODE_RCTRL,
    };
    if (sc <= 0 || sc >= SDL_NUM_SCANCODES) return 1;
    if (sc >= SDL_SCANCODE_1 && sc <= SDL_SCANCODE_0) return 1;     /* the disk keys */
    for (size_t i = 0; i < sizeof kept / sizeof kept[0]; i++)
        if (sc == kept[i]) return 1;
    const char *n = SDL_GetScancodeName((SDL_Scancode)sc);
    return !n || !*n;
}

static void write_file(void) {
    if (!file) return;
    FILE *f = fopen(file, "w");
    if (!f) { fprintf(stderr, "controls: can't write %s\n", file); return; }
    fprintf(f, "# nesrecomp's keys and pad buttons (the pause menu's CONTROLLERS writes this):\n"
               "# keyboard 1 or 2 or the pads, NES button, the key as SDL names it\n"
               "# or the pad button by position\n"
               "version 2\n");
    for (int p = 0; p < 2; p++)
        for (int b = 0; b < CB_COUNT; b++) {
            char lower[8];
            size_t i = 0;
            for (; controls_button_names[b][i]; i++)
                lower[i] = (char)tolower((unsigned char)controls_button_names[b][i]);
            lower[i] = 0;
            fprintf(f, "keyboard%d %s %s\n", p + 1, lower,
                    SDL_GetScancodeName((SDL_Scancode)keys[p][b]));
        }
    for (int b = 0; b < CB_COUNT; b++) {
        char lower[8];
        size_t i = 0;
        for (; controls_button_names[b][i]; i++)
            lower[i] = (char)tolower((unsigned char)controls_button_names[b][i]);
        lower[i] = 0;
        fprintf(f, "pad %s %s\n", lower, pad_choices[pad_choice(pads[b])].file);
    }
    fclose(f);
}

int controls_set(int player, int button, int sc, int *op, int *ob) {
    player &= 1;
    if (controls_reserved(sc)) return 0;
    int old = keys[player][button], swapped = 0;
    for (int p = 0; p < 2; p++)
        for (int b = 0; b < CB_COUNT; b++)
            if (keys[p][b] == sc && !(p == player && b == button)) {
                keys[p][b] = old;
                if (op) *op = p;
                if (ob) *ob = b;
                swapped = 1;
            }
    keys[player][button] = sc;
    if (old != sc) write_file();
    return swapped ? 2 : 1;
}

void controls_defaults(int player) {
    player &= 1;
    int other = player ^ 1;
    memcpy(keys[player], default_keys[player], sizeof keys[player]);
    /* The other player keeps its keys, unless one of them is one of
       these: that one goes back to its own default too. */
    for (int b = 0; b < CB_COUNT; b++)
        for (int k = 0; k < CB_COUNT; k++)
            if (keys[other][b] == keys[player][k]) keys[other][b] = default_keys[other][b];
    write_file();
}

int controls_pad_set(int button, int pad, int *ob) {
    if (pad_choice(pad) < 0) return 0;
    int old = pads[button], swapped = 0;
    for (int b = 0; b < CB_COUNT; b++)
        if (pads[b] == pad && b != button) {
            pads[b] = old;
            if (ob) *ob = b;
            swapped = 1;
        }
    pads[button] = pad;
    if (old != pad) write_file();
    return swapped ? 2 : 1;
}

void controls_pad_defaults(void) {
    memcpy(pads, default_pads, sizeof pads);
    write_file();
}

uint8_t controls_buttons(int player, const uint8_t *state, int nkeys) {
    uint8_t out = 0;
    for (int b = 0; b < CB_COUNT; b++) {
        int sc = keys[player & 1][b];
        if (sc < nkeys && state[sc]) out |= button_bits[b];
    }
    return out;
}

int controls_scancode(const char *name) {
    char buf[64];
    size_t i = 0;
    for (; name[i] && i < sizeof buf - 1; i++) buf[i] = name[i] == '_' ? ' ' : name[i];
    buf[i] = 0;
    return SDL_GetScancodeFromName(buf);
}

/* Read `path` into k and pd: 1, or 0 with why. Version 1 (step 3's)
   has only keys: the pads keep the usual layout. */
static int read_file(const char *path, int k[2][CB_COUNT], int pd[CB_COUNT], char *why, size_t size) {
    FILE *f = fopen(path, "r");
    if (!f) { snprintf(why, size, "not there yet"); return 0; }
    memcpy(k, default_keys, sizeof default_keys);
    memcpy(pd, default_pads, sizeof default_pads);
    char line[256];
    int n = 0, version = 0, ok = 1;
    while (ok && fgets(line, sizeof line, f)) {
        n++;
        line[strcspn(line, "\r\n")] = 0;
        if (!line[0] || line[0] == '#') continue;
        int v, p;
        char btn[16];
        int at = 0;
        if (sscanf(line, "version %d", &v) == 1) {
            version = v;
            if (v != 1 && v != 2) { snprintf(why, size, "version %d, not 1 or 2", v); ok = 0; }
            continue;
        }
        if (!version) { snprintf(why, size, "no version line before line %d", n); ok = 0; break; }
        char pname[32], extra[2];
        if (!strncmp(line, "pad ", 4)) {
            int b = 0, pad = -1;
            if (version >= 2 && sscanf(line, "pad %15s %31s %1s", btn, pname, extra) == 2) {
                for (; b < CB_COUNT; b++)
                    if (!SDL_strcasecmp(btn, controls_button_names[b])) break;
                pad = controls_pad_from_name(pname);
            }
            if (version < 2 || b == CB_COUNT || pad < 0) {
                snprintf(why, size, "line %d not understood", n);
                ok = 0;
                break;
            }
            pd[b] = pad;
            continue;
        }
        if (sscanf(line, "keyboard%d %15s %n", &p, btn, &at) != 2 || p < 1 || p > 2 || !at) {
            snprintf(why, size, "line %d not understood", n);
            ok = 0;
            break;
        }
        int b = 0;
        for (; b < CB_COUNT; b++)
            if (!SDL_strcasecmp(btn, controls_button_names[b])) break;
        int sc = SDL_GetScancodeFromName(line + at);
        if (b == CB_COUNT || sc == SDL_SCANCODE_UNKNOWN || controls_reserved(sc)) {
            snprintf(why, size, "line %d not understood", n);
            ok = 0;
            break;
        }
        k[p - 1][b] = sc;
    }
    fclose(f);
    if (ok && !version) { snprintf(why, size, "no version line"); ok = 0; }
    for (int i = 0; ok && i < 2 * CB_COUNT; i++)
        for (int j = i + 1; ok && j < 2 * CB_COUNT; j++)
            if (k[i / CB_COUNT][i % CB_COUNT] == k[j / CB_COUNT][j % CB_COUNT]) {
                snprintf(why, size, "a key used twice");
                ok = 0;
            }
    for (int i = 0; ok && i < CB_COUNT; i++)
        for (int j = i + 1; ok && j < CB_COUNT; j++)
            if (pd[i] == pd[j]) {
                snprintf(why, size, "a pad button used twice");
                ok = 0;
            }
    return ok;
}

void controls_use_file(const char *path) {
    int k[2][CB_COUNT], pd[CB_COUNT];
    char why[64] = "";
    file = path;
    if (read_file(path, k, pd, why, sizeof why)) {
        memcpy(keys, k, sizeof keys);
        memcpy(pads, pd, sizeof pads);
        fprintf(stderr, "controls: read %s\n", path);
    } else {
        memcpy(keys, default_keys, sizeof keys);
        memcpy(pads, default_pads, sizeof pads);
        fprintf(stderr, "controls: %s %s: the usual keys\n", path, why);
    }
}

/* --test-controls: the remapping, with a pretend keyboard and files in
   the system's temporary folder. */
static int fails;
static void expect(int ok, const char *what) {
    if (!ok) { fprintf(stderr, "FAIL  controls: %s\n", what); fails++; }
}

static uint8_t press(int player, int sc) {
    uint8_t state[SDL_NUM_SCANCODES] = { 0 };
    state[sc] = 1;
    return controls_buttons(player, state, SDL_NUM_SCANCODES);
}

static uint8_t pad_press(int pad) {
    uint8_t held[SDL_CONTROLLER_BUTTON_MAX] = { 0 };
    held[pad] = 1;
    return controls_pad_buttons(held, SDL_CONTROLLER_BUTTON_MAX);
}

static void write_text(const char *path, const char *text) {
    FILE *f = fopen(path, "w");
    if (f) { fputs(text, f); fclose(f); }
}

int controls_self_test(void) {
    char path[512];
    const char *tmp = getenv("TMPDIR");
    if (!tmp) tmp = getenv("TEMP");
    if (!tmp) tmp = "/tmp";
    snprintf(path, sizeof path, "%s/nesrecomp-controls-test-%d.txt", tmp, (int)SDL_GetTicks());
    remove(path);

    controls_use_file(path);                        /* missing: the usual keys */
    expect(press(0, SDL_SCANCODE_X) == BTN_A && press(0, SDL_SCANCODE_Z) == BTN_B,
           "the usual keys: X is A, Z is B");
    expect(press(1, SDL_SCANCODE_G) == BTN_A && press(0, SDL_SCANCODE_G) == 0,
           "the usual keys: G is player 2's A, not player 1's");
    expect(!strcmp(controls_key_name(SDL_SCANCODE_RSHIFT), "RIGHT SHIFT"), "a key's name");

    int op = -1, ob = -1;
    expect(controls_set(0, CB_A, SDL_SCANCODE_K, &op, &ob) == 1, "A to K");
    expect(press(0, SDL_SCANCODE_K) == BTN_A, "K now presses A");
    expect(press(0, SDL_SCANCODE_X) == 0, "X no longer presses A");

    static const int kept[] = { SDL_SCANCODE_ESCAPE, SDL_SCANCODE_M, SDL_SCANCODE_R,
                                SDL_SCANCODE_V, SDL_SCANCODE_P, SDL_SCANCODE_5,
                                SDL_SCANCODE_BACKSPACE, SDL_SCANCODE_GRAVE, SDL_SCANCODE_LGUI,
                                SDL_SCANCODE_LCTRL };
    for (size_t i = 0; i < sizeof kept / sizeof kept[0]; i++) {
        char what[64];
        snprintf(what, sizeof what, "%s refused", controls_key_name(kept[i]));
        expect(controls_set(0, CB_B, kept[i], NULL, NULL) == 0, what);
    }
    expect(press(0, SDL_SCANCODE_Z) == BTN_B, "a refused key leaves B on Z");

    /* A clash swaps: player 1's B onto W (player 2's UP), W's button gets Z. */
    expect(controls_set(0, CB_B, SDL_SCANCODE_W, &op, &ob) == 2 && op == 1 && ob == CB_UP,
           "B to W swaps with player 2's UP");
    expect(press(0, SDL_SCANCODE_W) == BTN_B && press(1, SDL_SCANCODE_W) == 0, "W is player 1's B");
    expect(press(1, SDL_SCANCODE_Z) == BTN_UP, "Z is player 2's UP");

    /* Written, and read back by a fresh start. */
    int want[2][CB_COUNT];
    memcpy(want, keys, sizeof want);
    memcpy(keys, default_keys, sizeof keys);
    controls_use_file(path);
    expect(!memcmp(keys, want, sizeof want), "the file read back gives the same keys");

    controls_defaults(0);
    expect(press(0, SDL_SCANCODE_X) == BTN_A && press(0, SDL_SCANCODE_Z) == BTN_B &&
           press(0, SDL_SCANCODE_K) == 0, "DEFAULTS brings player 1's keys back");
    expect(press(1, SDL_SCANCODE_W) == BTN_UP && press(1, SDL_SCANCODE_Z) == 0,
           "... and player 2's UP, which had Z, back to W");
    controls_defaults(1);

    /* Missing, older, garbled: the usual keys, not a crash. */
    static const char *const bad[] = {
        "version 3\nkeyboard1 a K\n",
        "keyboard1 a K\n",
        "version 1\nkeyboard1 a\n",
        "version 1\nkeyboard3 a K\n",
        "version 1\nkeyboard1 jump K\n",
        "version 1\nkeyboard1 a NoSuchKey\n",
        "version 1\nkeyboard1 a Escape\n",
        "version 1\nkeyboard1 a K\nkeyboard1 b K\n",
        "version 1\nkeyboard1 a W\n",               /* W is still player 2's UP */
        "\x01\x02\xff garbage \n\n",
        "",
        "version 1\npad a top\n",                  /* the pads came with version 2 */
        "version 2\npad a\n",
        "version 2\npad a guide\n",               /* Home is the menu's */
        "version 2\npad a leftshoulder\n",
        "version 2\npad jump top\n",
        "version 2\npad a top\npad b top\n",
        "version 2\npad a top bottom\n",
    };
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; i++) {
        write_text(path, bad[i]);
        keys[0][CB_A] = SDL_SCANCODE_J;
        pads[CB_A] = SDL_CONTROLLER_BUTTON_Y;
        controls_use_file(path);
        char what[64];
        snprintf(what, sizeof what, "bad file %d gives the usual keys and pad", (int)i + 1);
        expect(!memcmp(keys, default_keys, sizeof keys) && !memcmp(pads, default_pads, sizeof pads),
               what);
    }
    write_text(path, "# a comment\nversion 1\r\nkeyboard1 select Right Ctrl\r\n"
                     "keyboard2 start Keypad Enter\n");
    controls_use_file(path);
    expect(keys[0][CB_SELECT] == SDL_SCANCODE_RSHIFT, "Right Ctrl is the window's: refused");
    write_text(path, "version 1\nkeyboard1 select Space\nkeyboard2 start Keypad Enter\n");
    controls_use_file(path);
    expect(keys[0][CB_SELECT] == SDL_SCANCODE_SPACE && keys[1][CB_START] == SDL_SCANCODE_KP_ENTER,
           "a good file with two-word key names");
    expect(!memcmp(pads, default_pads, sizeof pads), "a version 1 file: the usual pad");

    /* The pads (step 4): one layout, by position. */
    expect(pad_press(SDL_CONTROLLER_BUTTON_A) == BTN_B && pad_press(SDL_CONTROLLER_BUTTON_B) == BTN_A &&
           pad_press(SDL_CONTROLLER_BUTTON_X) == 0, "the usual pad: bottom is B, right is A");
    expect(controls_pad_set(CB_A, SDL_CONTROLLER_BUTTON_Y, &ob) == 1, "A to the top button");
    expect(pad_press(SDL_CONTROLLER_BUTTON_Y) == BTN_A && pad_press(SDL_CONTROLLER_BUTTON_B) == 0,
           "the top button now presses A, the right one nothing");
    ob = -1;
    expect(controls_pad_set(CB_A, SDL_CONTROLLER_BUTTON_A, &ob) == 2 && ob == CB_B,
           "A to the bottom button swaps with B");
    expect(pad_press(SDL_CONTROLLER_BUTTON_A) == BTN_A && pad_press(SDL_CONTROLLER_BUTTON_Y) == BTN_B,
           "bottom is A, and B has the top button A had");
    static const int fixed[] = { SDL_CONTROLLER_BUTTON_GUIDE, SDL_CONTROLLER_BUTTON_LEFTSHOULDER,
                                 SDL_CONTROLLER_BUTTON_RIGHTSHOULDER, SDL_CONTROLLER_BUTTON_MISC1,
                                 SDL_CONTROLLER_BUTTON_PADDLE1, SDL_CONTROLLER_BUTTON_TOUCHPAD, -1, 99 };
    for (size_t i = 0; i < sizeof fixed / sizeof fixed[0]; i++) {
        char what[64];
        snprintf(what, sizeof what, "pad button %d refused", fixed[i]);
        expect(controls_pad_set(CB_START, fixed[i], NULL) == 0, what);
    }
    expect(pad_press(SDL_CONTROLLER_BUTTON_START) == BTN_START, "a refused one leaves Start on Start");
    expect(!strcmp(controls_pad_name(SDL_CONTROLLER_BUTTON_A), "BOTTOM BUTTON") &&
           !strcmp(controls_pad_name(SDL_CONTROLLER_BUTTON_LEFTSHOULDER), "LEFT SHOULDER"),
           "pad buttons' names");
    int want_pads[CB_COUNT];
    memcpy(want, keys, sizeof want);
    memcpy(want_pads, pads, sizeof want_pads);
    memcpy(pads, default_pads, sizeof pads);
    controls_use_file(path);                        /* written as changed: read back */
    expect(!memcmp(pads, want_pads, sizeof pads) && !memcmp(keys, want, sizeof want),
           "the file read back gives the same pad and keys");
    controls_defaults(0);
    expect(!memcmp(pads, want_pads, sizeof pads), "keyboard DEFAULTS leaves the pad");
    controls_pad_defaults();
    expect(!memcmp(pads, default_pads, sizeof pads) && keys[0][CB_SELECT] == SDL_SCANCODE_RSHIFT,
           "the pad's DEFAULTS: the usual pad");
    write_text(path, "version 2\npad start left_stick\npad select right_stick\n");
    controls_use_file(path);
    expect(pads[CB_START] == SDL_CONTROLLER_BUTTON_LEFTSTICK &&
           pads[CB_SELECT] == SDL_CONTROLLER_BUTTON_RIGHTSTICK, "a good file with pad lines");
    remove(path);
    file = NULL;
    memcpy(keys, default_keys, sizeof keys);
    memcpy(pads, default_pads, sizeof pads);
    if (fails) { fprintf(stderr, "%d controls check(s) failed\n", fails); return 1; }
    printf("PASS: keyboard and pad remapping, refusals, swaps, defaults and controls.txt\n");
    return 0;
}
