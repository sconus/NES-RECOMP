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

### 1. A safety net (done)
This is the deepest change since the PPU stage, and the folder has no
version control. Set up git (`git init`, a `.gitignore` already exists,
and a first commit of the current state), so any step can be compared
with or rolled back to today. Needs your OK, since it creates a
repository.

Done: branch `main`, first commit of the state before this stage.
`.missed`, `.sav` and `.wav` files are ignored, since runs create them.

### 2. Cycle maps (done)
Generate the per-opcode maps from `recomp.py`'s table. Add a check (run
by `make test`) that every map's length equals the instruction's cycle
count in every case nestest exercises. Nothing uses the maps yet, so
nothing else changes.

Done. `recomp.py` builds a map for each of the 244 opcodes
(`cycle_map`, letters explained in `CYCLE_KEY`) and writes them into
the generated program as `cycle_map[256]`. Example: `LDA ($nn),Y` is
`F1LHyr`: opcode, operand, pointer low and high, a dummy read only when
adding Y crosses a page, then the read. `runtime/cycles.c` turns a map
into an instruction's length using the current registers. Two checks:

- When the recompiler starts, every map's always-happening cycles must
  equal the table's count, with the page-cross or branch cycles exactly
  where the table has a penalty.
- `--check-cycles` (with `--trace`) compares each instruction's length
  from its map with the cycles it really took. `make test` runs it on
  nestest (9,086 instructions, 227 opcodes). `instr_timing` 1 also
  passes it: 8.26 million instructions, 242 opcodes.

Breaking the page-cross rule for X or for Y, the taken-branch rule, or
the branch page-cross rule each made `make test` fail; dropping a cycle
from a map stopped the recompiler. Suite unchanged (111 of 123).

### 3. Instruction tracking (done)
Record the current instruction's start cycle and address. Measure the
speed cost on nes15 and on a heavy test ROM; if it's more than about 10%,
look for a cheaper way (for example deriving the start from the event
check that already runs on every instruction).

Done. `EVENT_CHECK`, at the top of every translated instruction, now
also stores `insn_pc` and `insn_start` (`runtime/rt.h`); the interpreter
does the same for each instruction it runs. Registers aren't saved: when
the runtime later looks back at an instruction, its real length (the
cycle count now minus `insn_start`) already says whether a page was
crossed or a branch taken.

`--check-cycles` also checks that both values are right before every
instruction. Leaving them out of the interpreter made `instr_timing` fail
that check at once.

Speed: no measurable cost. Five runs each of the old and new builds:
nes15, 6000 frames headless, 3.49-3.67 s for both; `instr_timing` 1
(mostly interpreted), 0.59-0.76 s for both. Suite unchanged (111 of 123).

### 4. Exact interrupt polling (done)
Replace `NMI_LATENCY`/`IRQ_LATENCY` with the polling cycle from the maps,
including the taken-branch case. The PPU and APU already report when
they raise a line, in dots. Re-check every interrupt and timing test
(`ppu_vbl_nmi`, `vbl_nmi_timing`, MMC3, `irq_timing`, `cpu_interrupts`),
since they were all tuned against the old constants.
Target: `cpu_interrupts_v2` 5, then 3.

Done; both targets pass (113 of 123). Three changes:

- **Polling cycle** (`poll_end` in `runtime/event.c`). The rule from the
  maps: the CPU decides on an instruction's second-to-last cycle, except
  a taken branch that stays on its page, which decides on its first. For
  every other instruction that is what the old rule already assumed, so
  only that case moved. Fixed `5-branch_delays_irq`.
- **An NMI that's too late no longer hides an IRQ.** When an NMI was
  pending but too late for a boundary, `runtime_event` returned without
  checking the IRQ. Now the IRQ entry starts, and the NMI can take it over
  as on hardware (`3-nmi_and_irq` rows 8-10).
- **Reading `$4015` reschedules the APU.** Clearing the frame IRQ flag
  didn't ask for a wake-up at the next frame IRQ, so that IRQ was only
  noticed when some other event happened to run, here the NMI, up to 7
  cycles late (`3-nmi_and_irq` rows 10-12).

`NMI_LATENCY` and `IRQ_LATENCY` stay, at 6 dots, but now mean something
narrower: how far into a CPU cycle the PPU and APU raise their lines,
measured from the polling cycle the map gives rather than from the end of
the instruction. Exact cycles alone don't remove them; that would need the
sub-cycle phase between the PPU's and CPU's clocks.

Every interrupt and timing test still passes (`ppu_vbl_nmi`,
`vbl_nmi_timing`, MMC3, `irq_timing`, `cpu_interrupts` 1 and 2). The
combined `cpu_interrupts` ROM now stops at test 4 instead of 3. The nes15
sound recording changed: an NMI landing after a taken branch now arrives
one instruction later, which moves some register writes by a few cycles
(RMS difference about 1% of the signal, no shift in time). Accepted as
the new baseline.

### 5. Exact DMC DMA (done)
Halt on the first read cycle at or after the request, using the maps;
then the alignment wait and the fetch. Repeat the halted read if it hits
a hardware register. Remove the `DMA_*` guesses that this replaces.
Target: the three `dmc_dma_during_read4` read tests.

Done; all three pass (116 of 123), from the rules on the nesdev wiki's
DMA page (`apu_dma_point` in `runtime/apu.c`):

- CPU cycles alternate get and put. `GET_PARITY` says which are gets; on
  hardware it's one of two at random from power-on, and the tests pass
  with either.
- A reload (the output unit took the buffered byte) first tries to halt
  on a put cycle, a load (a `$4015` write) on a get cycle.
- The CPU can only be halted on a read cycle. At an instruction boundary
  the instruction's write cycles are known from its cycle map and how
  long it took (`insn_writes_at` in `cycles.c`), and the halt moves past
  them one cycle at a time.
- Then the halt cycle, a dummy cycle, an alignment cycle if needed, and
  the fetch on a get cycle: 3 or 4 cycles, replacing the constant 4.
  When the halt lands on a register read, that read is repeated on each
  wasted cycle, as before ($4016 still only shifts once).

Breaking the rules one at a time: giving loads and reloads the same
starting cycle type, or a constant 4 cycles again, fails `dma_2007_read`
and `dma_4016_read`. Flipping `GET_PARITY` changes nothing, as on
hardware. Skipping write cycles isn't checked by any test in the suite
yet; it's there because the wiki says so.

`double_2007_read` turned out not to involve the DMC at all: an indexed
read makes two `$2007` reads on back-to-back cycles. Now a `$2007` read
within one CPU cycle of the last one returns the buffer from before the
last refill, while its own refill and increment still happen
(`READ_2007_REPEAT_DOTS` in `ppu.c`). That gives "22 44 55 66 77", one of
the four results the test lists for real consoles. The DMC's repeated
reads throw their values away, so `dma_2007_read` isn't affected.

Constants still there: `DMA_READ_AT` (1) and `DMA_START_DELAY` (2), the
offset between the CPU's cycle count and the APU's clock, which the
other APU tests were tuned with. `DMA_DURING_OAM_STALL` is for step 6.

### 6. Sprite DMA and DMC DMA together (done)
Model `$4014` DMA cycle by cycle (read/write alternation, the
alignment cycle) and how a DMC fetch slots into it; also the IRQ check
around sprite DMA.
Target: both `sprdma_and_dmc_dma` and `cpu_interrupts_v2` 4.

Done; all three pass, and so does the combined `cpu_interrupts` ROM
(120 of 123). The expected tables came from blargg's nesdev forum thread
(topic 6100) and another emulator's notes; both tests' output matches
them row for row.

- **Sprite DMA cycle by cycle** (`apu_oam_dma` in `runtime/apu.c`). The CPU
  halts on the cycle after the `$4014` write, waits for a get cycle, then
  makes 256 get/put pairs: 513 or 514 cycles, as before.
- **A DMC fetch around it**, from blargg's annotated table:
  - Its halt would land on a read before the write (the STA's own
    opcode or operand fetch): a normal DMC DMA first, +4.
  - It lands on the write or inside the copy: the CPU is already halted,
    so the DMC only needs its fetch on a get cycle two or more cycles
    after it tries to halt. It takes over one of the copy's gets, which
    waits for the next: +2.
  - Its fetch falls just after the copy (it tried on the next-to-last
    put): +1. It tried on the last put: +3.
- **The interrupt decision stays before the stall** (`cpu_late_stall` in
  `event.c`). The STA decided on its usual cycle, before the DMA, so an
  IRQ raised during the 513 halted cycles waits one instruction
  (`4-irq_and_dma`). The same goes for a DMC fetch that halts an
  instruction's last cycle or the next opcode fetch.

Each was checked by breaking it on purpose: dropping the pre-write case
fails `sprdma_and_dmc_dma`, the +2 case fails both, the end case fails
`_512`, and moving the decision back fails `cpu_interrupts` 4 and the
combined ROM. `DMA_DURING_OAM_STALL` (a constant 2) is gone.

### 7. Suite, README, notes (done)
Accept the new baseline, update the README's results and status, and
record what each removed constant became.

Done: baselines were accepted at each step; the README's results, status
list and runtime notes are current; the summary is below.

## Where the stage ended

All 8 target tests pass, plus the combined `cpu_interrupts` ROM: the
suite went from 111 to 120 of 123, nestest is still cycle-exact, and the
pictures and sounds match (nes15's sound recording was re-accepted once,
in step 4). Speed is unchanged: nes15 runs 6000 headless frames in about
3.5 s, as before the stage.

What the timing constants became:

| Before | Now |
|---|---|
| `NMI_LATENCY`, `IRQ_LATENCY` (6 dots before the end of the instruction) | Still 6 dots, but counted from the polling cycle the cycle map gives (`poll_end`), which moves for taken branches and for DMA stalls after the decision (`cpu_late_stall`). They now only cover where in a CPU cycle the PPU and APU raise their lines. |
| `DMA_STALL` (always 4 cycles) | Gone: 3 or 4 from get/put alignment, with loads and reloads trying to halt on different cycle types and write cycles postponing the halt. |
| `DMA_DURING_OAM_STALL` (2) | Gone: `apu_oam_dma` works sprite DMA out cycle by cycle (+2 inside the copy, +1 or +3 at its end, +4 before the write). |
| `DMA_READ_AT`, `DMA_START_DELAY` | Unchanged: the offset between the CPU's cycle count and the APU's clock, which the other APU tests were tuned with. |
| (new) `GET_PARITY` | Which cycles are gets; either value passes, as on hardware. |
| (new) `READ_2007_REPEAT_DOTS` | `$2007` reads one CPU cycle apart count as back to back. |

Why earlier attempts failed (`PLAN-sound.md` step 4): a 3-or-4 stall by
alignment had been tried and did worse. What was missing was the
difference between load and reload DMA (they first try to halt on
different kinds of cycle), and knowing which cycles of an instruction
are writes, which the cycle maps now provide.

Two bugs found on the way had nothing to do with exact cycles: an NMI
that was too late for a boundary stopped the IRQ check, and reading
`$4015` didn't reschedule the next frame IRQ.

Not covered by any test in the suite: write cycles postponing a DMC
halt, and a load DMA landing inside sprite DMA. Both follow the nesdev
wiki's DMA page.

Still failing, outside this stage: `ppu_open_bus` #3 (open-bus decay),
`mmc3_test_2/6-MMC3_alt` and `mmc3_irq_tests/5.MMC3_rev_A` (older MMC3
revisions).

## Risks (as planned)
- Every timing value tuned so far was tuned against the old model. Steps
  4 and 5 may break tests that pass today before they fix the failing
  ones; each step only lands once the suite is no worse than before.
  (In the end, nothing that passed broke.)
- Some of the 8 may need more than exact cycles (for example the PPU's
  own reaction to repeated `$2007` reads in `double_2007_read`). Those
  will be noted rather than forced. (That one did: see step 5.)
