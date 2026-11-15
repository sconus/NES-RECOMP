/* nesrecomp's recompiler, in C: the 6502's opcodes (recomp.py's OPS,
   SIZE, the sets of mnemonics, the C each becomes, and the cycle maps). */
#ifndef RECOMP_OPS_H
#define RECOMP_OPS_H

enum { M_IMP, M_ACC, M_IMM, M_ZP, M_ZPX, M_ZPY, M_IZX, M_IZY, M_REL, M_ABS, M_ABX, M_ABY,
       M_IND, M_COUNT };

struct op {
    int valid;
    const char *mnem;
    int mode, cyc, pen;
};

extern struct op OPS[256];
extern const char *const mode_name[M_COUNT];
extern const int SIZE[M_COUNT];

/* Fill OPS in recomp.py's order, and check every cycle map against the
   table's cycle counts (recomp.py's check_cycle_maps). */
void ops_init(void);
/* The bus cycles of an opcode, as letters (recomp.py's cycle_map). */
const char *cycle_map(const char *mnem, int mode);

/* recomp.py's sets and tables: is `m` in it, and its text. */
int is_read(const char *m);
int is_rmw(const char *m);
const char *store_value(const char *m);        /* STORES, or NULL */
const char *high_store_value(const char *m);   /* HIGH_STORES, or NULL */
const char *branch_cond(const char *m);        /* BRANCH, or NULL */
const char *read_op(const char *m);            /* READ_OPS */
const char *rmw_op(const char *m);             /* RMW_OPS */
const char *implied_op(const char *m);         /* IMPLIED, or NULL */

#endif
