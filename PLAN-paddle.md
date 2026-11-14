# Plan: the Arkanoid paddle (Vaus controller)

Goal: plug a "Vaus" paddle into either controller port (NES) or the
Famicom expansion port, play it with the mouse, and script it in tests,
alongside the standard controllers from the input stage.

`make test-all` must not get worse at any step; nestest stays exact.

## The device

From the test ROMs' notes (`vaus-test/README.txt`) and the nesdev wiki's
"Arkanoid controller" page (to be read again before step 1):

- A knob (a potentiometer) and one button. The knob's position is an
  8-bit number, sampled when the program writes 1 to `$4016` and then
  shifted out one bit per read, most significant bit first. The two ends
  of the knob's travel are about 160 counts apart.
- NES version, in a 7-pin controller port: the button on bit 3 and the
  position on bit 4 of that port's register (`$4016` for port 1,
  `$4017` for port 2, which Arkanoid uses).
- Famicom version, in the 15-pin expansion port: the button on bit 1 of
  `$4016`, the position on bit 1 of `$4017`. The standard controllers
  stay on bit 0, so they keep working.
- Settled from the wiki before step 1: the position goes out inverted
  (games EOR it with $FF); it is really 9 bits, and reads after the 9th
  repeat the 9th bit (games ignore it; it is 0 here, so those reads give
  1); the button reads 1 when pressed, straight from the switch, whatever
  the strobe does; turning the knob left lowers the value. The real
  paddle takes up to 7 ms to measure after the strobe, so a game reads
  the previous strobe's result; the runtime measures at the strobe, a
  frame sooner.

## What exists

- `runtime/input.c` models two standard controllers on bit 0 of
  `$4016`/`$4017`: latch on the strobe, one bit a read, 1s after the
  8th. Every other bit reads as the open bus (`$40`).
- Input scripts set buttons for both controllers per frame (`2:` for
  controller 2); the window takes the keyboard and game controllers.

## Test material

- `vaus-test` (Damian Yerrick, 2013; free licence): a demo that reads
  every wiring at once (NES paddle in either port, Famicom paddle,
  standard controllers) and moves a character toward the knob's
  position once A is pressed. Not self-checking: a picture check.
- `PaddleTest3` (3GenGames, 2011): reads a paddle in port 1 and shows
  its value in hex on a scale, and whether the button is down. Not
  self-checking either: a picture check, but the hex digits on screen
  can be compared with the scripted position by eye.
- Neither grades itself, so the project writes a test ROM (as for
  controller 2) that reads each wiring and compares what it gets with
  what its input script sets: the position, MSB first, in each port
  and the expansion port, the button, the bits after the 8th, and
  that standard controllers on bit 0 are unaffected.

## Steps

### 1. The paddle on the bus, and in scripts (done)
- Each controller port holds a standard controller or a paddle, and the
  expansion port can hold a Famicom paddle: options `--port1 vaus`,
  `--port2 vaus`, `--famicom-vaus`. With none of them, nothing changes.
- The paddle samples its position on the strobe and shifts it out on
  bit 4 (NES) or `$4017` bit 1 (Famicom), with the button on bit 3 (NES)
  or `$4016` bit 1 (Famicom).
- Input scripts: `knob=N` (the position, 0-255) and `fire` on a line
  set the paddle; they work with the existing button names.
- Check: a generated test ROM, through the `$6000` protocol, for each
  wiring (one suite line each), and breaking each part of the model.
- Done: `runtime/input.c` holds what each port has; `make_vaus_test.py`
  writes four ROMs (port 1, port 2, Famicom, two paddles) and one script
  (`2:knob=`/`2:fire` for the second paddle). They pass, and each fails
  with status $02 when run without its option. 14 breaks tried, 12
  caught: knob not inverted, 8 bits not 9, wrong bits after the 9th,
  NES and Famicom button inverted, button lost while the strobe is
  high, Famicom data on the wrong bit, controller left on bit 0 under
  an NES paddle, controllers hidden by the Famicom paddle, only one
  paddle numbered, knob springing back between script lines, `--port2`
  setting port 1. One did not compile (redone as the Famicom one). Not caught: what the knob does
  while the strobe is held at 1, which the model doesn't copy. 168 of
  169 (test28 the expected failure); nestest exact; `recomp.py`
  unchanged, so generated C is the same.

### 2. Playing it with the mouse (done)
- With a paddle plugged in, the mouse's left-right position across the
  window turns the knob over its real range of about 160 counts, and
  the left mouse button is the paddle's button. The keyboard and game
  controllers keep working for any standard controller.
- Checks: `vaus-test` and `PaddleTest3` run from scripts with the knob
  at set positions, saved as pictures (their hex value and marker
  checked by eye, then kept as regression checks); a try by hand with
  the mouse.
- Done: the mouse turns the first paddle's knob over 160 counts, from
  `--vaus-left` (default $4D, Arkanoid II's low end per the wiki) at the
  window's left edge; it only takes over once it has moved over the
  window, and its button adds to any scripted press. The wiki gives
  the first Arkanoid as "$62-$02" (wrapping, or a typo: PaddleTest3's
  own screen says $62-$F2); `--vaus-left 98` covers it either way.
  `make run` passes `ARGS="..."` to the program.
  Pictures, checked by eye: PaddleTest3 shows "Value: A5" and the
  button lit for `knob=165 fire`; vaus-test, with either wiring, shows
  the observed range's brackets at 77 and 237, the knob marker at 197,
  and the character walked to its target (frame 600: it walks at a
  third of a pixel a frame). Breaks caught: knob not inverted, each
  wiring's button off or on the wrong bit, script knob ignored. 168 of
  169, 26 pictures; nestest exact.
  Not checked by the suite: the mouse itself (tests run without a
  window). Tried by hand with vaus-test and PaddleTest3: it works.

### 3. Suite, README, notes (done)
Accept the new checks, document the options, the mouse and the script
syntax, and write where the stage ended.
- Done: the README has an Arkanoid paddle section, the options, the
  script words, `make run ARGS=`, the generator and the new results;
  the status list ticks the paddle and keeps the Zapper and Four Score.

## Where the stage ended
- Paddles plug into either controller port or the Famicom expansion
  port, two at once if wanted, and are played with the mouse or set
  from input scripts. Nothing changes without the options, and
  `recomp.py` didn't change, so every program recompiles to the same C.
- Checks: four generated ROMs that grade every wiring, and pictures of
  the collection's `vaus-test` (two wirings) and `PaddleTest3`. Each
  part of the model was broken on purpose and caught, except what the
  knob does while the strobe is held at 1, which isn't modelled.
- Results: 168 of 169 graded tests (test28 the expected failure), 26
  pictures and 8 sounds; nestest exact.
- Left as they are: the knob is measured at the strobe rather than up
  to 7 ms later; the 9th bit is always 0; the reads during a
  measurement and DMC corruption of reads, which the wiki describes,
  aren't modelled. The first Arkanoid's range is given by the wiki as
  "$62-$02" and by PaddleTest3 as $62-$F2; no free program settles it.
- Not done: the Zapper, the Four Score, a game controller's stick as
  the knob, and changing what's plugged in while a program runs.

## Not in this stage
- The Zapper light gun and the Four Score four-player adapter (the
  status list keeps them as open items).
- A game controller's stick or triggers as the knob.
- Changing what's plugged in while the program runs.

## Risks
- The details listed above as unsettled. The wiki is the reference; the
  two test ROMs only show what they read, so if the wiki is unclear,
  they can show which reading looks right, but not prove it.
- A mouse is not a knob: the window maps position to position, which
  is easy to aim but has no feel of the knob's ends.
