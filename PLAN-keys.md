# Plan: an ALL KEYS page

Goal: every key and button the game answers to, on one page you can
open at any time, so nobody has to catch them on the cards that flash
by before a game. Your idea (2026-11-22, in `PLAN-library.md`).

Today the keys are in three places, none complete:
- the app's two cards before a game (2.5 seconds each, any key skips
  them): the game's keys, then save, rewind and the pads. The first
  card has no room for P (a picture), so P is on neither;
- the README's tables;
- the pause menu's KEYBOARD 1, KEYBOARD 2 and PADS pages, which show the
  NES buttons' keys (as changed), but not the window's own keys (M, R,
  V, P, Cmd+S, ...).

Like the pause menu, the page is in the game program (`runtime/`), so
it's the same on Mac and Windows, from the app and from `make run`.

At every step:
- `make test-all` must not get worse (230 of 231, test28 the known
  failure), and nestest stays exact;
- the generated C doesn't change: `make test-same-c`;
- deliberate breaks in scratch copies, counting only real FAIL lines;
- pictures of each new page sent early;
- the Windows run checked at the start of each step;
- the terminal says what happens ("frame N: ALL KEYS 1/2").

## Decisions for you (my recommendation first)

1. **Its name in the menu.** **ALL KEYS** (recommended). "KEYS" alone
   is too close to KEYBOARD 1 and 2 (where keys are changed), and
   "HELP" says less about what's there.
2. **Where it is.** **A line in the pause menu, ALL KEYS, between
   CONTROLLERS and QUIT** (recommended), and **K on the app's drop
   screen shows the two cards again**, with no game started (also
   recommended: cheap, and it's where a new player looks first). The
   other choice: the menu page only.
3. **Which keys it shows.** **The keys as they are now** (recommended):
   if you moved A to K on KEYBOARD 1, the page says K. The other
   choice: the usual keys always, which would be wrong after a change.
4. **How it fits.** **Two pages in the big box** (the button test's,
   17 lines of 37 letters), **Left and Right flip between them**
   (recommended): 1/2 THE GAME (keyboard players 1 and 2, the pads), 2/2
   THE WINDOW (menu, sound, reset, record, picture, save and load,
   slots, rewind, fast-forward, the window's size, full screen, a disk's
   side). The other choice: one tightly packed page, in two columns of
   short names.
5. **The cards.** **The first card's ESC line becomes "ESC  MENU+KEYS"**,
   pointing at the page, **and the second card's last line "P
   PICTURE"** in place of "MENU KEYS+PADS" (recommended), so P is on a
   card at last and the cards say where the rest is. The other choice:
   leave the cards as they are.

## The hard part, and the answer

**The keys' names.** SDL names keys in words ("Right Shift", "Return",
"Keypad Enter", "Backspace"), the menu's font is capitals, and a line
has 37 letters. The page uses short names where they're long (R.SHIFT,
RETURN, BKSPACE) and the keyboard's own label where it differs (the
Mac's Backspace key says DELETE; Cmd on the Mac, Ctrl on Windows), as
the second card does now. Any other key: SDL's name in capitals, cut to
fit. One function makes these names, for this page and for the
KEYBOARD pages, so they agree.

**Staying true.** The window's keys are answered in `video_sdl.c`; the
page lists them from one table in the runtime. A check reads both and
fails if a key the window answers to isn't on the page (or the page
names one it doesn't answer to). Another compares the README's key
tables and the app's cards with the same list, so a key added later
can't be left out of one of them.

**The game stays frozen.** The page is part of the menu, which runs no
game code (`PLAN-pause.md`), so opening it changes nothing: the frames
after it closes are the same as if it was never opened.

## What it looks like

A sketch (step 1 sends real pictures before the look is settled):

    ALL KEYS 1/2: THE GAME             ALL KEYS 2/2: THE WINDOW
     KEYBOARD 1      KEYBOARD 2         ESC        MENU
      D-PAD ARROWS    D-PAD W A S D     M          SOUND ON/OFF
      A     X         A     G           R          RESET
      B     Z         B     F           V          RECORD A MOVIE
      START RETURN    START E           P          SAVE A PICTURE
      SELECT R.SHIFT  SELECT Q          CMD+S / L  SAVE / LOAD
     PADS                               CMD+1-4    PICK A SLOT
      A BOTTOM  B RIGHT  START START    DELETE     REWIND (HELD)
      SEL+ST HELD: MENU                 `          FAST X4 (HELD)
      LB REWIND  RB FAST X4             CMD+= / -  WINDOW SIZE
                                        CMD+F      FULL SCREEN
                                        0-9        DISK SIDE (FDS)
     < > THE OTHER PAGE   ESC BACK

## How it's tested

- **Pictures.** As `tests/check_menu.py` does for the CONTROLLERS pages:
  the menu opened by an input script, moved to ALL KEYS, both pages
  photographed and compared pixel by pixel with the text each should
  show, for the Mac and for Windows (`--pairing-for` already picks the
  system; it would pick the key names too), and once with an unusual
  `controls.txt`, whose moved keys must show.
- **The game frozen.** The game's frames after the page closes, the same
  as a run that never opened the menu.
- **Staying true.** The check above: the window's keys in
  `video_sdl.c`, the page's table, the README's tables and the app's
  cards, all naming the same keys.
- **The app.** `make test-app`: K on the drop screen shows the first
  card, then the second, pixel for pixel; the cards' new lines.
- **The Windows run.** The pictures saved as a download (as the
  Controllers pages are), and the checks run there.

## Steps

### 1. The ALL KEYS page
- ALL KEYS in the pause menu (the box a line taller again, as for
  CONTROLLERS); its two pages in the big box; Left and Right flip; Esc,
  Z, B or Home go back; the keys as they are now; Mac and Windows names.
- One function for keys' short names, used here and by the KEYBOARD
  pages.
- `tests/check_menu.py`: both pages, both systems, an unusual
  `controls.txt`; the frames unchanged; the terminal's lines.
- Pictures sent early.
- Breaks: a moved key shown as the usual one; CMD on the Windows page;
  page 2 unreachable; a key the window answers to left off the page;
  the game running a frame while the page is open.

**Where step 1 ended (2026-11-22).** The five decisions as recommended.
- The pause menu has ALL KEYS between CONTROLLERS and QUIT: 10 lines,
  the box 13 pixels taller and 7 higher (`MENU_BOX_Y` 36, `MENU_BOX_H`
  166, the title at 46, the first line at 64).
- Its two pages in the button test's bigger box. 1/2 THE GAME: KEYBOARD
  1 and KEYBOARD 2 side by side (UP, DOWN, LEFT, RIGHT, A, B, START,
  SELECT, each with its key now), then PADS (each NES button's pad
  button now, two to a line), then "SELECT+START HELD, OR HOME: MENU"
  and "LB: REWIND   RB: FAST X4". 2/2 THE WINDOW: 14 lines from one
  table in `menu.c` (ESC, M, R, V, P, Cmd+S, Cmd+L, Cmd+1-4, Delete,
  the key left of 1, Cmd+= / -, Cmd+F, 1-9, 0), with the Mac's names or
  Windows' (Ctrl, Bkspace) by the system it's built for, or
  `--pairing-for`. Left, Right or OK flip; Esc, Z, a pad's B or Home go
  back to the menu, ALL KEYS still picked. The terminal: "frame N: ALL
  KEYS 1/2".
- Two changes from the plan: the short names (R.SHIFT, BKSPACE, KP
  ENTER, L.STICK IN, "BOTTOM" for BOTTOM BUTTON, at most 12 letters)
  are made by a step on top of the KEYBOARD pages' own name function,
  and only ALL KEYS uses them: the KEYBOARD pages have room for SDL's
  full names, and their checks and terminal lines use them. And the
  fast-forward key is "LEFT OF 1" (as the README says it), as the
  menu's font has no backquote (adding one would change the font the
  app's art shares).
- Pictures sent: the menu, page 1, page 2 on a Mac and on Windows.

The checks (`tests/check_menu.py`, 7 more on each of its two games):
page 1 and 2 pixel by pixel, flipped with OK, Right and Left; leave
back to the menu with ALL KEYS picked; the terminal's lines; the game's
frames the same as a plain run; page 2 with the Mac's and Windows'
names; page 1 with a `controls.txt` moving keyboard 1's A to K and the
pads' A to the top button, and Z going back. The expected text is
written in the check, not read from `menu.c`. The checks that reach
CONTROLLERS by going up from RESUME now go up three lines (past QUIT
and ALL KEYS), here and in `tests/menu_pictures.py`.

- `make test-all`: 230 of 231 as before (test28), nestest exact, 240 of
  240 with the menu; the same C.

Breaks, each in a scratch copy (`tests/check_menu.py`, FAIL lines over
both games):

| broken | FAIL lines |
| --- | --- |
| a moved key shown as the usual one (A as X) | 2 |
| CMD on the Windows page | 2 |
| page 2 unreachable (the flip does nothing) | 8 |
| P left off the window's keys | 6 |
| the menu closing (the game running) as the page opens | 12 |

Not checked by a test: the window's keys and a real pad reaching the
page (headless has neither); the page in a live window is for you.

### 2. The app, the cards, the README
- K on the drop screen shows the two cards again (decision 2); the
  cards' new lines (decision 5).
- The "staying true" check (the window's keys, the page, the README,
  the cards).
- README: the page, K, the cards; both READ ME FIRSTs; the Windows run's
  pictures (`tests/menu_pictures.py` gains the two pages).
- Breaks: the README's table missing a key; a card without its new
  line; K showing only the first card.

**Where step 2 ended (2026-11-22).**
- The app: K on the drop screen shows the two cards again (2.5 seconds
  each, any key for the next), then the drop screen; no game starts.
  Esc there goes back instead of quitting; a drop meanwhile builds as
  usual. The cards' timing is one function (`cards_over`), for a game's
  cards and K's, and `--card-test [FRAME ...]` steps it frame by frame
  (a key at each frame given). The terminal: "cards: the keys again
  (K)", "cards: back to the drop screen".
- The cards: the first's last line is "ESC  MENU+KEYS", the second's
  "P  PICTURE" (in place of "MENU  KEYS+PADS"), so P is on a card.
- `tests/check_keys.py` (new, `make test-keys` in `make test-all`, and
  the Windows run): knows each of the window's 14 keys (its names in
  `video_sdl.c`, on the page, in the README, on a card); every key
  `video_sdl.c` names must be one of them or one of the menu's own
  moves, and each must still be there; the page must list exactly
  them, in order, with Windows' names; the README must mention each;
  the cards must have the 10 that belong on one, on both systems.
- README: the pause menu's sketch (it had neither CONTROLLERS nor ALL
  KEYS), ALL KEYS, K and the cards' lines, the checks, the plans' list.
  Both READ ME FIRSTs: ALL KEYS in the pause menu, K on the drop screen;
  their checks look for both. `tests/menu_pictures.py` also takes both
  ALL KEYS pages (11 pictures), so the Windows run's download has them.

The checks:
- `tests/check_app.py`: K's cards (`--card-test`), card 1 then card 2
  then the drop screen at frames 0, 150, 300, and with keys at 40 and
  90; both cards pixel by pixel with their new lines.
- `make test-keys`: 7 checks, all pass.
- `make test-release`: the Mac READ ME FIRST with ALL KEYS and K, lines
  of 72 or fewer (a line was 73 at first, and rewrapped).
- `tests/menu_pictures.py`: 11 of 11, for the Mac and for Windows.

- `make test-all`: 230 of 231 as before (test28), nestest exact, 240 of
  240; the same C.

Breaks, each in a scratch copy:

| broken | caught by |
| --- | --- |
| the README's table without P | `check_keys.py`, 1 FAIL |
| CMD+F left off the page | `check_keys.py`, 1 |
| a new key (Q) answered but on no list | `check_keys.py`, 1 |
| the second card without P | `check_keys.py` 2, `check_app.py` 1 |
| K showing only the first card | `check_app.py`, 2 |

Not checked by a test: K pressed in a live window (the window's keys),
and Esc on K's cards going back.

## Where the stage ended (2026-11-22)

ALL KEYS is in the pause menu, and the app's K shows the cards again: 2
steps, 10 breaks (5 and 5), all caught; `make test-all` 230 of 231
(test28 as before) and the same C throughout. Step 1: 9367c76.
Not tried live: the page from a real keyboard and pad, and K in the app.

Each step ends with "Where step N ended" here, its checks and its
breaks table.

## Not in this plan
- Changing the window's own keys (M, R, V, P, Cmd+S, ...): they stay
  fixed, as `PLAN-controllers.md` decided, so a remap can never lock you
  out of the menu.
- A page of the app's own keys (I, H, C, the shelf's arrows, Delete):
  the README has them; the drop screen could show them later.
- Translating the page into other languages.

## Risks
- **The menu's box grows again** (11 lines). If it gets too tall, ALL
  KEYS can be the first line of the CONTROLLERS page instead; the
  pictures in step 1 will show.
- **Key names on other keyboards** (a French or German layout) may be
  long or unusual; they're cut to fit, and the page still says which
  key it is in SDL's words.
- **The page and the window drifting apart** later: the "staying true"
  check is there for that.
