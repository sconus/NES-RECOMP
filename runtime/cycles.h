/* nesrecomp runtime: per-cycle bus maps of each opcode (generated into the
   program by recomp.py, see CYCLE_KEY there). */
#ifndef NESRECOMP_CYCLES_H
#define NESRECOMP_CYCLES_H
#include <stdint.h>

extern const char *const cycle_map[256];

/* How many cycles the instruction at `a` will take with the registers as
   they are now, counting page-cross and taken-branch cycles. Reads memory
   without side effects. -1 for an opcode with no map. */
int cycle_len(uint16_t a);

/* --check-cycles: compare every instruction's length from its map with
   the cycles it really took (called from trace_step). */
extern int check_cycles;
void cycle_check_step(uint16_t a);

#endif
