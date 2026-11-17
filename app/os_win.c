/* nesrecomp app: Windows's ways (os.h, PLAN-windows.md step 4). Text is
   UTF-8 inside the app (as SDL hands it over), turned into Windows's
   wide characters at each call, so names in any alphabet get through.
   On the Mac this file is empty: os_mac.c. */
typedef int os_win_c;                   /* (so the file is never empty) */
#ifdef _WIN32
#define COBJMACROS
#include <windows.h>
#include <commdlg.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "os.h"

#define WMAX 4096

static int widen(const char *s, wchar_t *out, int n) {
    return MultiByteToWideChar(CP_UTF8, 0, s, -1, out, n) > 0;
}

static void narrow(const wchar_t *s, char *out, size_t n) {
    if (!WideCharToMultiByte(CP_UTF8, 0, s, -1, out, (int)n, NULL, NULL) && n) out[0] = 0;
}

/* One argument for a Windows command line, quoted as programs built
   with the usual C library read it back: in quotes if it has a space, a
   tab or a quote (or is empty), a quote as \", and the backslashes
   before a quote (or the closing one) doubled. */
static void quote(wchar_t *cmd, size_t *k, size_t n, const wchar_t *a) {
#define PUT(c) do { if (*k + 1 < n) cmd[(*k)++] = (c); } while (0)
    int q = !*a || wcspbrk(a, L" \t\"") != NULL;
    if (*k) PUT(L' ');
    if (!q) { for (; *a; a++) PUT(*a); cmd[*k] = 0; return; }
    PUT(L'"');
    for (;; a++) {
        int bs = 0;
        while (*a == L'\\') { a++; bs++; }
        if (!*a) { for (int i = 0; i < bs * 2; i++) PUT(L'\\'); break; }
        if (*a == L'"') { for (int i = 0; i < bs * 2 + 1; i++) PUT(L'\\'); PUT(L'"'); }
        else { for (int i = 0; i < bs; i++) PUT(L'\\'); PUT(*a); }
    }
    PUT(L'"');
    cmd[*k] = 0;
#undef PUT
}

os_proc os_start(char *const argv[], const char *log, int append) {
    static wchar_t cmd[32768];
    wchar_t w[WMAX];
    size_t k = 0;
    cmd[0] = 0;
    for (int i = 0; argv[i]; i++) {
        if (!widen(argv[i], w, WMAX)) return -1;
        quote(cmd, &k, sizeof cmd / sizeof *cmd, w);
    }
    SECURITY_ATTRIBUTES sa = { sizeof sa, NULL, TRUE };     /* handed to the program */
    if (!widen(log ? log : "NUL", w, WMAX)) return -1;
    HANDLE out = CreateFileW(w, append ? FILE_APPEND_DATA : GENERIC_WRITE,
                             FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, &sa,
                             append ? OPEN_ALWAYS : CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (out == INVALID_HANDLE_VALUE) return -1;
    HANDLE in = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa,
                            OPEN_EXISTING, 0, NULL);
    STARTUPINFOW si;
    memset(&si, 0, sizeof si);
    si.cb = sizeof si;
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = in;
    si.hStdOutput = si.hStdError = out;
    PROCESS_INFORMATION pi;
    /* No console window for the tools or the game (its own window is
       SDL's); a bare name is looked for on PATH, as Windows does. */
    BOOL ok = CreateProcessW(NULL, cmd, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi);
    CloseHandle(out);
    if (in != INVALID_HANDLE_VALUE) CloseHandle(in);
    if (!ok) return -1;
    CloseHandle(pi.hThread);
    return (os_proc)pi.hProcess;
}

static const char *exception_name(DWORD c) {
    switch (c) {
    case 0xC0000005: return "an access violation";
    case 0xC000001D: return "an illegal instruction";
    case 0xC0000094: return "a division by zero";
    case 0xC00000FD: return "a stack overflow";
    case 0xC0000135: return "a DLL it needs is missing";
    case 0xC0000139: return "a DLL it needs is the wrong one";
    case 0xC0000409: return "a broken stack";
    case 0xC000013A: return "Ctrl+C";
    default: return "an exception";
    }
}

int os_poll(os_proc p, int wait, int *code, char *crash, size_t n) {
    HANDLE h = (HANDLE)p;
    if (crash && n) crash[0] = 0;
    DWORD r = WaitForSingleObject(h, wait ? INFINITE : 0);
    if (r == WAIT_TIMEOUT) return 0;
    DWORD c = 0;
    if (r != WAIT_OBJECT_0 || !GetExitCodeProcess(h, &c)) {
        CloseHandle(h);
        *code = -1;
        if (crash) snprintf(crash, n, "lost track of it");
        return 1;
    }
    CloseHandle(h);
    if (c >= 0xC0000000u) {             /* a Windows exception: it crashed */
        *code = -1;
        if (crash) snprintf(crash, n, "exception 0x%08lX, %s", (unsigned long)c, exception_name(c));
        return 1;
    }
    *code = (int)c;
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

static DWORD WINAPI thread_main(LPVOID a) {
    struct thread_job j = *(struct thread_job *)a;
    free(a);
    j.fn(j.arg);
    return 0;
}

int os_thread(void (*fn)(void *), void *arg) {
    struct thread_job *j = malloc(sizeof *j);
    if (!j) return -1;
    j->fn = fn;
    j->arg = arg;
    HANDLE t = CreateThread(NULL, 0, thread_main, j, 0, NULL);
    if (!t) { free(j); return -1; }
    CloseHandle(t);
    return 0;
}

double os_now(void) {
    LARGE_INTEGER f, c;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&c);
    return (double)c.QuadPart / (double)f.QuadPart;
}

void os_setenv(const char *name, const char *value) {
    wchar_t wn[256], wv[WMAX];               /* what CreateProcessW passes on */
    if (widen(name, wn, 256) && widen(value, wv, WMAX)) SetEnvironmentVariableW(wn, wv);
}

int os_exe_path(char *out, size_t n) {
    wchar_t w[WMAX];
    DWORD len = GetModuleFileNameW(NULL, w, WMAX);
    if (!len || len >= WMAX) return -1;
    narrow(w, out, n);
    return out[0] ? 0 : -1;
}

int os_real_path(const char *path, char *out, size_t n) {
    wchar_t w[WMAX], full[WMAX];
    if (!widen(path, w, WMAX)) return -1;
    DWORD len = GetFullPathNameW(w, WMAX, full, NULL);
    if (!len || len >= WMAX || GetFileAttributesW(full) == INVALID_FILE_ATTRIBUTES) return -1;
    narrow(full, out, n);
    return 0;
}

void os_app_dir(char *out, size_t n) {
    const wchar_t *local = _wgetenv(L"LOCALAPPDATA");
    char base[WMAX] = "";
    if (local && *local) narrow(local, base, sizeof base);
    else {
        const wchar_t *home = _wgetenv(L"USERPROFILE");
        char h[WMAX] = "C:";
        if (home && *home) narrow(home, h, sizeof h);
        snprintf(base, sizeof base, "%s\\AppData\\Local", h);
    }
    snprintf(out, n, "%s\\NES RECOMP", base);
}

const char *os_last_sep(const char *path) {
    const char *a = strrchr(path, '/'), *b = strrchr(path, '\\');
    return a > b ? a : b;
}

const char *os_exe_ext(void) { return ".exe"; }

static DWORD attrs(const char *path) {
    wchar_t w[WMAX];
    return widen(path, w, WMAX) ? GetFileAttributesW(w) : INVALID_FILE_ATTRIBUTES;
}

int os_exists(const char *path) { return attrs(path) != INVALID_FILE_ATTRIBUTES; }

int os_can_run(const char *path) {
    DWORD a = attrs(path);
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

int os_can_write(const char *dir) {
    /* Windows's permissions are only known by trying: a file made there
       and gone again. */
    char p[WMAX];
    wchar_t w[WMAX];
    snprintf(p, sizeof p, "%s\\.nesrecomp-write-test", dir);
    if (!widen(p, w, WMAX)) return 0;
    HANDLE h = CreateFileW(w, GENERIC_WRITE, 0, NULL, CREATE_NEW,
                           FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, NULL);
    if (h == INVALID_HANDLE_VALUE) return 0;
    CloseHandle(h);
    return 1;
}

static int info(const char *path, WIN32_FILE_ATTRIBUTE_DATA *d) {
    wchar_t w[WMAX];
    return widen(path, w, WMAX) && GetFileAttributesExW(w, GetFileExInfoStandard, d);
}

double os_mtime(const char *path) {
    WIN32_FILE_ATTRIBUTE_DATA d;
    if (!info(path, &d)) return -1;
    ULARGE_INTEGER t = { .LowPart = d.ftLastWriteTime.dwLowDateTime,
                         .HighPart = d.ftLastWriteTime.dwHighDateTime };
    return t.QuadPart / 1e7;            /* 100 ns steps since 1601 */
}

long os_size(const char *path) {
    WIN32_FILE_ATTRIBUTE_DATA d;
    return info(path, &d) ? (long)d.nFileSizeLow : 0;
}

void os_mkdir(const char *path) {
    wchar_t w[WMAX];
    if (widen(path, w, WMAX)) CreateDirectoryW(w, NULL);
}

void os_make_dirs(const char *path) {
    char part[WMAX];
    snprintf(part, sizeof part, "%s", path);
    char *p = part;
    if (p[0] && p[1] == ':') p += 2;                    /* C: */
    else if ((p[0] == '\\' || p[0] == '/') && (p[1] == '\\' || p[1] == '/')) {
        p += 2;                                         /* \\server\share\ */
        for (int k = 0; k < 2 && *p; p++) if (*p == '\\' || *p == '/') k++;
    }
    for (p++; *p; p++)
        if (*p == '/' || *p == '\\') { char c = *p; *p = 0; os_mkdir(part); *p = c; }
    os_mkdir(part);
}

void os_remove(const char *path) {
    wchar_t w[WMAX];
    if (widen(path, w, WMAX)) DeleteFileW(w);
}

int os_copy(const char *from, const char *to) {
    char tmp[WMAX];
    wchar_t wf[WMAX], wt[WMAX], wtmp[WMAX];
    snprintf(tmp, sizeof tmp, "%s.new", to);
    if (!widen(from, wf, WMAX) || !widen(to, wt, WMAX) || !widen(tmp, wtmp, WMAX)) return -1;
    /* (CopyFile keeps the file's time.) */
    if (!CopyFileW(wf, wtmp, FALSE) || !MoveFileExW(wtmp, wt, MOVEFILE_REPLACE_EXISTING)) {
        DeleteFileW(wtmp);
        return -1;
    }
    return 0;
}

int os_list(const char *dir, void (*each)(const char *name, void *arg), void *arg) {
    char pat[WMAX];
    wchar_t w[WMAX];
    snprintf(pat, sizeof pat, "%s\\*", dir);
    if (!widen(pat, w, WMAX)) return -1;
    WIN32_FIND_DATAW f;
    HANDLE h = FindFirstFileW(w, &f);
    if (h == INVALID_HANDLE_VALUE) return -1;
    do {
        char name[1024];
        narrow(f.cFileName, name, sizeof name);
        if (name[0] && name[0] != '.') each(name, arg);
    } while (FindNextFileW(h, &f));
    FindClose(h);
    return 0;
}

int os_pick_file(char *out, size_t n) {
    /* Windows's own "Open" box (it needs COM, on this thread). */
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    wchar_t file[WMAX] = L"";
    OPENFILENAMEW o;
    memset(&o, 0, sizeof o);
    o.lStructSize = sizeof o;
    o.lpstrFilter = L"NES ROMs, NSF and FDS files (*.nes, *.nsf, *.fds)\0*.nes;*.nsf;*.fds\0"
                    L"All files\0*.*\0";
    o.lpstrFile = file;
    o.nMaxFile = WMAX;
    o.lpstrTitle = L"Choose an NES ROM, NSF or FDS file";
    o.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR | OFN_EXPLORER;
    int got = GetOpenFileNameW(&o) != 0;
    CoUninitialize();
    if (!got) return 0;
    narrow(file, out, n);
    return out[0] != 0;
}

int os_open_url(const char *url) {
    const char *open = getenv("NESRECOMP_OPEN");        /* for the checks */
    if (open && *open) {
        char *argv[] = { (char *)open, (char *)url, NULL };
        return os_run(argv, NULL);
    }
    wchar_t w[WMAX];
    if (!widen(url, w, WMAX)) return -1;
    return (INT_PTR)ShellExecuteW(NULL, L"open", w, NULL, NULL, SW_SHOWNORMAL) > 32 ? 0 : -1;
}
#endif
