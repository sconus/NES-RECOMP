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
   file name, for the first line. With a listing file (PLAN-standalone.md
   step 8; recomp.py has none), also write there, for each instruction,
   one line, tab-separated:
       BB:AAAA  FIRST  LAST  BYTES  TEXT
   its bank and address, the lines of the .c it became (from 1: FIRST
   holds its label), its bytes ("AD 02 20") and its 6502 text ("LDA
   $2002", unofficial opcodes starred as in nestest.log: "*NOP $A9"). The
   C written to f is the same either way. */
void generate(FILE *f, const struct rom *r, const struct traced *t, const char *src_name,
              FILE *listing);
/* An instruction's 6502 text, as above. */
void disasm(const struct insn *in, char *out, size_t n);

#endif
