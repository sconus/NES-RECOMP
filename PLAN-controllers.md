# Plan: a Controllers screen

Goal: one place for everything about controllers, reached from the pause
menu with the keyboard or a pad. Three things:
- **Pairing help**: how to pair an Xbox, PlayStation or Switch pad with
  this computer (macOS or Windows settings). The app doesn't pair
  anything itself; it tells you which buttons to hold and where to click.
- **A button test**: press a button and see it light up on a drawing of
  a pad, under the controller's slot (1 to 4) and its name, so you know
  which pad is which player.
- **Remapping**: choose which key or which pad button is A, B, Select,
  Start and the D-pad, remembered for the next game.

Like the pause menu, all of it is in the game program (`runtime/`), so
it's the same on Mac and Windows, from the app and from `make run`.

At every step:
- `make test-all` must not get worse, and nestest stays exact;
- the generated C doesn't change (runtime work only): `make test-same-c`;
- deliberate breaks in scratch copies, counting only real FAIL lines;
- pictures of each new page early (sent to you), as it's visual work;
- the Windows run checked at the start of the next step;
- the terminal says what happens ("frame N: CONTROLLERS", "controller 2:
  A pressed", "keyboard 1: A is now K"), so a live try can be checked
  from the log.

## Decisions for you (my recommendation first)

1. **Where it lives.** In the pause menu only (recommended): a new
   CONTROLLERS line opens its own page. The game's window already reads
   the pads, it works from the sofa, and it's the same everywhere. The
   other choice: also a screen in the app before a game (say, K on the
   drop screen), which means teaching the app to read pads too (today
   only the game does); a bigger job for the same pages.
2. **One pad layout, or one per pad.** One layout for every pad
   (recommended): SDL already lines up Xbox, PlayStation and Switch pads
   by position, so "the bottom button is B" means the same on all of
   them. The other choices: a layout per brand (Xbox / PlayStation /
   Switch), or per slot (1-4). Both are more to show and test, for a
   need that's rare on an NES game.
3. **What can be remapped.** The eight NES buttons only (recommended),
   for keyboard player 1, keyboard player 2, and the pads. The menu's
   own ways in (Esc, Select+Start held, Home) and the shoulders (rewind,
   fast-forward) stay fixed, so a bad remap can never lock you out of
   the menu. Keys the window already uses (Esc, M, R, V, P, 0-9,
   Backspace, `, and Cmd/Ctrl keys) can't be chosen; choosing a key that
   another button has swaps the two.
4. **Where it's remembered.** A `controls.txt` that the app keeps in its
   build folder, next to `app-prefs.txt`, handed to the game with
   `--controls FILE` (recommended): the same way the window size and
   volume work now, and the tests can point it at a scratch file.
   `make run` uses `build/controls.txt`. The other choice: the system's
   per-user settings folder, so it follows you everywhere, but then
   every test must be careful not to touch your real one.
5. **Leaving the button test.** Esc, Home, or holding Select+Start for
   half a second (recommended): every other button is being tested, so
   pressing B mustn't leave. The page says so at the bottom.

## The hard part, and the answer

**Changing controls mustn't change the game.** The remap only changes
what the window reads (`video_buttons`, `gamepad_buttons`); input
scripts set the NES buttons directly, so every test, state and recording
plays exactly as before. A check runs the whole suite with an odd
`controls.txt` and expects the same fingerprints.

**"Press the button for A" while the pad also drives the menu.** When a
line is waiting for a button, the next fresh press (made after it
started waiting) is the answer, whatever it is, and the menu doesn't
move. Esc on the keyboard, or 5 seconds of nothing, cancels and keeps
the old one. Buttons already held when it starts waiting don't count, as
in the menu now.

**The menu is a loop that runs no game code** (PLAN-pause.md), so new
pages are just more of that loop: the button test reads the pads every
60th of a second while the game stays frozen. The pads' raw state and
names come from `gamepad.c` (new: what each slot holds, its name and
brand from SDL, every button including the shoulders and Home).

**Which pad is which.** Besides the slot number on screen, SDL can set a
pad's own player lights (PlayStation and Switch pads have them; Xbox
pads don't): each pad shows its slot.

**Space.** The pause menu's box fits eight lines; a ninth (CONTROLLERS)
makes it a line taller. The pages use a bigger box (about 38 characters
wide in the 5x7 font) so the pairing text fits.

## What it looks like

A sketch (the first step shows you real pictures before the look is
settled):

        PAUSED                      CONTROLLERS

      > RESUME                    > BUTTON TEST
        ...                         KEYBOARD 1
        WINDOW < 3X >               KEYBOARD 2
        CONTROLLERS                 PADS
        QUIT                        PAIRING HELP
                                    BACK

    BUTTON TEST
     1 XBOX WIRELESS      2 DUALSENSE
       [pad drawing]        [pad drawing]
     3 -                  4 -
     KEYBOARD 1  [pad]    KEYBOARD 2  [pad]
     ESC OR HOLD SELECT+START TO LEAVE

    KEYBOARD 1                    PAIRING HELP (MAC)
      UP     UP ARROW               XBOX
      DOWN   DOWN ARROW             PLAYSTATION
      ...                           SWITCH PRO
      A      X                      ALREADY PAIRED TO A CONSOLE?
      B      Z                      BACK
      DEFAULTS
      BACK

Each pairing page is a short list of steps, for example (Mac, Xbox):
turn the pad on with the Xbox button; hold the small pair button on its
top edge until the logo flashes fast; System Settings > Bluetooth, click
Connect next to "Xbox Wireless Controller". Windows' pages say Settings
> Bluetooth & devices > Add device > Bluetooth. PlayStation: hold Create
(PS5) or Share (PS4) with the PS button until the light bar flashes.
Switch Pro: hold the small sync button on top. Each step is checked
against the makers' and Apple's / Microsoft's own help pages before it
goes in, and the Xbox one is tried by you live.

## How it's tested

- **Pictures.** As `tests/check_menu.py` does now: the menu opened by an
  input-script line, moved to CONTROLLERS and each page, `shot=FILE`,
  compared pixel by pixel with the text each page should show. The
  pairing pages for Mac and for Windows (a test option picks which).
- **The button test.** A new script word plugs in one of SDL's virtual
  controllers (as `--test-gamepads` already does, no hardware needed)
  and holds its buttons, so the page can be photographed with A lit on
  controller 2, and nothing lit on 1, 3 and 4.
- **Remapping.** A self-test (`--test-controls`, in `make test` and the
  Windows run) with a pretend keyboard and virtual pads: a remapped key
  presses the new NES button and the old key no longer does; a reserved
  key is refused; a clash swaps; a cancel keeps the old one; DEFAULTS
  brings back today's layout. `controls.txt` written and read back; a
  missing, older or garbled file gives today's layout, not a crash.
- **Nothing changes the game.** The suite with an odd `controls.txt`:
  the same frames as without (`tests/check_states.py`'s way), and the
  same C.
- **Live, with your Xbox pad:** the pairing steps as written, the right
  slot lighting up, a remap kept after quitting and starting again.

## Steps

### 1. The CONTROLLERS page and the button test
- CONTROLLERS in the pause menu (the box a line taller); its page with
  BUTTON TEST, PAIRING HELP and BACK (the remap lines come in steps 3
  and 4).
- `gamepad.c`: what each slot holds (name, brand, every button); the
  pads' own player lights set to their slot.
- The button test page: four slots and the two keyboard players, each a
  small pad that lights up; leaving as decided.
- The script word for virtual pads; the pictures check.
- Pictures sent early.
- Breaks: a press shown on the wrong slot; a button that doesn't light;
  B leaving the test page; the game running while the page is open.

**Where step 1 ended (2026-11-22).** The five decisions as recommended.
- The menu has CONTROLLERS above QUIT (9 lines; the box is a line taller
  and moved up 7 pixels). Its page, in the same box: BUTTON TEST, BACK,
  then what each slot holds ("2 XBOX WIRELESS CONTROLLER", or "3 -").
  PAIRING HELP joins the page in step 2, so there's no empty line now.
- The button test: a bigger box with six small pads (controllers 1-4,
  then keyboard players 1 and 2), each labelled with its slot and brand
  (XBOX, PS5, SWITCH PRO, ... or SDL's name). The D-pad, Select, Start,
  B, A, both shoulders and Home light green as they're held; a slot with
  nothing in it says NO CONTROLLER. No button moves or chooses there:
  only Esc, Home, or Select+Start held 0.5 s go back to CONTROLLERS (the
  page says so). The terminal names each fresh press ("controller 2: A",
  "keyboard 1: LEFT"); buttons already held as it opens don't count.
- Esc in the menu is now "leave" (back a page, or closes the menu from
  its first page, as before); Z and a pad's B go back a page.
- `gamepad.c`: what each slot holds (`gamepad_info`); each pad's own
  player lights set to its slot (PlayStation and Switch pads).
- Input scripts: `leave` (as Esc), and `pad=2:a+start` holds buttons
  on a virtual controller in slot 2, plugged in if need be (`pad=2:none`
  lets go). A menu line may hold 32 words (it was 16, and more were
  dropped without a word; now it says so and stops).

The checks:
- `tests/check_menu.py`, 6 more on each of its two games: the
  CONTROLLERS page with a virtual controller in slot 2, pixel by pixel;
  the button test with A, Start and LB lit; OK, back and the arrows
  leaving it as it was; leave going back to CONTROLLERS; the terminal's
  presses (B pressed while A, held as it opened, isn't named); and the
  game's frames the same as a run that never opened the menu. All pass.
- `--test-gamepads`: on the button test, B, A, Start and a held D-pad
  ask for nothing; Home asks to leave; Select+Start leaves after 0.5 s,
  not before, and not again while held on; `gamepad_info` gives the
  virtual controller's buttons, shoulders and name; the `pad=` words.
- `make test-all` as before (230 of 231, nestest exact, 240 of 240 with
  the menu); the same C.

Breaks, each in a scratch copy:

| broken | FAIL lines |
| --- | --- |
| a press shown on the wrong slot | 6 |
| A doesn't light | 6 |
| back (Z) leaves the button test | 6 |
| a pad's B leaves the button test | 1 |
| Select+Start leaves the test at once | 2 (after fixing the test: at first it only looked at the last frame of the hold, 1) |
| a button held as the test opens counts as a press | 2 (after fixing the test: 0 before, as nothing looked while A was still held) |
| the game runs a frame while the test is open | 8 |

Not checked by a test, only in a live window: the keyboard's two pads
lighting up (headless has no keyboard), a real pad's name and brand, its
player lights, and the window's Esc and Home reaching the test page.
Tried live on the Mac with an Xbox pad (2026-11-22): it works.

### 2. Pairing help
- One page per brand, with the steps for the system it's built for (Mac
  or Windows), plus "already paired to a console?" (pairing to the
  computer means pairing back to the console later).
- Each step checked against the official help pages; the README gets
  the same steps.
- The pictures check, Mac and Windows pages. Break: the Windows text on
  a Mac build.

**Where step 2 ended (2026-11-22).**
- CONTROLLERS now has BUTTON TEST, PAIRING HELP, BACK (the slot list
  moved down a line). PAIRING HELP (MAC), or (WINDOWS), lists XBOX,
  PLAYSTATION, SWITCH PRO, ON A CONSOLE TOO? and BACK; each opens a page
  of steps in the button test's bigger box (up to 17 lines of 37
  characters). OK, B, Esc or Home on a page go back to the list. The
  terminal names each page ("frame N: XBOX ON A MAC").
- The steps were checked against: Apple's Xbox and PlayStation pages
  (support.apple.com 111101, 111100) and its "Connect a Bluetooth
  device with your Mac"; Xbox Support's "How do I connect my Xbox
  controller to PC?" (Windows 11 and 10 paths, USB, re-syncing to the
  console, Series X|S double press); PlayStation's DualSense and
  DualShock 4 pages (Create/Share + PS, back to the console with a USB
  cable); Nintendo's "How to Pair the Nintendo Switch Pro Controller"
  (SYNC held a second or more; back on the Switch). Nintendo covers only
  its consoles and Apple lists no Switch pads, so the Switch Pro page
  says its steps aren't official.
- `--pairing-for mac|windows` picks the other system's pages, for the
  tests; without it, the one it was built for.
- README.md: "Pairing a controller", with the same steps, and the
  option.

The checks (`tests/check_menu.py`), on each of its two games: the list
and all four pages pixel by pixel for the Mac, for Windows, and with no
option (the system it runs on); the terminal's page names for each; the
game's frames the same as a plain run. Once: all seven pages fit the
box. All pass; `make test-all` as before, the same C.

Breaks, each in a scratch copy:

| broken | FAIL lines |
| --- | --- |
| the Windows text on a Mac build | 4 |
| PLAYSTATION shows the Switch page | 8 |
| Esc on a page of steps does nothing | 12 |
| a line too long for the box | 5 |
| BACK on the list goes to the game's menu | 6 |
| a page drawn a line lower | 6 |

Not checked by a test: the steps themselves on a real pad (the Xbox
ones are for you to try live), and the Windows pages on a real Windows
build (step 5 adds the menu check to the Windows run).

### 3. Remapping the keyboard
- KEYBOARD 1 and KEYBOARD 2 pages: each of the eight buttons with its
  key; OK on a line waits for a key (cancel with Esc or after 5 s);
  reserved keys refused, clashes swapped; DEFAULTS.
- `--controls FILE`: read at the start, written when a key changes; the
  app passes it; `make run` uses `build/controls.txt`.
- `--test-controls`; the "nothing changes the game" check.
- Breaks: the old key still pressing the button; a reserved key
  accepted; the file not written, or a garbled one crashing.

**Where step 3 ended (2026-11-22).**
- CONTROLLERS now lists BUTTON TEST, KEYBOARD 1, KEYBOARD 2, PAIRING
  HELP, BACK. A KEYBOARD page shows the eight buttons with their keys,
  DEFAULTS and BACK, and a line saying what happened. OK on a button
  waits ("..."): the next key is the answer, Esc or 5 seconds with none
  keeps the old one, and a key the window keeps (Esc, M, R, V, P, 0-9,
  Backspace, the fast-forward key, Cmd, Ctrl) is refused and it waits
  on. A key another button has, either player's, swaps the two.
  DEFAULTS brings back that player's usual keys, and the other player's
  where one clashed. While it waits the pads only cancel (Home, or
  Select+Start held), as on the button test.
- `runtime/controls.c`: the two players' keys (it replaces the table in
  `video_sdl.c`), refusals, swaps, `controls.txt` (a "version 1" line,
  then "keyboard1 a X" lines, keys as SDL names them); a missing, older
  or garbled file gives the usual keys and says why in the terminal.
- `--controls FILE`; the app passes its build folder's `controls.txt`
  (beside `app-prefs.txt`), `make run` passes `build/controls.txt`.
- The terminal: "keyboard 1: press a key for A", "keyboard 1: A is now
  K", "... (swapped: keyboard 2 UP is now X)", "M is the window's", "A
  kept as X (no key in 5 seconds)", "the usual keys".
- Input scripts: `key=k` (a key, as `key=right_shift`) and `wait=300`
  (60ths with nothing pressed). A menu line may now hold 64 words, as
  many as the menu queues (33 were needed for the checks).
- README: the keys table points at the KEYBOARD pages; "Changing the
  keys"; `--controls` and the new checks.

The checks:
- `--test-controls` (in `make test`, and in the Windows run through
  `tests/run_nestest.py`): a pretend keyboard; K pressing A and X no
  longer; ten window keys refused; a clash swapped across players; the
  file read back; DEFAULTS, and the other player's clashing key back;
  eleven bad files (older, no version, a missing key, player 3, an
  unknown button or key, Esc, a key twice, a key still the other
  player's, binary, empty) giving the usual keys; two-word key names.
- `tests/check_menu.py`, 6 more on each game: the KEYBOARD pages pixel
  by pixel (open, waiting, refused, swapped, Esc, still waiting at 299
  60ths, given up at 300, keyboard 2); the terminal's lines; the file as
  changed; a run with the changed file playing the same frames, the
  file untouched; DEFAULTS; a garbled file.
- `tests/check_states.py`: every game's menu run reads an unusual
  `controls.txt` (every key moved): 240 of 240 the same frames, and the
  file left as it was.
- `tests/check_app.py`: the app gives the game `--controls` with its
  build folder's `controls.txt` (`--game-args`, for the test).
- `make test-all`: 230 of 231 as before (test28), nestest exact; the
  same C. The 64-word change came after that run (it's only the menu
  lines' parsing); the menu checks were run again with it.

Breaks, each in a scratch copy (FAIL lines in the self-test, and in the
menu checks):

| broken | self-test | menu |
| --- | --- | --- |
| the old key still presses the button | 2 | 0 (headless reads no keyboard) |
| M (the window's) accepted | 4 | 6 |
| the file not written | 1 | 4 |
| a garbled key name taken as it is | 4 | 0 |
| a clash not swapped (two buttons, one key) | 3 | 6 |
| DEFAULTS leaves the other player's clashing key | 1 | 2 |
| the wait ends a 60th early | 0 | 2 |
| Esc while waiting taken as the answer | 0 | 4 |

(The first count of these showed 6 menu FAILs for every break: the
checks' own menu line had grown to 33 words, over the limit of 32, so
it never ran. That's what the 64 is for; the table is after it.)

Not checked by a test: real keys in a window (headless has no
keyboard): that a remapped key plays, the Esc and pad cancels, and the
file kept after quitting and starting again.

### 4. Remapping the pads
- The PADS page: the same, for one layout every pad uses (as decided);
  waiting for a pad button, not a key.
- Breaks: the remap applied to only one slot; a button held when the
  wait started taken as the answer; Select+Start held to open the menu
  stopping working after a remap of Select or Start.

**Where step 4 ended (2026-11-22).**
- CONTROLLERS now lists BUTTON TEST, KEYBOARD 1, KEYBOARD 2, PADS,
  PAIRING HELP, BACK (the slots' list below moved down 7 pixels and
  closer, to fit). PADS is the KEYBOARD page for the pads' one layout:
  each NES button with its pad button by position (BOTTOM BUTTON, RIGHT
  BUTTON, LEFT, TOP, SELECT, START, D-PAD UP ... RIGHT, LEFT and RIGHT
  STICK IN), DEFAULTS and BACK. OK waits for a pad button on any pad:
  the next fresh press is the answer (one held as it started doesn't
  count); Esc, Home or 5 seconds keep the old one; a shoulder (or
  another button not every pad has) is refused and it waits on; a
  button another NES button has swaps the two.
- The layout is for every pad. The left stick is always the D-pad's
  directions. Select+Start held for the menu, and the menu's moves,
  follow the layout (they read NES buttons), so they're always on some
  button; Home and the shoulders never move. The button test lights
  the NES button each pad button is now.
- `controls.txt` is now "version 2", with "pad a bottom" lines after
  the keys; a version 1 file (step 3's) is still read, with the usual
  pad. A pad line in a version 1 file, an unknown or fixed button
  (Home, a shoulder), or one used twice: the usual keys and pad.
- The terminal: "pads: press a button for A", "pads: A is now BOTTOM
  BUTTON (swapped: B is now RIGHT BUTTON)", "pads: RIGHT SHOULDER stays
  as it is", "pads: A kept as BOTTOM BUTTON (no button in 5 seconds)",
  "pads: the usual buttons".
- Input scripts' `pad=` words gained x, y, ls, rs (the left and top
  face buttons, the sticks pressed in); they name places on the pad,
  whatever the layout.
- README: "Changing the pad buttons", with a table of what each name is
  on Xbox, PlayStation and Switch Pro; `--controls`; the checks.

The checks:
- `--test-controls`: the usual pad; A to the top button, then to the
  bottom one swapping with B; Home, both shoulders, Share, a paddle,
  the touch pad and two nonsense numbers refused; the file read back;
  keyboard DEFAULTS leaving the pad and the pad's DEFAULTS; seven bad
  pad files; a version 1 file giving the usual pad.
- `--test-gamepads`, with virtual pads: the layout on controllers 1 and
  2; the stick still the D-pad; Select moved to the left button, then
  that and Start held 0.5 s opening the menu (on 1 and on 2) and the
  old Select and Start not; the moved A choosing in the menu; the wait
  ignoring a button held as it started, and Home; a press on another
  pad answering; the answer held on not also choosing in the menu.
- `tests/check_menu.py`, 8 more on each game: the PADS page pixel by
  pixel (open, waiting, a held button not taken, a shoulder refused,
  swapped, Esc, 5 seconds), the button test lighting by the new layout,
  the terminal's lines, the file as changed and read back by a new run,
  DEFAULTS, a file giving A the Home button, the game's frames
  unchanged.
- `tests/check_states.py`: the unusual `controls.txt` now moves every
  pad button too: 240 of 240 the same frames, the file untouched.
- `make test-all`: 230 of 231 as before (test28), nestest exact; the
  same C.

Breaks, each in a scratch copy (FAIL lines in the two self-tests, and
in the menu checks):

| broken | self-tests | menu |
| --- | --- | --- |
| the layout applied to controller 1 only | 2 | 0 (headless checks one pad) |
| a button held as the wait started taken as the answer | 1 | 4 |
| Select+Start stays on the old buttons after a remap | 3 | 0 |
| Home taken as the answer | 1 | 0 |
| the answer, held on, also chooses in the menu | 1 | 0 |
| a shoulder accepted | 2 | 6 |
| a pad clash not swapped | 3 | 4 |
| the file's pad lines not used | 3 | 2 |
| the pad's change not written | 2 | 2 |
| PADS DEFAULTS does nothing | 2 | 2 |

(The file's pad lines were at first caught only by the self-test: the
menu check of the file read back by a new run was added for it.)

Not checked by a test: a real pad (headless only has virtual ones):
your Xbox pad's buttons answering the page, Home cancelling, and the
layout kept after quitting and starting again.

### 5. The app, Windows, the README
- The app's SAVE AND REWIND card (or CONTROLS) mentions the
  CONTROLLERS page; the checks join the Windows run (the Windows
  pairing pages pictured there); the README gets the page, the pairing
  steps and `--controls`; the releases' READ ME FIRST says where to find
  it.

**Where step 5 ended (2026-11-22).**
- The app: the SAVE AND REWIND card (after a game's keys) has a ninth
  line, "MENU  KEYS+PADS", saying where the keys and pad buttons
  change. (CONTROLLERS itself is 11 letters; the card's column holds 9.)
- Both releases' READ ME FIRST, under USING IT: the pause menu's
  CONTROLLERS page (a button test, KEYBOARD 1 and 2, PADS, kept for the
  next game, and how to pair an Xbox, PlayStation or Switch Pro pad
  with your Mac / PC). Their checks look for it.
- README: the app's "Then the keys" names the card's new line; the
  tests section says how to get the pictures. (The page, the pairing
  steps, `--controls` and the checks went in with steps 2 to 4.)
- The Windows run: `tests/check_menu.py` there already checks every
  CONTROLLERS page, Windows' pairing help without `--pairing-for`
  included, and `tests/run_nestest.py` the two self-tests; new, it
  saves pictures of every page as Windows draws them
  (`tests/menu_pictures.py`) and keeps them as a download on the run's
  page ("controllers-pages-windows"), and one more Windows break: the
  Mac's pairing help shown on Windows.

The checks:
- `make test-app`: the card with its new line, pixel by pixel.
- `make test-release`: the Mac zip's READ ME FIRST names the
  CONTROLLERS page, PADS and pairing.
- `tests/menu_pictures.py`, for the Mac and for Windows' pairing help:
  9 of 9 pictures each.
- No runtime change since step 4's `make test-all` (the C, the game
  and the menu are as then); the menu checks pass.
- Not run here: the Windows checks (the read-me's points, the new
  break, the pictures): they run on the next push.

Breaks, each in a scratch copy:

| broken | caught by |
| --- | --- |
| the card without its new line | `make test-app`, 1 FAIL |
| the Mac READ ME FIRST without the CONTROLLERS page | `make test-release`, 1 FAIL |
| the pairing help for the other system by default (the Mac's side of the Windows break) | `make test-menu`, 4 FAILs |

## Not in this plan
- Pairing from inside the app (it's the system's job).
- Swapping which pad is player 1 or 2 (today: the order they connect).
- Turbo buttons, and remapping the menu's own buttons and the
  shoulders.
- A screen in the app for all this, unless you choose it (decision 1).

## Risks
- **Pairing steps go out of date** when Apple, Microsoft or the makers
  change their settings. They're kept short, and the README says where
  the official pages are.
- **A pad SDL doesn't know** shows as "UNKNOWN PAD" in the test and may
  not light every button; it still plays with the default layout if SDL
  can read it.
- **The Home button** may be taken by the system (Game Center, Game Bar,
  Steam), as in the pause menu: then it just doesn't light in the test.
