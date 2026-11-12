# Plan: mappers (bank switching)

Goal: recompile and run games and tests that use the common mappers:
CNROM (3), UxROM (2), AxROM (7), BNROM (34), MMC1 (1) and MMC3 (4). Between
them these cover most of the NES library. The recompiler stays generic: it
learns a mapper's bank layout from a small table, never from a particular
game.

`make test-all` must stay at its current results after every step.

## Why this is hard for a recompiler

Today a CPU address names one instruction: `$C123` is always the same
bytes, so it gets one label, `L_C123`. With bank switching, `$8000` can
hold different code at different times (bank 3 now, bank 5 after a write
to the mapper). So:

- **Code is named by (bank, address).** Labels become `L_03_8000`, and
  `dispatch` looks up the bank currently mapped at `pc` as well as `pc`.
- **The tracer often can't know which bank a jump lands in.** A `JSR $8000`
  from the fixed bank reaches whatever bank is mapped at that moment.
  Such jumps go through `dispatch` (a runtime lookup), and anything the
  tracer didn't see is run by the interpreter and saved to `.missed` as
  `bank:address`. That is the same feedback loop as today, keyed by
  bank.
- **Code can switch the bank it's running from.** After any write that
  could reach a mapper register (`$8000-$FFFF`, or an unknown address),
  the generated code checks a `bank_changed` flag and, if set, continues
  through `dispatch` instead of a direct `goto`. Mapper writes only set
  the flag when the mapping really changes (MMC1 takes 5 writes).
- **What stays direct:** jumps and branches inside the same bank window,
  and jumps into windows a mapper never switches (like UxROM's last 16 KB).
  RTS and RTI already go through `dispatch`, which is what makes returning
  into a different bank correct.

Everything is keyed by 8 KB bank numbers, the smallest PRG unit
these mappers use (MMC3), so one scheme fits every mapper.

## Test ROMs found (all in the existing clone)

| Mapper | ROMs | Reports via |
|---|---|---|
| 3 CNROM | `ppu_read_buffer` (now fails #70 on CNROM), `cpu_dummy_reads`, `read_joy3/*` | `$6000` / screen |
| 2 UxROM, 34 BNROM | `240pee/240pee.nes`, `240pee-bnrom.nes` (tepples' 240p test suite) | picture |
| 1 MMC1 | combined blargg ROMs: `instr_test-v5/all_instrs.nes`, `official_only.nes`, `ppu_vbl_nmi/ppu_vbl_nmi.nes`, `instr_misc/instr_misc.nes`, `cpu_interrupts_v2/cpu_interrupts.nes`; `MMC1_A12/mmc1_a12.nes`; `scrolltest/scroll.nes` | `$6000` / picture |
| 4 MMC3 | `mmc3_test_2/rom_singles/1..6`, `mmc3_irq_tests/1..6` | `$6000` / screen |

The MMC1 combined ROMs are especially useful: they run tests we already
pass one by one, switching banks between them. `240pee` has no licence
file in the clone; the upstream project is published as open source,
which should be checked before relying on it. `stomper` (MMC3) is left
out because it plays Super Mario World music.

AxROM (7) has only `other/oam3.nes`, whose licence isn't clear, so it gets
implemented from the docs and checked with a hand-made test if needed.
MMC5, VRC and the rest are out of scope.

## Steps

### 1. Runtime mapper layer, CHR banking first (CNROM) (done)
Done: `runtime/mapper.c` with 8 KB PRG and 1 KB CHR slots, NROM and
CNROM (with bus conflicts), single-screen mirroring modes, and the CPU
bus and PPU reading through the slots. `recomp.py` accepts mappers whose
PRG never moves (0 and 3) without a warning. `ppu_read_buffer` now
passes completely and `cpu_dummy_reads` passes too, so the suite is at
57 of 58; only `ppu_open_bus` #3 fails. The `read_joy3` tests need the
APU's DMC channel, so they wait for the sound stage.

Original notes:
- `runtime/mapper.c`: the cartridge's CPU and PPU windows as slots: four
  8 KB PRG slots for `$8000-$FFFF`, eight 1 KB CHR slots for the pattern
  tables, plus mirroring, PRG-RAM enable and an IRQ line. Each mapper is a
  reset function and a register-write function that fill the slots.
- The CPU bus and the PPU read through the slots. Mirroring can now change
  at runtime and gains single-screen modes (AxROM, MMC1).
- Mapper writes catch the PPU up first, so a mid-frame CHR or mirroring
  change lands on the right scanline.
- Bus conflicts: on CNROM, UxROM and BNROM boards the ROM drives the bus
  too, so a register write sees the value ANDed with the ROM byte at that
  address. Games work around it by writing to a byte that holds the same
  value; modelling the AND keeps both kinds of game working.
- CNROM switches only CHR, so the recompiler needs no change yet.
  Checkpoint: `ppu_read_buffer` passes, plus `cpu_dummy_reads` and
  `read_joy3`.

### 2. Banked recompilation (UxROM, BNROM, AxROM) (done)
Done:
- `recomp.py` has a `MAPPERS` table (which slots switch together, which
  never switch, the power-on banks). Code is traced and labelled by
  (8 KB bank, address), e.g. `L_03_8000`. `Rom.resolve` decides whether
  a jump target's bank is known: same bank, a slot that moves with it, or
  a fixed slot gives a direct `goto`; anything else goes through
  `dispatch`, which switches on `bank << 16 | pc`.
- Stores in switchable code that could reach `$8000+` check
  `mapper.bank_changed` and continue through `dispatch` if it is set.
- `.missed` is now `BB:AAAA`; old `AAAA` files are read as the power-on
  bank and rewritten in the new format.
- Runtime: UxROM (with bus conflicts), AxROM (with one-screen mirroring),
  BNROM (with bus conflicts).
- Unsupported mappers now stop the recompiler with the list of supported
  ones.
- Speculative tracing wasn't needed: the feedback loop found everything
  in one or two passes.

Checks:
- NROM and CNROM results are unchanged, including all 6 pictures.
- Both 240pee builds draw identical pictures on their about page and after
  scripted menu navigation into a test. Its about page says it is free
  software.
- `tests/axrom_switch.nes`, made by `tests/make_axrom_test.py`, switches
  banks from inside the switching window. It passes; with the
  `bank_changed` checks stripped from the generated C it fails, so it
  catches that mistake.
- Suite: 58 of 59 pass, 10 pictures.

Original notes:
- `recomp.py` gets a mapper table: for each mapper, the PRG window size
  and which windows are fixed to which bank.
- Tracing runs per (bank, window); labels and `dispatch` are keyed by
  bank. NROM keeps working as the case with no switchable windows.
- `bank_changed` checks after possible mapper writes, as described above.
- `.missed` lines become `BB:AAAA`. Plain `AAAA` lines still load, as
  bank-less addresses.
- Optional speculative tracing: follow `JSR`/`JMP` targets from fixed
  code into every switchable bank, then measure how much it saves
  against how much extra code it generates.
- Checkpoint: the 240pee builds run and their menus draw. NROM results
  are unchanged.

### 3. MMC1 (done)
Done:
- Runtime: the 5-write serial register, reset by bit 7, all PRG modes
  (32 KB, first bank fixed, last bank fixed), 4/8 KB CHR, all four
  mirroring settings, PRG-RAM disable, the 512 KB (SUROM) outer bank, and
  ignoring a write on the cycle right after another.
- Recompiler: MMC1 in the table with no fixed slots (any slot can move
  depending on the mode). Writes that may reach a mapper are now made on
  their real cycle, so `INC $8000`-style double writes land back to back
  as the chip expects.

Finding: the blargg combined ROMs (`all_instrs`, `official_only`,
`ppu_vbl_nmi`) pass even with MMC1 program switching disabled, so they
don't test it. `tests/mmc1_switch.nes` (from `tests/make_mmc1_test.py`)
does, with one status code per check. Each check was confirmed by
breaking that part of the runtime and seeing its code reported: PRG
register ignored ($02), bit 7 keeping half a load ($03), back-to-back
writes accepted ($04), no `bank_changed` checks ($05), mode 2 wrong ($06),
32 KB mode wrong ($07), mirroring ignored ($08).

Suite: 62 of 65 pass, 12 pictures. New failures are expected:
`instr_misc` test 4 needs the APU, `cpu_interrupts` test 1 needs IRQs
and the APU. `mmc1_a12` and `scrolltest` are visual demos without a
pass/fail and are kept as picture checks.

Original notes:
- Serial 5-write register, PRG modes (32 KB, fix first, fix last),
  CHR 4/8 KB modes, mirroring, PRG-RAM enable. Writes on consecutive CPU
  cycles are ignored (the RMW double write), which `mmc1_a12` and some
  games depend on.
- Checkpoint: the combined blargg ROMs pass (all of `all_instrs.nes`
  and `ppu_vbl_nmi.nes` should, since their parts pass alone).

### 4. IRQs and MMC3 (done)
Done:
- CPU IRQs (`event.c`): a shared level-triggered line (`cpu_set_irq`,
  one bit per source), taken between instructions when I is clear, with
  the same delay rule as NMI. CLI and PLP let a waiting IRQ in only after
  the next instruction; RTI lets it in at once (`cpu_irq_poll`, emitted by
  `recomp.py` for those three).
- MMC3 (`mapper.c`): 8 KB PRG and 1/2 KB CHR banking with both mode bits,
  mirroring, and the IRQ counter (Super Mario Bros. 3-style chip). PRG-RAM
  protect is ignored, so `$6000` stays usable. In the recompiler table
  only `$E000` is fixed.
- A12 (`ppu.c`): the PPU reports A12 rises from its fetch pattern
  (sprite phase at dot 261, background prefetch at 325, the pre-render
  line's first fetch at dot 5 after vblank) and from `$2006`/`$2007` with
  rendering off. The mapper ignores rises after lows shorter than 9 dots.
  While the IRQ is enabled, the PPU wakes the CPU at each possible clock
  so IRQs arrive on time.

Tuning: the first version failed `4-scanline_timing` #9. Logging showed
the `$2000=$10` scanline-0 IRQ arriving a whole line late; the test's
constants (256 dots before the `$08` case) pointed at the pre-render
line's first background fetch, which fixed it.

Results: 10 of 12 MMC3 tests pass. The two failures (`6-MMC3_alt`,
`5.MMC3_rev_A`) check the different behaviour of some older MMC3 chips;
one chip can't pass both sets.

The MMC3 tests turned out not to notice wrong CLI timing, so
`tests/irq_timing.nes` (from `tests/make_irq_test.py`) checks the IRQ
rules directly, clocking the MMC3 counter by hand. Each check was
confirmed by breaking that rule: IRQ ignoring I ($02), CLI ($03), PLP
($04), RTI ($05), `$E000` not acknowledging ($06).

Suite: 73 of 78 pass, 12 pictures, all earlier results unchanged.

Original notes:
- The CPU learns IRQs: a level-triggered line in `event.c`, taken
  between instructions when `I` is clear, with the CLI/SEI/PLP one-
  instruction delay (`cpu_interrupts_v2/1-cli_latency` checks it).
- MMC3: 8 KB PRG and 1/2 KB CHR banking with its two modes, mirroring,
  PRG-RAM protect, and the scanline counter. The real counter is clocked
  by the PPU's A12 address line. Start with the usual approximation (one
  clock per rendered line at dot 260) and refine against `mmc3_test_2`
  and `mmc3_irq_tests`.
- Checkpoint: as many of the 12 MMC3 tests as the approximation allows.
  Then decide whether to track A12 properly.

### 5. Saves, suite, README (done)
Done:
- Battery saves: carts with the battery flag load `<rom>.sav` into
  `$6000-$7FFF` at start and write it on exit (through a temporary file
  and a rename). `--no-save` skips both, and the test runner always
  passes it so old saves can't change results. Checked with a throwaway
  battery ROM that increments `$7000` on each boot: three runs left 3 in
  the save, and a `--no-save` run left it alone.
- The suite has every ROM from this stage (78 graded, 12 pictures).
- README: bank switching, supported mappers, the `.missed` format,
  saves, the project's own test ROMs, results and status.

Stage result: 73 of 78 graded tests pass. The 5 failures are open-bus
decay, two that need the APU, and two that test older MMC3 chips.

Original notes:
- Battery-backed PRG RAM saved to `<rom>.sav` on exit and loaded at start.
- Add all the ROMs above to `tests/suite.txt`, accept the baseline.
- README: mapper list, `.missed` format, status.

## Not in this stage
Sound (APU) and its IRQ, MMC5, VRC and other less common mappers,
Famicom Disk System.
