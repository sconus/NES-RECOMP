/* nesrecomp app: "under the hood" (PLAN-standalone.md step 7). For each
   ROM, a history of its runs, kept as NAME.history in the build folder,
   one line a run:

       run R translated T spots S native N interp I

   T: the 6502 instructions the recompiler translated for that run's
   build (its "translated T instructions" line); S: the spots that ran in
   the interpreter during the run (the game's "S spot(s) ran in the
   interpreter" line, 0 when it has none); N and I: the instructions that
   ran as translated C and in the interpreter (its "ran N instruction(s)
   as translated C, I in the interpreter" line). A spot is a place the
   interpreter had to start, not a count of instructions; the next build
   translates those places too, so the spots shrink as you play. */
#ifndef APP_HOOD_H
#define APP_HOOD_H

struct hood_run {
    int run;
    long translated, spots;
    unsigned long long native, interp;
};

#define HOOD_MAX 1000                   /* runs read back */

/* After a game: add its run to dir/NAME.history, from its log and the
   build's translated count. Returns 0, or -1 if the log has no "ran"
   line (the game didn't end by itself: killed or crashed). */
int hood_add(const char *dir, const char *name, long translated, const char *game_log,
             struct hood_run *added);
/* The runs in a history file, oldest first; returns how many. */
int hood_load(const char *path, struct hood_run *runs, int max);
/* "99.97%" (never rounded up to 100% while anything was interpreted),
   "100%", or "-" with nothing run. */
void hood_share(const struct hood_run *r, char *out, int n);

#endif
