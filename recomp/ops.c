/* nesrecomp's recompiler, in C: the 6502's opcodes (see ops.h). Built in
   the same order as recomp.py's, so a later entry replaces an earlier one
   exactly as there. */
#include "ops.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct op OPS[256];
const char *const mode_name[M_COUNT] = { "imp", "acc", "imm", "zp", "zpx", "zpy", "izx",
                                         "izy", "rel", "abs", "abx", "aby", "ind" };
const int SIZE[M_COUNT] = { 1, 1, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3 };

static void op(int code, const char *mnem, int mode, int cyc, int pen) {
    OPS[code].valid = 1;
    OPS[code].mnem = mnem;
    OPS[code].mode = mode;
    OPS[code].cyc = cyc;
    OPS[code].pen = pen;
}

struct pair { const char *k, *v; };

static const char *find(const struct pair *t, const char *m) {
    for (; t->k; t++)
        if (!strcmp(t->k, m)) return t->v;
    return NULL;
}

static const char *const READS[] = { "ORA", "AND", "EOR", "ADC", "SBC", "LDA", "LDX", "LDY",
                                     "CMP", "CPX", "CPY", "BIT", "LAX", "NOP", "ANC", "ALR",
                                     "ARR", "AXS", "XAA", "LXA", "LAS", NULL };
static const char *const RMW[] = { "ASL", "LSR", "ROL", "ROR", "INC", "DEC", "SLO", "RLA",
                                   "SRE", "RRA", "DCP", "ISB", NULL };
static const struct pair STORES[] = {
    { "STA", "A" }, { "STX", "X" }, { "STY", "Y" }, { "SAX", "(A & X)" }, { NULL, NULL } };
static const struct pair HIGH_STORES[] = {
    { "SHY", "Y" }, { "SHX", "X" }, { "AHX", "(A & X)" }, { "TAS", "SP" }, { NULL, NULL } };
static const struct pair BRANCH[] = {
    { "BPL", "!N" }, { "BMI", "N" }, { "BVC", "!V" }, { "BVS", "V" },
    { "BCC", "!C" }, { "BCS", "C" }, { "BNE", "!Z" }, { "BEQ", "Z" }, { NULL, NULL } };
static const struct pair READ_OPS[] = {
    { "ORA", "A |= v; setzn(A);" },
    { "AND", "A &= v; setzn(A);" },
    { "EOR", "A ^= v; setzn(A);" },
    { "ADC", "adc(v);" },
    { "SBC", "adc(v ^ 0xFF);" },
    { "LDA", "A = v; setzn(A);" },
    { "LDX", "X = v; setzn(X);" },
    { "LDY", "Y = v; setzn(Y);" },
    { "LAX", "A = X = v; setzn(A);" },
    { "CMP", "cmp(A, v);" },
    { "CPX", "cmp(X, v);" },
    { "CPY", "cmp(Y, v);" },
    { "BIT", "Z = (A & v) == 0; N = v >> 7; V = (v >> 6) & 1;" },
    { "NOP", "(void)v;" },
    { "ANC", "A &= v; setzn(A); C = N;" },
    { "ALR", "A &= v; A = lsr(A);" },
    { "ARR", "A &= v; A = (uint8_t)(A >> 1 | C << 7); setzn(A); "
             "C = (A >> 6) & 1; V = C ^ ((A >> 5) & 1);" },
    { "AXS", "{ uint8_t ax = A & X; C = ax >= v; X = (uint8_t)(ax - v); setzn(X); }" },
    /* XAA and LXA mix in "magic" bits that vary between consoles; $FF is
       the value the instr_test-v5 ROMs expect for LXA. */
    { "XAA", "A = (A | 0xFF) & X & v; setzn(A);" },
    { "LXA", "A = X = (A | 0xFF) & v; setzn(A);" },
    { "LAS", "A = X = SP = v & SP; setzn(A);" },
    { NULL, NULL } };
static const struct pair RMW_OPS[] = {
    { "ASL", "v = asl(v);" },
    { "LSR", "v = lsr(v);" },
    { "ROL", "v = rol(v);" },
    { "ROR", "v = ror(v);" },
    { "INC", "v++; setzn(v);" },
    { "DEC", "v--; setzn(v);" },
    { "SLO", "v = asl(v); A |= v; setzn(A);" },
    { "RLA", "v = rol(v); A &= v; setzn(A);" },
    { "SRE", "v = lsr(v); A ^= v; setzn(A);" },
    { "RRA", "v = ror(v); adc(v);" },
    { "DCP", "v--; cmp(A, v);" },
    { "ISB", "v++; adc(v ^ 0xFF);" },
    { NULL, NULL } };
static const struct pair IMPLIED[] = {
    { "CLC", "C = 0;" }, { "SEC", "C = 1;" },
    { "CLI", "{ uint8_t oi = I; I = 0; cpu_i_change(oi, 2); }" },
    { "SEI", "{ uint8_t oi = I; I = 1; cpu_i_change(oi, 2); }" },
    { "CLV", "V = 0;" }, { "CLD", "D = 0;" }, { "SED", "D = 1;" },
    { "TAX", "X = A; setzn(X);" }, { "TAY", "Y = A; setzn(Y);" },
    { "TSX", "X = SP; setzn(X);" }, { "TXA", "A = X; setzn(A);" },
    { "TXS", "SP = X;" }, { "TYA", "A = Y; setzn(A);" },
    { "DEX", "X--; setzn(X);" }, { "DEY", "Y--; setzn(Y);" },
    { "INX", "X++; setzn(X);" }, { "INY", "Y++; setzn(Y);" },
    { "NOP", "" },
    { "PHA", "push(A);" }, { "PHP", "push(getP(1));" },
    { "PLA", "A = pop(); setzn(A);" },
    { "PLP", "{ uint8_t oi = I; setP(pop()); cpu_i_change(oi, 4); }" },
    { NULL, NULL } };

static int in(const char *const *set, const char *m) {
    for (; *set; set++)
        if (!strcmp(*set, m)) return 1;
    return 0;
}

int is_read(const char *m) { return in(READS, m); }
int is_rmw(const char *m) { return in(RMW, m); }
const char *store_value(const char *m) { return find(STORES, m); }
const char *high_store_value(const char *m) { return find(HIGH_STORES, m); }
const char *branch_cond(const char *m) { return find(BRANCH, m); }
const char *read_op(const char *m) { return find(READ_OPS, m); }
const char *rmw_op(const char *m) { return find(RMW_OPS, m); }
const char *implied_op(const char *m) { return find(IMPLIED, m); }

/* The cycle map's letters (recomp.py's CYCLE_KEY) and the optional ones. */
static const char KEY_LETTERS[] = "F12nzLHdxyrwmsuUjkvVtc";
static const char OPTIONAL[] = "xytc";

const char *cycle_map(const char *mnem, int mode) {
    static const struct { const char *mnem; int mode; const char *map; } special[] = {
        { "JMP", M_ABS, "F12" }, { "JMP", M_IND, "F12LH" }, { "JSR", M_ABS, "F1jUU2" },
        { "RTS", M_IMP, "Fnsuuk" }, { "RTI", M_IMP, "Fnsuuu" }, { "BRK", M_IMP, "F1UUUvV" },
        { "PHA", M_IMP, "FnU" }, { "PHP", M_IMP, "FnU" },
        { "PLA", M_IMP, "Fnsu" }, { "PLP", M_IMP, "Fnsu" },
    };
    static char buf[16];
    int is_special = 0;
    for (size_t i = 0; i < sizeof special / sizeof special[0]; i++)
        if (!strcmp(special[i].mnem, mnem)) {
            is_special = 1;
            if (special[i].mode == mode) return special[i].map;
        }
    if (is_special) {
        fprintf(stderr, "no cycle map for %s %s\n", mnem, mode_name[mode]);
        exit(1);
    }
    if (mode == M_IMP || mode == M_ACC) return "Fn";
    if (mode == M_IMM) return "F1";
    if (mode == M_REL) return "F1tc";
    const char *access;
    if (is_read(mnem)) access = "r";
    else if (is_rmw(mnem)) access = "rmw";
    else if (store_value(mnem) || high_store_value(mnem)) access = "w";
    else {
        fprintf(stderr, "no cycle map for %s %s\n", mnem, mode_name[mode]);
        exit(1);
    }
    /* Indexed reads only spend the fix-up cycle on a page cross; writes
       and read-modify-writes always do. */
    const char *fix = mode == M_ABX ? "x" : mode == M_ABY || mode == M_IZY ? "y" : "";
    if (*fix && strcmp(access, "r")) fix = "d";
    const char *prefix;
    switch (mode) {
    case M_ZP: prefix = "F1"; break;
    case M_ZPX: case M_ZPY: prefix = "F1z"; break;
    case M_ABS: case M_ABX: case M_ABY: prefix = "F12"; break;
    case M_IZX: prefix = "F1zLH"; break;
    case M_IZY: prefix = "F1LH"; break;
    default:
        fprintf(stderr, "no cycle map for %s %s\n", mnem, mode_name[mode]);
        exit(1);
    }
    snprintf(buf, sizeof buf, "%s%s%s", prefix, fix, access);
    return buf;
}

static void check_cycle_maps(void) {
    for (int opc = 0; opc < 256; opc++) {
        if (!OPS[opc].valid) continue;
        const struct op *o = &OPS[opc];
        const char *m = cycle_map(o->mnem, o->mode);
        int fixed = 0;
        char optional[8] = "";
        for (const char *c = m; *c; c++) {
            if (!strchr(KEY_LETTERS, *c)) {
                fprintf(stderr, "$%02X: unknown letter in %s\n", opc, m);
                exit(1);
            }
            if (strchr(OPTIONAL, *c)) strncat(optional, c, 1);
            else fixed++;
        }
        const char *want = o->mode == M_REL ? "tc" : o->pen ? (o->mode == M_ABX ? "x" : "y") : "";
        if (fixed != o->cyc || strcmp(optional, want)) {
            fprintf(stderr, "$%02X %s %s: map %s doesn't fit the table's cycles\n", opc, o->mnem,
                    mode_name[o->mode], m);
            exit(1);
        }
    }
}

void ops_init(void) {
    static const struct { int base; const char *m; } g1[] = {
        { 0x00, "ORA" }, { 0x20, "AND" }, { 0x40, "EOR" }, { 0x60, "ADC" },
        { 0xA0, "LDA" }, { 0xC0, "CMP" }, { 0xE0, "SBC" } };
    for (int i = 0; i < 7; i++) {
        int b = g1[i].base;
        const char *m = g1[i].m;
        op(b + 0x09, m, M_IMM, 2, 0);
        op(b + 0x05, m, M_ZP, 3, 0);
        op(b + 0x15, m, M_ZPX, 4, 0);
        op(b + 0x0D, m, M_ABS, 4, 0);
        op(b + 0x1D, m, M_ABX, 4, 1);
        op(b + 0x19, m, M_ABY, 4, 1);
        op(b + 0x01, m, M_IZX, 6, 0);
        op(b + 0x11, m, M_IZY, 5, 1);
    }
    op(0x85, "STA", M_ZP, 3, 0); op(0x95, "STA", M_ZPX, 4, 0); op(0x8D, "STA", M_ABS, 4, 0);
    op(0x9D, "STA", M_ABX, 5, 0); op(0x99, "STA", M_ABY, 5, 0);
    op(0x81, "STA", M_IZX, 6, 0); op(0x91, "STA", M_IZY, 6, 0);

    static const struct { int base; const char *m; } sh[] = {
        { 0x00, "ASL" }, { 0x20, "ROL" }, { 0x40, "LSR" }, { 0x60, "ROR" } };
    for (int i = 0; i < 4; i++) {
        int b = sh[i].base;
        op(b + 0x0A, sh[i].m, M_ACC, 2, 0);
        op(b + 0x06, sh[i].m, M_ZP, 5, 0);
        op(b + 0x16, sh[i].m, M_ZPX, 6, 0);
        op(b + 0x0E, sh[i].m, M_ABS, 6, 0);
        op(b + 0x1E, sh[i].m, M_ABX, 7, 0);
    }
    static const struct { int base; const char *m; } id[] = { { 0xE0, "INC" }, { 0xC0, "DEC" } };
    for (int i = 0; i < 2; i++) {
        int b = id[i].base;
        op(b + 0x06, id[i].m, M_ZP, 5, 0); op(b + 0x16, id[i].m, M_ZPX, 6, 0);
        op(b + 0x0E, id[i].m, M_ABS, 6, 0); op(b + 0x1E, id[i].m, M_ABX, 7, 0);
    }

    op(0xA2, "LDX", M_IMM, 2, 0); op(0xA6, "LDX", M_ZP, 3, 0); op(0xB6, "LDX", M_ZPY, 4, 0);
    op(0xAE, "LDX", M_ABS, 4, 0); op(0xBE, "LDX", M_ABY, 4, 1);
    op(0xA0, "LDY", M_IMM, 2, 0); op(0xA4, "LDY", M_ZP, 3, 0); op(0xB4, "LDY", M_ZPX, 4, 0);
    op(0xAC, "LDY", M_ABS, 4, 0); op(0xBC, "LDY", M_ABX, 4, 1);
    op(0x86, "STX", M_ZP, 3, 0); op(0x96, "STX", M_ZPY, 4, 0); op(0x8E, "STX", M_ABS, 4, 0);
    op(0x84, "STY", M_ZP, 3, 0); op(0x94, "STY", M_ZPX, 4, 0); op(0x8C, "STY", M_ABS, 4, 0);
    op(0xE0, "CPX", M_IMM, 2, 0); op(0xE4, "CPX", M_ZP, 3, 0); op(0xEC, "CPX", M_ABS, 4, 0);
    op(0xC0, "CPY", M_IMM, 2, 0); op(0xC4, "CPY", M_ZP, 3, 0); op(0xCC, "CPY", M_ABS, 4, 0);
    op(0x24, "BIT", M_ZP, 3, 0); op(0x2C, "BIT", M_ABS, 4, 0);

    static const struct { int code; const char *m; } br[] = {
        { 0x10, "BPL" }, { 0x30, "BMI" }, { 0x50, "BVC" }, { 0x70, "BVS" },
        { 0x90, "BCC" }, { 0xB0, "BCS" }, { 0xD0, "BNE" }, { 0xF0, "BEQ" } };
    for (int i = 0; i < 8; i++) op(br[i].code, br[i].m, M_REL, 2, 0);

    op(0x4C, "JMP", M_ABS, 3, 0); op(0x6C, "JMP", M_IND, 5, 0); op(0x20, "JSR", M_ABS, 6, 0);
    op(0x60, "RTS", M_IMP, 6, 0); op(0x40, "RTI", M_IMP, 6, 0); op(0x00, "BRK", M_IMP, 7, 0);

    static const struct { int code; const char *m; } imp[] = {
        { 0x18, "CLC" }, { 0x38, "SEC" }, { 0x58, "CLI" }, { 0x78, "SEI" },
        { 0xB8, "CLV" }, { 0xD8, "CLD" }, { 0xF8, "SED" }, { 0xAA, "TAX" },
        { 0xA8, "TAY" }, { 0xBA, "TSX" }, { 0x8A, "TXA" }, { 0x9A, "TXS" },
        { 0x98, "TYA" }, { 0xCA, "DEX" }, { 0x88, "DEY" }, { 0xE8, "INX" },
        { 0xC8, "INY" }, { 0xEA, "NOP" } };
    for (int i = 0; i < 18; i++) op(imp[i].code, imp[i].m, M_IMP, 2, 0);
    op(0x48, "PHA", M_IMP, 3, 0); op(0x08, "PHP", M_IMP, 3, 0);
    op(0x68, "PLA", M_IMP, 4, 0); op(0x28, "PLP", M_IMP, 4, 0);

    /* Commonly used "unofficial" opcodes. */
    static const int nop1[] = { 0x1A, 0x3A, 0x5A, 0x7A, 0xDA, 0xFA };
    for (int i = 0; i < 6; i++) op(nop1[i], "NOP", M_IMP, 2, 0);
    static const int nop2[] = { 0x80, 0x82, 0x89, 0xC2, 0xE2 };
    for (int i = 0; i < 5; i++) op(nop2[i], "NOP", M_IMM, 2, 0);
    static const int nopz[] = { 0x04, 0x44, 0x64 };
    for (int i = 0; i < 3; i++) op(nopz[i], "NOP", M_ZP, 3, 0);
    static const int nopzx[] = { 0x14, 0x34, 0x54, 0x74, 0xD4, 0xF4 };
    for (int i = 0; i < 6; i++) op(nopzx[i], "NOP", M_ZPX, 4, 0);
    op(0x0C, "NOP", M_ABS, 4, 0);
    static const int nopax[] = { 0x1C, 0x3C, 0x5C, 0x7C, 0xDC, 0xFC };
    for (int i = 0; i < 6; i++) op(nopax[i], "NOP", M_ABX, 4, 1);
    op(0xA3, "LAX", M_IZX, 6, 0); op(0xA7, "LAX", M_ZP, 3, 0); op(0xAF, "LAX", M_ABS, 4, 0);
    op(0xB3, "LAX", M_IZY, 5, 1); op(0xB7, "LAX", M_ZPY, 4, 0);
    op(0xBF, "LAX", M_ABY, 4, 1);
    op(0x83, "SAX", M_IZX, 6, 0); op(0x87, "SAX", M_ZP, 3, 0); op(0x8F, "SAX", M_ABS, 4, 0);
    op(0x97, "SAX", M_ZPY, 4, 0);
    op(0xEB, "SBC", M_IMM, 2, 0);
    static const struct { int base; const char *m; } un[] = {
        { 0x00, "SLO" }, { 0x20, "RLA" }, { 0x40, "SRE" }, { 0x60, "RRA" },
        { 0xC0, "DCP" }, { 0xE0, "ISB" } };
    for (int i = 0; i < 6; i++) {
        int b = un[i].base;
        const char *m = un[i].m;
        op(b + 0x03, m, M_IZX, 8, 0); op(b + 0x07, m, M_ZP, 5, 0);
        op(b + 0x0F, m, M_ABS, 6, 0); op(b + 0x13, m, M_IZY, 8, 0);
        op(b + 0x17, m, M_ZPX, 6, 0); op(b + 0x1B, m, M_ABY, 7, 0);
        op(b + 0x1F, m, M_ABX, 7, 0);
    }
    /* The rest of the stable unofficial opcodes. */
    op(0x0B, "ANC", M_IMM, 2, 0); op(0x2B, "ANC", M_IMM, 2, 0);
    op(0x4B, "ALR", M_IMM, 2, 0); op(0x6B, "ARR", M_IMM, 2, 0);
    op(0xCB, "AXS", M_IMM, 2, 0);
    op(0x8B, "XAA", M_IMM, 2, 0); op(0xAB, "LXA", M_IMM, 2, 0);
    op(0x9C, "SHY", M_ABX, 5, 0); op(0x9E, "SHX", M_ABY, 5, 0);
    op(0x9F, "AHX", M_ABY, 5, 0); op(0x93, "AHX", M_IZY, 6, 0);
    op(0x9B, "TAS", M_ABY, 5, 0); op(0xBB, "LAS", M_ABY, 4, 1);
    /* Not translated: the 12 "JAM" opcodes ($02, $12, ... $F2). */
    check_cycle_maps();
}
