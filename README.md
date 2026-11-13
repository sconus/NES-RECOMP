# nesrecomp

A static recompiler for NES programs, built as a learning project. It turns
the 6502 machine code in a `.nes` file into C, which a normal compiler turns
into a native program for your Mac, with graphics in a window, sound,
keyboard controls, bank switching for the common cartridge types, and
battery saves.

## How it works

1. **Trace.** `recomp.py` starts at the cartridge's reset, NMI and IRQ
   vectors and follows every branch, jump and subroutine call to find the
   reachable code.
2. **Translate.** Each 6502 instruction becomes a few lines of C. Jumps and
   branches become `goto`s, so the CPU never "decodes" anything at runtime.
   Reads and writes that can reach the hardware registers (`$2000-$401F`)
   happen on the same CPU cycle as on the real console.
3. **Fall back.** Some code can't be found ahead of time (jump tables,
   addresses pushed onto the stack and "returned" to, code copied into
   RAM). When the native code lands somewhere untranslated, a small
   interpreter, generated from the same opcode table, runs it until
   execution reaches translated code again.
4. **Learn.** Each spot the interpreter had to handle is saved to
   `<rom>.missed` as `BB:AAAA` (8 KB bank, address). Recompiling with
   `--missed` translates those natively. Repeat until no new spots show up.
   `make game` does this for you.

The ROM's data (graphics, levels, music) is not copied into the generated C.
The program loads the `.nes` file when it starts, so the output is only
useful alongside the `.nes` file it was made from.

### Bank switching

Many cartridges hold more program ROM than the CPU can see at once, and
swap 8, 16 or 32 KB banks in and out by writing to the cartridge (the
mapper). So the same address can hold different code at different times:

- Code is named by (8 KB bank, address). Labels look like `L_03_8000`,
  and `dispatch` looks up the bank mapped at `pc` right now as well as
  `pc`.
- `recomp.py` has a small table per mapper: which slots switch together,
  which never switch, and what's mapped at power-on. A jump whose
  target bank is certain (same bank, or a slot that never switches)
  becomes a direct `goto`; anything else goes through `dispatch`.
- Code can switch out the bank it's running from. A store that could
  reach the mapper checks a "bank changed" flag afterwards and carries on
  through `dispatch` if it's set.

Supported mappers: 0 NROM, 1 MMC1, 2 UxROM, 3 CNROM, 4 MMC3 (with its
scanline IRQ), 7 AxROM, 9 MMC2, 10 MMC4, 11 Color Dreams, 21/22/23/25
Konami VRC2 and VRC4 (with VRC4's IRQ), 28 Action 53, 34 BNROM,
66 GxROM. `python3 tests/romlist.py <folder>` shows which mapper a ROM
uses.

### The rest of the console (`runtime/`)

- **Hardware events.** Every translated instruction starts with a cheap
  check, `cycles >= next_event`. When the PPU needs attention (a frame is
  done, an NMI is due) the check jumps to a small handler, which brings the
  hardware up to date and enters the NMI handler if needed. Without a
  check on every instruction, a game's `forever: JMP forever` loop would
  never see an NMI.
- **PPU** (`ppu.c`). The PPU doesn't run alongside the CPU: it catches up
  dot by dot whenever the CPU touches it or an event is due, and draws the
  way the real chip does: background tiles fetched every 8 dots through
  the scroll address as it is at that dot, each line's sprites prepared
  during the line before, and each pixel output at its own dot with
  `$2001` as it is then. So scroll, pattern table, CHR bank, greyscale and
  emphasis changes made partway through a line show from the right pixel
  (the `scanline` demo checks this). It covers background and sprites,
  sprite 0 hit, sprite overflow (including the hardware's search bug),
  the cycle-exact vblank and NMI behaviour the timing test ROMs check,
  and the "decay register": what write-only registers read back, each
  bit fading to 0 about 600 ms after it was last refreshed.
- **Colours** (`palette.c`). Worked out from the NTSC video signal the NES
  outputs (voltage levels to YIQ to RGB), not copied from a palette file,
  including the three colour-emphasis bits of `$2001`, which dim parts of
  that signal: 512 colours in all.
- **APU** (`apu.c`). The sound chip, also catching up on demand: length
  counters, the frame counter and its IRQ, envelopes, sweeps, the five
  channels (two pulses, triangle, noise, DMC) and the DMC's sample DMA,
  which pauses the CPU on the cycle the hardware would (only on a read,
  3 or 4 cycles, depending on get/put alignment) and can repeat a
  `$2007` or `$4016` read it lands on. When sound is wanted, the channels are mixed with the console's
  non-linear formulas, averaged down to 48 kHz and filtered like its
  output stage. Headless test runs skip the mixing, so they stay fast.
- **Window and speakers** (`video_sdl.c`). SDL2, 3x size, sharp pixels,
  paced to the NES's 60.1 frames a second. The video keeps the beat: the
  APU's sample clock is nudged by at most 0.5% to keep SDL's audio queue
  near 50 ms, so the sound neither drifts nor crackles.
- **Mappers** (`mapper.c`). The CPU sees ROM through four 8 KB slots and
  the PPU through eight 1 KB slots; each mapper decides what fills them.
  MMC3 counts scanlines from the PPU's A12 address line, which `ppu.c`
  reports. Two MMC3 revisions differ in when that counter raises its IRQ;
  the newer one (B) is the default, and `--mmc3-rev A` selects the older
  one, which a few boards (Crystalis) have. A cartridge doesn't say which
  it has.
- **Interrupts** (`event.c`). NMI and IRQ timing, decided on the cycle
  the real CPU checks (from each opcode's cycle map, `cycles.c`),
  including the one-instruction delay after CLI/PLP and taken branches,
  an NMI taking over a BRK or IRQ entry, and the reset button.
- **Cartridge** (`cart.c`, including battery saves), **controllers**
  (`input.c`), and the **CPU bus** and command line (`main.c`).

## On a Mac

Once:

    xcode-select --install
    brew install sdl2

For the test suite, also clone the free test ROM collection:

    git clone --depth 1 https://github.com/christopherpow/nes-test-roms.git tests/roms/nes-test-roms

`python3 tests/romlist.py tests/roms` lists each ROM's mapper, sizes and
mirroring (`--nrom` shows only mapper 0).

## Play something

    make run ROM=tests/roms/nes-test-roms/nes15-1.0.0/nes15-NTSC.nes

This recompiles the ROM into `build/<name>`, builds it and opens a window.
Run it again after playing for a while: anything the interpreter had to
handle gets translated natively on the next build. Paths with spaces
aren't supported by the Makefile.

Cartridges with a battery keep their `$6000-$7FFF` RAM in `<rom>.sav`
next to the ROM: it's loaded at start and written on exit.

Sound plays through the speakers unless you pass `--mute` (or press M).
`--wav FILE` also writes it to a file, with or without a window.

| Key | NES button |
|---|---|
| Arrow keys | D-pad |
| X | A |
| Z | B |
| Return | Start |
| Right Shift | Select |
| M | Mute / unmute |
| R | Reset button |
| Escape | Quit |

The built program takes options after the ROM path:

    --headless         no window (for tests)
    --frames N         stop after N frames
    --screenshot FILE  with --frames: save the last frame as a PNG
    --dump-text        with --frames: print the screen's tiles as text
    --no-save          don't load or write <rom>.sav (battery RAM)
    --wav FILE         write the sound to a WAV file
    --mute             no sound from the speakers (M toggles it)
    --audio-stats      print the sound queue depth once a second
    --input FILE       scripted button presses (below)
    --scale N          window size, N times 256x240 (default 3)
    --mmc3-rev A|B     which MMC3 chip to act like (default B)
    --info             print the cartridge header and exit
    --trace            print CPU state before every instruction
    --check-cycles     with --trace: check each instruction's length
                       against its cycle map
    --start HEX        start here instead of the reset vector

An input script holds one change per line: from frame N on, hold these
buttons (`a b select start up down left right`). A frame number on its
own releases everything. `tests/inputs/` has examples.

    120 start      # press Start at frame 120
    126            # release it

## Tests

    make test       # CPU: nestest, cycle-exact
    make test-ppu   # everything in tests/suite.txt (needs the ROM clone)
    make test-all   # both

`make test` checks the program's state after every one of nestest's 8,991
instructions against a reference log: registers, flags, stack pointer and
cycle count. It also checks that every instruction took as many cycles as
its cycle map says (the per-cycle bus activity `recomp.py` generates for
each opcode, used for exact DMA and interrupt timing).

`make test-ppu` (the name is from when it was only PPU tests) runs
`tests/run_tests.py`. It recompiles each ROM in
`tests/suite.txt` (with the `.missed` loop), runs it headless, and judges
it in one of these ways (the top of `tests/suite.txt` explains each):

- `result`: the `$6000` status byte newer test ROMs write. A ROM that
  asks for the reset button (status `$81`) gets it pressed automatically.
- `text` and `crc`: the result text, or a checksum the test's source
  lists as correct, read from the screen.
- `frame` and `audio`: a fingerprint of the final picture or of the
  recorded sound (regression checks for homebrew).
- `silence`: the `apu_mixer` tests play a tone and its exact inverse, so
  a correct mixer leaves near silence between their two beeps.

A suite line can also pass options to the program, such as
`--mmc3-rev=A`. It compares against `tests/expected.txt` and exits with
an error only if something got worse. After an improvement, accept the
new results with `python3 tests/run_tests.py --update`. To run part of
the suite, pass part of a path: `python3 tests/run_tests.py sprite_hit`.

Some checks needed test ROMs that didn't exist, so the project makes its
own. Each `tests/make_*.py` writes a small ROM into `tests/`:

- `make_axrom_test.py`: AxROM switching from inside the switched window.
- `make_mmc1_test.py`: MMC1's serial register, reset, PRG modes,
  mirroring, and its ignoring of back-to-back writes.
- `make_irq_test.py`: when the CPU takes an IRQ (I flag, CLI, PLP, RTI,
  acknowledge), using MMC3's counter as an IRQ source.
- `make_gxrom_test.py`: GxROM's PRG and CHR switching and its bus
  conflicts.
- `make_mmc2_test.py`: MMC2 and MMC4's tile-triggered CHR latches,
  driven through `$2007` reads.
- `make_vrc4_test.py`: one ROM per VRC4 mapper number (21, 23, 25):
  banking, swap mode, mirroring and the IRQ in both modes, through both
  address wirings each number covers.

Each check in these was confirmed by breaking that part of the runtime or
recompiler on purpose and seeing the test report it.

Current results: 129 of 130 graded tests pass, and the 17 pictures and 2
sound recordings match. That includes all 16 `instr_test-v5` CPU tests,
all of `ppu_vbl_nmi`, `vbl_nmi_timing`, the sprite 0 hit and sprite
overflow suites, blargg's 2005 PPU tests, all 8 `apu_test` and 11 blargg
APU tests, the three `apu_mixer` silence checks, all 8 reset tests, both
CNROM tests, all 12 MMC3 tests (the two for the older chip run with
`--mmc3-rev=A`), all of `cpu_interrupts_v2`, all of
`dmc_dma_during_read4`, both `sprdma_and_dmc_dma` tests and
`ppu_open_bus`. The one failure is `other/test28`, a 2012 Action 53 test
whose expectations contradict the nesdev wiki's reference
implementation; the Action 53 collection it was written for (Streemerz)
works.

`dmc_tests` (no readme, source or on-screen result) and the interactive
or display-only `read_joy3` tests are left out of the suite.

## Status

- [x] iNES loader, code tracer, 6502 to C translation
- [x] All official opcodes and all stable unofficial ones, cycle-accurate
      (only the 12 "JAM" opcodes that lock up a real CPU are left out)
- [x] Fallback interpreter and multi-pass `.missed` feedback
- [x] nestest passes in full
- [x] PPU (graphics) and an SDL window
- [x] NMI delivery at vblank, cycle-exact
- [x] Controller 1 on the keyboard, and scripted input for tests
- [x] Test ROM runner with a recorded baseline
- [x] Mappers 0, 1, 2, 3, 4, 7, 34, with banked recompilation
- [x] IRQs (MMC3 scanline counter) and battery saves
- [x] APU: sound through the speakers or a WAV file, frame and DMC IRQs
- [x] The reset button
- [x] Interrupt polling on the exact cycle, from per-opcode cycle maps
- [x] DMC DMA halting on the exact cycle, 3 or 4 cycles long
- [x] Sprite DMA cycle by cycle, with DMC fetches inside it
- [x] PPU open-bus decay
- [x] Colour emphasis
- [x] Mid-line scroll, `$2000`, `$2001` and CHR bank changes
- [ ] Other mappers (MMC5, VRC, ...) and Famicom expansion sound
- [ ] Controller 2 and game controllers

`PLAN.md`, `PLAN-mappers.md`, `PLAN-sound.md`, `PLAN-cycles.md` and
`PLAN-render.md` have the step-by-step notes for the graphics, mapper,
sound, per-cycle timing and rendering stages, including how each timing value was tuned and what was
tried for what still fails.
