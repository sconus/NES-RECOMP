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

**Where step 2 ended (2026-11-21).** In `runtime/gamepad.c`:
`gamepad_frame` runs once a frame (from the window's event handling,
also on fast-forward's undrawn frames and in the menu) and says what the
controllers want besides the game's buttons. Any of the four controllers
can do it:
- Select+Start held 0.5 s (both, counted from when both are down) asks
  for the menu once; a shorter press reaches the game as before. Held
  on, or held as the menu closes, it doesn't open again until let go.
  Home / Guide opens it at once where the system lets SDL see it. The
  terminal says "controller N: menu", then "frame N: MENU" as before.
- In the menu only presses made after it opened count: the D-pad or
  stick moves (a held direction repeats after 0.4 s, then every 0.1 s),
  A or Start chooses, B or Home closes.
- Left shoulder held rewinds, right shoulder fast-forwards (with
  Backspace and ` as before); not in the menu, and not game buttons.
- The buttons held when the menu closes are ignored by the game until
  let go, now kept per controller (`gamepad_ignore_held`); the window's
  own guard covers only the keyboard.

The check: `--test-gamepads` (in `make test` and the Windows run's
tests/run_nestest.py) now also drives a virtual controller with a
pretend clock through all of the above, frame by frame.

Breaks, each in a scratch copy:

| broken | FAIL lines |
| --- | --- |
| a short Select+Start opens the menu | 4 |
| a button held as the menu closes reaches the game | 2 |
| buttons held as the menu opens act in it | 5 |
| the left shoulder doesn't rewind | 1 |
| the shoulders work in the menu | 1 |
| Select+Start held as the menu closes opens it again | 1 (after fixing the test: at first it only looked at the last frame) |
| a held direction doesn't repeat | 1 |

Found in a live window (an Xbox Series controller, Bluetooth): the
pad was opened twice, as controllers 1 and 2, because SDL announces the
controllers already connected after `gamepad_init` has opened them (a
bug since controllers were added: one pad played as both players, and in
the menu each D-pad press moved two lines). Now each is opened once; the
self-test announces them again, with a free slot, and checks no slot is
added (the break, opening it twice: 1 FAIL line; with all four slots
full the check couldn't see it, so one is unplugged first).

Tried in a live window (mmc3_split.nes, the same controller):
Select+Start opened it as controller 1, the D-pad moved one line, SAVE
STATE, RESUME and QUIT worked, the left shoulder rewound. The right
shoulder (fast-forward) wasn't tried.

Not checked by a test: the window's wiring (that the event handling
calls `gamepad_frame` and passes on what it wants, and that closing the
menu calls `gamepad_ignore_held`); only in a live window with a real
controller.

### 3. Sound and window in the menu
- SOUND: on/off and a volume (in steps); WINDOW: the size steps (as
  Cmd+= / Cmd+-) and FULL SCREEN.
- The volume is remembered with the window size (the file
  `--remember-size` already writes), so the next game opens the same.
- Checks: the volume actually scales the samples (a sound check), and is
  remembered. Breaks: the volume not applied, not remembered.

**Where step 3 ended (2026-11-21).** Two lines, not four, so the menu
stays short (8 lines; the box moved up a little):
- `SOUND < 10 >`: left / right change the speakers' volume, 10 (as loud
  as before) down to 1, then OFF; right from OFF is 1. Return turns it
  off and on at the same volume, as M does (M and the menu are now the
  same setting, kept in main.c). Each step is 3 dB: the gains are a
  table of whole numbers, the same on every machine. Only the speakers:
  a WAV file and a recording keep the game's own sound, and the game's
  fingerprints don't change. The sound is paused while the menu is open,
  so a new volume is heard when it closes.
- `WINDOW < 3X >`: left / right a step smaller or bigger, as Cmd+- and
  Cmd+=; one step past the biggest that fits the screen is FULL; left
  from FULL is the window again. Return switches full screen, as Cmd+F.
- Remembered: `--remember-size` now writes `game_scale N`, `volume N`,
  `sound_off 0|1` (full screen keeps the last window size). The app
  reads them back for the next game (`--volume N`, `--sound-off`); an
  older file with only `game_scale` still works. Full screen itself
  isn't remembered.
- New options: `--volume N`, `--sound-off`, and for the tests
  `--speaker-out F` (what the speakers would get, headless too). Headless,
  WINDOW works on a pretend window (4X at most) so the tests can see it.

The checks (`tests/check_menu.py`, all pass): pictures with SOUND 7 and
WINDOW FULL, and with SOUND OFF and WINDOW 2X; on the FDS demo
(mmc3_split.nes is silent) the speakers' samples are exactly the plain
run's at 15 dB less from the frame the menu closed (SOUND 5), silent with
OFF and with ten steps down, and `--volume 5` from the start; the volume
doesn't change the fingerprints; SOUND 8 / 2X and OFF / FULL are written
on exit. `tests/check_app.py`: the game writes the volume, the app reads
it back (`--game-prefs`, a test hook), and reads a 2.0 file.

Breaks, each in a scratch copy:

| broken | FAIL lines |
| --- | --- |
| the volume not applied | 2 |
| the volume not remembered | 2 |
| steps of 4 dB, not 3 (my first table was wrong: the test's own numbers caught it before any break) | 2 |
| OFF not silencing the speakers | 2 |
| SOUND shows a number while off | 2 (after adding the OFF picture: 0 before) |
| WINDOW shows a size other than the one used | 2 (after adding the 2X picture: 0 before) |
| the app not reading the volume back | 1 |

The terminal says each change ("frame N: SOUND 7", "SOUND OFF",
"WINDOW 4X", "WINDOW FULL"). Committed without a live try of SOUND and
WINDOW (the user's call); a live run opened and closed the menu.

**Added after the live try (the user's choice): a blip.** With the
game's sound paused in the menu, a new volume couldn't be heard until
it closed. Now each change of SOUND in the menu plays a short blip at
the new volume: 50 ms of a 1047 Hz square wave (C6), fading out over its
last 10 ms, through the same gain as the game's sound; OFF is silent,
and M while playing doesn't blip. It plays over the paused speakers in
place of anything queued, and when the menu closes the game's sound
starts again from the queue's silence. `--speaker-out F` writes the
blips to `F.blip`; `tests/check_menu.py` checks that the 9 -> 10 blip is
the full one and every other is it scaled exactly (five steps down: 9 to
5; down to OFF and up: no blip for OFF; Return off and on: one blip; no
change: none). Breaks: the blip at full volume (2 FAIL lines), a blip
for OFF (2), the blip at the volume before the change (4). Not checked by
a test: that M while playing stays silent, and how it sounds.

The user heard the blip live: "sounds perfect".

**Found in a live window: WINDOW stuck at 5X.** The biggest size was
worked out from the whole screen, but a window can't cover the menu bar
and the Dock, so macOS kept it at 5X while the menu thought 6X fitted,
and right never reached FULL. Now the biggest size comes from the
screen's usable space less the window's title bar and edges (also for
Cmd+=), and if a step bigger doesn't grow the window, it goes full
screen.

Not checked by a test: the real window's resize and full screen from
the menu, and the speakers themselves (only `--speaker-out`, which the
speakers get the same samples as); only in a live window.

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
