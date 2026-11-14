# Plan: the Zapper and four players

Goal: plug a Zapper light gun into a controller port and aim it with the
mouse, and play with four controllers through the Four Score (NES) or
the Famicom's extra controller wiring, from the keyboard, game
controllers and input scripts.

`make test-all` must not get worse at any step; nestest stays exact;
programs run without the new options behave exactly as before, and
`recomp.py` doesn't change.

## The devices

From the nesdev wiki's "Zapper" and "Four player adapters" pages:

**Zapper**
- No shift register: each read of its port's register (`$4016` port 1,
  `$4017` port 2) shows the gun as it is at that moment. Bit 3 is the
  light sensor, 0 when it sees light; bit 4 is the trigger.
- The sensor sees the TV picture as the beam draws it: it turns on when
  the beam passes a bright spot under the aim, and stays on for about
  26 scanlines for white, 24 for light grey, 19 for dark grey, fading
  as a capacitor drains. Games draw a white (`$20`) or light (`$31-$3C`)
  box and read the sensor through the frame.
- The official trigger reads 1 while half pulled and 0 when released
  or fully pulled, and takes about 100 ms to read "released" again;
  simpler guns read 1 while pulled. Games fire on the change.
- The Famicom Zapper plugs into the expansion port and reads like an
  NES one in port 2.

**Four Score** (NES)
- One strobe for all four. `$4016` bit 0 sends controller 1's 8
  buttons, then controller 3's, then a signature: 0, 0, 0, 1, 0, 0, 0,
  0; `$4017` sends controller 2, controller 4, then 0, 0, 1, 0, 0, 0,
  0, 0. After 24 reads, 1s.

**Famicom, players 3 and 4**
- Simple adapters, and controllers plugged into the expansion port:
  controller 3 on `$4016` bit 1, controller 4 on `$4017` bit 1, 8
  buttons each like controllers 1 and 2.
- The Hori 4 Players Adapter: the Four Score's sequence on bit 1, with
  the two signatures swapped.

## What exists

- `runtime/input.c` already decides, per port, between a standard
  controller and a paddle, plus a Famicom paddle on bit 1; scripts set
  two controllers (`2:`) and two paddles; the mouse plays the first
  paddle.
- `gamepad.c` gives the first two game controllers to players 1 and 2.
- The PPU draws the picture dot by dot into a framebuffer and can be
  brought up to the CPU's cycle (`ppu_catch_up`), which is what the
  Zapper's sensor needs: what was drawn near the aim, and how many
  scanlines ago.

## Test material

The collection has no program for either device; `vaus-test` reads
Famicom controller 3 (bit 1 of `$4016`) and can show it in a picture.
So, as for the paddle, the project writes its own test ROMs, graded
through the `$6000` protocol, plus a small Zapper target program for a
try by hand.

## Steps

### 1. Four players (done)
- Options: `--four-score` (NES: both ports through the adapter),
  `--famicom-4p` (controllers 3 and 4 on bit 1), `--hori-4p` (the Hori
  adapter). With none of them, nothing changes.
- Input scripts: `3:` and `4:` in front of a button name, like `2:`.
- Game controllers: the third and fourth connected play controllers 3
  and 4 (the keyboard stays on players 1 and 2).
- Check: a generated test ROM, one suite line per wiring, reading all
  four controllers and the signature, and the reads after it; and a
  `vaus-test` picture with A held on Famicom controller 3. Break each
  part.
- Done: `input.c` keeps one 32-bit sequence per line (bit 0 and bit 1
  of each port), refilled at the strobe and shifted with 1s coming in,
  which covers a standard controller, the Four Score and both Famicom
  wirings. A paddle can't share a line with them: such option pairs
  are refused. `make_four_test.py` writes one ROM per wiring and a
  shared script; each reads all four lines 24 times after a strobe
  (after 5 reads and a fresh strobe), then 10 more. All pass, and each
  fails without its option. The `vaus-test` picture: with A on
  controller 3, then Right, the character walks right; without the
  option it stays put. The game controller self-test now plugs in four.
  Breaks, all caught: 3 and 4 swapped (Four Score, Famicom), the Four
  Score's and Hori's signatures, Famicom 3 and 4 on bit 0, 0s after
  the sequence (the test first read only 2 more, which missed it, so it
  reads 10), a strobe mid-sequence ignored, script `3:` or `4:` wrong.
  171 of 172; nestest exact; `recomp.py` unchanged.

### 2. The Zapper on the bus, and in scripts
- Options: `--port1 zapper`, `--port2 zapper`, `--famicom-zapper`.
- The sensor: at each read, bring the PPU up to date and look at the
  pixels drawn around the aim in the last few scanlines; it sees light
  if a bright enough one was drawn recently enough (how bright and how
  long from the wiki's figures: white lasts longest, darker colours
  less, dark ones not at all). Off screen, or aimed away, it sees
  nothing.
- The trigger: reads 1 while pulled (the simpler gun's behaviour, which
  the wiki says games accept).
- Input scripts: `aim=X,Y` (a pixel, 0-255 and 0-239), `aim=off`, and
  `trigger`; the aim stays put until changed, like the knob.
- Check: a generated test ROM that draws white, light and dark boxes,
  aims at each (and between them) from its script, and reads the
  sensor before, during and after the beam passes them, timed with
  sprite 0 hit; plus the trigger and the bits nothing drives. Break
  each part.

### 3. The Zapper on the mouse
- With a Zapper plugged in, it aims where the mouse points in the
  window, and the left button pulls the trigger. The mouse pointer is
  shown as a cross over the window.
- A small generated target program (a white box that moves, a counter
  of hits) for a try by hand.

### 4. Suite, README, notes
Accept the new checks, document the options, the mouse, the script
syntax and the key choices, and write where the stage ended.

## Not in this stage
- The Vs. System Zapper (a serial report) and the NES Satellite (its
  details are unknown, says the wiki).
- The official trigger's half pull and 100 ms release.
- The keyboard for players 3 and 4.
- The Four Score's turbo switches.

## Risks
- The sensor: the wiki gives how long it stays lit but not how bright
  a colour must be or how wide an area it sees. The choice (a few
  pixels around the aim, brightness from the palette's colour) will be
  written down; with no game or test program to compare against, only
  the project's own test ROM checks it.
- Light detection depends on when in the frame the program reads, so
  the Zapper test also checks the PPU and CPU timing together; a
  failure could be either.
