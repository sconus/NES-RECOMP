# Plan: the nesrecomp app (a first version)

Goal: a window you drop a ROM onto, instead of typing `make run`.
- **First screen:** a pixel-art TV with an NES-style console in front of
  it, front and centre, and the words "DROP YOUR NES ROM FILE HERE".
- **After a drop:** a loading bar and "RECOMPILING IN PROGRESS" while
  the ROM is recompiled and built.
- **Then:** the game opens and plays.

Everything the command line does today stays as it is. The app runs
the same steps `make game` does: `recomp.py`, then the C compiler.

## Choices

- **SDL2, in C,** like the runtime. It is already a dependency, it
  draws pixel art naturally (a small picture scaled up with sharp
  pixels), and it hands the window a dropped file (`SDL_DROPFILE`).

  The alternatives would add a toolchain: a native Swift app needs
  Xcode, and Python's Tkinter draws pixel art poorly. A native
  macOS look can come later if wanted.
- **The art is original:** a generic 1980s TV and a grey console of
  that era, with no Nintendo logo, name or trade dress copied. It lives
  as text-art in a Python generator (like the BIOS:
  `tools/make_app_art.py` writes a C header), so it can be edited and
  redrawn.

  The text uses the runtime's 5x7 font (the NSF player screen's),
  enlarged.
- **The canvas:** the picture is drawn at 320x180 and scaled up by a
  whole number, so the pixels stay square and crisp in any window size.
- **The loading bar shows real stages,** not a fake timer:
  - checking the file;
  - recompiling (`recomp.py`);
  - compiling the C (the long part: the bar moves through this stage by
    time, against an estimate from the C file's size);
  - linking.

  If a stage fails, the screen says so with the tool's message, and you
  can drop another file.
- **What you can drop:** `.nes`, `.nsf` and `.fds` files, as the
  recompiler takes them. Anything else gets "NOT AN NES ROM" on the TV
  screen. An unsupported mapper shows the recompiler's own message.
- **Where it runs:** this first version runs from the project folder. It
  needs Python 3, a C compiler and SDL2, as `make run` does. A
  self-contained app you could give to someone else would need Python
  and a compiler bundled, or the recompiler rewritten; that is a later
  stage, if wanted.
- **Testing** stays with free material: the free test ROMs and the
  project's own. The app has a headless mode that saves each screen as
  a PNG, for picture checks, and takes a ROM path on the command line
  in place of a drop, so the suite can drive it.

## Steps

### 1. The window and the art
- `tools/make_app_art.py` writes `app/art.h`: the TV, the console, and
  the colours (the NES palette's, so it looks of a piece).
- `app/app.c`: the window, scaled to fit, with the drop screen:
  - the TV and the console;
  - "DROP YOUR NES ROM FILE HERE" on the TV's screen;
  - a gentle idle animation, such as the screen's glow or scanlines
    flickering, and the console's power light.
- `make app` builds `build/nesrecomp-app`; `make run-app` opens it.
- Check: `--screenshot FILE` saves the first screen as a PNG for a
  picture check; it looks right at several window sizes.

- Done:
  - **`tools/make_app_art.py`** draws the 320x180 picture from simple
    shapes:
    - a striped wall and a wooden table;
    - a wood-cabinet TV with a rounded, scanlined screen, two dials and
      a grille;
    - a grey console in front of it: a light top with the cartridge
      slot, and a dark band with two controller ports, a power light
      and two buttons.

    It writes `app/art.h`: the palette, the pixels, the screen's place,
    and the runtime's 5x7 font, read from `runtime/nsf.c` so there is
    one copy. It also writes `build/app_art.png` to look at. Three
    palette entries are animated: the screen's glow, its scanlines,
    and the light.
  - **`app/app.c`:** the SDL window, resizable, drawn at the largest
    whole-number scale that fits, centred on a dark border. It counts
    real pixels, so it's sharp on a Retina screen too.
    - The text: "DROP YOUR / NES ROM / FILE HERE", the font at twice
      its size, centred on the TV.
    - The idle animation: the glow rises and falls every 4 seconds,
      the scanlines shimmer every 6 frames, and the light is off for
      the last 10 frames of each second.
    - A dropped file is only printed for now (step 2 recompiles it).
  - **`make app`, `make run-app`, `make test-app`;** `test-all`
    includes the app checks.
  - **`tests/check_app.py`** checks the app's own headless screenshots
    (`--screenshot F --frames N --size WxH`) against `app/art.h`. Its
    12 checks:
    - every pixel of the picture, except what is animated or covered by
      text;
    - the text pixel for pixel, and nothing else in its colour on the
      screen;
    - five window sizes: 2x and 3x exact fits, a border both ways, an
      odd size, and one smaller than the canvas (1x, cropped);
    - the glow, the shimmer and the blinking, and nothing else moving.
  - **Breaks, 12 tried, all caught.** One only after a fix: "the wall
    shimmers too" passed until a frame on the other half of the
    shimmer was added (all the frames looked at had fallen on the same
    half).
  - Not checked by the script: the real window. It opens, and it looked
    right when I opened it; you can resize it.

### 1b. The art round
Asked for after step 1: the look of the user's channel, Polygon
Legends, and a console that reads as an NES. Done in previews
(`build/app_art.png`, from the generator alone); the app picks the art
up when it's right.
- The room in the channel's colours: a blue-violet to magenta gradient,
  dithered in pixels, and a dark purple table.
- A console shaped like the NES: the two-tone grey box, the flap on
  top, the ridges and the black band on the right, the dark lower front
  with the power and reset buttons and a light, and the two controller
  ports. No Nintendo logo or name: those say it's Nintendo's product,
  and this is an unofficial tool.
- A pixel dragon in the style of the channel's logo: red, with a
  purple-blue mane and gold horns. Its head is drawn pixel by pixel (a
  grid in the generator) and its body as a coiling curve.
- The TV text in the logo's style: white with a dark outline.
- A sign on the wall: "NES RECOMP TOOL BY POLYGON LEGENDS".
- The TV stays as it is.
- Check: `make test-app` still passes; the checks learn the outline.

- Done (the user approved it, with the sign's wording changed):
  - **The wall:** the channel's gradient, dithered between five
    shades, from violet at the top left to magenta at the bottom right,
    above a dark purple table.
  - **The console:** in the NES's shape, with no logo or name. After
    the art round was committed, the user drew the version they wanted,
    and it now follows that drawing:
    - a light upper half with a large flap on the left, and no ridges;
    - the darker lower half with the light and the two buttons;
    - the black band on the right, the full height, with two seams;
    - the two controller ports side by side in it;
    - a narrow strip after the band, light above and dark below.
  - **The dragon:** drawn from shapes and outlined automatically
    (`Sprite` in the generator), in two goes:
    - The first was too small: the mane looked like a crown and the
      thin, many-spiked body like a centipede.
    - The second has a head 1.45 times bigger (angry yellow eyes,
      fangs, gold horns, a flaring blue and purple mane), a thicker
      shaded body with a gold belly, a few big spikes, and a spade tip
      on the tail.
  - **The sign:** "NES RECOMP / TOOL BY / POLYGON / LEGENDS" on the
    wall, outlined, in a neon frame. It first said only "POLYGON
    LEGENDS"; the user asked for the full wording.
  - **The TV text:** outlined like the logo's letters (the app draws
    the outline).
  - **Checks:** 13 now, with the outline. 14 breaks, all caught, after
    two fixes:
    - the outline check also looks for dark pixels beyond the outline
      (a 2-pixel outline passed at first);
    - two old breaks referred to colour names the new art renamed. They
      didn't compile, and the break script counted that as "caught".
      The script now reports a build failure as one, the same lesson
      as in the FDS stage.

### 2. The drop and the recompiling screen
- A file dropped on the window, or given on the command line, is
  checked: an iNES, NSF or FDS header. A wrong file gets a message on
  the TV, and the app waits for another.
- The recompiling screen: the TV shows "RECOMPILING IN PROGRESS", a
  loading bar and the stage name.
- The work runs beside the window, which stays responsive:
  - `recomp.py` then `cc`, the same commands as `make game`;
  - their output is collected, and stages are read from it;
  - errors are shown on the TV.
- Check:
  - a free ROM goes through every stage to a working binary;
  - a non-ROM file and an unsupported mapper show their messages;
  - screenshots of each screen;
  - break each part (a stage not reported, an error swallowed, a
    wrong file accepted).

- Done:
  - **`app/build.c`:** the build in five stages, the same steps as
    `make game`:
    1. checking the file's first bytes (iNES, NSF or FDS);
    2. `recomp.py`, with the ROM's `.missed` when there is one;
    3. `cc -c` of the game's C;
    4. the runtime's 15 files, each compiled on its own into
       `build/app-rt/`, and compiled again only when its source or any
       runtime header is newer;
    5. linking.

    The tools run through `posix_spawn` (no shell, so paths with
    spaces work), with their output in `build/NAME.log`. The name is
    the file's, with anything unusual made `_`. A failing tool stops
    the build, and its message is kept for the screen: the recompiler's
    last line, or the compiler's first "error:".
  - **The bar:**
    - each stage has a share of it: 2, 13, 45, 30 and 10%;
    - the runtime stage counts its files;
    - the other stages move by time against an estimate (the ROM's
      size, then the C file's at 100 KB a second), slowing as they get
      close to 95% of their share;
    - so the bar never claims a stage is done before it is, and only
      ever moves forward.
  - **The screens (`app/app.c`):**
    - recompiling: the file's name (cut to fit), "RECOMPILING / IN
      PROGRESS" in tall 1x2 letters, a pink bar, and the stage;
    - error: "CAN'T RECOMPILE", the message wrapped to 5 lines of 18,
      and "DROP ANOTHER FILE";
    - done: "DONE! BUILT AND READY".

    The build runs on its own thread, so the window stays responsive.
    The power light blinks fast while building, and drops are ignored
    until the build ends.
  - **Ways to run it:**
    - `nesrecomp-app ROM` opens the window and builds;
    - `--build ROM` builds with no window (`--trace-progress` uses the
      thread and prints the bar);
    - `--progress-model` prints the bar's arithmetic;
    - `--screenshot` takes `--show`, `--rom`, `--stage`, `--progress`
      and `--message`;
    - `--build-dir` sets where builds go;
    - the project is where `make app` ran, or `$NESRECOMP_ROOT`.
  - **The checks:** 39 now, the 14 of step 1 plus:
    - every build screen's text and bar, pixel for pixel, at 0, 13, 42,
      77 and 100%;
    - the error and done screens;
    - the bar's arithmetic;
    - a free test ROM built from a path with spaces: the stages in
      order, the bar moving forward and below 1 until done, 15 runtime
      files compiled, then 0 the second time, and the program passing
      the ROM's own test;
    - `.missed` reaching the recompiler;
    - a newer header recompiling the runtime;
    - and the three failures: a non-ROM, an unsupported mapper (a file
      made by the check), and a runtime file that doesn't compile (in a
      copy of the project).
  - **Breaks, 17 tried, all caught.** Two only after the arithmetic
    check was added: weights adding up to more than the bar, and a stage
    going past its share. A real build of a test ROM is too quick to
    show either.
  - Not checked by the script: dropping a file onto the real window. The
    window is open for you to try.

### 3. Playing the game
- When the build is done, the game starts in its own window, and the
  app's window gets out of the way.
- When the game quits, the app comes back to the drop screen.
- The `.missed` feedback works as with `make run`: the next drop of the
  same ROM rebuilds with it, so it gets faster as you play.
- The game's output is kept in a log, to look at if something goes
  wrong.
- Check: drop, build, play and quit with a free ROM, twice (the second
  time with `.missed`); a game that fails to start shows its message.

- Done:
  - **`app/play.c`** runs the built program on the ROM, through
    `posix_spawn`, with its output in `build/NAME.game.log`, and says
    how it ended:
    - well: exit 0, and no "stopped:" line;
    - the runtime's "stopped:" line (an unknown opcode, say);
    - a crash: the signal;
    - another exit status: that, with its last line;
    - or that it couldn't start.
  - **The window:** when a build is done, the game starts in its own
    window and the app hides, checking every 50 ms without drawing.
    - When the game ends well, the app comes back to the drop screen
      and to the front.
    - Otherwise it shows "THE GAME STOPPED" and why.
    - A "NOW PLAYING" screen exists for while it's hidden. Drops are
      ignored while a game plays.
  - **`.missed`:** the game writes it beside the ROM when it quits, as
    with `make run`, and the next build passes it to the recompiler. In
    the check, the second run interprets fewer spots than the first.
  - **For the checks:** `--build ROM --then-play [--play-args "..."]`
    and `--play-only EXE ROM`.
  - **The checks:** 47 now, the 39 before plus:
    - the stopped and playing screens;
    - build and play of a free test ROM: it ends well, and its test
      passes;
    - the `.missed` it writes, used by the next build, with less
      interpreted;
    - a ROM made to stop on an unknown opcode;
    - a "game" that crashes (SIGSEGV), one that exits 3, and one that
      doesn't exist.
  - **Breaks, 10 tried, all caught.** "Extra arguments dropped" was
    caught by the check's time limit: without `--headless`, the game
    opened a real window and ran until the check stopped waiting.
  - In the window, with `nes15` (free homebrew from the collection): the
    user built it, played it, quit, and the drop screen came back. The
    second time, the build used the `.missed` from the first, and the
    game ran with 0 spots interpreted.

### 3b. Polish
Asked for after step 3. Each item is checked by `make test-app` where a
script can see it, and tried in the window where it can't.
- **About screen, and the license.**
  - An `ABOUT` screen on the TV, reached with the I key and left with
    any key or a drop, saying: "NES RECOMP / For educational purposes
    only / by Serge and Claude / Free software under the MIT License".
  - A `LICENSE` file at the top of the project with the MIT License
    (copyright Serge and Claude), and a line in the README.
  - Step 4's app bundle puts the same words in the Mac menu's "About"
    box.
  - Check: the screen pixel for pixel; the key opens and closes it.
- **Skip unneeded rebuilds.** A ROM whose program is already built,
  from the same ROM, the same `.missed`, the same recompiler and the
  same runtime, starts at once, with no recompile.
  - A small record next to each build says what it was built from: the
    ROM's size and time, the `.missed` file's, `recomp.py`'s, and the
    newest runtime file's. When any of those differ, it is built again,
    as now.
  - The bar shows its stages as done, then the game opens.
  - Check:
    - built twice in a row, the second skips every stage;
    - after touching the ROM, the `.missed`, `recomp.py` or a runtime
      file, it builds again.
- **Click to open.** Clicking the TV opens the Mac's file picker (a
  standard "Choose a ROM" dialog); the file chosen is taken as if
  dropped. Cancelling changes nothing.
  - Check: in the window (a script can't click a Mac dialog); the
    clickable area is checked by its code.
- **Controls card.** Before a game starts, the TV shows the keys for a
  couple of seconds:
  - controller 1: arrows, X = A, Z = B, Return = Start, Right Shift =
    Select;
  - M = mute, R = reset, Esc = quit.

  Any key skips it, and the game then opens.
  - Check: the card pixel for pixel; it comes before the game and its
    time is skipped by a key.
- **Resizing the game's window.** The game's window can be resized like
  the app's, and keeps its picture sharp: the largest whole-number
  scale that fits, centred on black.
  - Cmd+= and Cmd+- grow and shrink it a step; Cmd+F switches full
    screen.
  - The app starts each game at the size used last, kept in
    `build/app-prefs.txt`; the runtime gets `--scale`, and a
    `--remember-size FILE` option to write the size back on exit.
  - Without the app, games behave as before (fixed size, `--scale`),
    except that dragging the window's edge works too.
  - Check:
    - the runtime's scaling of the picture into a window of several
      sizes (the same arithmetic as the app's, checked from its
      screenshot path);
    - `--remember-size` writes what the window was;
    - in the window, the keys and the dragging.
  - The ROM suite and nestest stay as they are, and all 319 earlier
    files give the same C (the runtime's window code isn't in the
    generated C).

- Done:
  - **About and the license.** I opens an About screen on the TV:
    "NES RECOMP" in tall letters, "For educational purposes only", "By
    Serge and Claude", "Free software under the MIT License". Any key,
    a click or a drop leaves it. A `LICENSE` file (MIT, 2026, Serge and
    Claude) is at the top of the project, and the README has a License
    section.
  - **Up to date.** After a build, `build/NAME.stamp` records:
    - the ROM's path, size and time (to the nanosecond);
    - the `.missed` file's size and time;
    - `recomp.py`'s time;
    - the newest runtime file's time.

    The next build of that ROM, if all of them match and the program is
    there, says "up to date" after checking the file and is done at
    once. A build that starts removes the record, so only a finished
    build is trusted.
  - **Click to open.** A click on the TV's screen opens the Mac's file
    dialog, through `osascript`, on a thread of its own so the window
    keeps drawing. The file chosen is taken as if dropped, and Cancel
    changes nothing. Mouse points are turned into window pixels (twice
    as many on a Retina screen) and then into the canvas, by the same
    layout as the drawing.
  - **The controls card.** Before each game the TV shows the keys for
    2.5 seconds (any key skips it), in two columns:
    - for a game: arrows, X, Z, Return, Right Shift, M, R, Esc;
    - for a music file (an NSF): Left, Right, R, M, Esc.
  - **The game's window.** It can now be resized, in the runtime (so
    `make run` gets it too):
    - SDL draws the picture at the largest whole-number scale that
      fits, centred on black;
    - Cmd+= and Cmd+- change the size by a whole step (up to what the
      screen holds), and Cmd+F switches full screen;
    - the Zapper and paddle read the mouse relative to the picture, not
      the window;
    - `--remember-size FILE` writes "game_scale N" on exit.

    The app keeps that in `build/app-prefs.txt` and starts the next
    game at that size with `--scale`.
  - **Checks:** 58 now. New ones:
    - the About screen and both cards, pixel for pixel;
    - the LICENSE file;
    - the click area's edges at four window sizes;
    - up to date when nothing changed (and the program not touched);
    - built again after a change to the ROM, a new `.missed`, a newer
      recompiler, or a deleted program;
    - the size remembered.

    Two checks needed fixing first, both test setups:
    - playing between two builds writes a `.missed`, so rebuilding there
      was right;
    - a header's time has to pass the newest runtime file's.
  - **Breaks, 12 tried, all caught.** At first every run seemed caught,
    because the break script's copy of the project had no `LICENSE`, so
    the checks crashed at that point. With the copy fixed and only real
    failures counted, "a missing program trusted" wasn't caught, and the
    deleted-program check was added. A missing LICENSE is now a failure,
    not a crash.
  - Games are unchanged: nestest exact, the suite 219 of 220 (test28 as
    always), all 319 earlier files give the same C.
  - In the window: the picker, the card and the resizing are for the
    user to try.

### 4. A double-clickable app and the README
- `make app-bundle` builds `build/nesrecomp.app`, a macOS app bundle
  with an icon (from the same art), which opens the window. It still
  uses the project folder for the recompiler and the compiler.
- README: the app, its screens, what it needs, and what it doesn't do
  yet.
- Check: it opens from Finder; dropping a ROM onto the app's icon in
  the Dock works too, if macOS passes it on.

- Done:
  - **`tools/make_app_bundle.py`** (`make app-bundle`) builds
    `build/nesrecomp.app`:
    - **`Info.plist`:** the name "NES RECOMP", identifier
      `local.nesrecomp` (no web domain claimed), version 1.0, and the
      About line "For educational purposes only. By Serge and Claude.
      Free software under the MIT License." It also declares that the
      app opens `.nes`, `.nsf` and `.fds` files, at "Alternate" rank so
      it doesn't take them over from other apps.
    - **`Credits.rtf`:** the About box's three lines.
    - **The icon:** the TV and the console from the art, five icon
      pixels to an art pixel, on the wall's gradient in a rounded
      square, at every size `iconutil` wants. The first try showed the
      tip of the dragon's tail in the crop, so the icon takes only the
      TV's and console's rectangles.
    - **The program and its signature:** the program is copied in, and
      the whole bundle gets an ad-hoc signature.
  - **Opened from Finder or the Dock,** an app starts in `/` with a bare
    PATH. Every file is already given by its full path, and the app now
    adds `/opt/homebrew/bin` and `/usr/local/bin` to PATH, so the build
    finds the same `python3` as Terminal. On this Mac `/usr/bin/python3`
    exists too, so the PATH line can't be shown to matter here; it's
    for Macs where Python comes only from Homebrew.
  - **The SDL menu's "About NES RECOMP"** shows the Mac's standard About
    box from the plist and `Credits.rtf`.
  - **`tests/check_app_bundle.py`** (`make test-app-bundle`, not in
    `test-all`, since it shows a window), 11 checks:
    - the plist's values, that it opens the three file types, and that
      it's valid;
    - the credits;
    - a 1024-pixel image in the icon;
    - the program, the same code as `build/nesrecomp-app`;
    - the signature;
    - opening a ROM with it as Finder does (`open -a`): it starts, the
      file reaches it, it builds it and plays it (a ROM made by the
      check that stops at once), and it quits when asked.

    Comparing the program needed care: signing rewrites its signature
    and one byte of its header, so the check compares the code
    (`otool -tX`).
  - **Breaks, 9 tried, all caught.** Two lessons from the break script:
    - "quit ignored" left its app running. SDL turns a terminate signal
      into a quit request, which that break ignored. The next break's
      `open` then went to the leftover app and passed. The script now
      force-quits, and that break was run again on its own.
    - "a different program" first copied a system program, which broke
      the bundle generator instead. It now compiles a small program.
  - **README:** "The app" section (how to build it, the screens, what
    it needs), the status list, the plan list.
  - Not checked by a script: dragging a ROM onto the Dock icon (`open
    -a` sends the same "open this file" request, which works), and the
    About box itself on screen.

## Not in this version
- A self-contained app that runs without the project folder, Python and
  a compiler.
- A library of built games, settings, and key remapping.
- Windows and Linux builds; it's written so they could follow, with SDL.

## Risks
- **Art is taste.** The first drawing is a starting point, and step 1
  ends with screenshots to adjust from.
- **Compile time varies,** so the bar moves through the compile stage
  by an estimate. It never claims to be done before it is, and waits at
  the end of that stage if the compiler is slow.
- **macOS and dropped files:** dropping onto the window works through
  SDL. Dropping onto the Dock icon needs the app bundle (step 4); if SDL
  doesn't pass that on, it's written down and left for later.
