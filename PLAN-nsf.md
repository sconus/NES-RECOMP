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

### 2. Bank switching
- 4 KB slots at $5FF8-$5FFF, the starting banks from the header, the
  load address's offset into the first bank. The recompiler's banks are
  8 KB today, so NSFs get a 4 KB unit (the change stays in the `Rom`
  model; generated code keeps switching on bank and address).
- Check: a generated NSF that switches banks under code that's running
  and checks what it sees, through the $6000 protocol.

### 3. Playing music
- A window showing the title, artist, copyright and song number;
  left/right to change song, R to restart it, M to mute.
- The play rate from the header (NTSC field; PAL with the PAL flag).
- Checks: a generated NSF whose play routine flips a pulse note every
  call, so the note's pitch measures the play rate (through the `tones`
  check), at the default 60 Hz and at an unusual rate. The engine
  test's songs recorded as `audio` regression checks.

### 4. Expansion chips in NSFs
- Turn on the chips the header lists, at their NSF addresses, using the
  sound code that already exists for VRC6, VRC7, MMC5, Namco 163 and
  Sunsoft 5B.
- Check: NSF versions of the expansion-sound stage's tone tests, with
  the same expected notes, so they must sound the same as the ROMs.

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
