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

/* The parts, file by file. */
void cpu_state(struct state_io *s);         /* main.c: CPU, RAM, script */
void event_state(struct state_io *s);       /* event.c */
void apu_state(struct state_io *s);         /* apu.c */
void mapper_state(struct state_io *s);      /* mapper.c */
void input_state(struct state_io *s);       /* input.c */
void fds_state(struct state_io *s);         /* fds.c */

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

/* main.c: told what happened ("STATE SAVED", ...), to show it. */
void runtime_state_message(const char *text);
/* main.c: right after a save. */
void runtime_state_saved(void);
/* main.c: after a load, before the game carries on (empties the sound
   queue, so old sound doesn't play over the new). */
void runtime_state_loaded(void);

#endif
