/* nesrecomp runtime: what the Mac and Windows do differently
   (PLAN-windows.md step 2), behind the same few functions. sys.c has a
   way for each. */
#ifndef NESRECOMP_SYS_H
#define NESRECOMP_SYS_H
#include <stddef.h>

/* Where recordings and pictures go by default: ~/Movies/NES RECOMP on the
   Mac, Videos\NES RECOMP in the user's folder on Windows. */
void sys_media_dir(char *out, size_t n);
/* The character between folders in a path: '/', or '\' on Windows. */
char sys_sep(void);
/* Make a folder and those above it (no harm if they're there). */
void sys_make_dirs(const char *path);
/* Is there a file (or folder) at path? */
int sys_exists(const char *path);
/* Call handler(n) when asked to quit from outside: Ctrl+C, and on the Mac
   a quit or hang-up signal, on Windows the console closing or the user
   logging off. The handler only notes it (the runtime quits at the end
   of the frame). */
void sys_on_stop(void (*handler)(int));
/* End the program at once, without the usual tidying up. */
void sys_quit_now(int status);

#endif
