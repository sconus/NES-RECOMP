/* nesrecomp app: the 6502 next to its C, the data (see code.h). */
#include "code.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *slurp(const char *path, long *len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *s = malloc((size_t)n + 1);
    if (s && fread(s, 1, (size_t)n, f) != (size_t)n) { free(s); s = NULL; }
    fclose(f);
    if (s) s[n] = 0;
    if (len) *len = n;
    return s;
}

static long find(const struct code_view *v, int bank, long addr) {
    for (long i = 0; i < v->n; i++)
        if (v->insns[i].bank == bank && v->insns[i].addr == addr) return i;
    return -1;
}

int code_load(struct code_view *v, const char *listing, const char *cfile, int rows) {
    memset(v, 0, sizeof *v);
    v->rows = rows;
    long len;
    char *lst = slurp(listing, &len);
    if (!lst) return -1;
    v->c = slurp(cfile, &len);
    if (!v->c) { free(lst); return -1; }
    /* The .c's lines. */
    long cap = 1024;
    v->lines = malloc(sizeof *v->lines * (size_t)cap);
    char *p = v->c;
    while (*p) {
        if (v->n_lines == cap) v->lines = realloc(v->lines, sizeof *v->lines * (size_t)(cap *= 2));
        v->lines[v->n_lines++] = p;
        char *nl = strchr(p, '\n');
        if (!nl) break;
        *nl = 0;
        p = nl + 1;
    }
    /* The listing: the header's entries, then an instruction a line. */
    int ent_bank[64], reset_bank = -1, n_ent = 0;
    long ent_addr[64], reset_addr = -1;
    long icap = 1024;
    v->insns = malloc(sizeof *v->insns * (size_t)icap);
    for (char *line = strtok(lst, "\n"); line; line = strtok(NULL, "\n")) {
        int b;
        long a;
        if (line[0] == '#') {
            if (sscanf(line, "# reset %x:%lx", &b, &a) == 2) { reset_bank = b; reset_addr = a; }
            if ((sscanf(line, "# entry %x:%lx", &b, &a) == 2 || sscanf(line, "# init %x:%lx", &b, &a) == 2)
                && n_ent < 64) { ent_bank[n_ent] = b; ent_addr[n_ent++] = a; }
            if (sscanf(line, "# init %x:%lx", &b, &a) == 2 && reset_addr < 0) { reset_bank = b; reset_addr = a; }
            continue;
        }
        struct code_insn in = { 0 };
        char bytes[64], text[64];
        if (sscanf(line, "%x:%lx\t%ld\t%ld\t%63[^\t]\t%63[^\n]", &in.bank, &in.addr, &in.first,
                   &in.last, bytes, text) != 6) continue;
        snprintf(in.bytes, sizeof in.bytes, "%s", bytes);
        snprintf(in.text, sizeof in.text, "%s", text);
        if (v->n == icap) v->insns = realloc(v->insns, sizeof *v->insns * (size_t)(icap *= 2));
        v->insns[v->n++] = in;
    }
    free(lst);
    if (!v->n) { code_free(v); return -1; }
    /* The routines: the entries, and every JSR's target (in the JSR's
       bank, or any bank that has it). */
    for (int k = 0; k < n_ent; k++) {
        long i = find(v, ent_bank[k], ent_addr[k]);
        if (i >= 0) v->insns[i].routine = 1;
    }
    for (long j = 0; j < v->n; j++) {
        long t;
        if (sscanf(v->insns[j].text, "JSR $%lx", &t) != 1) continue;
        long i = find(v, v->insns[j].bank, t);
        for (long k = 0; i < 0 && k < v->n; k++) if (v->insns[k].addr == t) i = k;
        if (i >= 0) v->insns[i].routine = 1;
    }
    long start = reset_addr >= 0 ? find(v, reset_bank, reset_addr) : -1;
    v->cursor = v->top = start >= 0 ? start : 0;
    return 0;
}

void code_free(struct code_view *v) {
    free(v->insns);
    free(v->c);
    free(v->lines);
    memset(v, 0, sizeof *v);
}

long code_c_count(const struct code_view *v, long i) {
    const struct code_insn *in = &v->insns[i];
    if (in->first < 1 || in->last < in->first || in->last > v->n_lines) return 0;
    return in->last - in->first + 1;
}

const char *code_c_line(const struct code_view *v, long i, long k) {
    return v->lines[v->insns[i].first - 1 + k];
}

long code_rows(const struct code_view *v, long i) {
    long n = code_c_count(v, i);
    return n < 1 ? 1 : n;
}

/* Rows from the top's first row to the end of instruction i. */
static long rows_to_end(const struct code_view *v, long i) {
    long r = 0;
    for (long k = v->top; k <= i; k++) r += code_rows(v, k);
    return r;
}

void code_move(struct code_view *v, int how) {
    long c = v->cursor;
    switch (how) {
    case CODE_UP: if (c > 0) c--; break;
    case CODE_DOWN: if (c + 1 < v->n) c++; break;
    case CODE_PAGE_UP: c = c > 10 ? c - 10 : 0; break;
    case CODE_PAGE_DOWN: c = c + 10 < v->n ? c + 10 : v->n - 1; break;
    case CODE_TAB: {
        long k = c + 1;
        while (k < v->n && !v->insns[k].routine) k++;
        if (k == v->n) for (k = 0; k < c && !v->insns[k].routine; k++) {}
        if (v->insns[k].routine) { v->cursor = v->top = k; return; }
        return;
    }
    }
    v->cursor = c;
    if (c < v->top) v->top = c;
    while (v->top < c && rows_to_end(v, c) > v->rows) v->top++;
}

const char *code_english(const char *text) {
    static const char *const words[][2] = {
        { "ADC", "ADD TO A, WITH THE CARRY" }, { "AND", "AND A WITH MEMORY" },
        { "ASL", "SHIFT LEFT ONE BIT" }, { "BCC", "BRANCH IF THE CARRY IS CLEAR" },
        { "BCS", "BRANCH IF THE CARRY IS SET" }, { "BEQ", "BRANCH IF EQUAL (ZERO)" },
        { "BIT", "TEST BITS OF MEMORY WITH A" }, { "BMI", "BRANCH IF MINUS" },
        { "BNE", "BRANCH IF NOT EQUAL (NOT ZERO)" }, { "BPL", "BRANCH IF PLUS" },
        { "BRK", "BREAK: A SOFTWARE INTERRUPT" }, { "BVC", "BRANCH IF NO OVERFLOW" },
        { "BVS", "BRANCH IF OVERFLOW" }, { "CLC", "CLEAR THE CARRY" },
        { "CLD", "CLEAR DECIMAL MODE" }, { "CLI", "ALLOW INTERRUPTS" },
        { "CLV", "CLEAR THE OVERFLOW FLAG" }, { "CMP", "COMPARE A WITH MEMORY" },
        { "CPX", "COMPARE X WITH MEMORY" }, { "CPY", "COMPARE Y WITH MEMORY" },
        { "DEC", "SUBTRACT ONE FROM MEMORY" }, { "DEX", "SUBTRACT ONE FROM X" },
        { "DEY", "SUBTRACT ONE FROM Y" }, { "EOR", "EXCLUSIVE-OR A WITH MEMORY" },
        { "INC", "ADD ONE TO MEMORY" }, { "INX", "ADD ONE TO X" }, { "INY", "ADD ONE TO Y" },
        { "JMP", "JUMP" }, { "JSR", "CALL A SUBROUTINE" }, { "LDA", "LOAD A FROM MEMORY" },
        { "LDX", "LOAD X FROM MEMORY" }, { "LDY", "LOAD Y FROM MEMORY" },
        { "LSR", "SHIFT RIGHT ONE BIT" }, { "NOP", "DO NOTHING" },
        { "ORA", "OR A WITH MEMORY" }, { "PHA", "PUSH A ON THE STACK" },
        { "PHP", "PUSH THE FLAGS ON THE STACK" }, { "PLA", "PULL A FROM THE STACK" },
        { "PLP", "PULL THE FLAGS FROM THE STACK" }, { "ROL", "ROTATE LEFT THROUGH THE CARRY" },
        { "ROR", "ROTATE RIGHT THROUGH THE CARRY" }, { "RTI", "RETURN FROM AN INTERRUPT" },
        { "RTS", "RETURN FROM A SUBROUTINE" }, { "SBC", "SUBTRACT FROM A, WITH THE CARRY" },
        { "SEC", "SET THE CARRY" }, { "SED", "SET DECIMAL MODE" },
        { "SEI", "BLOCK INTERRUPTS" }, { "STA", "STORE A IN MEMORY" },
        { "STX", "STORE X IN MEMORY" }, { "STY", "STORE Y IN MEMORY" },
        { "TAX", "COPY A TO X" }, { "TAY", "COPY A TO Y" }, { "TSX", "COPY THE STACK POINTER TO X" },
        { "TXA", "COPY X TO A" }, { "TXS", "COPY X TO THE STACK POINTER" }, { "TYA", "COPY Y TO A" },
    };
    if (text[0] == '*') return "AN UNOFFICIAL OPCODE";
    for (size_t i = 0; i < sizeof words / sizeof *words; i++)
        if (!strncmp(text, words[i][0], 3)) return words[i][1];
    return "";
}
