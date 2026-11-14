# nesrecomp

A static recompiler for NES programs, built as a learning project. It turns
the 6502 machine code in a `.nes` file into C, which a normal compiler turns
into a native program for your Mac, with graphics in a window, sound
(including the Famicom cartridges' extra sound chips), up to four players
on the keyboard or game controllers, a Zapper light gun or an Arkanoid
paddle on the mouse, bank switching for the common cartridge types, and
battery saves. It also recompiles NSF music files (the music
program from a game or a homebrew album) into a player.

## How it works

1. **Trace.** `recomp.py` starts at the cartridge's reset, NMI and IRQ
   vectors and follows every branch, jump and subroutine call to find the
   reachable code.
2. **Translate.** Each 6502 instruction becomes a few lines of C. Jumps and
   branches become `goto`s, so the CPU never "decodes" anything at runtime.
   Reads and writes that can reach the hardware registers (`$2000-$401F`)
   happen on the same CPU cycle as on the real console.
3. **Fall back.** Some code can't be found ahead of time (jump tables,
   addresses pushed onto the stack and "returned" to, code copied into
   RAM). When the native code lands somewhere untranslated, a small
   interpreter, generated from the same opcode table, runs it until
   execution reaches translated code again.
4. **Learn.** Each spot the interpreter had to handle is saved to
   `<rom>.missed` as `BB:AAAA` (8 KB bank, or 4 KB for an NSF that
   switches banks, and address). Recompiling with
   `--missed` translates those natively. Repeat until no new spots show up.
   `make game` does this for you.

The ROM's data (graphics, levels, music) is not copied into the generated C.
The program loads the `.nes` file when it starts, so the output is only
useful alongside the `.nes` file it was made from.

### Bank switching

Many cartridges hold more program ROM than the CPU can see at once, and
swap 8, 16 or 32 KB banks in and out by writing to the cartridge (the
mapper). So the same address can hold different code at different times:

- Code is named by (8 KB bank, address). Labels look like `L_03_8000`,
  and `dispatch` looks up the bank mapped at `pc` right now as well as
  `pc`.
- `recomp.py` has a small table per mapper: which slots switch together,
  which never switch, and what's mapped at power-on. A jump whose
  target bank is certain (same bank, or a slot that never switches)
  becomes a direct `goto`; anything else goes through `dispatch`.
- Code can switch out the bank it's running from. A store that could
  reach the mapper checks a "bank changed" flag afterwards and carries on
  through `dispatch` if it's set.

Supported mappers: 0 NROM, 1 MMC1, 2 UxROM, 3 CNROM, 4 MMC3 (with its
scanline IRQ), 5 MMC5 (with its sound and vertical split), 7 AxROM,
9 MMC2, 10 MMC4, 11 Color Dreams, 19 Namco 163 (with its sound),
21/22/23/25 Konami VRC2 and VRC4 (with VRC4's IRQ), 24/26 Konami VRC6
(with its sound), 28 Action 53, 34 BNROM, 66 GxROM, 69 Sunsoft FME-7
(with the 5B's sound), 85 Konami VRC7 (with its FM sound, partly
approximate). `python3 tests/romlist.py <folder>` shows which
mapper a ROM uses.

### The rest of the console (`runtime/`)

- **Hardware events.** Every translated instruction starts with a cheap
  check, `cycles >= next_event`. When the PPU needs attention (a frame is
  done, an NMI is due) the check jumps to a small handler, which brings the
  hardware up to date and enters the NMI handler if needed. Without a
  check on every instruction, a game's `forever: JMP forever` loop would
  never see an NMI.
- **PPU** (`ppu.c`). The PPU doesn't run alongside the CPU: it catches up
  dot by dot whenever the CPU touches it or an event is due, and draws the
  way the real chip does: background tiles fetched every 8 dots through
  the scroll address as it is at that dot, each line's sprites prepared
  during the line before, and each pixel output at its own dot with
  `$2001` as it is then. So scroll, pattern table, CHR bank, greyscale and
  emphasis changes made partway through a line show from the right pixel
  (the `scanline` demo checks this). It covers background and sprites,
  sprite 0 hit, sprite overflow (including the hardware's search bug),
  the cycle-exact vblank and NMI behaviour the timing test ROMs check,
  and the "decay register": what write-only registers read back, each
  bit fading to 0 about 600 ms after it was last refreshed.
- **Colours** (`palette.c`). Worked out from the NTSC video signal the NES
  outputs (voltage levels to YIQ to RGB), not copied from a palette file,
  including the three colour-emphasis bits of `$2001`, which dim parts of
  that signal: 512 colours in all.
- **APU** (`apu.c`). The sound chip, also catching up on demand: length
  counters, the frame counter and its IRQ, envelopes, sweeps, the five
  channels (two pulses, triangle, noise, DMC) and the DMC's sample DMA,
  which pauses the CPU on the cycle the hardware would (only on a read,
  3 or 4 cycles, depending on get/put alignment) and can repeat a
  `$2007` or `$4016` read it lands on. When sound is wanted, the
  channels are mixed with the console's non-linear formulas, averaged
  down to 48 kHz and filtered like its output stage. Cartridges with
  their own sound chips (VRC6, VRC7, Sunsoft 5B, Namco 163, MMC5) add
  their channels to that mix cycle by cycle (`mapper.c`). Headless test
  runs skip the mixing, so they stay fast.
- **Game controllers** (`gamepad.c`). Through SDL's game controller
  support, with plugging in and out handled as it happens.
- **Window and speakers** (`video_sdl.c`). SDL2, 3x size, sharp pixels,
  paced to the NES's 60.1 frames a second. The video keeps the beat: the
  APU's sample clock is nudged by at most 0.5% to keep SDL's audio queue
  near 50 ms, so the sound neither drifts nor crackles.
- **Mappers** (`mapper.c`). The CPU sees ROM through four 8 KB slots and
  the PPU through eight 1 KB slots; each mapper decides what fills them.
  MMC3 counts scanlines from the PPU's A12 address line, which `ppu.c`
  reports. Two MMC3 revisions differ in when that counter raises its IRQ;
  the newer one (B) is the default, and `--mmc3-rev A` selects the older
  one, which a few boards (Crystalis) have. A cartridge doesn't say which
  it has. Other boards hook in where they need to: VRC4's IRQ counter
  keeps its own time (`catch_up`/`schedule`), MMC2 and MMC4 watch which
  tiles the PPU reads, and MMC5 also maps nametables, sees whether the
  PPU is fetching sprites or background, detects scanlines, supplies
  background tiles itself (extended attributes and the vertical split),
  and has registers and RAM at `$5000-$5FFF`.
- **Interrupts** (`event.c`). NMI and IRQ timing, decided on the cycle
  the real CPU checks (from each opcode's cycle map, `cycles.c`),
  including the one-instruction delay after CLI/PLP and taken branches,
  an NMI taking over a BRK or IRQ entry, and the reset button.
- **Cartridge** (`cart.c`, including battery saves), **controllers,
  four-player adapters, Arkanoid paddles and the Zapper** (`input.c`),
  and the **CPU bus** and command line (`main.c`).

## On a Mac

Once:

    xcode-select --install
    brew install sdl2

For the test suite, also clone the free test ROM collection:

    git clone --depth 1 https://github.com/christopherpow/nes-test-roms.git tests/roms/nes-test-roms

`python3 tests/romlist.py tests/roms` lists each ROM's mapper, sizes and
mirroring (`--nrom` shows only mapper 0).

## Play something

    make run ROM=tests/roms/nes-test-roms/nes15-1.0.0/nes15-NTSC.nes

This recompiles the ROM into `build/<name>`, builds it and opens a window.
Run it again after playing for a while: anything the interpreter had to
handle gets translated natively on the next build. Paths with spaces
aren't supported by the Makefile.

Cartridges with a battery keep their `$6000-$7FFF` RAM in `<rom>.sav`
next to the ROM: it's loaded at start and written on exit. With an NES
2.0 header only the battery-backed part (its PRG NVRAM) is saved; see
"NES 2.0 headers" below.

Sound plays through the speakers unless you pass `--mute` (or press M).
`--wav FILE` also writes it to a file, with or without a window.

| NES button | Controller 1 | Controller 2 |
|---|---|---|
| D-pad | Arrow keys | W A S D |
| A | X | G |
| B | Z | F |
| Start | Return | E |
| Select | Right Shift | Q |

| Key | Does |
|---|---|
| M | Mute / unmute |
| R | Reset button |
| Escape | Quit |

Game controllers (Xbox, PlayStation, Switch Pro and others SDL knows)
work too, alongside the keyboard: the first one connected plays
controller 1, the second controller 2, and so on up to four (players 3
and 4 need a four-player adapter, below, and have no keyboard keys);
they can be plugged in or out while the game runs. The buttons go by position, as on the NES pad:

| NES button | Game controller |
|---|---|
| D-pad | D-pad, or the left stick past half way |
| A | Right face button (Xbox B, PlayStation circle, Switch A) |
| B | Bottom face button (Xbox A, PlayStation cross, Switch B) |
| Start | Start / Menu |
| Select | Back / Select / Share |

The built program takes options after the ROM path:

    --headless         no window (for tests)
    --frames N         stop after N frames
    --screenshot FILE  with --frames: save the last frame as a PNG
    --dump-text        with --frames: print the screen's tiles as text
    --no-save          don't load or write <rom>.sav (battery RAM)
    --wav FILE         write the sound to a WAV file
    --mute             no sound from the speakers (M toggles it)
    --audio-stats      print the sound queue depth once a second
    --input FILE       scripted button presses (below)
    --scale N          window size, N times 256x240 (default 3)
    --mmc3-rev A|B     which MMC3 chip to act like (default B)
    --song N           NSF: start on song N (from 1)
    --port1 pad|vaus|zapper   what controller port 1 or 2 holds (default
    --port2 pad|vaus|zapper     pad): the NES Arkanoid paddle or a Zapper
    --famicom-vaus     a Famicom Arkanoid paddle in the expansion port
    --famicom-zapper   a Famicom Zapper in the expansion port
    --four-score       controllers 3 and 4 through an NES Four Score
    --famicom-4p       controllers 3 and 4 in the Famicom expansion port
    --hori-4p          controllers 1-4 through Hori's Famicom adapter
    --vaus-left N      paddle: the knob's value at the window's left
                       edge, 0-255 (default 77, $4D)
    --info             print the cartridge or NSF header and exit
    --trace            print CPU state before every instruction
    --check-cycles     with --trace: check each instruction's length
                       against its cycle map
    --start HEX        start here instead of the reset vector

An input script holds one change per line: from frame N on, hold these
buttons (`a b select start up down left right`, with `2:`, `3:` or `4:`
in front for controllers 2 to 4). A frame number on its own releases everything.
`tests/inputs/` has examples.

    120 start      # press Start at frame 120
    126            # release it
    200 a 2:start  # A on controller 1, Start on controller 2
    300 knob=160 fire  # paddle: knob at 160, its button held
    400 aim=128,100 trigger  # Zapper: aimed at pixel (128, 100), fired

`knob=N` (0-255) and `fire` set the first paddle, `2:knob=N` and
`2:fire` the second (paddles count in the order port 1, port 2,
Famicom). The knob stays where it was on lines that don't mention it;
the button, like the others, is released. For the Zapper, `aim=X,Y`
(0-255, 0-239) points it at a pixel and `aim=off` away from the screen;
the aim stays put like the knob, and `trigger` is held only on its line.

With none of the controller options, an NES 2.0 header can choose the
device instead (below).

`make run` passes options to the program with `ARGS`:

    make run ROM=game.nes ARGS="--port2 vaus"

## The Arkanoid paddle

The "Vaus" controller that came with Arkanoid is a knob and one button.
Plug one in with `--port2 vaus` (the NES version in controller port 2,
where Arkanoid looks for it), `--port1 vaus`, or `--famicom-vaus` (the
Famicom version, in the expansion port, which leaves both controllers
working). Then the mouse plays it: its position across the window turns
the knob, left to right, and the left mouse button is the paddle's
button. The mouse takes over once it moves over the window.

The window covers 160 counts of the knob, about what a real one turns
through. Games expect different ranges (from the nesdev wiki): Arkanoid
II about $4D-$E2, which is the default, and the first Arkanoid $62 up
to $F2 or beyond, which `--vaus-left 98` covers.

The model follows the nesdev wiki's "Arkanoid controller" page: the
knob is measured when the program writes 1 to `$4016` and sent inverted,
most significant bit first, 9 bits (reads after the 9th repeat it); the
button reads 1 when pressed. A real paddle takes up to 7 ms to measure,
so a game reads the previous strobe's value; here it is measured at
the strobe itself, a frame sooner, which no game should notice.

## The Zapper

Plug the light gun in with `--port2 zapper` (where most games look for
it), `--port1 zapper` or `--famicom-zapper`. It aims where the mouse
points: the pointer turns into a cross over the window, the left button
pulls the trigger, and outside the window the gun points away from the
screen. `tests/zapper_demo.nes` is a target to try:

    make run ROM=tests/zapper_demo.nes ARGS="--port2 zapper"

From the nesdev wiki's "Zapper" page: bit 3 of the port's register
reads 0 while the sensor sees light, and bit 4 is the trigger, here 1
while pulled (as on the simpler guns; the official one's half pull isn't
copied). The sensor sees the picture as the beam draws it: a bright
pixel keeps it lit for about 26 scanlines if white, 24 if light grey,
19 if dark grey. The wiki doesn't say how wide an area the sensor sees
or how bright a colour must be, so nesrecomp's choice is the 5 x 5
pixels around the aim, and the colour's brightness sorted against the
greys: white and the pale colours ($31-$3C) count as white, the light
greys and the middle row ($21-$2C) as light grey, dark grey ($00) as
dark grey, and the darker rows ($01-$0C, $11-$1C) aren't seen. Each read
of the gun's port brings the picture up to that exact moment first.

## Four players

`--four-score` plugs in the NES Four Score, `--famicom-4p` puts
controllers 3 and 4 in the Famicom's expansion port, and `--hori-4p`
plugs in Hori's Famicom adapter. The third and fourth game controllers
play controllers 3 and 4, and scripts set them with `3:` and `4:`.

From the nesdev wiki's "Four player adapters": with the Four Score,
`$4016` sends controller 1's buttons, then controller 3's, then a
signature, and `$4017` the same for 2 and 4 with a different signature;
the Famicom wiring sends controllers 3 and 4 on bit 1 beside 1 and 2;
Hori's adapter sends the Four Score's sequence on bit 1 with the
signatures swapped. A paddle on the same line as an adapter is refused.

## NES 2.0 headers

An iNES header gives little more than the mapper number and the ROM
sizes. An NES 2.0 header (nesdev wiki "NES 2.0") adds:
- RAM sizes;
- the board variant (a "submapper");
- the console and region the program was made for;
- the controller it expects.

`recomp.py` and the runtime read it the same way; `--info` prints
every field. A file whose NES 2.0 sizes don't fit in it is read as
iNES 1.0, as the wiki says. iNES 1.0 files behave as they always have.

- **ROM sizes** up to the header's limits, including the exponent form
  for odd sizes. Sizes that aren't whole banks are refused.
- **RAM** (bytes 10-11):
  - `$6000-$7FFF` holds the declared PRG RAM, then the battery-backed
    PRG NVRAM, and smaller RAM repeats through the 8 KB. With none,
    reads give the open bus (the address's high byte).
  - MMC1 boards with 16 or 32 KB (SOROM, SXROM) switch it with CHR
    bank 0's bits 3 and 2.
  - `<rom>.sav` holds only the NVRAM.
  - CHR RAM is the declared size; with neither CHR ROM nor CHR RAM,
    pattern data reads 0.
- **Board variants** (byte 8, "NES 2.0 submappers"), where an iNES 1.0
  header leaves the runtime guessing:
  - bus conflicts on UxROM, CNROM and AxROM (1 none, 2 yes);
  - MMC1's fixed 32 KB boards (5), which the recompiler also knows
    never switch;
  - one VRC2/VRC4 wiring instead of both (21, 23, 25: 1 and 2);
  - the VRC2 itself (23, 25: 3): no IRQ, two mirroring modes, and a
    1-bit latch at `$6000-$6FFF` where there's no PRG RAM;
  - VRC7a or VRC7b (85: 2, 1);
  - Namco 163's loudness (19: none, 12, 16.5 or 18.75 dB);
  - NEC's MMC3 (4: 4), the older chip of `--mmc3-rev A`, which the
    option can still change.

  NINA-001 (34: 1) is refused. Other submappers run as submapper 0,
  with a warning.
- **The controller** (byte 15): with no controller option, the runtime
  plugs in what the header names:
  - the Four Score (`$02`) or Famicom four players (`$03`);
  - a Zapper in port 2 (`$08`) or port 1 (`$49`);
  - an Arkanoid paddle in port 2 (`$0F`) or the Famicom's (`$10`).

  Devices the runtime doesn't have get a warning and standard
  controllers.
- **Region and console** (bytes 7, 12-14) are only reported: a PAL or
  Dendy program runs at NTSC speed, and a Vs. System or PlayChoice-10
  program as an NES, each with a warning.

## MMC5's vertical split

MMC5 can draw part of each line's background (the left or right side,
from a tile column the program picks) from its own 1 KB of ExRAM, with
its own vertical scroll and its own 4 KB of CHR, while the rest of the
screen scrolls as usual. Games used it for a status panel beside a
playfield. Following the nesdev wiki ("MMC5"):
- `$5200`: bit 7 on, bit 6 the side (0 left, 1 right), bits 0-4 the
  threshold tile. `$5201` is the split's vertical scroll, `$5202` its
  4 KB CHR bank, whatever the CHR mode, `$5130` and 8x16 sprites say.
- The split's tiles and attributes come from ExRAM, which must be in
  mode 0 or 1. In mode 1 the rest of the screen keeps its extended
  attributes, while the split uses plain ones. Modes 2 and 3 turn the
  split off.
- The split doesn't scroll sideways: its columns stay put, and only its
  edge moves with the fine X scroll, by up to 7 pixels.
- `$5201` values 240-255 show the attribute bytes as tiles for the
  first lines, then wrap to row 0.

The wiki leaves three details open. The runtime chooses:
- **Where counting starts.** Tile 0 is the first fetch at dot 321 of
  the line before. So the count matches the 34 tiles the PPU draws from:
  2 fetched at the end of the line before, then 32.
- **The ExRAM address.** For split tile n on split row r, the tile is at
  `r * 32 + (n & 31)`, and the attribute byte is at
  `$3C0 + (r / 4) * 8 + (n & 31) / 4`.
- **The line count.** The split starts from `$5201` where the MMC5 sees
  the frame start (as for its IRQ counter), and moves one line on each
  rendered line. When rendering is turned off and on again mid-frame,
  it starts over from `$5201` at the line where rendering came back.

No free program in the test collection uses the split, so these
choices are checked only by the project's own test ROMs. A game's panel
a tile or a line out would point to one of them.
`tests/mmc5_split_demo.nes` is a demo to try by hand: a scrolling
playfield beside the panel. Up and Down scroll the panel, Left pauses the
playfield, and A moves the panel to the other side.

    make run ROM=tests/mmc5_split_demo.nes

Not done: the MMC5A's extra registers (`$5207-$520A`, `$5800`) and the
split's SL mode.

## Play music (NSF files)

An NSF file holds a music program without a picture: a routine that
sets up a song (init) and one that moves it on (play, normally called
60 times a second). The same commands build and play one:

    make run ROM=tests/roms/nes-test-roms/other/dnsf2_enginetest3.nsf

The recompiler starts from init and play instead of the reset vector.
The runtime plays the part of an NSF player with a small 6502 program at
`$4100` (an address no NSF uses): it resets the sound registers, sets
the starting banks, calls init, then waits for the play timer and calls
play, over and over. It waits by checking the timer, not by being
interrupted, so play never cuts into init or into itself.

The window shows the title, artist, copyright, song number and time.

| Key | Does |
|---|---|
| Left / Right | Previous / next song (arrow keys, a game controller's D-pad, or an input script) |
| R | Restart the song |
| M | Mute / unmute |
| Escape | Quit |

`--song N` starts on song N (from 1; the default is the file's own
choice), and `--info` prints the header: title, songs, play rate, bank
switching and sound chips.

Supported: bank switching (4 KB banks at `$5FF8-$5FFF`); the header's
play rate (its PAL rate for NSFs made only for PAL consoles, which play
at PAL speed but about 7% sharp, since the console is an NTSC one); and
the VRC6, VRC7, MMC5, Namco 163 and Sunsoft 5B sound chips, alone or
together. Not supported: the Famicom Disk System's sound chip (silent,
with a message), NSFs that load below `$8000`, and the newer NSF2 and
NSFe formats.

## Tests

    make test       # CPU: nestest, cycle-exact
    make test-ppu   # everything in tests/suite.txt (needs the ROM clone)
    make test-all   # both

`make test` also runs `--test-gamepads`, which plugs in virtual game
controllers, presses and tilts them, and checks the NES buttons that
come out, and `tests/check_headers.py`, which writes 19 iNES and NES 2.0
headers and checks that `recomp.py` and the runtime read each the same
way, and as written down by hand from the wiki. It checks the program's state after every one of nestest's 8,991
instructions against a reference log: registers, flags, stack pointer and
cycle count. It also checks that every instruction took as many cycles as
its cycle map says (the per-cycle bus activity `recomp.py` generates for
each opcode, used for exact DMA and interrupt timing).

`make test-ppu` (the name is from when it was only PPU tests) runs
`tests/run_tests.py`. It recompiles each ROM in
`tests/suite.txt` (with the `.missed` loop), runs it headless, and judges
it in one of these ways (the top of `tests/suite.txt` explains each):

- `result`: the `$6000` status byte newer test ROMs write. A ROM that
  asks for the reset button (status `$81`) gets it pressed automatically.
- `text` and `crc`: the result text, or a checksum the test's source
  lists as correct, read from the screen.
- `frame` and `audio`: a fingerprint of the final picture or of the
  recorded sound (regression checks for homebrew).
- `silence`: the `apu_mixer` tests play a tone and its exact inverse, so
  a correct mixer leaves near silence between their two beeps.
- `tones`: a test ROM plays notes one at a time; each note's pitch (to
  0.25%) and loudness relative to the first (to 5%) are measured from
  the recording and compared with what the sound chip's documentation
  predicts, after the runtime's output filters (computed harmonic by
  harmonic in `make_tone_test.py`).

A suite line can also pass options to the program, such as
`--mmc3-rev=A`. It compares against `tests/expected.txt` and exits with
an error only if something got worse. After an improvement, accept the
new results with `python3 tests/run_tests.py --update`. To run part of
the suite, pass part of a path: `python3 tests/run_tests.py sprite_hit`.

Some checks needed test ROMs that didn't exist, so the project makes its
own. Each `tests/make_*.py` writes a small ROM into `tests/`:

- `make_axrom_test.py`: AxROM switching from inside the switched window.
- `make_mmc1_test.py`: MMC1's serial register, reset, PRG modes,
  mirroring, and its ignoring of back-to-back writes.
- `make_irq_test.py`: when the CPU takes an IRQ (I flag, CLI, PLP, RTI,
  acknowledge), using MMC3's counter as an IRQ source.
- `make_gxrom_test.py`: GxROM's PRG and CHR switching and its bus
  conflicts.
- `make_tone_test.py`: notes of known pitch and volume, for the `tones`
  check (`apu_tones.nes` uses only the APU; the expansion sound
  generators build on it).
- `make_vrc6_test.py`: VRC6 banking and IRQ, and tone ROMs for its two
  pulses and sawtooth (mappers 24 and 26).
- `make_fme7_test.py`: FME-7 banking and its cycle-counting IRQ, and a
  tone ROM for the 5B's channels, volume curve and envelope.
- `make_n163_test.py`: Namco 163 banking (including nametable RAM as CHR
  and nametables), sound RAM and IRQ, and a tone ROM for its wavetable
  channels.
- `make_mmc5_sound_test.py`: MMC5's pulses and PCM channel, its 240 Hz
  length counters and PCM IRQ.
- `make_split_test.py`: MMC5's vertical split, in 44 checks of one frame
  each, using sprite 0 hit to see whether the split was drawn under the
  sprite:
  - sides, threshold, scroll, wrap and pattern row;
  - the bank, alone and beside CHR mode, `$5130` and 8x16 sprites;
  - ExRAM modes; fine and coarse X; `$5201` 240-255;
  - a restart when rendering comes back mid-frame.

  Also a picture of the split's colours beside extended attributes.
- `make_split_demo.py`: the split demo above, with a scripted panel
  scroll and side change as a picture check.
- `make_vrc7_test.py`: VRC7 banking (both board variants) and IRQ, and a
  tone ROM for its FM channels with a near-sine instrument.
- `make_joy_test.py`: both controllers read at set frames against a
  matching input script, the 9th-read and held-strobe behaviour.
- `make_vaus_test.py`: Arkanoid paddles in each wiring (port 1, port 2,
  Famicom, and two at once) read at set frames against one input
  script: the knob's 8 bits, the reads after them, the button (also
  with the strobe held), controllers alongside, and bits nothing drives.
- `make_four_test.py`: one ROM per four-player wiring, reading every
  line through its whole sequence and beyond, after a strobe that
  restarts it part way.
- `make_zapper_test.py`: one ROM per Zapper wiring that draws white,
  grey and blue boxes and reads the light sensor once a scanline for a
  whole frame with the gun aimed at each, comparing when the light
  starts and stops with the model; and the trigger.
- `make_zapper_demo.py`: the Zapper target to try by hand, with a
  scripted hit and miss as a picture check.
- `make_mmc2_test.py`: MMC2 and MMC4's tile-triggered CHR latches,
  driven through `$2007` reads.
- `make_vrc4_test.py`: one ROM per VRC4 mapper number (21, 23, 25):
  banking, swap mode, mirroring and the IRQ in both modes, through both
  address wirings each number covers.
- `make_ram_test.py`: NES 2.0 RAM sizes: no PRG RAM, 2 KB repeated,
  no CHR at all, MMC1 with 32 and 16 KB of banked PRG RAM, and 16 KB of
  CHR RAM. They report on screen (`text`), since a RAM test can't count
  on RAM.
- `make_variant_test.py`: one ROM per board variant (submapper): bus
  conflicts, MMC1's fixed PRG, each VRC2/VRC4 and VRC7 wiring alone, the
  VRC2 and its latch, and Namco 163 tone ROMs at two loudness levels.
- `make_device_test.py`: NES 2.0 copies of the Zapper, paddle and
  four-player ROMs that name their device in byte 15 and run with no
  option.
- `make_nsf_test.py`: NSFs for bank switching (12 tagged banks, code
  switching its own slot), the play rate (each play call flips the DMC
  level, so the pitch shows the rate; NTSC and PAL-only headers), and
  two sound chips in one file. The chip generators above also write
  NSF versions of their tone ROMs (`tone_nsf`), which must sound the
  same as the ROMs.

Each check in these was confirmed by breaking that part of the runtime or
recompiler on purpose and seeing the test report it.

Current results: 206 of 207 graded tests pass, and the 31 pictures and 8
sound recordings match. That includes all 16 `instr_test-v5` CPU tests
and the 11 built as NSFs (`nes_instr_test/nsf_singles`),
all of `ppu_vbl_nmi`, `vbl_nmi_timing`, the sprite 0 hit and sprite
overflow suites, blargg's 2005 PPU tests, all 8 `apu_test` and 11 blargg
APU tests, the three `apu_mixer` silence checks, all 8 reset tests, both
CNROM tests, all 12 MMC3 tests (the two for the older chip run with
`--mmc3-rev=A`), all of `cpu_interrupts_v2`, all of
`dmc_dma_during_read4`, both `sprdma_and_dmc_dma` tests,
`ppu_open_bus`, pictures of the paddle programs `vaus-test` and
`PaddleTest3` with scripted knob positions and of `vaus-test` with
Famicom controller 3, and recordings of "The Amazing Engine Test" NSF's songs.
The one failure is `other/test28`, a 2012 Action 53 test whose
expectations contradict the nesdev wiki's reference
implementation; the Action 53 collection it was written for (Streemerz)
works.

`dmc_tests` (no readme, source or on-screen result) and the interactive
or display-only `read_joy3` tests are left out of the suite, and so is
`other/LINUS.NSF`, which is music from a commercial game.

## Status

- [x] iNES loader, code tracer, 6502 to C translation
- [x] All official opcodes and all stable unofficial ones, cycle-accurate
      (only the 12 "JAM" opcodes that lock up a real CPU are left out)
- [x] Fallback interpreter and multi-pass `.missed` feedback
- [x] nestest passes in full
- [x] PPU (graphics) and an SDL window
- [x] NMI delivery at vblank, cycle-exact
- [x] Controllers 1 and 2 on the keyboard or game controllers, and
      scripted input for both
- [x] Test ROM runner with a recorded baseline
- [x] Mappers 0, 1, 2, 3, 4, 7, 34, with banked recompilation
- [x] Mappers 5, 9, 10, 11, 21, 22, 23, 25, 28, 66
- [x] IRQs (MMC3 scanline counter) and battery saves
- [x] APU: sound through the speakers or a WAV file, frame and DMC IRQs
- [x] The reset button
- [x] Interrupt polling on the exact cycle, from per-opcode cycle maps
- [x] DMC DMA halting on the exact cycle, 3 or 4 cycles long
- [x] Sprite DMA cycle by cycle, with DMC fetches inside it
- [x] PPU open-bus decay
- [x] Colour emphasis
- [x] Mid-line scroll, `$2000`, `$2001` and CHR bank changes
- [x] Expansion sound: VRC6, Sunsoft 5B, Namco 163, MMC5 and VRC7
      (mappers 5, 19, 24, 26, 69, 85; VRC7's envelope timing and
      modulation depth approximate)
- [x] NSF music files: a player screen, song changes, bank switching,
      the header's play rate, and the expansion sound chips (not FDS)
- [x] NES 2.0 headers: RAM sizes, board variants (submappers) and the
      expected controller
- [x] Arkanoid paddles (NES and Famicom), on the mouse or in scripts
- [x] The Zapper (NES and Famicom) on the mouse or in scripts
- [x] Four players: the Four Score, the Famicom's expansion port, Hori's
      adapter
- [x] MMC5's vertical split screen
- [ ] The Famicom Disk System: its sound chip (for NSFs too) and disks
- [ ] NSF2 and NSFe music files (track names and lengths, songs that end
      by themselves)

`PLAN.md`, `PLAN-mappers.md`, `PLAN-sound.md`, `PLAN-cycles.md`,
`PLAN-render.md`, `PLAN-mappers2.md`, `PLAN-expansion.md`,
`PLAN-input.md`, `PLAN-nsf.md`, `PLAN-paddle.md`, `PLAN-zapper.md`,
`PLAN-nes2.md` and `PLAN-split.md` have the step-by-step notes for each
stage (graphics, mappers, sound, per-cycle timing, rendering, more
mappers, expansion sound, controllers, NSF music, the paddle, the Zapper
and four players, NES 2.0 headers, MMC5's split), including how each timing value was tuned, what
was tried for what still fails, and where the documentation left a
choice to make.
