/* nesrecomp runtime: mapper implementations. Each one is a reset function
   (power-on banks) and a write function (its registers). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "cart.h"
#include "mapper.h"
#include "nsf.h"
#include "ppu.h"
#include "rt.h"
#include "event.h"
#include "fds.h"
#include "apu.h"

struct mapper mapper;
static void (*write_reg)(uint16_t addr, uint8_t val);
static void (*write_low)(uint16_t addr, uint8_t val);   /* $4020-$5FFF */
static int (*read_low)(uint16_t addr);                  /* -1: open bus */

/* ---- helpers: put bank n (counted in the given size) in a slot ------ */

static int prg_banks_8k(void) { return (int)(cart.prg_size / 0x2000); }
static int chr_banks_1k(void) { return (int)(cart.chr_size / 0x400); }

/* Put 8 KB bank n of the cartridge's PRG RAM at $6000 (the header's
   size: less than 8 KB repeats, none leaves open bus). */
static void set_ram_8k(int bank) {
    size_t total = cart.prg_ram_size + cart.prg_nvram_size;
    size_t banks = total / 0x2000;
    mapper.ram6000 = cart.prg_ram + (banks > 1 ? (size_t)bank % banks * 0x2000 : 0);
    mapper.ram6000_size = total < 0x2000 ? total : 0x2000;
}

/* Negative bank numbers count from the end: -1 is the last bank. */
static int wrap(int n, int count) { n %= count; return n < 0 ? n + count : n; }

static void set_prg_8k(int slot, int bank) {
    bank = wrap(bank, prg_banks_8k());
    if (mapper.prg_bank[slot] != bank) mapper.bank_changed = 1;
    mapper.prg_bank[slot] = bank;
    mapper.prg[slot] = cart.prg + (size_t)bank * 0x2000;
}
static void set_prg_16k(int window, int bank) {        /* window 0 or 1 */
    set_prg_8k(window * 2, bank * 2);
    set_prg_8k(window * 2 + 1, bank * 2 + 1);
}
static void set_prg_32k(int bank) {
    for (int i = 0; i < 4; i++) set_prg_8k(i, bank * 4 + i);
}
static void set_chr_1k(int slot, int bank) {
    mapper.chr[slot] = cart.chr + (size_t)wrap(bank, chr_banks_1k()) * 0x400;
}
static void set_chr_4k(int half, int bank) {         /* half 0 or 1 */
    for (int i = 0; i < 4; i++) set_chr_1k(half * 4 + i, bank * 4 + i);
}
static void set_chr_8k(int bank) {
    for (int i = 0; i < 8; i++) set_chr_1k(i, bank * 8 + i);
}

/* Boards without a mapper chip (CNROM, UxROM, ...) let the ROM drive the
   data bus during a write too, so the register sees value AND ROM byte. */
static uint8_t bus_conflict(uint16_t addr, uint8_t val) {
    return val & prg_read(addr);
}

/* UxROM, CNROM and AxROM: NES 2.0 submapper 1 says the board has no bus
   conflicts, 2 that it has them; 0 leaves the usual guess (yes for UxROM
   and CNROM, no for AxROM). Set by mapper_init. */
static int conflicts;
static uint8_t maybe_conflict(uint16_t addr, uint8_t val) {
    return conflicts ? bus_conflict(addr, val) : val;
}

/* ---- 0: NROM. No registers. ------------------------------------------ */

static void nrom_write(uint16_t addr, uint8_t val) { (void)addr; (void)val; }

/* ---- 3: CNROM. One register: which 8 KB of CHR ROM. ------------------ */

static void cnrom_write(uint16_t addr, uint8_t val) {
    set_chr_8k(maybe_conflict(addr, val));
}

/* ---- 2: UxROM. 16 KB at $8000 switches; the last 16 KB is fixed. ---- */

static void uxrom_write(uint16_t addr, uint8_t val) {
    set_prg_16k(0, maybe_conflict(addr, val));
}

/* ---- 7: AxROM. 32 KB PRG switching and one-screen mirroring. --------- */

static void axrom_write(uint16_t addr, uint8_t val) {
    val = maybe_conflict(addr, val);
    set_prg_32k(val & 7);
    cart.mirroring = (val & 0x10) ? MIRROR_SINGLE_HIGH : MIRROR_SINGLE_LOW;
}

/* ---- 34: BNROM. 32 KB PRG switching (with bus conflicts). ------------- */

static void bnrom_write(uint16_t addr, uint8_t val) {
    set_prg_32k(bus_conflict(addr, val));
}

/* ---- 11: Color Dreams. One register: CCCC LLPP, a 32 KB PRG bank in bits
   0-1 and an 8 KB CHR bank in bits 4-7 (bits 2-3 drove the lockout-chip
   defeat). Released games had bus conflicts, but some prototypes break
   with them, and the nesdev wiki says to assume none unless the header
   says otherwise; this runtime reads iNES 1.0 headers, so: none. ---- */

static void color_dreams_write(uint16_t addr, uint8_t val) {
    (void)addr;
    set_prg_32k(val & 3);
    set_chr_8k(val >> 4);
}

/* ---- 66: GxROM. One register: xxPP xxCC, a 32 KB PRG bank in bits 4-5
   and an 8 KB CHR bank in bits 0-1, with bus conflicts. ------------- */

static void gxrom_write(uint16_t addr, uint8_t val) {
    val = bus_conflict(addr, val);
    set_prg_32k((val >> 4) & 3);
    set_chr_8k(val & 3);
}

/* ---- 71: Camerica / Codemasters (BF9093, BF9097). nesdev wiki,
   "INES Mapper 071". 16 KB at $8000 switches by writes to $C000-$FFFF
   (bits 0-3), the last 16 KB is fixed, CHR is RAM. The BF9097 (Fire
   Hawk) also has one-screen mirroring at $8000-$9FFF (bit 4: 0 $2000,
   1 $2400): submapper 1 says the board has it; with submapper 0, as the
   wiki suggests, the header's mirroring holds until the program first
   writes there. No bus conflicts (the CIC-stun chip drives the bus). */

static int camerica_mirror_reg;

static void camerica_write(uint16_t addr, uint8_t val) {
    if (addr >= 0xC000) set_prg_16k(0, val & 0x0F);
    else if (addr < 0xA000 && (camerica_mirror_reg || cart.submapper == 0))
        cart.mirroring = (val & 0x10) ? MIRROR_SINGLE_HIGH : MIRROR_SINGLE_LOW;
}

static void camerica_reset(void) {
    set_prg_16k(0, 0);
    set_prg_16k(1, -1);
    camerica_mirror_reg = cart.submapper == 1;
    if (camerica_mirror_reg) cart.mirroring = MIRROR_SINGLE_LOW;
}

/* ---- 79: AVE NINA-03 / NINA-06. nesdev wiki, "INES Mapper 079". One
   register, answering at $4100-$5FFF where A8 is set (addr & $E100 =
   $4100): bit 3 the 32 KB PRG bank, bits 0-2 the 8 KB CHR bank.
   Mirroring is the header's. */

static void nina_write_low(uint16_t addr, uint8_t val) {
    if ((addr & 0xE100) != 0x4100) return;
    set_prg_32k((val >> 3) & 1);
    set_chr_8k(val & 7);
}

/* ---- 41: Caltron 6-in-1. nesdev wiki, "INES Mapper 041". Two
   registers:
     $6000-$67FF  the address is the value: ..MC CEPP, the 32 KB PRG bank
                  in bits 0-2 (EPP), bit 2 (E) also lets the inner
                  register be written, CC the high bits of the CHR bank,
                  M mirroring (0 vertical, 1 horizontal);
     $8000-$FFFF  the inner register, only while E is set: the low two
                  bits of the 8 KB CHR bank, with bus conflicts. */

static int caltron_outer, caltron_inner;

static void caltron_apply(void) {
    set_prg_32k(caltron_outer & 7);
    set_chr_8k((caltron_outer >> 1 & 0x0C) | (caltron_inner & 3));
    cart.mirroring = (caltron_outer & 0x20) ? MIRROR_HORIZONTAL : MIRROR_VERTICAL;
}

static void caltron_write_6000(uint16_t addr, uint8_t val) {
    (void)val;
    if (addr >= 0x6800) return;
    caltron_outer = addr & 0x3F;
    caltron_apply();
}

static void caltron_write(uint16_t addr, uint8_t val) {
    if (!(caltron_outer & 4)) return;
    caltron_inner = bus_conflict(addr, val) & 3;
    caltron_apply();
}

static void caltron_reset(void) {
    caltron_outer = caltron_inner = 0;
    caltron_apply();
}

/* ---- 228: Active Enterprises (Action 52, Cheetahmen II). nesdev wiki,
   "INES Mapper 228". Everything is in a write to $8000-$FFFF:
     address  ..MH HPPP PPS. CCCC
              M mirroring (0 vertical, 1 horizontal), HH which 512 KB
              PRG chip, PPPPP the 16 KB bank in that chip, S the PRG
              mode (0: 32 KB, the bank with bit 0 clear at $8000 and set
              at $C000; 1: the same 16 KB at both), CCCC the high bits
              of the 8 KB CHR bank;
     data     .... ..CC  the low bits of the CHR bank.
   Action 52 has three 512 KB chips, in sockets 0, 1 and 3: socket 2 is
   empty, so chip 3 is the file's third 512 KB. The wiki says an empty
   socket reads as open bus; here chip 2 is the third chip too, as in
   Mesen (neither game selects it). The games expect $00 written to
   $8000 at power-on and reset. The wiki says the 4-bit RAM once
   described at $4020-$5FFF isn't on either cartridge, so there is none. */

static void ae_write(uint16_t addr, uint8_t val) {
    int chip = addr >> 11 & 3;
    if (chip == 3) chip = 2;
    int bank = chip << 5 | (addr >> 6 & 0x1F);
    if (addr & 0x20) {
        set_prg_16k(0, bank);
        set_prg_16k(1, bank);
    } else {
        set_prg_16k(0, bank & ~1);
        set_prg_16k(1, bank | 1);
    }
    set_chr_8k((addr & 0x0F) << 2 | (val & 3));
    cart.mirroring = (addr & 0x2000) ? MIRROR_HORIZONTAL : MIRROR_VERTICAL;
}

static void ae_reset(void) {           /* the reset button */
    ppu_catch_up();
    ae_write(0x8000, 0);
    ppu_schedule();
}

/* ---- 172: TXC 22211, the Jiahe/Super Mega board (1991 Du Ma Racing).
   nesdev wiki, "INES Mapper 172": mapper 136's JV001 chip mounted upside
   down, so the CPU's data bits D0-D5 reach the chip as D5-D0. Modelled
   here in the chip's own bit order (as mapper 136 describes it), with
   the bits reversed on the way in and out. Registers where
   addr & $E103 is $4100-$4103:
     $4100 write  Mode 0: Register := Input, bits 0-3 inverted if
                  Invert; Mode 1: bits 0-3 of Register count up by one,
                  bits 4-5 stay.
     $4101 write  Invert := chip bit 0 (CPU bit 5).
     $4102 write  Input := the six bits.
     $4103 write  Mode := chip bit 0 (CPU bit 5).
     read         Register, bits 4-5 inverted if Invert; bits 6-7 open
                  bus (0 here, as the runtime's open bus).
   A write to $8000-$FFFF (its value ignored) copies Register to Output:
   Output bits 0-1 are the 8 KB CHR bank, and mirroring becomes
   horizontal with Invert clear, vertical with it set. The wiki doesn't
   say what the chip holds at power-on: here everything is 0, and the
   header's mirroring holds until the first $8000 write. PRG never
   switches. */

static struct { uint8_t input, reg, invert, mode; } txc;

static uint8_t rev6(uint8_t v) {
    uint8_t r = 0;
    for (int i = 0; i < 6; i++)
        if (v & 1 << i) r |= (uint8_t)(0x20 >> i);
    return r;
}

static void txc_write_low(uint16_t addr, uint8_t val) {
    if ((addr & 0xE100) != 0x4100) return;
    uint8_t v = rev6(val & 0x3F);
    switch (addr & 3) {
    case 0:
        if (txc.mode) txc.reg = (uint8_t)((txc.reg & 0x30) | ((txc.reg + 1) & 0x0F));
        else txc.reg = txc.input ^ (txc.invert ? 0x0F : 0);
        break;
    case 1: txc.invert = v & 1; break;
    case 2: txc.input = v; break;
    case 3: txc.mode = v & 1; break;
    }
}

static int txc_read_low(uint16_t addr) {
    if ((addr & 0xE100) != 0x4100) return -1;
    return rev6(txc.reg ^ (txc.invert ? 0x30 : 0));
}

static void txc_write(uint16_t addr, uint8_t val) {
    (void)addr; (void)val;
    set_chr_8k(txc.reg & 3);
    cart.mirroring = txc.invert ? MIRROR_VERTICAL : MIRROR_HORIZONTAL;
}

/* ---- 28: Action 53. A multicart board (nesdev wiki "Action 53 mapper").
   $5000-$5FFF selects a register with bits 7 and 0; $8000-$FFFF writes
   it. No bus conflicts.
     $00  CHR RAM bank (bits 0-1, 8 KB of 32 KB)
     $01  inner PRG bank (bits 0-3)
     $80  mode: mirroring (bits 0-1: one-screen low/high, vertical,
          horizontal), PRG mode (bits 2-3: 32 KB, 32 KB, $8000 fixed,
          $C000 fixed), game size (bits 4-5: 32-256 KB)
     $81  outer PRG bank, in 32 KB units
   In a one-screen mirroring mode, bit 4 of a write to $00 or $01 picks
   which screen. ------------------------------------------------------- */

static struct { uint8_t select, chr, inner, mode, outer; } a53;

/* The 16 KB bank at $8000 (a14 = 0) or $C000 (a14 = 1), as the wiki's
   reference implementation computes it: the inner bank supplies the low
   bits (more of them for bigger games), the outer bank the rest. The
   fixed half of a 16 KB mode acts like 32 KB mode with the smallest
   size, so it's the outer bank's first or last 16 KB. */
static int a53_bank(int a14) {
    int mode = (a53.mode >> 2) & 3, size = (a53.mode >> 4) & 3;
    if ((mode & 2) && ((mode ^ a14) & 3) == 2) mode = size = 0;
    int current = (mode & 2) ? a53.inner : (a53.inner << 1 | a14);
    int mask = (2 << size) - 1;
    return (current & mask) | ((a53.outer << 1) & ~mask);
}

static void a53_apply(void) {
    set_prg_16k(0, a53_bank(0));
    set_prg_16k(1, a53_bank(1));
    set_chr_8k(a53.chr & 3);
    static const enum mirroring mir[4] = {
        MIRROR_SINGLE_LOW, MIRROR_SINGLE_HIGH, MIRROR_VERTICAL, MIRROR_HORIZONTAL };
    cart.mirroring = mir[a53.mode & 3];
}

static void a53_select(uint16_t addr, uint8_t val) {
    if (addr >= 0x5000) a53.select = val & 0x81;
}

static void a53_write(uint16_t addr, uint8_t val) {
    (void)addr;
    switch (a53.select) {
    case 0x00: a53.chr = val; break;
    case 0x01: a53.inner = val & 0x0F; break;
    case 0x80: a53.mode = val; break;
    case 0x81: a53.outer = val; break;
    }
    if (a53.select <= 0x01 && (a53.mode & 2) == 0)     /* one-screen mode */
        a53.mode = (uint8_t)((a53.mode & ~1) | ((val >> 4) & 1));
    a53_apply();
}

static void a53_reset(void) {
    /* The wiki only promises the last 16 KB at $C000; this is the state
       it suggests a menu sets up (32 KB mode, the last 32 KB). */
    a53.outer = 0xFF;
    a53.mode = 0x02;
    a53.inner = a53.chr = a53.select = 0;
    /* 32 KB of CHR RAM, unless an NES 2.0 header says how much. */
    if (cart.chr_is_ram && !cart.nes2 && cart.chr_size < 0x8000) {
        cart.chr = realloc(cart.chr, 0x8000);
        memset(cart.chr, 0, 0x8000);
        cart.chr_size = 0x8000;
    }
    a53_apply();
}

/* ---- 21, 22, 23, 25: Konami VRC2 and VRC4 (nesdev wiki "VRC2 and VRC4",
   "VRC IRQ"). The same chips, wired to different CPU address lines for
   the chip's register select bits A0 and A1:
     21  VRC4a (A1, A2) and VRC4c (A6, A7)
     22  VRC2a (A1, A0)
     23  VRC2b/VRC4f (A0, A1) and VRC4e (A2, A3)
     25  VRC2c/VRC4b (A1, A0) and VRC4d (A3, A2)
   An iNES 1.0 header can't say which wiring, and the two wirings of each
   number don't overlap, so both are decoded at once. Mappers 21, 23 and
   25 are treated as VRC4 (a superset of VRC2), 22 as VRC2. An NES 2.0
   submapper picks one (nesdev wiki "NES 2.0 submappers"):
     1  the first wiring above: VRC4a, VRC4f, VRC4b
     2  the second: VRC4c, VRC4e, VRC4d
     3  23 and 25 only: VRC2b, VRC2c (the first wiring, and a VRC2)
   A VRC2 has no IRQ, no swap mode, two mirroring modes, 4-bit CHR high
   registers and, on boards without PRG RAM, a 1-bit latch at
   $6000-$6FFF (bit 0 reads back what was written; Contra (J) checks it).
   Registers, by chip select (0-3) within each $1000 range:
     $8000      PRG bank for $8000 (or $C000 in swap mode), 5 bits
     $9000/1    mirroring: vertical, horizontal (VRC4 also one-screen
                low, high)
     $9002      VRC4: bit 1 swap mode, bit 0 PRG RAM enable (ignored here:
                the RAM stays usable)
     $A000      PRG bank for $A000
     $B000-$E003  CHR banks: two registers per 1 KB bank, low 4 bits then
                high 5 bits (VRC2a drops the lowest bit of the result)
     $F000-$F003  VRC4 IRQ: latch low/high nibble, control, acknowledge
   $C000 holds the second-to-last 8 KB (or the $8000 bank in swap mode)
   and $E000 the last. ----------------------------------------------- */

static struct {
    int vrc2;                   /* a VRC2 chip (mapper 22, or submapper 3) */
    int chr_shift;              /* VRC2a (22) drops CHR's lowest bit */
    int wiring;                 /* 0 both, 1 the first, 2 the second */
    uint8_t prg0, prg1, swap, mirror;
    uint16_t chr[8];
    /* IRQ: latch, counter, control bits, and the scanline prescaler,
       valid at cycle irq_time. */
    uint8_t latch, counter, enable, enable_after_ack, cycle_mode;
    int prescaler;
    uint64_t irq_time;
} vrc;

/* The address lines each wiring uses for A0 and A1: [mapper][wiring]. */
static int vrc_lines(int wiring, int *a0, int *a1) {
    static const int lines[3][2][2] = {
        { {1, 2}, {6, 7} },             /* 21: VRC4a, VRC4c */
        { {0, 1}, {2, 3} },             /* 23: VRC4f/VRC2b, VRC4e */
        { {1, 0}, {3, 2} },             /* 25: VRC4b/VRC2c, VRC4d */
    };
    int m = cart.mapper == 21 ? 0 : cart.mapper == 23 ? 1 : 2;
    *a0 = lines[m][wiring][0];
    *a1 = lines[m][wiring][1];
    return 0;
}

static int vrc_select(uint16_t addr) {
    int a0 = 0, a1 = 0;
    if (cart.mapper == 22) {                    /* VRC2a: A1, A0 */
        a0 = (addr >> 1) & 1;
        a1 = addr & 1;
    } else {
        for (int w = 0; w < 2; w++) {
            if (vrc.wiring && vrc.wiring != w + 1) continue;
            int l0, l1;
            vrc_lines(w, &l0, &l1);
            a0 |= (addr >> l0) & 1;
            a1 |= (addr >> l1) & 1;
        }
    }
    return a1 << 1 | a0;
}

static void vrc_apply(void) {
    set_prg_8k(vrc.swap ? 2 : 0, vrc.prg0);
    set_prg_8k(vrc.swap ? 0 : 2, -2);
    set_prg_8k(1, vrc.prg1);
    set_prg_8k(3, -1);
    for (int i = 0; i < 8; i++)
        set_chr_1k(i, vrc.chr_shift ? vrc.chr[i] >> 1 : vrc.chr[i]);
    static const enum mirroring mir[4] = {
        MIRROR_VERTICAL, MIRROR_HORIZONTAL, MIRROR_SINGLE_LOW, MIRROR_SINGLE_HIGH };
    cart.mirroring = mir[vrc.vrc2 ? vrc.mirror & 1 : vrc.mirror & 3];
}

/* The IRQ counter counts up and trips the IRQ when it passes $FF,
   reloading from the latch. In cycle mode it's clocked every CPU cycle; in
   scanline mode by a prescaler that starts at 341 and loses 3 each cycle,
   clocking the counter and adding 341 whenever it reaches 0 or below
   (114, 114, 113 cycles: a scanline). Nothing is clocked while disabled.
   Worked out a clock at a time, not a cycle at a time. */
static uint64_t vrc_cycles_to_clock(void) {
    return vrc.cycle_mode ? 1 : (uint64_t)((vrc.prescaler + 2) / 3);
}

static void vrc_irq_catch_up(void) {
    uint64_t now = cycles;
    if (!vrc.enable) { vrc.irq_time = now; return; }
    for (;;) {
        uint64_t k = vrc_cycles_to_clock();
        if (vrc.irq_time + k > now) break;
        vrc.irq_time += k;
        if (!vrc.cycle_mode) vrc.prescaler += 341 - 3 * (int)k;
        if (vrc.counter == 0xFF) {
            vrc.counter = vrc.latch;
            cpu_set_irq_at(IRQ_MAPPER, 1, vrc.irq_time * 3);
        } else {
            vrc.counter++;
        }
    }
    if (!vrc.cycle_mode) vrc.prescaler -= 3 * (int)(now - vrc.irq_time);
    vrc.irq_time = now;
}

static void vrc_irq_schedule(void) {
    if (!vrc.enable) return;
    /* When the counter next passes $FF. */
    uint64_t clocks = 0x100 - vrc.counter;
    uint64_t first = vrc_cycles_to_clock();
    uint64_t per = vrc.cycle_mode ? 1 : 341 / 3;    /* close enough to wake early */
    schedule_event(vrc.irq_time + first + (clocks - 1) * per);
}

/* The VRC IRQ's control and acknowledge registers (VRC4, VRC6, VRC7). */
static void vrc_irq_control(uint8_t val) {
    /* Acknowledge, reset the prescaler, and reload if enabled. */
    vrc.enable_after_ack = val & 1;
    vrc.enable = (val >> 1) & 1;
    vrc.cycle_mode = (val >> 2) & 1;
    vrc.prescaler = 341;
    if (vrc.enable) vrc.counter = vrc.latch;
    cpu_set_irq(IRQ_MAPPER, 0);
}

static void vrc_irq_ack(void) {     /* acknowledge; A is copied to E */
    vrc.enable = vrc.enable_after_ack;
    cpu_set_irq(IRQ_MAPPER, 0);
}

static void vrc_write(uint16_t addr, uint8_t val) {
    int reg = vrc_select(addr);
    switch (addr & 0xF000) {
    case 0x8000: vrc.prg0 = val & 0x1F; break;
    case 0xA000: vrc.prg1 = val & 0x1F; break;
    case 0x9000:
        if (vrc.vrc2 || reg < 2) vrc.mirror = val;
        else if (reg == 2) vrc.swap = (val >> 1) & 1;
        break;
    case 0xB000: case 0xC000: case 0xD000: case 0xE000: {
        int bank = ((addr >> 12) - 0xB) * 2 + (reg >> 1);
        if (reg & 1)
            vrc.chr[bank] = (uint16_t)((vrc.chr[bank] & 0x0F) | (val & (vrc.vrc2 ? 0x0F : 0x1F)) << 4);
        else
            vrc.chr[bank] = (uint16_t)((vrc.chr[bank] & ~0x0F) | (val & 0x0F));
        break;
    }
    case 0xF000:
        if (vrc.vrc2) break;
        vrc_irq_catch_up();
        switch (reg) {
        case 0: vrc.latch = (uint8_t)((vrc.latch & 0xF0) | (val & 0x0F)); break;
        case 1: vrc.latch = (uint8_t)((vrc.latch & 0x0F) | (val & 0x0F) << 4); break;
        case 2: vrc_irq_control(val); break;
        case 3: vrc_irq_ack(); break;
        }
        break;
    }
    vrc_apply();
}

static void vrc_reset(void) {
    memset(&vrc, 0, sizeof vrc);
    vrc.chr_shift = cart.mapper == 22;
    vrc.vrc2 = cart.mapper == 22 || cart.submapper == 3;
    vrc.wiring = cart.mapper == 22 ? 0 : cart.submapper == 3 ? 1 : cart.submapper;
    /* The VRC2's latch, where there's no PRG RAM to answer at $6000. */
    mapper.latch6000 = vrc.vrc2 && !(cart.prg_ram_size + cart.prg_nvram_size);
    vrc.prg1 = 1;
    vrc.prescaler = 341;
    vrc.irq_time = cycles;
    vrc_apply();
    if (!vrc.vrc2) {
        mapper.catch_up = vrc_irq_catch_up;
        mapper.schedule = vrc_irq_schedule;
    }
}

/* ---- 9, 10: MMC2 and MMC4 (nesdev wiki "MMC2", "MMC4"). Two 4 KB CHR
   banks per pattern table, chosen by a latch that flips when the PPU
   reads tile $FD or $FE's second plane: $xFD8 sets it to $FD, $xFE8 to
   $FE. On MMC2 the left table ($0000) only reacts to exactly $0FD8/$0FE8
   (a tile's top row); the right table, and both on MMC4, to the whole
   row range $xFD8-$xFDF / $xFE8-$xFEF. The latch changes after the read,
   so the switching tile itself still comes from the old bank.
     $A000  PRG bank: 8 KB at $8000 (MMC2; the last three 8 KB fixed) or
            16 KB (MMC4; the last 16 KB fixed)
     $B000  CHR bank for $0000 when latch 0 = $FD     $C000  ... = $FE
     $D000  CHR bank for $1000 when latch 1 = $FD     $E000  ... = $FE
     $F000  mirroring: 0 vertical, 1 horizontal
   The wiki doesn't give the power-on latch state; both start at $FE. ---- */

static struct { uint8_t chr[4], latch[2]; } mmc2;

static void mmc2_apply_chr(void) {
    set_chr_4k(0, mmc2.chr[mmc2.latch[0] == 0xFD ? 0 : 1]);
    set_chr_4k(1, mmc2.chr[mmc2.latch[1] == 0xFD ? 2 : 3]);
}

static void mmc2_write(uint16_t addr, uint8_t val) {
    switch (addr & 0xF000) {
    case 0xA000:
        if (cart.mapper == 9) set_prg_8k(0, val & 0x0F);
        else set_prg_16k(0, val & 0x0F);
        break;
    case 0xB000: mmc2.chr[0] = val & 0x1F; break;
    case 0xC000: mmc2.chr[1] = val & 0x1F; break;
    case 0xD000: mmc2.chr[2] = val & 0x1F; break;
    case 0xE000: mmc2.chr[3] = val & 0x1F; break;
    case 0xF000: cart.mirroring = (val & 1) ? MIRROR_HORIZONTAL : MIRROR_VERTICAL; break;
    }
    mmc2_apply_chr();
}

static void mmc2_chr_fetched(uint16_t addr) {
    int table = addr >> 12;
    uint16_t low = addr & 0x0FFF;
    int exact = cart.mapper == 9 && table == 0;     /* MMC2's left table */
    uint8_t to = 0;
    if (exact ? low == 0xFD8 : (low & 0xFF8) == 0xFD8) to = 0xFD;
    else if (exact ? low == 0xFE8 : (low & 0xFF8) == 0xFE8) to = 0xFE;
    if (to && mmc2.latch[table] != to) {
        mmc2.latch[table] = to;
        mmc2_apply_chr();
    }
}

static void mmc2_reset(void) {
    memset(&mmc2, 0, sizeof mmc2);
    mmc2.latch[0] = mmc2.latch[1] = 0xFE;
    if (cart.mapper == 9) {
        set_prg_8k(0, 0); set_prg_8k(1, -3); set_prg_8k(2, -2); set_prg_8k(3, -1);
    } else {
        set_prg_16k(0, 0); set_prg_16k(1, -1);
    }
    mmc2_apply_chr();
    mapper.chr_fetched = mmc2_chr_fetched;
}

/* ---- 5: MMC5 (nesdev wiki "MMC5"), with its extended attributes,
   vertical split and sound.
     $5100     PRG mode: 0 = 32 KB, 1 = 16+16, 2 = 16+8+8, 3 = 8 KB x 4
     $5101     CHR mode: 0 = 8 KB, 1 = 4 KB, 2 = 2 KB, 3 = 1 KB banks
     $5102/3   PRG RAM write protect: writable only when $02 / $01
     $5104     ExRAM mode: 0/1 nametable (CPU writes while rendering),
               2 CPU RAM, 3 CPU read-only
     $5105     nametable mapping, 2 bits per quarter: CIRAM 0, CIRAM 1,
               ExRAM, fill mode
     $5106/7   fill-mode tile and palette
     $5113     8 KB RAM bank at $6000
     $5114-7   PRG banks (bit 7: ROM, else RAM; $5117 always ROM)
     $5120-7   CHR "A" set, $5128-B CHR "B" set, $5130 upper CHR bits
     $5200     vertical split: bit 7 on, bit 6 right side, bits 0-4 the
               threshold tile; $5201 its vertical scroll, $5202 its 4 KB
               CHR bank (see mmc5_split_tile)
     $5203/4   scanline IRQ compare / enable (read: pending, in frame)
     $5205/6   8 x 8 multiplier (read: product low, high)
     $5C00-$5FFF  ExRAM (1 KB)
   PRG RAM: the wiki suggests always emulating the 64 KB superset; bank 0
   is the cartridge's (battery-saved) 8 KB, banks 1-7 live here. ---- */

static uint8_t mmc5_ram[7][0x2000];

static struct {
    uint8_t prg_mode, chr_mode, protect1, protect2, exram_mode, nt_map;
    uint8_t fill_tile, fill_attr, upper, last_b, irq_target, irq_enable;
    uint8_t irq_pending, in_frame, counter, mul_a, mul_b;
    uint8_t prg[5];                 /* $5113-$5117 */
    uint16_t chr[12];               /* $5120-$512B, in 1 KB units */
    int phase;                      /* from the PPU: 0 none, 1 bg, 2 sprites */
    uint8_t exram[0x400];
    uint8_t split_ctrl, split_scroll, split_bank;   /* $5200-$5202 */
    uint8_t split_start;            /* $5201 as loaded for this frame */
    int split_base;                 /* the line the split's count starts on */
} mmc5;

static uint8_t *mmc5_ram_bank(int n) {
    n &= 7;
    return n == 0 ? cart.prg_ram : mmc5_ram[n - 1];
}

/* One 8 KB CPU slot: a ROM bank, or (bit 7 clear) a RAM bank. */
static void mmc5_prg_slot(int slot, int value, int rom) {
    if (rom) {
        set_prg_8k(slot, value & 0x7F);
    } else {
        int bank = 0x1000 + (value & 7);   /* never matches a ROM bank */
        if (mapper.prg_bank[slot] != bank) mapper.bank_changed = 1;
        mapper.prg_bank[slot] = bank;
        mapper.prg[slot] = mmc5_ram_bank(value);
    }
}

static void mmc5_apply_prg(void) {
    uint8_t *r = mmc5.prg;          /* r[0] = $5113 ... r[4] = $5117 */
    mapper.ram6000 = mmc5_ram_bank(r[0]);
    mapper.ram6000_size = 0x2000;         /* MMC5 keeps its own 64 KB */
    mapper.prg_ram_readonly = !(mmc5.protect1 == 2 && mmc5.protect2 == 1);
    switch (mmc5.prg_mode & 3) {
    case 0:
        for (int i = 0; i < 4; i++) mmc5_prg_slot(i, (r[4] & 0x7C) + i, 1);
        break;
    case 1:
        mmc5_prg_slot(0, (r[2] & 0x7E), r[2] >> 7);
        mmc5_prg_slot(1, (r[2] & 0x7E) + 1, r[2] >> 7);
        mmc5_prg_slot(2, (r[4] & 0x7E), 1);
        mmc5_prg_slot(3, (r[4] & 0x7E) + 1, 1);
        break;
    case 2:
        mmc5_prg_slot(0, (r[2] & 0x7E), r[2] >> 7);
        mmc5_prg_slot(1, (r[2] & 0x7E) + 1, r[2] >> 7);
        mmc5_prg_slot(2, r[3], r[3] >> 7);
        mmc5_prg_slot(3, r[4], 1);
        break;
    case 3:
        mmc5_prg_slot(0, r[1], r[1] >> 7);
        mmc5_prg_slot(1, r[2], r[2] >> 7);
        mmc5_prg_slot(2, r[3], r[3] >> 7);
        mmc5_prg_slot(3, r[4], 1);
        break;
    }
}

/* Which CHR set the PPU sees: with 8x16 sprites (and rendering on),
   sprites use the A set ($5120-$5127) and backgrounds the B set
   ($5128-$512B); with 8x8 sprites only the A set is used. $2007 access
   uses whichever set was written last. */
static void mmc5_apply_chr(void) {
    int big = (ppu.ctrl & 0x20) && (ppu.mask & 0x18);
    int use_b = big ? (mmc5.phase == 1 || (mmc5.phase == 0 && mmc5.last_b)) : 0;
    int size = 8 >> (mmc5.chr_mode & 3);       /* 8, 4, 2 or 1 KB */
    for (int slot = 0; slot < 8; slot++) {
        int first = slot & ~(size - 1);         /* first 1 KB of its window */
        int reg;
        if (use_b) reg = 8 + (((first & 3) + size - 1) & 3);
        else reg = first + size - 1;            /* last register of the window */
        set_chr_1k(slot, mmc5.chr[reg] + (slot - first) % (use_b && size == 8 ? 8 : size));
    }
}

/* MMC5's sound (nesdev wiki "MMC5 audio"): two pulses like the APU's
   ($5000-$5007 as $4000-$4007), but without a sweep, not muted by short
   periods, and with the envelope and length counter clocked at a fixed
   240 Hz (M2 / 7424 on the die), so length counts run twice as fast; and
   an 8-bit PCM channel written at $5011 (a write of 0 is ignored, and
   trips the PCM IRQ if $5010 bit 7 enables it). All as loud as the APU's
   channels with the same values, but inverted. The PCM read mode (the DAC
   following reads of $8000-$BFFF) isn't modelled. */
static const uint8_t mmc5_length_table[32] = {
    10, 254, 20, 2, 40, 4, 80, 6, 160, 8, 60, 10, 14, 12, 26, 14,
    12, 16, 24, 18, 48, 20, 96, 22, 192, 24, 72, 26, 16, 28, 32, 30 };
static const uint8_t mmc5_duty[4][8] = {
    { 0, 1, 0, 0, 0, 0, 0, 0 }, { 0, 1, 1, 0, 0, 0, 0, 0 },
    { 0, 1, 1, 1, 1, 0, 0, 0 }, { 1, 0, 0, 1, 1, 1, 1, 1 } };

static struct {
    struct {
        uint8_t ctrl, enabled, step, length, env_start, env_divider, env_decay;
        uint16_t period, timer;
    } p[2];
    uint8_t pcm, pcm_irq_enable, pcm_trip;
    int cycle;                       /* pulse timers run every 2 cycles */
    uint64_t next_frame;             /* CPU cycle of the next 240 Hz tick */
} m5a;

static void mmc5_update_irq(void) {
    cpu_set_irq_at(IRQ_MAPPER, (mmc5.irq_enable && mmc5.irq_pending) ||
                               (m5a.pcm_irq_enable && m5a.pcm_trip), ppu.dots);
}

/* The 240 Hz ticks (envelopes and length counters), up to CPU cycle
   `upto`. They keep their own time, so length counters run (and $5015
   reads right) even when no sound is being made. */
static void mmc5_frames(uint64_t upto) {
    while (m5a.next_frame <= upto) {
        m5a.next_frame += 7424;
        for (int i = 0; i < 2; i++) {
            __typeof__(m5a.p[0]) *q = &m5a.p[i];
            if (q->env_start) {
                q->env_start = 0;
                q->env_decay = 15;
                q->env_divider = q->ctrl & 15;
            } else if (q->env_divider == 0) {
                q->env_divider = q->ctrl & 15;
                if (q->env_decay) q->env_decay--;
                else if (q->ctrl & 0x20) q->env_decay = 15;     /* loop */
            } else {
                q->env_divider--;
            }
            if (q->length && !(q->ctrl & 0x20)) q->length--;
        }
    }
}

static float mmc5_audio_step(uint64_t cycle) {
    mmc5_frames(cycle);
    m5a.cycle ^= 1;
    int sum = 0;
    for (int i = 0; i < 2; i++) {
        __typeof__(m5a.p[0]) *q = &m5a.p[i];
        if (m5a.cycle) {                    /* timers every other cycle */
            if (q->timer == 0) { q->timer = q->period; q->step = (q->step - 1) & 7; }
            else q->timer--;
        }
        if (q->length && mmc5_duty[q->ctrl >> 6][q->step])
            sum += (q->ctrl & 0x10) ? (q->ctrl & 15) : q->env_decay;
    }
    /* The APU's mixing curves, for the same values (inverted). */
    float out = sum ? 95.88f / (8128.0f / sum + 100.0f) : 0.0f;
    if (m5a.pcm) out += 159.79f / (1.0f / (m5a.pcm / 22638.0f) + 100.0f);
    return -out;
}

static void mmc5_sound_reset(void) {
    memset(&m5a, 0, sizeof m5a);
    m5a.next_frame = cycles + 7424;
}

static void mmc5_sound_write(uint16_t addr, uint8_t val) {
    apu_catch_up();                 /* the change lands on this cycle */
    mmc5_frames(cycles);
    if (addr <= 0x5007) {
        __typeof__(m5a.p[0]) *q = &m5a.p[(addr >> 2) & 1];
        switch (addr & 3) {
        case 0: q->ctrl = val; break;
        case 1: break;              /* no sweep */
        case 2: q->period = (uint16_t)((q->period & 0x700) | val); break;
        case 3:
            q->period = (uint16_t)((q->period & 0xFF) | (val & 7) << 8);
            if (q->enabled) q->length = mmc5_length_table[val >> 3];
            q->step = 0;
            q->env_start = 1;
            break;
        }
    } else if (addr == 0x5010) {
        m5a.pcm_irq_enable = val >> 7;
        mmc5_update_irq();
    } else if (addr == 0x5011) {
        if (val) m5a.pcm = val;
        m5a.pcm_trip = val == 0;
        mmc5_update_irq();
    } else if (addr == 0x5015) {
        for (int i = 0; i < 2; i++) {
            m5a.p[i].enabled = (val >> i) & 1;
            if (!m5a.p[i].enabled) m5a.p[i].length = 0;
        }
    }
}

static void mmc5_scanline(int line) {
    if (line < 0) { mmc5.in_frame = 0; return; }
    if (!mmc5.in_frame) {
        mmc5.in_frame = 1;
        mmc5.counter = 0;
        mmc5.irq_pending = 0;       /* scanline 0 acknowledges */
    } else if (++mmc5.counter == mmc5.irq_target && mmc5.irq_target) {
        mmc5.irq_pending = 1;
    }
    mmc5_update_irq();
}

static void mmc5_phase(int phase) {
    if (phase != mmc5.phase) { mmc5.phase = phase; mmc5_apply_chr(); }
}

static uint8_t mmc5_nt_read(uint16_t addr) {
    uint16_t off = addr & 0x3FF;
    switch ((mmc5.nt_map >> (((addr >> 10) & 3) * 2)) & 3) {
    case 0: return ppu.nametables[off];
    case 1: return ppu.nametables[0x400 | off];
    case 2: return mmc5.exram_mode < 2 ? mmc5.exram[off] : 0;
    default: {
        uint8_t c = mmc5.fill_attr & 3;
        return off < 0x3C0 ? mmc5.fill_tile : (uint8_t)(c | c << 2 | c << 4 | c << 6);
    }
    }
}

static void mmc5_nt_write(uint16_t addr, uint8_t val) {
    uint16_t off = addr & 0x3FF;
    switch ((mmc5.nt_map >> (((addr >> 10) & 3) * 2)) & 3) {
    case 0: ppu.nametables[off] = val; break;
    case 1: ppu.nametables[0x400 | off] = val; break;
    case 2: if (mmc5.exram_mode < 2) mmc5.exram[off] = val; break;
    default: break;                 /* fill mode: nothing to write to */
    }
}

static void mmc5_write_low(uint16_t addr, uint8_t val) {
    if (addr >= 0x5C00) {
        /* Modes 0/1: CPU writes only land while rendering; 2: always. */
        if (mmc5.exram_mode == 2 || (mmc5.exram_mode < 2 && mmc5.in_frame))
            mmc5.exram[addr - 0x5C00] = val;
        return;
    }
    switch (addr) {
    case 0x5100: mmc5.prg_mode = val & 3; mmc5_apply_prg(); break;
    case 0x5101: mmc5.chr_mode = val & 3; mmc5_apply_chr(); break;
    case 0x5102: mmc5.protect1 = val & 3; mmc5_apply_prg(); break;
    case 0x5103: mmc5.protect2 = val & 3; mmc5_apply_prg(); break;
    case 0x5104: mmc5.exram_mode = val & 3; break;
    case 0x5105: mmc5.nt_map = val; break;
    case 0x5106: mmc5.fill_tile = val; break;
    case 0x5107: mmc5.fill_attr = val & 3; break;
    case 0x5113: case 0x5114: case 0x5115: case 0x5116: case 0x5117:
        mmc5.prg[addr - 0x5113] = addr == 0x5117 ? (val | 0x80) : val;
        mmc5_apply_prg();
        break;
    case 0x5130: mmc5.upper = val & 3; break;
    case 0x5203: mmc5.irq_target = val; break;
    case 0x5204:
        mmc5.irq_enable = val >> 7;
        mapper.watch_scanlines = mmc5.irq_enable;
        mmc5_update_irq();
        break;
    case 0x5205: mmc5.mul_a = val; break;
    case 0x5206: mmc5.mul_b = val; break;
    default:
        if (addr >= 0x5120 && addr <= 0x512B) {
            /* Stored in 1 KB units, by the CHR mode at the time of the
               write; $5130 supplies the top bits in 1 and 2 KB modes. */
            uint16_t v;
            switch (mmc5.chr_mode & 3) {
            case 3:  v = (uint16_t)(mmc5.upper << 8 | val); break;
            case 2:  v = (uint16_t)((mmc5.upper & 1) << 9 | val << 1); break;
            case 1:  v = (uint16_t)(val << 2); break;
            default: v = (uint16_t)((val & 0x7F) << 3); break;
            }
            mmc5.chr[addr - 0x5120] = v;
            mmc5.last_b = addr >= 0x5128;
            mmc5_apply_chr();
        }
        if (addr <= 0x5015) mmc5_sound_write(addr, val);
        break;
    case 0x5200: mmc5.split_ctrl = val; break;
    case 0x5201: mmc5.split_scroll = val; break;
    case 0x5202: mmc5.split_bank = val; break;
    }
}

static int mmc5_read_low(uint16_t addr) {
    if (addr >= 0x5C00)
        return mmc5.exram_mode >= 2 ? mmc5.exram[addr - 0x5C00] : -1;
    switch (addr) {
    case 0x5010: {                  /* PCM IRQ (acknowledged by reading) */
        int v = (m5a.pcm_trip && m5a.pcm_irq_enable) << 7;
        m5a.pcm_trip = 0;
        mmc5_update_irq();
        return v;
    }
    case 0x5015:
        apu_catch_up();
        mmc5_frames(cycles);
        return (m5a.p[0].length > 0) | (m5a.p[1].length > 0) << 1;
    case 0x5204: {
        uint8_t v = (uint8_t)(mmc5.irq_pending << 7 | mmc5.in_frame << 6);
        mmc5.irq_pending = 0;       /* reading acknowledges */
        mmc5_update_irq();
        return v;
    }
    case 0x5205: return (mmc5.mul_a * mmc5.mul_b) & 0xFF;
    case 0x5206: return (mmc5.mul_a * mmc5.mul_b) >> 8;
    }
    return -1;
}

/* The vertical split (nesdev wiki "MMC5"): with $5200 bit 7 set, ExRAM
   mode 0 or 1, and rendering on, the tiles before the threshold (left
   side) or from it on (right side) come from ExRAM as a nametable of
   their own, with patterns from the 4 KB bank in $5202 (whatever the CHR
   mode and $5130 say) and no horizontal scrolling.
   The wiki leaves three things open; chosen here:
   - Tiles are counted as the PPU fetches them for a line: 0 and 1 at
     dots 321-336 of the line before, then 2-33. So tile n is column n,
     moved left by fine X like the rest.
   - The split's own vertical position starts from $5201 (loaded on the
     pre-render line) and moves one pixel a line. From 0-239 it wraps at
     240 back to 0; from 240-255 it reads the attribute rows as tiles
     until it wraps at 256, then goes on from 0.
   - Tile n on split row r is ExRAM byte r * 32 + (n & 31), and its
     attribute is ExRAM $3C0 + (r / 4) * 8 + (n & 31) / 4, the quarter
     chosen as the PPU does. */
static int mmc5_split_y(int line) {
    int start = mmc5.split_start;
    if (start < 240) return (start + line) % 240;
    int k = 256 - start;                    /* lines on the attribute rows */
    return line < k ? start + line : (line - k) % 240;
}

static int mmc5_split_tile(int tile, uint8_t *name, uint8_t *palette,
                           const uint8_t **chr4k, int *fine_y) {
    /* The line this tile will be drawn on. Until the MMC5 has seen the
       frame start (its in-frame flag, as for the IRQ counter), that line
       is the first one: the split's count starts there, from $5201 as it
       is then. So rendering turned off and on again mid-frame restarts
       the split from its scroll value at the line where it came back. */
    int line = tile >= 2 ? ppu.scanline : ppu.scanline == 261 ? 0 : ppu.scanline + 1;
    if (!mmc5.in_frame) {
        mmc5.split_base = line;
        mmc5.split_start = mmc5.split_scroll;
    }
    if (!(mmc5.split_ctrl & 0x80) || mmc5.exram_mode >= 2 || !(ppu.mask & 0x18))
        return 0;
    int threshold = mmc5.split_ctrl & 0x1F;
    int inside = (mmc5.split_ctrl & 0x40) ? tile >= threshold : tile < threshold;
    if (!inside) return 0;
    int y = mmc5_split_y(line - mmc5.split_base);
    int row = y >> 3, col = tile & 31;
    *name = mmc5.exram[(row * 32 + col) & 0x3FF];
    uint8_t attr = mmc5.exram[0x3C0 + ((row >> 2) & 7) * 8 + (col >> 2)];
    *palette = (attr >> (((row & 2) << 1) | (col & 2))) & 3;
    *chr4k = cart.chr + ((size_t)mmc5.split_bank * 0x1000) % cart.chr_size;
    *fine_y = y & 7;
    return 1;
}

/* Extended attribute mode (ExRAM mode 1, rendering on): each background
   tile's ExRAM byte (same position as its nametable byte, the same for
   all four nametables) gives its palette (bits 6-7) and a 4 KB CHR bank
   (bits 0-5, with $5130 above them), ignoring the CHR registers. */
static int mmc5_bg_tile(uint16_t v, int tile, uint8_t *name, uint8_t *palette,
                        const uint8_t **chr4k, int *fine_y) {
    if (mmc5_split_tile(tile, name, palette, chr4k, fine_y)) return 1;
    if (mmc5.exram_mode != 1 || !(ppu.mask & 0x18)) return 0;
    uint8_t e = mmc5.exram[v & 0x3FF];
    size_t bank = (size_t)(mmc5.upper << 6 | (e & 0x3F));
    *palette = e >> 6;
    *chr4k = cart.chr + (bank * 0x1000) % cart.chr_size;
    *fine_y = (v >> 12) & 7;
    return 1;
}

/* CPU writes to $8000-$DFFF land in RAM when RAM is mapped there. */
static void mmc5_write(uint16_t addr, uint8_t val) {
    int slot = (addr >> 13) & 3;
    if (mapper.prg_bank[slot] >= 0x1000 && !mapper.prg_ram_readonly)
        mapper.prg[slot][addr & 0x1FFF] = val;
}

static void mmc5_reset(void) {
    memset(&mmc5, 0, sizeof mmc5);
    mmc5.prg_mode = 3;
    mmc5.chr_mode = 3;
    mmc5.protect1 = 1;
    mmc5.protect2 = 2;
    mmc5.exram_mode = 3;
    for (int i = 0; i < 5; i++) mmc5.prg[i] = 0xFF;
    mmc5_apply_prg();
    mmc5_apply_chr();
    mapper.ppu_phase = mmc5_phase;
    mapper.nt_read = mmc5_nt_read;
    mapper.nt_write = mmc5_nt_write;
    mapper.scanline = mmc5_scanline;
    mapper.bg_tile = mmc5_bg_tile;
    mmc5_sound_reset();
    mapper.audio_step = mmc5_audio_step;
    write_low = mmc5_write_low;
    read_low = mmc5_read_low;
}

/* ---- 24, 26: Konami VRC6 (nesdev wiki "VRC6", "VRC6 audio"). Mapper 26
   swaps address lines A0 and A1. Registers (addr & $F003):
     $8000  16 KB PRG bank at $8000      $C000  8 KB PRG bank at $C000
            (the last 8 KB is fixed at $E000; 8 KB of PRG RAM at $6000)
     $B003  banking style: bits 2-3 mirroring (vertical, horizontal,
            one-screen low, high) in mode 0, the only one Konami's games
            used; the other modes and CHR-ROM nametables aren't modelled
     $D000-$E003  eight 1 KB CHR banks
     $F000  IRQ latch, $F001 control, $F002 acknowledge (the VRC IRQ)
   Sound, three channels summed on a linear DAC; at full volume the
   pulses roughly match the APU's pulses, inverted:
     $9000-2, $A000-2  pulses: MDDD VVVV (mode, duty (D+1)/16, volume),
            period low, E... FFFF (enable, period high); one 16-step duty
            cycle per 16 periods: CPU / (16 * (t + 1))
     $B000-2  sawtooth: ..AA AAAA (rate), period low, E... FFFF. Every
            other period the rate is added to an 8-bit accumulator; after
            six adds it resets: CPU / (14 * (t + 1)). Output: its top
            5 bits.
     $9003  bit 0 halts all three; bit 1 / bit 2 shift the periods right
            by 4 / 8 (16x / 256x the pitch)  ---------------------------- */

static struct {
    uint8_t ctrl[3];                /* $9000, $A000, $B000 */
    uint16_t period[3];
    uint8_t enable[3];
    uint16_t timer[3];
    uint8_t step[2];                /* pulse duty position, 15 down to 0 */
    uint8_t saw_clock, saw_acc;     /* sawtooth: 0-13 and the accumulator */
    uint8_t freq_ctrl;              /* $9003 */
} vrc6;

static float vrc6_audio_step(uint64_t cycle) {
    (void)cycle;
    if (!(vrc6.freq_ctrl & 1)) {
        int shift = (vrc6.freq_ctrl & 4) ? 8 : (vrc6.freq_ctrl & 2) ? 4 : 0;
        for (int c = 0; c < 3; c++) {
            if (!vrc6.enable[c]) continue;
            if (vrc6.timer[c] == 0) {
                vrc6.timer[c] = (uint16_t)(vrc6.period[c] >> shift);
                if (c < 2) {
                    vrc6.step[c] = (vrc6.step[c] - 1) & 15;
                } else {
                    vrc6.saw_clock = (uint8_t)((vrc6.saw_clock + 1) % 14);
                    if (vrc6.saw_clock == 0) vrc6.saw_acc = 0;
                    else if (!(vrc6.saw_clock & 1))
                        vrc6.saw_acc = (uint8_t)(vrc6.saw_acc + (vrc6.ctrl[2] & 0x3F));
                }
            } else {
                vrc6.timer[c]--;
            }
        }
    }
    int out = 0;
    for (int c = 0; c < 2; c++) {
        uint8_t r = vrc6.ctrl[c];
        if (vrc6.enable[c] && ((r & 0x80) || vrc6.step[c] <= ((r >> 4) & 7)))
            out += r & 15;
    }
    if (vrc6.enable[2]) out += vrc6.saw_acc >> 3;
    /* A full-volume pulse (15) matches an APU pulse at 15 (0.1494). */
    return -(float)out * (0.1494f / 15.0f);
}

static void vrc6_apply(uint8_t b003) {
    static const enum mirroring mir[4] = {
        MIRROR_VERTICAL, MIRROR_HORIZONTAL, MIRROR_SINGLE_LOW, MIRROR_SINGLE_HIGH };
    cart.mirroring = mir[(b003 >> 2) & 3];
}

/* The sound registers: $9000-$9003, $A000-$A002, $B000-$B002 (addr
   already reduced to $x000-$x003; $B003 isn't sound). */
static void vrc6_sound_write(uint16_t addr, uint8_t val) {
    int reg = addr & 3;
    if (addr == 0x9003) { apu_catch_up(); vrc6.freq_ctrl = val; return; }
    if (reg == 3) return;
    int c = ((addr >> 12) & 0xF) - 9;
    apu_catch_up();                 /* the change lands on this cycle */
    if (reg == 0) vrc6.ctrl[c] = val;
    else if (reg == 1) vrc6.period[c] = (uint16_t)((vrc6.period[c] & 0xF00) | val);
    else {
        vrc6.period[c] = (uint16_t)((vrc6.period[c] & 0xFF) | (val & 0x0F) << 8);
        vrc6.enable[c] = val >> 7;
        if (!vrc6.enable[c]) {      /* disabled: duty and saw reset */
            if (c < 2) vrc6.step[c] = 15;
            else { vrc6.saw_acc = 0; vrc6.saw_clock = 0; }
        }
    }
}

static void vrc6_sound_reset(void) {
    memset(&vrc6, 0, sizeof vrc6);
    vrc6.step[0] = vrc6.step[1] = 15;
}

static void vrc6_write(uint16_t addr, uint8_t val) {
    if (cart.mapper == 26)                       /* A0 and A1 swapped */
        addr = (uint16_t)((addr & ~3) | (addr & 1) << 1 | (addr >> 1 & 1));
    addr &= 0xF003;
    int reg = addr & 3;
    switch (addr & 0xF000) {
    case 0x8000: set_prg_16k(0, val & 0x0F); break;
    case 0xC000: set_prg_8k(2, val & 0x1F); break;
    case 0x9000: case 0xA000: case 0xB000:
        if (addr == 0xB003) vrc6_apply(val);
        else vrc6_sound_write(addr, val);
        break;
    case 0xD000: case 0xE000:
        set_chr_1k(((addr >> 12) - 0xD) * 4 + reg, val);
        break;
    case 0xF000:
        vrc_irq_catch_up();
        if (reg == 0) vrc.latch = val;
        else if (reg == 1) vrc_irq_control(val);
        else if (reg == 2) vrc_irq_ack();
        break;
    }
}

static void vrc6_reset(void) {
    memset(&vrc, 0, sizeof vrc);
    vrc6_sound_reset();
    vrc.prescaler = 341;
    vrc.irq_time = cycles;
    set_prg_16k(0, 0); set_prg_8k(2, -2); set_prg_8k(3, -1);
    mapper.catch_up = vrc_irq_catch_up;
    mapper.schedule = vrc_irq_schedule;
    mapper.audio_step = vrc6_audio_step;
}

/* ---- 69: Sunsoft FME-7, with the 5B's sound (nesdev wiki "Sunsoft
   FME-7", "Sunsoft 5B audio"). $8000 selects a command, $A000 runs it:
     $0-$7  1 KB CHR banks
     $8     $6000: ERbBBBBB, bit 6 RAM (else ROM), bit 7 RAM enable (RAM
            selected but not enabled reads open bus)
     $9-$B  8 KB PRG banks at $8000, $A000, $C000 ($E000: the last bank)
     $C     mirroring: vertical, horizontal, one-screen low, high
     $D     IRQ: bit 7 counter on, bit 0 IRQ on; any write acknowledges
     $E/$F  IRQ counter low/high: counts down every CPU cycle while on,
            IRQ when it wraps from $0000 to $FFFF
   5B sound: $C000 selects register 0-15 (writes to $E000 are ignored if
   its top 4 bits aren't 0), $E000 writes it. A YM2149:
     $0-$5  tone periods A, B, C (12 bits): CPU / (32 * period)
     $6     noise period (5 bits): a 17-bit LFSR stepped every 32 * P
     $7     1 disables: bits 0-2 tone A-C, bits 3-5 noise A-C
     $8-$A  ---E VVVV: E = use the envelope, else volume V
     $B/$C  envelope period (16 bits): a step every 16 * P cycles, 32
            steps a ramp
     $D     envelope shape: continue, attack, alternate, hold
   A period of 0 acts as 1. Each channel outputs its level when (tone or
   tone off) and (noise or noise off); levels go through a 5-bit log DAC,
   1.5 dB a step, where volume V is level 2V + 1 and levels 0-1 are
   silent. How loud the 5B is against the APU isn't documented ("very
   loud", through a non-linear amplifier); here one channel at full
   volume equals an APU pulse at full volume. ------------------------ */

static struct {
    uint8_t command, irq_ctrl;
    uint16_t irq_counter;
    uint64_t irq_time;              /* cycle irq_counter is valid at */
    /* 5B */
    uint8_t select, regs[16];
    uint32_t tone_timer[3], noise_timer, env_timer, lfsr;
    uint8_t tone_out[3];
    uint8_t env_step, env_flip, env_holding;
} fme;

static float fme_dac[32];

static void fme_irq_catch_up(void) {
    uint64_t now = cycles;
    if (fme.irq_ctrl & 0x80) {
        uint64_t elapsed = now - fme.irq_time;
        if (elapsed > fme.irq_counter) {        /* wrapped past 0 */
            uint64_t at = fme.irq_time + fme.irq_counter + 1;
            if (fme.irq_ctrl & 1) cpu_set_irq_at(IRQ_MAPPER, 1, at * 3);
        }
        fme.irq_counter = (uint16_t)(fme.irq_counter - elapsed);
    }
    fme.irq_time = now;
}

static void fme_irq_schedule(void) {
    if ((fme.irq_ctrl & 0x81) == 0x81)
        schedule_event(fme.irq_time + fme.irq_counter + 1);
}

static void fme_set_6000(uint8_t v) {
    if (v & 0x40) {                             /* RAM */
        set_ram_8k(0);
        mapper.prg_ram_disabled = !(v & 0x80);
        mapper.prg_ram_readonly = 0;
    } else {                                    /* ROM, read-only */
        mapper.ram6000 = cart.prg + (size_t)((v & 0x3F) % prg_banks_8k()) * 0x2000;
        mapper.ram6000_size = 0x2000;
        mapper.prg_ram_disabled = 0;
        mapper.prg_ram_readonly = 1;
    }
}

/* The envelope's level (0-31) and its next step. */
static int fme_env_level(void) {
    int attack = (fme.regs[13] >> 2) & 1;
    if (fme.env_holding && !(fme.regs[13] & 8)) return 0;   /* shapes 0-7 */
    return (attack ^ fme.env_flip) ? fme.env_step : 31 - fme.env_step;
}

static void fme_env_clock(void) {
    if (fme.env_holding) return;
    if (++fme.env_step < 32) return;
    uint8_t shape = fme.regs[13];
    if (!(shape & 8)) { fme.env_holding = 1; return; }      /* drop to 0 */
    if (shape & 1) {                                        /* hold */
        fme.env_holding = 1;
        fme.env_step = 31;
        if (shape & 2) fme.env_flip ^= 1;
    } else {
        fme.env_step = 0;
        if (shape & 2) fme.env_flip ^= 1;                   /* alternate */
    }
}

static float fme_audio_step(uint64_t cycle) {
    (void)cycle;
    uint8_t *r = fme.regs;
    for (int c = 0; c < 3; c++) {
        if (fme.tone_timer[c] == 0) {
            uint32_t p = (uint32_t)(r[c * 2] | (r[c * 2 + 1] & 0x0F) << 8);
            fme.tone_timer[c] = 16 * (p ? p : 1) - 1;
            fme.tone_out[c] ^= 1;
        } else {
            fme.tone_timer[c]--;
        }
    }
    if (fme.noise_timer == 0) {
        uint32_t p = r[6] & 0x1F;
        fme.noise_timer = 32 * (p ? p : 1) - 1;
        uint32_t bit = (fme.lfsr ^ (fme.lfsr >> 3)) & 1;
        fme.lfsr = fme.lfsr >> 1 | bit << 16;
    } else {
        fme.noise_timer--;
    }
    if (fme.env_timer == 0) {
        uint32_t p = (uint32_t)(r[11] | r[12] << 8);
        fme.env_timer = 16 * (p ? p : 1) - 1;
        fme_env_clock();
    } else {
        fme.env_timer--;
    }
    float out = 0;
    int noise = fme.lfsr & 1;
    for (int c = 0; c < 3; c++) {
        int tone_on = !(r[7] >> c & 1), noise_on = !(r[7] >> (c + 3) & 1);
        if ((fme.tone_out[c] || !tone_on) && (noise || !noise_on)) {
            int level = (r[8 + c] & 0x10) ? fme_env_level()
                      : (r[8 + c] & 15) ? (r[8 + c] & 15) * 2 + 1 : 0;
            out += fme_dac[level];
        }
    }
    return out;
}

/* The 5B's data port ($E000), for the register selected at $C000. */
static void fme_sound_data(uint8_t val) {
    if (fme.select & 0xF0) return;
    apu_catch_up();                 /* the change lands on this cycle */
    fme.regs[fme.select & 15] = val;
    if ((fme.select & 15) == 13) {          /* new shape: restart */
        fme.env_step = 0;
        fme.env_flip = 0;
        fme.env_holding = 0;
    }
}

static void fme_sound_reset(void) {
    memset(&fme, 0, sizeof fme);
    fme.lfsr = 1;
    for (int n = 2; n < 32; n++)    /* 1.5 dB a step; full scale = APU pulse */
        fme_dac[n] = 0.1494f * powf(10.0f, (n - 31) * 1.5f / 20.0f);
}

static void fme_write(uint16_t addr, uint8_t val) {
    switch (addr & 0xE000) {
    case 0x8000: fme.command = val & 0x0F; break;
    case 0xA000: {
        uint8_t c = fme.command;
        if (c < 8) set_chr_1k(c, val);
        else if (c == 8) fme_set_6000(val);
        else if (c < 0x0C) set_prg_8k(c - 9, val & 0x3F);
        else if (c == 0x0C) {
            static const enum mirroring mir[4] = {
                MIRROR_VERTICAL, MIRROR_HORIZONTAL, MIRROR_SINGLE_LOW, MIRROR_SINGLE_HIGH };
            cart.mirroring = mir[val & 3];
        } else {
            fme_irq_catch_up();
            if (c == 0x0D) { fme.irq_ctrl = val; cpu_set_irq(IRQ_MAPPER, 0); }
            else if (c == 0x0E) fme.irq_counter = (uint16_t)((fme.irq_counter & 0xFF00) | val);
            else fme.irq_counter = (uint16_t)((fme.irq_counter & 0x00FF) | val << 8);
        }
        break;
    }
    case 0xC000: fme.select = val; break;
    case 0xE000: fme_sound_data(val); break;
    }
}

static void fme_reset(void) {
    fme_sound_reset();
    fme.irq_time = cycles;
    set_prg_8k(0, 0); set_prg_8k(1, 1); set_prg_8k(2, 2); set_prg_8k(3, -1);
    mapper.catch_up = fme_irq_catch_up;
    mapper.schedule = fme_irq_schedule;
    mapper.audio_step = fme_audio_step;
}

/* ---- 19: Namco 163 (nesdev wiki "INES Mapper 019", "Namco 163 audio").
     $4800      sound RAM data port (128 bytes, address from $F800)
     $5000/$5800  IRQ counter low / high 7 bits, bit 7 = enable: a 15-bit
                counter counting up every CPU cycle, firing at $7FFF and
                stopping there; writes acknowledge, reads return it
     $8000-$B800  1 KB CHR banks; $E0 and up select nametable RAM (page
                by bit 0) unless $E800 bit 6 (low table) / 7 (high) is set
     $C000-$D800  nametables: $E0 and up nametable RAM, else a CHR ROM bank
     $E000      8 KB PRG at $8000; bit 6 turns the sound off
     $E800      8 KB PRG at $A000; bits 6-7 as above
     $F000      8 KB PRG at $C000 ($E000 holds the last 8 KB)
     $F800      sound RAM address (bit 7 auto-increment, stopping at $7F),
                and PRG RAM write protect: writable only with $4x (the
                per-2 KB protect bits aren't modelled; $4F protects all)
   Sound: channel n's registers are bytes $40 + 8 (n - 1) of sound RAM:
   frequency (18 bits), phase (24 bits), wave length 256 - 4L, wave
   address (in 4-bit samples, low nibble first), volume; $7F bits 4-6 =
   enabled channels - 1, counting down from channel 8. The chip updates
   one channel every 15 CPU cycles, adding the frequency to the phase and
   outputting (sample - 8) * volume; the outputs are averaged, as the wiki
   recommends for emulation. A full one-channel square is set 16.5 dB above
   a full APU square: the middle of the 16-17 dB measured on boards like
   Rolling Thunder (the wiki's measurements run from 11 to 19.5 dB). ---- */

static struct {
    uint8_t ram[128], addr, sound_off, e800, nt[4], chr[8];
    uint16_t irq_counter;
    uint8_t irq_enable;
    uint64_t irq_time;
    int timer, channel;             /* 15-cycle update, channel 7..0 */
    int out[8];
} n163;

static void n163_apply_chr(void) {
    mapper.chr_writable = 0;
    for (int i = 0; i < 8; i++) {
        uint8_t v = n163.chr[i];
        int ram_ok = !(n163.e800 >> (i < 4 ? 6 : 7) & 1);
        if (v >= 0xE0 && ram_ok) {
            mapper.chr[i] = ppu.nametables + (v & 1) * 0x400;
            mapper.chr_writable |= (uint8_t)(1 << i);
        } else {
            set_chr_1k(i, v);
        }
    }
}

static uint8_t n163_nt_read(uint16_t addr) {
    uint8_t v = n163.nt[(addr >> 10) & 3];
    uint16_t off = addr & 0x3FF;
    if (v >= 0xE0) return ppu.nametables[(v & 1) * 0x400 + off];
    return cart.chr[((size_t)v * 0x400 + off) % cart.chr_size];
}

static void n163_nt_write(uint16_t addr, uint8_t val) {
    uint8_t v = n163.nt[(addr >> 10) & 3];
    if (v >= 0xE0) ppu.nametables[(v & 1) * 0x400 + (addr & 0x3FF)] = val;
}

static void n163_irq_catch_up(void) {
    uint64_t now = cycles;
    if (n163.irq_enable && n163.irq_counter < 0x7FFF) {
        uint64_t left = 0x7FFFu - n163.irq_counter;
        if (now - n163.irq_time >= left) {
            n163.irq_counter = 0x7FFF;
            cpu_set_irq_at(IRQ_MAPPER, 1, (n163.irq_time + left) * 3);
        } else {
            n163.irq_counter = (uint16_t)(n163.irq_counter + (now - n163.irq_time));
        }
    }
    n163.irq_time = now;
}

static void n163_irq_schedule(void) {
    if (n163.irq_enable && n163.irq_counter < 0x7FFF)
        schedule_event(n163.irq_time + (0x7FFFu - n163.irq_counter));
}

/* How much louder than an APU square a full one-channel square is: 16.5
   dB (6.683 times), or what an NES 2.0 submapper says (nesdev wiki "NES
   2.0 submappers"): 2 no sound (1, deprecated, also has none), 3 11-13
   dB, 4 16-17 dB, 5 18-19.5 dB; the middle of each range. */
static float n163_gain = 6.683f;

static float n163_audio_step(uint64_t cycle) {
    (void)cycle;
    uint8_t *w = n163.ram;
    int count = ((w[0x7F] >> 4) & 7) + 1;
    if (!n163.sound_off && --n163.timer <= 0) {
        n163.timer = 15;
        /* Channels 8, 7, ... down to the number enabled. */
        if (n163.channel < 8 - count) n163.channel = 7;
        uint8_t *r = &w[0x40 + 8 * n163.channel];
        uint32_t phase = (uint32_t)(r[5] << 16 | r[3] << 8 | r[1]);
        uint32_t freq = (uint32_t)((r[4] & 3) << 16 | r[2] << 8 | r[0]);
        uint32_t length = 256 - (r[4] & 0xFC);
        phase = (phase + freq) % (length << 16);
        r[5] = (uint8_t)(phase >> 16); r[3] = (uint8_t)(phase >> 8); r[1] = (uint8_t)phase;
        int x = ((phase >> 16) + r[6]) & 0xFF;
        int sample = (w[x >> 1] >> ((x & 1) * 4)) & 0x0F;
        n163.out[n163.channel] = (sample - 8) * (r[7] & 0x0F);
        n163.channel--;
    }
    if (n163.sound_off) return 0;
    int sum = 0;
    for (int c = 8 - count; c < 8; c++) sum += n163.out[c];
    /* 15 * 15 from top to bottom of a full square = 16.5 dB over an APU
       square at 0.1494. */
    return (float)sum / (float)count * (0.1494f * n163_gain / 225.0f);
}

static void n163_write_low(uint16_t addr, uint8_t val) {
    if (addr >= 0x4800 && addr < 0x5000) {
        apu_catch_up();
        n163.ram[n163.addr & 0x7F] = val;
        if ((n163.addr & 0x80) && (n163.addr & 0x7F) < 0x7F) n163.addr++;
    } else if (addr >= 0x5000) {
        n163_irq_catch_up();
        if (addr < 0x5800) n163.irq_counter = (uint16_t)((n163.irq_counter & 0x7F00) | val);
        else {
            n163.irq_counter = (uint16_t)((n163.irq_counter & 0xFF) | (val & 0x7F) << 8);
            n163.irq_enable = val >> 7;
        }
        cpu_set_irq(IRQ_MAPPER, 0);
    }
}

static int n163_read_low(uint16_t addr) {
    if (addr >= 0x4800 && addr < 0x5000) {
        uint8_t v = n163.ram[n163.addr & 0x7F];
        if ((n163.addr & 0x80) && (n163.addr & 0x7F) < 0x7F) n163.addr++;
        return v;
    }
    if (addr >= 0x5000) {
        n163_irq_catch_up();
        if (addr < 0x5800) return n163.irq_counter & 0xFF;
        return (n163.irq_counter >> 8) | n163.irq_enable << 7;
    }
    return -1;
}

static void n163_write(uint16_t addr, uint8_t val) {
    switch (addr & 0xF800) {
    case 0xC000: case 0xC800: case 0xD000: case 0xD800:
        n163.nt[(addr >> 11) & 3] = val;
        break;
    case 0xE000:
        set_prg_8k(0, val & 0x3F);
        apu_catch_up();
        n163.sound_off = (val >> 6) & 1;
        break;
    case 0xE800: set_prg_8k(1, val & 0x3F); n163.e800 = val; n163_apply_chr(); break;
    case 0xF000: set_prg_8k(2, val & 0x3F); break;
    case 0xF800:
        n163.addr = val;
        mapper.prg_ram_readonly = (val & 0xF0) != 0x40 || (val & 0x0F) == 0x0F;
        break;
    default:                                    /* $8000-$BFFF: CHR */
        n163.chr[(addr >> 11) & 7] = val;
        n163_apply_chr();
        break;
    }
}

static void n163_reset(void) {
    memset(&n163, 0, sizeof n163);
    n163.irq_time = cycles;
    n163.channel = 7;
    for (int i = 0; i < 4; i++) n163.nt[i] = 0xE0 | (i & 1);   /* vertical */
    for (int i = 0; i < 8; i++) n163.chr[i] = (uint8_t)i;
    n163_apply_chr();
    set_prg_8k(0, 0); set_prg_8k(1, 1); set_prg_8k(2, 2); set_prg_8k(3, -1);
    mapper.nt_read = n163_nt_read;
    mapper.nt_write = n163_nt_write;
    mapper.catch_up = n163_irq_catch_up;
    mapper.schedule = n163_irq_schedule;
    mapper.audio_step = n163_audio_step;
    static const float gain[6] = { 6.683f, 0, 0, 3.981f, 6.683f, 8.660f };
    n163_gain = cart.submapper <= 5 ? gain[cart.submapper] : 6.683f;
    write_low = n163_write_low;
    read_low = n163_read_low;
}

/* ---- 85: Konami VRC7 (nesdev wiki "VRC7", "VRC7 audio"). VRC7a (Lagrange
   Point) decodes A4 for its second registers, VRC7b (Tiny Toon Adventures
   2) A3; both are decoded at once.
     $8000, $8010/$8008, $9000  8 KB PRG at $8000, $A000, $C000 ($E000:
                the last bank)
     $A000-$D010  eight 1 KB CHR banks
     $E000      bits 0-1 mirroring (vertical, horizontal, one-screen low,
                high), bit 6 silences the sound; bit 7 is WRAM enable on
                the mapper page and "reset sound" on the audio page (the
                wiki disagrees with itself), so it's ignored here
     $E010/$E008 IRQ latch, $F000 control, $F010/$F008 acknowledge
     $9010      sound register select, $9030 sound data
   The sound is a cut-down Yamaha OPLL: six FM channels, each a modulator
   operator phase-modulating a carrier. Exact here, from the wiki: the
   registers, the 15 built-in instruments (dumped from the chip), the
   frequency (49716 Hz * F / 2^(19 - octave), times the multiplier), the
   multiplier and feedback tables, volume (3 dB a step), modulator total
   level (0.75 dB), sustain level (3 dB), the half-sine waveforms, key on
   and off, the sustain and envelope-type bits. Approximate (the wiki
   points elsewhere for these): the envelope rates (from YM-family timing
   ratios), the modulation depth, and the output level (one channel's
   full sine spans what a full APU pulse does; undocumented). Not
   modelled: key scaling, tremolo and vibrato. Each channel is computed
   at the chip's 49716 Hz (every 36 CPU cycles) and the result held. --- */

static const uint8_t vrc7_patches[16][8] = {
    { 0 },
    { 0x03, 0x21, 0x05, 0x06, 0xE8, 0x81, 0x42, 0x27 },  /* Buzzy Bell */
    { 0x13, 0x41, 0x14, 0x0D, 0xD8, 0xF6, 0x23, 0x12 },  /* Guitar */
    { 0x11, 0x11, 0x08, 0x08, 0xFA, 0xB2, 0x20, 0x12 },  /* Wurly */
    { 0x31, 0x61, 0x0C, 0x07, 0xA8, 0x64, 0x61, 0x27 },  /* Flute */
    { 0x32, 0x21, 0x1E, 0x06, 0xE1, 0x76, 0x01, 0x28 },  /* Clarinet */
    { 0x02, 0x01, 0x06, 0x00, 0xA3, 0xE2, 0xF4, 0xF4 },  /* Synth */
    { 0x21, 0x61, 0x1D, 0x07, 0x82, 0x81, 0x11, 0x07 },  /* Trumpet */
    { 0x23, 0x21, 0x22, 0x17, 0xA2, 0x72, 0x01, 0x17 },  /* Organ */
    { 0x35, 0x11, 0x25, 0x00, 0x40, 0x73, 0x72, 0x01 },  /* Bells */
    { 0xB5, 0x01, 0x0F, 0x0F, 0xA8, 0xA5, 0x51, 0x02 },  /* Vibes */
    { 0x17, 0xC1, 0x24, 0x07, 0xF8, 0xF8, 0x22, 0x12 },  /* Vibraphone */
    { 0x71, 0x23, 0x11, 0x06, 0x65, 0x74, 0x18, 0x16 },  /* Tutti */
    { 0x01, 0x02, 0xD3, 0x05, 0xC9, 0x95, 0x03, 0x02 },  /* Fretless */
    { 0x61, 0x63, 0x0C, 0x00, 0x94, 0xC0, 0x33, 0xF6 },  /* Synth Bass */
    { 0x21, 0x72, 0x0D, 0x00, 0xC1, 0xD5, 0x56, 0x06 },  /* Sweep */
};
static const double vrc7_multiplier[16] = {
    0.5, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 12, 12, 15, 15 };

enum { EG_ATTACK, EG_DECAY, EG_SUSTAIN, EG_RELEASE, EG_OFF };

struct vrc7_op {
    double phase;                   /* in cycles */
    double att;                     /* envelope attenuation, dB (48 = off) */
    int stage;
};

static struct {
    uint8_t select, regs[0x40], silent;
    uint8_t key[6];
    struct vrc7_op op[6][2];        /* [channel][0 modulator, 1 carrier] */
    double fb[6][2];                /* the modulator's last two outputs */
    int timer;
    float out;
} vrc7;

#define VRC7_RATE 49716.0
/* Approximate envelope speeds (dB per sample) for a rate 1-15: attack
   from silence to full in 2.83 s at rate 1, decay or release through
   48 dB in 19.6 s at rate 1, each twice as fast per step. */
static double vrc7_attack_step(int r)  { return r ? 48.0 / (2.83 / (1 << (r - 1)) * VRC7_RATE) : 0; }
static double vrc7_decay_step(int r)   { return r ? 48.0 / (19.6 / (1 << (r - 1)) * VRC7_RATE) : 0; }

static const uint8_t *vrc7_patch(int ch) {
    int inst = vrc7.regs[0x30 + ch] >> 4;
    return inst ? vrc7_patches[inst] : vrc7.regs;
}

static void vrc7_envelope(int ch, int o, const uint8_t *p) {
    struct vrc7_op *op = &vrc7.op[ch][o];
    int ar = p[4 + o] >> 4, dr = p[4 + o] & 15;
    int sl = p[6 + o] >> 4, rr = p[6 + o] & 15;
    int sustained = (p[o] >> 5) & 1;            /* EG type */
    if ((vrc7.regs[0x20 + ch] >> 5) & 1) rr = 5;  /* channel sustain */
    switch (op->stage) {
    case EG_ATTACK:
        if (ar == 15) op->att = 0;
        else op->att -= vrc7_attack_step(ar);
        if (op->att <= 0) { op->att = 0; op->stage = EG_DECAY; }
        break;
    case EG_DECAY:
        op->att += vrc7_decay_step(dr);
        if (op->att >= sl * 3.0) {
            op->att = sl * 3.0;
            op->stage = sustained ? EG_SUSTAIN : EG_RELEASE;
        }
        break;
    case EG_SUSTAIN:
        break;
    case EG_RELEASE:
        op->att += vrc7_decay_step(rr);
        if (op->att >= 48) { op->att = 48; op->stage = EG_OFF; }
        break;
    default:
        break;
    }
}

static double vrc7_wave(double phase, int half) {
    double s = sin(2 * 3.14159265358979 * phase);
    return (half && s < 0) ? 0 : s;
}

static float vrc7_sample(void) {
    static const double feedback[8] = {
        0, 3.14159265358979 / 16, 3.14159265358979 / 8, 3.14159265358979 / 4,
        3.14159265358979 / 2, 3.14159265358979, 2 * 3.14159265358979,
        4 * 3.14159265358979 };
    double sum = 0;
    for (int ch = 0; ch < 6; ch++) {
        const uint8_t *p = vrc7_patch(ch);
        int fnum = vrc7.regs[0x10 + ch] | (vrc7.regs[0x20 + ch] & 1) << 8;
        int octave = (vrc7.regs[0x20 + ch] >> 1) & 7;
        double base = fnum * pow(2.0, octave - 19);  /* cycles per sample */
        struct vrc7_op *m = &vrc7.op[ch][0], *c = &vrc7.op[ch][1];
        vrc7_envelope(ch, 0, p);
        vrc7_envelope(ch, 1, p);
        m->phase += base * vrc7_multiplier[p[0] & 15];
        c->phase += base * vrc7_multiplier[p[1] & 15];
        m->phase -= floor(m->phase);
        c->phase -= floor(c->phase);
        if (c->stage == EG_OFF) continue;
        double fb = feedback[p[3] & 7] * (vrc7.fb[ch][0] + vrc7.fb[ch][1]) / 2;
        double m_att = (p[2] & 0x3F) * 0.75 + m->att;
        double mod = vrc7_wave(m->phase + fb / (2 * 3.14159265358979), (p[3] >> 3) & 1) *
                     pow(10.0, -m_att / 20);
        vrc7.fb[ch][1] = vrc7.fb[ch][0];
        vrc7.fb[ch][0] = mod;
        /* Approximate: a full modulator shifts the carrier by 4 pi. */
        double c_att = (vrc7.regs[0x30 + ch] & 15) * 3.0 + c->att;
        sum += vrc7_wave(c->phase + mod * 2.0, (p[3] >> 4) & 1) * pow(10.0, -c_att / 20);
    }
    return (float)(sum * 0.0747);
}

static float vrc7_audio_step(uint64_t cycle) {
    (void)cycle;
    if (--vrc7.timer <= 0) {        /* the chip's 49716 Hz: ~36 cycles */
        vrc7.timer = 36;
        vrc7.out = vrc7.silent ? 0.0f : vrc7_sample();
    }
    return vrc7.out;
}

static void vrc7_sound_write(uint8_t reg, uint8_t val) {
    apu_catch_up();                 /* the change lands on this cycle */
    if (reg >= 0x40) return;
    if (reg >= 0x20 && reg <= 0x25) {
        int ch = reg - 0x20, on = (val >> 4) & 1;
        if (on && !vrc7.key[ch]) {                  /* key on */
            for (int o = 0; o < 2; o++) {
                vrc7.op[ch][o].stage = EG_ATTACK;
                vrc7.op[ch][o].phase = 0;
            }
            vrc7.fb[ch][0] = vrc7.fb[ch][1] = 0;
        } else if (!on && vrc7.key[ch]) {           /* key off */
            vrc7.op[ch][1].stage = EG_RELEASE;
            if (!((vrc7_patch(ch)[0] >> 5) & 1)) vrc7.op[ch][0].stage = EG_RELEASE;
        }
        vrc7.key[ch] = (uint8_t)on;
    }
    vrc7.regs[reg] = val;
}

static void vrc7_sound_reset(void) {
    memset(&vrc7, 0, sizeof vrc7);
    for (int ch = 0; ch < 6; ch++)
        for (int o = 0; o < 2; o++) { vrc7.op[ch][o].att = 48; vrc7.op[ch][o].stage = EG_OFF; }
}

static void vrc7_write(uint16_t addr, uint8_t val) {
    /* A4 (VRC7a, submapper 2), A3 (VRC7b, submapper 1), or either. */
    int second = (cart.submapper == 1 ? addr >> 3 : cart.submapper == 2 ? addr >> 4
                  : (addr >> 4) | (addr >> 3)) & 1;
    switch (addr & 0xF000) {
    case 0x8000: set_prg_8k(second, val & 0x3F); break;
    case 0x9000:
        if ((addr & 0x30) == 0x10) vrc7.select = val;
        else if ((addr & 0x30) == 0x30) vrc7_sound_write(vrc7.select, val);
        else if (!second) set_prg_8k(2, val & 0x3F);
        break;
    case 0xA000: case 0xB000: case 0xC000: case 0xD000:
        set_chr_1k(((addr >> 12) - 0xA) * 2 + second, val);
        break;
    case 0xE000:
        if (second) { vrc_irq_catch_up(); vrc.latch = val; break; }
        {
            static const enum mirroring mir[4] = {
                MIRROR_VERTICAL, MIRROR_HORIZONTAL, MIRROR_SINGLE_LOW, MIRROR_SINGLE_HIGH };
            cart.mirroring = mir[val & 3];
            apu_catch_up();
            vrc7.silent = (val >> 6) & 1;
        }
        break;
    case 0xF000:
        vrc_irq_catch_up();
        if (second) vrc_irq_ack();
        else vrc_irq_control(val);
        break;
    }
}

static void vrc7_reset(void) {
    memset(&vrc, 0, sizeof vrc);
    vrc7_sound_reset();
    vrc.prescaler = 341;
    vrc.irq_time = cycles;
    set_prg_8k(0, 0); set_prg_8k(1, 1); set_prg_8k(2, 2); set_prg_8k(3, -1);
    mapper.catch_up = vrc_irq_catch_up;
    mapper.schedule = vrc_irq_schedule;
    mapper.audio_step = vrc7_audio_step;
}

/* ---- 1: MMC1. Registers are loaded one bit at a time. -----------------

   Each write to $8000-$FFFF shifts bit 0 into a 5-bit register; the fifth
   write copies it to the register chosen by address bits 13-14 ($8000
   control, $A000 CHR 0, $C000 CHR 1, $E000 PRG). A write with bit 7 set
   resets the shift and selects PRG mode 3. The chip ignores a write on
   the cycle right after another, which is what happens with the double
   write of INC/ASL etc. */
static struct {
    uint8_t shift, count;
    uint8_t control, chr0, chr1, prg;
    uint64_t last_write;
} mmc1;

static void mmc1_apply(void) {
    static const enum mirroring mir[4] = {
        MIRROR_SINGLE_LOW, MIRROR_SINGLE_HIGH, MIRROR_VERTICAL,
        MIRROR_HORIZONTAL };
    cart.mirroring = mir[mmc1.control & 3];

    if (mmc1.control & 0x10) {               /* two separate 4 KB banks */
        set_chr_4k(0, mmc1.chr0);
        set_chr_4k(1, mmc1.chr1);
    } else {                                 /* one 8 KB bank */
        set_chr_8k(mmc1.chr0 >> 1);
    }

    /* 512 KB boards (SUROM) use CHR bit 4 to pick the 256 KB half. */
    int outer = cart.prg_size > 0x40000 ? (mmc1.chr0 & 0x10) : 0;
    int bank = outer | (mmc1.prg & 0x0F);
    if (cart.submapper == 5)                 /* SEROM, SHROM: 32 KB, fixed */
        set_prg_32k(0);
    else switch ((mmc1.control >> 2) & 3) {
    case 0: case 1: set_prg_16k(0, bank & ~1); set_prg_16k(1, bank | 1); break;
    case 2: set_prg_16k(0, outer); set_prg_16k(1, bank); break;
    case 3: set_prg_16k(0, bank); set_prg_16k(1, outer | 0x0F); break;
    }
    mapper.prg_ram_disabled = (mmc1.prg & 0x10) != 0;
    /* 16 KB of PRG RAM (SOROM) or 32 KB (SXROM), from an NES 2.0 header:
       bits 2-3 of CHR bank 0 pick the 8 KB at $6000 (SOROM wires only bit
       3). The wiki asks for the same bits in CHR bank 1 in 4 KB mode. */
    size_t ram = cart.prg_ram_size + cart.prg_nvram_size;
    if (ram > 0x2000)
        set_ram_8k(ram > 0x4000 ? (mmc1.chr0 >> 2) & 3 : (mmc1.chr0 >> 3) & 1);
}

static void mmc1_write(uint16_t addr, uint8_t val) {
    uint64_t now = cycles;
    int back_to_back = now == mmc1.last_write + 1;
    mmc1.last_write = now;
    if (back_to_back) return;
    if (val & 0x80) {
        mmc1.shift = mmc1.count = 0;
        mmc1.control |= 0x0C;
        mmc1_apply();
        return;
    }
    mmc1.shift |= (uint8_t)((val & 1) << mmc1.count);
    if (++mmc1.count < 5) return;
    switch ((addr >> 13) & 3) {
    case 0: mmc1.control = mmc1.shift; break;
    case 1: mmc1.chr0 = mmc1.shift; break;
    case 2: mmc1.chr1 = mmc1.shift; break;
    case 3: mmc1.prg = mmc1.shift; break;
    }
    mmc1.shift = mmc1.count = 0;
    mmc1_apply();
}

static void mmc1_reset(void) {
    mmc1.control = 0x0C;                     /* last bank fixed at $C000 */
    mmc1.last_write = UINT64_MAX - 1;
    mmc1_apply();
}

/* ---- 4: MMC3. 8 KB PRG and 1/2 KB CHR banks, and a scanline counter.

   $8000 picks which of R0-R7 the next $8001 write sets, plus two layout
   bits. The IRQ counter is clocked by rising edges of the PPU's A12
   address line (ppu.c reports them), roughly once per rendered line. A
   rise only counts after A12 has been low for a while (MMC3_A12_FILTER
   dots), which hides the short dips between tile fetches. */
#define MMC3_A12_FILTER 9

static struct {
    uint8_t select, r[8];
    uint8_t latch, counter, reload, irq_enabled;
    int a12, four_screen;
    uint64_t a12_low_since;
} mmc3;

/* 119: TQROM, an MMC3 with 8 KB of CHR RAM beside its CHR ROM (nesdev
   wiki, "INES Mapper 119"). Bit 6 of a CHR bank number picks the chip:
   0 CHR ROM (bits 0-5: up to 64 KB), 1 CHR RAM, where only the bits
   that fit 8 KB (0-2) count, as the RAM's address lines are CHR A0-A12. */
static int tqrom;
static uint8_t tqrom_ram[0x2000];

static void mmc3_chr(int slot, uint8_t bank) {
    if (tqrom && (bank & 0x40)) {
        mapper.chr[slot] = tqrom_ram + (bank & 7) * 0x400;
        mapper.chr_writable |= (uint8_t)(1 << slot);
    } else {
        set_chr_1k(slot, tqrom ? bank & 0x3F : bank);
    }
}

static void mmc3_apply(void) {
    int x = (mmc3.select & 0x80) ? 4 : 0;   /* swap CHR halves */
    mapper.chr_writable = 0;
    mmc3_chr(0 ^ x, mmc3.r[0] & 0xFE); mmc3_chr(1 ^ x, mmc3.r[0] | 1);
    mmc3_chr(2 ^ x, mmc3.r[1] & 0xFE); mmc3_chr(3 ^ x, mmc3.r[1] | 1);
    for (int i = 0; i < 4; i++) mmc3_chr((4 + i) ^ x, mmc3.r[2 + i]);
    if (mmc3.select & 0x40) { set_prg_8k(0, -2); set_prg_8k(2, mmc3.r[6]); }
    else                    { set_prg_8k(0, mmc3.r[6]); set_prg_8k(2, -2); }
    set_prg_8k(1, mmc3.r[7]);
    set_prg_8k(3, -1);
}

char mmc3_revision = 'B';

static void mmc3_clock(void) {
    /* Revision A only raises the IRQ when the counter gets to 0: by
       counting down, or reloading after a $C001 clear. Reloading after it
       reached 0 by itself doesn't, even to 0. Revision B raises it
       whenever the counter is 0 after a clock (mmc3_irq_tests readme). */
    int reaches_zero = mmc3.counter != 0 || mmc3.reload;
    if (mmc3.counter == 0 || mmc3.reload) {
        mmc3.counter = mmc3.latch;
        mmc3.reload = 0;
    } else {
        mmc3.counter--;
    }
    if (mmc3.counter == 0 && mmc3.irq_enabled &&
        (mmc3_revision != 'A' || reaches_zero))
        cpu_set_irq(IRQ_MAPPER, 1);
}

static void mmc3_a12(int level, uint64_t dot) {
    if (level && !mmc3.a12 && dot - mmc3.a12_low_since >= MMC3_A12_FILTER)
        mmc3_clock();
    if (!level && mmc3.a12) mmc3.a12_low_since = dot;
    mmc3.a12 = level;
}

static void mmc3_write(uint16_t addr, uint8_t val) {
    switch (addr & 0xE001) {
    case 0x8000: mmc3.select = val; mmc3_apply(); break;
    case 0x8001: mmc3.r[mmc3.select & 7] = val; mmc3_apply(); break;
    case 0xA000:
        if (!mmc3.four_screen)
            cart.mirroring = (val & 1) ? MIRROR_HORIZONTAL : MIRROR_VERTICAL;
        break;
    case 0xA001: break;     /* PRG-RAM protect: ignored, RAM stays usable */
    case 0xC000: mmc3.latch = val; break;
    case 0xC001: mmc3.counter = 0; mmc3.reload = 1; break;
    case 0xE000: mmc3.irq_enabled = 0; cpu_set_irq(IRQ_MAPPER, 0); break;
    case 0xE001: mmc3.irq_enabled = 1; break;
    }
    mapper.watch_lines = mmc3.irq_enabled;
}

static void mmc3_reset(void) {
    static const uint8_t r[8] = { 0, 2, 4, 5, 6, 7, 0, 1 };
    for (int i = 0; i < 8; i++) mmc3.r[i] = r[i];
    mmc3.four_screen = cart.mirroring == MIRROR_FOUR_SCREEN;
    mmc3_apply();
    mapper.a12 = mmc3_a12;
}

/* ---- 112: NTDEC / Asder (nesdev wiki, "INES Mapper 112"). A simpler,
   scrambled MMC3, registers where addr & $E001 is:
     $8000  bank select, bits 0-2: 0/1 the 8 KB PRG bank at $8000/$A000,
            2/3 the 2 KB CHR banks at $0000/$0800, 4-7 the 1 KB CHR
            banks at $1000-$1C00 (no PRG or CHR mode bits)
     $A000  bank data
     $E000  bit 0: nametable arrangement, 0 horizontal (A10: vertical
            mirroring), 1 vertical (A11: horizontal mirroring)
   No IRQ. The wiki doesn't say which banks are fixed or the units of the
   2 KB banks: here $C000-$FFFF is the last 16 KB, as on the MMC3 it
   imitates, and a 2 KB bank number counts 1 KB banks with its low bit
   ignored, also as on the MMC3. Power-on (not given either): the
   first 16 KB at $8000 (R0 = 0, R1 = 1), the other registers 0. ---- */

static uint8_t ntdec_select, ntdec_r[8];

static void ntdec_apply(void) {
    set_prg_8k(0, ntdec_r[0]);
    set_prg_8k(1, ntdec_r[1]);
    set_chr_1k(0, ntdec_r[2] & 0xFE); set_chr_1k(1, ntdec_r[2] | 1);
    set_chr_1k(2, ntdec_r[3] & 0xFE); set_chr_1k(3, ntdec_r[3] | 1);
    for (int i = 0; i < 4; i++) set_chr_1k(4 + i, ntdec_r[4 + i]);
}

static void ntdec_write(uint16_t addr, uint8_t val) {
    switch (addr & 0xE001) {
    case 0x8000: ntdec_select = val & 7; break;
    case 0xA000: ntdec_r[ntdec_select] = val; ntdec_apply(); break;
    case 0xE000:
        cart.mirroring = (val & 1) ? MIRROR_HORIZONTAL : MIRROR_VERTICAL;
        break;
    }
}

static void ntdec_reset(void) {
    ntdec_select = 0;
    memset(ntdec_r, 0, sizeof ntdec_r);
    ntdec_r[1] = 1;
    ntdec_apply();
    set_prg_8k(2, -2);
    set_prg_8k(3, -1);
}

/* ---- 16: Bandai FCG-1/2 and LZ93D50 (nesdev wiki, "INES Mapper 016"
   and "Bandai FCG board"). 16 KB at $8000 switches, the last 16 KB is
   fixed, eight 1 KB CHR banks. Registers, by address AND $000F:
     0-7  CHR bank for PPU $0000, $0400, ... $1C00
     8    PRG bank, bits 0-3
     9    mirroring, bits 0-1: 0 vertical (the wiki's "horizontal
          arrangement", A10), 1 horizontal, 2 one-screen $2000, 3 $2400
     A    IRQ: bit 0 enables counting; any write acknowledges the IRQ
     B/C  IRQ counter (FCG) or latch (LZ93D50), low/high byte
     D    EEPROM (LZ93D50): bit 5 SCL, bit 6 SDA, bit 7 releases SDA to
          read; the data comes back in bit 4 of reads of $6000-$7FFF
   The FCG-1/2 (submapper 4) answers at $6000-$7FFF, its counter written
   directly; the LZ93D50 (submapper 5) at $8000-$FFFF, its B/C a latch
   copied to the counter by every write to A. Submapper 0 decodes both,
   each range acting as its own chip. While enabled, the counter counts
   down every CPU cycle, and the IRQ fires on a cycle that finds it at 0
   (so enabling it at 0 fires at once); the wiki doesn't say more. Here,
   as in Mesen, it then goes on counting down from $FFFF.

   The EEPROM: a 24C02 (256 bytes) when the NES 2.0 header gives the
   LZ93D50 board 256 bytes or more of battery RAM, or, with no submapper,
   when the header has the battery bit. It is that battery RAM, so it is
   kept in <rom>.sav like any other. The wiki gives no protocol for it;
   it follows the 24C02's own (I2C): a start is SDA falling while SCL is
   high, a stop SDA rising; bits go most significant first, sampled
   while SCL rises; the device byte is $A0 (write) or $A1 (read), then
   for a write the word address and data bytes, each acknowledged by the
   chip pulling SDA low on the ninth clock; writes wrap within an 8-byte
   page; reads go on through all 256 bytes while the program
   acknowledges. The chip's write time (about 5 ms, when it answers
   nothing) isn't modelled: writes land at once. Not here: the 128-byte
   X24C01 of submapper 1 / mapper 159, the Datach (2, mapper 157) and
   submapper 3's 8 KB RAM (mapper 153). Power-on (not given): every
   register 0, the header's mirroring until register 9 is written. */

static struct {
    uint8_t chr[8], enabled;
    uint16_t counter, latch;
    uint64_t time;                  /* cycle the counter is valid at */
} bandai;

static struct {
    uint8_t *mem;                   /* 256 bytes, or NULL: no EEPROM */
    int mode, next, bits, ack;
    uint8_t shift, addr, byte;
    int scl, sda, out;              /* out: what the chip drives (1: let go) */
} ee;
enum { EE_IDLE, EE_DEVICE, EE_ADDR, EE_WRITE, EE_READ, EE_ACK_OUT, EE_ACK_IN };

static void ee_send_byte(void) {
    ee.byte = ee.mem[ee.addr];
    ee.out = ee.byte >> 7;
    ee.bits = 1;                    /* bits put on SDA so far */
}

static void ee_lines(int scl, int sda) {
    if (ee.scl && scl && ee.sda && !sda) {              /* start */
        ee.mode = EE_DEVICE; ee.bits = 0; ee.shift = 0; ee.out = 1;
    } else if (ee.scl && scl && !ee.sda && sda) {       /* stop */
        ee.mode = EE_IDLE; ee.out = 1;
    } else if (!ee.scl && scl) {                        /* SCL rises */
        if (ee.mode == EE_DEVICE || ee.mode == EE_ADDR || ee.mode == EE_WRITE) {
            ee.shift = (uint8_t)(ee.shift << 1 | sda);
            ee.bits++;
        } else if (ee.mode == EE_ACK_IN) {
            ee.ack = !sda;
        }
    } else if (ee.scl && !scl) {                        /* SCL falls */
        switch (ee.mode) {
        case EE_DEVICE:
            if (ee.bits < 8) break;
            if ((ee.shift & 0xFE) != 0xA0) { ee.mode = EE_IDLE; break; }
            ee.next = (ee.shift & 1) ? EE_READ : EE_ADDR;
            ee.mode = EE_ACK_OUT; ee.out = 0;
            break;
        case EE_ADDR:
            if (ee.bits < 8) break;
            ee.addr = ee.shift;
            ee.next = EE_WRITE; ee.mode = EE_ACK_OUT; ee.out = 0;
            break;
        case EE_WRITE:
            if (ee.bits < 8) break;
            ee.mem[ee.addr] = ee.shift;
            ee.addr = (uint8_t)((ee.addr & 0xF8) | ((ee.addr + 1) & 7));
            ee.next = EE_WRITE; ee.mode = EE_ACK_OUT; ee.out = 0;
            break;
        case EE_ACK_OUT:                /* the ninth clock is over */
            ee.mode = ee.next; ee.bits = 0; ee.shift = 0; ee.out = 1;
            if (ee.mode == EE_READ) ee_send_byte();
            break;
        case EE_READ:
            if (ee.bits < 8) {
                ee.out = (ee.byte >> (7 - ee.bits)) & 1;
                ee.bits++;
            } else {                    /* let go for the program's ack */
                ee.out = 1; ee.mode = EE_ACK_IN; ee.ack = 0;
                ee.addr++;
            }
            break;
        case EE_ACK_IN:
            if (ee.ack) { ee.mode = EE_READ; ee_send_byte(); }
            else ee.mode = EE_IDLE;     /* no ack: wait for the stop */
            break;
        }
    }
    ee.scl = scl; ee.sda = sda;
}

static int bandai_read_6000(uint16_t addr) {
    if (!ee.mem) return -1;
    return ((addr >> 8) & 0xEF) | (ee.sda & ee.out) << 4;
}

static void bandai_irq_catch_up(void) {
    uint64_t now = cycles;
    if (bandai.enabled) {
        uint64_t elapsed = now - bandai.time;
        if (elapsed > bandai.counter)               /* found it at 0 */
            cpu_set_irq_at(IRQ_MAPPER, 1, (bandai.time + bandai.counter + 1) * 3);
        bandai.counter = (uint16_t)(bandai.counter - elapsed);
    }
    bandai.time = now;
}

static void bandai_irq_schedule(void) {
    if (bandai.enabled) schedule_event(bandai.time + bandai.counter + 1);
}

static void bandai_reg(int lz, uint16_t addr, uint8_t val) {
    int r = addr & 0x0F;
    if (r < 8) {
        bandai.chr[r] = val;
        set_chr_1k(r, val);
    } else if (r == 8) {
        set_prg_16k(0, val & 0x0F);
    } else if (r == 9) {
        static const enum mirroring mir[4] = {
            MIRROR_VERTICAL, MIRROR_HORIZONTAL, MIRROR_SINGLE_LOW, MIRROR_SINGLE_HIGH };
        cart.mirroring = mir[val & 3];
    } else if (r == 0x0A) {
        bandai_irq_catch_up();
        cpu_set_irq(IRQ_MAPPER, 0);
        if (lz) bandai.counter = bandai.latch;
        bandai.enabled = val & 1;
    } else if (r == 0x0B || r == 0x0C) {
        int shift = r == 0x0B ? 0 : 8;
        uint16_t keep = (uint16_t)(0xFF00 >> shift);
        if (lz) {
            bandai.latch = (uint16_t)((bandai.latch & keep) | val << shift);
        } else {
            bandai_irq_catch_up();
            bandai.counter = (uint16_t)((bandai.counter & keep) | val << shift);
        }
    } else if (r == 0x0D && lz && ee.mem) {
        ee_lines(val >> 5 & 1, (val >> 6 | val >> 7) & 1);
    }
}

static void bandai_write(uint16_t addr, uint8_t val) {           /* LZ93D50 */
    if (cart.submapper != 4) bandai_reg(1, addr, val);
}
static void bandai_write_6000(uint16_t addr, uint8_t val) {      /* FCG-1/2 */
    if (cart.submapper != 5) bandai_reg(0, addr, val);
}

static void bandai_reset(void) {
    memset(&bandai, 0, sizeof bandai);
    memset(&ee, 0, sizeof ee);
    ee.scl = ee.sda = ee.out = 1;
    bandai.time = cycles;
    set_prg_16k(0, 0);
    set_prg_16k(1, -1);
    set_chr_8k(0);
    int eeprom = cart.submapper == 5 ? cart.prg_nvram_size >= 256
               : cart.submapper == 0 && cart.battery && cart.prg_nvram_size >= 256;
    if (eeprom) {
        ee.mem = cart.prg_ram + cart.prg_ram_size;
        /* No plain RAM: $6000-$7FFF isn't the EEPROM's memory. */
        if (!cart.prg_ram_size) mapper.ram6000_size = 0;
    }
    mapper.catch_up = bandai_irq_catch_up;
    mapper.schedule = bandai_irq_schedule;
    mapper.write_6000 = bandai_write_6000;
    mapper.read_6000 = bandai_read_6000;
}

/* ---- 68: Sunsoft-4 (nesdev wiki, "INES Mapper 068"). 16 KB at $8000
   switches, the last 16 KB is fixed; four 2 KB CHR banks; and the
   background's nametables can come from CHR ROM. Registers by 4 KB:
     $8000-$BFFF  the 2 KB CHR banks at PPU $0000, $0800, $1000, $1800
     $C000/$D000  the 1 KB CHR ROM banks used in place of CIRAM's first
                  and second 1 KB; bit 7 is always taken as 1, so they're
                  in the last 128 KB of CHR ROM
     $E000        bits 0-1 mirroring (0 vertical, 1 horizontal, 2/3 one
                  screen, the first / second table), bit 4: nametables
                  from CHR ROM ($C000 for the first, $D000 the second,
                  arranged by the same mirroring) instead of CIRAM
     $F000        bits 0-3 the PRG bank, bit 4 enables the PRG RAM
   No bus conflicts. Not given by the wiki, and chosen here: writes to a
   ROM nametable change nothing; power-on has every register 0 except
   that the PRG RAM starts enabled, and the header's mirroring holds
   until $E000 is written. Nantettatte!! Baseball's extra ROM cartridge
   and licensing timer aren't here. */

static uint8_t sun4_nt[2], sun4_rom_nt;

static int sun4_table(uint16_t addr) {         /* 0: first, 1: second */
    int t = (addr >> 10) & 3;
    switch (cart.mirroring) {
    case MIRROR_VERTICAL:    return t & 1;
    case MIRROR_HORIZONTAL:  return t >> 1;
    case MIRROR_SINGLE_HIGH: return 1;
    default:                 return 0;
    }
}

static uint8_t sun4_nt_read(uint16_t addr) {
    int t = sun4_table(addr);
    if (sun4_rom_nt) {
        size_t bank = (size_t)wrap(sun4_nt[t] | 0x80, chr_banks_1k());
        return cart.chr[bank * 0x400 + (addr & 0x3FF)];
    }
    return ppu.nametables[t << 10 | (addr & 0x3FF)];
}

static void sun4_nt_write(uint16_t addr, uint8_t val) {
    if (!sun4_rom_nt) ppu.nametables[sun4_table(addr) << 10 | (addr & 0x3FF)] = val;
}

static void sun4_write(uint16_t addr, uint8_t val) {
    switch (addr & 0xF000) {
    case 0x8000: case 0x9000: case 0xA000: case 0xB000: {
        int slot = ((addr >> 12) & 3) * 2;
        set_chr_1k(slot, val * 2);
        set_chr_1k(slot + 1, val * 2 + 1);
        break;
    }
    case 0xC000: sun4_nt[0] = val; break;
    case 0xD000: sun4_nt[1] = val; break;
    case 0xE000: {
        static const enum mirroring mir[4] = {
            MIRROR_VERTICAL, MIRROR_HORIZONTAL, MIRROR_SINGLE_LOW, MIRROR_SINGLE_HIGH };
        cart.mirroring = mir[val & 3];
        sun4_rom_nt = (val >> 4) & 1;
        break;
    }
    case 0xF000:
        set_prg_16k(0, val & 0x0F);
        mapper.prg_ram_disabled = !(val & 0x10);
        break;
    }
}

static void sun4_reset(void) {
    sun4_nt[0] = sun4_nt[1] = 0;
    sun4_rom_nt = 0;
    set_prg_16k(0, 0);
    set_prg_16k(1, -1);
    set_chr_8k(0);
    mapper.prg_ram_disabled = 0;
    mapper.nt_read = sun4_nt_read;
    mapper.nt_write = sun4_nt_write;
}

/* ---------------------------------------------------------------------- */

/* ---- NSF expansion sound (nesdev wiki "NSF"). Header byte $7B lists
   the chips; each sits at its usual addresses, with no bank switching or
   IRQs of its own:
     bit 0  VRC6      $9000-$9003, $A000-$A002, $B000-$B002
     bit 1  VRC7      $9010 register select, $9030 data
     bit 2  FDS       $4040-$408A sound, read back at $4040-$407F and
                      $4090-$4097 (fds.c); $8000-$DFFF become writable
                      RAM, and $5FF6/$5FF7 switch 4 KB banks into the
                      RAM at $6000/$7000 (nsf.c)
     bit 3  MMC5      $5000-$5015 sound, $5205/$5206 multiplier, and
                      $5C00-$5FF5 as plain RAM
     bit 4  Namco 163 $4800 sound RAM data, $F800 its address
     bit 5  5B        $C000 register select, $E000 data
   The chips' outputs add up, as on a cartridge each joins the APU's. */
static uint8_t nsf_chips;
static uint8_t nsf_exram[0x400];

static float nsf_audio_step(uint64_t cycle) {
    float out = 0;
    if (nsf_chips & NSF_VRC6) out += vrc6_audio_step(cycle);
    if (nsf_chips & NSF_VRC7) out += vrc7_audio_step(cycle);
    if (nsf_chips & NSF_MMC5) out += mmc5_audio_step(cycle);
    if (nsf_chips & NSF_N163) out += n163_audio_step(cycle);
    if (nsf_chips & NSF_5B) out += fme_audio_step(cycle);
    if (nsf_chips & NSF_FDS) out += fds_audio_step(cycle);
    return out;
}

void nsf_chips_reset(uint8_t chips) {
    nsf_chips = chips;
    vrc6_sound_reset();
    vrc7_sound_reset();
    memset(&mmc5, 0, sizeof mmc5);
    mmc5_sound_reset();
    memset(nsf_exram, 0, sizeof nsf_exram);
    memset(&n163, 0, sizeof n163);
    n163.channel = 7;
    fme_sound_reset();
    fds_sound_reset();
    fds_sound_on = 1;
    mapper.audio_step = chips ? nsf_audio_step : NULL;
}

static void nsf_chip_write(uint16_t addr, uint8_t val) {
    /* With the FDS, $8000-$DFFF is RAM (nesdev wiki "NSF"); code the
       recompiler translated from there checks code_owner (rt.h). */
    if ((nsf_chips & NSF_FDS) && addr < 0xE000)
        code_ram_write(&mapper.prg[(addr >> 13) & 3][addr & 0x1FFF], addr, val);
    if ((nsf_chips & NSF_VRC6) && addr >= 0x9000 && addr < 0xC000 &&
        (addr & 0x0FFC) == 0 && addr != 0xB003)
        vrc6_sound_write(addr, val);
    if (nsf_chips & NSF_VRC7) {
        if (addr == 0x9010) vrc7.select = val;
        else if (addr == 0x9030) vrc7_sound_write(vrc7.select, val);
    }
    if ((nsf_chips & NSF_N163) && addr >= 0xF800) n163.addr = val;
    if (nsf_chips & NSF_5B) {
        if ((addr & 0xE000) == 0xC000) fme.select = val;
        else if ((addr & 0xE000) == 0xE000) fme_sound_data(val);
    }
}

void nsf_chip_write_low(uint16_t addr, uint8_t val) {
    if ((nsf_chips & NSF_FDS) && addr >= 0x4040 && addr <= 0x408A) {
        apu_catch_up();
        fds_sound_write(addr, val);
    }
    if ((nsf_chips & NSF_N163) && addr >= 0x4800 && addr < 0x5000)
        n163_write_low(addr, val);
    if (nsf_chips & NSF_MMC5) {
        if (addr >= 0x5000 && addr <= 0x5015) mmc5_sound_write(addr, val);
        else if (addr == 0x5205) mmc5.mul_a = val;
        else if (addr == 0x5206) mmc5.mul_b = val;
        else if (addr >= 0x5C00 && addr < 0x5FF6) nsf_exram[addr - 0x5C00] = val;
    }
}

int nsf_chip_read_low(uint16_t addr) {
    if ((nsf_chips & NSF_FDS) && addr >= 0x4040 && addr <= 0x4097) {
        apu_catch_up();
        int v = fds_sound_read(addr);
        if (v >= 0) return v;
    }
    if ((nsf_chips & NSF_N163) && addr >= 0x4800 && addr < 0x5000)
        return n163_read_low(addr);
    if (nsf_chips & NSF_MMC5) {
        if (addr == 0x5015 || addr == 0x5205 || addr == 0x5206 || addr == 0x5010)
            return mmc5_read_low(addr);
        if (addr >= 0x5C00 && addr < 0x5FF6) return nsf_exram[addr - 0x5C00];
    }
    return -1;
}

/* The NES 2.0 submappers this runtime tells apart (nesdev wiki "NES 2.0
   submappers"); others run as submapper 0, with a warning. */
static void check_submapper(void) {
    int s = cart.submapper, known;
    switch (cart.mapper) {
    case 1:  known = s == 5; break;                         /* fixed PRG */
    case 2: case 3: case 7: known = s == 1 || s == 2; break;  /* conflicts */
    case 4:  known = s == 4; break;                         /* MMC3A/NEC */
    case 19: known = s >= 1 && s <= 5; break;               /* sound level */
    case 21: known = s == 1 || s == 2; break;               /* wiring */
    case 23: case 25: known = s >= 1 && s <= 3; break;      /* wiring, VRC2 */
    case 34:
        if (s == 1) {
            fprintf(stderr, "mapper 34 submapper 1 (NINA-001) is not supported\n");
            exit(1);
        }
        known = s == 2; break;                              /* BNROM */
    case 85: known = s == 1 || s == 2; break;               /* wiring */
    case 71: known = s == 1; break;                         /* BF9097 */
    case 16: known = s == 4 || s == 5; break;               /* FCG, LZ93D50 */
    default: known = 0;
    }
    if (s && !known)
        fprintf(stderr, "mapper %d submapper %d isn't modelled: running it as"
                        " submapper 0\n", cart.mapper, s);
}

void mapper_init(void) {
    /* Power-on layout for every board: ROM laid out from the start and
       repeated to fill 32 KB (so 16 KB NROM appears twice). Each mapper's
       reset may then change it. */
    for (int i = 0; i < 4; i++) set_prg_8k(i, i);
    set_chr_8k(0);
    set_ram_8k(0);
    mapper.bank_changed = 0;
    conflicts = cart.submapper == 2 || (cart.submapper != 1 && cart.mapper != 7);
    check_submapper();

    switch (cart.mapper) {
    case 0: mapper.name = "NROM"; write_reg = nrom_write; break;
    case 1: mapper.name = "MMC1"; write_reg = mmc1_write; mmc1_reset(); break;
    case 2:
        mapper.name = "UxROM"; write_reg = uxrom_write;
        set_prg_16k(1, -1);
        break;
    case 3: mapper.name = "CNROM"; write_reg = cnrom_write; break;
    case 4:
        mapper.name = "MMC3"; write_reg = mmc3_write; mmc3_reset();
        /* Submapper 4: the older MMC3A (NEC); --mmc3-rev, read after
           this, can still choose. */
        if (cart.submapper == 4) mmc3_revision = 'A';
        break;
    case 119:
        mapper.name = "TQROM"; write_reg = mmc3_write;
        tqrom = 1; memset(tqrom_ram, 0, sizeof tqrom_ram);
        mmc3_reset();
        break;
    case 16:
        mapper.name = cart.submapper == 4 ? "Bandai FCG" : cart.submapper == 5 ?
                      "Bandai LZ93D50" : "Bandai FCG/LZ93D50";
        write_reg = bandai_write; bandai_reset();
        break;
    case 68: mapper.name = "Sunsoft-4"; write_reg = sun4_write; sun4_reset(); break;
    case 112: mapper.name = "NTDEC 112"; write_reg = ntdec_write; ntdec_reset(); break;
    case 7:
        mapper.name = "AxROM"; write_reg = axrom_write;
        set_prg_32k(0);
        cart.mirroring = MIRROR_SINGLE_LOW;
        break;
    case 34: mapper.name = "BNROM"; write_reg = bnrom_write; set_prg_32k(0); break;
    case 11:
        mapper.name = "Color Dreams"; write_reg = color_dreams_write;
        set_prg_32k(0);
        break;
    case 66: mapper.name = "GxROM"; write_reg = gxrom_write; set_prg_32k(0); break;
    case 5: mapper.name = "MMC5"; write_reg = mmc5_write; mmc5_reset(); break;
    case 9: mapper.name = "MMC2"; write_reg = mmc2_write; mmc2_reset(); break;
    case 10: mapper.name = "MMC4"; write_reg = mmc2_write; mmc2_reset(); break;
    case 21: case 23: case 25:
        mapper.name = cart.submapper == 3 ? "VRC2" : "VRC4";
        write_reg = vrc_write; vrc_reset();
        break;
    case 19: mapper.name = "Namco 163"; write_reg = n163_write; n163_reset(); break;
    case 85: mapper.name = "VRC7"; write_reg = vrc7_write; vrc7_reset(); break;
    case 69: mapper.name = "FME-7"; write_reg = fme_write; fme_reset(); break;
    case 24: case 26:
        mapper.name = "VRC6"; write_reg = vrc6_write; vrc6_reset();
        break;
    case 22: mapper.name = "VRC2"; write_reg = vrc_write; vrc_reset(); break;
    case MAPPER_FDS:
        mapper.name = "FDS"; write_reg = fds_write;
        read_low = fds_read_low; write_low = fds_write_low;
        fds_reset();
        break;
    case MAPPER_NSF:
        mapper.name = "NSF"; write_reg = nsf_chip_write;
        read_low = nsf_read_low; write_low = nsf_write_low;
        nsf_mapper_reset();
        break;
    case 28:
        mapper.name = "Action 53"; write_reg = a53_write; write_low = a53_select;
        a53_reset();
        break;
    case 71:
        mapper.name = "Camerica"; write_reg = camerica_write; camerica_reset();
        break;
    case 79:
        mapper.name = "NINA-03/06"; write_reg = nrom_write; write_low = nina_write_low;
        set_prg_32k(0);
        break;
    case 41:
        mapper.name = "Caltron 6-in-1"; write_reg = caltron_write;
        mapper.write_6000 = caltron_write_6000;
        caltron_reset();
        break;
    case 228:
        mapper.name = "Active Enterprises"; write_reg = ae_write;
        mapper.reset = ae_reset;
        ae_write(0x8000, 0);
        break;
    case 172:
        mapper.name = "TXC 172"; write_reg = txc_write;
        write_low = txc_write_low; read_low = txc_read_low;
        memset(&txc, 0, sizeof txc);
        set_prg_32k(0);
        set_chr_8k(0);
        break;
    default:
        fprintf(stderr, "mapper %d is not supported yet; running it as NROM, "
                        "which will probably go wrong\n", cart.mapper);
        mapper.name = "unsupported";
        write_reg = nrom_write;
        break;
    }
    mapper.bank_changed = 0;
    for (int i = 0; i < 4; i++) mapper.power_on_bank[i] = mapper.prg_bank[i];
}

uint8_t mapper_read_low(uint16_t addr) {
    if (!read_low) return 0;
    ppu_catch_up();             /* MMC5's $5204 reflects the PPU's line */
    int v = read_low(addr);
    return v < 0 ? 0 : (uint8_t)v;
}

void mapper_write_low(uint16_t addr, uint8_t val) {
    if (!write_low) return;
    ppu_catch_up();
    write_low(addr, val);
    ppu_schedule();
    if (mapper.schedule) mapper.schedule();     /* Namco 163's IRQ counter */
}

void mapper_write_6000(uint16_t addr, uint8_t val) {
    ppu_catch_up();     /* CHR or mirroring may change mid-frame */
    mapper.write_6000(addr, val);
    ppu_schedule();
    if (mapper.schedule) mapper.schedule();
}

void mapper_write(uint16_t addr, uint8_t val) {
    ppu_catch_up();     /* CHR or mirroring may change mid-frame */
    write_reg(addr, val);
    ppu_schedule();     /* an IRQ may now be due sooner */
    if (mapper.schedule) mapper.schedule();
}
