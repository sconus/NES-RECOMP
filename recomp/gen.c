/* nesrecomp's recompiler, in C: following the code and writing the C
   (see gen.h). Each function follows recomp.py's of the same name, and
   writes the same text to the byte: where recomp.py joins a list of
   strings with spaces (empty ones too), `struct parts` does the same. */
#include "gen.h"
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include "ops.h"

/* --- text --------------------------------------------------------------- */

struct sb {
    char *s;
    size_t n, cap;
};

static void sb_vadd(struct sb *b, const char *fmt, va_list ap) {
    va_list ap2;
    va_copy(ap2, ap);
    int need = vsnprintf(NULL, 0, fmt, ap2);
    va_end(ap2);
    if (b->n + (size_t)need + 1 > b->cap) {
        b->cap = (b->n + (size_t)need + 1) * 2;
        b->s = realloc(b->s, b->cap);
    }
    vsnprintf(b->s + b->n, (size_t)need + 1, fmt, ap);
    b->n += (size_t)need;
}

static void sb_add(struct sb *b, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    sb_vadd(b, fmt, ap);
    va_end(ap);
}

/* A Python list of strings, to be joined with " ". */
struct parts {
    struct sb sb;
    int count;
};

static void part(struct parts *p, const char *fmt, ...) {
    if (p->count++) sb_add(&p->sb, " ");
    if (!p->sb.s) sb_add(&p->sb, "");
    va_list ap;
    va_start(ap, fmt);
    sb_vadd(&p->sb, fmt, ap);
    va_end(ap);
}

static const char *joined(struct parts *p) {
    if (!p->sb.s) sb_add(&p->sb, "");
    return p->sb.s;
}

static void parts_free(struct parts *p) {
    free(p->sb.s);
    p->sb.s = NULL;
    p->sb.n = p->sb.cap = 0;
    p->count = 0;
}

/* --- a set of locations ------------------------------------------------- */

static uint64_t loc_key(int bank, long addr) { return (uint64_t)(uint32_t)bank << 32 | (uint32_t)addr; }

struct locset {
    uint64_t *keys;
    long *vals;                      /* an index, for insns */
    uint8_t *used;
    long cap, n;
};

static uint64_t mix(uint64_t k) {
    k ^= k >> 33;
    k *= 0xff51afd7ed558ccdULL;
    k ^= k >> 33;
    return k;
}

static long ls_find(const struct locset *s, uint64_t k) {
    if (!s->cap) return -1;
    long i = (long)(mix(k) & (uint64_t)(s->cap - 1));
    while (s->used[i]) {
        if (s->keys[i] == k) return i;
        i = (i + 1) & (s->cap - 1);
    }
    return -1;
}

static void ls_put(struct locset *s, uint64_t k, long v);

static void ls_grow(struct locset *s) {
    struct locset old = *s;
    s->cap = old.cap ? old.cap * 2 : 1024;
    s->keys = calloc((size_t)s->cap, sizeof *s->keys);
    s->vals = calloc((size_t)s->cap, sizeof *s->vals);
    s->used = calloc((size_t)s->cap, 1);
    s->n = 0;
    for (long i = 0; i < old.cap; i++)
        if (old.used[i]) ls_put(s, old.keys[i], old.vals[i]);
    free(old.keys);
    free(old.vals);
    free(old.used);
}

static void ls_put(struct locset *s, uint64_t k, long v) {
    if ((s->n + 1) * 2 > s->cap) ls_grow(s);
    long i = (long)(mix(k) & (uint64_t)(s->cap - 1));
    while (s->used[i] && s->keys[i] != k) i = (i + 1) & (s->cap - 1);
    if (!s->used[i]) s->n++;
    s->used[i] = 1;
    s->keys[i] = k;
    s->vals[i] = v;
}

static int ls_has(const struct locset *s, int bank, long addr) {
    return ls_find(s, loc_key(bank, addr)) >= 0;
}

/* --- tracing ------------------------------------------------------------ */

static struct locset insn_set;       /* for goto(): was (bank, addr) translated? */

static int by_loc(const void *a, const void *b) {
    const struct insn *x = a, *y = b;
    if (x->bank != y->bank) return x->bank < y->bank ? -1 : 1;
    return x->addr < y->addr ? -1 : x->addr > y->addr;
}

struct spot {
    int bank;
    long addr;
};

static int by_spot(const void *a, const void *b) {
    const struct spot *x = a, *y = b;
    if (x->bank != y->bank) return x->bank < y->bank ? -1 : 1;
    return x->addr < y->addr ? -1 : x->addr > y->addr;
}

static int inline_count(const struct rom *r, long addr, int *count) {
    for (int i = 0; i < r->n_inline; i++)
        if (r->inline_addr[i] == addr) { *count = r->inline_count[i]; return 1; }
    return 0;
}

void trace(const struct rom *r, const int *banks, const long *addrs, long n, struct traced *t) {
    struct locset unknown = { 0 };
    long ni = 0, cap_i = 1024, nw = n, cap_w = n + 1024;
    struct insn *insns = malloc((size_t)cap_i * sizeof *insns);
    struct spot *work = malloc((size_t)cap_w * sizeof *work);
    memset(&insn_set, 0, sizeof insn_set);
    for (long i = 0; i < n; i++) { work[i].bank = banks[i]; work[i].addr = addrs[i]; }
    while (nw) {
        struct spot loc = work[--nw];
        while (!ls_has(&insn_set, loc.bank, loc.addr) && !ls_has(&unknown, loc.bank, loc.addr)) {
            int bank = loc.bank;
            long addr = loc.addr;
            int opc = rom_read(r, bank, addr);
            if (!OPS[opc].valid) {
                ls_put(&unknown, loc_key(bank, addr), 0);
                break;
            }
            const struct op *o = &OPS[opc];
            int size = SIZE[o->mode];
            uint8_t operand[2];
            int got = 0;
            for (int i = 1; i < size; i++) {
                int b = rom_resolve(r, bank, addr, (addr + i) & 0xFFFF);
                if (b == NO_BANK) break;
                operand[got++] = (uint8_t)rom_read(r, b, (addr + i) & 0xFFFF);
            }
            if (got != size - 1) {           /* operand lies in an unknown bank */
                ls_put(&unknown, loc_key(bank, addr), 0);
                break;
            }
            if (ni == cap_i) { cap_i *= 2; insns = realloc(insns, (size_t)cap_i * sizeof *insns); }
            insns[ni].bank = bank;
            insns[ni].addr = addr;
            insns[ni].opc = opc;
            insns[ni].n_operand = got;
            memcpy(insns[ni].operand, operand, sizeof operand);
            ls_put(&insn_set, loc_key(bank, addr), ni);
            ni++;
            long nxt = (addr + size) & 0xFFFF;
            long targets[2];
            int nt = 0;
            if (o->mode == M_REL) {
                int off = operand[0] >= 128 ? operand[0] - 256 : operand[0];
                targets[nt++] = (nxt + off) & 0xFFFF;
            }
            int jump = (!strcmp(o->mnem, "JMP") || !strcmp(o->mnem, "JSR")) && o->mode == M_ABS;
            if (jump) targets[nt++] = operand[0] | operand[1] << 8;
            for (int i = 0; i < nt; i++) {
                int b = rom_resolve(r, bank, addr, targets[i]);
                if (b != NO_BANK) {
                    if (nw == cap_w) { cap_w *= 2; work = realloc(work, (size_t)cap_w * sizeof *work); }
                    work[nw].bank = b;
                    work[nw++].addr = targets[i];
                }
            }
            const char *m = o->mnem;
            if (!strcmp(m, "JMP") || !strcmp(m, "RTS") || !strcmp(m, "RTI") || !strcmp(m, "BRK"))
                break;
            int count;
            if (!strcmp(m, "JSR") && inline_count(r, targets[0], &count)) {
                /* It returns past the pointers that follow the JSR. */
                if (count < 0) break;
                nxt = (nxt + 2 * count) & 0xFFFF;
            }
            int b = rom_resolve(r, bank, addr, nxt);
            if (b == NO_BANK) break;
            loc.bank = b;
            loc.addr = nxt;
        }
    }
    free(work);
    /* Sorted, as recomp.py's sorted(insns), and the set rebuilt to point
       at the sorted places. */
    qsort(insns, (size_t)ni, sizeof *insns, by_loc);
    for (long i = 0; i < ni; i++) ls_put(&insn_set, loc_key(insns[i].bank, insns[i].addr), i);
    t->insns = insns;
    t->n_insns = ni;
    struct spot *u = malloc((size_t)(unknown.n + 1) * sizeof *u);
    long nu = 0;
    for (long i = 0; i < unknown.cap; i++)
        if (unknown.used[i]) {
            u[nu].bank = (int)(unknown.keys[i] >> 32);
            u[nu++].addr = (long)(uint32_t)unknown.keys[i];
        }
    qsort(u, (size_t)nu, sizeof *u, by_spot);
    t->n_unknown = nu;
    t->unknown_bank = malloc((size_t)(nu + 1) * sizeof(int));
    t->unknown_addr = malloc((size_t)(nu + 1) * sizeof(long));
    for (long i = 0; i < nu; i++) { t->unknown_bank[i] = u[i].bank; t->unknown_addr[i] = u[i].addr; }
    free(u);
}

/* --- writing the C ------------------------------------------------------ */

static void lbl(char *out, size_t n, int bank, long addr) {
    snprintf(out, n, "L_%02X_%04lX", bank, addr);
}

static long word(const uint8_t *operand) { return operand[0] | operand[1] << 8; }

/* recomp.py's ea_code: the C computing ea, and the page-cross test. */
static void ea_code(struct parts *p, int mode, const uint8_t *operand, char *cross, size_t cn) {
    snprintf(cross, cn, "0");
    switch (mode) {
    case M_ZP: part(p, "ea = 0x%02X;", operand[0]); return;
    case M_ZPX: part(p, "ea = (uint8_t)(0x%02X + X);", operand[0]); return;
    case M_ZPY: part(p, "ea = (uint8_t)(0x%02X + Y);", operand[0]); return;
    case M_ABS: part(p, "ea = 0x%04lX;", word(operand)); return;
    case M_ABX:
    case M_ABY: {
        long base = word(operand);
        const char *reg = mode == M_ABX ? "X" : "Y";
        part(p, "ea = (uint16_t)(0x%04lX + %s);", base, reg);
        snprintf(cross, cn, "((0x%02lX + %s) > 0xFF)", base & 0xFF, reg);
        return;
    }
    case M_IZX:
        part(p, "{ uint8_t p = (uint8_t)(0x%02X + X); ea = rd(p) | (rd((uint8_t)(p + 1)) << 8); }",
             operand[0]);
        return;
    case M_IZY:
        part(p, "base = rd(0x%02X) | (rd(0x%02X) << 8); ea = (uint16_t)(base + Y);", operand[0],
             (operand[0] + 1) & 0xFF);
        snprintf(cross, cn, "(((base & 0xFF) + Y) > 0xFF)");
        return;
    }
    fprintf(stderr, "ea_code: mode %s\n", mode_name[mode]);
    exit(1);
}

static int may_touch_io(int mode, const uint8_t *operand) {
    if (mode == M_ZP || mode == M_ZPX || mode == M_ZPY) return 0;
    if (mode == M_ABS) { long a = word(operand); return a >= 0x2000 && a < 0x4020; }
    if (mode == M_ABX || mode == M_ABY) { long a = word(operand); return a <= 0x401F && a + 0xFF >= 0x2000; }
    return 1;
}

static int may_write_mapper(int mode, const uint8_t *operand, const struct rom *r) {
    if (mode == M_ZP || mode == M_ZPX || mode == M_ZPY) return 0;
    long lo = 0x8000, hi = 0x8000;
    if (r->low_lo >= 0) { lo = r->low_lo; hi = r->low_hi; }
    if (mode == M_ABS) { long a = word(operand); return a >= 0x8000 || (lo <= a && a <= hi); }
    if (mode == M_ABX || mode == M_ABY) {
        long a = word(operand);
        return a + 0xFF >= 0x8000 || (a <= hi && a + 0xFF >= lo);
    }
    return 1;
}

/* recomp.py's mem_body. */
static void mem_body(struct parts *p, const char *mnem, int mode, int cyc, int pen,
                     const char *cross, const char *base, int timed, const char *value) {
    int indexed = mode == M_ABX || mode == M_ABY || mode == M_IZY;
    char unfixed[96];
    snprintf(unfixed, sizeof unfixed, "(uint16_t)((%s & 0xFF00) | (ea & 0xFF))", base);
    const char *hs = high_store_value(mnem);
    if (hs) {
        if (!strcmp(mnem, "TAS")) part(p, "SP = A & X;");
        part(p, "v = (uint8_t)(%s & ((%s >> 8) + 1)); "
                "if ((%s ^ ea) & 0xFF00) ea = (uint16_t)((ea & 0xFF) | v << 8);", hs, base, base);
        mem_body(p, "STA", mode, cyc, pen, cross, base, timed, "v");
        return;
    }
    const char *sv = store_value(mnem);
    int rmw = is_rmw(mnem);
    if (!timed) {
        if (sv) {
            part(p, "wr(ea, %s);", value ? value : sv);
            part(p, "cycles += %d;", cyc);
            return;
        }
        if (rmw) {
            part(p, "v = rd(ea); %s wr(ea, v);", rmw_op(mnem));
            part(p, "cycles += %d;", cyc);
            return;
        }
        part(p, "v = rd(ea); %s", read_op(mnem));
        if (pen && strcmp(cross, "0")) part(p, "cycles += %d + %s;", cyc, cross);
        else part(p, "cycles += %d;", cyc);
        return;
    }
    if (sv) {
        const char *val = value ? value : sv;
        if (indexed) {
            part(p, "cycles += %d; dummy_rd(%s); cycles += 1;", cyc - 2, unfixed);
            part(p, "wr(ea, %s); cycles += 1;", val);
        } else {
            part(p, "cycles += %d; wr(ea, %s); cycles += 1;", cyc - 1, val);
        }
        return;
    }
    if (rmw) {
        if (indexed) part(p, "cycles += %d; dummy_rd(%s); cycles += 1;", cyc - 4, unfixed);
        else part(p, "cycles += %d;", cyc - 3);
        part(p, "v = rd(ea); cycles += 1; wr(ea, v); cycles += 1;");
        part(p, "%s", rmw_op(mnem));
        part(p, "wr(ea, v); cycles += 1;");
        return;
    }
    part(p, "cycles += %d;", cyc - 1);
    if (pen && strcmp(cross, "0")) part(p, "if (%s) { dummy_rd(%s); cycles += 1; }", cross, unfixed);
    part(p, "v = rd(ea); cycles += 1; %s", read_op(mnem));
}

/* recomp.py's goto. */
static void goto_text(char *out, size_t n, const struct rom *r, int fbank, long faddr, long tgt) {
    int b = rom_resolve(r, fbank, faddr, tgt);
    if (b != NO_BANK && ls_has(&insn_set, b, tgt)) {
        char l[32];
        lbl(l, sizeof l, b, tgt);
        snprintf(out, n, "goto %s;", l);
    } else {
        snprintf(out, n, "{ pc = 0x%04lX; goto dispatch; }", tgt);
    }
}

/* "v" replaced by "A", as recomp.py's str.replace for the accumulator. */
static void v_to_a(char *out, size_t n, const char *s) {
    size_t k = 0;
    for (; *s && k + 1 < n; s++) out[k++] = *s == 'v' ? 'A' : *s;
    out[k] = 0;
}

static void gen_insn(struct sb *out, const struct insn *in, const struct rom *r) {
    long addr = in->addr;
    const struct op *o = &OPS[in->opc];
    const char *mnem = o->mnem;
    int mode = o->mode, cyc = o->cyc, pen = o->pen, size = SIZE[mode];
    long nxt = (addr + size) & 0xFFFF;
    const uint8_t *operand = in->operand;
    char l[32], g[96];
    lbl(l, sizeof l, in->bank, addr);
    int tag = rom_guard_tag(r, in->bank, addr);
    if (tag < 0) {
        sb_add(out, "%s: EVENT_CHECK(0x%04lX); STEP(0x%04lX);\n", l, addr, addr);
    } else {
        /* Code in RAM: only while its bytes are the ones translated. */
        struct parts cond = { 0 };
        for (int i = 0; i < size; i++) {
            long a = (addr + i) & 0xFFFF;
            if (a >= 0x6000 && a < 0xE000) {
                if (cond.count++) sb_add(&cond.sb, " || ");
                sb_add(&cond.sb, "code_owner[0x%04lX] != %d", a - 0x6000, tag);
            }
        }
        sb_add(out, "%s: EVENT_CHECK(0x%04lX);\n", l, addr);
        sb_add(out, "    if (%s) { pc = 0x%04lX; goto changed; }\n", joined(&cond), addr);
        sb_add(out, "    ram_native++; STEP(0x%04lX);\n", addr);
        parts_free(&cond);
    }
    struct parts body = { 0 };
    int falls = 1;
    const char *imp = implied_op(mnem);
    if (mode == M_IMP && imp) {
        part(&body, "%s", imp);
        part(&body, "cycles += %d;", cyc);
    } else if (mode == M_ACC) {
        char a[64];
        v_to_a(a, sizeof a, rmw_op(mnem));
        part(&body, "%s", a);
        part(&body, "cycles += %d;", cyc);
    } else if (mode == M_IMM) {
        part(&body, "v = 0x%02X; %s", operand[0], read_op(mnem));
        part(&body, "cycles += %d;", cyc);
    } else if (mode == M_REL) {
        int off = operand[0] >= 128 ? operand[0] - 256 : operand[0];
        long tgt = (nxt + off) & 0xFFFF;
        int extra = (tgt & 0xFF00) != (nxt & 0xFF00) ? 2 : 1;
        part(&body, "cycles += %d;", cyc);
        goto_text(g, sizeof g, r, in->bank, addr, tgt);
        part(&body, "if (%s) { cycles += %d; %s }", branch_cond(mnem), extra, g);
    } else if (!strcmp(mnem, "JMP") && mode == M_ABS) {
        goto_text(g, sizeof g, r, in->bank, addr, word(operand));
        part(&body, "cycles += 3; %s", g);
        falls = 0;
    } else if (!strcmp(mnem, "JMP") && mode == M_IND) {
        long p = word(operand);
        long hi = (p & 0xFF00) | ((p + 1) & 0xFF);   /* the famous 6502 page-wrap bug */
        part(&body, "pc = rd(0x%04lX) | (rd(0x%04lX) << 8); cycles += 5; goto dispatch;", p, hi);
        falls = 0;
    } else if (!strcmp(mnem, "JSR")) {
        long ret = (addr + 2) & 0xFFFF;
        goto_text(g, sizeof g, r, in->bank, addr, word(operand));
        part(&body, "push(0x%02lX); push(0x%02lX); cycles += 6; %s", ret >> 8, ret & 0xFF, g);
        falls = 0;
    } else if (!strcmp(mnem, "RTS")) {
        part(&body, "pc = pop(); pc |= pop() << 8; pc++; cycles += 6; goto dispatch;");
        falls = 0;
    } else if (!strcmp(mnem, "RTI")) {
        part(&body, "setP(pop()); pc = pop(); pc |= pop() << 8; cycles += 6; cpu_irq_poll(0); "
                    "goto dispatch;");
        falls = 0;
    } else if (!strcmp(mnem, "BRK")) {
        long ret = (addr + 2) & 0xFFFF;
        part(&body, "push(0x%02lX); push(0x%02lX); push(getP(1)); I = 1; pc = brk_vector(); "
                    "cycles += 7; goto dispatch;", ret >> 8, ret & 0xFF);
        falls = 0;
    } else {
        char cross[64], base[16];
        ea_code(&body, mode, operand, cross, sizeof cross);
        if (mode == M_IZY) snprintf(base, sizeof base, "base");
        else if (size == 3) snprintf(base, sizeof base, "0x%04lX", word(operand));
        else snprintf(base, sizeof base, "ea");
        int writes = store_value(mnem) || is_rmw(mnem) || high_store_value(mnem);
        /* Writes that may reach a mapper are timed too. */
        int timed = may_touch_io(mode, operand) ||
                    (writes && r->high_writes && may_write_mapper(mode, operand, r));
        mem_body(&body, mnem, mode, cyc, pen, cross, base, timed, NULL);
        /* Code in a switchable bank that writes to the mapper may have
           just switched itself out: carry on through dispatch if so. */
        if (writes && rom_switches(r, addr) && may_write_mapper(mode, operand, r))
            part(&body, "if (mapper.bank_changed) { mapper.bank_changed = 0; "
                        "pc = 0x%04lX; goto dispatch; }", nxt);
    }
    sb_add(out, "    %s\n", joined(&body));
    parts_free(&body);
    if (falls) {
        goto_text(g, sizeof g, r, in->bank, addr, nxt);
        sb_add(out, "    %s\n", g);
    }
}

/* recomp.py's interp_ea: operands read at run time. */
static const char *interp_ea(int mode, const char **cross) {
    *cross = "0";
    switch (mode) {
    case M_ZP: return "ea = o1;";
    case M_ZPX: return "ea = (uint8_t)(o1 + X);";
    case M_ZPY: return "ea = (uint8_t)(o1 + Y);";
    case M_ABS: return "ea = o1 | (o2 << 8);";
    case M_ABX: *cross = "(((base & 0xFF) + X) > 0xFF)";
        return "base = o1 | (o2 << 8); ea = (uint16_t)(base + X);";
    case M_ABY: *cross = "(((base & 0xFF) + Y) > 0xFF)";
        return "base = o1 | (o2 << 8); ea = (uint16_t)(base + Y);";
    case M_IZX: return "{ uint8_t p = (uint8_t)(o1 + X); ea = rd(p) | (rd((uint8_t)(p + 1)) << 8); }";
    case M_IZY: *cross = "(((base & 0xFF) + Y) > 0xFF)";
        return "base = rd(o1) | (rd((uint8_t)(o1 + 1)) << 8); ea = (uint16_t)(base + Y);";
    }
    fprintf(stderr, "interp_ea: mode %s\n", mode_name[mode]);
    exit(1);
}

static void gen_interp_case(struct sb *out, int opc) {
    const struct op *o = &OPS[opc];
    const char *mnem = o->mnem;
    int mode = o->mode, cyc = o->cyc, size = SIZE[mode];
    struct parts b = { 0 };
    const char *imp = implied_op(mnem);
    if (mode == M_IMP && imp) {
        part(&b, "%s", imp);
        part(&b, "cycles += %d;", cyc);
        part(&b, "pc += %d;", size);
    } else if (mode == M_ACC) {
        char a[64];
        v_to_a(a, sizeof a, rmw_op(mnem));
        part(&b, "%s", a);
        part(&b, "cycles += %d;", cyc);
        part(&b, "pc += %d;", size);
    } else if (mode == M_IMM) {
        part(&b, "v = o1;");
        part(&b, "%s", read_op(mnem));
        part(&b, "cycles += %d;", cyc);
        part(&b, "pc += %d;", size);
    } else if (mode == M_REL) {
        part(&b, "cycles += 2;");
        part(&b, "if (%s) { uint16_t n = pc + 2; uint16_t t = n + (int8_t)o1; "
                 "cycles += ((t & 0xFF00) != (n & 0xFF00)) ? 2 : 1; pc = t; } else pc += 2;",
             branch_cond(mnem));
    } else if (!strcmp(mnem, "JMP") && mode == M_ABS) {
        part(&b, "pc = o1 | (o2 << 8); cycles += 3;");
    } else if (!strcmp(mnem, "JMP") && mode == M_IND) {
        part(&b, "{ uint16_t p = o1 | (o2 << 8); "
                 "pc = rd(p) | (rd((p & 0xFF00) | ((p + 1) & 0xFF)) << 8); } cycles += 5;");
    } else if (!strcmp(mnem, "JSR")) {
        part(&b, "{ uint16_t r = pc + 2; push(r >> 8); push(r & 0xFF); } pc = o1 | (o2 << 8); "
                 "cycles += 6;");
    } else if (!strcmp(mnem, "RTS")) {
        part(&b, "pc = pop(); pc |= pop() << 8; pc++; cycles += 6;");
    } else if (!strcmp(mnem, "RTI")) {
        part(&b, "setP(pop()); pc = pop(); pc |= pop() << 8; cycles += 6; cpu_irq_poll(0);");
    } else if (!strcmp(mnem, "BRK")) {
        part(&b, "{ uint16_t r = pc + 2; push(r >> 8); push(r & 0xFF); } push(getP(1)); I = 1; "
                 "pc = brk_vector(); cycles += 7;");
    } else {
        const char *cross;
        part(&b, "%s", interp_ea(mode, &cross));
        const char *base = mode == M_ABX || mode == M_ABY || mode == M_IZY ? "base" : "ea";
        mem_body(&b, mnem, mode, cyc, o->pen, cross, base,
                 !(mode == M_ZP || mode == M_ZPX || mode == M_ZPY), NULL);
        part(&b, "pc += %d;", size);
    }
    sb_add(out, "    case 0x%02X: %s break;\n", opc, joined(&b));
    parts_free(&b);
}

static void gen_interpreter(struct sb *out) {
    sb_add(out, "/* Fallback interpreter: runs one instruction at pc. Used only when\n"
                "   execution reaches code the tracer could not see ahead of time. */\n"
                "int interp_step(void) {\n"
                "    uint16_t ea, base; uint8_t v;\n"
                "    (void)ea; (void)base; (void)v;\n"
                "    insn_pc = pc; insn_start = cycles;\n"
                "    STEP(pc);\n"
                "    uint8_t opc = rd(pc), o1 = rd(pc + 1), o2 = rd(pc + 2);\n"
                "    (void)o2;\n"
                "    switch (opc) {\n");
    for (int opc = 0; opc < 256; opc++)
        if (OPS[opc].valid) gen_interp_case(out, opc);
    sb_add(out, "    default: return 0;\n    }\n    return 1;\n}\n\n");
}

static void gen_cycle_maps(struct sb *out) {
    sb_add(out, "/* Bus cycles of each opcode, one letter per cycle; the key is\n"
                "   CYCLE_KEY in recomp.py. Used by runtime/cycles.c. */\n"
                "const char *const cycle_map[256] = {\n");
    for (int opc = 0; opc < 256; opc++)
        if (OPS[opc].valid)
            sb_add(out, "    [0x%02X] = \"%s\",  /* %s %s */\n", opc,
                   cycle_map(OPS[opc].mnem, OPS[opc].mode), OPS[opc].mnem, mode_name[OPS[opc].mode]);
    sb_add(out, "};\n\n");
}

void generate(FILE *f, const struct rom *r, const struct traced *t, const char *src_name) {
    struct sb out = { 0 };
    sb_add(&out, "/* Generated by nesrecomp from %s. Do not edit by hand. */\n"
                 "#include \"rt.h\"\n#include \"mapper.h\"\n\n", src_name);
    gen_interpreter(&out);
    gen_cycle_maps(&out);
    char bank_now[160];
    const char *slot = r->slot_bits == 13 ? "mapper.prg_bank[(pc >> 13) & 3]"
                                          : "mapper.prg_bank_4k[(pc >> 12) & 7]";
    if (r->is_fds)                    /* an FDS: RAM is keyed by file */
        snprintf(bank_now, sizeof bank_now,
                 "(pc >= 0x6000 && pc < 0xE000 ? code_owner[pc - 0x6000] : %s)", slot);
    else snprintf(bank_now, sizeof bank_now, "%s", slot);
    sb_add(&out, "void recomp_run(uint16_t start) {\n"
                 "    uint16_t ea, base; uint8_t v;\n"
                 "    int in_interp = 0;\n"
                 "    (void)ea; (void)base; (void)v;\n"
                 "    pc = start;\n"
                 "dispatch:\n"
                 "    INTERRUPT_CHECK();\n"
                 "    /* Look up the bank mapped at pc right now, as well as pc. */\n"
                 "    switch ((uint32_t)%s << 16 | pc) {\n", bank_now);
    for (long i = 0; i < t->n_insns; i++) {
        char l[32];
        lbl(l, sizeof l, t->insns[i].bank, t->insns[i].addr);
        sb_add(&out, "    case 0x%06lX: in_interp = 0; goto %s;\n",
               (long)t->insns[i].bank << 16 | t->insns[i].addr, l);
    }
    sb_add(&out, "    default:\n"
                 "        if (!in_interp) note_missed(pc);\n"
                 "        in_interp = 1;\n");
    if (rom_guarded(r))
        sb_add(&out, "        if (pc >= 0x6000 && pc < 0xE000) ram_interp++;\n"
                     "        if (!interp_step()) { untranslated(pc); return; }\n"
                     "        goto dispatch;\n"
                     "    }\n"
                     "\n"
                     "changed:  /* code in RAM that isn't what was translated any more */\n"
                     "    ram_interp++;\n"
                     "    in_interp = 1;\n"
                     "    if (!interp_step()) { untranslated(pc); return; }\n"
                     "    goto dispatch;\n"
                     "\n");
    else
        sb_add(&out, "        if (!interp_step()) { untranslated(pc); return; }\n"
                     "        goto dispatch;\n"
                     "    }\n"
                     "\n");
    sb_add(&out, "event: {  /* hardware needs attention; pc holds the next address */\n"
                 "        uint16_t vector = runtime_event();\n"
                 "        if (vector) take_interrupt(vector);\n"
                 "        goto dispatch;\n"
                 "    }\n"
                 "\n");
    for (long i = 0; i < t->n_insns; i++) gen_insn(&out, &t->insns[i], r);
    sb_add(&out, "}\n");
    fwrite(out.s, 1, out.n, f);
    free(out.s);
}
