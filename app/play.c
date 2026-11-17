/* nesrecomp app: playing a built game. The program the build made runs
   on its own (its own window, sound and keys), with the ROM as its
   argument, like `make run`; its output goes to build/NAME.game.log.
   Like `make run`, it writes the spots it had to interpret to ROM.missed
   beside the ROM when it quits, and the next build of that ROM uses
   them, so a game gets faster as it is played.

   How it ended, for the app's screen:
     - exit 0 and no "stopped:" line in its log: it ended well (the
       player quit);
     - a "stopped:" line (the runtime met something it can't run, such
       as an unknown opcode): that line;
     - killed by a signal (a crash; on Windows, an exception): which;
     - any other exit status: the status and its last line of output. */
#include "play.h"
#include <stdio.h>
#include <string.h>

os_proc play_start(const char *exe, const char *rom, char *const extra[], const char *log) {
    char *argv[40];
    int n = 0;
    argv[n++] = (char *)exe;
    argv[n++] = (char *)rom;
    for (int i = 0; extra && extra[i] && n < 39; i++) argv[n++] = extra[i];
    argv[n] = NULL;
    /* Only a program that is there (never one of that name on PATH). */
    if (!os_can_run(exe)) return -1;
    return os_start(argv, log, 0);
}

/* The line of the log starting with `want`, or the last non-empty one. */
static int log_line(const char *log, const char *want, char *out, size_t n) {
    FILE *f = fopen(log, "rb");
    char line[512];
    int found = 0;
    out[0] = 0;
    if (!f) return 0;
    while (fgets(line, sizeof line, f)) {
        line[strcspn(line, "\r\n")] = 0;
        if (!line[0]) continue;
        if (want) {
            if (!strncmp(line, want, strlen(want))) {
                snprintf(out, n, "%s", line + strlen(want));
                found = 1;
                break;
            }
        } else {
            snprintf(out, n, "%s", line);
            found = 1;
        }
    }
    fclose(f);
    return found;
}

int play_poll(os_proc pid, const char *log, int wait, char *why, size_t n) {
    int code;
    char crash[256];
    if (!os_poll(pid, wait, &code, crash, sizeof crash)) return 0;
    char line[512];
    if (code < 0) {
        if (!strcmp(crash, "lost track of it")) snprintf(why, n, "lost track of the game");
        else snprintf(why, n, "the game crashed (%s)", crash);
        return -1;
    }
    if (log_line(log, "stopped: ", line, sizeof line)) {
        snprintf(why, n, "%s", line);
        return -1;
    }
    if (code != 0) {
        log_line(log, NULL, line, sizeof line);
        snprintf(why, n, "the game ended with status %d%s%s", code, line[0] ? ": " : "", line);
        return -1;
    }
    return 1;
}
