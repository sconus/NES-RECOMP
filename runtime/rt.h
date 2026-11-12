/* nesrecomp runtime: CPU state and helpers used by the generated code. */
#ifndef NESRECOMP_RT_H
#define NESRECOMP_RT_H
#include <stdint.h>
#include <stdio.h>

/* 6502 registers. Flags are kept as separate 0/1 bytes for speed and are
   only packed into a status byte when the program pushes or prints them. */
extern uint8_t A, X, Y, SP;
extern uint8_t C, Z, I, D, V, N;
extern uint16_t pc;
extern uint64_t cycles;
/* Cycle at which the runtime next needs control (vblank, a pending NMI).
   UINT64_MAX when nothing is scheduled. */
extern uint64_t next_event;
extern int trace_on;

uint8_t rd(uint16_t addr);
void wr(uint16_t addr, uint8_t val);
/* A read with no side effects: RAM and cartridge only, 0 for registers. */
uint8_t peek(uint16_t addr);
void untranslated(uint16_t addr);
void note_missed(uint16_t addr);
int interp_step(void);
void trace_step(uint16_t addr);
void recomp_run(uint16_t start);
/* Called when cycles >= next_event, between two instructions. Brings the
   hardware up to date, sets a new next_event, and returns the vector of an
   interrupt to take now ($FFFA for NMI, $FFFE for IRQ) or 0 for none. */
uint16_t runtime_event(void);
/* Where BRK goes: its own vector at $FFFE, unless an NMI arrives early
   enough during BRK to take it over (then $FFFA). Called with `cycles`
   still at the start of the BRK. */
uint16_t brk_vector(void);
/* From RTI: its new I flag takes effect at once (see event.c). */
void cpu_irq_poll(int delay);
/* From CLI, SEI and PLP, after changing I: `old_i` is I before the
   instruction, `len` its length in cycles (see event.c). */
void cpu_i_change(int old_i, int len);

/* Runs before every instruction: optional trace output. */
#define STEP(addr) do { if (trace_on) trace_step(addr); } while (0)
/* Interrupts are checked between instructions, as on the real CPU. The
   generated code puts EVENT_CHECK at the top of every translated
   instruction and INTERRUPT_CHECK at dispatch, which the interpreter
   passes through on every step. Both jump to the "event" block in
   recomp_run, which calls runtime_event and enters the handler if asked. */
#define EVENT_CHECK(addr) \
    do { if (cycles >= next_event) { pc = (addr); goto event; } } while (0)
#define INTERRUPT_CHECK() do { if (cycles >= next_event) goto event; } while (0)

/* The CPU's extra read from a half-computed address in indexed modes.
   Only hardware registers notice it ($2007 advances, $4016 shifts). */
static inline void dummy_rd(uint16_t a) {
    if (a >= 0x2000 && a < 0x4020) (void)rd(a);
}

static inline void setzn(uint8_t v) { Z = (v == 0); N = v >> 7; }

static inline uint8_t getP(int brk) {
    return (uint8_t)(N << 7 | V << 6 | 1 << 5 | (brk ? 1 : 0) << 4 |
                     D << 3 | I << 2 | Z << 1 | C);
}
static inline void setP(uint8_t p) {
    N = p >> 7; V = (p >> 6) & 1; D = (p >> 3) & 1;
    I = (p >> 2) & 1; Z = (p >> 1) & 1; C = p & 1;
}

static inline void push(uint8_t v) { wr(0x100 | SP, v); SP--; }
static inline uint8_t pop(void) { SP++; return rd(0x100 | SP); }

/* Enter an NMI or IRQ handler as the hardware does: push the return
   address and status (B flag clear), set I, load the vector. */
static inline void take_interrupt(uint16_t vector) {
    if (vector == 0xFFFC) {
        /* The reset button: the same 7-cycle sequence, but the three
           stack writes are turned into reads, so only SP moves. */
        SP -= 3;
        I = 1;
        pc = rd(0xFFFC) | (rd(0xFFFD) << 8);
        cycles += 7;
        return;
    }
    push(pc >> 8); push(pc & 0xFF); push(getP(0));
    I = 1;
    /* An IRQ's entry, like BRK's, can be taken over by an NMI that
       arrives in time; brk_vector handles both. */
    pc = vector == 0xFFFE ? brk_vector() : (rd(vector) | (rd(vector + 1) << 8));
    cycles += 7;
}

/* Add with carry. The NES CPU has no decimal mode, so D is ignored. */
static inline void adc(uint8_t v) {
    unsigned sum = A + v + C;
    V = (~(A ^ v) & (A ^ sum) & 0x80) != 0;
    C = sum > 0xFF;
    A = (uint8_t)sum;
    setzn(A);
}
static inline void cmp(uint8_t r, uint8_t v) {
    C = r >= v; setzn((uint8_t)(r - v));
}
static inline uint8_t asl(uint8_t v) { C = v >> 7; v <<= 1; setzn(v); return v; }
static inline uint8_t lsr(uint8_t v) { C = v & 1; v >>= 1; setzn(v); return v; }
static inline uint8_t rol(uint8_t v) {
    uint8_t c = C; C = v >> 7; v = (uint8_t)(v << 1 | c); setzn(v); return v;
}
static inline uint8_t ror(uint8_t v) {
    uint8_t c = C; C = v & 1; v = (uint8_t)(v >> 1 | c << 7); setzn(v); return v;
}

#endif
