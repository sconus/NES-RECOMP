/* nesrecomp app: playing a built game (see play.c). */
#ifndef APP_PLAY_H
#define APP_PLAY_H
#include <stddef.h>
#include "os.h"

/* Start the program `exe` on the ROM, with `extra` arguments (NULL-ended,
   may be NULL), its output into `log`. Returns it, or -1. */
os_proc play_start(const char *exe, const char *rom, char *const extra[], const char *log);
/* Has it ended? 0: still running. 1: ended well. -1: it stopped on
   something it couldn't run, crashed or failed; *why says what, from
   its log or its exit, for the screen. `wait` blocks until it ends. */
int play_poll(os_proc pid, const char *log, int wait, char *why, size_t n);

#endif
