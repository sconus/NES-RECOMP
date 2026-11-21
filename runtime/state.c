/* nesrecomp runtime: save states (state.h, PLAN-savestates.md step 1).

   The held state is one block of memory: for each part, its name (a
   fixed 24-byte field), its size (4 bytes) and its bytes. Loading goes
   through the parts twice: once only checking that every name and size
   matches what this program has, and only then copying them in, so a
   state that doesn't fit is refused whole. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "state.h"
#include "rt.h"
#include "event.h"
#include "cart.h"
#include "fds.h"
#include "ppu.h"

#define NAME_BYTES 24

enum { SAVE, CHECK, LOAD };

struct state_io {
    int mode;
    uint8_t *buf;
    size_t len, room;           /* SAVE: written so far; else: the state's size */
    size_t at;                  /* CHECK, LOAD: the next record */
    const char *bad;            /* CHECK: the first part that doesn't fit */
};

static uint8_t *held;
static size_t held_len;

int state_reading(const struct state_io *s) { return s->mode != SAVE; }

static void put(struct state_io *s, const void *p, size_t n) {
    if (s->len + n > s->room) {
        s->room = (s->len + n) * 2;
        s->buf = realloc(s->buf, s->room);
        if (!s->buf) { fprintf(stderr, "out of memory saving a state\n"); exit(1); }
    }
    memcpy(s->buf + s->len, p, n);
    s->len += n;
}

/* The next record when reading: its bytes, or NULL if it isn't `name`
   or is bigger than `room` (its size in *n). */
static const uint8_t *next(struct state_io *s, const char *name, size_t room, size_t *n) {
    uint32_t size;
    if (s->bad) return NULL;
    if (s->at + NAME_BYTES + 4 > s->len) { s->bad = name; return NULL; }
    const uint8_t *r = s->buf + s->at;
    memcpy(&size, r + NAME_BYTES, 4);
    if (strncmp((const char *)r, name, NAME_BYTES) || size > room ||
        s->at + NAME_BYTES + 4 + size > s->len) {
        s->bad = name;
        return NULL;
    }
    s->at += NAME_BYTES + 4 + size;
    *n = size;
    return r + NAME_BYTES + 4;
}

void state_part_sized(struct state_io *s, const char *name, void *p, size_t n,
                      size_t room, size_t *loaded_n) {
    if (s->mode == SAVE) {
        char field[NAME_BYTES] = { 0 };
        strncpy(field, name, NAME_BYTES - 1);
        uint32_t size = (uint32_t)n;
        put(s, field, NAME_BYTES);
        put(s, &size, 4);
        put(s, p, n);
        return;
    }
    size_t got;
    const uint8_t *data = next(s, name, room, &got);
    if (!data) return;
    if (loaded_n == NULL && got != n) { s->bad = name; return; }
    if (s->mode == LOAD) {
        memcpy(p, data, got);
        if (loaded_n) *loaded_n = got;
    }
}

void state_part(struct state_io *s, const char *name, void *p, size_t n) {
    state_part_sized(s, name, p, n, n, NULL);
}

/* The cartridge: the header's facts and the current mirroring (struct
   cart), and its RAM: $6000 RAM (with an FDS, its 32 KB), CHR RAM. ROM
   never changes and isn't saved. */
static void cart_state(struct state_io *s) {
    state_part(s, "cart", &cart, sizeof cart);
    state_part(s, "cart.prg_ram", cart.prg_ram, cart.prg_ram_alloc);
    if (cart.chr_is_ram) state_part(s, "cart.chr_ram", cart.chr, cart.chr_size);
}

/* Every part, always in this order. */
static void all_parts(struct state_io *s) {
    cpu_state(s);
    event_state(s);
    cart_state(s);
    state_part(s, "ppu", &ppu, sizeof ppu);
    apu_state(s);
    mapper_state(s);
    input_state(s);
    if (cart.mapper == MAPPER_FDS) fds_state(s);
}

static void save(void) {
    struct state_io s = { SAVE, held, 0, held ? held_len : 0, 0, NULL };
    /* Keep the old block's memory: the new state is the same size. */
    s.room = held ? held_len : 0;
    s.buf = held;
    all_parts(&s);
    held = s.buf;
    held_len = s.len;
}

static int load(void) {
    struct state_io s = { CHECK, held, held_len, held_len, 0, NULL };
    all_parts(&s);
    if (!s.bad && s.at != s.len) s.bad = "(more parts than this program has)";
    if (s.bad) {
        fprintf(stderr, "can't load the state: part \"%s\" doesn't fit\n", s.bad);
        return 0;
    }
    s.mode = LOAD;
    s.at = 0;
    all_parts(&s);
    return 1;
}

/* ---- the safe point ---- */

static int wanted;
static uint64_t wanted_at;

void state_request_at(int what, uint64_t when) {
    wanted = what;
    wanted_at = when;
    schedule_event(when);           /* at the first instruction boundary from then */
}

void state_request(int what) { state_request_at(what, cycles); }

int state_wanted(void) { return wanted != 0; }
uint64_t state_wanted_at(void) { return wanted_at; }
int state_held(void) { return held != NULL; }
size_t state_size(void) { return held ? held_len : 0; }

int state_service(void) {
    int what = wanted;
    if (!what || cycles < wanted_at) return 0;
    wanted = 0;
    if (what == STATE_SAVE) {
        save();
        runtime_state_saved();
        runtime_state_message("STATE SAVED");
    } else if (!held) {
        runtime_state_message("NO STATE");
    } else if (load()) {
        runtime_state_loaded();
        runtime_state_message("STATE LOADED");
    } else {
        runtime_state_message("STATE DOESN'T FIT");
    }
    return 1;
}
