# Plan: the mappers your games need

Goal: support the nine mapper numbers your own games stop at
("MAPPER NN IS NOT SUPPORTED"), in order of size, the way earlier
mappers were added: each board is an entry in the recompiler's mapper
table (`recomp.py`'s `MAPPERS` and `recomp/rom.c`'s `mappers[]`, which
must agree: which program slots switch together, which are fixed, what's
there at power-on) plus its registers in `runtime/mapper.c`.

At every step:
- `make test-all` must not get worse, and nestest stays exact;
- the 395 test files recompile to the same C, byte for byte, and
  `make test-recomp` shows `recomp.py` and the C recompiler agree;
- GitHub's Windows run stays green (it runs on every push to main).

## Your list

| Mapper | Board | Your games |
|---|---|---|
| 71 | Camerica / Codemasters (BF9093, BF9097) | Cosmic Spacehead |
| 79 | AVE NINA-03 / NINA-06 | Blackjack, Deathbots, Dudes with Attitude |
| 41 | Caltron 6-in-1 | Caltron 6 in 1 |
| 112 | NTDEC / Asder | Chik Bik Ji Jin |
| 172 | TXC 22211 (Jiahe variant) | 1991 Du Ma Racing |
| 228 | Active Enterprises | Action 52, Cheetahmen II |
| 119 | Nintendo TQROM (MMC3) | High Speed |
| 16 | Bandai FCG-1/2, LZ93D50 | Battle Rush |
| 68 | Sunsoft-4 | After Burner |

## How they're tested

Not with your games: with free test ROMs where the collection has one,
and otherwise with small test ROMs the project generates
(`tests/make_<board>_test.py`), as for MMC1, GxROM, VRC4 and MMC2. Each
writes the board's registers as the nesdev wiki describes them and
checks what the program then sees: the right bank at each address, the
right graphics, the mirroring, the board's IRQ or save memory. It reports
a status code (`$00` all right, another number for each thing that's
wrong) and, where pictures matter, gives a picture to compare.

Every check is confirmed by breaking that feature on purpose, in a
scratch copy, and seeing it fail with its own code. The tests prove the
code matches the documentation, not the real boards; your games are the
real-world check, yours to try in the app after each step.

## Steps

### 1. Small boards: 71, 79 and 41 (done)
- **71, Camerica/Codemasters:** 16 KB at `$8000` switched by writes to
  `$C000-$FFFF`, the last 16 KB fixed, graphics in RAM. The BF9097
  variant (Fire Hawk) also picks one-screen mirroring with writes to
  `$8000-$9FFF`; told apart by the NES 2.0 submapper when there is one,
  and both decoded when there isn't.
- **79, AVE NINA-03/06:** one register in `$4100-$5FFF` (addresses where
  `A8` is set): 32 KB of program and 8 KB of graphics. The register is
  below `$8000`, so a store there can switch the running code out: the
  recompiler's `low_regs`, as for MMC5.
- **41, Caltron 6-in-1:** an outer register in `$6000-$67FF` whose
  address bits (not data) pick the 32 KB program bank, the graphics
  block and the mirroring, and an inner register at `$8000-$FFFF`,
  writable only in the last game slots, for the graphics bank. Also
  `low_regs`.
- Checks: `make_camerica_test.py`, `make_nina_test.py`,
  `make_caltron_test.py`.
- Breaks: the wrong bank bits, the fixed bank switching, the register
  answered at the wrong addresses, the outer register's lock ignored.

Done, following the nesdev wiki's pages for each board:
- **71, Camerica/Codemasters:** 16 KB at `$8000` picked by writes to
  `$C000-$FFFF`, the last 16 KB fixed, CHR RAM. The BF9097's one-screen
  mirroring is bit 4 of writes to `$8000-$9FFF`: with submapper 1 it is
  on from the start; with submapper 0 (or no NES 2.0 header) the
  header's mirroring holds until the game first writes there.
- **79, AVE NINA-03/06:** the register answers where
  `addr & $E100 == $4100`; bit 3 picks the 32 KB program bank, bits 0-2
  the 8 KB graphics bank. `low_regs` covers `$4100-$5FFF`.
- **41, Caltron 6-in-1:** the outer register is the address of a write
  to `$6000-$67FF` (..MCCEPP: mirroring, the high graphics bits, the
  enable bit, the program bank); the inner graphics register at
  `$8000-$FFFF` works only while the enable bit is set, with bus
  conflicts. `low_regs` covers `$6000-$67FF`.
- A new runtime hook, `mapper.write_6000` / `mapper_write_6000()`, for
  boards that watch writes to `$6000-$7FFF`.
- Both recompiler tables have the three boards (the C table kept in
  number order).

Checks: `tests/camerica_switch.nes`, `nina_switch.nes` and
`caltron_switch.nes`, made by `make_camerica_test.py`,
`make_nina_test.py` and `make_caltron_test.py` (shared code in
`mappers3_common.py`; each generator's docstring lists its status
codes). All three pass. The Caltron test writes its registers at
`$6700-$673F`, so it doesn't overwrite the test-status bytes at
`$6000-$6004`. The Camerica test has its program in every bank, so a
broken fixed bank reports status 5 instead of crashing.

Breaks, in scratch copies: 14 of 14 caught with their own FAIL lines.
For 71: the program bits, `$C000` not fixed, the header's mirroring
ignored, mirroring answered at `$A000`, the one-screen pages swapped.
For 79: the program bit, the graphics bits, no `A8` check, only `$41xx`
answered. For 41: the lock ignored, the high graphics bits, no bus
conflict, mirroring swapped, the register answering above `$67FF`.

Results: `make test-all` 222 of 223 as before (test28 as always) plus
the 3 new ones; `tests/check_same_c.py` and `make test-recomp` pass.
`tests/same_c.txt` gained the three ROMs. Its other 390 changed lines
differ only in the listing's hash: each listing records the temporary
C file's name (`aN.c`, numbered by sorted position), and the new ROMs
moved the numbers along. The exit status, the C and the printed lines
are the same for all 396 earlier files. GitHub's Windows run (run 29,
test branch `mappers3-step1`) passed.

Not verified: taking `low_regs` away from 79 or 41 isn't caught,
because every bank of those test ROMs holds the same program, so
switching out the running code changes nothing the test can see. Your
games (Cosmic Spacehead, the AVE games, Caltron 6 in 1) are the real
check, yours to try in the app.

### 2. Multicarts with odd layouts: 228 and 172 (done)
- **228, Active Enterprises (Action 52, Cheetahmen II):** everything is
  in the written address: the program bank, which of the three ROM
  chips, 16 or 32 KB mode, mirroring; the data and the low address bits
  pick the graphics. Action 52's chips leave a gap (the third socket's
  512 KB is empty: chip 3 is the second ROM); the loader maps it as the
  wiki says. Plus the four 4-bit RAM cells at `$5FF0`.
- **172, TXC 22211 (Du Ma Racing):** a TXC chip with a register that is
  read back; mapper 172 has the graphics bits in reverse order and its
  own mirroring bit. The wiki's TXC page is followed bit for bit.
- Checks: `make_ae_test.py`, `make_txc_test.py`.
- Breaks: the chip gap ignored, 16/32 KB mode swapped, the read-back
  register wrong, 172's bits not reversed.

Done, following the nesdev wiki's pages ("INES Mapper 228", "INES
Mapper 172" and, for the chip 172 is built on, "INES Mapper 136"):
- **228, Active Enterprises:** a write to `$8000-$FFFF` sets everything
  from its address, `..MH HPPP PPS. CCCC` (mirroring, the 512 KB chip,
  the 16 KB bank, 32 or 16 KB mode, the high graphics bits), and the
  low two graphics bits from its data. Chip 3 is the file's third
  512 KB (Action 52's empty socket). The games expect `$00` written at
  power-on and on reset, so the runtime has a new hook,
  `mapper.reset`, called when the reset button is pressed, before the
  reset vector is read.
- **172, TXC 22211:** the wiki describes it as mapper 136's JV001 chip
  mounted upside down, with the CPU's data bits D0-D5 reaching it as
  D5-D0. It's written that way: the chip's registers (Input, Register,
  Invert, Mode, Output) in the chip's own bit order, as the 136 page
  gives them, with the bits reversed on the way in and out. This also
  explains the 172 page's two different-looking CHR formulas (Output
  bits 5/4 in the CPU's order are bits 0/1 in the chip's). Registers
  where `addr & $E103` is `$4100-$4103`, read back at `$4100`; a write
  to `$8000-$FFFF` sets the CHR bank and the mirroring.
- Both recompiler tables have the two boards. 228 has no `low_regs`
  (its register is at `$8000-$FFFF`), and 172's program never moves.

Different from what this plan said, or the wiki leaves open:
- **No RAM at `$5FF0` for 228.** The wiki says the 4-bit RAM once
  described for this board isn't on either cartridge, and neither game
  touches it, so there is none.
- **Chip 2 of 228** (the empty socket) reads as open bus on the real
  board, says the wiki. Here it is the third chip, as in Mesen: neither
  game selects it, and open bus there would need a fake bank.
- **172 at power-on:** the wiki doesn't say. Here everything starts at 0,
  and the header's mirroring holds until the first `$8000` write.
  Reading `$4100` gives 0 in bits 6-7, as the runtime's open bus does
  everywhere (the games check the low six bits).

Checks: `tests/ae_switch.nes` (from `make_ae_test.py`: 1.5 MB of PRG
laid out as Action 52's three chips, 512 KB of CHR, the program in every
16 KB bank) and `tests/txc_switch.nes` (from `make_txc_test.py`). Both
pass; each generator's docstring lists its status codes. The 228 test
asks for the reset button (status `$81`) and checks the banks after it.
The 172 test's expected values were worked out by hand from the wiki, in
the CPU's bit order, and are written next to each check.

Breaks, in scratch copies: 19 of 19 caught, each with its own FAIL code.
For 228: the chip gap ignored, 16 and 32 KB modes swapped, 32 KB mode
keeping bit 0, the chip from the wrong address bits, the data's
graphics bits ignored, mirroring swapped, the register only at
`$8000-$BFFF`, nothing on the reset button. For 172: the input bits not
reversed, the read not reversed, the read inverting the wrong bits, the
`$4100` copy not inverted, the count carrying into bits 4-5, Invert from
the wrong data bit, the CHR bank from the wrong Output bits, mirroring
swapped, the header's mirroring replaced at power-on, the registers
answering without `A8`, the registers only at `$41xx`.

Results: `make test-all` 224 of 225 (test28 as always), nestest exact;
`tests/check_same_c.py` and `make test-recomp` pass. `tests/same_c.txt`
gained the two ROMs. Its other 397 changed lines differ only in the
listing's hash (the temporary C file names moved along again); the exit
status, the C and the printed lines are the same for all 399 earlier
files. The same-C list only covers files git tracks, so it was written
with a scratch index holding the two new ROMs, not the real one.

Not verified: chip 2's open bus (not built, see above), and anything
the wiki doesn't describe. Your games (Action 52, Cheetahmen II, 1991
Du Ma Racing) are the real check, yours to try in the app.

GitHub's Windows run (run 31, test branch `mappers3-step2`) passed.

### 3. MMC3's relatives: 112 and 119 (done)
- **112, NTDEC/Asder:** like MMC3 (a register select at `$8000`, the
  value at `$A000`): two 8 KB program banks, the last 16 KB fixed, two
  2 KB and four 1 KB graphics banks, mirroring at `$E000`; no IRQ.
- **119, TQROM:** an MMC3 whose graphics banks can point into 8 KB of
  graphics RAM as well as ROM (bit 6 of the bank number). Shares MMC3's
  code: only where a graphics bank points to changes.
- Checks: `make_ntdec_test.py`, `make_tqrom_test.py` (drawing from ROM
  and RAM banks in one picture).
- Breaks: 112's fixed banks wrong, TQROM's RAM bit ignored, MMC3's IRQ
  disturbed (the existing MMC3 tests must still pass).

Done, following the nesdev wiki's pages ("INES Mapper 112", "INES
Mapper 119"):
- **112, NTDEC/Asder:** its own small board in `runtime/mapper.c`
  (`ntdec_*`): registers where `addr & $E001` is `$8000` (select, bits
  0-2 only: no PRG or CHR mode bits), `$A000` (data) and `$E000`
  (bit 0: the wiki's "horizontal arrangement", which is vertical
  mirroring, or "vertical arrangement", horizontal mirroring). No IRQ.
- **119, TQROM:** the MMC3's code with one change: each CHR bank number
  goes through `mmc3_chr()`, which sends it to the board's 8 KB of CHR
  RAM when bit 6 is set (bits 0-2 pick the 1 KB bank, since the RAM only
  has 8 KB) and to CHR ROM otherwise (bits 0-5, up to 64 KB). RAM banks
  are marked writable; ROM banks aren't. For mapper 4 nothing changes.
- Both recompiler tables have the two boards: 112 with `$C000-$FFFF`
  fixed, 119 the same as MMC3.

Different from what this plan said, or the wiki leaves open:
- **112's fixed banks, 2 KB bank units and power-on** aren't on the
  wiki page. Here, as on the MMC3 it imitates: the last 16 KB fixed, a
  2 KB bank number counted in 1 KB banks with its low bit ignored, and
  the first 16 KB at `$8000` at power-on.
- **112's `$C000` register:** some emulators give 112 a register at
  `$C000` with extra CHR bank bits, for games with more than 256 KB of
  CHR. The wiki doesn't list it, so it isn't here. If Chik Bik Ji Jin
  shows wrong graphics, this is the first thing to look at.
- **No picture for TQROM:** the test reads ROM and RAM banks back
  through `$2007` instead, which checks the same thing with a status
  code for each case.

Checks: `tests/ntdec_switch.nes` (`make_ntdec_test.py`: 128 KB PRG,
128 KB CHR, the program in the fixed last 8 KB) and
`tests/tqrom_switch.nes` (`make_tqrom_test.py`: 128 KB PRG, 64 KB CHR
ROM, the CHR RAM; 1 and 2 KB RAM banks, the CHR swap bit, the RAM
wrapping at 8 KB, ROM not writable, the MMC3's PRG banks and its
scanline IRQ). Both pass; each generator's docstring lists its status
codes. The TQROM test turns the APU's frame IRQ off first: a first
version left it on, and a break of the MMC3's IRQ then hung in the IRQ
handler instead of failing, which also meant the passing run couldn't
prove which IRQ it had seen.

Breaks, in scratch copies: 19 of 19 caught, each with its own FAIL
code. For 112: `$C000` switching with R0, the wrong fixed bank, MMC3's
PRG mode bit obeyed, MMC3's CHR swap bit obeyed, select keeping bit 3,
2 KB banks in 2 KB units, mirroring swapped, odd addresses answered, a
register at `$C000`. For 119: the RAM bit ignored, the RAM not
writable, only 4 KB of RAM, ROM writable, writable marks not cleared,
RAM only through the 1 KB registers, RAM ignoring the swap bit, the
IRQ never enabled, no A12 hook, the PRG mode bit ignored. (A first run
caught 14: two breaks crashed because the 112 test ran from `$C000`,
and three found gaps in the tests; the tests were fixed and every break
run again.)

Results: `make test-all` 226 of 227 (test28 as always), nestest exact;
`tests/check_same_c.py` and `make test-recomp` pass. `tests/same_c.txt`
gained the two ROMs; its other 336 changed lines differ only in the
listing's hash, as in steps 1 and 2. The exit status, the C and the
printed lines are the same for all 401 earlier files.

Not verified: GitHub's Windows run (it starts with the push to main).
Your games (Chik Bik Ji Jin, High Speed) are the real check, yours to
try in the app.

### 4. Bandai FCG: 16 (done)
- 16 KB at `$8000`, the last 16 KB fixed, eight 1 KB graphics banks,
  mirroring, and a 16-bit IRQ counter clocked by the CPU. Its registers
  are at `$6000-$7FFF` on the FCG-1/2 chips and at `$8000-$FFFF` on the
  LZ93D50: the NES 2.0 submapper tells them apart, and without one both
  are decoded (as the wiki suggests). Some boards have a small save
  memory (a 24C01/24C02 EEPROM, talked to bit by bit); it's kept in
  `<rom>.sav` like battery RAM.
- About Battle Rush: it's a **Datach** game, which on the real thing
  plugs into a barcode reader (mapper 157, really). Saved as mapper 16
  it should start, but anything that needs a scanned card won't work.
  The reader isn't in this plan.
- Check: `make_bandai_test.py` (banks, the IRQ firing on the right
  cycle, the EEPROM written and read back, and kept across a restart).
- Breaks: the IRQ a cycle late, the register range wrong for a
  submapper, the EEPROM's acknowledge bit wrong, the save not kept.

Done, following the nesdev wiki's pages ("INES Mapper 016", "Bandai FCG
board", "INES Mapper 159"):
- **The registers** (`bandai_*` in `runtime/mapper.c`), by address AND
  `$000F`: 0-7 the 1 KB CHR banks, 8 the 16 KB PRG bank (bits 0-3), 9
  mirroring (0 vertical, 1 horizontal, 2/3 one-screen), A the IRQ
  enable (any write acknowledges), B/C the counter's low and high byte,
  D the EEPROM's lines. Submapper 4 (FCG-1/2) answers at `$6000-$7FFF`
  and B/C write the counter itself; submapper 5 (LZ93D50) answers at
  `$8000-$FFFF`, B/C write a latch, and every write to A copies it to
  the counter. Submapper 0 decodes both ranges, each acting as its own
  chip.
- **The IRQ:** while enabled, the counter counts down every CPU cycle,
  and a cycle that finds it at 0 raises the IRQ (so enabling it at 0
  fires at once, as the wiki says). Built like the FME-7's: the counter
  is brought up to date when touched, and an event is asked for the
  cycle it will fire.
- **The EEPROM:** a 24C02 (256 bytes) when the NES 2.0 header gives the
  LZ93D50 board 256 bytes or more of battery RAM, or, with no
  submapper, when the header has the battery bit. Its memory *is* that
  battery RAM, so the existing `<rom>.sav` code keeps it, with no new
  save path. Its data comes back in bit 4 of reads of `$6000-$7FFF`,
  through a new runtime hook, `mapper.read_6000`.
- The recompiler tables: 16 KB at `$8000` switches, the last 16 KB
  fixed, and `low_regs` over `$6000-$7FFF` for the FCG's registers.

Different from what this plan said, or the wiki leaves open:
- **The EEPROM's protocol** isn't on the wiki (its pages for the chips
  are gone). It follows the 24C02's own (I2C, as on its data sheets):
  start and stop conditions, bits most significant first, the device
  byte `$A0`/`$A1`, a word address, an acknowledge on each ninth clock,
  writes wrapping within an 8-byte page, reads going on while the
  program acknowledges. The chip's write time (about 5 ms, when it
  answers nothing) isn't modelled.
- **Only the 24C02.** The 128-byte X24C01 (submapper 1, mapper 159)
  talks differently and the wiki doesn't say how, so it isn't here;
  neither are the Datach (submapper 2, mapper 157) or submapper 3's
  8 KB RAM (mapper 153). They run as submapper 0, with a warning.
- **After the IRQ fires**, the counter goes on counting down from
  `$FFFF` (the wiki doesn't say; Mesen does this).
- **Power-on** (not given): every register 0, PRG bank 0 at `$8000`,
  the header's mirroring until register 9 is written.

Checks: `make_bandai_test.py` writes three ROMs: `bandai_fcg.nes`
(submapper 4), `bandai_lz.nes` (submapper 5 with the EEPROM) and
`bandai_both.nes` (iNES 1.0, no submapper). All three pass; the
generator's docstring lists the status codes. The IRQ is checked to the
cycle: the docstring works out by hand which instruction the IRQ should
interrupt for counters 20, 21 and 0, and counters 20 and 21 land on
different instructions, so one cycle either way shows. The runtime
landed exactly where the hand count said. `tests/check_bandai_save.py`
(now part of `make test-ppu`) runs `bandai_lz.nes` three times: the
EEPROM starts blank and the `.sav` holds the 256 bytes written; the
second run finds them; a byte changed in the `.sav` is what the third
run reads.

Breaks, in scratch copies: 28 of 28 caught, each with its own FAIL
code (the save one by the save check): the IRQ a cycle late, a cycle
early, enabling at 0 waiting a full count, the LZ93D50's latch not
copied, its B/C writing the counter, the FCG copying a latch, no
acknowledge, no disable, submapper 4 answering at `$8000`, submapper 5
at `$6000`, submapper 0 ignoring `$6000`, the FCG only at
`$6000-$600F`, the LZ93D50 only at `$8000-$800F`, `$C000` switching,
mirroring swapped, the one-screen pages swapped, the CHR registers
reversed; for the EEPROM: no acknowledge of the device byte, none of
data bytes, bits least significant first, no page wrap, reads not
moving on, any device code answered, the data in bit 0, bit 7 not
letting SDA go, not kept in the battery RAM, the `$6000` read hook not
called, no EEPROM on submapper 5. (First runs found test gaps, all
fixed before the final run: the FCG test wrote its CHR registers over
its own status bytes at `$6000`, so it now uses the mirror at `$7F00`;
the test text was overwritten mid-word by the `$6008` check, so it's
written last; the one-screen check compared the two pages only with
each other.)

Results: `make test-all` 229 of 230 (test28 as always), nestest exact;
`tests/check_same_c.py` and `make test-recomp` pass. `tests/same_c.txt`
gained the three ROMs; its other 396 changed lines differ only in the
listing's hash. The exit status, the C and the printed lines are the
same for all 403 earlier files.

Not verified: GitHub's Windows run (it starts with the push to main).
Battle Rush is the real check, yours to try in the app; as a Datach
game, whatever needs a scanned card won't work.

### 5. Sunsoft-4: 68
- 16 KB at `$8000`, the last 16 KB fixed, four 2 KB graphics banks, and
  its special feature: the background's name tables can come from
  graphics ROM (two 1 KB banks) instead of the console's RAM. The
  runtime already lets a board supply name-table reads (`nt_read`, made
  for MMC5), so this is that hook plus mirroring. Program RAM at
  `$6000` with an enable bit. (Nantettatte!! Baseball's extra ROM
  cartridge isn't needed for After Burner, and isn't in this plan.)
- Check: `make_sunsoft4_test.py`, a picture whose background comes from
  graphics ROM, switched mid-way.
- Breaks: name tables from RAM when they should be ROM, the wrong 1 KB
  bank, mirroring wrong.

### 6. The suite, the README, the notes
- The new test ROMs in `tests/suite.txt`; the README's mapper list;
  where the stage ended, with the results and speed.
- The app needs no change: it builds whatever the recompiler accepts.
- A release (2.1) is a separate decision, after this.

## Not in this plan
- The Datach barcode reader (mapper 157) and its cards.
- Sunsoft-4's licensing ROM (Nantettatte!! Baseball).
- Mappers you haven't hit yet; the TV's message names them as before.

## Risks
- These boards are mostly unlicensed, and the wiki's notes on some (172
  above all) come from studying a few carts. The test ROMs check the
  code against the wiki; if one of your games still goes wrong, the
  wiki may be missing a detail, and we look at what that game does.
- Boards with registers below `$8000` (79, 41, 16) let a store switch
  out the code running it. `low_regs` handles this for MMC5; more
  boards using it is more of the recompiler's code paths to keep exact.
- Action 52's chip gap and Caltron's address-bit registers are unusual
  ways to switch banks: each gets its own breaks.
