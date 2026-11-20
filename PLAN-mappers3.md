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
- GitHub's Windows run stays green (a test branch, on your OK).

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

### 2. Multicarts with odd layouts: 228 and 172
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

### 3. MMC3's relatives: 112 and 119
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

### 4. Bandai FCG: 16
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
