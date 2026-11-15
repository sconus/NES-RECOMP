/* nesrecomp's recompiler, in C: following the code (recomp.py's trace)
   and writing the C (generate). */
#ifndef RECOMP_GEN_H
#define RECOMP_GEN_H
#include <stdint.h>
#include <stdio.h>
#include "rom.h"

/* An instruction found, at (bank, addr). */
struct insn {
    int bank;
    long addr;
    int opc, n_operand;
    uint8_t operand[2];
};

struct traced {
    struct insn *insns;              /* sorted by (bank, addr) */
    long n_insns;
    int *unknown_bank;               /* the spots it stopped at, sorted */
    long *unknown_addr;
    long n_unknown;
};

void trace(const struct rom *r, const int *banks, const long *addrs, long n, struct traced *t);
/* Write the C for it to f, as recomp.py's generate. src_name is the ROM's
   file name, for the first line. */
void generate(FILE *f, const struct rom *r, const struct traced *t, const char *src_name);

#endif
