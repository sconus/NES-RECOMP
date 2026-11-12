# Plan: sound (the APU)

Goal: recompiled programs play correct NES sound through the Mac's
speakers, and the parts of the APU that programs can see (status bits,
IRQs, DMA timing) behave closely enough to pass the APU test ROMs. Like
the PPU, the APU lives entirely in `runtime/`; the recompiler shouldn't
need changes.

`make test-all` must stay at its current results after every step.

## What the APU is

Five channels: two pulse (square) waves, a triangle, noise, and the DMC,
which plays 1-bit delta samples fetched from ROM. Each has a timer
(pitch); most also have a length counter (note duration), and the pulses
and noise have an envelope (volume fade). The pulses have a sweep unit
(pitch slide), and the triangle a linear counter. A frame counter clocks
the envelopes, sweeps and length counters 4 or 5 times per frame and can
raise an IRQ. The channels are mixed by a non-linear DAC.

Programs see the APU through `$4000-$4013` (channel registers), `$4015`
(enable/status) and `$4017` (frame counter). Today these writes are
ignored and reads return 0.

## Design

- **Catch-up, like the PPU.** `apu_catch_up()` runs the APU forward to the
  current CPU cycle, called before any APU register access and from
  `runtime_event`. Timers run per CPU cycle; at 1.79 MHz a plain loop is
  cheap enough, and can be optimised later by jumping straight to the
  next timer event.
- **Events.** The frame counter's IRQ time and the DMC's next sample
  fetch are known ahead of time, so the APU schedules them with
  `schedule_event`, the same way the PPU schedules vblank.
- **IRQs** go through the existing `cpu_set_irq(IRQ_APU, ...)`.
- **Samples.** The mixer output is computed with the standard non-linear
  formulas (as lookup tables) and turned into 48 kHz audio with a simple
  low-pass and decimation step, plus the gentle high-pass filters of the
  console's output stage.
- **Playback and pacing.** Video stays the master clock (frames paced to
  60.0988 Hz as now). Audio goes to an SDL audio queue, and the
  resampling rate is nudged by a fraction of a percent to keep the queue
  near a target depth. That avoids both drift and crackle without
  changing how frames are paced.
- **Headless.** `--wav FILE` writes the sound to a WAV file, so tests can
  check audio without speakers.

## Test ROMs (all in the existing clone)

| ROM | Checks | Reports via |
|---|---|---|
| `apu_test/rom_singles/1..8` | length counters, tables, IRQ flag, jitter, timing, DMC basics/rates | `$6000` |
| `blargg_apu_2005.07.30/01..11` | older versions of the same | screen |
| `apu_reset/*` (6) | power-on and reset state | `$6000`, needs the reset button |
| `dmc_tests/*` (4) | DMC buffer, latency, status, IRQ | screen |
| `dmc_dma_during_read4/*` (5), `sprdma_and_dmc_dma/*` (2) | DMC DMA stealing CPU cycles and its double reads | `$6000` / screen |
| `apu_mixer/*` (4) | mixer levels and non-linearity: a tone plus its inverse through the DMC should cancel | measured from the WAV |
| `cpu_interrupts_v2` 1, 3, 4, 5; `instr_misc` 4; `instr_timing` 1-2 | CPU tests that lean on the APU (frame IRQ, length counter timing) | `$6000` |
| `read_joy3/*` (4) | controller reads while DMC DMA runs (CNROM) | screen |

For listening and an audio fingerprint, nes15 has music under its BSD
licence. spritecans plays an arrangement of a commercial song, so it
isn't used as an audio reference. `volume_tests` and `apu_mixer` come
with recordings from real consoles and other emulators, which are useful
for comparing by ear.

## Steps

### 1. APU state the CPU can see (still silent) (done)
Done (`runtime/apu.c`): length counters with the halt and same-cycle
reload rules, the frame counter in both modes with its IRQ, `$4015`
reads and writes, and the DMC's sample reader with its status and IRQ
(fetch timing still simplified). Each source of an IRQ now says when it
raised the line, and CLI, SEI and PLP use the I flag from before they
ran for the very next interrupt decision. An NMI can take over an IRQ's
entry the way it already could a BRK's.

Tuned against the tests: APU writes land 1 cycle after the start of the
write's bus cycle, and `$4017` takes effect 2 cycles after that, plus one
on odd cycles. Bugs found on the way: writing `$4015` cleared the DMC IRQ
after restarting a sample instead of before; the IRQ test ROM made for
the mapper stage never turned the frame IRQ off (fixed in its generator,
all five deliberate breakages still caught).

Results: all 8 `apu_test`, all 11 `blargg_apu_2005`, both `instr_timing`,
`instr_misc` (single and combined) and `cpu_interrupts` 1 and 2 pass;
the suite is at 97 of 104. Still failing from this area:
`cpu_interrupts` 3 (NMI during IRQ entry, rows that depend on APU and
PPU lining up within a cycle or two), 4 (IRQ around sprite DMA, for
step 4) and 5 (exactly which cycle of a JMP or taken branch the
interrupt check happens on).

`dmc_tests` was left out: no readme, no source, no text on screen.
StarsSE was dropped from the picture checks: its music code runs CLI with
the APU frame IRQ still on and its IRQ handler doesn't acknowledge it, so
it gets stuck before turning rendering on, as on a real console.

Original notes:
Registers, length counters (with the load table and halt flags), the
frame counter in both modes with its IRQ and the odd/even-cycle delay on
`$4017` writes, `$4015` reads and writes, and DMC status bits and IRQ
(without exact fetch timing yet).
Checkpoint: `apu_test` 1-6, most of `blargg_apu_2005`, `cpu_interrupts`
1 and 3, `instr_misc` 4, and the `instr_timing` tests (they time
instructions against the length counter).

### 2. Waveforms, mixer and WAV output (done)
Done (`runtime/apu.c`, `runtime/wav.c`): both pulses (duty, envelope,
sweep with pulse 1's one's-complement quirk, muting), the triangle with
its linear counter, the noise shift register in both modes, and the
DMC's output level driven by the fetched sample bits. Each CPU cycle the
timers step and the channels are mixed with the nesdev formulas; the mix
is averaged down to 48 kHz and filtered like the console's output stage
(90 Hz and 440 Hz high-pass, 14 kHz low-pass). This only runs when sound
is wanted, so headless tests aren't slowed down. `--wav FILE` writes it
out: 20 seconds of nes15 take about 1.2 s.

Finding: the common `3t + 2n + d` shortcut for the triangle/noise/DMC
mixer left 4x more sound in `apu_mixer/triangle` than the exact formula,
so the exact one is used, as a 16x16x128 table.

Test runner: `silence` (apu_mixer square, triangle, dmc: the loudest
quarter second between the beeps must be below 0.05 of the beeps; the
correct mixer gives 0.017-0.028) and `audio` (a fingerprint of the
recording, for nes15's music and the noise mixer test). Confirmed by
breaking the mixer four ways; each was caught:

| Broken on purpose | square | triangle | dmc |
|---|---|---|---|
| (unchanged) | 0.028 | 0.020 | 0.017 |
| `3t + 2n + d` shortcut | 0.033 | 0.086 FAIL | 0.048 |
| pulses mixed linearly | 0.412 FAIL | 0.018 | 0.132 FAIL |
| DMC DAC linear | FAIL | 0.127 FAIL | FAIL |
| triangle 20% too loud | 0.028 | 0.176 FAIL | 0.017 |

Suite: 100 of 107, 11 pictures, 2 sounds.

Original notes:
Pulse duty sequences, sweep, envelopes, the triangle's 32-step sequence
and linear counter, the noise shift register (both modes), the DMC's
output unit fed from ROM, the non-linear mixer, filtering to 48 kHz, and
`--wav`.
Test runner: an `audio` kind that fingerprints the WAV (regression, like
`frame`), and a `silence` kind for `apu_mixer` that measures how quiet
the middle section is compared with the beeps. The threshold gets set
from what a correct mixer produces, then checked by breaking the mixer on
purpose.

### 3. Speakers (done)
Done (`runtime/video_sdl.c`, `runtime/main.c`): each frame's samples go
into SDL's audio queue. The video keeps the beat; the APU's sample clock
is nudged by at most 0.5% to hold the queue near 2400 samples (50 ms),
and the queue starts pre-filled with that much silence. Over a 15-second
nes15 run the queue stayed at 2050-2880 samples with no underruns.
`--mute` turns sound off, M in the window toggles it (the title shows
"(muted)"), and `--audio-stats` prints the queue depth once a second.

Listened to on your Mac: nes15's music and the four apu_mixer tests
(near silence between the beeps for square, triangle and DMC; noise
fading in and out) sound right.

Original notes:
SDL audio queue, the rate nudging described above, a mute option
(`--mute`, and a key in the window), and checking by ear with nes15 and
the mixer tests against their recordings. This is the one step where
you'll need to listen.

### 4. DMC DMA timing (partly done)
Done (`runtime/apu.c`, `runtime/main.c`, `runtime/event.c`):
- A DMC sample fetch is now a DMA request that pauses the CPU 4 cycles.
  `dmc_dma_due` holds the cycle it is due (a pending request, or the
  predicted moment the output unit takes the buffered byte), and an
  event wakes the CPU then. Reads of `$2000-$401F` check it first; a DMA
  that lands exactly on such a read repeats it while the CPU is halted
  (`$2007` 3 extra times, `$4016` once, since a controller doesn't shift
  again on back-to-back reads). A DMA due earlier in the instruction
  halts on its opcode or operand fetch instead, with no side effect.
- A fetch that lands in sprite DMA costs 2 cycles.
- The runner gained a `crc` check: the screen must show one of the
  checksums the test's source lists as correct.

Bug found on the way: restarting a sample through `$4015` while the
previous sample's last byte was still buffered didn't update the
predicted DMA time, so nothing woke the CPU and the first fetch came
~26,000 cycles late (that broke `8-dmc_rates` until fixed).

Results: `apu_test` 1-8 still pass; `dma_2007_write`,
`read_write_2007` and `read_joy3/thorough_test` pass. Suite: 103 of
115.

Still failing: `dma_2007_read` and `dma_4016_read` (the repeated read
happens on the 4th of 5 passes instead of the 3rd: one cycle off),
`double_2007_read`, and both `sprdma_and_dmc_dma`. The read tests first
sync to the DMC using the same DMA stalls, so shifting any one timing
value by a cycle also shifts their sync; sweeps of the stall length
(constant, or 3-or-4 by alignment), the restart delay (fixed and
parity-based) and when a read counts as hit didn't find a combination
that passes. Getting these right probably needs each instruction's
individual bus cycles (which ones are reads), not just the cycle of its
hardware access.

Original notes:
The DMC fetches sample bytes from ROM by pausing the CPU for 1-4 cycles.
Those pauses go into `cycles` at the right moment via the event system.
The hard part is the side effect: if the pause lands during a read of
`$2007` or `$4016`, the real CPU repeats the read, which corrupts
controller input in some games. The recompiled code makes its accesses on
the right cycle (from the PPU stage), so this can be modelled where it
matters.
Checkpoint: `apu_test` 7-8, `dmc_tests`, `dmc_dma_during_read4`,
`sprdma_and_dmc_dma`, `read_joy3`.

### 5. The reset button (done)
Done: `cpu_request_reset()` (R in the window) takes effect at the next
instruction boundary through the interrupt path, as vector `$FFFC`: SP
drops by 3 without writing, I is set, 7 cycles. The APU clears `$4015`
and the frame IRQ, clears the pulse and noise length halt flags (the
triangle's stays), and writes the last `$4017` value again 2 cycles
later; the PPU clears `$2000`, `$2001` and its write toggle. RAM, the
cartridge, mapper state and saves are kept. Headless runs press reset 10
frames (about 170 ms) after a test ROM sets status `$81`.

All 8 reset tests pass (`apu_reset` x6, `cpu_reset` x2), first try.
Checked that they depend on it: without the automatic press they stay at
`$81`; with a reset that doesn't clear `$4015`, `4015_cleared` fails #3.

Original notes:
Some tests (`apu_reset`, and `cpu_reset` from earlier) ask you to press
reset: the status byte at `$6000` becomes `$81`. Add a soft reset (CPU
to the reset vector with the register effects a reset has, APU and PPU
partly reset, RAM kept), a key for it in the window, and have the test
runner press it when a ROM asks.

### 6. Suite and README (done)
The suite has every ROM from this stage, and the README covers sound,
the reset button, the new checks (`audio`, `silence`, `crc`), current
results and each remaining failure.

## Where the stage ended
111 of 123 graded tests pass, with 11 pictures and 2 sound recordings
checked; the sound was confirmed by ear on your Mac. Step 4 (DMC DMA)
is only partly done: 5 DMA tests and 3 `cpu_interrupts_v2` tests still
fail, with what was tried recorded under steps 1 and 4. The likely next
move for them is giving the generated code each instruction's individual
bus cycles (which are reads), so a DMA or interrupt can land on the exact
cycle.

Original notes for step 6:
Add the ROMs above to `tests/suite.txt`, accept the baseline, document
`--wav`, `--mute`, the keys, and update the status list.

## Not in this stage
Expansion audio from Famicom cartridges (VRC6, MMC5, N163 and others),
PAL timing, and the Famicom microphone.
