/* nesrecomp runtime: reading the per-opcode cycle maps. */
#include <stdio.h>
#include <stdlib.h>
#include "cycles.h"
#include "rt.h"

int check_cycles;

/* Whether the branch opcode `opc` is taken with the current flags: bits
   7-6 pick the flag (N, V, C, Z), bit 5 the value that takes it. */
static int branch_taken(uint8_t opc) {
    static uint8_t *const flag[4] = { &N, &V, &C, &Z };
    return *flag[opc >> 6] == ((opc >> 5) & 1);
}

int cycle_len(uint16_t a) {
    uint8_t opc = peek(a);
    const char *m = cycle_map[opc];
    if (!m) return -1;
    uint8_t o1 = peek(a + 1), o2 = peek(a + 2);
    /* The address an indexed mode starts from, before adding X or Y. */
    uint16_t base = o1 | o2 << 8;
    for (const char *p = m; *p; p++)
        if (*p == 'L') base = peek(o1) | peek((uint8_t)(o1 + 1)) << 8;
    int n = 0, taken = 0;
    for (const char *p = m; *p; p++) {
        switch (*p) {
        case 'x': n += ((base & 0xFF) + X) > 0xFF; break;
        case 'y': n += ((base & 0xFF) + Y) > 0xFF; break;
        case 't': taken = branch_taken(opc); n += taken; break;
        case 'c': {
            uint16_t next = a + 2, target = next + (int8_t)o1;
            n += taken && (next & 0xFF00) != (target & 0xFF00);
            break;
        }
        default: n++;
        }
    }
    return n;
}

static int started;
static int pending = -1;        /* expected length of the last instruction */
static uint16_t pending_at;
static uint64_t pending_start;
static unsigned long checked;
static uint8_t seen[256];       /* opcodes whose length has been checked */

static void report(void) {
    int kinds = 0;
    for (int i = 0; i < 256; i++) kinds += seen[i];
    fprintf(stderr, "cycle maps: %lu instruction lengths match (%d opcodes)\n",
            checked, kinds);
}

void cycle_check_step(uint16_t a) {
    if (pending >= 0) {
        uint64_t took = cycles - pending_start;
        if (took != (uint64_t)pending) {
            fprintf(stderr, "cycle map wrong: $%02X at $%04X took %llu cycles, "
                    "its map \"%s\" says %d\n", peek(pending_at), pending_at,
                    (unsigned long long)took, cycle_map[peek(pending_at)], pending);
            exit(1);
        }
        checked++;
        seen[peek(pending_at)] = 1;
    }
    if (!started) { started = 1; atexit(report); }
    pending = cycle_len(a);
    pending_at = a;
    pending_start = cycles;
}
