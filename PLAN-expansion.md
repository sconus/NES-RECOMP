# Plan: Famicom expansion sound

Goal: the extra sound channels some Famicom cartridges carry, mixed with
the console's own APU, and the boards that come with them:

| Chip | Mapper | Sound |
|---|---|---|
| VRC6 | 24, 26 | 2 pulses (16 duty steps) and a sawtooth |
| Sunsoft 5B (FME-7) | 69 | 3 square channels (an AY-3-8910 clone) with noise and an envelope |
| Namco 163 | 19 | 1-8 wavetable channels, time-multiplexed, in 128 bytes of RAM |
| MMC5 | 5 (exists) | 2 pulses like the APU's (no sweep) and an 8-bit PCM channel |
| VRC7 | 85 | 6 FM channels (a cut-down Yamaha OPLL) |

`make test-all` must not get worse at any step; nestest stays exact.

## Test material

The free ROM collection has nothing with expansion sound (its NSF files
use only the APU, and it has no VRC6, 5B, N163 or VRC7 ROMs). So, as for
VRC4 and MMC2, the project writes its own test ROMs, and checks what
comes out of the speaker objectively:

- Each test ROM plays a sequence of notes with known settings, one
  channel at a time, with silence between them, starting with a reference
  note on the APU's own pulse channel.
- A new check in `tests/run_tests.py` records the sound (`--wav`), splits
  it at the silences, and measures each note's pitch and loudness. Pitch
  must match the frequency the chip's documentation gives for those
  settings; loudness, relative to the APU reference, must match the
  documented mixing level (both within a tolerance).
- As before, each check is confirmed by breaking the feature on purpose.

That checks the chips against their documentation, not against
recordings of real hardware; the nesdev wiki's mixing levels are
themselves measurements, with some spread between cartridges.

## Approach

- **Mixing.** The APU already steps its channels every CPU cycle while
  it catches up. A mapper with sound gets a hook there: step its own
  channels one cycle and return its output, which is added to the mix at
  the chip's documented level relative to the APU.
- **Timing.** A write to a sound register brings the APU (and so the
  chip) up to that cycle first, so notes start on the right cycle.
- **Banking.** Each board is a `MAPPERS` entry plus registers in
  `mapper.c`, as before. VRC6 and VRC7 reuse VRC4's IRQ code.

## Steps

### 1. Groundwork: the mixing hook and the tone check (done)
Add the hook to the APU mixer, and the "tones" check to the runner.
Prove the check itself with a generated ROM that plays APU pulse notes
of known pitch and volume.

Done.
- `mapper.audio_step` (`runtime/mapper.h`): the APU calls it for every
  cycle it mixes and adds what it returns to the mix. A chip calls
  `apu_catch_up()` before changing its sound registers.
- The `tones` check (`tests/run_tests.py`): it splits the recording at
  silences (10 ms windows under 2% of the loudest), measures each note's
  pitch from the spacing of its rising zero crossings over the middle 60%,
  and its RMS loudness relative to the first note. Pitch must be within
  0.25%, loudness within 10%. The console's output filters cut low
  frequencies (an 880 Hz note measures 1.19 times as loud as the same
  note at 440 Hz), so loudness is only compared between notes of the
  same pitch; other notes get `-`.
- `tests/make_tone_test.py` builds tone ROMs from lists of register
  writes (`tone_rom`); `apu_tones.nes` plays five APU pulse notes. They
  measure 440.40 and 880.80 Hz (expected 440.4 and 880.8), and
  loudness 0.509 for volume 7 (expected 0.509) and 0.924 for 25% duty
  (expected 0.866 before the filters; the filters favour its stronger
  high harmonics, so that's within the tolerance but not by much).
- Breaking the APU on purpose: a pulse period one longer (438.7 Hz),
  volume ignored, the 25% duty playing 50%, or pulse 2 silent each fail
  the check.

### 2. VRC6 (24, 26) (done)
Banking (16 KB + 8 KB PRG, eight 1 KB CHR banks, mirroring), the VRC
IRQ, and its three channels: two pulses with 16-step duty and a
"digitized" mode, and the sawtooth. Mapper 26 swaps two address lines.
Check: a generated test ROM of tones (pitch, duty, volume, sawtooth
rate), and the IRQ through the VRC4 test's method.

Done (`vrc6_*` in `runtime/mapper.c`), from the nesdev wiki's "VRC6" and
"VRC6 audio" pages:
- Banking: 16 KB at `$8000`, 8 KB at `$C000`, the last 8 KB fixed;
  eight 1 KB CHR banks; mirroring from `$B003` in banking mode 0, the
  only mode Konami's games used (the others, and nametables from CHR,
  aren't modelled). Mapper 26 swaps A0 and A1.
- IRQ: the VRC IRQ, shared with VRC4 (its control and acknowledge
  registers moved into `vrc_irq_control`/`vrc_irq_ack`).
- Sound (`vrc6_audio_step`): the pulses' 16-step duty counting down,
  with "ignore duty" mode; the sawtooth adding its rate every other clock
  and resetting after six adds; `$9003`'s halt and 16x/256x shifts; a
  linear DAC, inverted, where a full pulse equals a full APU pulse.

Making the tones check exact: the loudness of a narrow pulse depends on
the output filters (they cut its fundamental more than its harmonics),
so the first expected values, from unfiltered formulas, were off by up
to 16% for a 1/16 duty. `make_tone_test.py` now computes every expected
loudness from the ideal waveform passed through a model of the runtime's
filters (`filtered_rms`), and the tolerance went from 10% to 5%. The
model and the measurements agree to within about 3% (25% duty: 0.927
expected, 0.923 measured; sawtooth: 1.458 and 1.451).

The notes run longer than planned (about 40 frames, not 30): the ROM
waits for vblank by polling `$2002`, and a read just as vblank begins
stops the flag for that frame, a race the PPU models as hardware has it.
The recordings were lengthened to fit.

Checks: `tests/vrc6_24.nes`, `vrc6_26.nes` (banking, mirroring, IRQ) and
`vrc6_tones_24.nes`, `vrc6_tones_26.nes` (nine notes: pulses at full and
half volume, 25% and 1/16 duty, pulse 2, a 16x-shifted period, and the
sawtooth at two rates). Breaking the duty comparison, the sawtooth's
cycle length or add rhythm, the `$9003` shift, the output level, or
mapper 26's line swap each fails a check.

### 3. Sunsoft FME-7 and 5B (69) (done)
Banking (four 8 KB PRG slots including RAM or ROM at `$6000`, eight
1 KB CHR banks, mirroring) and the 16-bit CPU-cycle IRQ counter; then the
5B's three square channels: 12-bit period, logarithmic volume, tone and
noise enables, and the envelope generator. Check: tones and the IRQ.

Done (`fme_*` in `runtime/mapper.c`), from the nesdev wiki's "Sunsoft
FME-7" and "Sunsoft 5B audio":
- Banking through the command/parameter pair: eight 1 KB CHR banks,
  three 8 KB PRG banks (`$E000` fixed), mirroring, and `$6000` as a ROM
  bank (read-only) or RAM (with its enable bit).
- The IRQ: a 16-bit counter counting down every CPU cycle, firing when
  it wraps past 0, worked out from the elapsed cycles (catch_up/
  schedule hooks, like VRC4's); any write to command D acknowledges.
- The 5B (`fme_audio_step`): three tones at CPU / (32 P), the 17-bit
  noise LFSR, the 32-step envelope with all its shapes, the mixer's
  enables (a channel with tone and noise both off outputs its level
  constantly), and the 5-bit log DAC at 1.5 dB a step (volume V is level
  2V + 1).
- The 5B's loudness against the APU isn't documented (the wiki says it's
  "very loud" and goes through a non-linear amplifier, still being
  investigated). Here a full channel equals a full APU pulse; the tones
  check only compares 5B notes with each other, so this choice is
  unverified.

Checks: `tests/fme7.nes` (PRG and `$6000` banks, RAM, CHR, mirroring,
IRQ timing) and `tests/fme7_tones.nes` (three volumes on the log curve:
0.501 and 0.178 measured and expected; channels B and C; the envelope's
sawtooth and triangle: 0.564 and 0.550 measured, 0.570 and 0.548
expected, pitches exact). Breaking the log DAC, the tone or envelope
rate, the envelope's alternate bit, the tone-off constant output, the
`$6000` ROM select or the IRQ counter each fails a check.

### 4. Namco 163 (19) (done)
Banking (8 KB PRG, 1 KB CHR including the nametable RAM choices) and its
15-bit IRQ counter; then the wavetable channels, stepped one at a time
as the chip does (one channel every 15 CPU cycles), with the number of
enabled channels affecting each one's rate. Check: tones from a known
waveform in sound RAM.

Done (`n163_*` in `runtime/mapper.c`), from the nesdev wiki's "INES
Mapper 019" and "Namco 163 audio":
- Banking: three 8 KB PRG banks, eight 1 KB CHR banks and four
  nametables, where values `$E0` and up select the console's nametable
  RAM (for CHR only if `$E800` allows it). CHR slots pointing at that RAM
  are writable through a new per-slot `chr_writable` mask.
- `$F800` is both the sound RAM address and the PRG RAM write protect
  (writable only with `$4x`; the per-2 KB protect bits aren't modelled).
- The IRQ: a 15-bit counter counting up every cycle, firing at `$7FFF`
  and stopping; `$5000`/`$5800` writes acknowledge, reads return it.
- Sound (`n163_audio_step`): one channel updated every 15 cycles, from
  channel 8 down through the enabled ones, following the wiki's
  pseudo-code (phase, frequency, length, wave address, 4-bit samples low
  nibble first, (sample - 8) * volume); outputs averaged over the
  enabled channels, as the wiki recommends for emulation.
- Level: the wiki gives measurements, 11 to 19.5 dB between a full APU
  square and a full one-channel N163 square, varying by game. This uses
  16.5 dB, the middle of the 16-17 dB measured on boards like Rolling
  Thunder (NES 2.0 submapper 4); other games are quieter or louder.

Two runtime gaps showed up through the test ROM: writes to `$4020-$5FFF`
didn't ask the mapper to schedule its next event (so an IRQ set up there
never woke the CPU); and the test itself had to restore `$F800` before
writing its result, since setting the sound RAM address also
write-protects `$6000`, on hardware too.

Checks: `tests/n163.nes` (PRG and CHR banks, nametable RAM as CHR and as
nametables, sound RAM through the port, IRQ timing, the counter
stopping at `$7FFF`) and `tests/n163_tones.nes` (a square against the
APU: 6.673 measured, 6.682 expected; volume; two-channel averaging;
channel 7; a ramp and a 25% square from other wave addresses). Breaking
the averaging, the 15-cycle update, the wave address or length, the
level, channel 7, nametable RAM as CHR, or the IRQ each fails a check.

### 5. MMC5's sound
Two pulses (the APU's, without sweep, with length counters and
envelopes) and the PCM channel (written by the CPU). Check: tones.

### 6. VRC7 (85)
Banking and the VRC IRQ, then FM synthesis: six channels, each a
modulator and a carrier, with the chip's 15 built-in instruments and one
custom instrument, following the nesdev wiki's description of the chip.
This is the largest piece; if exact OPLL behaviour (envelope rates,
log-sine tables) turns out too large, the step lands with pitch and
volume right and the finer timbre noted as approximate. Check: tones
(pitch and level of a pure-sine instrument).

### 7. Suite, README, notes
Accept the new checks, update the README's mapper list and status, and
write where the stage ended.

## Not in this stage
- The Famicom Disk System's sound (it comes with the disk drive, not a
  mapper).
- NSF music files: playing them would need a small player program around
  the music code, a natural follow-up once the chips exist.
- MMC5's vertical split (left from the last stage).

## Risks
- No reference recordings: the checks prove the code follows the
  documentation. Where the wiki gives a range (mixing levels vary between
  cartridges), the tolerance has to cover it.
- Speed: stepping extra channels every cycle costs time when sound is
  on. Headless test runs without `--wav` skip mixing, as now.
- VRC7 is a real FM synthesizer in miniature; it may land approximate.
