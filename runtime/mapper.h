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
    /* NSFs with bank switching switch 4 KB at a time: which 4 KB bank
       each 4 KB slot holds ($8000, $9000, ...). Their recompiled code
       is keyed by these instead of prg_bank (code_4k is set). */
    int prg_bank_4k[8];
    int code_4k;
    uint8_t *chr[8];        /* what the PPU reads at $0000, $0400, ... */
    uint8_t chr_writable;   /* bit per slot: writable though CHR is ROM
                               (Namco 163 mapping nametable RAM there) */
    int bank_changed;       /* set when a PRG slot changes (for the CPU) */
    int power_on_bank[4];   /* prg_bank[] after reset (old .missed files) */
    int prg_ram_disabled;   /* $6000-$7FFF switched off by the mapper */
    int prg_ram_readonly;   /* $6000-$7FFF write-protected (MMC5) */
    uint8_t *ram6000;       /* what $6000-$7FFF reads and writes (8 KB) */
    /* Mappers that watch the PPU's A12 address line (MMC3) set this; the
       PPU calls it when A12 changes. `dot` is in ppu.dots units. */
    void (*a12)(int level, uint64_t dot);
    int watch_lines;        /* PPU should wake the CPU at each A12 clock */
    /* Mappers with their own clock (VRC4's IRQ counter) bring themselves
       up to the CPU's current cycle, and ask for an event when they next
       need attention. Called from runtime_event and after mapper writes. */
    void (*catch_up)(void);
    void (*schedule)(void);
    /* Called after every PPU read of pattern data ($0000-$1FFF), from
       rendering or $2007 (MMC2/MMC4 switch banks on certain tiles). */
    void (*chr_fetched)(uint16_t addr);
    /* MMC5. The PPU says which kind of pattern fetches come next (0 none:
       vblank, rendering off or $2007; 1 background; 2 sprites), so the
       mapper can switch between its CHR sets. */
    void (*ppu_phase)(int phase);
    /* Nametable reads and writes ($2000-$3EFF), when the mapper decides
       where each nametable comes from (MMC5's $5105, fill mode, ExRAM). */
    uint8_t (*nt_read)(uint16_t addr);
    void (*nt_write)(uint16_t addr, uint8_t val);
    /* Called at dot 4 of lines 0-240 with the line number while rendering
       a visible line, or -1 (line 240, or rendering off): MMC5 detects
       scanlines there. watch_scanlines asks the PPU to wake the CPU at
       each such dot. */
    void (*scanline)(int line);
    int watch_scanlines;
    /* MMC5's extended attributes: for the background tile the PPU is
       fetching through v, return 1 and give its palette and the 4 KB of
       CHR its pattern comes from; return 0 for the normal fetch. */
    int (*bg_tile)(uint16_t v, uint8_t *palette, const uint8_t **chr4k);
    /* Expansion sound: step the cartridge's own channels by one CPU cycle
       and return their output, in the same units as the APU's mix (its
       two pulses at full volume make about 0.26). Called by the APU for
       every cycle it mixes, so only when sound is being made. A chip
       calls apu_catch_up() before changing its sound registers, so the
       change lands on the right cycle. */
    float (*audio_step)(uint64_t cycle);    /* the CPU cycle being mixed */
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
/* CPU read of $4020-$5FFF: a mapper register (MMC5) or open bus (0). */
uint8_t mapper_read_low(uint16_t addr);

static inline uint8_t prg_read(uint16_t addr) {
    return mapper.prg[(addr >> 13) & 3][addr & 0x1FFF];
}
static inline uint8_t chr_read(uint16_t addr) {
    return mapper.chr[(addr >> 10) & 7][addr & 0x3FF];
}

#endif
