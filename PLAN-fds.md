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

- Done:
  - `runtime/fds.c` reads `.fds` images (with or without the header,
    any number of sides). A side that doesn't start with the standard
    disk info and file count blocks is refused. `--info` lists each
    side's files.
  - The memory: 32 KB of RAM at `$6000-$DFFF`, the BIOS at `$E000`,
    8 KB of CHR RAM.
  - The registers:
    - the timer IRQ (`$4020-$4023`, `$4030`), to the cycle;
    - `$4023` disk and sound enables;
    - `$4025` bit 3 mirroring (0 vertical, 1 horizontal; `$06` while
      disk I/O is off);
    - `$4032` and `$4033` as fixed values for now.
  - `tools/make_fds_bios.py` writes `runtime/fds_bios.h`, the
    project's BIOS:
    - the power-on state;
    - a soft reset that goes straight to `$DFFC`;
    - the boot load (through `$4028`, which the runtime answers);
    - the NMI and IRQ dispatch, and the handlers at `$E19D`, `$E1CE`,
      `$E1D9`, `$E1EF`.

    Every unused byte is `$02`, which stops the CPU with a message
    naming the address, so a missing BIOS routine shows at once.
  - Instead of the license check, the BIOS waits a little over a frame
    (a delay loop) after loading. A boot file that turns on NMIs then
    gets its NMI first, which is how programs skip the license check on
    the real console. My first version polled `$2002` for vblank, which
    can swallow that very NMI, so I changed it before testing.
  - `recomp.py` reads `.fds` too. It translates the BIOS (from
    `runtime/fds_bios.h`) and leaves `$6000-$DFFF` to the interpreter.
    The runtime doesn't save RAM spots there to `.missed`.
  - `fdsirqtests`: both images, all 21 checks marked O, on the first
    run. A new suite kind, `marks N`, grades a screen of O/X lines.
    - The two images differ in two bytes: the original reads the BIOS's
      copy of `$4025` at `$FA` where the patched one loads `$2E`. Its
      results don't depend on it.
    - It starts through its NMI during the boot, then jumps through
      `$FFFC` itself, so it also uses the soft reset path.
  - `make_fds_test.py` writes `fds_boot.fds`: 15 checks through `$6000`,
    including a second part after a reset (status `$81`). It also has
    `fds_image()` for later tests. It covers:
    - which files the boot code picks;
    - where each file type goes, and PRG files below `$2000`;
    - the NMI that skips the license check;
    - every value the BIOS leaves;
    - both mirrorings and `$4030` bit 3;
    - the four NMI and two IRQ dispatch paths;
    - the timer's reload, and `$4020` writes not acknowledging;
    - the soft reset not reloading files.
  - Breaks, 25 tried:
    - 24 caught, 5 of them only after fixes:
      - checks 14 and 15 were added for two breaks nothing caught;
      - check 14 was made two-sided;
      - one break edit didn't compile, and my break script took the
        runner's "build failed" for "not caught". The script now
        reports build failures.
    - One isn't caught, and is left as a written-down choice: the timer
      firing one cycle sooner. The wiki's wording allows it, and
      `fdsirqtests` passes either way. Firing a cycle later fails it.
  - Not yet: the disk drive itself (`$4024`, `$4031`, the transfer
    IRQ), the BIOS's routines, disk sides.
  - 213 of 214 (test28 as always); nestest exact; all 319 earlier
    files give the same C.

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

- Done:
  - The guard, `code_owner` in `rt.h`: one tag per byte of
    `$6000-$DFFF`.
    - An FDS file's tag is its number. The recompiler and the runtime
      both count every file of every side in disk order, starting at 4
      (`FDS_FIRST_TAG`); bank 3 is the BIOS. Files past number 255 aren't
      translated.
    - The boot load tags each PRG file's bytes.
    - Any write that changes a byte clears its tag. Writes reach RAM
      three ways (`$6000-$7FFF`, the FDS's `$8000-$DFFF`, an FDS NSF's
      `$8000-$DFFF`), and all three go through one helper,
      `code_ram_write`.
  - It works differently from the plan, and it is simpler and safer:
    every translated instruction in RAM checks its own bytes' tags
    first. If one doesn't match, the interpreter runs that instruction.
    - The plan's `bank_changed` exit only covered a write made by code
      running at that moment.
    - With the check at each instruction, a direct jump inside compiled
      code to a changed spot is caught too, wherever the change came
      from.
  - `dispatch` keys RAM code by the tag at `pc`. Spots the interpreter
    ran are saved to `.missed` by file ("05:8020"), so the feedback
    loop works for disk programs as it does for cartridges.
  - `recomp.py`:
    - reads every file of every side;
    - traces from the BIOS and from the vectors that the boot files
      leave at `$DFF6-$DFFF`;
    - keeps a jump direct only while it stays in the same file.
  - FDS NSFs: `$8000-$DFFF` is RAM there too, so their code gets the
    same check, with tag 1. A bank-switched one is tagged again each
    time a bank is copied in. The part below `$8000` is still
    interpreted.
  - Counting: the program option `--ram-stats` prints how many RAM
    instructions ran translated and how many interpreted. The runner
    option `--translated=P` fails a test unless at least P% ran
    translated. All six FDS tests here use 99%.
    - `fdsirqtests`: 5,903,690 translated, 0 interpreted.
  - `make_fds_code_test.py` writes three tests:
    - `fds_code.fds`, 10 checks:
      - a boot file loaded over part of another, reached by a direct
        jump inside the old file and by a call;
      - rewritten operands, both through `$6000-$7FFF` and through
        `$8000-$DFFF`;
      - code that rewrites the next instruction while it runs;
      - JMP targets rewritten, one by the low byte and another by the
        high byte;
      - a routine copied over with new opcodes;
      - writing the value already there;
      - a change and then a change back;
      - an opcode changed, reached through `JMP ($0010)`.

      9,510 of its instructions in RAM ran translated; the 13 changed
      ones ran interpreted.
    - `fds_nsf_code.nsf` and `fds_nsf_code_banks.nsf`: the same kinds
      of rewrite in FDS NSFs, plus a bank copied in again holding its
      original code.
  - A file loaded while the program runs (not during the boot) is left
    for step 4, which adds the BIOS's file routines. The boot overlap
    already covers a file replacing another's bytes.
  - Breaks, 19 tried:
    - 18 caught. One needed a better test first: "the guard skips an
      instruction's third byte" passed until the high-byte rewrite got
      a JMP of its own. The first version rewrote a JMP whose low byte
      had already sent it to the interpreter.
    - One isn't caught, and doesn't need to be: the recompiler
      skipping the boot vectors only costs speed, because the `.missed`
      feedback finds those spots anyway.
  - A slip in the test itself: a branch distance computed before the
    DEX byte was emitted (the same slip as twice before). It showed as
    check 7 failing in the interpreter too.
  - 216 of 217 (test28 as always); nestest exact; all 319 earlier
    files give the same C. Only the four FDS NSFs from step 1 change,
    by gaining the check.

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

- Done:
  - The BIOS has the eight file routines at the wiki's addresses:
    - `$E1F8` LoadFiles;
    - `$E237` AppendFile, which is `LDA #$FF` followed by WriteFile;
    - `$E239` WriteFile;
    - `$E2B7` CheckFileCount;
    - `$E2BB` AdjustFileCount;
    - `$E301` SetFileCount1;
    - `$E305` SetFileCount;
    - `$E32A` GetDiskInfo.

    Each one stores A in `$4029` and makes its request through `$4028`.
    The runtime then:
    - does the work against the disk image, at once;
    - moves the return address past the pointers that follow the JSR;
    - leaves the error number in `$4029` and LoadFiles' count in
      `$402A`. The routine loads them back, so Z is set when there was
      no error.
  - The wiki's rules, in `runtime/fds.c`:
    - **Disk ID:** 10 bytes, checked against disk info `$0F-$18`, with
      error numbers `$04-$10`. `$FF` in the expected ID skips that byte;
      I read the wildcard as applying to each byte, which the wiki
      leaves open for the 4-byte name.
    - **No disk:** error `$01`. A wrong `*NINTENDO-HVC*` is error `$21`.
    - **LoadFiles:** a list of up to 20 IDs ending in `$FF` (only `$FF`
      means the boot files), loaded in disk order. Y counts dummy loads
      too.
    - **Dummy loads:** a PRG file below `$2000` (except to `$0200-$07FF`
      and `$1200-$17FF`), or any file running past `$FFFF`. The boot
      load now goes through the same code.
  - **WriteFile:** the file goes in as file A (`$FF` appends), and the
    count becomes A+1, hiding any files after it. The wiki only says
    the count becomes "the A value". A+1 is what keeps the written file
    visible, and it fits AppendFile adding one file. Its data comes
    from RAM or VRAM, as the header says. Errors:
    - `$24`: A is past the last file;
    - `$29`: the side is full.
  - **The count routines:** CheckFileCount and AdjustFileCount give
    error `$31` when A is more than the count.
  - **GetDiskInfo:** the disk ID, the file count, each file's ID and
    name, then the size. The size is every file's size plus 261 per
    file, high byte first.
  - **Not here:** the lower-level routines (CheckDiskHeader,
    FileMatchTest, ...). They read the disk byte by byte, so they wait
    for step 5. Calling one stops with the usual message.
  - **Sides:** `disk=eject` and `disk=N` in input scripts. In the
    window, 0 ejects and 1-9 eject and then put in that side half a
    second later, so the program sees the disk come out. `$4032` shows
    a missing disk. The keys aren't tried in the window yet.
  - **Saving:** a disk the program wrote to goes to `<image>.sav` (the
    whole disk) when it stops. That file is loaded instead the next
    time, and the image itself is left alone. Checked by hand: the
    image's checksum didn't change, the `.sav` held the written file,
    and a second run started from it and passed. The suite runs with
    `--no-save`.
  - **The guard and written files:** a file keeps its translation only
    while it matches the image file's version of it, byte for byte.
    A file the program rewrote (or a `.sav` changed) gets tag 0.
  - **Recompiler:** it knows how many pointers follow a JSR to each
    file routine, and traces past them. Before this, it read the
    pointers as code and stopped there.
  - **`make_fds_files_test.py`** writes `fds_files.fds`, two sides with
    18 checks:
    - LoadFiles: lists, the boot list, Y, dummy loads, CHR files;
    - code loaded over code while the program runs (step 3's open
      item);
    - each disk ID error and the wildcard;
    - GetDiskInfo;
    - AppendFile from RAM and from VRAM;
    - WriteFile hiding later files;
    - the three count routines;
    - error `$01` with the disk out;
    - side B by its ID;
    - a WriteFile over side B's code, so the new code runs and not the
      old translation.

    Its input script takes the disk out at frame 120 and puts in side
    B at 150. 1,458,564 instructions ran translated, 0 interpreted.
  - **Slips found by testing:**
    - Y for IDs 8 and 9 is 3, not 2: three files match.
    - While waiting for the side change, the test reported `$81`,
      which makes the runtime press reset. It stays at `$80` now.
  - **Breaks, 27 tried:**
    - 26 caught. One only after a fix: the check for a file wrapping
      past `$FFFF` looked at `$FFF0`, which is ROM. It looks at zero
      page now, where the bytes would land.
    - One isn't caught, and doesn't need to be: the recompiler not
      skipping the pointers only costs speed, because the `.missed`
      feedback finds the code after them.
  - 217 of 218 (test28 as always); nestest exact; all 319 earlier
    files give the same C.

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

- Done:
  - **The stream.** The drive sees a side as a stream of bytes built
    from the image:
    - a leading gap of 28300 bits (3537 zero bytes);
    - then each block as the gap's end mark `$80`, the block, its CRC
      (low byte first), and a gap of 976 bits (122 bytes);
    - then the side's remaining room, as gap.

    The CRC is CRC-16/KERMIT over the mark and the block, as the wiki
    says. One byte passes every 149⅓ cycles, kept exact in PPU dots
    (448).
  - **The registers:**
    - `$4025`: bit 0 = 0 is the transfer reset (the head goes back to
      the start); the head moves while bits 1-0 are `01`; bit 2 picks
      read or write; bit 4 is for the CRC; bits 5 and 6 must both be
      set for a transfer; bit 7 is the IRQ.
    - `$4030` gives the transfer flag (bit 7), the CRC error (bit 4) and
      end of head (bit 6). Reading it acknowledges only the timer.
    - `$4031` (read) and `$4024` (write) clear the flag.
    - `$4032` bit 1 (not ready) is 0 only while the head moves.
    - The transfer IRQ has its own source bit, `IRQ_DISK`, so the timer
      and the drive don't clear each other's IRQ.
  - **Reading:** with bit 6 set, the first nonzero byte ends the gap.
    That byte is the mark, and it isn't handed over. Each byte after it
    goes to `$4031` and raises the flag. With bit 4 set, `$4030` bit 4
    says whether the CRC so far came out wrong.
  - **Writing:** with bit 6 set, each byte time writes `$4024`. With
    bit 4 also set, it writes the CRC (two bytes) and then zeros. With
    bit 6 clear, it writes zeros, which is how gaps are written.
  - **Writes reach the image:** what the drive wrote goes back into the
    image (blocks only, without the gaps and CRCs) when the head stops
    or resets, before a BIOS file routine, and at exit. A side changed
    in the image (by a file routine or a `.sav`) is rebuilt into a
    stream the next time the motor starts.
  - **Choices where the wiki is open,** all written in `runtime/fds.c`:
    - bit 0 as a transfer reset;
    - finding a block by the first nonzero byte;
    - the CRC low byte first;
    - no spin-up time;
    - the head stopping at the end of the side until a transfer reset;
    - the transfer flag not cleared by `$4025` writes. The wiki only
      names `$4031` and `$4024`. So bytes keep coming after a block's
      CRC while bit 6 is on, and a program has to read `$4031` once
      before it waits for the next block.
  - **`make_fds_drive_test.py`** writes `fds_drive.fds`, 12 checks:
    - the ready flag;
    - the leading gap's length, timed;
    - the byte time;
    - blocks 1 and 2, read by polling;
    - `$4030` not clearing the transfer flag, and `$4031` clearing it;
    - the CRC checked a byte early, flagged bad;
    - a data block read by IRQ (through the BIOS's `$0101` = `$C0`);
    - a data block rewritten through `$4024`: the gap, the mark, the
      block, the CRC, and a gap over the old block. LoadFiles then
      loads the new bytes, and the drive reads them back with a good
      CRC;
    - end of head, not ready, and a transfer reset back to block 1;
    - no bytes with bit 5 clear.

    3.9 million instructions ran translated, 0 interpreted.
  - **The leftover transfer flag,** found while testing: the test read
    a stale byte as a block's first. The behaviour stays, as the wiki
    describes it; the test now clears the flag first, as noted above.
  - **Breaks, 23 tried, all caught.** Two only after fixes:
    - "bit 5 not needed" needed check 12;
    - "bit 6 off doesn't wait for a mark" had to break both places
      that reset the wait.
  - **Not covered by any test here:** the BIOS's own disk IRQ modes
    (`$0101` = `$00`, `$40`). They still only acknowledge, since the
    BIOS's file routines don't use the drive.
  - 218 of 219 (test28 as always); nestest exact; all 319 earlier
    files give the same C.

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

- Done:
  - **The BIOS's other routines,** at the wiki's addresses: a JMP at
    each, the code after the reset code. Written in 6502 from the
    wiki's descriptions; each is listed with what it does in
    `tools/make_fds_bios.py`:
    - Delay131 and Delayms;
    - the six PPUMASK routines;
    - VINTWait, with its NMI handler at `$E19D`;
    - VRAMStructWrite (copy, fill, add 32, length 0 = 64,
      sub-structures through `$4C`/`$60`);
    - FetchDirectPtr;
    - WriteVRAMBuffer, PrepareVRAMString, PrepareVRAMStrings;
    - Pixel2NamConv and Nam2PixelConv;
    - Random, SpriteDMA, CounterLogic;
    - ReadPads, OrPads and the five Down/Verify/Exp reading routines;
    - VRAMFill, MemFill, SetScroll, JumpEngine.

    The IRQ handler for `$0101` = `$80` now calls Delay131, as its name
    says ("acknowledge and delay").
  - **Choices where the wiki is open,** written down there too:
    - what Delayms' 1790·Y+5 counts (the routine and its RTS, not the
      JSR);
    - Random's feedback bit (bit 1 of the first two bytes XORed);
    - CounterLogic's ends read as "A, Y";
    - WriteVRAMBuffer's length byte taken as a plain count;
    - the buffer emptied afterwards (`$0301` = 0, `$0302` = `$FF`);
    - MemFill including its last page.
  - **Left out:**
    - the VRAM read buffer routines (the wiki calls their use
      speculation);
    - ReadKeyboard (the keyboard isn't in this stage);
    - LoadTileset and UploadObject (not in the plan's list; their
      descriptions leave too much open).
  - **A correction to step 2.** The wiki says the `$0100` = `00` NMI
    handler is VINTWait's own. It drops the interrupt and returns to
    VINTWait's caller with I still set. Step 2's version returned with
    RTI, and `fds_boot`'s check 10 tested that. Both now follow the
    wiki: the check calls VINTWait and checks A, `$FF`, `$0100`, I, and
    that the program's NMI wasn't called.
  - **`recomp.py`:** VRAMStructWrite and the two PrepareVRAMString
    routines also take a pointer after the JSR. JumpEngine never
    returns there, so tracing stops after a JSR to it.
  - **`make_fds_helpers_test.py`** writes `fds_helpers.fds`, 16 checks,
    run with `--famicom-4p` so the expansion port has pads 3 and 4:
    - Delay131 and Delayms timed with the FDS timer, exact to the
      cycle;
    - every other routine above.
  - **Slips found by testing:**
    - VRAMStructWrite's add-32 branch skipped 3 bytes instead of 4.
    - The demo: a branch length, the A/B request bits swapped, the
      message toggle backwards. All three were caught by reading the
      code before the first run; the screenshots then showed the split
      a row too high.
  - **Breaks, 35 tried:**
    - 34 caught. Five only after fixes:
      - the delay checks had a ±5-cycle window, and are exact now;
      - the expansion pads were added for ReadOrDownPads and
        ReadDownExpPads;
      - one break was written in code that never ran, and was redone.
    - One isn't caught, and doesn't need to be: the recompiler not
      skipping these pointers only costs speed.
  - **`make_fds_demo.py`** writes `fds_demo.fds`:
    - LoadFiles plus VRAMStructWrite for the message files;
    - WriteFile for a count (kept in the `.sav`);
    - a timer-IRQ split with a scrolling band;
    - a tune on the FDS wavetable;
    - VINTWait, the PPUMASK routines, ReadDownPads, SetScroll.

    Its script loads, saves twice and stops the music, as a picture
    check. The sound was checked too: it plays, and goes quiet after
    Select.

    Tried in a window afterwards. The saved count survived between runs
    (19, then 28 in the `.sav`). One glitch was found, in the demo
    itself: after each load or save, the picture jumped up for a frame.
    The demo turned rendering back on mid-frame, and its VRAM writes had
    moved the PPU's address, which the PPU then drew the rest of that
    frame from. A real console would do the same. The demo now waits
    for vblank (VINTWait) and calls SetScroll before turning rendering
    on. Screenshots of the frames around each disk action now show one
    blank frame, then the picture back in place.
  - **README:**
    - a Famicom Disk System section: the BIOS and what it leaves out,
      the drive, code in RAM, sides and saving, keys;
    - the NSF section (FDS sound supported, `$6000` loads);
    - the options and input script docs;
    - the test generators;
    - the status list.
  - **A linker warning** about `code_owner`'s alignment went away by
    initializing it.
  - 219 of 220 (test28 as always), 32 pictures, 8 sounds; nestest
    exact; all 319 earlier files give the same C.

## Where the stage ended

Disk images run on the project's own BIOS, with:
- the boot and dispatch;
- the file routines and the other documented routines;
- the drive byte by byte;
- the timer IRQ and the sound channel (in NSFs too).

Disk code is translated per file, and a check on every instruction
keeps changed code from running stale. The only disk program in the
free collection, `fdsirqtests`, passes on both images; everything else
is checked by the project's own disks and was confirmed by deliberate
breaks. What would show a gap: a program that relies on Nintendo's
exact BIOS code or timing, an undocumented entry point, or one of the
routines left out above.

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
