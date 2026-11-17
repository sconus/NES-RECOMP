# Plan: NES RECOMP for Windows

Goal: the same app on Windows. Someone unzips `NES RECOMP`, opens it,
drops a ROM on the TV, and the game is recompiled, built and played on
their PC, with recording, "under the hood" and the support link, as on
the Mac. It needs nothing installed first: no compiler, no Python.

Every step keeps what holds on the Mac today:
- `make test-all`, `make test-recomp`, `make test-standalone`,
  `make test-app-bundle` and `make test-release` don't get worse, and the
  Mac app and its release are built as before;
- the 395 files under `tests/` recompile to the same C, now on Windows
  too, byte for byte the same as on the Mac;
- only free test ROMs and the project's own are used;
- each check is confirmed with breaks made in scratchpad copies, and only
  real failures count (not a crash, not a failed build).

## Where things stand

Most of the project is ready for Windows already:
- **The recompiler** (`recomp/`) is plain standard C. It should build for
  Windows as it is.
- **The runtime** (the CPU, the picture, the sound, the controllers) is C
  on SDL2, which works on Windows. A few places use Mac or Unix calls:
  where recordings and pictures go (`~/Movies`), Ctrl+C and quit
  signals, making folders, and recording itself (`record_mac.m`, Apple's
  AVFoundation).
- **The app** draws all its screens itself into its own canvas, so they
  would look the same, pixel for pixel. What's Mac-only is around them:
  starting the recompiler, the compiler and the game (`posix_spawn`),
  its build thread, finding its own files, the app folder, the file
  picker (`osascript`), copying SDL2, the compiler check (`xcode-select`),
  and the menu with the support link (Cocoa).
- **zlib** (for PNG pictures) is part of macOS, not of Windows.

The big difference is the C compiler. On a Mac the app uses Apple's
free one, or offers to install it. Windows has none built in, and
Microsoft's is a download of several gigabytes. So the Windows app has
to bring its own.

## Choices

- **The compiler inside the app: Zig** (recommended). Zig is a single
  free download (MIT License) that includes clang, the compiler Apple's
  is built on, with everything needed to build Windows programs. Its
  `zig cc` takes the same options as `cc`, and the generated C and the
  runtime already build with clang (the runtime's instruction counting
  uses a clang feature, `__builtin_constant_p`).
  - The cost is size: the app would grow by about 50 to 80 MB. I'll
    measure it and leave out what a build doesn't use.
  - A compiler's first build also prepares its C library, which takes a
    while. The release can carry that work already done, so a first
    build takes seconds, as on the Mac.
  - Other options: **TinyCC** (under 1 MB, compiles very fast, but the
    games run more slowly and it lacks clang features such as
    `__builtin_constant_p`), or **asking people to install Microsoft's
    compiler** (several gigabytes, a poor first experience).
- **The same compiler builds everything.** Zig can build Windows
  programs on the Mac too (cross-compiling), so the Windows app, its
  SDL2 and zlib can be built here, with the same compiler that goes into
  the app. It's one download, needing your OK at step 1.
- **The checks run on a real Windows machine, on GitHub.** Your
  repository is public, so GitHub Actions gives it free Windows
  machines. A workflow file (`.github/workflows/windows.yml`) would build
  the Windows version and run the checks on every push. Pushing it is
  your go-ahead, as any push is.
  - **Your Boot Camp Windows** is for what only a person can judge: the
    window, the sound, controllers, recording opened in a video app,
    SmartScreen's first-launch warning, a high-resolution screen.
    Restarting into Windows is needed for each try, so the automatic
    checks do the everyday work.
- **SDL2 and zlib from their official source releases**, built with
  Zig, as SDL2 is for the Mac (step 1 of PLAN-standalone). SDL2's source
  is already here; zlib's needs your OK to download (about 1.5 MB, zlib
  License).
- **Recording on Windows: MP4, with Microsoft's Media Foundation.** It's
  part of Windows and writes H.264 video that every video app and editor
  opens.
  - The difference from the Mac: Media Foundation puts AAC sound in an
    MP4, not uncompressed sound. AAC loses a little, like H.264 does for
    the picture, so the check compares the sound closely rather than
    sample for sample.
  - The movie runs on game time, as on the Mac, so picture and sound
    stay in sync.
  - Some editions of Windows ("N" editions, sold in Europe) come
    without Media Foundation's video codecs. There, the app says so
    instead of recording, and points to Microsoft's free "Media Feature
    Pack".
- **One small layer for what differs between the systems.**
  - `app/os_mac.c` and `app/os_win.c` hold, behind the same few
    functions, what each system does differently: starting a program
    and waiting for it, a thread, the app's own folder, the app folder,
    copying a file, choosing a file, opening a link.
  - The rest of the app stays one file for both.
  - The runtime gets the same treatment where needed (`runtime/
    sys_mac.c`, `runtime/sys_win.c`), with recording in
    `record_mac.m` and `record_win.c`.
- **Where things go on Windows:**
  - builds, logs and settings: `%LOCALAPPDATA%\NES RECOMP` (on Windows,
    the app's folder in your user account);
  - recordings and pictures: `Videos\NES RECOMP`;
  - `.missed` and `.sav` beside the ROM, as on the Mac.
- **The support link on Windows:** on the About screen (D) as on the
  Mac, and in the window's own menu (the one behind its icon, top left,
  or Alt+Space), since a Windows window has no menu bar like the Mac's.
- **Names with accents or other alphabets** (`Pokémon`, Japanese file
  names) work through Windows's UTF-8 setting for an app (its
  manifest), so the C code can keep its plain `fopen` and friends.
- **Signing:** unsigned at first. The first time, Windows SmartScreen
  says "Windows protected your PC"; More info, then Run anyway. The
  read-me says so, as the Mac's explains Open Anyway. A code-signing
  certificate removes that, at a cost; that's for later, as notarizing
  is on the Mac.

## Steps

### 1. The tools, and the recompiler on Windows
- Zig on this Mac (your OK to download, about 45 MB). `make windows`
  starts the Windows build in `build/windows/`.
- The recompiler built for Windows (`nesrecomp-recomp.exe`), with any
  fixes it needs. Windows reads some numbers as narrower than the Mac
  does (`long` is 32 bits there), and writes `\r\n` for a new line in a
  text file unless told otherwise.
- **The Windows test bench:** `.github/workflows/windows.yml`. Your OK
  is needed to push it. On each push, a GitHub Windows machine builds
  the recompiler with Zig and checks it.
- Check:
  - on GitHub's Windows machine, all 395 files under `tests/` recompile
    to the same C as on the Mac, byte for byte, and print the same
    lines (Python is on those machines, so recomp.py is the reference
    there too);
  - the listing (step 8 of PLAN-standalone) the same too;
  - on the Mac, nothing changes.
  - Breaks: a number cut to 32 bits, `\r\n` in the C, a file opened as
    text instead of bytes, the workflow not failing when a check fails.

- Done (committed and pushed: 5fcd20d, then the fix 47c886a; the
  Windows run is green):
  - **Zig 0.17.1** is in `build/zig/` (from ziglang.org, its checksum
    matching the one Zig publishes; 421 MB unpacked, mostly C library
    headers for every system it can build for). `make windows` builds
    `build/windows/nesrecomp-recomp.exe`, a 64-bit Windows program,
    with no warnings.
  - **The recompiler needed four small changes:**
    - Its own CRC-32 for `--dump-rom` instead of zlib's (Windows has no
      zlib). It's the same checksum, so the dumps are unchanged.
    - The C and the listing written as bytes, so Windows adds no "\r\n".
    - The ROM's name in the C's first line cut at a "\" as well as a
      "/" on Windows.
    - The listing's header names the C file alone, not its folder, so a
      listing is the same on every machine. It also no longer names a
      folder of the machine that made it.
  - **The check:** `tests/check_same_c.py`.
    - On the Mac, `make same-c` writes down the fingerprints (SHA-256) of
      the C, the listing and the printed lines for all 396 recompiles
      (every file under `tests/`, the free test ROM clone at its pinned
      commit, and nestest as `make test` recompiles it) in
      `tests/same_c.txt`.
    - Anywhere, `make test-same-c` (or the script with
      `--recompiler PATH`) recompiles them all and checks the
      fingerprints are the Mac's, byte for byte. It also checks that what
      each file reads (`--dump-rom`) is what recomp.py reads on that
      system, and that a refused file gets the same message. Python
      writes "\r\n" on Windows, so the C itself is compared by
      fingerprint, not against recomp.py there.
  - **The test bench:** `.github/workflows/windows.yml`. On each push, a
    GitHub Windows machine:
    - fetches the test ROM clone at the same commit as here;
    - downloads Zig for Windows, refusing it if its checksum is wrong;
    - builds the recompiler with warnings as errors;
    - runs the check;
    - runs `tests/windows_breaks.py`.
  - **The breaks** are the mistakes a Windows build invites: the C
    written as text, the listing written as text, a ROM read as text,
    and a number cut to 32 bits (a key mixing bank and address in an
    `unsigned long`, which is 64 bits on the Mac and 32 on Windows).
    Each is made in a scratch copy on GitHub's machine, never in the
    repository. Caught means a FAIL line and a failing status, so the
    workflow would fail.
    - On the Mac, with its own compiler, the copy with no break passes
      and none of the four is caught: on a Mac these mistakes change
      nothing. That's why they're checked on Windows.
  - **On GitHub's Windows machine:** all 396 recompiles give the Mac's
    C, listing and printed lines, byte for byte, and all 395 readable
    files read as recomp.py reads them. The copy with no break passed,
    and 4 of 4 breaks were caught.
  - **Found on the way:**
    - **The token:** GitHub refuses a push that adds a workflow unless
      the token has the "workflow" permission. You made a new token with
      it.
    - **A hang the check didn't count:** with a number cut to 32 bits,
      the Windows recompiler loops forever. The first run's check waited
      five minutes and crashed instead of failing. Each recompile now
      has a minute (they take milliseconds); one that doesn't finish is
      a FAIL, and the rest aren't started. With a stand-in that never
      finishes, the check fails in a minute.
    - **GitHub's logs need a signed-in account.** You signed in to
      GitHub in the app's browser pane, where I read them.
  - The workflow uses actions/checkout@v5 (the Node.js 20 warning gone).
  - Unchanged on the Mac: `make test-all` (nestest exact, the suite 219
    of 220 with test28 as always, the app and recording checks),
    `make test-recomp`, `make test-standalone`, `make test-app-bundle`
    and `make test-release`.

### 2. The runtime on Windows
- SDL2 and zlib built for Windows with Zig, from their source releases
  (zlib's needs your OK to download).
- The runtime's Unix calls behind `sys_win.c`:
  - the recordings folder;
  - Ctrl+C and closing the console (Windows's own ways of saying "quit");
  - making folders;
  - the user's home folder.
- `make windows` builds a game for Windows as `make game` does.
- Check, on GitHub's Windows machine:
  - nestest exact, as `make test` checks it;
  - the test ROM suite (`tests/suite.txt`, the free test ROM clone):
    219 of 220, the same as on the Mac, including its 32 pictures and
    8 sounds;
  - a game's picture and sound the same as on the Mac, exactly (they
    come from the same C).
  - Breaks: a picture's byte order swapped, the sound's sample rate
    wrong, a save written to the wrong place, Ctrl+C losing the
    `.missed` file.


- Done (committed and pushed: 57da016; the Windows run is green):
  - **SDL2: SDL's official Windows build** (`SDL2-devel-2.32.10-mingw.zip`,
    from SDL's GitHub release, its published SHA-256 checked), not a
    build from source as planned. Building SDL for Windows needs CMake
    or a Windows resource compiler, which neither this Mac nor GitHub's
    Windows machine reliably has. This is the same version as the Mac's,
    made by SDL's own maintainers, and the identical file on both
    machines.
  - **zlib 1.3.1** (zlib.net; its checksum matched zlib's published one
    and the copy on zlib's GitHub), its 15 C files compiled by Zig.
    zlib 1.4 was only eleven days old, so the long-used 1.3.1 it is.
  - **The runtime's changes:**
    - `runtime/sys.c` holds the Mac's way and Windows's for the
      pictures' folder (Movies or Videos), making folders, whether a
      file is there, and quitting from outside (signals on the Mac;
      the console's Ctrl+C, Ctrl+Break and closing on Windows).
    - `video_sdl.c` was missing an `#include <stdio.h>`, which the Mac's
      SDL headers had hidden.
    - `record_win.c` is a stand-in until step 3: on Windows, V says
      "recording isn't on Windows yet".
    - **Ctrl+C now always ends a game well**, on the Mac too, not only
      while recording, so `.missed`, `.sav` and any recording are
      written.
  - `make windows-game ROM=x.nes` builds `build/windows/<name>.exe`, with
    `SDL2.dll` beside it.
  - **The test scripts build through `tests/toolchain.py`:** the Mac's
    `cc` and Homebrew's SDL2 as before, or Zig with SDL's Windows build
    and zlib.
    - `tests/run_nestest.py` does what `make test` does, on any system.
    - `tests/check_runtime_sys.py` checks `sys.c`: a picture into a new
      folder two levels deep, into the system's own folder, two in one
      second kept apart, and a game asked to quit from outside ending
      well.
  - **On GitHub's Windows machine:**
    - nestest exact (all 8,991 instructions, with its cycles), the game
      controller self-test, and 19 of 19 header cases;
    - the test ROM suite at 219 of 220 (test28 as always), with its 32
      pictures and 8 sounds the same as on the Mac;
    - `sys.c`'s four checks (the default folder `~\Videos\NES RECOMP`);
    - step 1's checks.
  - **Breaks, 10 of 10 caught there**, the copy with no break passing:
    step 1's four, and six new ones: the pictures' default folder wrong
    on Windows, folders not made two levels deep, a file's being there
    never seen (a second picture over the first), Ctrl+Break not caught
    (the game killed), a picture's red and blue swapped, and the sound
    at 44,100 samples a second. The suite counts a picture that differs
    as "WORSE" rather than FAIL, so the breaks script counts both.
  - Unchanged on the Mac: `make test-all`, `make test-recomp`,
    `make test-standalone`, `make test-app-bundle` and
    `make test-release` all pass; the app now compiles 18 runtime files.

### 3. Recording on Windows
- `runtime/record_win.c`, with Media Foundation: an MP4, H.264 at
  1024x960, 60.0988 frames a second on game time, AAC sound at 48 kHz.
  V, P, `--record` and `--record-dir` as on the Mac.
- On a Windows without the video codecs, a clear message instead.
- Check, on GitHub's Windows machine, with the same test ROM as on the
  Mac (`tests/make_av_sync_test.py`: a flash and a beep, once a second),
  read back with Media Foundation (`tests/read_movie_win.c`):
  - the frames, their size, their rate and timing, each frame against
    the runtime's own picture of it;
  - the sound close to the runtime's `--wav` of the same run (AAC loses
    a little);
  - each beep within a frame of its flash;
  - a recording stopped by Ctrl+C still opens.
  - Breaks: the sound a frame late, a frame dropped, the wrong rate, no
    sound, a file not finished on quit.

- Done (tested on the branch `windows-step3`; the Windows run is green):
  - **`runtime/record_win.c` records with Media Foundation:** an MP4,
    H.264 at 1024x960 and 20 Mbit/s, AAC at 48 kHz mono and 192 kbit/s,
    on game time. The picture's colours are worked out here (BT.709,
    16-235, as on the Mac), and the file says so.
    - **H.264's Baseline profile**, not High: with High, the encoder
      shows frames out of order ("B-frames"), and Media Foundation's MP4
      then shows every frame one frame late with nothing in the file to
      undo it, so the picture would be 17 ms behind the sound. Found by
      the first Windows run. At 20 Mbit/s it looks the same.
    - **Frame times to the file's tick:** Media Foundation's MP4 keeps
      the picture's time in its own unit, 60,098 ticks a second, so each
      frame is at its exact game time to the nearest tick (16.6 µs): 1,000
      ticks a frame, with an occasional 999.
    - **Media Foundation is loaded when a recording starts**, only from
      Windows' own folder. A Windows without it (the "N" editions) still
      runs games; V then says Microsoft's Media Feature Pack adds it.
      That message is written but not tried on a real Windows N.
    - V's movies end in `.mp4` on Windows (`record_ext()`), `.mov` on the
      Mac.
    - The game is linked with `ole32` (Windows' COM, which Media
      Foundation needs); `make windows-game` too.
  - **The check, `tests/check_record_win.py`**, reads the movies back
    with `tests/read_movie_win.c` (Media Foundation's decoders), and
    looks inside the MP4 at its timing tables. On GitHub's Windows
    machine, all pass:
    - 300 frames, 1024x960, at 60.0988 a second, frame N at its game time
      (to the file's tick), from 0, none shown out of its place;
    - each checked frame within 1.3 of 255 of the runtime's own picture
      on average; the flashes 4 frames each, 60 apart;
    - the sound as long as the picture, and 0.9% different from the
      `--wav` of the same run; each beep within 0.07 of a frame of its
      flash;
    - stopped by Ctrl+Break part way: the movie opens;
    - in a window, V's way (names, " 2"), P's picture, and the default
      `Videos\NES RECOMP`.
  - **16 of 16 breaks caught**, the copy with no break passing: steps 1
    and 2's ten, and six for recording (the sound a frame late, a frame
    dropped, the wrong rate, no sound, a file not finished on quit, and
    B-frames back).
  - The Mac's suites still pass (`make test-all`, 219 of 220 as always,
    and the system checks).

### 4. The app on Windows
- `app/os_win.c`, with the Mac's ways moved into `app/os_mac.c` behind
  the same functions:
  - starting the recompiler, the compiler and the game, and waiting;
  - the build thread;
  - finding its own files (its folder, `runtime\`, `sdl2\`);
  - the app folder (`%LOCALAPPDATA%\NES RECOMP`);
  - copying `SDL2.dll` beside a built game;
  - Windows's own file picker;
  - opening the support link;
  - the support item in the window's menu.
- Drag and drop onto the window, as on the Mac (SDL handles it).
- The screens are unchanged: the same canvas, the same pixels.
- Check, on GitHub's Windows machine: `tests/check_app.py`'s screens
  pixel for pixel (the same pictures as on the Mac); building, playing
  and "under the hood" from the command line (`--build`,
  `--then-play`); the support link, with a stand-in for opening it. On
  the Mac, all of `make test-app` and `make test-app-bundle` unchanged.
  - Breaks: a path with a space breaking a build, the app folder in the
    wrong place, a build that never finishes on Windows, `SDL2.dll` not
    beside a game, the support link wrong in the window's menu.

- Done (tested on the branch `windows-step4`; the Windows run is green):
  - **`app/os.h`**, with the Mac's ways in `app/os_mac.c` and Windows's
    in `app/os_win.c`: starting a program and waiting for it (on
    Windows with its arguments quoted as Windows programs read them
    back, and no console window), a thread, the program's own path, the
    app's folder (`%LOCALAPPDATA%\NES RECOMP`), file times and sizes,
    copying a file, listing a folder, the file picker (Windows's own
    "Open" box) and opening a link. Text is UTF-8 inside the app and
    Windows's wide characters at each call. `build.c`, `play.c` and
    `app.c` use only these; the rest is unchanged, so the screens are the
    same pixels.
  - **Building on Windows:** `zig cc` (the app's own `zig\zig.exe` once
    step 5 brings it; until then one on PATH), games named `NAME.exe`
    with `SDL2.dll` copied beside them, zlib linked from the app's
    folder, only the runtime's `.c` files compiled. With no compiler, the
    app says "the app's compiler is missing" (no installer screen).
  - **The support item on Windows** is the last of the window's own menu
    (its icon, or Alt+Space), after a line: `app/support_win.c`.
  - **`make windows-app`** (`tools/make_windows_app.py`) puts the app
    together in `build/windows/app`: the app (a windowed program), the
    recompiler, the runtime's sources, `SDL2.dll` with SDL's headers and
    import library, and zlib, 7.9 MB in all.
  - A game's log is now `NAME.game.log` on both systems (on Windows it
    was `NAME.exe.game.log` at first; found by the first Windows run).
  - **`tests/check_app.py` runs on Windows too:** 87 checks there, all
    passing, and the Mac's 95 (the Mac's own 8: Apple's compiler and its
    app menu). New on both: builds go to the app's folder by default,
    SDL's library is beside each game, and a build or game that never
    ends stops the check, not hangs it. On Windows a crash is reported
    as an exception, and the stand-ins are a small program
    (`tests/stand_in.c`), not scripts.
  - **21 of 21 breaks caught**, the copy with no break passing: steps 1
    to 3's sixteen, and five for the app (a path with a space, the app's
    folder in the wrong place, a build that never finishes, `SDL2.dll`
    not beside a game, the wrong link in the window's menu). On GitHub's
    machine SDL's own folder is on PATH, so a game without `SDL2.dll`
    beside it still started there; the check that the copy is beside it
    caught that break.
  - The Mac's suites still pass: `make test-all` (219 of 220 as always),
    `test-app-bundle`, `test-standalone`, `test-release`.
  - Not checked by machine, for step 7: the real window, dragging a ROM
    onto it, the "Open" box, and clicking the menu item by hand.

### 5. The compiler inside the app
- The app's build runs the Zig that comes with it, not a compiler on
  the PC: `zig cc` with the same options as on the Mac.
- On Windows, no "needs a compiler" screen is needed: the compiler is
  always there. If its files are missing, the app says "the app's
  compiler is missing", as for the recompiler today.
- The first build's preparation is done ahead and shipped, so a first
  build on a new PC takes seconds, not minutes.
- Only the parts of Zig a build needs: the size measured and written
  down.
- Check, on GitHub's Windows machine:
  - with no other compiler reachable (none on PATH, the usual places
    hidden), the app builds and plays a free test ROM, which passes its
    test;
  - a first build's time measured, a second one up to date at once;
  - the log names the app's own compiler.
  - Breaks: the build using a compiler from the PC, the shipped
    preparation not used, a part of Zig left out that a build needs.

### 6. The Windows release
- `make release-windows` builds `build/NES-RECOMP-<version>-windows.zip`.
  It holds one folder, "NES RECOMP <version>", with:
  - `NES RECOMP.exe`, with the app's icon (the same picture as the Mac
    app's) and its version;
  - the runtime, the recompiler, Zig, `SDL2.dll`;
  - `READ ME FIRST.txt` for Windows (SmartScreen's More info, Run
    anyway; where things go; the keys; the support link);
  - the licenses: MIT, SDL's and zlib's, and Zig's with what it carries
    (LLVM's and MinGW-w64's).
- Check, on GitHub's Windows machine:
  - the zip's contents, and no path of the machine that built it;
  - unzipped into a folder whose name has spaces, and marked as
    downloaded as a browser marks it (Windows's "Mark of the Web"), it
    builds and plays a free test ROM;
  - the read-me's points.
  - Breaks: a license left out, the icon missing, a file the app needs
    left out, the version wrong.

### 7. Your turn: Boot Camp
- A checklist for you, on your MacBook Pro in Windows:
  - the zip from GitHub, unzipped, SmartScreen's warning, Run anyway;
  - dropping a ROM, the loading bar, playing;
  - sound, a game controller, resizing and full screen (Alt+Enter and
    the window's own buttons), a high-resolution screen;
  - V to record, the movie opened in Windows's video app and in your
    editor;
  - I, H and C, and the support link.
- The same machine in macOS: the Mac release on a real Intel Mac,
  including Open Anyway, which until now was only tried on this Mac and
  under Rosetta.
- Whatever you find gets fixed here, with a check where one can be
  written.

### 8. Releasing both
- Version 2.0, with your go-ahead: both zips, Mac and Windows, on one
  GitHub release, with notes for each. If the v2 mappers (71, 79 and the
  others) are ready by then, they go in too.
- The README gets a "Windows" part: getting it, opening it the first
  time, and building it from the project.

## Order, and what can be trimmed

- **Why this order:** every later step needs the test bench of step 1;
  the app (4) needs the runtime (2); the compiler inside (5) is easiest
  once the app builds with a compiler that's there; the release (6)
  needs it all; and your test (7) is worth most on the real release.
- **Can be trimmed:**
  - recording (step 3), for a first Windows version without it: V would
    say "not on Windows yet";
  - the support item in the window's menu (the About screen still has
    it);
  - the shipped first-build preparation (5): the first build would then
    take a minute or two, once.
- **The heaviest steps** are 4 (the app's layer for each system) and 5
  (the compiler inside, and its size).

## Not in this stage
- Windows on ARM (Snapdragon laptops). x64 apps run on those too,
  through Windows's own translation; a native version can come later.
- Linux. After this stage it's close: SDL2, Zig and the layer of step 4
  would cover most of it.
- A code-signing certificate, and the Microsoft Store.
- Windows versions before Windows 10.

## Risks
- **Zig's size and first build.** If Zig can't be trimmed well, the app
  is bigger than the Mac's by far. TinyCC is the fallback for size, at
  the cost of speed.
- **Antivirus.** Windows Defender scans new programs, and a game built
  on the PC is one, so a first run may be slower. A bundled compiler
  making programs is sometimes flagged by other antivirus programs;
  only trying will tell.
- **Media Foundation's H.264 encoder** differs between Windows versions
  and graphics cards. The check runs on GitHub's Windows machine, and
  you try it on yours.
- **Paths:** Windows still limits most paths to 260 characters, and some
  names (`CON`, `NUL`) can't be files. The app's folder names are short;
  a ROM name like those gets a safe name for its build.
- **GitHub Actions** is free for public repositories. If the repository
  became private, its free minutes would be limited.
- **What only a person can judge** (SmartScreen, controllers, sound on
  real hardware, a video editor) waits for your Boot Camp try, between
  restarts.
