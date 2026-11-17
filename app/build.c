/* nesrecomp app: building a dropped ROM, as `make game` does, in stages
   the loading bar can follow:
     1  checking the file   its first bytes: iNES, NSF or FDS
     2  recompiling         nesrecomp-recomp ROM -o build/NAME.c, the
                            recompiler in C beside the app's program
                            (with ROM.missed when there is one)
     3  compiling the game  cc -c build/NAME.c
     4  the runtime         cc -c runtime/X.c (and X.m) for each file, kept in
                            build/app-rt/ and only compiled again when a
                            runtime source or header is newer
     5  linking             cc -o build/NAME ...
   SDL2 is the app's own copy, not Homebrew's (PLAN-standalone.md step
   1): games compile against its headers and link build/lib/libSDL2.dylib,
   a copy of the app's library made before linking, which they find
   beside them (their rpath is @executable_path/lib). So a game still
   runs after the app is moved or replaced.
   Everything a build needs comes with the app (PLAN-standalone.md step
   4): the runtime's sources (Contents/Resources/runtime in the bundle,
   ../runtime beside the program otherwise, or $NESRECOMP_ROOT/runtime),
   SDL2 and the recompiler. "build/" above is the build folder app.c
   chooses: ~/Library/Application Support/NES RECOMP unless told.
   ROM.missed (and the game's ROM.sav) are kept beside the ROM. If the
   ROM's folder can't be written, they are kept in the build folder as
   NAME.missed and NAME.sav instead (the game is told with --files-at).
   A build that would make the same program again is skipped: build/
   NAME.stamp records what the program was built from (the app's
   version, the ROM's path, size and time, its .missed file's, the
   recompiler's time, the newest runtime file's, SDL's header's), and
   when all match and the program is there, the build is "up to date"
   and done at once.
   Apple's C compiler (the Command Line Tools, or Xcode) is looked for
   before compiling, and never run blindly: on a Mac without it,
   /usr/bin/cc is a stand-in that pops up Apple's install box in the
   middle of a build. `xcode-select -p` says where the tools would be,
   and clang must be there. If not, the build stops before stage 2 with
   b->no_compiler set, and the window says what to do (app.c). A game
   already built and up to date still plays without it.
   The tools run with no shell (os_start, so paths with spaces work),
   their output appended to build/NAME.log. A tool that fails stops the
   build; its message (the recompiler's last line, the compiler's first
   "error:" line) is kept for the screen.

   On Windows (PLAN-windows.md step 4) the same stages, with what the
   app's folder holds beside NES RECOMP's program: nesrecomp-recomp.exe,
   runtime\, SDL2.dll with sdl2\include and sdl2\lib\libSDL2.dll.a (to
   link against), and zlib\include and zlib\lib\libz.a (Windows has no
   zlib of its own). The compiler is Zig's (`zig cc`): the app's own,
   zig\zig.exe beside the program, or one on PATH. A game is NAME.exe,
   and SDL2.dll is copied beside it. Only the runtime's .c files are
   compiled (record_mac.m is the Mac's). */
#include "build.h"
#include "os.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char rt_dir[PATH_MAX], build_dir[PATH_MAX];
static char sdl_lib[PATH_MAX], sdl_inc[PATH_MAX + 8], sdl_version_h[PATH_MAX];
static char recompiler[PATH_MAX];
#ifdef _WIN32
static char sdl_implib[PATH_MAX], zlib_inc[PATH_MAX + 8], zlib_lib[PATH_MAX];
static char zig[PATH_MAX];              /* the compiler (build_have_compiler) */
#endif

/* How much of the bar each stage has. */
static const double weight[ST_COUNT] = { 0.02, 0.13, 0.45, 0.30, 0.10 };

const char *build_stage_name(int stage) {
    static const char *names[ST_COUNT] = {
        "CHECKING THE FILE", "RECOMPILING", "COMPILING THE GAME",
        "BUILDING RUNTIME", "LINKING",
    };
    return stage >= 0 && stage < ST_COUNT ? names[stage] : "";
}

double build_now(void) { return os_now(); }

void build_setup(const char *b) {
    snprintf(build_dir, sizeof build_dir, "%s", b);
}

static int exists(const char *path) { return os_exists(path); }

int build_find_parts(const char *exe, const char *root) {
    char dir[PATH_MAX], lib[PATH_MAX], inc[PATH_MAX], rt[PATH_MAX];
    snprintf(dir, sizeof dir, "%s", exe);
    char *slash = (char *)os_last_sep(dir);
    if (slash) *slash = 0; else snprintf(dir, sizeof dir, ".");
#ifdef _WIN32
    /* All beside the program (the folder the release unzips to). */
    snprintf(lib, sizeof lib, "%s/SDL2.dll", dir);
    snprintf(inc, sizeof inc, "%s/sdl2/include", dir);
    snprintf(rt, sizeof rt, "%s/runtime", dir);
    snprintf(sdl_implib, sizeof sdl_implib, "%s/sdl2/lib/libSDL2.dll.a", dir);
    snprintf(zlib_inc, sizeof zlib_inc, "-I%s/zlib/include", dir);
    snprintf(zlib_lib, sizeof zlib_lib, "%s/zlib/lib/libz.a", dir);
    if (root && *root) snprintf(rt, sizeof rt, "%s/runtime", root);
    if (os_real_path(rt, rt_dir, sizeof rt_dir)) snprintf(rt_dir, sizeof rt_dir, "%s", rt);
    if (os_real_path(lib, sdl_lib, sizeof sdl_lib)) sdl_lib[0] = 0;
    snprintf(recompiler, sizeof recompiler, "%s/nesrecomp-recomp.exe", dir);
    char real[PATH_MAX];
    if (!os_real_path(inc, real, sizeof real)) {
        snprintf(sdl_inc, sizeof sdl_inc, "-I%s/SDL2", real);
        snprintf(sdl_version_h, sizeof sdl_version_h, "%s/SDL2/SDL_version.h", real);
    } else sdl_inc[0] = sdl_version_h[0] = 0;
    return sdl_lib[0] && sdl_version_h[0] && exists(sdl_version_h) && exists(sdl_implib);
#else
    size_t len = strlen(dir);
    if (len >= 15 && !strcmp(dir + len - 15, "/Contents/MacOS")) {
        snprintf(lib, sizeof lib, "%s/../Frameworks/libSDL2.dylib", dir);
        snprintf(inc, sizeof inc, "%s/../Resources/sdl2/include", dir);
        snprintf(rt, sizeof rt, "%s/../Resources/runtime", dir);
    } else {
        snprintf(lib, sizeof lib, "%s/sdl2/lib/libSDL2.dylib", dir);
        snprintf(inc, sizeof inc, "%s/sdl2/include", dir);
        snprintf(rt, sizeof rt, "%s/../runtime", dir);
    }
    if (root && *root) snprintf(rt, sizeof rt, "%s/runtime", root);
    if (os_real_path(rt, rt_dir, sizeof rt_dir)) snprintf(rt_dir, sizeof rt_dir, "%s", rt);
    if (os_real_path(lib, sdl_lib, sizeof sdl_lib)) sdl_lib[0] = 0;
    /* The recompiler is beside the program, in the bundle and in build/. */
    snprintf(recompiler, sizeof recompiler, "%s/nesrecomp-recomp", dir);
    char real[PATH_MAX];
    if (!os_real_path(inc, real, sizeof real)) {
        snprintf(sdl_inc, sizeof sdl_inc, "-I%s/SDL2", real);
        snprintf(sdl_version_h, sizeof sdl_version_h, "%s/SDL2/SDL_version.h", real);
    } else sdl_inc[0] = sdl_version_h[0] = 0;
    return sdl_lib[0] && sdl_version_h[0] && exists(sdl_version_h);
#endif
}

const char *build_runtime(void) { return rt_dir; }

const char *build_sdl_lib(void) { return sdl_lib; }

const char *build_recompiler(void) { return recompiler; }

/* Copy the app's SDL2 library beside the games (build/lib/ on the Mac,
   build/ itself on Windows), unless the copy there already has its size
   and time. */
static int copy_sdl(char *dest, size_t n) {
#ifdef _WIN32
    snprintf(dest, n, "%s/SDL2.dll", build_dir);
#else
    char dir[PATH_MAX];
    snprintf(dir, sizeof dir, "%s/lib", build_dir);
    os_mkdir(dir);
    snprintf(dest, n, "%s/libSDL2.dylib", dir);
#endif
    if (!exists(sdl_lib)) return -1;
    if (exists(dest) && os_size(sdl_lib) == os_size(dest) && os_mtime(sdl_lib) == os_mtime(dest))
        return 0;
    return os_copy(sdl_lib, dest);
}

int build_check_file(const char *path, char *why, size_t n) {
    unsigned char h[16] = { 0 };
    FILE *f = fopen(path, "rb");
    if (!f) { snprintf(why, n, "CAN'T OPEN THE FILE"); return 0; }
    size_t got = fread(h, 1, sizeof h, f);
    fclose(f);
    if (got >= 4 && !memcmp(h, "NES\x1a", 4)) return 1;
    if (got >= 5 && !memcmp(h, "NESM\x1a", 5)) return 1;
    if (got >= 4 && !memcmp(h, "FDS\x1a", 4)) return 1;
    if (got >= 15 && !memcmp(h, "\x01*NINTENDO-HVC*", 15)) return 1;
    snprintf(why, n, "NOT AN NES ROM");
    return 0;
}

void build_name(const char *path, char *out, size_t n) {
    const char *base = os_last_sep(path);
    base = base ? base + 1 : path;
    size_t len = strlen(base);
    const char *dot = strrchr(base, '.');
    if (dot && dot != base) len = (size_t)(dot - base);
    size_t k = 0;
    for (size_t i = 0; i < len && k + 1 < n; i++) {
        char c = base[i];
        int ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
                 c == '-' || c == '_';
        out[k++] = ok ? c : '_';
    }
    if (k == 0 && n > 4) { strcpy(out, "rom"); k = 3; }
    out[k] = 0;
}

static void set_stage(struct build *b, int stage, double estimate) {
    b->stage_start = build_now();
    b->estimate = estimate > 0.2 ? estimate : 0.2;
    atomic_store(&b->stage, stage);
    if (b->verbose) {
        printf("stage %d/%d: %s\n", stage + 1, ST_COUNT, build_stage_name(stage));
        fflush(stdout);
    }
}

static int fail(struct build *b, const char *fmt, const char *detail) {
    snprintf(b->error, sizeof b->error, fmt, detail ? detail : "");
    atomic_store(&b->state, B_FAILED);
    if (b->verbose) { printf("error: %s\n", b->error); fflush(stdout); }
    else fprintf(stderr, "nesrecomp: %s: %s\n", b->rom, b->error);   /* for the Mac's log */
    return 1;
}

/* Run argv with its output appended to the log. Returns the exit status
   (or -1 if it couldn't start), and leaves where its output began in
   *from, to look for its message. */
static int run(struct build *b, char **argv, long *from) {
    FILE *f = fopen(b->log, "ab");
    if (!f) return -1;
    fprintf(f, "$");
    for (int i = 0; argv[i]; i++) fprintf(f, " %s", argv[i]);
    fprintf(f, "\n");
    fseek(f, 0, SEEK_END);
    *from = ftell(f);
    fclose(f);
    return os_run(argv, b->log);
}

/* A line of what a tool printed: the first containing `want`, or the
   last non-empty one. */
static void message(struct build *b, long from, const char *want, char *out, size_t n) {
    out[0] = 0;
    FILE *f = fopen(b->log, "rb");
    if (!f) return;
    fseek(f, from, SEEK_SET);
    char line[1024];
    while (fgets(line, sizeof line, f)) {
        line[strcspn(line, "\r\n")] = 0;
        if (!line[0]) continue;
        if (want && strstr(line, want)) {
            char *p = strstr(line, want);
            snprintf(out, n, "%s", p + strlen(want));
            break;
        }
        if (!want || !out[0]) snprintf(out, n, "%s", line);
    }
    fclose(f);
}

/* Whole seconds (as the runtime objects are compared), and to the
   system's finest (for the record of what a program was built from). */
static double mtime(const char *path) {
    double t = os_mtime(path);
    return t < 0 ? -1 : floor(t);
}

static long file_size(const char *path) { return os_size(path); }

static double mtime_ns(const char *path) { return os_mtime(path); }

static int ends(const char *name, const char *ext) {
    size_t len = strlen(name), e = strlen(ext);
    return len > e && !strcmp(name + len - e, ext);
}

struct newest { const char *dir; double t; };

static void newest_source(const char *name, void *arg) {
    struct newest *nw = arg;
    if (ends(name, ".c") || ends(name, ".h") || ends(name, ".m")) {
        char path[PATH_MAX];
        snprintf(path, sizeof path, "%s/%s", nw->dir, name);
        double t = mtime_ns(path);
        if (t > nw->t) nw->t = t;
    }
}

/* What a program would be built from, as one line. */
static void stamp_text(const char *rom, const char *missed, char *out, size_t n) {
    char recomp[PATH_MAX];
    snprintf(recomp, sizeof recomp, "%s", recompiler);
    struct newest nw = { rt_dir, 0 };
    os_list(rt_dir, newest_source, &nw);
    double newest = nw.t;
    snprintf(out, n, "app %s rom %s %ld %.9f missed %ld %.9f recomp %.9f runtime %.9f sdl %.9f\n",
             APP_VERSION, rom, file_size(rom), mtime_ns(rom), file_size(missed), mtime_ns(missed),
             mtime_ns(recomp), newest, mtime_ns(sdl_version_h));
}

#ifdef _WIN32
const char *build_xcode_select(void) { return ""; }

/* Zig's compiler: the app's own (zig\zig.exe beside the program, PLAN-
   windows.md step 5), or one on PATH. */
int build_have_compiler(char *where, size_t n) {
    if (where && n) where[0] = 0;
    char own[PATH_MAX];
    snprintf(own, sizeof own, "%s", recompiler);
    char *cut = (char *)os_last_sep(own);
    if (cut) { snprintf(cut + 1, sizeof own - (size_t)(cut + 1 - own), "zig/zig.exe"); }
    zig[0] = 0;
    if (cut && os_can_run(own)) snprintf(zig, sizeof zig, "%s", own);
    else {
        const char *path = getenv("PATH");
        char dir[PATH_MAX];
        while (path && *path && !zig[0]) {
            size_t k = strcspn(path, ";");
            snprintf(dir, sizeof dir, "%.*s/zig.exe", (int)k, path);
            if (k && os_can_run(dir)) snprintf(zig, sizeof zig, "%s", dir);
            path += k + (path[k] == ';');
        }
    }
    if (!zig[0]) return 0;
    if (where) snprintf(where, n, "%s", zig);
    return 1;
}
#else
#include <errno.h>
#include <fcntl.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

const char *build_xcode_select(void) {
    const char *x = getenv("NESRECOMP_XCODE_SELECT");     /* for the checks */
    return x && *x ? x : "/usr/bin/xcode-select";
}

int build_have_compiler(char *where, size_t n) {
    if (where && n) where[0] = 0;
    int fd[2];
    if (pipe(fd)) return 0;
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_adddup2(&fa, fd[1], 1);
    posix_spawn_file_actions_addopen(&fa, 2, "/dev/null", O_WRONLY, 0);
    posix_spawn_file_actions_addclose(&fa, fd[0]);
    char *argv[] = { (char *)build_xcode_select(), "-p", NULL };
    pid_t pid;
    int err = posix_spawn(&pid, argv[0], &fa, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&fa);
    close(fd[1]);
    char dir[PATH_MAX] = "";
    if (!err) {
        size_t got = 0;
        ssize_t k;
        while (got + 1 < sizeof dir && (k = read(fd[0], dir + got, sizeof dir - 1 - got)) > 0)
            got += (size_t)k;
        dir[got] = 0;
        int status;
        while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {}
        if (!WIFEXITED(status) || WEXITSTATUS(status)) dir[0] = 0;
    }
    close(fd[0]);
    dir[strcspn(dir, "\r\n")] = 0;
    if (!dir[0]) return 0;
    /* The Command Line Tools have usr/bin/clang; Xcode has it in its
       default toolchain. */
    static const char *const at[] = {
        "usr/bin/clang", "Toolchains/XcodeDefault.xctoolchain/usr/bin/clang",
    };
    for (size_t i = 0; i < sizeof at / sizeof *at; i++) {
        char p[PATH_MAX + 64];
        snprintf(p, sizeof p, "%s/%s", dir, at[i]);
        if (os_can_run(p)) {
            if (where) snprintf(where, n, "%s", p);
            return 1;
        }
    }
    return 0;
}
#endif

static int by_name(const void *a, const void *b) {
    return strcmp(*(char *const *)a, *(char *const *)b);
}

/* The start of a compiler's command: cc (Apple's) on the Mac, zig cc on
   Windows, with what every file needs: the runtime's headers, SDL's,
   (on Windows) zlib's. */
static int cc_start(char **a, char *inc) {
    int k = 0;
#ifdef _WIN32
    a[k++] = zig; a[k++] = "cc";
#else
    a[k++] = "cc";
#endif
    a[k++] = "-O1"; a[k++] = "-w"; a[k++] = inc; a[k++] = sdl_inc;
#ifdef _WIN32
    a[k++] = zlib_inc;
#endif
    a[k++] = "-D_THREAD_SAFE";
    return k;
}

/* The runtime's files to compile (.c, and on the Mac record_mac.m,
   Objective-C), and its headers' newest time. */
struct sources { const char *dir; char *srcs[256]; int n; double newest_h; };

static void add_source(const char *name, void *arg) {
    struct sources *sl = arg;
    char path[PATH_MAX];
    snprintf(path, sizeof path, "%s/%s", sl->dir, name);
#ifdef _WIN32
    int compiled = ends(name, ".c");
#else
    int compiled = ends(name, ".c") || ends(name, ".m");
#endif
    if (compiled && sl->n < 256) sl->srcs[sl->n++] = strdup(name);
    else if (ends(name, ".h") && mtime(path) > sl->newest_h) sl->newest_h = mtime(path);
}

int build_run(struct build *b, const char *rom) {
    char why[128], cfile[PATH_MAX], gobj[PATH_MAX], missed[PATH_MAX], rtdir[PATH_MAX];
    char rdir[PATH_MAX], recomp[PATH_MAX], inc[PATH_MAX + 2], msg[512];
    long from;
    if (rom != b->rom) snprintf(b->rom, sizeof b->rom, "%s", rom);
    rom = b->rom;
    build_name(rom, b->name, sizeof b->name);
    snprintf(b->out, sizeof b->out, "%s/%s%s", build_dir, b->name, os_exe_ext());
    snprintf(b->log, sizeof b->log, "%s/%s.log", build_dir, b->name);
    /* Where ROM.missed and ROM.sav are kept: beside the ROM if its folder
       can be written, otherwise here, as NAME.missed and NAME.sav. */
    char rom_dir[PATH_MAX];
    snprintf(rom_dir, sizeof rom_dir, "%s", rom);
    char *cut = (char *)os_last_sep(rom_dir);
    if (cut == rom_dir) cut[1] = 0;
    else if (cut) *cut = 0;
    else snprintf(rom_dir, sizeof rom_dir, ".");
    if (os_can_write(rom_dir)) snprintf(b->files_at, sizeof b->files_at, "%s", rom);
    else snprintf(b->files_at, sizeof b->files_at, "%s/%s", build_dir, b->name);
    b->error[0] = 0;
    b->no_compiler = 0;
    atomic_store(&b->rt_done, 0);
    atomic_store(&b->rt_total, 0);
    atomic_store(&b->state, B_RUNNING);
    os_mkdir(build_dir);
    os_remove(b->log);

    set_stage(b, ST_CHECK, 0.2);
    if (!build_check_file(rom, why, sizeof why)) return fail(b, "%s", why);
    if (!sdl_lib[0] || !exists(sdl_version_h))
        return fail(b, "%s", "the app's SDL2 is missing");
    if (!os_can_run(recompiler))
        return fail(b, "%s", "the app's recompiler is missing");
    char rt_h[PATH_MAX + 8];
    snprintf(rt_h, sizeof rt_h, "%s/rt.h", rt_dir);
    if (!exists(rt_h))
        return fail(b, "%s", "the app's runtime is missing");

    /* Up to date? Then nothing to build. */
    char stamp[PATH_MAX], want[PATH_MAX * 2 + 256], have[sizeof want];
    snprintf(stamp, sizeof stamp, "%s/%s.stamp", build_dir, b->name);
    snprintf(missed, sizeof missed, "%s.missed", b->files_at);
    stamp_text(rom, missed, want, sizeof want);
    FILE *sf = fopen(stamp, "r");
    have[0] = 0;
    if (sf) { if (!fgets(have, sizeof have, sf)) have[0] = 0; fclose(sf); }
    /* What the recompiler translated, for "under the hood" (hood.h): its
       "translated N instructions" line, kept beside the program. */
    char counted[PATH_MAX + 16];
    snprintf(counted, sizeof counted, "%s/%s.translated", build_dir, b->name);
    b->translated = -1;
    char listing[PATH_MAX + 16];
    snprintf(listing, sizeof listing, "%s/%s.listing", build_dir, b->name);
    if (!strcmp(have, want) && os_can_run(b->out) && exists(listing)) {
        FILE *cf = fopen(counted, "r");
        if (cf) { if (fscanf(cf, "%ld", &b->translated) != 1) b->translated = -1; fclose(cf); }
        atomic_store(&b->stage, ST_LINK);
        atomic_store(&b->state, B_DONE);
        if (b->verbose) { printf("up to date: %s\n", b->out); fflush(stdout); }
        return 0;
    }
    os_remove(stamp);               /* only a finished build is trusted */

    /* The C compiler, before anything is compiled: Apple's on the Mac
       (or what to do to get it), the app's own on Windows. */
    if (!build_have_compiler(NULL, 0)) {
#ifdef _WIN32
        return fail(b, "%s", "the app's compiler is missing");
#else
        b->no_compiler = 1;
        return fail(b, "%s", "needs Apple's C compiler: xcode-select --install");
#endif
    }

    /* 2: the recompiler. */
    set_stage(b, ST_RECOMP, 0.5 + file_size(rom) / 200000.0);
    snprintf(cfile, sizeof cfile, "%s/%s.c", build_dir, b->name);
    snprintf(recomp, sizeof recomp, "%s", recompiler);
    /* With --listing, for "the 6502 next to its C" (code.h). */
    char lst[PATH_MAX + 16];
    snprintf(lst, sizeof lst, "%s/%s.listing", build_dir, b->name);
    char *ra[] = { recomp, (char *)rom, "-o", cfile, "--listing", lst, NULL, NULL, NULL };
    if (exists(missed)) { ra[6] = "--missed"; ra[7] = missed; }
    int r = run(b, ra, &from);
    if (r) {
        message(b, from, NULL, msg, sizeof msg);
        return fail(b, "%s", r < 0 ? "the recompiler didn't start" : msg);
    }
    message(b, from, "translated ", msg, sizeof msg);
    if (sscanf(msg, "%ld instructions", &b->translated) != 1) b->translated = -1;
    FILE *cf = fopen(counted, "w");
    if (cf) { fprintf(cf, "%ld\n", b->translated); fclose(cf); }

    /* 3: the game's C. */
    set_stage(b, ST_GAME, file_size(cfile) / 100000.0);
    snprintf(gobj, sizeof gobj, "%s/%s.o", build_dir, b->name);
    snprintf(rdir, sizeof rdir, "%s", rt_dir);
    snprintf(inc, sizeof inc, "-I%s", rdir);
    char *ga[32];
    int gn = cc_start(ga, inc);
    ga[gn++] = "-c"; ga[gn++] = "-o"; ga[gn++] = gobj; ga[gn++] = cfile; ga[gn] = NULL;
    r = run(b, ga, &from);
    if (r) {
        message(b, from, "error: ", msg, sizeof msg);
        return fail(b, "the C compiler: %s", r < 0 ? "cc didn't start" : msg);
    }

    /* 4: the runtime, each file once (again when a source or header is
       newer than its object). */
    snprintf(rtdir, sizeof rtdir, "%s/app-rt", build_dir);
    os_mkdir(rtdir);
    struct sources sl = { rdir, {0}, 0, 0 };
    if (os_list(rdir, add_source, &sl)) return fail(b, "%s", "the app's runtime is missing");
    char **srcs = sl.srcs;
    int ns = sl.n;
    double newest_h = sl.newest_h;
    if (mtime(sdl_version_h) > newest_h) newest_h = mtime(sdl_version_h);
    qsort(srcs, (size_t)ns, sizeof *srcs, by_name);
    char objs[256][PATH_MAX];
    int todo[256], ntodo = 0;
    for (int i = 0; i < ns; i++) {
        char src[PATH_MAX];
        snprintf(src, sizeof src, "%s/%s", rdir, srcs[i]);
        snprintf(objs[i], sizeof objs[i], "%s/%.*s.o", rtdir, (int)strlen(srcs[i]) - 2, srcs[i]);
        double o = mtime(objs[i]);
        if (o < 0 || o < mtime(src) || o < newest_h) todo[ntodo++] = i;
    }
    atomic_store(&b->rt_total, ntodo);
    set_stage(b, ST_RUNTIME, 1.0);
    for (int k = 0; k < ntodo; k++) {
        int i = todo[k];
        char src[PATH_MAX];
        snprintf(src, sizeof src, "%s/%s", rdir, srcs[i]);
        char *ca[32];
        int cn = cc_start(ca, inc);
        ca[cn++] = "-c"; ca[cn++] = "-o"; ca[cn++] = objs[i]; ca[cn++] = src; ca[cn] = NULL;
        r = run(b, ca, &from);
        if (r) {
            os_remove(objs[i]);
            message(b, from, "error: ", msg, sizeof msg);
            for (int j = 0; j < ns; j++) free(srcs[j]);
            return fail(b, "the C compiler: %s", r < 0 ? "cc didn't start" : msg);
        }
        atomic_store(&b->rt_done, k + 1);
    }

    if (b->verbose) {
        printf("runtime: %d of %d file(s) compiled\n", ntodo, ns);
        fflush(stdout);
    }

    /* 5: linking. */
    set_stage(b, ST_LINK, 0.5);
    char sdl_copy[PATH_MAX];
    if (copy_sdl(sdl_copy, sizeof sdl_copy)) {
        for (int j = 0; j < ns; j++) free(srcs[j]);
        return fail(b, "can't copy SDL2 from %s", sdl_lib[0] ? sdl_lib : "the app");
    }
    char *la[300];
    int ln = 0;
#ifdef _WIN32
    la[ln++] = zig; la[ln++] = "cc";
    la[ln++] = "-o"; la[ln++] = b->out; la[ln++] = gobj;
    for (int i = 0; i < ns; i++) la[ln++] = objs[i];
    /* SDL2.dll, which it finds beside it (copied there above), through
       its import library; zlib for pictures; ole32 for recording. */
    la[ln++] = sdl_implib;
    la[ln++] = zlib_lib;
    la[ln++] = "-lole32";
#else
    la[ln++] = "cc"; la[ln++] = "-o"; la[ln++] = b->out; la[ln++] = gobj;
    for (int i = 0; i < ns; i++) la[ln++] = objs[i];
    la[ln++] = sdl_copy;
    la[ln++] = "-Wl,-rpath,@executable_path/lib";
    la[ln++] = "-lz"; la[ln++] = "-lm";
    /* Recording (record_mac.m): Apple's AVFoundation. */
    static char *fw[] = { "AVFoundation", "CoreMedia", "CoreVideo", "Foundation" };
    for (int i = 0; i < 4; i++) { la[ln++] = "-framework"; la[ln++] = fw[i]; }
#endif
    la[ln] = NULL;
    r = run(b, la, &from);
    for (int j = 0; j < ns; j++) free(srcs[j]);
    if (r) {
        message(b, from, "error: ", msg, sizeof msg);
        if (!msg[0]) message(b, from, NULL, msg, sizeof msg);
        return fail(b, "linking: %s", r < 0 ? "cc didn't start" : msg);
    }
    sf = fopen(stamp, "w");
    if (sf) { fputs(want, sf); fclose(sf); }
    atomic_store(&b->state, B_DONE);
    if (b->verbose) { printf("built: %s\n", b->out); fflush(stdout); }
    return 0;
}

static void thread_main(void *arg) {
    struct build *b = arg;
    build_run(b, b->rom);
}

void build_start(struct build *b, const char *rom) {
    snprintf(b->rom, sizeof b->rom, "%s", rom);
    b->name[0] = 0;
    build_name(rom, b->name, sizeof b->name);
    atomic_store(&b->stage, ST_CHECK);
    atomic_store(&b->state, B_RUNNING);
    b->stage_start = build_now();
    b->estimate = 0.2;
    if (os_thread(thread_main, b)) fail(b, "%s", "couldn't start the build");
}

double build_progress(struct build *b, double now) {
    int stage = atomic_load(&b->stage);
    if (atomic_load(&b->state) == B_DONE) return 1.0;
    double before = 0;
    for (int i = 0; i < stage && i < ST_COUNT; i++) before += weight[i];
    double frac;
    if (stage == ST_RUNTIME) {
        int total = atomic_load(&b->rt_total), done = atomic_load(&b->rt_done);
        frac = total ? 0.95 * done / total : 0.95;
    } else {
        double t = now - b->stage_start;
        frac = 0.95 * (1.0 - exp(-t / b->estimate));
    }
    return before + weight[stage < ST_COUNT ? stage : ST_COUNT - 1] * frac;
}
