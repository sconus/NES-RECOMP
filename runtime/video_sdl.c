/* nesrecomp runtime: the SDL2 window. Only this file knows about SDL, so
   headless runs (tests) never open a window. */
#define SDL_MAIN_HANDLED
#include <SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include "apu.h"
#include "event.h"
#include "gamepad.h"
#include "input.h"
#include "palette.h"
#include "ppu.h"
#include "record.h"
#include "state.h"
#include "menu.h"
#include "video.h"

/* The window's own shortcuts: Cmd on the Mac, Ctrl on Windows (where the
   Windows key belongs to Windows). */
#ifdef _WIN32
#define CMD_KEY KMOD_CTRL
#else
#define CMD_KEY KMOD_GUI
#endif

static SDL_Window *window;
static int window_scale;                /* the last whole-step size, for video_scale */
static SDL_Renderer *renderer;
static SDL_Texture *texture;
static uint64_t next_frame_at;           /* performance-counter ticks */
static uint64_t ticks_per_frame_1x;    /* at normal speed */
static const char *window_title;

/* ---- sound -------------------------------------------------------------

   The APU makes 48 kHz samples; each frame they go into SDL's audio
   queue. The video keeps the beat (60.0988 frames a second), so the
   sound has to follow it: if the queue grows, the APU is producing a
   touch too fast for this Mac's sound card, and the other way round. A
   small correction to the APU's sample clock (at most 0.5%, far too
   little to hear as a pitch change) keeps the queue near AUDIO_TARGET.
   Not while recording: the movie's sound must keep exactly to game time
   (48000 samples a game second), so the queue is left to drift, which
   at the sound card's tiny clock difference takes many minutes to
   matter (AUDIO_TOO_FULL catches it if it does). */
#define AUDIO_TARGET 2400                /* samples queued: 50 ms */
#define AUDIO_TOO_FULL 12000             /* 250 ms: drop it and start again */

static SDL_AudioDeviceID audio;
static int muted;

void video_init_audio(void) {
    if (SDL_InitSubSystem(SDL_INIT_AUDIO) != 0) {
        fprintf(stderr, "no sound: %s\n", SDL_GetError());
        return;
    }
    SDL_AudioSpec want = { 0 }, have;
    want.freq = 48000;
    want.format = AUDIO_S16SYS;
    want.channels = 1;
    want.samples = 512;
    audio = SDL_OpenAudioDevice(NULL, 0, &want, &have, 0);
    if (!audio) {
        fprintf(stderr, "no sound: %s\n", SDL_GetError());
        return;
    }
    /* Start with the queue at its target depth (as silence), so the
       small rate correction doesn't have to fill it up over many seconds. */
    static const int16_t silence[AUDIO_TARGET];
    SDL_QueueAudio(audio, silence, sizeof silence);
    SDL_PauseAudioDevice(audio, 0);
}

static int blipped;                     /* since the menu paused the sound */

void video_pause_audio(int on) {
    if (!audio) return;
    /* After a blip the game's old sound is gone: start again from the
       queue's silence, so the game's sound picks up without a gap. */
    if (!on && blipped) video_restart_audio();
    blipped = 0;
    SDL_PauseAudioDevice(audio, on);
}

/* The menu's blip: played at once, in place of anything queued. */
void video_blip(const int16_t *samples, int n) {
    if (!audio || muted) return;
    SDL_ClearQueuedAudio(audio);
    SDL_QueueAudio(audio, samples, (Uint32)n * sizeof *samples);
    SDL_PauseAudioDevice(audio, 0);
    blipped = 1;
}

void video_restart_audio(void) {
    if (!audio) return;
    static const int16_t silence[AUDIO_TARGET];
    SDL_ClearQueuedAudio(audio);
    if (!muted) SDL_QueueAudio(audio, silence, sizeof silence);
}

void video_queue_audio(const int16_t *samples, int n) {
    if (!audio || muted) return;
    SDL_QueueAudio(audio, samples, (Uint32)n * sizeof *samples);
    int queued = (int)(SDL_GetQueuedAudioSize(audio) / sizeof *samples);
    if (queued > AUDIO_TOO_FULL) {       /* after a stall: catch up at once */
        SDL_ClearQueuedAudio(audio);
        queued = 0;
    }
    double off = (double)(queued - AUDIO_TARGET) / AUDIO_TARGET;
    if (off > 1) off = 1;
    if (off < -1) off = -1;
    apu_set_sample_rate_trim(record_active() ? 1.0 : 1.0 + 0.005 * off);
}

int video_audio_queued(void) {
    return audio ? (int)(SDL_GetQueuedAudioSize(audio) / 2) : -1;
}

/* The sound off (main.c: M, or SOUND in the menu): nothing more is
   queued, what's queued is dropped, and the title says so. */
void video_set_muted(int on) {
    muted = on;
    if (audio && on) SDL_ClearQueuedAudio(audio);
    if (!window) return;
    char title[300];
    snprintf(title, sizeof title, "%s%s", window_title, muted ? " (muted)" : "");
    SDL_SetWindowTitle(window, title);
}

/* An NTSC NES makes 60.0988 frames a second (39375000/655171). */
#define FRAMES_PER_SEC_NUM 39375000ull
#define FRAMES_PER_SEC_DEN 655171ull

static void sdl_fail(const char *what) {
    fprintf(stderr, "%s: %s\n", what, SDL_GetError());
    exit(1);
}

void video_init(int scale, const char *title) {
    if (SDL_Init(SDL_INIT_VIDEO) != 0) sdl_fail("SDL_Init");
    if (gamepad_init() != 0)        /* no controllers is fine; say why */
        fprintf(stderr, "game controllers unavailable: %s\n", SDL_GetError());
    /* Resizable: the picture is drawn at the largest whole-number scale
       that fits, centred on black, so its pixels stay sharp. */
    window = SDL_CreateWindow(title, SDL_WINDOWPOS_CENTERED,
                              SDL_WINDOWPOS_CENTERED, NES_WIDTH * scale,
                              NES_HEIGHT * scale,
                              SDL_WINDOW_ALLOW_HIGHDPI | SDL_WINDOW_RESIZABLE);
    if (!window) sdl_fail("SDL_CreateWindow");
    window_title = title;
    renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED);
    if (!renderer) sdl_fail("SDL_CreateRenderer");
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "nearest");
    SDL_RenderSetLogicalSize(renderer, NES_WIDTH, NES_HEIGHT);
    SDL_RenderSetIntegerScale(renderer, SDL_TRUE);
    SDL_SetWindowMinimumSize(window, NES_WIDTH, NES_HEIGHT);
    window_scale = scale;
    texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_ARGB8888,
                                SDL_TEXTUREACCESS_STREAMING,
                                NES_WIDTH, NES_HEIGHT);
    if (!texture) sdl_fail("SDL_CreateTexture");
    atexit(SDL_Quit);

    ticks_per_frame_1x = SDL_GetPerformanceFrequency() * FRAMES_PER_SEC_DEN /
                      FRAMES_PER_SEC_NUM;
    next_frame_at = SDL_GetPerformanceCounter() + ticks_per_frame_1x;
}

static int mouse_seen;                  /* the mouse has moved over the window */

/* The window's size in whole steps of 256x240 (points), as it is now. */
static int current_scale(void) {
    int w, h;
    SDL_GetWindowSize(window, &w, &h);
    int sx = w / NES_WIDTH, sy = h / NES_HEIGHT, s = sx < sy ? sx : sy;
    return s < 1 ? 1 : s;
}

/* The biggest whole step a window fits in on its screen: the space
   left by the menu bar and the Dock (the taskbar on Windows), less the
   window's title bar and edges. */
int video_most_scale(void) {
    SDL_Rect r;
    int most = 16;
    if (window && SDL_GetDisplayUsableBounds(SDL_GetWindowDisplayIndex(window), &r) == 0) {
        int top = 0, left = 0, bottom = 0, right = 0;
        if (!video_full_screen()) SDL_GetWindowBordersSize(window, &top, &left, &bottom, &right);
        int mx = (r.w - left - right) / NES_WIDTH, my = (r.h - top - bottom) / NES_HEIGHT;
        most = mx < my ? mx : my;
    }
    return most < 1 ? 1 : most;
}

int video_full_screen(void) {
    return window && (SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN_DESKTOP) != 0;
}

void video_set_full_screen(int on) {
    if (!window || on == video_full_screen()) return;
    if (on) window_scale = current_scale();     /* the size to remember */
    SDL_SetWindowFullscreen(window, on ? SDL_WINDOW_FULLSCREEN_DESKTOP : 0);
}

void video_resize_step(int d) {
    if (!window || video_full_screen()) return;
    int s = current_scale() + d;
    int most = video_most_scale();
    if (s < 1) s = 1;
    if (s > most) s = most;
    SDL_SetWindowSize(window, NES_WIDTH * s, NES_HEIGHT * s);
}

int video_scale(void) {
    if (!window) return 0;
    if (!(SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN_DESKTOP))
        window_scale = current_scale();
    return window_scale;
}

/* The controllers' menu buttons and shoulders (gamepad.c), once a frame. */
static int pad_rewind, pad_fast;

static void pad_frame(void) {
    struct pad_wants w;
    gamepad_frame(SDL_GetTicks(), menu_is_open(), &w);
    pad_rewind = w.rewind;
    pad_fast = w.fast;
    if (w.open && !menu_is_open() && runtime_has_menu()) {
        fprintf(stderr, "controller %d: menu\n", w.open);
        menu_request();
    }
    for (int i = 0; i < w.nkeys; i++) menu_key(w.keys[i], NULL);
}

static void handle_events(void) {
    SDL_Event e;
    while (SDL_PollEvent(&e)) {
        if (e.type == SDL_QUIT) exit(0);
        if (e.type == SDL_MOUSEMOTION) mouse_seen = 1;
        gamepad_event(&e);
        /* Esc: the pause menu (PLAN-pause.md), or, in it, back to the
           game. A music file has no menu: Esc quits it. */
        if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_ESCAPE && !e.key.repeat) {
            if (menu_is_open()) menu_key(MENU_BACK, NULL);
            else if (!runtime_has_menu()) exit(0);
            else menu_request();
            continue;
        }
        if (e.type == SDL_KEYDOWN && (e.key.keysym.mod & CMD_KEY) && !e.key.repeat) {
            /* Cmd+= / Cmd+-: a whole step bigger or smaller; Cmd+F: full
               screen; Cmd+S / Cmd+L: save / load a state; Cmd+1 to
               Cmd+4: which slot. (Plain keys stay the controllers'.) */
            SDL_Keycode k = e.key.keysym.sym;
            if (k >= SDLK_1 && k <= SDLK_4) runtime_state_slot(k - SDLK_0);
            else if (k == SDLK_s) runtime_state_key(STATE_SAVE);
            else if (k == SDLK_l) runtime_state_key(STATE_LOAD);
            else if (k == SDLK_EQUALS || k == SDLK_PLUS || k == SDLK_KP_PLUS) video_resize_step(1);
            else if (k == SDLK_MINUS || k == SDLK_KP_MINUS) video_resize_step(-1);
            else if (k == SDLK_f) video_set_full_screen(!video_full_screen());
            continue;
        }
        /* While the menu is open, the keys are its own. */
        if (e.type == SDL_KEYDOWN && menu_is_open()) {
            SDL_Keycode k = e.key.keysym.sym;
            if (k == SDLK_UP) menu_key(MENU_UP, NULL);
            else if (k == SDLK_DOWN) menu_key(MENU_DOWN, NULL);
            else if (k == SDLK_LEFT) menu_key(MENU_LEFT, NULL);
            else if (k == SDLK_RIGHT) menu_key(MENU_RIGHT, NULL);
            else if (!e.key.repeat && (k == SDLK_RETURN || k == SDLK_KP_ENTER ||
                                       k == SDLK_SPACE || k == SDLK_x))
                menu_key(MENU_OK, NULL);
            else if (!e.key.repeat && k == SDLK_z) menu_key(MENU_BACK, NULL);
            continue;
        }
        if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_m && !e.key.repeat)
            runtime_sound_toggle();
        if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_r && !e.key.repeat)
            cpu_request_reset();
        if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_v && !e.key.repeat)
            runtime_record_key();
        if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_p && !e.key.repeat)
            runtime_snap_key();
        if (e.type == SDL_KEYDOWN && e.key.keysym.sym >= SDLK_0 &&
            e.key.keysym.sym <= SDLK_9 && !e.key.repeat)
            runtime_disk_key(e.key.keysym.sym - SDLK_0);
    }
    pad_frame();
}

/* Keyboard layout: controller 1 on the arrows and the keys around the
   right hand, controller 2 on WASD and the keys around the left. */
static const struct { SDL_Scancode key; uint8_t button; } keymap[2][8] = {
    { { SDL_SCANCODE_UP,     BTN_UP },     { SDL_SCANCODE_DOWN,  BTN_DOWN },
      { SDL_SCANCODE_LEFT,   BTN_LEFT },   { SDL_SCANCODE_RIGHT, BTN_RIGHT },
      { SDL_SCANCODE_X,      BTN_A },      { SDL_SCANCODE_Z,     BTN_B },
      { SDL_SCANCODE_RETURN, BTN_START },  { SDL_SCANCODE_RSHIFT, BTN_SELECT } },
    { { SDL_SCANCODE_W,      BTN_UP },     { SDL_SCANCODE_S,     BTN_DOWN },
      { SDL_SCANCODE_A,      BTN_LEFT },   { SDL_SCANCODE_D,     BTN_RIGHT },
      { SDL_SCANCODE_G,      BTN_A },      { SDL_SCANCODE_F,     BTN_B },
      { SDL_SCANCODE_E,      BTN_START },  { SDL_SCANCODE_Q,     BTN_SELECT } },
};

int video_fast_held(void) {
    /* The key left of 1. On a Mac's ISO keyboard (where it is §), SDL
       reports it as the key beside left Shift, and the other way round,
       so either counts. */
    const Uint8 *k = SDL_GetKeyboardState(NULL);
    return k[SDL_SCANCODE_GRAVE] || k[SDL_SCANCODE_NONUSBACKSLASH] || pad_fast;
}

int video_rewind_held(void) {
    return SDL_GetKeyboardState(NULL)[SDL_SCANCODE_BACKSPACE] != 0 || pad_rewind;
}

/* Keys held when the menu closed (Return is Start too): not seen by the
   game until they're let go, so closing the menu presses nothing. The
   controllers keep their own (gamepad_ignore_held). */
static uint8_t held_mask[2];
static uint8_t keyboard_buttons(int player);

void video_ignore_held(void) {
    for (int p = 0; p < 2; p++) held_mask[p] = keyboard_buttons(p);
    gamepad_ignore_held();
}

static uint8_t keyboard_buttons(int player) {
    const Uint8 *keys = SDL_GetKeyboardState(NULL);
    uint8_t b = 0;
    if (player < 2)             /* the keyboard has room for two players */
        for (int i = 0; i < 8; i++)
            if (keys[keymap[player][i].key]) b |= keymap[player][i].button;
    return b;
}

uint8_t video_buttons(int player) {
    uint8_t b = 0;
    if (player < 2) {
        b = keyboard_buttons(player);
        held_mask[player] &= b;
        b &= (uint8_t)~held_mask[player];
    }
    b |= gamepad_buttons(player);
    /* A real D-pad can't press opposite directions at once, and some
       games misbehave if they see it; cancel both instead. */
    if ((b & (BTN_UP | BTN_DOWN)) == (BTN_UP | BTN_DOWN))
        b &= ~(BTN_UP | BTN_DOWN);
    if ((b & (BTN_LEFT | BTN_RIGHT)) == (BTN_LEFT | BTN_RIGHT))
        b &= ~(BTN_LEFT | BTN_RIGHT);
    return b;
}

int video_mouse(double *x, double *y, int *inside, int *button) {
    if (!window || !mouse_seen) return 0;
    int mx, my, w, h;
    Uint32 b = SDL_GetMouseState(&mx, &my);
    SDL_GetWindowSize(window, &w, &h);
    /* Relative to the picture, not the window: in a resized window the
       picture is a whole-number scale, centred. */
    int s = current_scale(), pw = NES_WIDTH * s, ph = NES_HEIGHT * s;
    int ox = (w - pw) / 2, oy = (h - ph) / 2;
    if (pw > w) { ox = 0; pw = w; }
    if (ph > h) { oy = 0; ph = h; }
    double fx = pw > 1 ? (double)(mx - ox) / (pw - 1) : 0.5;
    double fy = ph > 1 ? (double)(my - oy) / (ph - 1) : 0.5;
    *x = fx < 0 ? 0 : fx > 1 ? 1 : fx;
    *y = fy < 0 ? 0 : fy > 1 ? 1 : fy;
    *inside = SDL_GetMouseFocus() == window;
    *button = (b & SDL_BUTTON(SDL_BUTTON_LEFT)) != 0;
    return 1;
}

void video_crosshair(void) {
    static SDL_Cursor *cross;
    if (!cross) cross = SDL_CreateSystemCursor(SDL_SYSTEM_CURSOR_CROSSHAIR);
    if (cross) SDL_SetCursor(cross);
}

/* 1, or 4 while fast-forwarding: the frames come that much sooner. */
static int speed = 1;

void video_set_speed(int n) { speed = n < 1 ? 1 : n; }

static void wait_for_next_frame(void) {
    uint64_t now = SDL_GetPerformanceCounter();
    uint64_t ticks_per_frame = ticks_per_frame_1x / (uint64_t)speed;
    if (now < next_frame_at) {
        uint64_t ms = (next_frame_at - now) * 1000 /
                      SDL_GetPerformanceFrequency();
        if (ms > 1) SDL_Delay((uint32_t)(ms - 1));
        while (SDL_GetPerformanceCounter() < next_frame_at) { /* spin */ }
        next_frame_at += ticks_per_frame;
    } else {
        /* Running behind (window dragged, machine busy): don't try to
           catch up with a burst of frames, just start counting again. */
        next_frame_at = now + ticks_per_frame;
    }
}

/* While recording: a red dot (blinking once a second) and "REC" in the
   picture's top right corner, in NES pixels, drawn over the picture in
   the window only. */
static void draw_rec(void) {
    static const char *const glyphs[3] = {     /* R E C, 3x5 */
        "###" "#.#" "##." "#.#" "#.#",
        "###" "#.." "##." "#.." "###",
        "###" "#.." "#.." "#.." "###",
    };
    static int blink;
    int x0 = NES_WIDTH - 24, y0 = 6;
    SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
    SDL_Rect back = { x0 - 2, y0 - 2, 22, 9 };
    SDL_RenderFillRect(renderer, &back);
    SDL_SetRenderDrawColor(renderer, 230, 30, 30, 255);
    if ((blink++ / 30) % 2 == 0) {
        SDL_Rect dot[] = { { x0 + 1, y0, 3, 5 }, { x0, y0 + 1, 5, 3 } };
        SDL_RenderFillRects(renderer, dot, 2);
    }
    for (int g = 0; g < 3; g++)
        for (int i = 0; i < 15; i++)
            if (glyphs[g][i] == '#') {
                SDL_Rect p = { x0 + 7 + g * 4 + i % 3, y0 + i / 3, 1, 1 };
                SDL_RenderFillRect(renderer, &p);
            }
}

/* A frame not drawn (fast-forward): the keys and the clock still. */
void video_skip(void) {
    handle_events();
    wait_for_next_frame();
}

void video_present(const uint16_t *fb) {
    void *pixels;
    int pitch;
    if (SDL_LockTexture(texture, NULL, &pixels, &pitch) == 0) {
        for (int y = 0; y < NES_HEIGHT; y++) {
            uint32_t *row = (uint32_t *)((uint8_t *)pixels + y * pitch);
            for (int x = 0; x < NES_WIDTH; x++)
                row[x] = nes_rgb[fb[y * NES_WIDTH + x] & 0x1FF];
        }
        SDL_UnlockTexture(texture);
    }
    SDL_RenderClear(renderer);
    SDL_RenderCopy(renderer, texture, NULL, NULL);
    if (record_active()) draw_rec();
    SDL_RenderPresent(renderer);
    handle_events();
    wait_for_next_frame();
}
