/* nesrecomp app: "under the hood", the run history (see hood.h). */
#include "hood.h"
#include <limits.h>
#include <stdio.h>
#include <string.h>

int hood_load(const char *path, struct hood_run *runs, int max) {
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    char line[256];
    int n = 0;
    while (fgets(line, sizeof line, f)) {
        struct hood_run r;
        if (sscanf(line, "run %d translated %ld spots %ld native %llu interp %llu",
                   &r.run, &r.translated, &r.spots, &r.native, &r.interp) != 5) continue;
        if (n < max) runs[n++] = r;
        else {                                  /* keep the latest max */
            memmove(runs, runs + 1, (size_t)(max - 1) * sizeof *runs);
            runs[max - 1] = r;
        }
    }
    fclose(f);
    return n;
}

int hood_add(const char *dir, const char *name, long translated, const char *game_log,
             struct hood_run *added) {
    FILE *g = fopen(game_log, "r");
    if (!g) return -1;
    char line[512];
    long spots = 0;
    unsigned long long native = 0, interp = 0;
    int ran = 0;
    while (fgets(line, sizeof line, g)) {
        long s;
        unsigned long long a, b;
        if (sscanf(line, "%ld spot(s) ran in the interpreter", &s) == 1 &&
            strstr(line, "spot(s) ran in the interpreter")) spots = s;
        else if (sscanf(line, "ran %llu instruction(s) as translated C, %llu in the interpreter",
                        &a, &b) == 2) {
            native = a;
            interp = b;
            ran = 1;
        }
    }
    fclose(g);
    if (!ran) return -1;
    char path[PATH_MAX];
    snprintf(path, sizeof path, "%s/%s.history", dir, name);
    static struct hood_run runs[HOOD_MAX];
    int n = hood_load(path, runs, HOOD_MAX);
    struct hood_run r = { n ? runs[n - 1].run + 1 : 1, translated, spots, native, interp };
    FILE *f = fopen(path, "a");
    if (!f) return -1;
    fprintf(f, "run %d translated %ld spots %ld native %llu interp %llu\n",
            r.run, r.translated, r.spots, r.native, r.interp);
    fclose(f);
    if (added) *added = r;
    return 0;
}

void hood_share(const struct hood_run *r, char *out, int n) {
    unsigned long long total = r->native + r->interp;
    if (!total) { snprintf(out, (size_t)n, "-"); return; }
    if (!r->interp) { snprintf(out, (size_t)n, "100%%"); return; }
    /* Hundredths of a percent, rounded down: 99.999% shows as 99.99%. */
    unsigned long long h = r->native * 10000ull / total;
    snprintf(out, (size_t)n, "%llu.%02llu%%", h / 100, h % 100);
}
