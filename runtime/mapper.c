/* nesrecomp runtime: mapper implementations. Each one is a reset function
   (power-on banks) and a write function (its registers). */
#include <stdio.h>
#include <stdlib.h>
#include "cart.h"
#include "mapper.h"
#include "ppu.h"
#include "rt.h"
#include "event.h"

struct mapper mapper;
static void (*write_reg)(uint16_t addr, uint8_t val);

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

void mapper_write(uint16_t addr, uint8_t val) {
    ppu_catch_up();     /* CHR or mirroring may change mid-frame */
    write_reg(addr, val);
    ppu_schedule();     /* an IRQ may now be due sooner */
}
