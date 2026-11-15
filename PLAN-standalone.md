# Plan: a NES RECOMP you can share, record with, and look inside

Goal: three things, in this order.
1. **A standalone Mac app.** You can give `NES RECOMP.app` to someone,
   and it works on their Mac with only Apple's free C compiler: no
   project folder, no Python, no Homebrew.
2. **Recording.** A key in the game's window saves picture and sound
   together in one movie file, ready for a video editor.
3. **"Under the hood."** The app shows how much of a game was
   translated to C and how much still runs in the interpreter, how that
   shrinks as you play, and a piece of the game as the original 6502
   instructions next to the C they became.

The release (a zip to share) comes last, so the shared app has all
three.

Every step keeps what holds today:
- `make test-all` doesn't get worse: the suite 219 of 220 (test28 as
  always), nestest exact, the app checks passing;
- all 319 earlier files under `tests/` recompile to the same C;
- only free test ROMs and the project's own are used;
- each check is confirmed with breaks made in scratchpad copies, and
  only real failures count (not a crash, not a failed build).

## What it needs today, and why that stops it being shared

- **SDL2 from Homebrew.** The app and every game it builds link
  `/opt/homebrew/lib/libSDL2.dylib`. On this Mac that is
  `sdl2-compat`, a stand-in that loads a second library, SDL3, also
  from Homebrew. It is built for Apple Silicon only and for macOS 15
  and later.
- **Python 3,** for `recomp.py`.
- **The project folder,** baked in as `PROJECT_ROOT` by the
  `Makefile`: the app finds `recomp.py` and `runtime/` there, and
  writes its builds to `build/`.
- **Apple's C compiler** (the Command Line Tools). This one stays: the
  app turns each game into C and compiles it on your Mac. It is free
  and Apple's own, so asking for it is fair. But today, without it, a
  build just fails with a confusing message.

## Choices

- **SDL2 inside the app.** Two ways:
  - **(a) Copy Homebrew's two libraries in** (sdl2-compat and SDL3).
    It's quick, but the app would only run on Apple Silicon Macs with
    macOS 15 or later, like the libraries.
  - **(b) Build SDL2 ourselves from its official source release**
    (SDL 2.32, zlib license, about 7 MB to download, and it builds
    with only Apple's compiler). It's one library, for both Intel and
    Apple Silicon, from macOS 11 on.

  I recommend (b): you'd be giving the app to people whose Macs you
  don't know. It needs your OK to download the source, asked at step
  1. The app itself is then built for both kinds of Mac too.
- **The games link the app's SDL2.** A game the app builds is its own
  program, made on your Mac. Each build gets a copy of the library next
  to the games, so a game still runs after the app is moved or
  updated.
- **The recompiler, in C,** as a small program inside the bundle
  (`Contents/MacOS/nesrecomp-recomp`). The app runs it as it runs
  `recomp.py` today: same options, same messages, same log. It runs as
  a separate program, not inside the app, so a recompiler crash can't
  take the window down, and the build code hardly changes.
  - **The check that matters:** for all 319 files, the C version writes
    exactly the same C as `recomp.py`, byte for byte, and prints the
    same lines.
  - **`recomp.py` stays** in the project for this stage, as the
    reference the C version is checked against. After that it's your
    call whether to keep both (any later change to the recompiler would
    then be made twice) or retire the Python one.
  - The project's own test scripts and ROM generators stay in Python.
    They're for working on the project, and the app doesn't need them.
- **Where the app keeps its things:** `~/Library/Application
  Support/NES RECOMP/`: the built games, the runtime's compiled files,
  logs, the window size, and the teaching history.
  - `<rom>.missed` and `<rom>.sav` stay beside the ROM, as now, so
    `make run` and the app share them.
  - If the ROM's folder can't be written (a locked disk, say), they go
    to the app's folder instead.
- **Recording with Apple's AVFoundation, not ffmpeg.**
  - AVFoundation is part of every Mac and writes `.mov` files that
    QuickTime, iMovie, Final Cut, DaVinci Resolve and Premiere all open.
  - ffmpeg isn't on this Mac. Shipping it would make the app much
    bigger and bring its own licensing questions, and asking people to
    install it undoes part 1.
  - The cost: one runtime file in Objective-C (Apple's compiler
    handles it), so this part is Mac-only. That's fine, since the app
    is too.
  - The Mac's own screen recorder (Cmd+Shift+5) doesn't record a
    game's sound without extra software, and it records the window's
    scaled, blurred pixels. That's why recording belongs in the game.
- **The movie runs on game time:** frame N is at N / 60.0988 seconds
  (the NES's rate), and the sound by its sample count at 48,000 a
  second. Picture and sound come from the same emulated time, so they
  stay in sync even if the Mac stutters while recording.
- **The 6502 next to the C comes from a side file.** Today the C has no
  trace of the original instructions, only their addresses. The C
  recompiler gets a `--listing FILE` option that writes, for each
  instruction, its address, bytes, its 6502 text (`LDA $2002`) and
  the lines of the `.c` it became. The `.c` itself doesn't change, and
  the 319-file check proves it.

## Steps

### 1. SDL2 inside the app
- Build SDL2 2.32 from its source release (choice (b)), for Intel and
  Apple Silicon, macOS 11 and later, into `build/sdl2/`. A script,
  `tools/build_sdl2.sh`, does this, so it can be done again.
- `make app` and `make app-bundle` use it. The bundle gets
  `Contents/Frameworks/libSDL2.dylib`, the SDL headers (the games need
  them to compile), and SDL's license text.
- The app is built for both kinds of Mac.
- Each game build copies the library next to the games, and the games
  find it there.
- For now the app still uses the project folder for `recomp.py` and
  `runtime/`.
- `make run`, `make test` and the suite keep Homebrew's SDL2 for now,
  so nothing else moves at once. Switching them over is a one-line
  change, for later.
- Check:
  - `otool -L` on the app, the library and a built game: no
    `/opt/homebrew` anywhere, only the bundled copy and Apple's own
    libraries;
  - the app and the library each hold both architectures (`lipo`), and
    the minimum macOS is 11;
  - the app, run with reading `/opt/homebrew` forbidden (macOS's
    `sandbox-exec`), opens, builds a free test ROM and plays it, and
    the ROM's own test passes;
  - `make test-app` and `make test-app-bundle` pass.
  - Breaks: the game linked to Homebrew's library, the library left
    out of the bundle, the headers left out, the app built for one kind
    of Mac only.

- Done:
  - **SDL2 2.32.10,** downloaded with your OK from SDL's GitHub
    releases (`SDL2-2.32.10.tar.gz`, 7,630,262 bytes, the size the
    release lists) into `build/sdl2/`. `tools/build_sdl2.sh` (`make
    sdl2`) builds it with only Apple's compiler, in about 40 seconds:
    - once for Apple Silicon and once for Intel, joined with `lipo`,
      macOS 11 and later;
    - no pkg-config, Homebrew or `/usr/local`, so nothing from this
      Mac's extras gets in. It needs only Apple's own libraries;
    - named `@rpath/libSDL2.dylib`, so each program finds it where its
      rpath says;
    - the headers and SDL's license (zlib) beside it.

    `make clean` now keeps `build/sdl2`, so the download isn't lost.
  - **The app** is built for both kinds of Mac, macOS 11 on, and loads
    SDL2 from `sdl2/lib` beside it, or from the bundle's
    `Contents/Frameworks`.
    - It finds its SDL2 from its own place, not from a path baked in.
    - `--sdl-info` says where that is.
  - **The bundle** gets `Frameworks/libSDL2.dylib`, and
    `Resources/sdl2/include` and `LICENSE.txt`.
  - **The games:**
    - they compile against the app's SDL headers;
    - before linking, the build copies the app's library to `lib/`
      beside the games (again only when its size or time differs), and
      the games find it there (`@executable_path/lib`);
    - the build record now holds the SDL headers' time, so games built
      with Homebrew's SDL2, or with an older one, are built again;
    - if the headers are missing, the build says "the app's SDL2 is
      missing".
  - `make run`, `make test` and the suite still use Homebrew's SDL2, as
    planned.
  - **`tests/check_standalone.py`** (`make test-standalone`), 25
    checks:
    - the library: both architectures, macOS 11, its name, only Apple's
      libraries, version 2.32.10;
    - the app: both architectures, macOS 11, SDL2 only through its
      rpath, both rpaths;
    - the bundle: the library (the same code), all 78 headers, the
      license, and no mention of `/opt/homebrew` but one. Until step 3,
      the app puts Homebrew's `bin` on PATH to find `python3`, and the
      check allows exactly those two strings;
    - with reading `/opt/homebrew` and `/usr/local` forbidden (first
      checked to really be forbidden): the bundle's app builds and plays
      a free test ROM, and its test passes. The game links only the
      bundled copy and loads it from `lib/`, and an old copy left there
      is replaced;
    - **as an Intel Mac would, under Rosetta,** also without Homebrew:
      the app builds an Intel game, and it passes;
    - a game still runs after the app that built it (a copy with
      spaces in its name) is deleted;
    - a newer SDL header rebuilds the game and all 15 runtime files;
    - headers missing: the message.
  - **Breaks, 14 tried, all caught,** after three fixes to the check:
    - "an old copy kept" wasn't caught at first: every check began with
      an empty build folder, so there was never an old copy to keep.
      The check now leaves a stale one there.
    - Four breaks first crashed the check instead of failing it, and
      two still did after a first fix: when the game, the library or
      the headers weren't there, it went on to open them. A crash
      doesn't count, so the check now looks first, and all six were run
      again.
    - The others: Homebrew's library or headers used for games, the
      library, headers or license left out of the bundle, the app for
      Apple Silicon only, no minimum macOS (it became 15.0), the
      bundle's rpath dropped, the game's rpath dropped, the game linked
      to the app's library instead of a copy, the record ignoring SDL's
      headers, missing headers not noticed, and the bundle using the
      build folder's SDL2.
  - Unchanged: `make test-all` (the suite 219 of 220, test28 as always;
    nestest exact; the 58 app checks), and `make test-app-bundle`'s 12. `recomp.py` isn't touched, so
    the 319 files' C can't change.

### 2a. The recompiler in C: reading the file
- `recomp/` holds the C version, in a few files the way `recomp.py`
  is laid out:
  - the opcode table and cycle maps;
  - the iNES and NES 2.0 headers;
  - the mappers and their banks;
  - NSF and FDS (the FDS BIOS read straight from
    `runtime/fds_bios.h`);
  - the tracer;
  - the C writer.
- This half covers reading: the file, its header, its banks, and where
  the code starts.
- For the check, both versions get a hidden `--dump-rom` option that
  prints everything they read.
- Check:
  - for all 319 files, the two dumps are the same;
  - the same error message for each kind of bad file (not a ROM, a
    short file, an unsupported mapper, NES 2.0 fields it refuses, a bad
    FDS side), from files the check makes.
  - Breaks: a mapper's bank size wrong, the trainer skipped wrongly,
    NES 2.0's size exponent misread, an FDS file's address off by one.

- Done:
  - **`recomp/rom.c` and `rom.h`:** recomp.py's `read_header`, `MAPPERS`
    and `class Rom` in C. Each part is named after the one it copies,
    and recomp.py's comments explain why each thing is done.
    - The FDS BIOS is built in from `runtime/fds_bios.h`; recomp.py
      reads it from that file each time it runs.
    - One trap: Python's `%` never gives a negative number, but C's
      does, and negative bank numbers ("the last bank" is -1) depend on
      it. The C version uses a Python-style one.
  - **`recomp/main.c`:**
    - the same options as recomp.py, including the abbreviations Python
      allows (`--ent`);
    - the entry points in the same order: the vectors, an NSF's init and
      play, a disk's boot files, `--entry`, `.missed` in both formats;
    - and `--dump-rom`.

    `make recomp` builds `build/nesrecomp-recomp`. Without `--dump-rom`
    it says translating comes in step 2b.
  - **recomp.py** gets the same hidden `--dump-rom`. It now gives a
    message instead of crashing (a Python traceback) on four kinds of
    file:
    - one too short for a header;
    - an NSF too short for its header;
    - a bank-switched NSF with no program;
    - a file it can't open.

    All 395 files under `tests/` give the same C as before (394
    recompile; one is deliberately not a ROM).
  - **`tests/check_recomp.py`** (`make test-recomp`), 64 checks:
    - all 394 readable files under `tests/`, read alone: the same dumps,
      line for line;
    - the 130 that have a `.missed` file, read with it: the same;
    - the one non-ROM: the same message;
    - nestest as `make test` reads it;
    - 37 files made by the check for what the collection lacks: a
      trainer, old dumps' junk, every NES 2.0 field, its exponent sizes
      (8 and 24 KB) and size MSB, a header claiming more than the file
      holds, 256 and 512 KB MMC1, MMC1 submapper 5, MMC5, VRC4, Action
      53, BNROM, MMC2, disks with and without a header, two sides, more
      than 252 files, files reaching past $6000-$DFFF, a short file
      count, a partial side, and NSFs at $8000, at $C123, too long, at
      $6000 (FDS sound), banked with an offset, and wrapping banks;
    - 16 files it refuses: the same message and exit status, and never a
      traceback;
    - entry points: `.missed` in both formats with spaces, blank lines,
      `0x` and banks past the last; two `.missed` files; `--entry`; a
      banked NSF; a disk image.
  - **Breaks, 22 tried, all caught,** after one fix to the check:
    - "the FDS tags stop one short" wasn't caught at first. In the made
      disk with many files, the file that gets tag 255 (the last
      translated) was empty, so it made no difference. It's now a real
      file, and so is the one after it, which must be left out.
    - Two made files didn't test what they meant to, because their
      sizes came out differently from what was intended. Both versions
      agreed on them, which is how it showed. Both were fixed before
      the breaks.
    - The others: MMC3's power-on banks, UxROM's fixed half, the
      trainer, NES 2.0's exponent and its fallback, old dumps' junk,
      `console_ext`, the 512 KB MMC1 rule, MMC1 submapper 5, C's `%`, a
      banked NSF's offset, an FDS NSF's floor, an FDS file's address,
      FDS boot files (`<` for `<=`, and from every side), a file of
      another type kept, `.missed` banks not wrapped, the old `.missed`
      format in bank 0, an NSF's play routine, entry points not
      filtered, a mapper's name misspelt.
  - Unchanged: `make test` (nestest exact, the header checks).

### 2b. The recompiler in C: tracing and writing the C
- The tracer (following the code from the vectors, the entry points and
  `.missed`) and the C writer, line for line as `recomp.py` makes it.
- `build/nesrecomp-recomp`, with the same options (`-o`, `--entry`,
  `--missed`) and the same printed lines.
- Check:
  - all 319 files, with their `.missed` files and nestest's `--entry
    C000`, give the same `.c` byte for byte, and print the same lines;
  - how long each takes (the C one should be much faster: worth
    knowing, not a pass/fail).
  - Breaks: one opcode's cycles wrong, a page-cross penalty dropped,
    `.missed` ignored, two cases' order swapped, an FDS routine's inline
    pointers miscounted, a mapper write not marked.

- Done:
  - **`recomp/ops.c`:** the opcode table, built in recomp.py's order (so
    a later entry replaces an earlier one exactly as there), with the
    mnemonic sets and the C text each instruction becomes.
    - The cycle maps, and their check against the table at start-up, as
      recomp.py does on import.
  - **`recomp/gen.c`:** `trace`, and the C writer (`gen_insn`,
    `mem_body`, `goto`, the interpreter, the cycle maps, `generate`).
    - Python builds each line as a list of strings joined with spaces,
      and an empty one still adds a space (`NOP` leaves a double
      space). `struct parts` does the same.
    - The instructions found are kept in a hash table, then sorted by
      bank and address as Python's `sorted` does.
  - **`recomp/main.c`** writes the file and prints the same lines as
    recomp.py.
  - nestest came out byte for byte the same on the first try, and so
    did all 394 files.
  - **`tests/check_recomp.py`,** 69 checks now. New:
    - all 394 readable files, alone and the 130 with their `.missed`:
      the same C byte for byte, and the same printed lines;
    - nestest as `make test` recompiles it;
    - the files made in step 2a;
    - **three new made programs:** every opcode in the table, each with
      operands at the edges the C writer decides on ($4018, $401F,
      $4020, $5110-$5118, $8000, indexing across $2000 and $8000,
      `JMP ($12FF)`, branches of 0, a page, +127 and -128). One as
      NROM, one as MMC1, and the writing ones as MMC5.
    - It also prints the time: the C version is about 7 to 8 times
      faster here. These test ROMs have little code, so most of each
      run is starting the program; recomp.py takes 0.05 s on the
      largest.
  - **Breaks, 20 tried, all caught,** after one fix to the check:
    - "I/O ends at $4018, not $4020" wasn't caught at first: nothing in
      the collection reads $4018-$401F directly. The every-opcode
      programs were added for it.
    - Their first layout put the program where MMC1 and MMC5 don't
      show it at power-on, so the tracer followed filler bytes. It
      showed because the C had no $4018 in it. The program is now in
      the banks each mapper shows at power-on.
    - "an empty part not joined" first changed nothing, because the
      break was written wrongly. Rewritten, it's caught.
    - "one opcode's cycles wrong" is caught twice over: the C version's
      own start-up check of the cycle maps refuses to run, as
      recomp.py's does.
    - The others: a page-cross penalty dropped, `.missed` ignored, the
      cases sorted by address before bank, FDS inline pointers
      miscounted, MMC5's low registers ignored for mapper writes, `JMP
      ($xxFF)`'s page wrap, a page-crossing branch's cycle, the
      accumulator form, RAM code guarded by its first byte only,
      tracing stopping after a `JSR`, a `goto` to a label never
      translated, the summary's bank count, the stopped-at spots
      unsorted, a 16 KB unit not followed, `TAS`, `(zp),Y`'s pointer at
      $FF, a branch back of exactly 128.
  - recomp.py isn't changed in this step, so `make test-all` and the
    395 files' C stay as in step 2a.

### 3. The app without Python
- The app runs the C recompiler, and the bundle carries it. Nothing in
  the app starts `python3` any more.
- `make game`, `make run` and `make test` use the C recompiler too.
  `make test-recomp` runs both on all 319 files and compares.
- The build record (`.stamp`) uses the recompiler program's time in
  place of `recomp.py`'s.
- Check:
  - `make test-app` passes;
  - the app, with reading Python forbidden (`/usr/bin/python3`,
    Homebrew's), builds and plays a free ROM;
  - a new recompiler rebuilds games that were up to date;
  - the suite and nestest as before.
  - Breaks: the app still calling `python3`, the stamp not noticing a
    new recompiler, a recompiler error not reaching the TV.

- Done:
  - **The app** runs `nesrecomp-recomp`, found beside its own program:
    `build/` for `make app`, `Contents/MacOS/` in the bundle.
    - The build record uses the recompiler's time.
    - If the recompiler is missing, the build says "the app's recompiler
      is missing".
    - `--sdl-info` also says where the recompiler is.
  - **The PATH line naming Homebrew is gone.** The app only sets the
    system's PATH if it gets none, so `cc` is found.
  - A failed build also writes its reason to stderr, so an app opened
    from Finder leaves it in the Mac's log.
  - **The recompiler** is built for Intel and Apple Silicon, and the
    bundle carries it.
  - **`make game`, `make run`, `make test`** (nestest) **and the test
    suite** (`tests/run_tests.py`) use it too. recomp.py is kept as the
    reference, and `make test-recomp` compares the two.
  - **Checks:**
    - `tests/check_standalone.py`, 33 now. The bundle names
      `/opt/homebrew` nowhere, with no exception left. Neither program
      names Python. The recompiler is there, the same code, for both
      kinds of Mac, needing only Apple's libraries. The program finds
      it. With Python stopped from running (the check first makes sure
      it really can't), the bundle builds and plays the test ROM, and
      its log shows its own recompiler. A recompiler missing gives the
      message.
    - `tests/check_app.py` still has 58: "a newer recompiler: built
      again" now uses a copy of the app with its own recompiler beside
      it.
    - `tests/check_app_bundle.py`: the log names the bundle's
      recompiler.
    - `tests/check_recomp.py`, 72 now: `make game` and `make test`
      recompile with the C version (what `make -n` would run), and one
      suite test passes with a `python3` first on PATH that only fails.
  - **Two things found on the way:**
    - The bundle check, slow: the scan of the bundle for
      `/opt/homebrew` used a pattern that took six minutes on the 3 MB
      library. It now looks for the plain text, and takes a second.
    - The bundle check, opened as Finder does, failed twice and then
      passed with no change. The file reached the app (a debug copy
      showed it), but no build started. My best explanation: macOS asks
      before an app opened from Finder may read files in the Desktop
      folder, where this project lives. It asks again for each rebuild
      with an ad-hoc signature, and the app waits until it's answered.
      The check's message now says so.
  - **Breaks, 11 tried, all caught,** after two fixes to the checks:
    - First, the copy of the project with no break passed all three
      checks (check_standalone, check_app, check_recomp), so a "caught"
      means the break.
    - Three breaks first crashed a check instead of failing it. The
      check removed the recompiler from a copy of the app without
      looking first, and check_app listed a folder a failed build never
      made. Both checks now look first, and the three were run again.
    - The breaks: the app still running `python3 recomp.py`, the stamp
      looking at recomp.py, a recompiler error replaced by a vague one,
      the bundle without the recompiler, the recompiler for Apple
      Silicon only, the app looking for it in the project's `build/`,
      Homebrew's bin put back on PATH, a missing recompiler not noticed,
      and `make game`, `make test` and the suite still using recomp.py.
  - Unchanged: `make test-all` (nestest exact through the C
    recompiler, the suite 219 of 220 with test28 as always, the 58 app
    checks), `make test-app-bundle`'s 12, and recomp.py and the C
    version still agreeing on all 395 files.

### 4. The app works from anywhere
- The bundle carries everything a build needs:
  - `Contents/Resources/runtime/` (the runtime's `.c` and `.h` files);
  - the SDL headers and library (step 1);
  - the recompiler (step 3).
- The bundled app no longer has `PROJECT_ROOT`. `make run-app`, for
  working on the project, can still point at the project folder with
  `NESRECOMP_ROOT`.
- Builds, logs and settings go to `~/Library/Application Support/NES
  RECOMP/`, and `.missed` and `.sav` go beside the ROM (see Choices).
- The build record also holds the app's version, so a new app
  rebuilds old games.
- Optional (trim): ship the runtime already compiled, as a library in
  the bundle, so a first build compiles only the game. That saves
  about a third of the first build's time.
- Check:
  - the bundle, copied to a scratch folder whose name has spaces, run
    with reading the project folder, `/opt/homebrew` and Python
    forbidden, builds and plays a free ROM, with its test passing;
  - the app holds no path of this project (searching the program's
    bytes);
  - a game still runs after the app is moved;
  - a ROM on a folder it can't write to still plays, with `.missed` in
    the app's folder.
  - Breaks: a runtime file left out of the bundle, a build written
    inside the bundle, the old project path still used, `.missed`
    lost when the ROM's folder is locked.

### 5. When Apple's compiler is missing
- Before building, the app checks for the Command Line Tools: it asks
  `xcode-select -p` and looks for `clang` there.
  - It never runs `/usr/bin/cc` blindly: on a Mac without the tools,
    that's a stand-in that pops up Apple's install box in the middle
    of a build.
- If they're missing, the TV says so instead of failing: "NEEDS APPLE'S
  C COMPILER", "CLICK TO INSTALL IT", and the command for Terminal,
  `xcode-select --install`.
  - A click runs that command, which opens Apple's own installer.
  - When it's done, dropping the ROM again builds it.
- Check:
  - the screen pixel for pixel;
  - with reading `/Library/Developer` forbidden, a drop shows that
    screen and the build doesn't start;
  - with the tools there, nothing changes.
  - Breaks: the tools always reported present, the screen replaced by
    the general error, a click that runs nothing.
  - Not checked for real here: a Mac that has never had the tools. That
    would need a second Mac or a fresh macOS install in a virtual
    machine; it's optional, and for you to decide.

### 6. Recording gameplay
- In the game's window, **V** starts and stops a recording. A small red
  "REC" shows in the window's corner, and it isn't in the movie.
- Each recording is one `.mov` in `~/Movies/NES RECOMP/`, named by the
  game and the date and time:
  - the picture: H.264, the NES's 256x240 at 4x with sharp pixels
    (1024x960), at the NES's 60.0988 frames a second;
  - the sound: 48 kHz, uncompressed, in the same file;
  - quitting with Esc, or the window closing, finishes the file
    properly. A movie cut off part way can't be opened at all, so this
    matters.
- In the runtime (`runtime/record_mac.m`), so `make run` has it too.
  `--record FILE` with `--frames N` records with no window, for the
  checks. The app's controls card adds "V = RECORD".
- Optional (trim):
  - **P** saves a PNG of the screen to the same folder;
  - a ProRes choice, bigger files that some editors prefer to H.264.
- Check, with a ROM the check makes (`tests/make_av_sync_test.py`): a
  white flash and a beep starting on the same frame, once a second. A
  small reader, `tests/read_movie.m` (AVFoundation, compiled by the
  check), reads the movie back:
  - the number of frames, their size and rate;
  - each frame against the runtime's own picture of that frame, close
    (H.264 loses a little, so not exact);
  - the sound, the same samples as the runtime's `--wav` of the same
    run;
  - each beep starts within one frame of its flash;
  - a recording stopped by quitting still opens.
  - Breaks: the sound a frame late, a frame dropped, the wrong rate, no
    sound, a recording that doesn't stop, a file not finished on quit.
  - The runtime changes, the generated C doesn't: the 319-file check,
    the suite and nestest as before.
  - For you to try: a recording in QuickTime and in the editor you use.

### 7. Under the hood: the numbers
- After a game, and with **H** on the drop screen for the last ROM, an
  "UNDER THE HOOD" screen on the TV shows:
  - how many 6502 instructions the recompiler found and translated
    (its "translated N instructions" line);
  - how many spots ran in the interpreter this time (the game log's "N
    spot(s) ran in the interpreter" line);
  - each run so far, as a small bar chart, shrinking as you play: run
    1, 12 spots; run 2, 3; run 3, 0.
- A plain note on what a "spot" is: a place the interpreter had to
  start, not a count of instructions. The next run translates those
  spots too.
- Optional (trim): also count the instructions the game actually ran,
  translated versus interpreted, as a share ("99.97% ran as translated
  C").
  - This can be done in the runtime's header alone: its `STEP` macro is
    used by both, with a fixed address in translated code and the
    variable `pc` in the interpreter. So the generated C stays the same.
  - If that turns out unreliable, the step keeps to the spots.
- The history is kept per ROM in the app's folder.
- Check:
  - the screen pixel for pixel;
  - nestest built without its `.missed`, played, built again: the
    numbers match the recompiler's and the game's own lines, and the
    second run's spots are fewer;
  - the history grows by one per game.
  - Breaks: the numbers from the wrong run, the history not saved, a
    bar for the wrong run, the counts swapped.

### 8. Under the hood: the 6502 next to its C
- The C recompiler's `--listing FILE` writes the side file (see
  Choices), and the app's build asks for it.
- A new full-window view, from the "UNDER THE HOOD" screen:
  - the original 6502 instructions on the left (`C5F5  AD 02 20  LDA
    $2002`), and the C each one became on the right, in step;
  - the arrow keys scroll, and Tab jumps to the next routine (each
    `JSR` target);
  - it starts at the game's reset routine.
  - Optional (trim): a line of plain English for the instruction under
    the cursor ("LDA: load A from memory").
- The TV is too small for this, so the view uses the whole window at a
  finer grid, in the app's lettering and colours. I'd show you a
  screenshot of the look before finishing it.
- Check:
  - every instruction's lines are really in the `.c` there, and start
    with its label;
  - the 6502 text agrees, instruction by instruction, with `nestest.log`
    (an independent listing of the same code);
  - the 319 files' C is unchanged with `--listing` on;
  - the view pixel for pixel at its start, after scrolling, and after
    Tab.
  - Breaks: the C lines off by one, an operand written wrongly (`$20`
    for `$2002`), the listing changing the `.c`, Tab skipping a routine.

### 9. A release
- `make release` builds `build/NES-RECOMP-1.0.zip`, with:
  - the app;
  - a short "read me first" (what it is, what it needs, how to open it
    the first time);
  - the MIT License;
  - SDL's license.
- It's zipped with `ditto`, which keeps the app's signature and links
  as macOS expects.
- Signing, three options:
  - **As now (an ad-hoc signature).** Free. The first time, the person
    has to allow it: on macOS 15, System Settings, Privacy & Security,
    "Open Anyway". Fine for friends and viewers with instructions.
  - **Signed with an Apple Developer ID and notarized by Apple.** It
    opens with no warning. It needs the Apple Developer Program (US$99
    a year), and a signing step and an upload to Apple at each
    release. The games the app builds are made on the person's own Mac,
    so they don't need signing.
  - **Decide later:** release ad-hoc now and notarize if people find
    the warning a problem.

  My suggestion: ad-hoc for now, with the read-me explaining "Open
  Anyway".
- **GitHub release, if you want one:** this project has no GitHub
  remote yet. It would need a repository on your account, public or
  private, and posting there is your go-ahead to give.
- Check:
  - the zip, unzipped into a scratch folder and marked "downloaded" as
    a browser would (`com.apple.quarantine`), is what Gatekeeper
    describes;
  - once allowed, it passes the step 4 check from there;
  - the README's "The app" section rewritten for the standalone app.
  - For you to try: give it to someone, or a second Mac or user
    account.

## Order, and what can be trimmed

- **Why this order:**
  - the recording and teaching parts go into the runtime and recompiler
    the bundle carries, so the bundle comes first;
  - step 8 needs the C recompiler (the listing is written once, in C,
    not in Python and then again);
  - the release comes last so it includes everything.
- **If you'd like something to share sooner:** a release right after
  step 5 works (step 9 moved up). Recording and teaching would come in
  a version 1.1.
- **Can be trimmed:**
  - 2a and 2b as one step, with one commit;
  - the prebuilt runtime library (step 4);
  - the virtual-machine try without the compiler (step 5);
  - P for screenshots and the ProRes choice (step 6);
  - the instruction count beside the spots (step 7);
  - the bar chart, keeping only the numbers (step 7);
  - the plain-English line (step 8);
  - the GitHub release and notarization (step 9).
- **The heaviest step** is 2 (about 1,200 lines of Python to C, to
  match byte for byte), then 8 (a new kind of screen).

## Not in this stage
- Windows and Linux. SDL would allow them, but recording uses
  AVFoundation and the compiler check is the Mac's.
- A library of built games, settings and key remapping.
- Running without any C compiler. That would need the recompiler to
  produce machine code itself, which is a different project.

## Risks
- **Byte-for-byte C from a port.** Python's sorting, its number
  formatting and its dictionaries' order all have to be matched. The
  319-file check finds any difference at once; fixing them is where
  step 2's time goes.
- **Building SDL2 from source** may need settings found by trying. If
  it fights back, choice (a) is the fallback, with the macOS 15 /
  Apple Silicon limit written in the read-me.
- **"Forbidden to read" checks use `sandbox-exec`.** Apple no longer
  documents it, but it works on this macOS. If it stops working, the
  fallback is checking every path the app opens (`fs_usage`).
- **Gatekeeper changes between macOS versions.** What a downloaded
  ad-hoc app needs the first time is checked on this Mac only.
- **Recording on a slow Mac:** the movie is made on game time, so it
  stays in sync. But if encoding can't keep up, the game would slow
  while recording. On this Mac a 1024x960 H.264 stream should be
  light; step 6 measures it.
