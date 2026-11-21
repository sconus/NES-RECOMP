# Plan: save states, rewind and fast-forward

Goal: save the whole game at any moment and come back to it later,
hold a key to run time backwards, and hold a key to run fast. All of it
in the game program (`runtime/`), so it works the same on Mac and
Windows, in games run from the app and from `make run`.

At every step:
- `make test-all` must not get worse, and nestest stays exact;
- the generated C doesn't change at all (this is runtime work only): the
  396 test files recompile to the same C, byte for byte, and
  `make test-recomp` passes;
- GitHub's Windows run stays green (a test branch, on your OK).

## The hard part, and the answer

An emulator always knows where it is: a program counter and nothing
else. A recompiled game is real compiled code, so at a random moment it
is somewhere in the middle of C, and the C compiler's own variables
can't be saved.

The runtime already has a moment when none of that matters: the
**event block**. When the hardware needs attention, the translated
instruction stores the 6502's next address in `pc` and jumps to
`event`, which calls `runtime_event()` and then `goto dispatch`. At that
point the 6502's whole state is in plain global variables (`A`, `X`,
`Y`, `SP`, the flags, `pc`, `cycles`), the 6502 stack is in the console's
RAM, and the next thing that happens is a lookup by `pc`. So:

- **Saving** happens inside `runtime_event()`: copy the state out.
- **Loading** also happens inside `runtime_event()`: copy the state in,
  including `pc`, and let `goto dispatch` jump to wherever the loaded
  `pc` says, the same way an interrupt or a bank switch already does.

The key press arrives in `frame_done()`, which the PPU calls while it
catches up, often in the middle of an instruction (a read of `$2002`,
say), where saving would be wrong. So the key only sets a "save
wanted" or "load wanted" flag and asks for an event right away
(`schedule_event(cycles)`); the save or load happens at the next
instruction boundary.

A nice result: a state holds only the console, not the native code, so
a state saved before the game was rebuilt (after `--missed` learned new
spots, say) still loads in the new build.

## What a state holds

Everything that changes while a game runs. The first job of step 1 is
a full inventory, file by file, of the runtime's variables, sorted into
"saved" and "not saved, and why" (settings, window, the audio queue,
tables that never change). Expected contents:
- the CPU registers, `cycles`, `next_event` and the event scheduler's
  pending NMI, IRQ lines, reset and DMA stall (`event.c`);
- the 2 KB console RAM, `$6000` RAM, CHR RAM, and the PPU (`struct ppu`:
  registers, OAM, name tables, palette, the scroll and fetch latches,
  the dot and frame counters, the picture being drawn);
- the APU (channels, frame counter, DMC) and each sound chip (MMC5,
  Namco 163, VRC6, VRC7's FM, Sunsoft 5B, FDS);
- the mapper (`struct mapper` and each board's registers, IRQ counters);
- the controllers and devices (shift registers, Zapper, paddle,
  Four Score), and the FDS drive, with the disk's contents, since games
  write to the disk;
- `code_owner` (which code in RAM is still what was translated).

`struct mapper` and `struct cart` hold pointers into the ROM and RAM
(`prg[]`, `chr[]`, `ram6000`). Within one run they stay valid; a state
written to a file stores them as "which buffer, which offset" instead
(step 2). Function pointers (the MMC3's `a12` hook) belong to the
board, not the state, and aren't saved.

NSF music files get no save states (there's nothing to save that
matters).

### The inventory (step 1)

Every variable the runtime keeps at file level (and the few kept inside
a function), file by file, taken from the compiled objects' symbol
lists (`nm`), so none is missed by reading. Each part of a state has a
name and a size (`runtime/state.c`); this is the order they're in.

**Saved**
- `main.c` (`cpu_state`): `A X Y SP`, the flags `C Z I D V N`, `pc`,
  `cycles`, `insn_pc` and `insn_start` (the instruction the event
  follows: `poll_end` looks at it), the 2 KB `ram`, `code_owner`; and
  where an input script has got to (`script_pos`, `script_buttons`,
  `script_fire`, `script_trigger`) and `reset_wait` (moved out of
  `frame_done`), so a scripted run replays the same presses.
- `event.c` (`event_state`): `next_event`, `nmi_pending`, `nmi_dot`,
  `nmi_blocked_until`, `irq_sources`, `irq_dot`, `old_i_until`, `old_i`,
  `reset_requested`, `late_stall_insn`, `late_stall`.
- `cart.c`: `struct cart` (the current mirroring is in it), the $6000
  RAM (all `prg_ram_alloc` bytes: an FDS's 32 KB too), CHR RAM when the
  pattern data is RAM.
- `ppu.c`: all of `struct ppu` (registers, OAM, name tables, palette,
  the scroll latches `v t x w`, the read buffer and bus decay, dot and
  frame counters, the fetch and sprite latches, the picture being drawn).
- `apu.c` (`apu_state`): `struct apu`, `clock_now`, `last_4017`, the
  DMC's DMA (`dmc_dma_due`, `_requested`, `_request_at`, `_load`); of
  the sound output: the sample clock (`snd.at`, `next_sample`, `sum`,
  `count`), the filters, `primed` (moved out of `emit_sample`), and the
  samples made but not yet taken.
- `mapper.c` (`mapper_state`): `struct mapper`, and each board's own:
  `caltron_outer/inner`, `txc`, `a53`, `vrc`, `mmc2`, `mmc5`, `m5a`,
  `vrc6`, `fme` (FME-7 and 5B), `n163`, `vrc7`, `mmc1`, `mmc3`,
  `ntdec_select`, `ntdec_r`, `bandai`, `ee` (the EEPROM's state; its
  bytes are in the $6000 RAM), `sun4_nt`, `sun4_rom_nt`; `mmc5_ram`
  (56 KB) only on MMC5 and `tqrom_ram` only on TQROM.
- `input.c` (`input_state`): `pad_buttons`, `vaus`, `zapper`, and the
  shift registers `shift`, `shift1`, `strobe`, `vaus_shift`.
- `fds.c` (`fds_state`, FDS only): `struct fds` (the RAM adapter, the
  side in the drive, the timer IRQ), the sides as the program has
  written them (`fds.image`), the drive (`drive`, and its bit stream up
  to `drive.len`), the sound channel (`fs`), and whether its sound is on
  (`fds_sound_on`, $4023 bit 1; found in step 2: it is shared between
  files, and step 1's `nm` listing took only each file's own variables).

**Not saved, and why**
- Settings, fixed at start: `trace_on`, `check_cycles`, `port_device`,
  `famicom_vaus`, `famicom_zapper`, `four_players`, `mmc3_revision`,
  `conflicts`, `camerica_mirror_reg`, `tqrom`, `n163_gain`, `vaus_left`,
  the hooks (`read_low`, `write_low`, `ppu_frame_done`), and every
  command-line option in `main.c`.
- Tables that never change: `fme_dac`, the APU's mixer tables, the rate
  tables, the font, `fds.orig` (the image file's own copy).
- The window, the sound queue, recording and pictures (`video_sdl.c`,
  `record_*.c`, `screenshot.c`, `wav.c`, `gamepad.c`), `last_frame`,
  `stop_signal`, and the sample clock's rate trim (it follows the
  speakers, not the console).
- What ran how: `insn_count`, `ram_native`, `ram_interp`, and the
  `.missed` notes (`missed`, `missed_count`). A load doesn't undo them.
- `cycles.c`: only used by `--check-cycles` with `--trace`.
- Scratch inside a function: `fds_file_tag`'s and `fds_code_banks`'
  file lists, `fds_audio_step`'s filter constant (worked out once).
- NSF music (`nsf.c`, `nsf_chips`, `nsf_exram`, `nsf_next_song`,
  `song_frames`, `nsf_controls`' `held`): no save states.
- The generated code's local variables: `ea`, `base` and `v` hold
  nothing between instructions; `in_interp` only decides what is noted
  in `.missed`.

Pointers inside the saved structs (`struct mapper`'s banks, `struct
cart`'s buffers, `ppu.fetch_chr`, `ee.mem`, the FDS's buffers) point at
this run's own memory, so within one run they're put back as they were;
the FDS's buffers stay this run's whatever the state says. Step 2 writes
them as "which buffer, which offset".

## How it's tested

A new headless check, `--state-test N M`: run N frames; take a state;
run M more frames, noting a fingerprint of each frame (the picture, the
RAM, the sound samples); load the state; run the same M frames again.
Every fingerprint must match. Any part of the state that was forgotten
makes the second run drift.

It runs over every ROM in `tests/suite.txt` (test ROMs, the project's
generated ROMs, ones with each sound chip, mapper IRQs, the FDS), with
the input scripts the suite already uses, and with N picked so the
state is taken mid-game, not at power-on.

Breaks, in a scratch copy, one at a time: each of the main parts left
out of the state (the APU, a sound chip, the PPU's scroll latch, the
mapper's IRQ counter, CHR RAM, the event scheduler, `code_owner`).
Each must make at least one ROM fail. A part that no ROM catches is
written down as a gap, not hidden.

## Steps

### 1. A state in memory: save and load in one run
- The inventory (above), written into this plan.
- `runtime/state.c`: `state_save()` and `state_load()` copy everything
  into and out of one block of memory, each part with a name and a
  size, so a missing or mis-sized part shows.
- The safe point: a flag from the key, then the work in
  `runtime_event()`.
- Keys: **Cmd+S** saves, **Cmd+L** loads (Ctrl on Windows). Cmd keys
  are already the window's (Cmd+F, Cmd+=), and plain keys stay the
  controllers'. On load the audio queue is emptied, so old sound
  doesn't play over the new.
- A short message drawn over the picture for a second ("STATE SAVED",
  "STATE LOADED", "NO STATE"), in the runtime's 5x7 font.
- Check: `--state-test` over the suite. Breaks as above.

**Where step 1 ended (2026-11-20).** `runtime/state.c` and `state.h`;
each file lists its own parts (`cpu_state`, `event_state`, `apu_state`,
`mapper_state`, `input_state`, `fds_state`; the cartridge and PPU in
`state.c`). Cmd+S / Cmd+L in the window (Ctrl on Windows: the window's
other shortcuts, Cmd+F and Cmd+=, moved to Ctrl there too, as the
Windows key belongs to Windows); the message is drawn top left for a
second, in the window only. `make test-states` (tests/check_states.py)
runs `--state-test` over the 240 games in the suite (NSFs left out),
saving half a frame after frame N (a third of the suite's frame count,
at most 600), so mid-picture, and comparing 120 frames: picture, RAM,
sound, and how many instructions ran translated and interpreted. All
240 pass. A state is 174 KB to 338 KB (the most: FDS and MMC5).

Breaks, each in a scratch copy, counting only "differs after loading"
failures:

| left out or broken | ROMs that caught it |
| --- | --- |
| the APU | 239 |
| a sound chip (VRC6) | 2 |
| the PPU's scroll latch (`t`, `x`) | 8 |
| CHR RAM | 3 |
| the event scheduler | 58 |
| saving at once from `frame_done`, mid-instruction | 239 |
| the samples waiting to be taken | 7 |
| the controllers' shift registers | 2 |
| the FDS disk's contents | 1 |
| the 2 KB RAM | 65 |
| the MMC3's IRQ counter | 0 at first; 1 with `mmc3_split.nes` (below) |
| `code_owner` | **0: a gap** |

The MMC3's counter at first went uncaught: the MMC3 test ROMs use the
IRQ only in short bursts, and no ROM in the suite ran an IRQ split every
frame, so a save never landed while the counter mattered (saving at
frames 5 to 80 didn't help either). So the suite gained
`tests/mmc3_split.nes` (tests/make_mmc3_split_test.py): a status bar's
worth of IRQs every frame, ten 24-line bands each scrolled 12 pixels
more, sliding a pixel a frame; a "frame" test in `make test-ppu`. With
it the break fails at the first frame after loading.

The gap that remains: `code_owner` only
decides whether code in RAM runs translated or interpreted; in every
FDS test the files are loaded before the save and unchanged until the
load, so the left-out copy is the same as the right one. It would take
a disk test that loads a new file between the save and the load. The
first try saved at vblank (where a key press lands); the scroll break
was caught by 3 ROMs then, 8 mid-frame, so the test saves mid-frame.

### 2. States on disk, with slots
- Four slots: **Cmd+1** to **Cmd+4** pick one (the message says which),
  saved as `<rom>.state1` to `.state4` next to the battery save, so it
  survives quitting.
- A small header: a magic word, a format version, the ROM's checksum.
  A state from another game or an older format is refused with a
  message, never loaded half-way.
- Pointers become "buffer + offset" on the way out and back on the way
  in.
- Check: the state test, but quitting between saving and loading (save
  in one run, load in a fresh one): the fingerprints must match.
- Breaks: a state from another ROM accepted, a pointer offset off by a
  bank, an old version number accepted.

**Where step 2 ended (2026-11-20).** A state file is a 40-byte header
(the magic word `NESRECOMP STATE`, format version 1, a checksum of the
game's file, the state's size) and then the state, which now holds no
addresses: `state_struct()` (state.c) saves a struct with its pointer
fields zeroed and, for each pointer into the console's memory, a
buffer number and an offset (`<name>.pointers`); the buffers are
`REGION_PRG`, `_CHR`, `_PRG_RAM`, `_NAMETABLES`, `_MMC5_RAM`,
`_TQROM_RAM`. Pointers that are the run's own (the board's functions,
its name, the cartridge's and the FDS's buffers) keep this run's value.
Such pointers are in `struct mapper` (banks, `ram6000`: data; 14
functions and the name: the run's), `struct cart`, `ppu.fetch_chr`,
`ee.mem`, `fds` and `drive`.

Cmd+1 to Cmd+4 pick a slot ("SLOT 2"); Cmd+S and Cmd+L save and load it,
as `<rom>.state1` to `.state4` beside the battery save (with
`--files-at P`, `P.state1`...; the app's folder). Messages: "SLOT 2
SAVED", "SLOT 2 LOADED", "SLOT 2 IS EMPTY", "SLOT 2 IS ANOTHER GAME'S",
"SLOT 2 IS AN OLDER FORMAT", "SLOT 2 ISN'T A STATE", "SLOT 2 NOT SAVED". A
file is written beside and then renamed, so a failed write never spoils
a good state. A refused file is checked whole (header, then every part)
before anything is copied in.

The check: `make test-states` now also runs every game twice more,
`--state-test N M --state-out F` (save to a file, note the
fingerprints in F.prints, quit) and `--state-test N M --state-in F` (a
fresh run loads F before the first instruction and must match). All
240 pass, in one run and in a new one. Then five files that must be
refused: another game's, version 0, a wrong magic word, one byte short,
one byte too many; all refused. States are 178 KB to 347 KB. `make
test-all` is as before (230 of 231, nestest exact), and the C is the
same (`make test-same-c`, `make test-recomp`).

The new-run test found a variable step 1 missed: `fds_sound_on`
(the FDS's $4023 sound switch), shared between files, which the `nm`
listing of each file's own variables didn't show. Listing the shared
ones too found no other.

Breaks, each in a scratch copy, counting only "differs after loading"
and "not refused" failures:

| broken | caught by |
| --- | --- |
| another game's state accepted | the refusal check |
| an older format number accepted | the refusal check |
| a file one byte too long accepted | the refusal check |
| a pointer's offset off by a bank (8 KB) | 62 ROMs |
| `mapper.ram6000` kept as this run's | 1 (mmc5_split) |
| the CHR banks 0-3 kept as this run's | 3 |
| the PRG banks kept as this run's | 8 |
| `fds_sound_on` left out | 1 (fds_demo) |
| the CHR banks 4-7 kept as this run's | **0: a gap** |
| `ppu.fetch_chr` kept as this run's | 0: can't matter |

`ppu.fetch_chr` is set again right before each use (ppu.c, the tile
fetch), so it holds nothing between instructions; it stays in the
state anyway. CHR slots 4-7 are a real gap: no game in the suite shows
tiles from those slots with banks other than the power-on ones when
the state is saved. A test ROM that switches the sprite banks (MMC3's
$8000 = 2-5) every frame would close it.

Tried in a live window (mmc3_split.nes): Cmd+S and Cmd+1 to Cmd+3 wrote
slots 1, 2 and 3 (178 KB each, header right). Slot files are in
.gitignore, like .sav and .missed.

### 3. Rewind
- While playing, a state is kept every frame in a ring of memory (first
  measure how big one state is; at an expected 20-40 KB, 10 seconds is
  12-24 MB). If it's large, keep only what changed from the frame
  before, or keep every second frame.
- Hold **Backspace** to step back one frame at a time, showing each
  picture, with the sound silent; let go and play carries on from
  there. (Backspace isn't one of the controllers' keys; the key is
  yours to choose.)
- Check: run a script, rewind 120 frames, and compare against the
  fingerprints the first time through that frame: they must match.
- Breaks: the ring stepping back one frame too many or too few, the
  oldest frame overwritten wrongly when the ring is full.

### 4. Fast-forward
- Hold **Tab** to run as fast as the computer allows (capped at 4x),
  drawing only some of the frames and skipping the sound.
- Check: a headless run with fast-forward held the whole time must give
  the same fingerprints as a normal run: going faster must never change
  the game.
- Break: a frame's input dropped during fast-forward.

### 5. The app, Windows, the README
- The app needs no change for the keys, but its help text lists them.
- The state test joins the Windows run (`.github/workflows/windows.yml`),
  with Ctrl instead of Cmd.
- The README: the keys, where states are kept, what a state holds.
- A release (2.1) is a separate decision, after this.

## Not in this plan
- A pause menu with buttons for all this (the next plan: it's where
  save, load, rewind and reset will live for people using a controller).
- Controller buttons for save, load and rewind (they come with the
  pause menu and button remapping).
- Pictures of each slot (thumbnails); they come with the game library.
- Movie recording of inputs (replays).

## Risks
- **Forgotten state.** A runtime this size has many small variables
  (about 65 at file level, plus every board's registers). One forgotten
  variable makes a loaded game go subtly wrong. The inventory and the
  state test over the whole suite are the guard; the breaks prove the
  test notices.
- **Hidden state in the C compiler's variables.** The generated
  `recomp_run` has four local variables: `ea`, `base` and `v` are
  scratch used only inside one instruction, so they hold nothing at an
  instruction boundary; `in_interp` says whether the interpreter is
  running, and is used only to note missed spots. Loading a
  state with it set wrongly only changes what gets noted in `.missed`,
  not how the game runs; step 1 checks this.
- **Saving mid-instruction.** Covered by doing the work only in
  `runtime_event()`; a break saves straight from `frame_done()` and must
  fail the state test.
- **Rewind's memory and speed.** Copying a state every frame costs
  time; step 3 measures it before choosing between full copies and
  changes only.
