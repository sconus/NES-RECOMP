# Plan: controller 2 and game controllers

Goal: two players, on the keyboard or on USB/Bluetooth game controllers
(Xbox, PlayStation, Switch Pro and the like, through SDL's game
controller support), and scripted input for both players in tests.

`make test-all` must not get worse at any step; nestest stays exact.

## What exists

- `runtime/input.c` already models both ports (`$4016`/`$4017`), with a
  button byte per controller, but only controller 1 is ever set: from the
  keyboard (arrows, X, Z, Return, Right Shift) or from an `--input`
  script.
- Nothing reads game controllers.

## Test material

- `read_joy3/test_buttons` (in the ROM collection) asks for each
  controller-1 button in turn, with the DMC running, and passes when
  each arrives alone; an input script can answer it.
- Nothing in the collection tests controller 2, so the project writes a
  small test ROM that reads both ports and checks scripted presses.
- Game controllers can't be plugged in by a test, but SDL can attach a
  *virtual* game controller from software. A self-test attaches one,
  presses its buttons and tilts its stick, and checks the NES buttons
  that come out, so the mapping is tested without hardware. Trying it
  with a real controller is then a quick check by hand.

## Steps

### 1. Controller 2 (done)
- Input scripts: a `2:` prefix for controller 2's buttons (`120 a 2:start`
  holds A on controller 1 and Start on controller 2).
- Keyboard for controller 2 (a second block of keys, listed in the
  README), so two people can share a keyboard.
- Checks: a generated ROM that reads both controllers and compares them
  with what its script presses (including both at once, and the bits
  after the eighth read); `read_joy3/test_buttons` driven by a script.

Done.
- Input scripts take `2:` before a button name for controller 2
  (`runtime/main.c`); each script line now sets both controllers.
- Controller 2's keys: W A S D for the D-pad, G = A, F = B, E = Start,
  Q = Select (`runtime/video_sdl.c`), chosen to stay clear of controller
  1's keys and of M (mute) and R (reset).
- `tests/joy2.nes` and `tests/inputs/joy2.txt` (from `make_joy_test.py`):
  the ROM counts frames in its NMI handler and, at five set frames,
  reads both controllers and compares them with the script (each alone,
  both at once, all eight buttons on each, all released), then checks a
  9th read returns 1 and that with the strobe held at 1 every read
  returns A. It fails at the first check without its script.
- `read_joy3/test_buttons` (which runs the DMC while asking for each
  button) passes with `tests/inputs/read_joy3_buttons.txt`.
- Breaking controller 2's latch, `$4017` reading controller 1, the
  bits after the 8th read, the script's `2:` prefix, or the held strobe
  each fails `joy2`. The held-strobe check was added after the first
  round of breaks showed nothing covered it.

### 2. Game controllers (done)
- Open game controllers at start and when plugged in later; the first
  plays controller 1, the second controller 2, alongside the keyboard.
- Mapping: D-pad and left stick to the D-pad (stick with a dead zone),
  Start and Back/Select to Start and Select, and the face buttons by
  position, as on the NES (right face button = A, bottom = B).
  Opposite directions cancel, as the keyboard does now.
- Check: the virtual-controller self-test, run by `make test`.

Done (`runtime/gamepad.c`).
- Controllers are opened at start and on SDL's "device added" event;
  each takes the first free slot (controller 1, then 2), and unplugging
  one frees its slot without moving the other.
- Mapping as planned. `SDL_HINT_GAMECONTROLLER_USE_BUTTON_LABELS` is set
  to 0 so Nintendo controllers aren't swapped to match their labels: the
  right face button is A on every brand. The stick counts past half way
  (16384 of 32767). Opposite directions cancel, as for the keyboard (in
  `video_buttons`, which now adds the controller's buttons).
- `--test-gamepads` (run by `make test`, with no ROM or window): attaches
  SDL virtual game controllers and checks the face buttons, Start and
  Back, the D-pad, the stick in four directions and inside the dead
  zone, a second controller becoming controller 2 without affecting
  controller 1, and unplugging and replugging. Breaking the face-button
  positions, the stick, the dead zone, the stick's vertical direction or
  the unplug handling each fails it with a message saying what came out.
- A game was run in a window with no controller attached to make sure
  start-up is clean.
- Tried by hand with a real Xbox Series X controller over Bluetooth:
  `read_joy3/test_buttons` passed (A on the right face button, B on the
  bottom one, Select on View, Start on Menu, the D-pad). A first run
  failed when a different button was pressed than the one on screen,
  which is what that test is for.

### 3. Suite, README, notes (done)
Accept the new checks, document the keys and the controller mapping, and
write where the stage ended.

Done: the README has the key tables for both controllers, the game
controller mapping, the `2:` script syntax and the self-test; its status
list now names the open ideas left from all the stages.

## Where the stage ended

- Two players, each on the keyboard (arrows / WASD blocks) or a game
  controller, or both at once; game controllers can come and go while a
  game runs.
- Input scripts drive both controllers (`2:`), so two-player behaviour
  can be tested headless.
- Checks: `tests/joy2.nes` (both ports, each alone and together, the 9th
  read, the held strobe), `read_joy3/test_buttons` from a script, and the
  virtual-controller self-test in `make test`. Every one was confirmed by
  breaking what it covers (10 breaks; one gap found and closed: nothing
  checked the held strobe until a break showed it).
- Confirmed on real hardware: an Xbox Series X controller over Bluetooth
  passed `test_buttons`, the first hands-on check of any part of this
  project against a physical device.
- Results: 144 of 145 graded tests (from 142 of 143), nestest exact, the
  game controller self-test passing.
- Found during the final run: with the Xbox controller still connected,
  the self-test failed, because the real controller took the slot the
  test had just freed. The self-test now ignores everything but its own
  virtual controllers (`SDL_JoystickIsVirtual`); games still open real
  ones as before.

Not done: the left stick and plugging in and out were only checked with
virtual controllers; other input devices (Zapper, Arkanoid paddle, Four
Score) and changing the mapping without recompiling are left for later.

## Not in this stage
- Other NES input devices: the Zapper light gun, the Arkanoid paddle
  (`vaus-test`, `PaddleTest3` are in the collection), the Four Score
  four-player adapter.
- Changing the key or button mapping without recompiling.

## Risks (as planned)
- The face-button question: "A" on an Xbox controller is the bottom
  button, while the NES's A is on the right. Mapping by position feels
  right on most layouts but may surprise people used to labels; the
  README will say which, and changing it is one table.
- A real controller's stick and D-pad differ by model; the virtual
  self-test covers the mapping, not every device.
