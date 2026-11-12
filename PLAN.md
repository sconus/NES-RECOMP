# Plan: PPU, window, NMI, controllers

Goal: a recompiled NROM program opens a window, draws correct frames at
60 Hz, takes NMIs at vblank, and reads the keyboard as controller 1. The
recompiler stays generic: everything NES-hardware lives in `runtime/`, and
`recomp.py` only changes in ways that apply to every ROM.

`make test` (nestest, cycle-exact) must keep passing after every step.

## The one problem to fix first: interrupts never get a chance to run

`INTERRUPT_CHECK()` sits only at the `dispatch:` label. Translated code jumps
straight from label to label, so it only reaches `dispatch` on RTS, RTI,
`JMP (ind)` and fall-through into untranslated code. Almost every NES game
ends its reset code with `forever: JMP forever` and does all its work in the
NMI handler. That loop never touches `dispatch`, so an NMI would never fire.

Fix: check for a pending event at the top of every translated instruction,
the same place real hardware checks (between instructions).

    L_C123: if (cycles >= next_event) { pc = 0xC123; goto event; }
            STEP(0xC123); ...

- `next_event` is a `uint64_t` the runtime sets to the cycle of the next thing
  that needs the CPU's attention: the next vblank start, or "now" when an NMI
  is pending. One compare and a branch that is almost never taken.
- `event:` calls `runtime_event()` (PPU catch-up, frame present, input poll).
  If an NMI is due it pushes `pc` and P, sets I, adds 7 cycles, loads
  `$FFFA`, then `goto dispatch`. RTI already returns through `dispatch`, so
  landing back mid-function just works: every translated address is a case.
- The interpreter path goes through `dispatch` on every step, so it gets the
  same check there.
- When nothing is running (nestest), `next_event` stays `UINT64_MAX`, so the
  trace is unchanged.

## Steps

### 1. Pick and check the test ROMs (done)
The collection is cloned at `tests/roms/nes-test-roms` (a shallow git
clone, listed in `.gitignore`). `python3 tests/romlist.py tests/roms --nrom`
prints mapper, PRG/CHR size, mirroring and battery for each ROM: 221 of
the 289 are mapper 0.

Chosen ROMs, all NROM. Paths are relative to `tests/roms/nes-test-roms/`.

**Group A: report through `$6000`.** These can be checked automatically:
status byte at `$6000`, `DE B0 61` at `$6001-$6003`, text from `$6004`.
- `instr_test-v5/rom_singles/01..16`: CPU. A good first check of the
  per-instruction event change and the `$6000` harness, before the PPU
  draws anything.
- `ppu_vbl_nmi/rom_singles/01..10`: vblank flag and NMI timing, odd frames.
- `ppu_read_buffer/test_ppu_read_buffer.nes`, `ppu_open_bus/ppu_open_bus.nes`,
  `oam_read/oam_read.nes`.
- `cpu_interrupts_v2/rom_singles/2-nmi_and_brk.nes`. The others in that
  set need APU IRQs or DMC DMA, so they wait for the APU stage.

**Group B: result shown on screen only** (blargg 2005 suites). Each prints
its result as text in the nametable. The runner will dump the nametable
as text after N frames and look for the result line, so no screenshots
are needed.
- `blargg_ppu_tests_2005.09.15b/`: palette_ram, power_up_palette,
  sprite_ram, vbl_clear_time, vram_access. These use CHR RAM (CHR size 0).
- `sprite_hit_tests_2005.10.05/01..11`
- `sprite_overflow_tests/1..5`
- `vbl_nmi_timing/1..7`

**Group C: open-source homebrew**, for looking at real rendering and
input. All of these come with source.
- `nes15-1.0.0/nes15-NTSC.nes`: Fifteen Puzzle by Mathew Brenaman, BSD-style
  licence. Needs the controller. The main game target for this stage.
- `spritecans-2011/spritecans.nes`: tepples, "feel free to spread". Many
  sprites, tests the 8-per-line limit and flicker.
- `full_palette/full_palette.nes`, `stars_se/StarsSE.NES`: all 64
  colours, a starfield demo. (`scrolltest/scroll.nes` was on this list but
  is mapper 1, so it waits for the mapper stage.)

Left out for now: `instr_timing` and the `apu_*` and `dmc_*` sets (they
need the APU), `nrom368` (a non-standard 48 KB board), the PAL versions,
and anything in `other/` whose licence isn't clear.

### 2. Memory map and cartridge (done)
Now in `runtime/cart.c` (loader, CHR ROM/RAM, mirroring, `$6000` RAM),
`runtime/ppu.c` (PPU memory map, and the `$2000-$2007` register behaviour
including `v`/`t`/`x`/`w` and the `$2007` read buffer, pulled forward from
step 4), `runtime/input.c` (controller shift registers) and the bus in
`runtime/main.c`. `--info` prints a ROM's header facts.
- Load CHR ROM (or allocate 8 KB CHR RAM when the header says 0 banks) and
  the mirroring bit (or four-screen bit) from the header.
- Add 8 KB PRG RAM at `$6000-$7FFF`. Many blargg-style test ROMs write their
  result there (status byte at `$6000`, signature `DE B0 61` at `$6001`,
  text from `$6004`), which lets tests run without looking at the screen.
- Route `$2000-$3FFF` (mirrored every 8) to the PPU, `$4014` to OAM DMA,
  `$4016/$4017` to the controllers. APU registers stay ignored for now.

### 3. Recompiler change: per-instruction event check (done)
Every translated instruction starts with `EVENT_CHECK(addr)`, and
`recomp_run` has an `event:` block that calls `runtime_event()` and
enters the handler through `take_interrupt()` (both in `rt.h`).
`runtime/event.c` owns `next_event`, with `cpu_request_nmi()` and
`schedule_event()` for the PPU to call in step 4. nestest still passes.

Checked with a fake 60 Hz vblank on nes15: NMIs arrive in its wait loops
and RTI returns cleanly (the stack pointer stays put across 60,000 NMIs).
Without the checks the same program never gets an NMI at all. Cost:
generated code is about 33% bigger (nestest object 524 KB to 696 KB).
Speed is not a concern: 60,000 frames ran in 4.7 seconds, about 200 times
faster than real time.

### 4 and 5. PPU core and window (done)
- `runtime/ppu.c`: catch-up timing (341 x 262 dots, odd-frame skip),
  vblank flag and NMI at line 241 dot 1, flags cleared on the pre-render
  line, the rendering hardware's v/t copies and Y increment, and a
  scanline renderer: background with fine scroll and attributes, sprites
  (8x8, 8x16, flips, priority, 8 per line, overflow flag), left-edge
  clipping, greyscale, and sprite 0 hit flagged at the right dot.
  Colour emphasis bits are ignored for now.
- `runtime/palette.c`: the 64 colours are computed from the NTSC signal
  (voltage levels to YIQ to RGB), not copied from a palette file.
- `runtime/video_sdl.c`: 3x window, nearest-neighbour scaling, paced to
  60.0988 frames a second (960 frames took 16.2 s against 15.97 s
  expected, the difference being window startup). Escape or closing the
  window exits and still saves `.missed`.
- `runtime/screenshot.c`: PNG output through zlib.
- New options: `--headless`, `--frames N`, `--screenshot FILE`, `--scale N`.
  On exit the runtime prints a test ROM's `$6000` result if it has one.
- New make targets: `make game ROM=...`, `make run ROM=...`.
- Recompiler fix found on the way: a JMP, JSR or branch whose target
  wasn't translated (code in RAM, or where the tracer stopped) used to
  produce a `goto` to a missing label. It now goes through `dispatch`.

Results after this step (600 frames headless):

| Suite | Pass | Failing (all timing, for step 7, unless noted) |
|---|---|---|
| `sprite_hit_tests_2005.10.05` | 11 / 11 | |
| `ppu_vbl_nmi/rom_singles` | 3 / 10 | 02 set time, 04 control, 05 timing, 06 suppression, 07/08 NMI on/off timing, 10 odd-frame timing |
| `vbl_nmi_timing` | 2 / 7 | 2 vbl timing, 3 even/odd, 5 suppression, 6 NMI disable, 7 NMI timing |
| `sprite_overflow_tests` | 3 / 5 | 3 timing (flag set too early in the line), 4 obscure (the hardware's buggy search after the 8th sprite isn't modelled) |
| `blargg_ppu_tests_2005.09.15b` | 3 / 5 | vbl_clear_time; power_up_palette checks the author's own console, so it is skipped |

Homebrew: nes15, spritecans and StarsSE draw correctly. full_palette
showed stripes here; step 7 fixed it by drawing rendering-off lines per
dot.

### 6. Controllers (done)
- `$4016`/`$4017` shift registers were done in step 2 (`runtime/input.c`).
- Keyboard, read once per frame in `runtime/video_sdl.c`: arrows,
  X = A, Z = B, Return = Start, Right Shift = Select. Pressing opposite
  directions together cancels both, since a real D-pad can't do that.
- `--input FILE` scripts button presses by frame number (`120 start`,
  `126` to release), so headless tests can play. Checked on nes15:
  Start leaves the title screen, a scripted move slides tile 14 into the
  gap ("MOVES 1"), and Select runs the game's auto-solver to "SOLVED!".
- Controller 2 still reads nothing; game controllers can come later.

### 7. Timing details (done)
Every timing value below was tuned against a test's own expected
table, not guessed.
- **Accesses on the right cycle** (`recomp.py`, `mem_body`). Loads and
  stores that can reach `$2000-$401F` now add cycles up to the bus cycle
  where the real CPU makes the access. Indexed modes make the CPU's
  dummy read from the not-yet-carried address (`dummy_rd`, which only
  touches hardware registers). Read-modify-write instructions write the
  old value back before the new one. RAM and ROM accesses keep the
  short form, so most code is unchanged, and so is nestest.
- **CPU writes reach the PPU one dot after reads** (`WRITE_SKEW`).
- **Racing vblank**: reading `$2002` one dot before vblank stops the
  flag that frame; on the dot or one after cancels the NMI.
- **NMI delay** (`runtime/event.c`): an NMI is taken at an instruction
  boundary only if it was raised 6+ dots earlier (`NMI_LATENCY`).
  Otherwise one more instruction runs. The handler's first instruction
  always runs before another NMI. Turning NMI off within 3 dots of it
  being raised cancels it.
- **NMI takes over BRK** if it arrives by BRK's 5th cycle
  (`brk_vector`): BRK jumps to the NMI vector, with B set on the stack.
- **Sprite overflow** is set at the dot the OAM search reaches the 9th
  sprite (2 dots per sprite, 8 for one in range), including the
  hardware's diagonal-byte bug after the 8th.
- **Rendering off is drawn per dot**, so palette changes partway along a
  line show up. full_palette now draws its colour grid; emphasis bands
  still repeat because emphasis isn't modelled.

Results: 53 of 57 graded tests pass (37 before this step).

| Suite | Pass |
|---|---|
| `ppu_vbl_nmi/rom_singles` | 10 / 10 |
| `vbl_nmi_timing` | 7 / 7 |
| `sprite_hit_tests_2005.10.05` | 11 / 11 |
| `sprite_overflow_tests` | 5 / 5 |
| `blargg_ppu_tests_2005.09.15b` | 4 / 4 (power_up_palette left out) |
| `oam_read`, `cpu_interrupts_v2/2-nmi_and_brk` | pass |
| `instr_test-v5/rom_singles` | 14 / 16 |

Still failing, none of them PPU timing:
- `instr_test-v5` 03 and 07: unofficial opcodes `$0B` and `$9C` (CPU).
- `ppu_read_buffer`: now passes the dummy-read check (#35) and stops at
  #70, which needs CNROM bank switching (the mapper stage).
- `ppu_open_bus` #3: the PPU's data-line value should fade to zero after
  about a second.

Speed after all this: 6000 frames of nes15 run headless in 3.9 s,
about 25 times real speed.

### 8. Test runner (done)
- `make test-ppu` runs `tests/run_tests.py` over `tests/suite.txt` (63
  entries) in parallel, in about 13 seconds. `make test-all` runs nestest
  too.
- Each ROM goes through the `.missed` loop: build, run, rebuild while
  the run keeps finding new code (up to 4 passes).
- How each kind is judged: `result` reads the `$6000` status (runs stop
  as soon as the ROM reports); `text` reads the screen through the new
  `--dump-text` option; `frame` compares a hash of the final picture,
  some driven by scripts in `tests/inputs/`.
- `tests/expected.txt` holds the accepted results, failures included.
  The runner marks each test ok, WORSE, better or changed, and exits 1
  only when something got worse. `--update` accepts new results. Checked
  by putting the old left-clip bug back: the runner flagged it as WORSE
  and exited 1.
- Baseline: 37 of 57 graded tests pass, and all 6 pictures match
  (53 of 57 after step 7).

New findings from the wider suite, outside this stage's PPU work:
- `instr_test-v5` 03 and 07 stop on unofficial opcodes the CPU doesn't
  have yet (`$0B` ANC, `$9C` SHY). The other 14 CPU tests pass.
- `ppu_read_buffer` #35 needs the CPU's dummy read on `STA abs,Y`
  (indexed writes read the address first, which matters for `$2007`).
- `ppu_open_bus` #3 needs the PPU's data-line value to fade to zero
  after about a second.

### 9. README (done)
README.md now covers the runtime's design, setup (SDL2, the ROM clone),
`make run`, the keys, the program's options and input scripts, the test
commands and current results, and an updated status list.

## After this stage: the missing unofficial opcodes (done)
Added to the opcode table in `recomp.py`: ANC, ALR, ARR, AXS, XAA, LXA
(immediate), SHY, SHX, AHX, TAS (stores that AND the value with the
address's high byte + 1, and replace that high byte when indexing crosses
a page), and LAS. XAA and LXA vary between consoles; they use the magic
value $FF, which is what `instr_test-v5` expects for LXA. Only the 12 JAM
opcodes are left untranslated. All 16 `instr_test-v5` tests pass, and the
suite is at 55 of 57. The two left are `ppu_read_buffer` #70 (needs the
CNROM mapper) and `ppu_open_bus` #3 (PPU open-bus decay).

## Not in this stage
APU/sound, mappers, controller 2, game controllers, save files.

## Order and checkpoints
1 → 2 → 3 (nestest still passes) → 4 + 5 together (first picture on screen
from a simple homebrew or PPU test) → 6 (input works) → 8 (automated PPU
tests) → 7 (fix timing tests that fail) → 9.
