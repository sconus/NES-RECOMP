/* nesrecomp app: building a dropped ROM (see build.c). */
#ifndef APP_BUILD_H
#define APP_BUILD_H
#include <limits.h>
#include <stdatomic.h>
#include <stddef.h>

/* The app's version: in the bundle's Info.plist, and in each build's
   record, so a new version builds old games again. */
#define APP_VERSION "2.1"

enum { ST_CHECK, ST_RECOMP, ST_GAME, ST_RUNTIME, ST_LINK, ST_COUNT };
enum { B_RUNNING, B_DONE, B_FAILED };

struct build {
    char rom[PATH_MAX];             /* the file dropped */
    char name[256];                 /* its name, for files and the screen */
    char out[PATH_MAX];             /* the program built */
    char log[PATH_MAX];             /* everything the tools printed */
    char files_at[PATH_MAX];        /* FILES_AT.missed, FILES_AT.sav: the ROM's
                                       path, or the build folder's NAME */
    char error[512];                /* why it failed, for the screen */
    atomic_int stage;               /* ST_*, the stage running now */
    atomic_int state;               /* B_* */
    atomic_int rt_done, rt_total;   /* runtime files compiled, to compile */
    double stage_start;             /* when the stage began (seconds) */
    double estimate;                /* how long it might take (seconds) */
    int verbose;                    /* print each stage (--build) */
    int no_compiler;                /* it failed for want of Apple's C compiler */
    long translated;                /* instructions the recompiler translated
                                       (kept in NAME.translated), or -1 */
};

/* The stage's name, as the screen shows it. */
const char *build_stage_name(int stage);
/* Is it a file the recompiler takes (an iNES, NSF or FDS image)? If
   not, why, in a few words for the screen. */
int build_check_file(const char *path, char *why, size_t n);
/* Where builds go: set once before building. */
void build_setup(const char *build_dir);
/* Find what builds need, from the app's own place (PLAN-standalone.md
   steps 1, 3 and 4):
   - its own SDL2, the library and the folder holding SDL2/SDL.h. Games
     compile against these headers, and link a copy of the library kept
     next to them. In a bundle, Contents/Frameworks/libSDL2.dylib and
     Contents/Resources/sdl2/include; otherwise sdl2/lib and
     sdl2/include beside the program;
   - the runtime's sources: Contents/Resources/runtime, or ../runtime
     beside the program; root/runtime instead when root is given
     ($NESRECOMP_ROOT, for working on the project).
   Returns 0 if SDL2 isn't there. */
int build_find_parts(const char *exe, const char *root);
const char *build_runtime(void);
const char *build_sdl_lib(void);
/* The recompiler, nesrecomp-recomp beside the app's program (found by
   build_find_parts too). */
const char *build_recompiler(void);
/* Is Apple's C compiler there? (xcode-select -p, and clang in the
   folder it names.) If so, where clang is, in where. */
int build_have_compiler(char *where, size_t n);
/* The xcode-select to ask (and to run --install): /usr/bin/xcode-select,
   or $NESRECOMP_XCODE_SELECT for the checks. */
const char *build_xcode_select(void);
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
