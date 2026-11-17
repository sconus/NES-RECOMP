/* nesrecomp app: supporting it on Windows (support.h, PLAN-windows.md
   step 4). A Windows window has no menu bar like the Mac's, so the item
   goes in the window's own menu: the one behind its icon at the top
   left, or Alt+Space. Choosing it sends the window WM_SYSCOMMAND with
   the item's number, which the window's handler, wrapped here, takes
   before SDL's. On the Mac this file is empty: support_mac.m. */
typedef int support_win_c;              /* (so the file is never empty) */
#ifdef _WIN32
#include <SDL.h>
#include <SDL_syswm.h>
#include <windows.h>
#include <stdio.h>
#include "os.h"
#include "support.h"

/* The item's number: below 0xF000 (Windows's own) and a multiple of 16
   (Windows uses the low 4 bits). */
#define ID_SUPPORT 0x0C10

static HWND hwnd;
static WNDPROC sdl_proc;

int support_open(void) { return os_open_url(SUPPORT_URL); }

static LRESULT CALLBACK proc(HWND h, UINT m, WPARAM w, LPARAM l) {
    if (m == WM_SYSCOMMAND && (w & 0xFFF0) == ID_SUPPORT) {
        support_open();
        return 0;
    }
    return CallWindowProcW(sdl_proc, h, m, w, l);
}

int support_menu_add(void *window) {
    SDL_SysWMinfo info;
    SDL_VERSION(&info.version);
    if (!window || !SDL_GetWindowWMInfo(window, &info) || info.subsystem != SDL_SYSWM_WINDOWS) return -1;
    hwnd = info.info.win.window;
    HMENU m = GetSystemMenu(hwnd, FALSE);
    if (!m) return -1;
    if (GetMenuState(m, ID_SUPPORT, MF_BYCOMMAND) != (UINT)-1) return 0;    /* there already */
    wchar_t title[128];
    MultiByteToWideChar(CP_UTF8, 0, SUPPORT_MENU_TITLE, -1, title, 128);
    if (!AppendMenuW(m, MF_SEPARATOR, 0, NULL) || !AppendMenuW(m, MF_STRING, ID_SUPPORT, title))
        return -1;
    if (!sdl_proc) sdl_proc = (WNDPROC)SetWindowLongPtrW(hwnd, GWLP_WNDPROC, (LONG_PTR)proc);
    return 0;
}

void support_menu_titles(char *out, size_t n) {
    out[0] = 0;
    HMENU m = hwnd ? GetSystemMenu(hwnd, FALSE) : NULL;
    size_t k = 0;
    for (int i = 0; m && i < GetMenuItemCount(m); i++) {
        wchar_t w[256] = L"";
        MENUITEMINFOW it;
        memset(&it, 0, sizeof it);
        it.cbSize = sizeof it;
        it.fMask = MIIM_FTYPE | MIIM_STRING;
        it.dwTypeData = w;
        it.cch = 256;
        char t[512] = "";
        if (GetMenuItemInfoW(m, (UINT)i, TRUE, &it)) {
            if (it.fType & MFT_SEPARATOR) snprintf(t, sizeof t, "-");
            else WideCharToMultiByte(CP_UTF8, 0, w, -1, t, sizeof t, NULL, NULL);
        }
        int wr = snprintf(out + k, n - k, "%s\n", t);
        if (wr < 0 || (size_t)wr >= n - k) break;
        k += (size_t)wr;
    }
}

int support_menu_choose(void) {
    HMENU m = hwnd ? GetSystemMenu(hwnd, FALSE) : NULL;
    if (!m || GetMenuState(m, ID_SUPPORT, MF_BYCOMMAND) == (UINT)-1) return -1;
    SendMessageW(hwnd, WM_SYSCOMMAND, ID_SUPPORT, 0);    /* as choosing it does */
    return 0;
}
#endif
