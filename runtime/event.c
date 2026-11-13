/* nesrecomp runtime: the bridge between the translated CPU code and the
   rest of the hardware. The generated code compares `cycles` with
   `next_event` before each instruction and calls runtime_event once it is
   reached; everything else is up to the hardware models. */
#include "rt.h"
#include "event.h"
#include "ppu.h"
#include "apu.h"
#include "mapper.h"
#include "cycles.h"

uint64_t next_event = UINT64_MAX;
static int nmi_pending;
static uint64_t nmi_dot;
/* After an interrupt sequence (BRK, NMI) the CPU always runs the
   handler's first instruction before it looks at NMI again. */
static uint64_t nmi_blocked_until;

/* The IRQ line is level-triggered and shared: each source (mapper, later
   the APU) holds its own bit, and the CPU sees their OR. */
static unsigned irq_sources;
static uint64_t irq_dot;            /* when the line last went active */
/* The CPU decides whether to take an IRQ before the last cycle of each
   instruction, so CLI, SEI and PLP change I too late for their own
   decision: at the boundary right after one of them, the old I counts. */
static uint64_t old_i_until;
static int old_i;
static int reset_requested;

void cpu_request_reset(void) {
    reset_requested = 1;
    next_event = cycles;
}

/* An NMI seen by this cycle of a BRK or IRQ entry (where it starts
   reading its vector) takes it over. Tuned with cpu_interrupts_v2
   2-nmi_and_brk; 3-nmi_and_irq checks the same for IRQs. */
#define BRK_HIJACK_CYCLE 5

/* The CPU decides whether to take an interrupt once per instruction, on
   its second-to-last cycle; a line that goes active later waits until
   after the NEXT instruction. poll_end() gives, for the instruction that
   just finished, the cycle that decision counts from (see below). An
   NMI is taken only if it was raised at least NMI_LATENCY dots before
   that, an IRQ IRQ_LATENCY dots: the dots cover where in the CPU cycle
   the PPU and APU raise their lines. Tuned with the ppu_vbl_nmi tests,
   the MMC3 timing tests and cpu_interrupts_v2. */
#define NMI_LATENCY 6
#define IRQ_LATENCY 6

/* For a normal instruction, its end (= cycles now). A taken branch that
   stays on its page decides on its first cycle instead, ignoring its
   last one, so an interrupt in that cycle waits one more instruction
   (cpu_interrupts_v2 5-branch_delays_irq). Found from the instruction's
   cycle map and how long it really took (cycles.c). */
static uint64_t late_stall_insn = UINT64_MAX, late_stall;

void cpu_late_stall(uint64_t n) {
    if (late_stall_insn != insn_start) { late_stall_insn = insn_start; late_stall = 0; }
    late_stall += n;
}

static uint64_t poll_end(void) {
    const char *m = cycle_map[peek(insn_pc)];
    /* A DMA stall after the decision (cpu_late_stall) doesn't move it. */
    uint64_t end = cycles;
    if (late_stall_insn == insn_start) end -= late_stall;
    uint64_t took = end - insn_start;
    if (m && m[2] == 't' && took == 3)      /* branch, taken, same page */
        return end - 1;
    return end;
}

void cpu_request_nmi(uint64_t at_dot) {
    nmi_pending = 1;
    nmi_dot = at_dot;
    next_event = cycles;            /* look at it before the next instruction */
}

void cpu_cancel_nmi(void) {
    nmi_pending = 0;
}

void cpu_set_irq_at(unsigned source, int active, uint64_t at_dot) {
    unsigned was = irq_sources;
    if (active) irq_sources |= source;
    else irq_sources &= ~source;
    if (!was && irq_sources) {
        irq_dot = at_dot;
        if (!I) next_event = cycles;
    }
}

void cpu_set_irq(unsigned source, int active) {
    cpu_set_irq_at(source, active, ppu.dots);
}

void cpu_irq_poll(int delay) {
    /* RTI calls this after adding its cycles: its I takes effect at once. */
    if (irq_sources && !I) schedule_event(cycles + delay);
}

void cpu_i_change(int was, int len) {
    /* Called before the instruction's cycles are added, so its end is
       cycles + len. There the old I decides; from the next boundary on,
       the new one. So CLI lets one more instruction run first, and SEI
       (or PLP setting I) still lets one IRQ in, with I set in the
       pushed status. */
    old_i_until = cycles + len;
    old_i = was;
    if (irq_sources) {
        if (!was) schedule_event(cycles + len);
        if (!I) schedule_event(cycles + len + 1);
    }
}

void schedule_event(uint64_t when) {
    if (when < next_event) next_event = when;
}

uint16_t brk_vector(void) {
    uint64_t start = cycles;
    cycles = start + BRK_HIJACK_CYCLE;
    ppu_catch_up();
    int hijack = nmi_pending && nmi_dot + NMI_LATENCY <= cycles * 3;
    cycles = start;
    nmi_blocked_until = start + 7 + 1;
    if (hijack) nmi_pending = 0;
    uint16_t v = hijack ? 0xFFFA : 0xFFFE;
    return rd(v) | (rd(v + 1) << 8);
}

uint16_t runtime_event(void) {
    ppu_catch_up();                 /* may raise an NMI and finish a frame */
    apu_catch_up();                 /* may raise an IRQ */
    if (mapper.catch_up) mapper.catch_up();     /* so may the mapper */
    if (cycles >= dmc_dma_due) apu_dma_point(0);
    next_event = UINT64_MAX;
    if (reset_requested) {
        /* RAM, the cartridge and the mapper keep their state; the CPU,
           APU and PPU do what the reset line makes them do. */
        reset_requested = 0;
        nmi_pending = 0;
        apu_soft_reset();
        ppu_soft_reset();
        ppu_schedule();
        apu_schedule();
        if (mapper.schedule) mapper.schedule();
        return 0xFFFC;
    }
    ppu_schedule();
    apu_schedule();
    if (mapper.schedule) mapper.schedule();
    uint64_t poll = poll_end();
    if (nmi_pending) {
        if (nmi_dot + NMI_LATENCY <= poll * 3 && cycles >= nmi_blocked_until) {
            nmi_pending = 0;
            nmi_blocked_until = cycles + 7 + 1;
            return 0xFFFA;
        }
        /* Too late for this boundary: ask again after the next instruction.
           An IRQ can still be taken now, and the NMI may then take over
           its entry (brk_vector; cpu_interrupts_v2 3-nmi_and_irq). */
        schedule_event(cycles + 1);
    }
    int i_flag = cycles == old_i_until ? old_i : I;
    if (irq_sources && !i_flag) {
        if (irq_dot + IRQ_LATENCY <= poll * 3 && cycles >= nmi_blocked_until) {
            nmi_blocked_until = cycles + 7 + 1;
            return 0xFFFE;           /* the line stays up until acknowledged */
        }
        schedule_event(cycles + 1);
    }
    return 0;
}
