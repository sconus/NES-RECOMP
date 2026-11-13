/* nesrecomp runtime: mapper implementations. Each one is a reset function
   (power-on banks) and a write function (its registers). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cart.h"
#include "mapper.h"
#include "ppu.h"
#include "rt.h"
#include "event.h"

struct mapper mapper;
static void (*write_reg)(uint16_t addr, uint8_t val);
static void (*write_low)(uint16_t addr, uint8_t val);   /* $4020-$5FFF */

/* ---- helpers: put bank n (counted in the given size) in a slot ------ */

static int prg_banks_8k(void) { return (int)(cart.prg_size / 0x2000); }
static int chr_banks_1k(void) { return (int)(cart.chr_size / 0x400); }

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

/* ---- 0: NROM. No registers. ------------------------------------------ */

static void nrom_write(uint16_t addr, uint8_t val) { (void)addr; (void)val; }

/* ---- 3: CNROM. One register: which 8 KB of CHR ROM. ------------------ */

static void cnrom_write(uint16_t addr, uint8_t val) {
    set_chr_8k(bus_conflict(addr, val));
}

/* ---- 2: UxROM. 16 KB at $8000 switches; the last 16 KB is fixed. ---- */

static void uxrom_write(uint16_t addr, uint8_t val) {
    set_prg_16k(0, bus_conflict(addr, val));
}

/* ---- 7: AxROM. 32 KB PRG switching and one-screen mirroring. --------- */

static void axrom_write(uint16_t addr, uint8_t val) {
    (void)addr;
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
    if (cart.chr_is_ram && cart.chr_size < 0x8000) {   /* 32 KB of CHR RAM */
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
   25 are treated as VRC4 (a superset of VRC2), 22 as VRC2.
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
    int vrc2;                   /* mapper 22: VRC2a */
    uint8_t prg0, prg1, swap, mirror;
    uint16_t chr[8];
    /* IRQ: latch, counter, control bits, and the scanline prescaler,
       valid at cycle irq_time. */
    uint8_t latch, counter, enable, enable_after_ack, cycle_mode;
    int prescaler;
    uint64_t irq_time;
} vrc;

static int vrc_select(uint16_t addr) {
    int a0, a1;
    switch (cart.mapper) {
    case 21: a0 = (addr >> 1 | addr >> 6) & 1; a1 = (addr >> 2 | addr >> 7) & 1; break;
    case 22: a0 = (addr >> 1) & 1;              a1 = addr & 1;                   break;
    case 23: a0 = (addr | addr >> 2) & 1;       a1 = (addr >> 1 | addr >> 3) & 1; break;
    default: a0 = (addr >> 1 | addr >> 3) & 1;  a1 = (addr | addr >> 2) & 1;      break;
    }
    return a1 << 1 | a0;
}

static void vrc_apply(void) {
    set_prg_8k(vrc.swap ? 2 : 0, vrc.prg0);
    set_prg_8k(vrc.swap ? 0 : 2, -2);
    set_prg_8k(1, vrc.prg1);
    set_prg_8k(3, -1);
    for (int i = 0; i < 8; i++)
        set_chr_1k(i, vrc.vrc2 ? vrc.chr[i] >> 1 : vrc.chr[i]);
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
        case 2:   /* control: acknowledge, reset the prescaler, maybe reload */
            vrc.enable_after_ack = val & 1;
            vrc.enable = (val >> 1) & 1;
            vrc.cycle_mode = (val >> 2) & 1;
            vrc.prescaler = 341;
            if (vrc.enable) vrc.counter = vrc.latch;
            cpu_set_irq(IRQ_MAPPER, 0);
            break;
        case 3:   /* acknowledge; A is copied to E */
            vrc.enable = vrc.enable_after_ack;
            cpu_set_irq(IRQ_MAPPER, 0);
            break;
        }
        break;
    }
    vrc_apply();
}

static void vrc_reset(void) {
    memset(&vrc, 0, sizeof vrc);
    vrc.vrc2 = cart.mapper == 22;
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
    switch ((mmc1.control >> 2) & 3) {
    case 0: case 1: set_prg_16k(0, bank & ~1); set_prg_16k(1, bank | 1); break;
    case 2: set_prg_16k(0, outer); set_prg_16k(1, bank); break;
    case 3: set_prg_16k(0, bank); set_prg_16k(1, outer | 0x0F); break;
    }
    mapper.prg_ram_disabled = (mmc1.prg & 0x10) != 0;
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

static void mmc3_apply(void) {
    int x = (mmc3.select & 0x80) ? 4 : 0;   /* swap CHR halves */
    set_chr_1k(0 ^ x, mmc3.r[0] & 0xFE); set_chr_1k(1 ^ x, mmc3.r[0] | 1);
    set_chr_1k(2 ^ x, mmc3.r[1] & 0xFE); set_chr_1k(3 ^ x, mmc3.r[1] | 1);
    for (int i = 0; i < 4; i++) set_chr_1k((4 + i) ^ x, mmc3.r[2 + i]);
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

/* ---------------------------------------------------------------------- */

void mapper_init(void) {
    /* Power-on layout for every board: ROM laid out from the start and
       repeated to fill 32 KB (so 16 KB NROM appears twice). Each mapper's
       reset may then change it. */
    for (int i = 0; i < 4; i++) set_prg_8k(i, i);
    set_chr_8k(0);
    mapper.bank_changed = 0;

    switch (cart.mapper) {
    case 0: mapper.name = "NROM"; write_reg = nrom_write; break;
    case 1: mapper.name = "MMC1"; write_reg = mmc1_write; mmc1_reset(); break;
    case 2:
        mapper.name = "UxROM"; write_reg = uxrom_write;
        set_prg_16k(1, -1);
        break;
    case 3: mapper.name = "CNROM"; write_reg = cnrom_write; break;
    case 4: mapper.name = "MMC3"; write_reg = mmc3_write; mmc3_reset(); break;
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
    case 9: mapper.name = "MMC2"; write_reg = mmc2_write; mmc2_reset(); break;
    case 10: mapper.name = "MMC4"; write_reg = mmc2_write; mmc2_reset(); break;
    case 21: case 23: case 25:
        mapper.name = "VRC4"; write_reg = vrc_write; vrc_reset();
        break;
    case 22: mapper.name = "VRC2"; write_reg = vrc_write; vrc_reset(); break;
    case 28:
        mapper.name = "Action 53"; write_reg = a53_write; write_low = a53_select;
        a53_reset();
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

void mapper_write_low(uint16_t addr, uint8_t val) {
    if (!write_low) return;
    ppu_catch_up();
    write_low(addr, val);
    ppu_schedule();
}

void mapper_write(uint16_t addr, uint8_t val) {
    ppu_catch_up();     /* CHR or mirroring may change mid-frame */
    write_reg(addr, val);
    ppu_schedule();     /* an IRQ may now be due sooner */
    if (mapper.schedule) mapper.schedule();
}
