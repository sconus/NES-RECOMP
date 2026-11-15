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
     - killed by a signal (a crash): which signal;
     - any other exit status: the status and its last line of output. */
#include "play.h"
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

pid_t play_start(const char *exe, const char *rom, char *const extra[], const char *log) {
    char *argv[40];
    int n = 0;
    argv[n++] = (char *)exe;
    argv[n++] = (char *)rom;
    for (int i = 0; extra && extra[i] && n < 39; i++) argv[n++] = extra[i];
    argv[n] = NULL;
    int fd = open(log, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return -1;
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_adddup2(&fa, fd, 1);
    posix_spawn_file_actions_adddup2(&fa, fd, 2);
    pid_t pid;
    int err = posix_spawn(&pid, exe, &fa, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&fa);
    close(fd);
    return err ? -1 : pid;
}

/* The line of the log starting with `want`, or the last non-empty one. */
static int log_line(const char *log, const char *want, char *out, size_t n) {
    FILE *f = fopen(log, "r");
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

int play_poll(pid_t pid, const char *log, int wait, char *why, size_t n) {
    int status;
    pid_t r;
    while ((r = waitpid(pid, &status, wait ? 0 : WNOHANG)) < 0 && errno == EINTR) {}
    if (r == 0) return 0;
    if (r < 0) { snprintf(why, n, "lost track of the game"); return -1; }
    char line[512];
    if (WIFSIGNALED(status)) {
        int sig = WTERMSIG(status);
        snprintf(why, n, "the game crashed (signal %d, %s)", sig, strsignal(sig));
        return -1;
    }
    int code = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
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
