/* nesrecomp app: "the 6502 next to its C" (PLAN-standalone.md step 8).
   A game's listing (the recompiler's --listing: each instruction's
   bank, address, bytes, 6502 text and the lines of the .c it became)
   and its .c, read for the view, and moving around them. Drawing is in
   app.c. */
#ifndef APP_CODE_H
#define APP_CODE_H

struct code_insn {
    int bank;
    long addr;
    long first, last;                   /* its lines in the .c, from 1 */
    char bytes[12], text[32];
    int routine;                        /* a JSR's target, or an entry */
};

struct code_view {
    struct code_insn *insns;
    long n;
    char *c;                            /* the .c, its lines split at '\0' */
    char **lines;
    long n_lines;
    long cursor, top;                   /* instruction indexes */
    int rows;                           /* screen rows for instructions */
};

/* Read a listing and its .c; the cursor at the reset routine (or the
   first instruction). Returns 0, or -1 if either can't be read. */
int code_load(struct code_view *v, const char *listing, const char *cfile, int rows);
void code_free(struct code_view *v);
/* An instruction's C lines: how many, and the k-th (from 0). */
long code_c_count(const struct code_view *v, long i);
const char *code_c_line(const struct code_view *v, long i, long k);
/* Rows an instruction takes: its C lines, at least 1. */
long code_rows(const struct code_view *v, long i);
/* Moves: up and down an instruction, a page, Tab to the next routine
   (each JSR's target, and the entries), wrapping to the first. The
   cursor stays on screen: above the top, it becomes the top; below the
   last row, the top moves down until it fits. Tab puts the routine at
   the top. */
enum { CODE_UP, CODE_DOWN, CODE_PAGE_UP, CODE_PAGE_DOWN, CODE_TAB };
void code_move(struct code_view *v, int how);
/* A line of plain English for a 6502 mnemonic ("LOAD A FROM MEMORY"). */
const char *code_english(const char *text);

#endif
