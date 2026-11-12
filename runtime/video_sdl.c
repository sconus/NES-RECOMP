/* nesrecomp runtime: the SDL2 window. Only this file knows about SDL, so
   headless runs (tests) never open a window. */
#define SDL_MAIN_HANDLED
#include <SDL.h>
#include <stdlib.h>
#include "apu.h"
#include "event.h"
#include "input.h"
#include "palette.h"
#include "ppu.h"
#include "video.h"

static SDL_Window *window;
static SDL_Renderer *renderer;
static SDL_Texture *texture;
static uint64_t next_frame_at;           /* performance-counter ticks */
static uint64_t ticks_per_frame;
static const char *window_title;

/* ---- sound -------------------------------------------------------------

   The APU makes 48 kHz samples; each frame they go into SDL's audio
   queue. The video keeps the beat (60.0988 frames a second), so the
   sound has to follow it: if the queue grows, the APU is producing a
   touch too fast for this Mac's sound card, and the other way round. A
   small correction to the APU's sample clock (at most 0.5%, far too
   little to hear as a pitch change) keeps the queue near AUDIO_TARGET. */
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

void video_queue_audio(const int16_t *samples, int n) {
    if (!audio) return;
    if (muted) { SDL_ClearQueuedAudio(audio); return; }
    SDL_QueueAudio(audio, samples, (Uint32)n * sizeof *samples);
    int queued = (int)(SDL_GetQueuedAudioSize(audio) / sizeof *samples);
    if (queued > AUDIO_TOO_FULL) {       /* after a stall: catch up at once */
        SDL_ClearQueuedAudio(audio);
        queued = 0;
    }
    double off = (double)(queued - AUDIO_TARGET) / AUDIO_TARGET;
    if (off > 1) off = 1;
    if (off < -1) off = -1;
    apu_set_sample_rate_trim(1.0 + 0.005 * off);
}

int video_audio_queued(void) {
    return audio ? (int)(SDL_GetQueuedAudioSize(audio) / 2) : -1;
}

static void toggle_mute(void) {
    muted = !muted;
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
    window = SDL_CreateWindow(title, SDL_WINDOWPOS_CENTERED,
                              SDL_WINDOWPOS_CENTERED, NES_WIDTH * scale,
                              NES_HEIGHT * scale, SDL_WINDOW_ALLOW_HIGHDPI);
    if (!window) sdl_fail("SDL_CreateWindow");
    window_title = title;
    renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED);
    if (!renderer) sdl_fail("SDL_CreateRenderer");
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "nearest");
    SDL_RenderSetLogicalSize(renderer, NES_WIDTH, NES_HEIGHT);
    texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_ARGB8888,
                                SDL_TEXTUREACCESS_STREAMING,
                                NES_WIDTH, NES_HEIGHT);
    if (!texture) sdl_fail("SDL_CreateTexture");
    atexit(SDL_Quit);

    ticks_per_frame = SDL_GetPerformanceFrequency() * FRAMES_PER_SEC_DEN /
                      FRAMES_PER_SEC_NUM;
    next_frame_at = SDL_GetPerformanceCounter() + ticks_per_frame;
}

static void handle_events(void) {
    SDL_Event e;
    while (SDL_PollEvent(&e)) {
        if (e.type == SDL_QUIT) exit(0);
        if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_ESCAPE) exit(0);
        if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_m && !e.key.repeat)
            toggle_mute();
        if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_r && !e.key.repeat)
            cpu_request_reset();
    }
}

/* Keyboard layout for controller 1. */
static const struct { SDL_Scancode key; uint8_t button; } keymap[] = {
    { SDL_SCANCODE_UP,     BTN_UP },     { SDL_SCANCODE_DOWN,  BTN_DOWN },
    { SDL_SCANCODE_LEFT,   BTN_LEFT },   { SDL_SCANCODE_RIGHT, BTN_RIGHT },
    { SDL_SCANCODE_X,      BTN_A },      { SDL_SCANCODE_Z,     BTN_B },
    { SDL_SCANCODE_RETURN, BTN_START },  { SDL_SCANCODE_RSHIFT, BTN_SELECT },
};

uint8_t video_buttons(void) {
    const Uint8 *keys = SDL_GetKeyboardState(NULL);
    uint8_t b = 0;
    for (size_t i = 0; i < sizeof keymap / sizeof keymap[0]; i++)
        if (keys[keymap[i].key]) b |= keymap[i].button;
    /* A real D-pad can't press opposite directions at once, and some
       games misbehave if they see it; cancel both instead. */
    if ((b & (BTN_UP | BTN_DOWN)) == (BTN_UP | BTN_DOWN))
        b &= ~(BTN_UP | BTN_DOWN);
    if ((b & (BTN_LEFT | BTN_RIGHT)) == (BTN_LEFT | BTN_RIGHT))
        b &= ~(BTN_LEFT | BTN_RIGHT);
    return b;
}

static void wait_for_next_frame(void) {
    uint64_t now = SDL_GetPerformanceCounter();
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

void video_present(const uint8_t *fb) {
    void *pixels;
    int pitch;
    if (SDL_LockTexture(texture, NULL, &pixels, &pitch) == 0) {
        for (int y = 0; y < NES_HEIGHT; y++) {
            uint32_t *row = (uint32_t *)((uint8_t *)pixels + y * pitch);
            for (int x = 0; x < NES_WIDTH; x++)
                row[x] = nes_rgb[fb[y * NES_WIDTH + x] & 0x3F];
        }
        SDL_UnlockTexture(texture);
    }
    SDL_RenderClear(renderer);
    SDL_RenderCopy(renderer, texture, NULL, NULL);
    SDL_RenderPresent(renderer);
    handle_events();
    wait_for_next_frame();
}
