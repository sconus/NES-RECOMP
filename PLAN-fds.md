# Plan: the Famicom Disk System

Goal: run Famicom Disk System programs (`.fds` disk images) and play
NSFs that use its sound chip. The FDS is a RAM adapter plus a disk
drive:
- 32 KB of PRG RAM at `$6000-$DFFF`, 8 KB of CHR RAM, and an 8 KB BIOS
  ROM at `$E000-$FFFF`;
- a timer IRQ, the disk drive's registers, and a wavetable sound
  channel.

Programs come on disk as files, which the BIOS loads into RAM.

`make test-all` must not get worse at any step; nestest stays exact.
Cartridge programs and NSFs that don't use FDS sound must recompile to
the same C as before.

## The big constraints

- **The BIOS.** Every disk program needs Nintendo's BIOS:
  - at power-on, it loads the boot files and jumps to the program;
  - it routes every NMI and IRQ to the program;
  - it has routines programs call (loading files, VRAM helpers,
    controllers).

  That BIOS is Nintendo's copyrighted code, so it can't be used here,
  and only free material is tested. So the project writes **its own
  BIOS**, from the nesdev wiki's description ("FDS BIOS"), at the same
  addresses:
  - the power-on state;
  - the boot load;
  - NMI/IRQ/reset dispatch;
  - the documented routines, as many as this stage covers.

  It does **not** contain the license text the real BIOS checks the
  disk against, so it skips that check. A program that depends on the
  real BIOS's exact code (timing loops, undocumented entry points)
  could behave differently; that's written down as it's found.
- **Code in RAM.** All of a disk program's code lives in RAM, and today
  the recompiler leaves anything below `$8000` to the interpreter. Step
  3 changes that for disk files, with a guard so that changed or
  reloaded code never runs stale.
- **Test material.** The collection has one FDS program, `fdsirqtests`
  (two images, the original and "V7 patched"). It tests the timer IRQ
  and calls no BIOS routines: it only needs the boot load, the
  NMI/IRQ dispatch and the reset vector. Everything else is checked by
  the project's own test images and NSFs, as for MMC5's split.

## What the wiki says (summary; details in each step)

- **Disk image** (`.fds`): an optional 16-byte header (`FDS\x1a`, the
  number of sides), then 65500 bytes per side. Each side holds:
  - block 1, the disk info, including the "boot read file code";
  - block 2, the file count;
  - then for each file, block 3 (its header: number, ID, name, load
    address, size, type 0 PRG / 1 CHR / 2 nametable) and block 4 (its
    data).

  Gaps and CRCs aren't stored.
- **Boot:** the BIOS loads every file whose ID is at most the boot
  code, then jumps to the program's reset vector at `$DFFC`.
- **Dispatch:**
  - NMI through `$0100` bits 7-6: the BIOS's own (00), or `$DFF6`,
    `$DFF8`, `$DFFA`;
  - IRQ through `$0101` bits 7-6: three BIOS disk modes, or `$DFFE`;
  - reset to `$DFFC` once `$0102`/`$0103` say the boot is done.
- **RAM adapter:**
  - a 16-bit timer IRQ: `$4020-$4022`, acknowledged three ways;
  - the master enable at `$4023` (disk and sound);
  - the drive: `$4024`, `$4025` (motor, read/write, CRC, IRQ, and the
    nametable arrangement, bit 3), `$4030-$4032`;
  - one byte crosses every 149 1/3 CPU cycles.
- **Sound** (`$4040-$4097`): a 64-step, 6-bit wavetable, a volume
  envelope, and a modulation unit with its own envelope and 32-entry
  table, all ticking every 16 CPU cycles. It passes through a low-pass
  filter near 2 kHz, and is about 2.4 times as loud as an APU square.
  The wiki contradicts itself about `$4083` bit 7; step 1 settles it
  from the references the page links.

## What exists

- Expansion sound for five chips, with tone ROMs and NSF versions
  checked by the `tones` kind.
- NSF support, which today warns that FDS sound is missing and plays
  the rest.
- Banked recompilation:
  - `dispatch` picks compiled code by bank and address, and the
    interpreter takes anything else (`.missed` feeds those spots back to
    the recompiler);
  - a store that could reach the mapper sets `mapper.bank_changed`, and
    compiled code then carries on through `dispatch`.

  Step 3 reuses this for code in RAM.
- Picture, text and result checks, scripted input, and test-image
  generators in Python.

## Steps

### 1. FDS sound
- `$4040-$408A` and the read-backs `$4090-$4097`: the wavetable, the
  volume envelope, the modulation unit and its envelope and table, the
  master volume, the envelope speed, the filter, the loudness. Gated by
  `$4023` bit 1 (NSFs act as if it is set).
- NSFs: drop the "not supported" warning. FDS NSFs also get RAM over
  `$6000-$DFFF` (checked against the wiki's NSF page first).
- Check: `make_fds_sound_test.py`, a tone NSF like the other chips'
  (pitch with and without modulation, envelopes, master volume), and a
  graded NSF for the register read-backs. Break each part.
- Done:
  - `runtime/fds.c` (new, for the whole FDS) has the sound channel,
    from the wiki's "FDS audio": the wavetable, both envelopes, the
    modulation table and counter, the pitch rounding, the master
    volume, the 2 kHz low-pass, and 2.4 APU squares at full scale. It
    keeps its own cycle count and catches up when the CPU reads or
    writes it. So the envelopes, the counter and the wave position read
    back right even when no sound is being made (my first version only
    moved them while recording, and the register test caught it). Read
    back: `$4040-$407F`, `$4090`, `$4091`, `$4092`, `$4097`.
  - Where the wiki's sources disagree (Disch's 2004 notes against the
    wiki and Loopy's later findings), I followed the wiki, as the
    comment at the top of `fds.c` lists:
    - `$4083` bit 7 resets the wave to position 0, and the envelopes
      run 4 times as fast;
    - `$4089` bit 7 holds the output's level;
    - the counter keeps changing the pitch while the table is stopped.
  - NSFs:
    - the "not supported" warning is gone;
    - an FDS NSF's `$8000-$DFFF` is writable RAM;
    - it may load from `$6000` (the part below `$8000` is copied into
      RAM before each song);
    - when bank-switched, `$5FF6`/`$5FF7` copy 4 KB banks into
      `$6000`/`$7000`, starting from header bytes `$76`/`$77`.

    `recomp.py` accepts such a load and leaves code below `$8000` to
    the interpreter.
  - Four NSFs, all passing:
    - `nsf_fds.nsf`, 10 notes for the `tones` check: the square at
      volume 32, 2/3 master, volume 16, volume 40 heard as 32, a
      triangle, and four modulation settings for the pitch and its
      rounding;
    - `fds_sound.nsf`, 17 checks of the registers, envelopes and
      modulation table through `$6000`;
    - `fds_nsf_low.nsf`, a load at `$7000` with a routine there called
      from `$8000`, and `$9000`/`$DFFF` writable;
    - `fds_nsf_banks.nsf`, `$5FF6`/`$5FF7`.
  - Breaks: 26 tried, all caught.
    - Three weren't caught at first, because the test couldn't tell
      right from wrong. The tests were strengthened:
      - an unsigned counter gives the same pitch at -16 by coincidence,
        so a note at -3 was added;
      - stopping the table was checked with nothing to stop;
      - the wave reset was checked with the wave already at 0.
    - My break of the wave reset at first removed only one of the two
      places that do it.
  - Not checked: when a new volume is first heard (at wave position 0),
    `$4089` bit 7 holding the level, and the sound while `$4083` bit 7
    is set. They don't change the pitch or loudness of a held note.
  - Known limit until step 3: code the recompiler translated from an
    FDS NSF's `$8000-$DFFF` doesn't see writes there. Self-modifying
    FDS NSFs would run stale code, so step 3's guard should cover them
    too.
  - The README still says FDS sound isn't supported; step 6 updates it.
  - 210 of 211 (test28 as always); nestest exact; all 319 earlier
    files give the same C.

### 2. Disk images, the project's BIOS, the timer IRQ
- The runtime reads `.fds`, with or without the header, any number of
  sides. Blocks that don't follow the standard layout are refused, with
  a message.
- The FDS's memory: 32 KB of PRG RAM, 8 KB of CHR RAM, `$4025` bit 3 for
  the nametable arrangement, and the BIOS at `$E000-$FFFF`.
- The project's BIOS: `tools/make_fds_bios.py`, written in the same
  little assembler as the test ROMs, produces `runtime/fds_bios.h`. The
  runtime runs it, and `recomp.py` compiles it like ROM. It does:
  - the power-on state the wiki lists (`$4023` = `$83`, the `$F9-$FF`
    register copies, `$0100-$0103`);
  - the boot load. A private register asks the runtime to copy the
    boot files: PRG files through the CPU bus (so a file loaded to
    `$2000` writes PPUCTRL, as `fdsirqtests` relies on), CHR and
    nametable files through the PPU;
  - the jump to `$DFFC`;
  - the NMI, IRQ and reset dispatch.
- The timer IRQ (`$4020-$4023`, `$4030`), to the cycle.
- At this step disk code runs in the interpreter.
- Check:
  - `fdsirqtests` (both images), graded however it reports (to be read
    from its screen);
  - `make_fds_test.py`: one image whose boot load and dispatch report
    through the screen or `$6000`-style RAM. It covers:
    - which files the boot code picks;
    - each file type;
    - the `$2000` trick;
    - the three NMI vectors and the IRQ vector;
    - the nametable arrangement;
    - the power-on values.
  - Break each part.

### 3. Recompiling disk programs
- `recomp.py` reads `.fds` too. Each PRG file is placed at its load
  address as a "bank" of its own, and tracing starts from the vectors at
  `$DFF6-$DFFF` that the boot files write, and from the project's BIOS.
- The guard: the runtime remembers, byte by byte over `$6000-$DFFF`,
  which file's bytes are there. Loading a file sets this; a CPU write
  that changes a byte clears it. `dispatch` runs compiled code only
  where the bytes are still the file's, and otherwise the interpreter
  runs them. A write that changes a byte compiled code is running from
  sets `bank_changed`, so self-modifying code leaves compiled code at
  once.
- Check:
  - the step 2 tests give the same results compiled;
  - a count of instructions run compiled and run interpreted shows
    the code really is compiled;
  - a test image that rewrites its own code (an operand and a whole
    routine), and one that loads a second file over the first.
  - Break the guard.

### 4. The BIOS's file routines and disk sides
- The documented file routines (LoadFiles, AppendFile, WriteFile,
  CheckFileCount, AdjustFileCount, SetFileCount, GetDiskInfo and the
  helpers they use), through the same private register: the runtime
  does the file work against the disk image, instantly.
  - Disk ID checks and their error codes, as the wiki lists them.
  - Writes go to `<image>.sav` beside the image, which is left alone.
- Changing sides: a key, and a `disk` command for input scripts. Eject,
  then insert side n.
- Check: a two-side test image that loads, appends and rewrites files,
  checks error codes, and asks for side B. Break each part.

### 5. The disk drive itself
- `$4024-$4026`, `$4030-$4033` byte by byte. Each byte crosses every
  149 1/3 cycles, with:
  - motor, scan and ready;
  - read and write mode;
  - the gaps and the CRC (rebuilt, since `.fds` drops them);
  - the transfer IRQ;
  - end of head.

  This is for programs that read the disk through the registers rather
  than through the BIOS.
- Check: a test image that reads its own blocks through the registers
  (polling and by IRQ), checks the CRC flag, and writes a block back.
  Break each part.

### 6. The BIOS's other routines, a demo, README
- The documented helpers: delays, VINTWait, the PPUMASK routines,
  the VRAM buffer and structures, VRAMFill, MemFill, SetScroll,
  JumpEngine, the controller routines, SpriteDMA, Random, CounterLogic.
  Each is written from the wiki's description and checked by a test
  image.
- `make_fds_demo.py`: something to try by hand that uses the disk, the
  timer IRQ and the sound.
- README: the FDS section, the BIOS and what it leaves out, the status
  list, where the stage ended.

## Not in this stage
- Nintendo's BIOS, or an option to use one: it can't be tested here.
  Programs that need it exactly (copy protection, undocumented BIOS
  entry points, the license screen) may not run.
- Disks with non-standard layouts, the QD format, the DRAM refresh
  watchdog IRQ (the wiki notes it is rarely used), the external
  connector beyond reading back `$4026`, the Famicom keyboard
  (ReadKeyboard).
- Commercial disk games: not used, as always.

## Risks
- **Step 3 is the hard part.** Code in RAM can change at any moment,
  and getting the guard wrong runs stale code silently. The guard
  checks bytes, not pages, and has its own break tests. Where in doubt,
  the interpreter runs the code.
- **The project's BIOS differs from Nintendo's** in timing and in
  anything undocumented. The boot load is instant instead of taking
  seconds of disk time. A program that measures the boot, or calls an
  undocumented entry point, would show it.
- **Little free test material:** one FDS program in the collection.
  Most checks are the project's own, so they test the wiki as I read
  it, like the MMC5 split.
- **The size of the stage:** six steps. Steps 4-6 can be trimmed or
  reordered after step 3 if the BIOS routines turn out to matter more
  than the drive.
