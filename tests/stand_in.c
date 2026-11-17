/* A stand-in program for the checks on Windows (tests/check_app.py),
   where a shell script can't stand in for one: for the browser opener
   ($NESRECOMP_OPEN), a game that crashes, and a game that fails.
     STANDIN_LOG=F     add its arguments to F, one line, as `echo "$@"` would
     STANDIN_SAY=T     print T
     STANDIN_CRASH=1   then crash (an access violation)
     STANDIN_EXIT=N    then end with status N (default 0) */
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    const char *log = getenv("STANDIN_LOG");
    if (log && *log) {
        FILE *f = fopen(log, "ab");
        if (f) {
            for (int i = 1; i < argc; i++) fprintf(f, i > 1 ? " %s" : "%s", argv[i]);
            fprintf(f, "\n");
            fclose(f);
        }
    }
    const char *say = getenv("STANDIN_SAY");
    if (say) { puts(say); fflush(stdout); }
    if (getenv("STANDIN_CRASH")) *(volatile int *)0 = 1;
    const char *e = getenv("STANDIN_EXIT");
    return e ? atoi(e) : 0;
}
