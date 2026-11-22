# Plan: the game library (the shelf)

Goal: the app's drop screen becomes a cosy living room, and the shelf
under the TV is your library. Every game you've built gets a box on the
shelf showing its own title screen; click a box (or pick it with the
arrows and press Enter) and the game plays, with no rebuild when nothing
changed. Dropping a ROM on the TV still builds it, and then it joins the
shelf.

The look is your reference picture itself, `design/library-reference.jpg`
(a painting at 1408x768), shrunk to 640x360 (your choice, 2026-11-22):
- the TV in the middle with "DRAG NES ROM HERE TO RECOMPILE" and a small
  cartridge with an arrow, the TV stand with a generic grey console and
  two controllers, the warm lamp on the left, the purple and blue
  evening light, the plants, the rug, the armchair, the picture on the
  wall;
- the Polygon Legends dragon sitting on the right of the shelf with the
  glowing cyan sword;
- two rows of game boxes, coloured by each game's title screen;
- pages, not scrolling.

All of it is the app (`app/`, `tools/make_app_art.py`), plus one small
runtime addition: the game takes its own title picture. Same on Mac and
Windows.

At every step:
- `make test-all` must not get worse (230 of 231, test28 the known
  failure), and nestest stays exact;
- the generated C doesn't change: `make test-same-c` (this stage
  touches only the app and the runtime);
- deliberate breaks in scratch copies, counting only real FAIL lines;
- 640x360 pictures sent early and often (visual work);
- the Windows run checked at the start of each step;
- the terminal says what happens ("shelf: 18 games, page 1 of 1",
  "shelf: play TETRIS_LIKE", "title: saved at frame 412 (Start)"), so a
  live try can be checked from the log.

## Already decided (2026-11-19)

- **Canvas 640x360**, twice today's 320x180: whole-number scales to
  1280x720 (x2), 1920x1080 (x3), 3840x2160 (x6), so pixels stay square.
- **The reference picture itself** as the room (your choice on
  2026-11-22; until then it was to be redrawn as pixel art, and step 1
  first did that): `tools/make_app_art.py` shrinks it, clears its
  painted boxes, and leaves the TV's glass to the app.
- **Original art only**: no real box art, no Nintendo name or logo; a
  generic grey console of the era; the boxes' sticker and little label
  are our own shapes.
- **Each box shows the game's auto-captured title screen, tinted by its
  main colour.**
- **Pages, not scrolling.**
- **The dragon with a cyan sword on the right.**

## Decisions for you (my recommendation first)

1. **How big the boxes are.** At 640x360 the shelf's two rows leave
   each box about 36x52 pixels, so the picture in its window is only
   about 30x28: you'd see the title screen's colours and big shapes,
   not its words. My recommendation: **keep the reference's 16 boxes a
   row (32 a page), and the TV shows the pointed-at game big**: its
   title screen on the TV's screen and its name under it, while the
   mouse is over a box or the arrows have picked it. The other choice:
   bigger boxes, 8 a row (16 a page), with a picture about 60x55, but
   then the shelf no longer looks like the reference.
2. **When the title picture is taken.** My recommendation: **the frame
   just before you first press Start** in a game (that's almost always
   the title screen), taken by the game itself the first time you play
   it. If Start isn't pressed in the first 30 seconds, the screen at 10
   seconds (or the first one after it that isn't a single colour). The
   other choice: the app runs the game alone after building it, for a
   set time, and takes that frame; quicker to have, but many games show
   a logo or a demo at any fixed time.
3. **The box's colour.** My recommendation: **the title screen's most
   common colour that isn't black, white or grey, snapped to one of 12
   box colours** taken from the reference (red, green, olive, blue-grey,
   blue, navy, gold, purple, orange, dark grey, ...), so the shelf looks
   like the reference and the labels stay readable. A screen with no
   colour at all gets dark grey. The other choice: the exact colour,
   which can give muddy or neon boxes.
4. **Where the ROM is.** A built game needs its ROM to play, and the
   build is tied to the ROM's place (today's `NAME.stamp`). My
   recommendation: **the shelf remembers where the ROM is**; if it's
   been moved or deleted, its box is dimmed, the TV says "ROM NOT FOUND:
   DROP IT AGAIN", and dropping it (from anywhere) puts the box back.
   Saves stay where they are now (beside the ROM). The other choice: the
   app keeps its own copy of every ROM in its folder, so boxes never go
   missing, but saves would move away from where they are today.
5. **The shelf's order.** My recommendation: **last played first**, so
   page 1 is what you play now; a new game goes first. The other
   choices: A to Z, or the order they were added.
6. **Removing a box.** My recommendation: **Delete (or Backspace) on a
   picked box**, then the TV asks "REMOVE FROM SHELF? Y / N". It removes
   the box and the built program, never the ROM, its saves or save
   states. A game that fails to build doesn't join the shelf (the TV
   shows why, as now).
(7 and 8 no longer apply: the picture has its own painting on the wall
and its own dragon.)
7. **The sign.** Today's neon "NES RECOMP / TOOL BY / POLYGON LEGENDS"
   sign isn't in the reference. My recommendation: **the picture on the
   wall becomes that sign**, small, top right; the About screen (I)
   still says it all.
8. **The dragon's look.** You offered the original vector logo as a
   sharp reference for the head and colours: if you send it (put it in
   `design/`), step 2 follows it; otherwise I follow the reference and
   today's dragon.

## The hard part, and the answer

**Taking the title picture must not change the game.** It only reads
the finished frame (the same pixels `--screenshot` saves), never the
game's memory or timing. A check runs every suite game with and without
it and expects the same fingerprints (`tests/check_states.py`'s way), and
the same C.

**A good picture, not a black one.** Many games start on a black screen
or a logo. "The frame before the first Start press" skips all that,
because you press Start on the title. The fallback (10 seconds, then the
first frame that isn't one colour, up to 30 seconds) covers games you
never press Start in. Input scripts press Start in the tests, so the
rule is checked with free test ROMs and the project's generated ones.
NSF music files get a box of their own, drawn with a music note, as they
have no title screen.

**Everything moves to 640x360.** Every screen today (drop, recompiling,
errors, About, the cards, under the hood, the compiler screen) is drawn
on the TV at 320x180. In the reference the TV's screen is about the same
size in pixels as today's (about 125x86 at 640x360), so the TV's text
keeps its size and the room grows around it. The screens move to the new
TV's place; `tests/check_app.py` reads the sizes from `app/art.h`, so
most of its checks follow, and its pictures get the new room. The code
view already uses a 640x360 canvas.

**Playing from a box goes the usual way.** A click calls the same path
as a drop (`take()` with the remembered ROM): the build's stamp says
it's up to date, so it skips straight to the keys card and the game. If
the app or the runtime changed since, it rebuilds, as it does now. No
second way to start a game.

**The shelf is a small text file**, `library.txt` in the build folder
(beside `app-prefs.txt`): a "version 1" line, then one game a line (its
name, its ROM's path, when last played). A missing or garbled file gives
an empty shelf and says why in the terminal, never a crash. On the first
start of the new app, the shelf is filled from games already built
(their `NAME.stamp` holds the ROM's path); their pictures come the next
time each is played.

**The picture file.** The game writes `NAME.title` in the build folder:
a short header and the 256x240 frame as plain colours (the app has no
PNG reader, and this needs none). The app shrinks it for the box
(averaging, so shapes survive) and shows it at about 1:2 on the TV.
The app passes `--title-out` only while the game has no picture yet.

## What it looks like

A sketch at 640x360 (step 1 shows real pictures before the look is
settled):

    +--------------------------------------------------------------+
    | curtain   plant        +-----------------+   [sign]          |
    |                        |   cartridge v   |        armchair   |
    |                        |  DRAG NES ROM   |                   |
    |   lamp                 |  HERE TO        |    dragon  plant  |
    |                        |  RECOMPILE      |    + sword        |
    |   rug    [pad] [ console ] [pad]                             |
    |==============================================================|
    | [][][][][][][][]   [][][][][][][][]       < PAGE 1/2 >       |
    |==============================================================|
    | [][][][][][][][]   [][][][][][][][]                          |
    +--------------------------------------------------------------+

The keys on the shelf screen: the arrows move between boxes (and flip
the page at the ends), Page Up / Page Down flip pages, Enter plays, Delete
removes, I and H as now, a drop or a click on the TV builds a new ROM.
The mouse: pointing at a box shows it on the TV; a click plays; clicks on
the shelf's page arrows flip pages.

## How it's tested

- **Pictures.** `tests/check_app.py` as now: the app's own screenshots
  (`--screenshot`, no window), compared pixel by pixel against
  `app/art.h`, now at 640x360, at several window sizes. New: `--show
  shelf` with a test library and test title files (`--library FILE`),
  so the shelf is pictured empty, half full, full, on page 2, with a box
  picked (and the TV showing it), with a missing ROM, and asking to
  remove.
- **The title picture.** A new `tests/check_titles.py`: suite games run
  headless with an input script pressing Start at a known frame; the
  `NAME.title` written must equal the `--screenshot` of the frame
  before; with no Start, the 10-second rule and the not-one-colour rule;
  no file written when `--title-out` isn't given; a game's fingerprints
  the same with and without it, for all 240.
- **The colour.** A self-test (`--test-shelf`): made-up pictures (all
  black, black with a red logo, a blue sky, grey only) giving the
  expected box colours; the averaging shrink on a known pattern.
- **The shelf file.** `--test-shelf` again: written and read back; last
  played first; removing; a missing ROM; filling from old builds' stamps;
  a missing, older or garbled file giving an empty shelf, not a crash.
- **Playing from a box.** `check_app.py` builds a free test ROM, then
  "clicks" its box (`--click-test shelf ...` with the test library): it
  plays without compiling anything again, and the shelf's order changes.
- **Live, by you:** the room and the dragon on your screen, dropping a
  ROM, clicking a box, flipping pages, a missing ROM coming back.

## Steps

### 1. The living room at 640x360
- `tools/make_app_art.py` at 640x360: the walls in the evening light,
  the curtain, the lamp with its warm glow, the plants, the rug, the
  armchair, the wall sign (decision 7), the TV on its stand with the
  console and two controllers, and the empty shelf's two rows (no boxes
  yet). The dragon's place is kept for step 2.
- "DRAG NES ROM HERE TO RECOMPILE" with the little cartridge and arrow
  on the TV.
- Every existing screen moved to the new TV; the window opens at 2x
  (1280x720), its smallest size 640x360; the click area follows the TV.
- `tests/check_app.py` updated for the new size and room.
- Pictures sent early, several rounds as you comment.
- Breaks: a screen drawn a pixel off the TV; the click area left where
  the old TV was; the canvas scaled by a non-whole number at 1920x1080;
  the idle glow touching a pixel outside the screen.

**Where step 1 ended (2026-11-22).** Decisions 1-8 as recommended ("Yes,
do step 1"); no vector logo yet.
- `tools/make_app_art.py` draws the room at 640x360: the wall dithered
  from blue at the left to purple, the curtain, a plant on the floor and
  its shadow on the wall, the floorboards and a patterned rug, the
  armchair, the framed sign (NES RECOMP, POLYGON LEGENDS), the shelf's
  top with the lamp (its warm light on the wall, floor, curtain and
  shelf) and a plant, the shelf's front with two rows on each side
  (empty), and the TV stand with the TV on it and the console between
  two pads inside. The dragon's place, left of the right-hand plant, is
  empty until step 2.
- The TV's screen keeps its size (116x86), now at (262, 40), so every
  screen (recompiling, errors, done, About, the cards, under the hood,
  the compiler screen) draws as before, on the new TV. The drop screen:
  a little cartridge with an arrow (`art_cart` in `app/art.h`), then
  "DRAG NES ROM / HERE TO / RECOMPILE" at twice the font's height.
- The window opens at 1280x720 (2x), or 640x360 if that doesn't fit the
  screen; its smallest size is 640x360. The terminal says "window:
  1280x720 (2x the 640x360 room)". The code view keeps its own 640x360
  canvas (it was "twice the art").
- The app's icon is cut from the first room (the TV and the console):
  that room is kept as `draw_icon()` with its own colours, so the icon
  is byte for byte the same as before (its 1024-pixel picture compared).

The checks:
- `tests/check_app.py`: the room pixel for pixel; the new words and their
  outline; the cartridge pixel for pixel, on the screen, above the
  words; the window at 640x360, 1280x720 (2x), 1920x1080 (3x), 1000x620,
  1500x900, 961x1080 and 333x200 (smaller than the room: 1x, cropped);
  the click area at 1280x720, 1920x1080, 1000x620, 640x360; every other
  screen as before. All pass.
- `make test-app-bundle`: the icon with NES RECOMP on its TV. Passes.
- `make test-all`: 230 of 231 (test28), nestest exact, 240 of 240 with
  states, rewind, fast-forward and the menu; `make test-same-c`: the
  same C.

Breaks, each in a scratch copy (`tests/check_app.py`):

| broken | FAIL lines |
| --- | --- |
| the cartridge (and words) a pixel lower | 3 |
| RECOMPILING a pixel left | 5 |
| the click area where the old TV was | 2 |
| the room stretched to the window, not whole steps | 4 (not at 1280x720 or 1920x1080, where stretching is whole steps) |
| the idle glow also changing the TV's wood | 2 |

Not checked by a test: the window's opening size (it needs a real
screen; it opened at 1280x720 here), and how the room looks to you.

**Then, the picture itself (2026-11-22).** You chose your reference
picture as the room, with placeholders of my own for the shelf.
- `tools/make_app_art.py` reads `design/library-reference.jpg` (macOS's
  `sips` turns it into a PNG), takes its 16:9 middle (columns 21-1386)
  and shrinks it to 640x360, each pixel the average of the area it
  covers. The hand-drawn room of the first try is gone (the icon's
  first room, `draw_icon()`, stays).
- The painted boxes are cleared: in each half-row, every line takes the
  colour of the shelf's back from the gaps between the boxes. In their
  32 places (`art_slot_x`, `art_slot_y`, 30x47 each, in `app/art.h` for
  step 4) a **placeholder**: the faint outline of a box in the shelf's
  own shadows, with its window, label and sticker, as if one had stood
  there.
- The TV's glass (found from the picture: the pixels joined to its
  middle that are brighter than its dark rim, then everything inside
  their outline) is the app's screen: its two animated colours, a
  mid-blue from the picture's glass, scanlines, and a dark rim. The
  picture's own words and cartridge on it are gone; the app draws its
  own. The screens' text area (116x86) is centred on the glass at
  (253, 43). The TV's little red light, at (394, 35), blinks as before.
- The picture has about 135,000 colours at 640x360; it keeps 1,000
  (median cut), after the app's named ones, so `art_pixels` is now
  16-bit.
- The About screen's last line, "SUPPORT IT: PRESS D", moved up 3
  pixels: its outline crossed the glass's curved corner.

The checks (`tests/check_app.py`, new):
- the glass solid, with nothing of the picture left on it; the text
  area's middle line and column on the glass; the light there and off
  the glass; the shelf's places, 2 rows of 8 a side, apart, below the TV;
- for 12 screens (recompiling, errors, done, the compiler's two,
  About, the three cards, under the hood, playing, stopped): the room
  untouched outside the glass. This found the About line.
- All earlier checks pass; the icon is as before.

Breaks, each in a scratch copy (`tests/check_app.py`; `make test-all`
230 of 231 as before, the same C, the icon the same):

| broken | FAIL lines |
| --- | --- |
| the glass not filled (the picture's words left on it) | 15 |
| the TV's light left out | 1 |
| the About line back where it crossed the glass's corner | 2 |
| the text area 13 pixels left, off the glass | 12 |
| the shelf's places too close (overlapping) | 1 |

Not checked by a test: that the placeholders look right to you.

### 2. The sword's glow (or skip)
- The dragon is in the picture now. What's left, if you want it: the
  sword's cyan glow pulsing gently, like the TV's (the app changing its
  cyan colours). Otherwise this step is skipped.
- Breaks: the pulse touching pixels outside the sword.

**Where step 2 ended (2026-11-22).** You chose to do it.
- `tools/make_app_art.py` finds the blade in the picture: the bright
  cyan pixels in a box beside the dragon (x 448-499, y 100-163; the
  hilt's guard, below, is left out). It writes `art_glow` in
  `app/art.h`: every pixel within 4 of the blade, with how much light
  it gets (all of it on the blade, fading to about a tenth 4 pixels
  off).
- The app adds a cyan light (at most 40, 120, 112 to red, green and
  blue, capped at 255) to those pixels, rising and falling every 3
  seconds (180 frames): none at frame 0, so the room is exactly as
  drawn, brightest at frame 90. So the blade brightens and a soft glow
  spreads onto the floor and the dragon's paw. It runs on every screen
  that shows the room, like the TV's glow.
- Pictures sent: the glow at frames 0, 45 and 90, and the room at its
  brightest.

The checks (`tests/check_app.py`):
- "nothing else moves" now leaves out the glow's pixels; new: at frame
  90 every blade pixel is the picture plus the whole light, capped;
  at frame 180 the glow is gone again; more than half the pixels around
  the blade are lit at frame 90; the glow is by the dragon, off the TV
  and the shelf. (The first try of the blade check, "more cyan than
  red", failed on a correct glow: the blade's green and blue are capped
  at 255 first. It now checks the exact sums.)

- `make test-all`: 230 of 231 as before (test28), nestest exact, 240 of
  240; the same C; the app bundle and its icon as before.

Breaks, each in a scratch copy (`tests/check_app.py`):

| broken | FAIL lines |
| --- | --- |
| the light also put 6 pixels to the right | 15 |
| lit at frame 0 (the pulse starting halfway) | 15 |
| every 4 seconds, not 3 | 2 |
| on the blade only, nothing around it | 1 |

Not checked by a test: how strong the glow looks to you.

Also in this step, the Windows runs' failures (read from their logs):
- **Run 52** (Controllers step 5) failed in its breaks step: the copy
  with no break failed `tests/check_menu.py` (58 FAIL lines, "no
  picture"), so its own break was "caught" for the wrong reason; the
  30 real breaks were caught. The cause: the breaks' scratch copies are
  in a folder named "nesrecomp break ...", and the check put the full
  path of each picture in an input script's `shot=` word, where words
  are split at spaces. It now gives those paths from the project folder,
  where the game runs. On the Mac, in a copy under a folder with a
  space: 58 FAIL lines before, none after; the matching break (the
  Windows pairing help on a Mac) caught there with 4.
- **Runs 53 and 54** (step 1) stopped before building: "zlib's checksum
  is wrong". zlib.net handed GitHub's machine something other than
  zlib 1.3.1 (the Mac gets the right file). The workflow now takes the
  same file (byte for byte, checked) from zlib's own release on GitHub,
  then zlib.net's, and says what it got if neither matches. This is
  first tried by the next Windows run.

### 3. The game takes its title picture
- Runtime: `--title-out FILE`: the frame before the first Start press
  (from a key, a pad, or an input script), else the 10-second rule;
  written once, then it stops looking. Prints "title: saved at frame N
  (Start)" or "(10 seconds)".
- The app passes it while `NAME.title` is missing.
- `tests/check_titles.py`; the fingerprints check over the suite; the
  same C.
- Breaks: the picture taken a frame late (the frame of the press); a
  black first frame accepted by the fallback; the file written again on
  every run; the game's frames changed by the capture.

**Where step 3 ended (2026-11-22).**
- `runtime/title.c` (new): with `--title-out FILE`, each frame it is
  given the picture and whether Start is among the buttons for the
  next frame (any of the four controllers, from keys, pads or a
  script). The first fresh press keeps that picture: the one on screen
  as Start was pressed. A picture 99% or more one colour doesn't
  count (a press on a black screen waits for the next). With no press
  by frame 1800 (30 seconds) it keeps frame 600's picture (10
  seconds), or the first after it that isn't one colour; if the game
  ends first (quit, window closed, a test finished), that one at the
  end. Written once, then it stops looking. "title: saved at frame N
  (Start)", "(10 seconds)", or "title: none (...)". A music file (NSF)
  keeps none, and says so.
- The file: "NRTITLE1", 256 and 240 (2 bytes each), then the picture
  as RGB, 184,332 bytes in all.
- The app gives the game `--title-out` with `NAME.title` in its build
  folder, only while that file isn't there.
- `--test-title DIR`: the runtime's self-test of the rules, in `make
  test` and the Windows run (`tests/run_nestest.py`).

The checks:
- `--test-title`, 14: a press on a one-colour screen waits; a press on
  a picture keeps it, and never again after; no Start: nothing until
  30 seconds, then the picture of 10 seconds; one colour at 10 seconds
  (99.5%): the first picture after; Start at 1000 wins; Start after 30
  seconds doesn't; ending at 20 seconds keeps the 10-second picture,
  at 5 seconds none; one colour for 30 seconds: none; 98% one colour
  is a picture; without `--title-out` nothing.
- `tests/check_titles.py` (new, `make test-titles` in `make test-all`,
  and the Windows run), on mmc3_split.nes, 240pee.nes and
  fds_demo.fds: Start pressed by a script at a frame gives exactly that
  frame's picture, as `--screenshot` saves it; no Start, frame 600's;
  the terminal's lines; nothing without `--title-out`; none for an NSF.
- `tests/check_states.py`: every game's fast-forward run also takes a
  title: 240 of 240 the same frames as without; 29 of them got far
  enough to keep one (the others are shorter than 10 seconds and press
  no Start).
- `tests/check_app.py`: the app asks for `game.title` while it's
  missing, not once it's there.
- `make test-all`: 230 of 231 as before (test28), nestest exact; the
  same C.

Breaks, each in a scratch copy:

| broken | caught by |
| --- | --- |
| the picture taken a frame late (the frame after the press) | `check_titles.py`, 5 FAIL lines (240pee's picture is the same a frame later: caught by the terminal's frame number) |
| a black screen accepted at 10 seconds | `--test-title`, 1 |
| the picture written again and again | `--test-title`, 2 |
| the app asking for a picture when there's one | `check_app.py`, 1 |
| a music file given a picture | `check_titles.py`, 1 |
| the capture taking the Start press away from the game | `check_states.py`, 4 (the games whose scripts press Start) |

Not checked by a test: a real window, keys and pads (headless has
none), and quitting a game early from the window. The rules are the
same code as in the self-test.

### 4. The shelf
- `library.txt` (written after each build and each game, read at the
  start; filled from older builds the first time); the boxes, 16 a row,
  two rows a page, each with its shrunk picture and its colour
  (decisions 1 and 3); a box with no picture yet shows a blank screen in
  dark grey; NSF boxes with a note.
- Picking with the arrows and the mouse, the TV showing the picked game,
  pages with "< PAGE 1/2 >", Enter or a click plays it through `take()`.
- Last played first (decision 5). An empty shelf (before the first game)
  is just the empty wood, with the TV's usual message.
- `--library FILE` and `--show shelf` for the pictures; `--test-shelf`.
- Pictures sent early.
- Breaks: the colour taken from black; a click playing the box next to
  it; page 2 showing page 1's boxes; a box's picture shrunk by skipping
  pixels instead of averaging; a played game not moving to the front;
  a garbled `library.txt` crashing.

### 5. Missing ROMs and removing
- A box whose ROM is gone: dimmed, "ROM NOT FOUND: DROP IT AGAIN" on the
  TV when picked; dropping a file of the same name puts it back
  (decision 4).
- Delete or Backspace: "REMOVE FROM SHELF? Y / N"; Y removes the box and
  the built program, keeps the ROM, saves and states (decision 6).
- A failed build never joins the shelf.
- Pictures; `--test-shelf` and `check_app.py` cases.
- Breaks: a missing ROM's box still trying to play; removing deleting
  the save; N removing anyway; a failed build added.

### 6. Windows, the README, the READ ME FIRSTs
- `check_titles.py` and the shelf's checks join the Windows run (paths
  with backslashes, `NAME.exe`); a picture of the shelf as Windows draws
  it kept as a download on the run's page, as the controllers' pages
  are.
- README: the shelf, its keys, `library.txt`, `--title-out`, the checks;
  both releases' READ ME FIRST say how the shelf works.
- Breaks: the Mac's paths in `library.txt` on Windows; the READ ME
  without the shelf.

Each step ends with "Where step N ended" here, its checks and its breaks
table, as in `PLAN-controllers.md`.

## Not in this plan
- The pause menu and the Controllers screen in the room's style (they
  belong to the game's window, not the app's).
- Choosing the shelf with a pad from the sofa (the app doesn't read pads;
  only the game does). A later stage if you want it.
- Retaking a game's picture by hand, box art you supply, sorting and
  searching, more than one shelf.
- A 2.1 release: your call, as before, after a green Windows run.

## Risks
- **The room needs the picture to be made again.**
  `design/library-reference.jpg` must be in the project (and in git, if
  anyone else is to run `tools/make_app_art.py`); `app/art.h`, made
  from it, is what the app is built from.
- **Small pictures.** A box is 30x47, its window about 20x16: colours,
  not words; the TV preview is what makes games recognisable
  (decision 1).
- **A bad title picture** for a game that waits on another button, or
  shows a demo first; it's still a picture of the game. Retaking by hand
  is for later.
- **Games built before this version** have no picture until played
  once, and their box is grey until then.
- **Every app picture changes,** so `check_app.py`'s pictures all get
  redone in step 1; the breaks show it still catches what it did.
- **Windows runs 50-52** (Controllers steps 3-5) were still "running"
  at the start of this stage, as runs 41 and 42 once were: look at them
  before the first commit here.
