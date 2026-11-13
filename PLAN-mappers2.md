# Plan: more mappers

Goal: support the next mappers that free test ROMs and homebrew use, in
order of size, keeping the recompiler generic: each new board is an
entry in `recomp.py`'s `MAPPERS` table (which PRG slots switch together,
which are fixed, what's there at power-on) plus its registers in
`runtime/mapper.c`.

`make test-all` must not get worse at any step; nestest stays exact.

## What the free ROM collection has

`python3 tests/romlist.py tests/roms` lists, besides the supported
mappers (0, 1, 2, 3, 4, 7, 34):

| Mapper | Board | ROMs |
|---|---|---|
| 11 | Color Dreams | `other/fceuxd`, `nestopia`, `nintendulator`, `test001` |
| 28 | Action 53 | `other/test28` (a test ROM), `other/Streemerz_bundle` (homebrew collection) |
| 22 | VRC2a (Konami) | `m22chrbankingtest/0-127` (CHR banking test, with a picture of the right result) |
| 5 | MMC5 | `mmc5test`, `mmc5test_v2`, `exram/mmc5exram`, `other/firefly` |

For boards with no free test ROM, the project writes its own, as it did
for MMC1 and AxROM (`tests/make_*.py`). Each check in those is confirmed
by breaking the feature on purpose.

## Steps

### 1. Simple discrete boards: Color Dreams (11) and GxROM (66) (done)
One register each: a 32 KB PRG bank and an 8 KB CHR bank in different
bits. Color Dreams has 4 ROMs to look at; GxROM gets a small generated
test ROM (`tests/make_gxrom_test.py`).

Done. Both are entries in `MAPPERS` (32 KB units, nothing fixed) and a
few lines in `mapper.c`:
- Color Dreams: CCCC LLPP (PRG bits 0-1, CHR bits 4-7; bits 2-3 drove
  the lockout-chip defeat). No bus conflicts: the nesdev wiki says
  released games have them but some prototypes break with them, so
  emulators should assume none unless an NES 2.0 header says so, and
  this runtime reads iNES 1.0 headers.
- GxROM: xxPP xxCC (PRG bits 4-5, CHR bits 0-1), with bus conflicts.

The four Color Dreams ROMs in `other/` have no notes or on-screen text.
Logging their register writes shows each one switches CHR from bank 0 to
bank 1 mid-frame, every frame, writing to ROM bytes that already hold the
value (so bus conflicts can't matter): raster tests, apparently one tuned
per emulator they're named after. `test001` is in the suite as a
regression picture only.

`tests/gxrom_switch.nes` (from `make_gxrom_test.py`) checks PRG
switching from inside the switched window, CHR switching, and the bus
conflict (`$33` written over a ROM `$21` must become `$21`). Breaking the
PRG bits, the CHR switch or the bus conflict on purpose gives status
`$02`, `$03` and `$04` respectively. Suite: 124 of 124, 15 pictures.

### 2. Action 53 (28) (done)
A multicart board: an outer bank and an inner bank that combine
according to a mode (32 KB, or 16 KB with either half fixed), plus
mirroring. Checks: `test28` and the `Streemerz` collection.

Done (`a53_*` in `runtime/mapper.c`), following the nesdev wiki page and
its reference implementation:
- `$5000-$5FFF` selects a register with bits 7 and 0 (`$00` CHR bank,
  `$01` inner bank, `$80` mode, `$81` outer bank); `$8000-$FFFF` writes
  it; no bus conflicts. Writes to `$4020-$5FFF` didn't reach the mapper
  before; `mapper_write_low` now passes them on (MMC5 will need it too).
- The 16 KB bank: the inner bank supplies as many low bits as the game
  size allows, the outer bank the rest; the fixed half of a 16 KB mode
  acts like 32 KB mode at the smallest size. One-screen mirroring can be
  flipped by bit 4 of writes to `$00`/`$01`.
- 32 KB of CHR RAM (the header can't say so in iNES 1.0).
- Power-on: the wiki only promises the last 16 KB at `$C000`; this starts
  in 32 KB mode with the last 32 KB, as it suggests.
- In `MAPPERS`: 16 KB units, nothing fixed, starting in the last 32 KB.

The Streemerz collection works: title, menu, a game's page, and launching
the game (through a routine the menu runs from RAM), whose title screen
appears. That's a picture check now, with its input script in
`tests/inputs/a53_streemerz.txt`. Ignoring the fixed half, the game size
or the outer bank each break it.

`test28` (2012) fails its check 2. Decoded from the ROM: it sets mode
`$00`, writes `$FF` to the outer bank, and then expects bank 0 at
`$8000` (check 2) and, after writing `$00` to the outer bank, the last
bank still at `$C000` (check 4). Under the wiki's rules and its
reference code, which this follows, mode `$00` with outer bank `$FF`
maps the last 32 KB, so the two checks can't both pass. Its source
couldn't be found (it isn't in the action53 repository), so the most
likely explanation, an older revision of the mapper, is unconfirmed.
It's in the suite as an expected failure.

### 3. Konami VRC2 and VRC4 (21, 22, 23, 25) (done)
8 KB PRG banks (with a swap mode on VRC4), 1 KB CHR banks written as two
4-bit halves, mirroring, and on VRC4 an IRQ counter clocked by the CPU
(by cycles or by approximate scanlines). The four mapper numbers are the
same chip family wired to different address lines; iNES 1.0 headers don't
say which wiring, so each mapper number accepts both of its variants.
Checks: `m22chrbankingtest` (against its reference picture), and a
generated VRC4 test for banking and the IRQ timing.

Done (`vrc_*` in `runtime/mapper.c`), from the nesdev wiki's "VRC2 and
VRC4" and "VRC IRQ" pages:
- Each mapper number decodes both of its wirings at once (they don't
  overlap): 21 = A1/A2 and A6/A7, 23 = A0/A1 and A2/A3, 25 = A1/A0 and
  A3/A2; 22 = A1/A0 only. 21, 23 and 25 are VRC4 (a superset of VRC2),
  22 is VRC2a, which drops the lowest CHR bank bit.
- PRG: 8 KB banks at `$8000` and `$A000`, the second-to-last at `$C000`
  (VRC4's swap mode exchanges `$8000` and `$C000`), the last at `$E000`.
  In `MAPPERS` like MMC3: only `$E000` fixed.
- CHR: eight 1 KB banks, each written as a low 4 bits and high 5 bits.
- VRC4's PRG RAM enable bit is ignored (the RAM stays usable); VRC2's
  1-bit latch at `$6000` is covered by plain RAM there.
- The IRQ counter has its own clock, so mappers got two new hooks,
  `catch_up` and `schedule`, called from `runtime_event` and after mapper
  writes, as the PPU and APU are. It's worked out one counter clock at a
  time: every CPU cycle in cycle mode, or in scanline mode whenever a
  prescaler that starts at 341 and loses 3 a cycle reaches 0 (114, 114,
  113 cycles).

Checks:
- `m22chrbankingtest` steps through CHR banks with mapper 22's dropped
  bit; it showed 007, 012 and 062 at frames 120, 200 and 1000, exactly
  as its source predicts. Frame 1000 is a picture check.
- `tests/vrc4_21.nes`, `vrc4_23.nes`, `vrc4_25.nes` (from
  `make_vrc4_test.py`) check PRG banks, swap mode, CHR (with the high
  nibble), one-screen mirroring, and the IRQ: cycle mode fires at 256
  cycles, scanline mode after two scanlines, and acknowledging with A = 0
  stops it. Registers are written through both wirings.
- Breaking each wiring, the swap mode, the CHR high nibble, one-screen
  mirroring, cycle mode, the acknowledge rule or the prescaler rate each
  fails exactly the check aimed at it.

Suite: 127 of 128 (the one failure is still `test28`), 17 pictures.

### 4. MMC2 and MMC4 (9, 10) (done)
CHR banks switched automatically when the PPU reads tile `$FD` or `$FE`
(a latch per pattern table), used for big animated characters. This
needs a hook on the PPU's pattern fetches, which the new dot-by-dot
renderer makes possible. No free ROM uses it, so a generated test checks
the latch timing.

Done (`mmc2_*` in `runtime/mapper.c`), from the nesdev wiki's MMC2 and
MMC4 pages:
- A new mapper hook, `chr_fetched`, is called after every PPU read of
  pattern data, from rendering or `$2007` (the wiki files these boards
  under "mappers triggering on reads"). Because it's called after the
  read, the tile that flips a latch is itself read from the old bank, as
  the wiki describes.
- Latch rules: `$xFD8` sets `$FD`, `$xFE8` sets `$FE`; on MMC2 the left
  table only reacts to exactly `$0FD8`/`$0FE8` (a tile's top row), the
  right table and both of MMC4's to the whole row range.
- PRG: MMC2 switches 8 KB at `$8000` with the last three fixed; MMC4
  switches 16 KB with the last 16 KB fixed. Both are `MAPPERS` entries
  with those fixed slots.
- The power-on latch state isn't documented; both start at `$FE`.
- Not modelled: the sprite unit's dummy fetches of tile `$FF` for empty
  slots, which with 8x16 sprites flip latch 1 at the ends of some lines
  (no known game relies on it; the renderer only fetches real sprites).

`tests/mmc2_9.nes` and `mmc4_10.nes` (from `make_mmc2_test.py`) check
PRG banks, all four CHR registers through both latches, MMC2's top-row
rule against MMC4's whole-tile rule, the old bank for the triggering
read, and mirroring. Breaking each of those fails its own status code
(the first mirroring check didn't notice, because the header already set
horizontal; the ROM now switches to vertical first). No measurable speed
cost from the hook (nes15: 4.6-4.9 s with and without it).

### 5. MMC5 (5)
The biggest Nintendo mapper:
- PRG in 8, 16 or 32 KB modes, with RAM or ROM in most slots;
- CHR in four sizes, with separate sets for sprites and backgrounds when
  sprites are 8x16;
- 1 KB of extra RAM (ExRAM) usable as a nametable, as per-tile colour and
  bank data, or as plain RAM;
- nametable mapping per quarter, including a fill mode;
- a scanline IRQ that detects the PPU's fetch pattern;
- an 8x8 multiplier.

The vertical split screen and MMC5's sound channels are left for later.
Checks: `mmc5test`, `mmc5test_v2`, `mmc5exram`, `firefly`. This step may
be split if it gets large.

### 6. Suite, README, notes
Add the new ROMs to the suite, update the README's mapper list and
status, and write where the stage ended.

## Not in this stage
- Expansion sound (VRC6, VRC7, MMC5's pulse channels, Namco 163, Sunsoft
  5B): its own stage, since it needs the APU mixer to take extra
  channels.
- Boards whose interesting part is sound (VRC6 24/26, FME-7 69, Namco
  163 19). They can come with the expansion sound stage.

## Risks
- Recompiling banked code depends on the `MAPPERS` table describing
  which slots move together. Boards with modes (Action 53, VRC4's swap
  mode, MMC5) are treated like MMC1: no slot is assumed fixed, so more
  jumps go through `dispatch`. That's correct but slower; it gets
  measured.
- MMC5 reacts to how the PPU fetches (its scanline detection and ExRAM
  attribute mode watch the fetches), so it leans on step 2-3 of the
  rendering stage being exact.
- The self-made test ROMs can only check what the documentation says.
  They prove the code matches the docs, not the hardware.
