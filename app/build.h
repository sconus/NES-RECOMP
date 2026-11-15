/* nesrecomp app: building a dropped ROM (see build.c). */
#ifndef APP_BUILD_H
#define APP_BUILD_H
#include <limits.h>
#include <stdatomic.h>
#include <stddef.h>

enum { ST_CHECK, ST_RECOMP, ST_GAME, ST_RUNTIME, ST_LINK, ST_COUNT };
enum { B_RUNNING, B_DONE, B_FAILED };

struct build {
    char rom[PATH_MAX];             /* the file dropped */
    char name[256];                 /* its name, for files and the screen */
    char out[PATH_MAX];             /* the program built */
    char log[PATH_MAX];             /* everything the tools printed */
    char error[512];                /* why it failed, for the screen */
    atomic_int stage;               /* ST_*, the stage running now */
    atomic_int state;               /* B_* */
    atomic_int rt_done, rt_total;   /* runtime files compiled, to compile */
    double stage_start;             /* when the stage began (seconds) */
    double estimate;                /* how long it might take (seconds) */
    int verbose;                    /* print each stage (--build) */
};

/* The stage's name, as the screen shows it. */
const char *build_stage_name(int stage);
/* Is it a file the recompiler takes (an iNES, NSF or FDS image)? If
   not, why, in a few words for the screen. */
int build_check_file(const char *path, char *why, size_t n);
/* Where the project is (the recompiler, the runtime) and where builds
   go: set once before building. */
void build_setup(const char *root, const char *build_dir);
/* Build it, now (returns 0 when done), or on a thread of its own. */
int build_run(struct build *b, const char *rom);
void build_start(struct build *b, const char *rom);
/* How far it has got, 0 to 1, for the loading bar. Real counts where
   there are some (the runtime's files), otherwise the time spent against
   an estimate, approaching the stage's end but never reaching it before
   the stage really ends. */
double build_progress(struct build *b, double now);
double build_now(void);
/* The short name for a ROM file: its base name without the extension,
   anything but letters, digits, '-' and '_' made '_'. */
void build_name(const char *path, char *out, size_t n);

#endif
