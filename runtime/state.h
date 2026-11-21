/* nesrecomp runtime: save states (PLAN-savestates.md).

   A state is everything about the console that changes while a game
   runs, copied into one block of memory as named parts: each part is a
   variable (or a piece of one) with its name and size, so a part that
   is missing, extra or a different size shows up by name instead of
   loading half a game.

   Saving and loading only ever happen in runtime_event (event.c), at an
   instruction boundary, where the whole 6502 is in global variables and
   the next thing the CPU does is look up `pc`. A key press only asks
   for it (state_request); the work happens at the next boundary. */
#ifndef NESRECOMP_STATE_H
#define NESRECOMP_STATE_H
#include <stddef.h>
#include <stdint.h>

struct state_io;

/* One part of the state: `n` bytes at `p`, called `name`. Each file
   that owns state lists its parts with these, in the same order every
   time (see the *_state functions below). */
void state_part(struct state_io *s, const char *name, void *p, size_t n);
/* A part whose size changes while running (the FDS drive's bit stream):
   `n` bytes now, at most `room`. A load accepts any saved size up to
   `room` and sets *loaded_n to it. */
void state_part_sized(struct state_io *s, const char *name, void *p, size_t n,
                      size_t room, size_t *loaded_n);
/* Whether this pass reads a state in (checking or loading), not out. */
int state_reading(const struct state_io *s);

/* A struct that holds pointers (step 2). A pointer is an address in
   this run's memory, which means nothing in another run, so a state
   never holds one. Each pointer field is listed (STATE_PTR) as one of:
   - STATE_DATA: it points into the console's memory (a ROM or RAM bank);
     the state holds "which buffer, which offset" instead, and a load
     points it at the same place in this run's buffer;
   - STATE_RUN: it belongs to this run (a board's functions, its name,
     the cartridge's own buffers): the state holds nothing for it, and a
     load leaves this run's value as it is. */
enum { STATE_DATA, STATE_RUN };
struct state_ptr { size_t at, size; int kind; };
#define STATE_PTR(type, field, kind) \
    { offsetof(type, field), sizeof(((type *)0)->field), kind }
void state_struct(struct state_io *s, const char *name, void *p, size_t n,
                  const struct state_ptr *ptrs, int count);
/* The buffers a STATE_DATA pointer may point into, by number (the number
   is what a state holds, so they never change). The cartridge's and
   the PPU's are known to state.c; mapper_init gives the boards' own. */
enum { REGION_NONE, REGION_PRG, REGION_CHR, REGION_PRG_RAM, REGION_NAMETABLES,
       REGION_MMC5_RAM, REGION_TQROM_RAM, REGION_COUNT };
void state_region(int id, const void *base, size_t size);

/* The parts, file by file. */
void cpu_state(struct state_io *s);         /* main.c: CPU, RAM, script */
void event_state(struct state_io *s);       /* event.c */
void apu_state(struct state_io *s);         /* apu.c */
void mapper_state(struct state_io *s);      /* mapper.c */
void input_state(struct state_io *s);       /* input.c */
void fds_state(struct state_io *s);         /* fds.c */

/* States on disk (step 2). A state file is a header (a magic word, the
   format's version, a checksum of the game's file, the state's size)
   and then the state. With a file in use, a save also writes it, and a
   load reads it (refusing, whole, a state from another game, an older
   format, or one that doesn't fit); with none, both use memory only
   (the state test). `label` names it in the messages ("STATE 2"). */
#define STATE_VERSION 1
void state_use_file(const char *path, const char *label);
/* The checksum of the game's file (main.c, at start). */
void state_set_game(uint64_t checksum);

/* Ask for a save or a load at the next instruction boundary. */
enum { STATE_SAVE = 1, STATE_LOAD = 2 };
void state_request(int what);
/* The same, from CPU cycle `when` on (the state test saves mid-frame). */
void state_request_at(int what, uint64_t when);
uint64_t state_wanted_at(void);
/* From runtime_event: do what was asked, if anything. Returns 1 when
   something was asked (a save or a load was done or refused). */
int state_service(void);
/* Whether a request is still waiting. */
int state_wanted(void);
/* Whether a state is held. */
int state_held(void);
/* How big the held state is, in bytes (0: none). */
size_t state_size(void);

/* Rewind (step 3): a state every frame, for the last `frames` frames,
   in at most `max_bytes` of changes (see state.c). Off until set up. */
void state_rewind_setup(int frames, size_t max_bytes);
int state_rewind_on(void);
/* From frame_done: at the next instruction boundary, keep this frame's
   state (STATE_KEEP), or go one frame back (STATE_BACK). */
enum { STATE_KEEP = 3, STATE_BACK = 4 };
void state_rewind_request(int what);
/* How many frames are kept (0: none), and in how many bytes. */
int state_rewind_frames(void);
size_t state_rewind_bytes(void);
/* main.c: right after a step back was loaded. */
void runtime_state_rewound(void);

/* main.c: told what happened ("STATE SAVED", ...), to show it. */
void runtime_state_message(const char *text);
/* main.c: right after a save. */
void runtime_state_saved(void);
/* main.c: after a load, before the game carries on (empties the sound
   queue, so old sound doesn't play over the new). */
void runtime_state_loaded(void);

#endif
