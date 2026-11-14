/* nesrecomp runtime: scheduling hardware events against the CPU clock. */
#ifndef NESRECOMP_EVENT_H
#define NESRECOMP_EVENT_H
#include <stdint.h>

/* The NMI line went active at PPU dot `at_dot` (counted like ppu.dots;
   the CPU's clock is cycles * 3 in these units). */
void cpu_request_nmi(uint64_t at_dot);
/* The NMI was withdrawn before the CPU noticed it (e.g. $2002 was read
   right as vblank started). */
void cpu_cancel_nmi(void);

/* IRQ sources. Each holds the shared IRQ line active until it lets go. */
#define IRQ_MAPPER 1u
#define IRQ_APU    2u
#define IRQ_DISK   4u     /* the FDS drive's byte transfer (the timer is IRQ_MAPPER) */
void cpu_set_irq(unsigned source, int active);
/* The same, saying when it happened (in PPU dots, cycles * 3), for
   sources that run on their own clock (the APU). */
void cpu_set_irq_at(unsigned source, int active, uint64_t at_dot);

/* Press the reset button: taken at the next instruction boundary. */
void cpu_request_reset(void);

/* A DMA just halted the CPU for n cycles after the running instruction
   decided whether to take an interrupt (sprite DMA after its $4014
   write, a DMC fetch on the last cycle or the next opcode fetch). The
   decision stays where it was: an interrupt raised during the stall
   waits for the next instruction (cpu_interrupts_v2 4-irq_and_dma). */
void cpu_late_stall(uint64_t n);

/* Ask for runtime_event to be called once cycles reaches `when`.
   Earlier requests win until the next event runs. */
void schedule_event(uint64_t when);

#endif
