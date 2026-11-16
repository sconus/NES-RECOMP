/* nesrecomp runtime: recording on Windows (record.h). Until PLAN-windows.md
   step 3 brings Media Foundation, a stand-in that says recording isn't
   there yet. On the Mac this file is empty: record_mac.m records. */
typedef int record_win_c;               /* (so the file is never empty) */
#ifdef _WIN32
#include <stdio.h>
#include "record.h"

int record_start(const char *path) {
    fprintf(stderr, "can't record to %s: recording isn't on Windows yet\n", path);
    return -1;
}

void record_frame(const uint16_t *framebuffer) { (void)framebuffer; }
void record_audio(const int16_t *samples, int n) { (void)samples; (void)n; }
void record_stop(void) {}
int record_active(void) { return 0; }
#endif
