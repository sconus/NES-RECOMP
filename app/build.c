/* nesrecomp app: building a dropped ROM, as `make game` does, in stages
   the loading bar can follow:
     1  checking the file   its first bytes: iNES, NSF or FDS
     2  recompiling         python3 recomp.py ROM -o build/NAME.c
                            (with ROM.missed when there is one)
     3  compiling the game  cc -c build/NAME.c
     4  the runtime         cc -c runtime/X.c for each file, kept in
                            build/app-rt/ and only compiled again when a
                            runtime source or header is newer
     5  linking             cc -o build/NAME ...
   SDL2 is the app's own copy, not Homebrew's (PLAN-standalone.md step
   1): games compile against its headers and link build/lib/libSDL2.dylib,
   a copy of the app's library made before linking, which they find
   beside them (their rpath is @executable_path/lib). So a game still
   runs after the app is moved or replaced.
   A build that would make the same program again is skipped: build/
   NAME.stamp records what the program was built from (the ROM's path,
   size and time, its .missed file's, recomp.py's time, the newest
   runtime file's), and when all match and the program is there, the
   build is "up to date" and done at once.
   The tools run with posix_spawn (no shell, so paths with spaces work),
   their output appended to build/NAME.log. A tool that fails stops the
   build; its message (the recompiler's last line, the compiler's first
   "error:" line) is kept for the screen. */
#include "build.h"
#include <dirent.h>
#include <errno.h>
#include <copyfile.h>
#include <fcntl.h>
#include <math.h>
#include <pthread.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

extern char **environ;

static char root[PATH_MAX], build_dir[PATH_MAX];
static char sdl_lib[PATH_MAX], sdl_inc[PATH_MAX + 8], sdl_version_h[PATH_MAX];

/* How much of the bar each stage has. */
static const double weight[ST_COUNT] = { 0.02, 0.13, 0.45, 0.30, 0.10 };

const char *build_stage_name(int stage) {
    static const char *names[ST_COUNT] = {
        "CHECKING THE FILE", "RECOMPILING", "COMPILING THE GAME",
        "BUILDING RUNTIME", "LINKING",
    };
    return stage >= 0 && stage < ST_COUNT ? names[stage] : "";
}

double build_now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

void build_setup(const char *r, const char *b) {
    snprintf(root, sizeof root, "%s", r);
    snprintf(build_dir, sizeof build_dir, "%s", b);
}

static int exists(const char *path) {
    struct stat st;
    return stat(path, &st) == 0;
}

int build_find_sdl(const char *exe) {
    char dir[PATH_MAX], lib[PATH_MAX], inc[PATH_MAX];
    snprintf(dir, sizeof dir, "%s", exe);
    char *slash = strrchr(dir, '/');
    if (slash) *slash = 0; else snprintf(dir, sizeof dir, ".");
    size_t len = strlen(dir);
    if (len >= 15 && !strcmp(dir + len - 15, "/Contents/MacOS")) {
        snprintf(lib, sizeof lib, "%s/../Frameworks/libSDL2.dylib", dir);
        snprintf(inc, sizeof inc, "%s/../Resources/sdl2/include", dir);
    } else {
        snprintf(lib, sizeof lib, "%s/sdl2/lib/libSDL2.dylib", dir);
        snprintf(inc, sizeof inc, "%s/sdl2/include", dir);
    }
    if (!realpath(lib, sdl_lib)) sdl_lib[0] = 0;
    char real[PATH_MAX];
    if (realpath(inc, real)) {
        snprintf(sdl_inc, sizeof sdl_inc, "-I%s/SDL2", real);
        snprintf(sdl_version_h, sizeof sdl_version_h, "%s/SDL2/SDL_version.h", real);
    } else sdl_inc[0] = sdl_version_h[0] = 0;
    return sdl_lib[0] && sdl_version_h[0] && exists(sdl_version_h);
}

const char *build_sdl_lib(void) { return sdl_lib; }

/* Copy the app's SDL2 library to build/lib/, unless the copy there
   already has its size and time. */
static int copy_sdl(char *dest, size_t n) {
    char dir[PATH_MAX];
    snprintf(dir, sizeof dir, "%s/lib", build_dir);
    mkdir(dir, 0755);
    snprintf(dest, n, "%s/libSDL2.dylib", dir);
    struct stat a, b;
    if (stat(sdl_lib, &a)) return -1;
    if (!stat(dest, &b) && a.st_size == b.st_size &&
        a.st_mtimespec.tv_sec == b.st_mtimespec.tv_sec &&
        a.st_mtimespec.tv_nsec == b.st_mtimespec.tv_nsec) return 0;
    char tmp[PATH_MAX + 8];
    snprintf(tmp, sizeof tmp, "%s.new", dest);
    if (copyfile(sdl_lib, tmp, NULL, COPYFILE_DATA | COPYFILE_STAT) ||
        rename(tmp, dest)) { unlink(tmp); return -1; }
    return 0;
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
    const char *base = strrchr(path, '/');
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
    return 1;
}

/* Run argv with its output appended to the log. Returns the exit status
   (or -1 if it couldn't start), and leaves where its output began in
   *from, to look for its message. */
static int run(struct build *b, char **argv, long *from) {
    int fd = open(b->log, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd < 0) return -1;
    dprintf(fd, "$");
    for (int i = 0; argv[i]; i++) dprintf(fd, " %s", argv[i]);
    dprintf(fd, "\n");
    *from = lseek(fd, 0, SEEK_END);
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_adddup2(&fa, fd, 1);
    posix_spawn_file_actions_adddup2(&fa, fd, 2);
    pid_t pid;
    int err = posix_spawnp(&pid, argv[0], &fa, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&fa);
    close(fd);
    if (err) return -1;
    int status;
    while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {}
    return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}

/* A line of what a tool printed: the first containing `want`, or the
   last non-empty one. */
static void message(struct build *b, long from, const char *want, char *out, size_t n) {
    out[0] = 0;
    FILE *f = fopen(b->log, "r");
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

static double mtime(const char *path) {
    struct stat st;
    return stat(path, &st) ? -1 : (double)st.st_mtime;
}

static long file_size(const char *path) {
    struct stat st;
    return stat(path, &st) ? 0 : (long)st.st_size;
}

static double mtime_ns(const char *path) {
    struct stat st;
    return stat(path, &st) ? -1 : st.st_mtimespec.tv_sec + st.st_mtimespec.tv_nsec / 1e9;
}

/* What a program would be built from, as one line. */
static void stamp_text(const char *rom, char *out, size_t n) {
    char missed[PATH_MAX], recomp[PATH_MAX], rdir[PATH_MAX];
    snprintf(missed, sizeof missed, "%s.missed", rom);
    snprintf(recomp, sizeof recomp, "%s/recomp.py", root);
    snprintf(rdir, sizeof rdir, "%s/runtime", root);
    double newest = 0;
    DIR *d = opendir(rdir);
    struct dirent *e;
    while (d && (e = readdir(d))) {
        size_t len = strlen(e->d_name);
        if (len > 2 && (!strcmp(e->d_name + len - 2, ".c") || !strcmp(e->d_name + len - 2, ".h"))) {
            char path[PATH_MAX];
            snprintf(path, sizeof path, "%s/%s", rdir, e->d_name);
            double t = mtime_ns(path);
            if (t > newest) newest = t;
        }
    }
    if (d) closedir(d);
    snprintf(out, n, "rom %s %ld %.9f missed %ld %.9f recomp %.9f runtime %.9f sdl %.9f\n",
             rom, file_size(rom), mtime_ns(rom), file_size(missed), mtime_ns(missed),
             mtime_ns(recomp), newest, mtime_ns(sdl_version_h));
}

static int by_name(const void *a, const void *b) {
    return strcmp(*(char *const *)a, *(char *const *)b);
}

int build_run(struct build *b, const char *rom) {
    char why[128], cfile[PATH_MAX], gobj[PATH_MAX], missed[PATH_MAX], rtdir[PATH_MAX];
    char rdir[PATH_MAX], recomp[PATH_MAX], inc[PATH_MAX + 2], msg[512];
    long from;
    if (rom != b->rom) snprintf(b->rom, sizeof b->rom, "%s", rom);
    rom = b->rom;
    build_name(rom, b->name, sizeof b->name);
    snprintf(b->out, sizeof b->out, "%s/%s", build_dir, b->name);
    snprintf(b->log, sizeof b->log, "%s/%s.log", build_dir, b->name);
    b->error[0] = 0;
    atomic_store(&b->rt_done, 0);
    atomic_store(&b->rt_total, 0);
    atomic_store(&b->state, B_RUNNING);
    mkdir(build_dir, 0755);
    unlink(b->log);

    set_stage(b, ST_CHECK, 0.2);
    if (!build_check_file(rom, why, sizeof why)) return fail(b, "%s", why);
    if (!sdl_lib[0] || !exists(sdl_version_h))
        return fail(b, "%s", "the app's SDL2 is missing");

    /* Up to date? Then nothing to build. */
    char stamp[PATH_MAX], want[PATH_MAX * 2 + 256], have[sizeof want];
    snprintf(stamp, sizeof stamp, "%s/%s.stamp", build_dir, b->name);
    stamp_text(rom, want, sizeof want);
    FILE *sf = fopen(stamp, "r");
    have[0] = 0;
    if (sf) { if (!fgets(have, sizeof have, sf)) have[0] = 0; fclose(sf); }
    if (!strcmp(have, want) && access(b->out, X_OK) == 0) {
        atomic_store(&b->stage, ST_LINK);
        atomic_store(&b->state, B_DONE);
        if (b->verbose) { printf("up to date: %s\n", b->out); fflush(stdout); }
        return 0;
    }
    unlink(stamp);                  /* only a finished build is trusted */

    /* 2: the recompiler. */
    set_stage(b, ST_RECOMP, 0.5 + file_size(rom) / 200000.0);
    snprintf(cfile, sizeof cfile, "%s/%s.c", build_dir, b->name);
    snprintf(recomp, sizeof recomp, "%s/recomp.py", root);
    snprintf(missed, sizeof missed, "%s.missed", rom);
    char *ra[] = { "python3", recomp, (char *)rom, "-o", cfile, NULL, NULL, NULL };
    if (access(missed, R_OK) == 0) { ra[5] = "--missed"; ra[6] = missed; }
    int r = run(b, ra, &from);
    if (r) {
        message(b, from, NULL, msg, sizeof msg);
        return fail(b, "%s", r < 0 ? "python3 didn't start" : msg);
    }

    /* 3: the game's C. */
    set_stage(b, ST_GAME, file_size(cfile) / 100000.0);
    snprintf(gobj, sizeof gobj, "%s/%s.o", build_dir, b->name);
    snprintf(rdir, sizeof rdir, "%s/runtime", root);
    snprintf(inc, sizeof inc, "-I%s", rdir);
    char *ga[32] = { "cc", "-O1", "-w", inc, sdl_inc, "-D_THREAD_SAFE" };
    int gn = 6;
    ga[gn++] = "-c"; ga[gn++] = "-o"; ga[gn++] = gobj; ga[gn++] = cfile; ga[gn] = NULL;
    r = run(b, ga, &from);
    if (r) {
        message(b, from, "error: ", msg, sizeof msg);
        return fail(b, "the C compiler: %s", r < 0 ? "cc didn't start" : msg);
    }

    /* 4: the runtime, each file once (again when a source or header is
       newer than its object). */
    snprintf(rtdir, sizeof rtdir, "%s/app-rt", build_dir);
    mkdir(rtdir, 0755);
    DIR *d = opendir(rdir);
    if (!d) return fail(b, "no runtime folder at %s", rdir);
    char *srcs[256];
    int ns = 0;
    double newest_h = 0;
    struct dirent *e;
    while ((e = readdir(d)) && ns < 256) {
        size_t len = strlen(e->d_name);
        char path[PATH_MAX];
        snprintf(path, sizeof path, "%s/%s", rdir, e->d_name);
        if (len > 2 && !strcmp(e->d_name + len - 2, ".c")) srcs[ns++] = strdup(e->d_name);
        else if (len > 2 && !strcmp(e->d_name + len - 2, ".h") && mtime(path) > newest_h)
            newest_h = mtime(path);
    }
    closedir(d);
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
        char *ca[32] = { "cc", "-O1", "-w", inc, sdl_inc, "-D_THREAD_SAFE" };
        int cn = 6;
        ca[cn++] = "-c"; ca[cn++] = "-o"; ca[cn++] = objs[i]; ca[cn++] = src; ca[cn] = NULL;
        r = run(b, ca, &from);
        if (r) {
            unlink(objs[i]);
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
    la[ln++] = "cc"; la[ln++] = "-o"; la[ln++] = b->out; la[ln++] = gobj;
    for (int i = 0; i < ns; i++) la[ln++] = objs[i];
    la[ln++] = sdl_copy;
    la[ln++] = "-Wl,-rpath,@executable_path/lib";
    la[ln++] = "-lz"; la[ln++] = "-lm"; la[ln] = NULL;
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

static void *thread_main(void *arg) {
    struct build *b = arg;
    build_run(b, b->rom);
    return NULL;
}

void build_start(struct build *b, const char *rom) {
    snprintf(b->rom, sizeof b->rom, "%s", rom);
    b->name[0] = 0;
    build_name(rom, b->name, sizeof b->name);
    atomic_store(&b->stage, ST_CHECK);
    atomic_store(&b->state, B_RUNNING);
    b->stage_start = build_now();
    b->estimate = 0.2;
    pthread_t t;
    if (pthread_create(&t, NULL, thread_main, b) == 0) pthread_detach(t);
    else fail(b, "%s", "couldn't start the build");
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
