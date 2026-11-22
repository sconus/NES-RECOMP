# Plan: a pause menu

Goal: one place, in the game's window, for everything that isn't
playing: carry on, save and load states (and pick the slot), reset,
sound, the window's size, quit. It works with the keyboard and with a
game controller, so someone on the sofa with a pad never needs the
keyboard. All of it is in the game program (`runtime/`), so it is the
same on Mac and Windows, from the app and from `make run`.

At every step:
- `make test-all` must not get worse (it now includes the state tests),
  and nestest stays exact;
- the generated C doesn't change (runtime work only): `make test-same-c`;
- deliberate breaks in scratch copies, counting only real FAIL lines;
- pictures of the menu early (sent to you), as it's visual work;
- the Windows run checked at the start of the next step.

## Decisions for you (my recommendation first)

1. **Which key opens it.** Esc (recommended). Today Esc quits at once,
   which is easy to hit by accident and loses the game; with the menu,
   Esc opens it, QUIT is its last item, and closing the window (and
   Cmd+Q on a Mac) still quits straight away. The other choice: keep Esc
   for quit and open the menu with another key (Tab is the Zapper's
   now, so it would be something like F1).
2. **Which controller button opens it.** Holding Select and Start
   together for half a second (recommended): every controller has
   them, and a short press of both still reaches the game (some games
   use Select+Start). The Home / Guide button would be nicer, but the
   system often takes it first (macOS's Game Center overlay, Windows'
   Game Bar, Steam), so it's added only where SDL sees it, as a second
   way.
3. **Rewind and fast-forward on a controller.** Hold the left shoulder
   button (LB / L1 / L) to rewind and the right one to fast-forward
   (recommended): the NES pad has no shoulder buttons, so nothing a game
   uses is taken. Save and load go through the menu.

## The hard part, and the answer

Pausing must not change the game. The window hands the runtime a
finished frame in `frame_done()`, which the PPU calls in the middle of
catching up, often mid-instruction. The game's state is whatever it is
at that moment, and nothing changes it as long as no more 6502 code
runs. So the menu is a loop inside `frame_done()`: while it is open,
it draws the menu over the last picture, reads the keys, and waits for
the next 60th of a second, and the game isn't touched. Closing it
returns from `frame_done()` and the game carries on from exactly where
it was, as if that frame had taken longer.

The menu's actions that do change the game don't happen inside the
menu: SAVE, LOAD and RESET only ask (the same requests as Cmd+S,
Cmd+L and R), close the menu, and happen at the next instruction
boundary, exactly as the keys already do. So they need no new safe
point, and they're tested by the same tests.

While the menu is open: the sound stops (the audio device is paused,
so no click and no old sound when it closes), rewind keeps no frames,
a recording records no frames (the movie runs on game time), and the
picture behind the menu is the last frame, darkened.

## What it looks like

Drawn by the runtime in the NES picture (256x240), in its 5x7 font,
over the darkened game, so it scales with the window like the game
does. A sketch:

        PAUSED

      > RESUME
        SAVE STATE
        LOAD STATE
        SLOT  < 2 >     21 NOV 09:14
        RESET
        SOUND < ON >
        WINDOW < 3X >
        QUIT

The slot line says what the slot holds: EMPTY, or the day and time it
was saved (the file's date). Up and down move, left and right change
a setting, Return / A chooses, Esc / B / the open button again closes.
The first step shows you real pictures before the look is settled.

## How it's tested

- **Pictures.** `--screenshot` with the menu open (a new input-script
  word opens it and moves the cursor), compared pixel by pixel with the
  text the menu should show, as `tests/check_app.py` checks the app's
  cards.
- **Pausing changes nothing.** A run that opens the menu, waits in it,
  moves around and closes it must give the same fingerprint for every
  frame (picture, RAM, sound, code counts: `--prints-out`) as a run
  that never opens it. Over the suite's games, as fast-forward was
  checked.
- **The menu's actions.** SAVE then LOAD from the menu must give the
  same frames as Cmd+S and Cmd+L (the state test, driven through the
  menu); RESET as R; SLOT writes `.state2` when 2 is picked.
- **Controllers.** SDL's virtual game controllers (as `--test-gamepads`
  already does): holding Select+Start opens the menu, a short press
  doesn't; the D-pad and A/B drive it; the shoulders rewind and
  fast-forward.

## Steps

### 1. The menu, with the keyboard
- Esc opens and closes it (if you choose that); the loop in
  `frame_done()`; the audio paused.
- Items: RESUME, SAVE STATE, LOAD STATE, SLOT (with what it holds),
  RESET, QUIT.
- The input-script words, the pictures check, the "pausing changes
  nothing" check, SAVE/LOAD/RESET through the menu.
- Pictures of the menu sent early.
- Breaks: a frame run while the menu is open; SAVE done inside the
  menu (mid-instruction) instead of asked for; the slot shown not the
  slot used; the sound not paused (a sound check).

**Where step 1 ended (2026-11-21).** The three keys as recommended.
`runtime/menu.c` (and `menu.h`): Esc in the window asks for the menu
(a music file has none: Esc still quits it); at the end of the frame
`menu_run` loops, drawing the menu over the last picture darkened (two
steps down the NES palette's brightness), until it closes, with the
speakers paused; no 6502 code runs meanwhile. Items: RESUME, SAVE STATE,
LOAD STATE, SLOT < n > with EMPTY or the day and time it was saved,
RESET, QUIT. Up/Down move, Left/Right (or Return on SLOT) change the
slot, Return / Space / X choose, Esc / Z close. SAVE, LOAD and RESET
only ask (as Cmd+S, Cmd+L and R), after the menu closes. Keys held when
it closes (Return is also Start) are ignored by the game until let go
(`video_ignore_held`). The terminal says "frame N: MENU" and "frame N:
MENU CLOSED (SAVE STATE)".

Input scripts: `800 menu down ok` opens the menu at the end of frame 800
and presses its keys (up, down, left, right, ok, back; shot=FILE saves
its picture, as PNG or the raw palette indexes); a menu line leaves the
buttons as they are, and isn't part of a state (a load doesn't repeat
it). Also a `reset` word (as R), and script lines may be 2047
characters long (they were 255).

The checks:
- `tests/check_menu.py` (`make test-menu`, in `make test-all`), on
  mmc3_split.nes and the FDS demo with its script: the menu's pictures
  pixel by pixel (as it opens, on SLOT with slot 2 picked, a saved
  slot's date) and the game behind it darkened; opening and closing at
  the frames asked for; SAVE then LOAD from the menu plays the same
  frames again and writes the file; RESET from the menu gives the same
  frames as the `reset` word (and different from no reset); slot 2
  picked writes `.state2`, not `.state1`. All 18 pass.
- `tests/check_states.py`: every game in the suite also runs with the
  menu opened at frame N, moved around (slot changed and back) and
  closed: the same frames as without it, and closed at the frame it
  opened. 240 of 240.
- `make test-all` as before (230 of 231, nestest exact); same C.

Breaks, each in a scratch copy:

| broken | caught by |
| --- | --- |
| the menu opens a frame late | 6 checks (both games) |
| SAVE done inside the menu, mid-instruction | 2 (the save/load replay) |
| the slot shown is not the slot used | 2 |
| the game behind the menu not darkened | 6 |
| a menu line lets go of the game's buttons | 10 games (those with scripts holding buttons) |

Tried in a live window (mmc3_split.nes): Esc opened it, RESUME and
QUIT worked, closed at the frame it opened.

Not checked by a test, only in a live window: the speakers pausing,
and a key held when the menu closes not reaching the game. The app's
cards still say ESC QUIT until step 4.

### 2. Game controllers
- Hold Select+Start (and Home where SDL sees it) to open; D-pad, A, B
  in the menu; the shoulders rewind and fast-forward while playing.
- While the menu is open the controller's buttons don't reach the game,
  and a button held when it closes isn't seen as a fresh press.
- Checks with virtual controllers. Breaks: a short Select+Start opening
  it (games lose that combination), a button leaking into the game when
  the menu closes.

### 3. Sound and window in the menu
- SOUND: on/off and a volume (in steps); WINDOW: the size steps (as
  Cmd+= / Cmd+-) and FULL SCREEN.
- The volume is remembered with the window size (the file
  `--remember-size` already writes), so the next game opens the same.
- Checks: the volume actually scales the samples (a sound check), and is
  remembered. Breaks: the volume not applied, not remembered.

### 4. The app, Windows, the README
- The app's cards: ESC MENU (and the controller's way) in place of
  ESC QUIT.
- The menu's checks join the Windows run; the README gets the menu and
  the controller buttons.

## Not in this plan
- The Controllers screen (pairing help, a button test, remapping): the
  next plan; the menu will get a CONTROLLERS item then.
- Pictures of each slot (thumbnails): with the game library.
- Changing keys (remapping): with the Controllers screen.

## Risks
- **A game that reads Select+Start.** Holding both for half a second is
  the guard; a game that needs them held that long would lose it, and
  the README will say so.
- **The system taking the Home button.** Then it simply does nothing in
  the game, and Select+Start still works.
- **The window closing while the menu is open.** It must quit properly
  (the battery save, the recording, the `.missed` notes), like Esc did;
  checked in step 1.
