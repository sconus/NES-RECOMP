/* nesrecomp runtime: save states (state.h, PLAN-savestates.md steps 1-2).

   The held state is one block of memory: for each part, its name (a
   fixed 24-byte field), its size (4 bytes) and its bytes. Loading goes
   through the parts twice: once only checking that every name and size
   matches what this program has, and only then copying them in, so a
   state that doesn't fit is refused whole. A state file is a header and
   then that block, which holds no addresses (state_struct), so it loads
   in a later run. */
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
    const char *bad;            /* the first part that doesn't fit (CHECK),
                                   or that can't be saved (SAVE) */
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

/* ---- pointers: "which buffer, which offset" ---- */

static struct { const uint8_t *base; size_t size; } region[REGION_COUNT];

void state_region(int id, const void *base, size_t size) {
    region[id].base = base;
    region[id].size = size;
}

/* A pointer as a buffer's number and an offset in it (0, 0: NULL).
   Returns 0 if it points into none of the buffers. */
static int encode(const uint8_t *v, uint32_t out[2]) {
    out[0] = out[1] = 0;
    if (!v) return 1;
    for (int r = 1; r < REGION_COUNT; r++)
        if (region[r].base && v >= region[r].base && v < region[r].base + region[r].size) {
            out[0] = (uint32_t)r;
            out[1] = (uint32_t)(v - region[r].base);
            return 1;
        }
    return 0;
}

/* Back again; 0 if the buffer doesn't exist here or is too small. */
static int decode(const uint32_t in[2], const uint8_t **v) {
    if (in[0] == 0) { *v = NULL; return in[1] == 0; }
    if (in[0] >= REGION_COUNT || !region[in[0]].base || in[1] >= region[in[0]].size)
        return 0;
    *v = region[in[0]].base + in[1];
    return 1;
}

#define MAX_PTRS 32

/* The struct goes in as one part with every pointer field zeroed, then
   its STATE_DATA pointers as a second part, "<name>.pointers": a
   buffer's number and an offset for each. */
void state_struct(struct state_io *s, const char *name, void *p, size_t n,
                  const struct state_ptr *ptrs, int count) {
    char pname[NAME_BYTES + 16];
    snprintf(pname, sizeof pname, "%s.pointers", name);
    uint32_t code[MAX_PTRS][2];
    int data = 0;
    if (count > MAX_PTRS) { fprintf(stderr, "state: too many pointers in %s\n", name); exit(1); }
    if (s->mode == SAVE) {
        uint8_t *copy = malloc(n);
        if (!copy) { fprintf(stderr, "out of memory saving a state\n"); exit(1); }
        memcpy(copy, p, n);
        for (int i = 0; i < count; i++) {
            if (ptrs[i].kind == STATE_DATA) {
                const uint8_t *v;
                memcpy(&v, (uint8_t *)p + ptrs[i].at, sizeof v);
                if (!encode(v, code[data++]) && !s->bad) s->bad = name;
            }
            memset(copy + ptrs[i].at, 0, ptrs[i].size);
        }
        state_part(s, name, copy, n);
        free(copy);
        state_part(s, pname, code, sizeof code[0] * (size_t)data);
        return;
    }
    for (int i = 0; i < count; i++) data += ptrs[i].kind == STATE_DATA;
    /* Reading: keep this run's own pointers through the copy. */
    uint8_t keep[MAX_PTRS][16];
    for (int i = 0; i < count; i++) memcpy(keep[i], (uint8_t *)p + ptrs[i].at, ptrs[i].size);
    state_part(s, name, p, n);
    for (int i = 0; i < count; i++) memcpy((uint8_t *)p + ptrs[i].at, keep[i], ptrs[i].size);
    size_t got;
    const uint8_t *rec = next(s, pname, sizeof code[0] * (size_t)data, &got);
    if (!rec) return;
    if (got != sizeof code[0] * (size_t)data) { s->bad = pname; return; }
    memcpy(code, rec, got);
    for (int i = 0, d = 0; i < count; i++) {
        if (ptrs[i].kind != STATE_DATA) continue;
        const uint8_t *v;
        if (!decode(code[d++], &v)) { s->bad = pname; return; }
        if (s->mode == LOAD) memcpy((uint8_t *)p + ptrs[i].at, &v, sizeof v);
    }
}

/* The cartridge: the header's facts and the current mirroring (struct
   cart), and its RAM: $6000 RAM (with an FDS, its 32 KB), CHR RAM. ROM
   never changes and isn't saved. */
static void cart_state(struct state_io *s) {
    static const struct state_ptr ptrs[] = {
        STATE_PTR(struct cart, prg, STATE_RUN),
        STATE_PTR(struct cart, chr, STATE_RUN),
        STATE_PTR(struct cart, prg_ram, STATE_RUN),
    };
    state_struct(s, "cart", &cart, sizeof cart, ptrs, 3);
    state_part(s, "cart.prg_ram", cart.prg_ram, cart.prg_ram_alloc);
    if (cart.chr_is_ram) state_part(s, "cart.chr_ram", cart.chr, cart.chr_size);
}

/* Every part, always in this order. */
static void all_parts(struct state_io *s) {
    state_region(REGION_PRG, cart.prg, cart.prg_size);
    state_region(REGION_CHR, cart.chr, cart.chr_size);
    state_region(REGION_PRG_RAM, cart.prg_ram, cart.prg_ram_alloc);
    state_region(REGION_NAMETABLES, ppu.nametables, sizeof ppu.nametables);
    cpu_state(s);
    event_state(s);
    cart_state(s);
    static const struct state_ptr ppu_ptrs[] = { STATE_PTR(struct ppu, fetch_chr, STATE_DATA) };
    state_struct(s, "ppu", &ppu, sizeof ppu, ppu_ptrs, 1);
    apu_state(s);
    mapper_state(s);
    input_state(s);
    if (cart.mapper == MAPPER_FDS) fds_state(s);
}

/* Into the held block. Returns 0 (keeping the block as it was) if a
   part can't be saved: a pointer into none of the known buffers. */
static int save(void) {
    struct state_io s = { SAVE, NULL, 0, 0, 0, NULL };
    all_parts(&s);
    if (s.bad) {
        fprintf(stderr, "can't save the state: part \"%s\" points outside the console\n", s.bad);
        free(s.buf);
        return 0;
    }
    free(held);
    held = s.buf;
    held_len = s.len;
    return 1;
}

/* From a block: check every part, and only then copy them in. */
static int load_block(uint8_t *block, size_t len) {
    struct state_io s = { CHECK, block, len, len, 0, NULL };
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

/* ---- files ---- */

#define MAGIC "NESRECOMP STATE\n"         /* 16 bytes, no terminator */
#define HEADER_BYTES 40

static const char *file_path, *file_label = "STATE";
static uint64_t game;

void state_use_file(const char *path, const char *label) {
    file_path = path;
    file_label = label;
}

void state_set_game(uint64_t checksum) { game = checksum; }

static void put32(uint8_t *p, uint32_t v) { for (int i = 0; i < 4; i++) p[i] = (uint8_t)(v >> 8 * i); }
static void put64(uint8_t *p, uint64_t v) { for (int i = 0; i < 8; i++) p[i] = (uint8_t)(v >> 8 * i); }
static uint32_t get32(const uint8_t *p) { uint32_t v = 0; for (int i = 3; i >= 0; i--) v = v << 8 | p[i]; return v; }
static uint64_t get64(const uint8_t *p) { uint64_t v = 0; for (int i = 7; i >= 0; i--) v = v << 8 | p[i]; return v; }

/* The header: the magic word, the version, 4 bytes kept 0, the game's
   checksum, the state's size; little-endian. */
static int write_file(void) {
    uint8_t h[HEADER_BYTES] = { 0 };
    memcpy(h, MAGIC, 16);
    put32(h + 16, STATE_VERSION);
    put64(h + 24, game);
    put64(h + 32, held_len);
    /* Written beside, then put in place, so a failed write never
       leaves half a state where a good one was. */
    char tmp[1100];
    snprintf(tmp, sizeof tmp, "%s.new", file_path);
    FILE *f = fopen(tmp, "wb");
    if (!f) return 0;
    int ok = fwrite(h, 1, sizeof h, f) == sizeof h &&
             fwrite(held, 1, held_len, f) == held_len;
    ok = (fclose(f) == 0) && ok;
    if (ok) {
        remove(file_path);                  /* Windows' rename won't replace */
        ok = rename(tmp, file_path) == 0;
    }
    if (!ok) remove(tmp);
    return ok;
}

enum { READ_OK, READ_NONE, READ_NOT_STATE, READ_OLD, READ_OTHER_GAME };

/* The file's state, checked against this game and this format. */
static int read_file(uint8_t **block, size_t *len) {
    FILE *f = fopen(file_path, "rb");
    if (!f) return READ_NONE;
    uint8_t h[HEADER_BYTES];
    int r = READ_NOT_STATE;
    *block = NULL;
    if (fread(h, 1, sizeof h, f) == sizeof h && !memcmp(h, MAGIC, 16)) {
        uint64_t n = get64(h + 32);
        if (get32(h + 16) != STATE_VERSION) r = READ_OLD;
        else if (get64(h + 24) != game) r = READ_OTHER_GAME;
        else if (n < (64u << 20) && (*block = malloc(n ? (size_t)n : 1)) &&
                 fread(*block, 1, (size_t)n, f) == n && fgetc(f) == EOF) {
            *len = (size_t)n;
            r = READ_OK;
        }
    }
    fclose(f);
    if (r != READ_OK) { free(*block); *block = NULL; }
    return r;
}

static void say(const char *fmt) {
    char text[64];
    snprintf(text, sizeof text, fmt, file_label);
    runtime_state_message(text);
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
        if (!save()) { say("%s NOT SAVED"); return 1; }
        if (file_path && !write_file()) {
            fprintf(stderr, "can't write %s\n", file_path);
            say("%s NOT SAVED");
            return 1;
        }
        runtime_state_saved();
        say("%s SAVED");
        return 1;
    }
    if (!file_path) {
        if (!held) say("NO %s");
        else if (load_block(held, held_len)) { runtime_state_loaded(); say("%s LOADED"); }
        else say("%s DOESN'T FIT");
        return 1;
    }
    uint8_t *block;
    size_t len = 0;
    switch (read_file(&block, &len)) {
    case READ_NONE:       say("%s IS EMPTY"); break;
    case READ_NOT_STATE:  say("%s ISN'T A STATE"); break;
    case READ_OLD:        say("%s IS AN OLDER FORMAT"); break;
    case READ_OTHER_GAME: say("%s IS ANOTHER GAME'S"); break;
    default:
        if (load_block(block, len)) {
            free(held);                     /* it's the state held now */
            held = block;
            held_len = len;
            runtime_state_loaded();
            say("%s LOADED");
        } else {
            free(block);
            say("%s DOESN'T FIT");
        }
    }
    return 1;
}
