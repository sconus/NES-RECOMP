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

### 4. A double-clickable app and the README
- `make app-bundle` builds `build/nesrecomp.app`, a macOS app bundle
  with an icon (from the same art), which opens the window. It still
  uses the project folder for the recompiler and the compiler.
- README: the app, its screens, what it needs, and what it doesn't do
  yet.
- Check: it opens from Finder; dropping a ROM onto the app's icon in
  the Dock works too, if macOS passes it on.

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
