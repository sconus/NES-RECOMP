/* nesrecomp runtime: the game's title picture, for the app's shelf
   (PLAN-library.md step 3).

   With --title-out FILE the game keeps one picture of itself: the
   picture on screen when Start is first pressed (on any controller, or
   by an input script), which is almost always the title screen. A
   picture that is (nearly) all one colour doesn't count, so a press on
   a black screen waits for the next. If Start isn't pressed in the first
   30 seconds (1800 frames), it keeps the picture at 10 seconds (frame
   600), or the first one after it that isn't one colour; and if the
   game ends before then, that one too. It is written once, and then it
   stops looking. It only reads the finished picture, never the game's
   memory or timing, so the game plays exactly as without it.

   FILE: "NRTITLE1", the width and height (2 bytes each, low byte
   first: 256 and 240), then the picture as red, green, blue bytes, row
   by row (the app reads it with no PNG reader). */
#ifndef NESRECOMP_TITLE_H
#define NESRECOMP_TITLE_H
#include <stdint.h>

#define TITLE_FALLBACK 600              /* 10 seconds */
#define TITLE_LAST 1800                 /* 30 seconds: Start counts until here */

/* Start looking, for FILE (--title-out). */
void title_start(const char *path);
/* Each frame: its picture, its number, and whether Start is among the
   buttons for the next frame (any controller). */
void title_frame(const uint16_t *fb, long frame, int start_held);
/* At the end of the run: the 10-second picture, if it's all there is. */
void title_finish(void);
/* The self-test (--test-title): made-up pictures and presses. 0 when
   all pass. */
int title_test(const char *scratch_dir);

#endif
