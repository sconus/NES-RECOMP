/* nesrecomp runtime: the Mac's way and Windows's (see sys.h). */
#include "sys.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <direct.h>
#include <io.h>
#include <process.h>

void sys_media_dir(char *out, size_t n) {
    const char *home = getenv("USERPROFILE");
    snprintf(out, n, "%s\\Videos\\NES RECOMP", home && *home ? home : ".");
}

char sys_sep(void) { return '\\'; }

void sys_make_dirs(const char *path) {
    char part[1024];
    snprintf(part, sizeof part, "%s", path);
    /* After a drive ("C:\"), then at each '\' or '/'. */
    for (char *p = part + 1; *p; p++)
        if ((*p == '\\' || *p == '/') && p[-1] != ':') {
            char c = *p;
            *p = 0;
            _mkdir(part);
            *p = c;
        }
    _mkdir(part);
}

int sys_exists(const char *path) { return _access(path, 0) == 0; }

static void (*stop_handler)(int);

/* Windows says "quit" to a console program through this, on another
   thread; returning TRUE says it's being handled (the runtime ends at
   the frame's end, well within the few seconds Windows gives). */
static BOOL WINAPI on_console(DWORD what) {
    if (!stop_handler) return FALSE;
    stop_handler(what == CTRL_C_EVENT ? 2 : 15);
    if (what == CTRL_CLOSE_EVENT || what == CTRL_LOGOFF_EVENT || what == CTRL_SHUTDOWN_EVENT)
        Sleep(5000);                    /* time to finish the recording */
    return TRUE;
}

void sys_on_stop(void (*handler)(int)) {
    stop_handler = handler;
    SetConsoleCtrlHandler(on_console, TRUE);
}

void sys_quit_now(int status) { _exit(status); }

#else

#include <pwd.h>
#include <signal.h>
#include <sys/stat.h>
#include <unistd.h>

void sys_media_dir(char *out, size_t n) {
    const char *home = getenv("HOME");
    struct passwd *pw = (!home || !*home) ? getpwuid(getuid()) : NULL;
    if (pw) home = pw->pw_dir;
    snprintf(out, n, "%s/Movies/NES RECOMP", home ? home : "/tmp");
}

char sys_sep(void) { return '/'; }

void sys_make_dirs(const char *path) {
    char part[1024];
    snprintf(part, sizeof part, "%s", path);
    for (char *p = part + 1; *p; p++)
        if (*p == '/') { *p = 0; mkdir(part, 0755); *p = '/'; }
    mkdir(part, 0755);
}

int sys_exists(const char *path) { return access(path, F_OK) == 0; }

void sys_on_stop(void (*handler)(int)) {
    signal(SIGINT, handler);
    signal(SIGTERM, handler);
    signal(SIGHUP, handler);
}

void sys_quit_now(int status) { _exit(status); }

#endif
