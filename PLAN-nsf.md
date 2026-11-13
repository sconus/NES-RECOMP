# Plan: NSF music files

Goal: recompile an NSF file (NES music ripped or written as a stand-alone
program) into a native program that plays its songs: in a window with
keys to change song, or headless to a WAV file for tests.

`make test-all` must not get worse at any step; nestest stays exact.

## What an NSF is

- A 128-byte header (`NESM`, $1A), then program data loaded at the
  header's load address. No picture, no reset vector: the header gives an
  **init** address (called once per song, with the song number in A and
  0 = NTSC in X) and a **play** address (called at a fixed rate, normally
  60 times a second; the header gives the period in microseconds).
- Optional bank switching: if any of the 8 bytes at $70-$77 is non-zero,
  $8000-$FFFF is eight 4 KB slots set by writing $5FF8-$5FFF, and those
  bytes are the starting banks. The data's position in its first bank is
  the load address's low 12 bits.
- RAM at $6000-$7FFF, as on many cartridges.
- A byte saying which expansion sound chips it uses (VRC6, VRC7, FDS,
  MMC5, Namco 163, Sunsoft 5B), each at its usual addresses.
- Title, artist and copyright strings; PAL/NTSC flags; song count and
  starting song.

## What exists

- `recomp.py` reads iNES files only, finds code from the three
  interrupt vectors (plus `--entry`), and models banks as 8 KB slots.
- The runtime starts at the reset vector and runs until the program
  stops; there's no way to call a routine and get control back.
- Sound for the APU and every expansion chip except FDS, and the WAV
  writer and `tones` check the earlier stages built.

## Test material

- `nes_instr_test/nsf_singles/` (11 files): blargg's CPU instruction
  tests built as NSFs. They report through $6000 (status and text, as
  the `result` kind already reads) as well as by beeps, and their init
  routine runs for a long time without returning, which checks the
  player doesn't call play while init is still running.
- `other/dnsf2_enginetest3.nsf`: "The Amazing Engine Test", a 6-song
  homebrew music engine test (Drag, 2010). No bank switching, no
  expansion chips. A recorded regression check, like the `audio` kind
  for ROMs.
- `other/LINUS.NSF` is music from a commercial Codemasters game, so by
  this project's rule it's left out.
- Nothing in the collection uses bank switching or expansion chips, so
  the project writes small NSFs for those, as it did tone ROMs for the
  expansion-sound stage.

## Steps

### 1. Load and run an NSF (no bank switching) (done)
- `recomp.py` recognises the `NESM` header, places the data at its load
  address, and traces from init and play instead of the vectors.
- The runtime plays the NSF player's part: it calls init for the chosen
  song, and when init returns, calls play at the header's rate. A call
  pushes a return address the program can't reach by itself, so the
  routine's final RTS hands control back to the runtime. If init never
  returns, play is never called (what the blargg NSFs need); if play runs
  late, the next call waits rather than interrupting it.
- Between calls, time still passes: the APU and its interrupts keep
  running up to the next play call.
- Options: `--song N`, plus the usual `--wav` and a run length in frames
  (play calls).
- Check: the 11 `nsf_singles` pass through the `result` kind.

Done (`runtime/nsf.c`, `recomp.py`).
- `recomp.py` reads the `NESM` header, puts the program at its load
  address in 32 KB that never moves (an "NSF" entry in `MAPPERS`, number
  `0x1000`, outside the iNES numbers), and traces from init and play as
  well as the vectors (the blargg NSFs keep their own BRK handler there).
  Bank switching and load addresses below $8000 are refused for now.
- The runtime's driver is 6502 code at $4100-$417F, served by the NSF
  "mapper" and run by the fallback interpreter: it clears $4000-$4013,
  writes $0F to $4015 and $40 to $4017, calls init with the song in A
  and 0 in X, then loops: read the play timer at $41F0, and if it says
  play is due, JSR play. Each RTS lands back in the driver, so control
  always returns with no special mechanism, and play can never cut into
  init or into itself. The timer ticks on a fixed grid from the header's
  period (60 Hz if the header says 0); ticks missed while play ran late
  are merged into one. The driver isn't counted as "missed" code.
- `--song N` (from 1; default the header's start song); `--info` prints
  the title, artist, songs and routines.
- All 11 `nsf_singles` pass (`11-special` after one `.missed` pass).
  Making the driver call play before init fails them with blargg's
  "Internal error".
- `dnsf2_enginetest3.nsf`: play runs 299 times in 300 frames (its header
  asks for 16666 us against the PPU's 16639), and songs 2 and 6 make
  sound. Song 1 is silent on purpose: its play routine only writes
  $4017, never a note.
- Ordinary ROMs recompile to byte-identical C (nestest, VRC7,
  Streemerz checked). Results: 155 of 156 graded tests (test28 the only
  failure, as before), nestest exact.

### 2. Bank switching (done)
- 4 KB slots at $5FF8-$5FFF, the starting banks from the header, the
  load address's offset into the first bank. The recompiler's banks are
  8 KB today, so NSFs get a 4 KB unit (the change stays in the `Rom`
  model; generated code keeps switching on bank and address).
- Check: a generated NSF that switches banks under code that's running
  and checks what it sees, through the $6000 protocol.

Done.
- `recomp.py`: the slot size is now part of the `Rom` model
  (`slot_bits`: 13 for every iNES ROM, 12 for a bank-switched NSF), and
  every place that worked out a slot from an address goes through it.
  A banked NSF has eight 4 KB slots that each switch alone, none fixed,
  the header's banks at power-on, and `$5FF8-$5FFF` as mapper registers
  (`low_regs`), so stores there get the existing "did my own bank just
  change?" check. Its dispatch switches on `mapper.prg_bank_4k`, the
  4 KB bank under pc; every other program's generated C is unchanged.
- Runtime (`nsf.c`): the file is cut into 4 KB banks from the load
  address's offset; `$5FF8-$5FFF` switch slots. The CPU still reads
  through four 8 KB slots, so a banked NSF is read through a 32 KB copy,
  refreshed 4 KB at a time on each bank write. The driver writes the
  header's starting banks to `$5FF8-$5FFF` before init, as a hardware
  player does. `.missed` files count 4 KB banks for these NSFs.
- `tests/nsf_banks.nsf` (`make_nsf_test.py`): 12 banks, each tagged;
  checks the starting banks, that switching `$9000` leaves `$8000` (the
  other half of the same 8 KB) alone, the same address running different
  code in two banks, code switching its own slot and carrying on in the
  new bank, and the load offset. Passes through the interpreter on the
  first pass and fully translated by the third.
- Breaks, each failing it: no `bank_changed` on a switch (status 5,
  once translated), the load offset ignored (2), writes going to the
  wrong slot, the driver not setting the starting banks. That last one
  passed at first, because the runtime's reset also set them; reset now
  leaves the banks in order and only the driver sets them, so the check
  covers it.
- nestest, VRC7, MMC1, Streemerz and both step-1 NSFs recompile to
  byte-identical C. Results: 156 of 157 graded tests (test28 the only
  failure), nestest exact.

### 3. Playing music (done)
- A window showing the title, artist, copyright and song number;
  left/right to change song, R to restart it, M to mute.
- The play rate from the header (NTSC field; PAL with the PAL flag).
- Checks: a generated NSF whose play routine flips a pulse note every
  call, so the note's pitch measures the play rate (through the `tones`
  check), at the default 60 Hz and at an unusual rate. The engine
  test's songs recorded as `audio` regression checks.

Done.
- The screen (`nsf_draw` in `nsf.c`): "NSF MUSIC", the title, artist and
  copyright, "SONG n OF m", the time the song has played, and the keys,
  drawn with a small built-in 5x7 font (upper case; lower case is shown
  as upper case). The window is named after the title. `--screenshot`
  saves this screen for an NSF.
- Song changes: controller 1's Left and Right (the arrow keys, a game
  controller, or an input script) step through the songs, wrapping
  round. R restarts the song. Both go through the reset button: for an
  NSF, reset clears RAM ($0000-$07FF and $6000-$7FFF, as a player does
  before init) and starts the driver again with the chosen song
  (`cpu_reset_target` in `main.c`, used by `take_interrupt` in place of
  reading $FFFC).
- The play rate: the header's NTSC field, or its PAL field for an NSF
  marked PAL-only, which is also told it's on PAL (X = 1). The console is
  still NTSC, so such music plays at PAL speed but about 7% sharp;
  `--info` says so. 0 in the field means 60 Hz.
- The default 60 Hz couldn't be checked with a tone as planned: a play
  routine flipping the level 60 times a second makes a 30 Hz wave, below
  what the output filters let through cleanly. The rate tests use a fast
  rate instead (1136 us, 880 calls a second), so the note's pitch shows
  the rate exactly; the usual rate is covered by the engine test
  recordings.
- Checks:
  - `tests/nsf_rate.nsf` and `nsf_rate_pal.nsf` (`make_nsf_test.py`):
    notes of 440.1 and 220.1 Hz pass the `tones` check. Using the NTSC
    field for the PAL-only one gives 166.7 Hz; a fixed 60 Hz gives 60.1.
  - The engine test's songs 2-6 recorded (`audio`), and one recording
    changing songs from a script (5 to 6, round to 1, back to 6).
    Not clearing RAM on a song change, or not wrapping round, each
    change that recording.
  - After a song change, the sound registers get exactly the same 1032
    writes as when that song is started fresh (checked by logging the
    writes). The sound itself only correlates 0.66 with the fresh
    start, since the noise channel's random generator and other channel
    phases carry on across a restart, as they would on a hardware
    player.
  - A screenshot of the screen, before and after scripted song changes,
    checked by eye.
- Results: 158 of 159 graded tests (test28 the only failure), 8 sounds
  checked, nestest exact; the ROM reset tests pass through the changed
  reset path.

### 4. Expansion chips in NSFs (done)
- Turn on the chips the header lists, at their NSF addresses, using the
  sound code that already exists for VRC6, VRC7, MMC5, Namco 163 and
  Sunsoft 5B.
- Check: NSF versions of the expansion-sound stage's tone tests, with
  the same expected notes, so they must sound the same as the ROMs.

Done.
- `mapper.c`: each chip's sound code was pulled apart from its
  cartridge's bank switching (`vrc6_sound_write`, `fme_sound_data`, and a
  sound-only reset for each chip), so an NSF can use the sound without
  the rest. A new NSF section turns on the chips in header byte $7B, at
  their NSF addresses: VRC6 $9000-$B002, VRC7 $9010/$9030, MMC5
  $5000-$5015 (plus the $5205 multiplier and $5C00-$5FF5 as RAM),
  Namco 163 $4800 and $F800, 5B $C000/$E000. Their outputs are added
  together. The chips start fresh with each song.
- FDS (bit 2) isn't supported: a message says its part will be silent.
  `--info` lists the chips.
- `recomp.py`: stores to $8000-$FFFF are cycle-timed when they can
  reach something, which for an NSF now includes sound chips
  (`high_writes`). Programs without chips recompile to identical C.
- Checks: `tone_nsf` (`make_tone_test.py`) builds an NSF from the same
  notes as a tone ROM, timed by delay loops in init instead of the
  PPU; each chip's generator now also writes one
  (`tests/nsf_vrc6.nsf`, `nsf_vrc7`, `nsf_mmc5`, `nsf_n163`, `nsf_5b`),
  and each passes with the same expected notes as its ROM (VRC6 from
  mapper 24's addresses). `tests/nsf_two_chips.nsf` has VRC6 and 5B
  together. The ROMs regenerate byte-identical.
- Breaks, each failing a check: VRC7's select at $9000; Namco 163's
  address port ignored; MMC5's PCM and $5015 ignored; the VRC6 sawtooth
  ignored; only the first chip mixed (the two-chip test); chips never
  switched on. A first try at the "only one chip" break didn't break
  anything for that pair of chips, so it was redone.
- Not checked: that chips start fresh on a song change (nothing here
  changes song with a chip playing), and the write timing (a few cycles
  either way doesn't change a note).
- Results: 164 of 165 graded tests (test28 the only failure), nestest
  exact.

### 5. Suite, README, notes
Accept the new checks, document the NSF options and keys, and write
where the stage ended.

## Not in this stage
- The FDS (Famicom Disk System) sound chip: a new chip, not yet built
  for ROMs either.
- NSF2 and NSFe (newer formats with extra data, such as track names and
  lengths).
- Ending a song by itself after silence or a set time.

## Risks
- Getting control back after an RTS: the runtime has never had to call
  into the program and return. Step 1 will settle how, and it must not
  slow ordinary ROMs.
- Some NSFs copy code into RAM and run it there; the fallback
  interpreter should cover that, but no test here does it.
- 4 KB banks touch the recompiler's core model; step 2 has to keep
  every existing ROM's output unchanged.
