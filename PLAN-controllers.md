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

### 4. Remapping the pads
- The PADS page: the same, for one layout every pad uses (as decided);
  waiting for a pad button, not a key.
- Breaks: the remap applied to only one slot; a button held when the
  wait started taken as the answer; Select+Start held to open the menu
  stopping working after a remap of Select or Start.

### 5. The app, Windows, the README
- The app's SAVE AND REWIND card (or CONTROLS) mentions the
  CONTROLLERS page; the checks join the Windows run (the Windows
  pairing pages pictured there); the README gets the page, the pairing
  steps and `--controls`; the releases' READ ME FIRST says where to find
  it.

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
