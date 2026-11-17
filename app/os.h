/* nesrecomp app: what the Mac and Windows do differently (PLAN-windows.md
   step 4), behind the same few functions. app/os_mac.c has the Mac's way
   (and any Unix's), app/os_win.c Windows's; the rest of the app is the
   same on both.

   Paths: on Windows, '/' works between folders as '\' does, so the app
   joins paths with '/' on both; what Windows hands back (its own
   program's path, a dropped file's) has '\', which os_last_sep finds. */
#ifndef APP_OS_H
#define APP_OS_H
#include <stddef.h>
#include <stdint.h>

/* A program started (os_start), or -1. */
typedef intptr_t os_proc;

/* Start argv[0] (a path, or a bare name looked for on PATH) with argv,
   its output (and errors) into the file log: added to its end with
   `append`, or replacing it. No shell: arguments with spaces stay one.
   Returns -1 if it couldn't start. */
os_proc os_start(char *const argv[], const char *log, int append);
/* Has it ended? 0: still running (only without `wait`). 1: ended, its
   exit status in *code; if it crashed, *code is -1 and crash says how
   ("signal 11, Segmentation fault: 11", or on Windows "exception
   0xC0000005, an access violation"). The process is then forgotten. */
int os_poll(os_proc p, int wait, int *code, char *crash, size_t n);
/* Start it, and wait: its exit status, or -1 (couldn't start, crashed). */
int os_run(char *const argv[], const char *log);

/* Run fn(arg) on a thread of its own. Returns 0, or -1. */
int os_thread(void (*fn)(void *), void *arg);
/* Seconds, from some fixed time (for timing stages). */
double os_now(void);

/* The running program's own full path. Returns 0, or -1. */
int os_exe_path(char *out, size_t n);
/* path made full, with "." and ".." and links resolved. 0, or -1 if
   it isn't there. */
int os_real_path(const char *path, char *out, size_t n);
/* The folder the app keeps its builds in by default:
   ~/Library/Application Support/NES RECOMP on the Mac,
   %LOCALAPPDATA%\NES RECOMP on Windows. */
void os_app_dir(char *out, size_t n);
/* The last character between folders in path ('/', or '\' too on
   Windows), or NULL. */
const char *os_last_sep(const char *path);
/* What a program's name ends with: "" on the Mac, ".exe" on Windows. */
const char *os_exe_ext(void);

int os_exists(const char *path);
/* Can it be run (a program), or written in (a folder)? */
int os_can_run(const char *path);
int os_can_write(const char *dir);
/* Its time (seconds, to the system's finest), or -1; its size, or 0. */
double os_mtime(const char *path);
long os_size(const char *path);
void os_mkdir(const char *path);
/* Make a folder and those above it. */
void os_make_dirs(const char *path);
void os_remove(const char *path);
/* Copy a file, keeping its time, through a temporary file, so the copy
   is whole or not there. 0, or -1. */
int os_copy(const char *from, const char *to);
/* Call each(name, arg) for each file in dir. 0, or -1 if no such folder. */
int os_list(const char *dir, void (*each)(const char *name, void *arg), void *arg);

/* The system's own "choose a file" box; waits until it's closed.
   Returns 1 with the file's path in out, or 0 if cancelled. */
int os_pick_file(char *out, size_t n);
/* Open a link in the browser (or $NESRECOMP_OPEN LINK, a stand-in for
   the checks). Returns the opener's exit status (0 when it went), or -1. */
int os_open_url(const char *url);

#endif
