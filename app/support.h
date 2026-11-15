/* nesrecomp app: supporting it, with a donation (Ko-fi). The link is
   here once; the app menu's "Support NES RECOMP..." item, D on the About
   screen, the About box (tools/make_app_bundle.py, through
   --support-url) and the release's read-me (tools/make_release.py) all
   take it from here. */
#ifndef APP_SUPPORT_H
#define APP_SUPPORT_H
#include <stddef.h>

#define SUPPORT_URL "https://ko-fi.com/polygonlegends"
#define SUPPORT_MENU_TITLE "Support NES RECOMP\xE2\x80\xA6"     /* "...", one character */

/* Open the support page in the browser: `open URL` (or
   $NESRECOMP_OPEN URL, a stand-in for the checks). Returns its exit
   status, or -1 if it couldn't start. */
int support_open(void);
/* Add "Support NES RECOMP..." to the app menu (after "About NES RECOMP"),
   once SDL has made the menu. Returns 0, or -1 with no menu yet. */
int support_menu_add(void);
/* The app menu's item titles, one a line, into out (for the checks). */
void support_menu_titles(char *out, size_t n);
/* Do what choosing the menu's support item does. Returns -1 if there's
   no such item. */
int support_menu_choose(void);

#endif
