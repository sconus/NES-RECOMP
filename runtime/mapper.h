/* nesrecomp runtime: the cartridge's mapper (bank switching).

   The CPU sees cartridge ROM through four 8 KB slots ($8000, $A000,
   $C000, $E000) and the PPU sees pattern data through eight 1 KB slots
   ($0000-$1FFF). A mapper is just code that decides which bank of the ROM
   sits in each slot, plus nametable mirroring and (later) an IRQ line.
   Everything is counted in 8 KB PRG banks and 1 KB CHR banks, the
   smallest units any supported mapper uses. */
#ifndef NESRECOMP_MAPPER_H
#define NESRECOMP_MAPPER_H
#include <stdint.h>

struct mapper {
    uint8_t *prg[4];        /* what the CPU reads at $8000/$A000/$C000/$E000 */
    int prg_bank[4];        /* which 8 KB bank each PRG slot holds */
    uint8_t *chr[8];        /* what the PPU reads at $0000, $0400, ... */
    int bank_changed;       /* set when a PRG slot changes (for the CPU) */
    int power_on_bank[4];   /* prg_bank[] after reset (old .missed files) */
    int prg_ram_disabled;   /* $6000-$7FFF switched off by the mapper */
    /* Mappers that watch the PPU's A12 address line (MMC3) set this; the
       PPU calls it when A12 changes. `dot` is in ppu.dots units. */
    void (*a12)(int level, uint64_t dot);
    int watch_lines;        /* PPU should wake the CPU at each A12 clock */
    /* Mappers with their own clock (VRC4's IRQ counter) bring themselves
       up to the CPU's current cycle, and ask for an event when they next
       need attention. Called from runtime_event and after mapper writes. */
    void (*catch_up)(void);
    void (*schedule)(void);
    const char *name;
};

extern struct mapper mapper;

/* Set up the mapper named in the cartridge header. Exits if unsupported. */
void mapper_init(void);
/* Which MMC3 to behave like: 'B' (the default; most games) or 'A', an
   older chip (Crystalis) that raises its IRQ only when the counter
   reaches 0, not when it reloads a 0. Set with --mmc3-rev. */
extern char mmc3_revision;
/* CPU write to $8000-$FFFF. */
void mapper_write(uint16_t addr, uint8_t val);
/* CPU write to $4020-$5FFF, which some boards also decode (Action 53's
   register select). Ignored by the others. */
void mapper_write_low(uint16_t addr, uint8_t val);

static inline uint8_t prg_read(uint16_t addr) {
    return mapper.prg[(addr >> 13) & 3][addr & 0x1FFF];
}
static inline uint8_t chr_read(uint16_t addr) {
    return mapper.chr[(addr >> 10) & 7][addr & 0x3FF];
}

#endif
