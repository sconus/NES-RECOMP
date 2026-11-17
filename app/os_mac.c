/* nesrecomp app: the Mac's ways (os.h); any Unix's, but for the file
   picker (osascript) and the app folder (~/Library). On Windows this
   file is empty: os_win.c. */
typedef int os_mac_c;                   /* (so the file is never empty) */
#ifndef _WIN32
#include "os.h"
#include <dirent.h>
#include <errno.h>
#include <copyfile.h>
#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <pwd.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

extern char **environ;

os_proc os_start(char *const argv[], const char *log, int append) {
    int fd = log ? open(log, O_WRONLY | O_CREAT | (append ? O_APPEND : O_TRUNC), 0644)
                 : open("/dev/null", O_WRONLY);
    if (fd < 0) return -1;
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_adddup2(&fa, fd, 1);
    posix_spawn_file_actions_adddup2(&fa, fd, 2);
    pid_t pid;
    /* A bare name ("cc") is looked for on PATH; a path is run as it is. */
    int err = strchr(argv[0], '/') ? posix_spawn(&pid, argv[0], &fa, NULL, argv, environ)
                                   : posix_spawnp(&pid, argv[0], &fa, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&fa);
    close(fd);
    return err ? -1 : (os_proc)pid;
}

int os_poll(os_proc p, int wait, int *code, char *crash, size_t n) {
    int status;
    pid_t r;
    if (crash && n) crash[0] = 0;
    while ((r = waitpid((pid_t)p, &status, wait ? 0 : WNOHANG)) < 0 && errno == EINTR) {}
    if (r == 0) return 0;
    if (r < 0) { *code = -1; if (crash) snprintf(crash, n, "lost track of it"); return 1; }
    if (WIFSIGNALED(status)) {
        int sig = WTERMSIG(status);
        *code = -1;
        if (crash) snprintf(crash, n, "signal %d, %s", sig, strsignal(sig));
        return 1;
    }
    *code = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    return 1;
}

int os_run(char *const argv[], const char *log) {
    os_proc p = os_start(argv, log, 1);
    if (p < 0) return -1;
    int code;
    while (!os_poll(p, 1, &code, NULL, 0)) {}
    return code;
}

struct thread_job { void (*fn)(void *); void *arg; };

static void *thread_main(void *a) {
    struct thread_job j = *(struct thread_job *)a;
    free(a);
    j.fn(j.arg);
    return NULL;
}

int os_thread(void (*fn)(void *), void *arg) {
    struct thread_job *j = malloc(sizeof *j);
    if (!j) return -1;
    j->fn = fn;
    j->arg = arg;
    pthread_t t;
    if (pthread_create(&t, NULL, thread_main, j)) { free(j); return -1; }
    pthread_detach(t);
    return 0;
}

double os_now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

void os_setenv(const char *name, const char *value) { setenv(name, value, 1); }

#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif

int os_exe_path(char *out, size_t n) {
    char exe[PATH_MAX], real[PATH_MAX];
#ifdef __APPLE__
    uint32_t len = sizeof exe;
    if (_NSGetExecutablePath(exe, &len)) return -1;
#else
    ssize_t len = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (len < 0) return -1;
    exe[len] = 0;
#endif
    if (!realpath(exe, real)) return -1;
    snprintf(out, n, "%s", real);
    return 0;
}

int os_real_path(const char *path, char *out, size_t n) {
    char real[PATH_MAX];
    if (!realpath(path, real)) return -1;
    snprintf(out, n, "%s", real);
    return 0;
}

void os_app_dir(char *out, size_t n) {
    const char *home = getenv("HOME");
    struct passwd *pw = (!home || !*home) ? getpwuid(getuid()) : NULL;
    if (pw) home = pw->pw_dir;
    snprintf(out, n, "%s/Library/Application Support/NES RECOMP", home ? home : "/tmp");
}

const char *os_last_sep(const char *path) { return strrchr(path, '/'); }

const char *os_exe_ext(void) { return ""; }

int os_exists(const char *path) {
    struct stat st;
    return stat(path, &st) == 0;
}

int os_can_run(const char *path) { return access(path, X_OK) == 0; }

int os_can_write(const char *dir) { return access(dir, W_OK) == 0; }

double os_mtime(const char *path) {
    struct stat st;
    if (stat(path, &st)) return -1;
#ifdef __APPLE__
    return st.st_mtimespec.tv_sec + st.st_mtimespec.tv_nsec / 1e9;
#else
    return st.st_mtim.tv_sec + st.st_mtim.tv_nsec / 1e9;
#endif
}

long os_size(const char *path) {
    struct stat st;
    return stat(path, &st) ? 0 : (long)st.st_size;
}

void os_mkdir(const char *path) { mkdir(path, 0755); }

void os_make_dirs(const char *path) {
    char part[PATH_MAX];
    snprintf(part, sizeof part, "%s", path);
    for (char *p = part + 1; *p; p++)
        if (*p == '/') { *p = 0; mkdir(part, 0755); *p = '/'; }
    mkdir(part, 0755);
}

void os_remove(const char *path) { unlink(path); }

int os_copy(const char *from, const char *to) {
    char tmp[PATH_MAX + 8];
    snprintf(tmp, sizeof tmp, "%s.new", to);
    if (copyfile(from, tmp, NULL, COPYFILE_DATA | COPYFILE_STAT) || rename(tmp, to)) {
        unlink(tmp);
        return -1;
    }
    return 0;
}

int os_list(const char *dir, void (*each)(const char *name, void *arg), void *arg) {
    DIR *d = opendir(dir);
    if (!d) return -1;
    struct dirent *e;
    while ((e = readdir(d)))
        if (e->d_name[0] != '.') each(e->d_name, arg);
    closedir(d);
    return 0;
}

int os_pick_file(char *out, size_t n) {
    /* The Mac's standard dialog, through osascript. */
    FILE *p = popen("osascript -e 'POSIX path of (choose file with prompt "
                    "\"Choose an NES ROM, NSF or FDS file\")' 2>/dev/null", "r");
    char line[PATH_MAX] = "";
    if (p) {
        if (!fgets(line, sizeof line, p)) line[0] = 0;
        pclose(p);
    }
    line[strcspn(line, "\r\n")] = 0;
    if (!line[0]) return 0;
    snprintf(out, n, "%s", line);
    return 1;
}

int os_open_url(const char *url) {
    const char *open = getenv("NESRECOMP_OPEN");        /* for the checks */
    if (!open || !*open) open = "/usr/bin/open";
    char *argv[] = { (char *)open, (char *)url, NULL };
    pid_t pid;
    if (posix_spawn(&pid, argv[0], NULL, NULL, argv, environ)) return -1;
    int status;                         /* open hands the link over and ends */
    while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {}
    return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}
#endif
