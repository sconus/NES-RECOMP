# Plan: per-cycle bus timing

Goal: know, for every instruction, what the CPU does on each of its
cycles (read or write, and of what), so that DMC DMA and interrupts can
land on the exact cycle the real CPU would. That's what the 8 remaining
timing failures need:

- `dmc_dma_during_read4`: `dma_2007_read`, `dma_4016_read`,
  `double_2007_read`
- `sprdma_and_dmc_dma`, `sprdma_and_dmc_dma_512`
- `cpu_interrupts_v2` 3, 4, 5 (and the combined ROM, which stops at 3)

`make test-all` must not get worse at any step, and nestest must stay
cycle-exact.

## What's approximate today

The generated code adds an instruction's cycles in one go, except for
accesses to hardware registers, which already land on their real cycle.
Two things are then guessed at instruction granularity:

- **Interrupt polling.** The real CPU decides whether to take an NMI or IRQ
  at a fixed cycle near the end of each instruction (and at a different
  one for a taken branch that doesn't cross a page, which is exactly what
  `5-branch_delays_irq` checks). We approximate that with one tuned
  latency (`NMI_LATENCY`, `IRQ_LATENCY` = 6 dots).
- **DMC DMA.** The DMA halts the CPU on its first *read* cycle at or after
  the request; write cycles postpone it, and the fetch then has to wait
  for an aligned cycle (3 or 4 cycles in all). We only know the cycle of
  hardware accesses, so the halt position and the alignment are guessed
  (a constant 4 cycles), and the tests that sync to the DMC through those
  same pauses come out one cycle off.

## Approach: a cycle map per opcode, used only when needed

Rewriting the generated code to step one cycle at a time would make
every instruction slower and the code several times bigger, for
behaviour that only matters around the rare moments a DMA or interrupt
falls inside an instruction. Instead:

1. **A cycle map for every opcode**, generated from the opcode table in
   `recomp.py` into the runtime: for each cycle, read or write, and which
   address it uses (opcode fetch, operand, effective address, dummy
   read, stack). A check makes sure each map's length matches the
   instruction's cycle count (including page-cross and branch extras),
   so the table can't drift from the timing nestest already verifies.
2. **The runtime knows which instruction is running**: its start cycle
   and where it is. The generated code records them once per instruction
   (two stores, next to the existing event check). That costs some
   speed, so it gets measured: headless nes15 currently runs 6000 frames
   in 3.5 s, about 30 times faster than a real console.
3. **When a DMA or interrupt falls inside an instruction**, the runtime
   replays that instruction's map from its start to find the exact cycle:
   - interrupts: the polling cycle, so the latency constants go away;
   - DMA: the first read cycle at or after the request, then the
     alignment, giving 3 or 4 cycles from the real rule rather than a
     guess. If the halted cycle reads a hardware register, that read is
     repeated, whatever address it is.
4. **Sprite DMA** gets its own map (alternating read and write cycles), so
   a DMC fetch in the middle of it costs what the hardware's rules say.

The generated code's normal path doesn't change shape: no per-cycle
work happens unless an event lands inside an instruction.

## Steps

### 1. A safety net
This is the deepest change since the PPU stage, and the folder has no
version control. Set up git (`git init`, a `.gitignore` already exists,
and a first commit of the current state), so any step can be compared
with or rolled back to today. Needs your OK, since it creates a
repository.

### 2. Cycle maps
Generate the per-opcode maps from `recomp.py`'s table. Add a check (run
by `make test`) that every map's length equals the instruction's cycle
count in every case nestest exercises. Nothing uses the maps yet, so
nothing else changes.

### 3. Instruction tracking
Record the current instruction's start cycle and address. Measure the
speed cost on nes15 and on a heavy test ROM; if it's more than about 10%,
look for a cheaper way (for example deriving the start from the event
check that already runs on every instruction).

### 4. Exact interrupt polling
Replace `NMI_LATENCY`/`IRQ_LATENCY` with the polling cycle from the maps,
including the taken-branch case. The PPU and APU already report when
they raise a line, in dots. Re-check every interrupt and timing test
(`ppu_vbl_nmi`, `vbl_nmi_timing`, MMC3, `irq_timing`, `cpu_interrupts`),
since they were all tuned against the old constants.
Target: `cpu_interrupts_v2` 5, then 3.

### 5. Exact DMC DMA
Halt on the first read cycle at or after the request, using the maps;
then the alignment wait and the fetch. Repeat the halted read if it hits
a hardware register. Remove the `DMA_*` guesses that this replaces.
Target: the three `dmc_dma_during_read4` read tests.

### 6. Sprite DMA and DMC DMA together
Model `$4014` DMA cycle by cycle (read/write alternation, the
alignment cycle) and how a DMC fetch slots into it; also the IRQ check
around sprite DMA.
Target: both `sprdma_and_dmc_dma` and `cpu_interrupts_v2` 4.

### 7. Suite, README, notes
Accept the new baseline, update the README's results and status, and
record what each removed constant became.

## Risks
- Every timing value tuned so far was tuned against the old model. Steps
  4 and 5 may break tests that pass today before they fix the failing
  ones; each step only lands once the suite is no worse than before.
- Some of the 8 may need more than exact cycles (for example the PPU's
  own reaction to repeated `$2007` reads in `double_2007_read`). Those
  will be noted rather than forced.
