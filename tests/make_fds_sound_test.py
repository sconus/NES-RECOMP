#!/usr/bin/env python3
"""Write FDS sound tests made for nesrecomp (nesdev wiki "FDS audio";
NSFs with header byte $7B bit 2). Run it again to regenerate them.

tests/nsf_fds.nsf: notes for the "tones" check (make_tone_test.py). The
pitch is f = CPU * p / 2^22 for frequency p, times the modulation's
factor, (64 + the rounded counter * gain / 16) / 64. The output is
sample * volume (at most 32) * master volume, full scale 2.4 APU
squares, through a one-pole low-pass at 2 kHz.

  1  APU pulse, 440.4 Hz                              reference
  2  a square (32 x 63, 32 x 0), p = 1031 (439.9 Hz), volume 32
  3  ... master volume 2/3 ($4089 = 1)                2/3 of note 2
  4  ... volume 16                                    1/2 of note 2
  5  ... volume 40: heard as 32                       as note 2
  6  a triangle, 0 to 62 and back                     from its waveform
  7  the square, counter 16, modulation gain 32: x 1.5 (659.9 Hz)
  8  ... counter -16: x 0.5 (220.0 Hz)
  9  ... counter 3, gain 5: 15 rounds up to 66/64 (453.7 Hz)
 10  ... counter -3, gain 5: -15 isn't rounded up: 63/64 (433.0 Hz)

tests/fds_sound.nsf: the registers, through the blargg $6000 protocol
(the test runs in init):
   0  passed
   2  wavetable bytes written with $4089 bit 7 don't read back (bits
      7-6 read 01)
   3  a write of $FF reads back as $7F (6 bits)
   4  without $4089 bit 7, a wavetable write is ignored, and any
      wavetable address reads the sample being played (position 0 with
      the wave stopped by $4083 bit 7)
   5  $4080 = $94 (envelope off, gain 20): $4090 doesn't read $54
   6  envelope down, speed 4, $408A = 1 (80 cycles a step), 800 cycles:
      the gain isn't 9-11
   7  envelope up, speed 0 (16 cycles), 400 cycles from 30: not 32
   8  $4083 bit 6 stops the envelope: the gain moved
   9  $408A = 0 stops the envelope: the gain moved
  10  $4083 bit 7: envelopes 4 times as fast, 200 cycles at 20 a step
      from 20: not 9-11
  11  $4084 = $A1: $4092 doesn't read $61
  12  the modulation table, all +1, stepping every 16 cycles ($4087 bit
      6), 160 cycles from 0: the counter ($4097) isn't 8-12
  13  $4087 = $C0 stops it (bit 7, even with bit 6): the counter moved
  14  table entries 4 reset the counter: from 20, not 0
  15  $4085 = $45: $4097 doesn't read $45
  16  entries +4 from 60 wrap to negative: not $40-$4B
  17  $4088 writes without $4087 bit 7 are ignored: the +1 table was
      changed
  18  $4091 (the wave position): still 0 with the wave running, or not
      back to 0 once $4083 bit 7 stops it

The memory of an FDS NSF (nesdev wiki "NSF"), blargg $6000 protocol:
tests/fds_nsf_low.nsf loads at $7000, below $8000 (as some rips do):
   2  $7000 / $7FFF don't hold the file's first and last bytes there
   3  JSR $7800, a routine in that part of the file (run from RAM),
      didn't return A = $77
   4  $9000 and $DFFF aren't writable (they are RAM with the FDS)
tests/fds_nsf_banks.nsf, bank-switched (ten 4 KB banks, each with its
number at $FF0; header banks 0-5, 8, 9):
   2  $6000 / $7000 don't start with banks 8 and 9 (header bytes $76
      and $77 also set $5FF6 and $5FF7)
   3  $E000 / $F000 don't hold banks 8 and 9
   4  after $5FF6 = 5, $6000 doesn't hold bank 5
   5  $6100 (a copy of the bank, in RAM) isn't writable
   6  $AFF0 (in $8000-$DFFF) isn't writable
"""
import cmath
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402
from make_tone_test import (tone_nsf, apu_pulse, apu_pulse_wave,  # noqa: E402
                            pulse_hz, CPU_HZ)

FDS = 0x04                                  # NSF header $7B
UNIT = 2.4 * 0.1494 / 2016                  # one step of sample * volume
SQUARE = [63] * 32 + [0] * 32
TRIANGLE = [2 * i for i in range(32)] + [63 - 2 * i for i in range(32)]


def fds_hz(p, counter=0, gain=0):
    temp = counter * gain
    if (temp & 0x0F) and not (temp & 0x800):
        temp += 0x20
    temp = ((temp + 0x400) >> 4) & 0xFF
    return CPU_HZ * p * temp / (64 * 2 ** 22)


def rms(steps, hz, lowpass=None):
    """As make_tone_test.filtered_rms, with the FDS's own low-pass."""
    n = len(steps)
    total, k = 0.0, 1
    while k * hz < 24000:
        f = k * hz
        dft = sum(v * cmath.exp(-2j * math.pi * k * i / n)
                  for i, v in enumerate(steps)) / n
        hold = abs(math.sin(math.pi * k / n) / (math.pi * k / n))
        avg = abs(math.sin(math.pi * f / 48000) / (math.pi * f / 48000))
        hp = f / math.hypot(f, 90) * f / math.hypot(f, 440)
        lp = 1 / math.hypot(1, f / 14000)
        if lowpass:
            lp /= math.hypot(1, f / lowpass)
        total += 2 * (abs(dft) * hold * avg * hp * lp) ** 2
        k += 1
    return math.sqrt(total)


def fds_rms(samples, volume, hz, master=1.0):
    return rms([UNIT * s * volume * master for s in samples], hz, 2000)


def wave_writes(samples):
    return ([(0x4089, 0x80)] + [(0x4040 + i, v) for i, v in enumerate(samples)] +
            [(0x4089, 0x00)])


def fds_note(p, volume=32, master=0, counter=0, gain=0, wave=None):
    start = list(wave_writes(wave)) if wave else []
    start += [(0x4089, master), (0x4087, 0x80), (0x4085, counter & 0x7F),
              (0x4084, 0x80 | gain), (0x4080, 0x80 | volume),
              (0x4082, p & 0xFF), (0x4083, p >> 8)]
    stop = [(0x4080, 0x80), (0x4085, 0), (0x4084, 0x80)]
    return start, stop


def tone_notes():
    ref, a = apu_pulse_wave(), pulse_hz(253)
    r_ref = rms(ref, a)
    p = 1031
    f = fds_hz(p)
    n2 = fds_rms(SQUARE, 32, f)

    def rel(x, to=r_ref):
        return "%.3f" % (x / to)

    notes = [
        (apu_pulse(0, 253), "%.1f@1" % a),
        (fds_note(p, wave=SQUARE), "%.1f@%s" % (f, rel(n2))),
        (fds_note(p, master=1), "%.1f@%s/2" % (f, rel(fds_rms(SQUARE, 32, f, 2 / 3), n2))),
        (fds_note(p, volume=16), "%.1f@%s/2" % (f, rel(fds_rms(SQUARE, 16, f), n2))),
        (fds_note(p, volume=40), "%.1f@%s/2" % (f, rel(n2, n2))),
        (fds_note(p, wave=TRIANGLE), "%.1f@%s/2" % (f, rel(fds_rms(TRIANGLE, 32, f), n2))),
    ]
    for counter, gain in ((16, 32), (-16, 32), (3, 5), (-3, 5)):
        fm = fds_hz(p, counter, gain)
        start, stop = fds_note(p, counter=counter, gain=gain,
                               wave=SQUARE if counter == 16 else None)
        notes.append(((start, stop), "%.1f@%s/2" % (fm, rel(fds_rms(SQUARE, 32, fm), n2))))
    return notes


def delay(a, cycles):
    """About `cycles` CPU cycles: LDY #n; DEY; BNE (5 a loop)."""
    n = max(1, cycles // 5)
    while n > 255:
        a.b(0xA0, 255, 0x88, 0xD0, 0xFD)
        n -= 255
    a.b(0xA0, n, 0x88, 0xD0, 0xFD)


def check_range(a, addr, lo, hi, mask, fail):
    """Fail unless lo <= (read & mask) <= hi."""
    a.lda_abs(addr); a.b(0x29, mask)
    a.cmp(lo); a.b(0xB0, 3); a.b(0x4C); a.fix.append((len(a.code), fail)); a.b(0, 0)
    a.cmp(hi + 1); a.b(0x90, 3); a.b(0x4C); a.fix.append((len(a.code), fail)); a.b(0, 0)


def register_nsf(path):
    a = Asm(0x8000)

    def w(addr, val):
        a.lda(val); a.sta(addr)

    def table(entry):
        w(0x4087, 0x80)
        for _ in range(32):
            w(0x4088, entry)

    a.label("init")
    a.lda(0x40); a.sta(0x4017)
    w(0x6000, 0x80)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        w(0x6001 + i, v)
    w(0x4083, 0x80)                             # wave stopped: position 0
    # 2-4: the wavetable.
    w(0x4089, 0x80); w(0x4040, 0x15); w(0x407F, 0x2A)
    a.check(0x4040, 0x55, "f2"); a.check(0x407F, 0x6A, "f2")
    w(0x4041, 0xFF); a.check(0x4041, 0x7F, "f3")
    w(0x4089, 0x00); w(0x4040, 0x33)
    a.check(0x4041, 0x55, "f4")                 # reads position 0's sample
    w(0x4089, 0x80); a.check(0x4040, 0x55, "f4")
    w(0x4089, 0x00)
    # 5-10: the volume envelope (wave running at frequency 0).
    w(0x4083, 0x00)
    w(0x4080, 0x94); a.check(0x4090, 0x54, "f5")
    w(0x408A, 1); w(0x4080, 0x04); delay(a, 800)
    check_range(a, 0x4090, 9, 11, 0x3F, "f6")
    w(0x4080, 0x80 | 30); w(0x4080, 0x40); delay(a, 400)
    a.check(0x4090, 0x60, "f7")
    w(0x4080, 0x94); w(0x4083, 0x40); w(0x4080, 0x00); delay(a, 400)
    a.check(0x4090, 0x54, "f8")
    w(0x4083, 0x00); w(0x4080, 0x94); w(0x408A, 0); w(0x4080, 0x00); delay(a, 400)
    a.check(0x4090, 0x54, "f9")
    w(0x408A, 1); w(0x4080, 0x94); w(0x4083, 0x80); w(0x4080, 0x04); delay(a, 200)
    check_range(a, 0x4090, 9, 11, 0x3F, "f10")
    w(0x4083, 0x00); w(0x4080, 0x80)
    # 11: the modulation gain.
    w(0x4084, 0xA1); a.check(0x4092, 0x61, "f11")
    # 12-17: the modulation table and counter.
    w(0x4086, 0)
    table(1); w(0x4085, 0); w(0x4087, 0x40); delay(a, 160)
    check_range(a, 0x4097, 8, 12, 0x7F, "f12")
    w(0x4087, 0xC0); a.lda_abs(0x4097); a.b(0x85, 0x10)
    delay(a, 200); a.lda_abs(0x4097); a.b(0xC5, 0x10)    # CMP $10
    a.bne("f13")
    table(4); w(0x4085, 20); w(0x4087, 0x40); delay(a, 100)
    a.check(0x4097, 0x00, "f14")
    w(0x4087, 0x80); w(0x4085, 0x45); a.check(0x4097, 0x45, "f15")
    table(3); w(0x4085, 60); w(0x4087, 0x40); delay(a, 35)
    check_range(a, 0x4097, 0x40, 0x4B, 0x7F, "f16")
    table(1); w(0x4087, 0x00)
    for _ in range(32):
        w(0x4088, 4)
    w(0x4087, 0x80); w(0x4085, 0); w(0x4087, 0x40); delay(a, 160)
    check_range(a, 0x4097, 8, 12, 0x7F, "f17")
    w(0x4087, 0x80)
    # 18: the wave position.
    w(0x4082, 0xFF); w(0x4083, 0x0F); delay(a, 100)
    a.lda_abs(0x4091); a.b(0xD0, 3); a.b(0x4C); a.fix.append((len(a.code), "f18")); a.b(0, 0)
    w(0x4083, 0x80); a.check(0x4091, 0x00, "f18")
    a.label("pass")
    for n in range(0, 19):
        if n == 1:
            continue
        if n:
            a.label("f%d" % n)
        w(0x6000, n)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)
    a.label("play")
    a.rts()
    code = a.done()

    prg = bytearray(0x8000)
    prg[:len(code)] = code
    header = bytearray(0x80)
    header[0:5] = b"NESM\x1a"
    header[5], header[6], header[7] = 1, 1, 1
    for at, v in ((8, 0x8000), (10, a.labels["init"]), (12, a.labels["play"]),
                  (0x6E, 16639)):
        header[at], header[at + 1] = v & 0xFF, v >> 8
    name = b"fds_sound.nsf"
    header[0x0E:0x0E + len(name)] = name
    header[0x2E:0x2E + 9] = b"nesrecomp"
    header[0x7B] = FDS
    with open(path, "wb") as f:
        f.write(bytes(header) + bytes(prg))
    print("wrote", path)


def nsf_header(name, load, init, play, banks=None):
    h = bytearray(0x80)
    h[0:5] = b"NESM\x1a"
    h[5], h[6], h[7] = 1, 1, 1
    for at, v in ((8, load), (10, init), (12, play), (0x6E, 16639)):
        h[at], h[at + 1] = v & 0xFF, v >> 8
    h[0x0E:0x0E + len(name)] = name.encode()
    h[0x2E:0x2E + 9] = b"nesrecomp"
    if banks:
        h[0x70:0x78] = bytes(banks)
    h[0x7B] = FDS
    return bytes(h)


def finish(a, last):
    """The pass label and fail labels 2..last, then play (RTS)."""
    a.label("pass")
    for n in range(0, last + 1):
        if n == 1:
            continue
        if n:
            a.label("f%d" % n)
        a.lda(n); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)
    a.label("play")
    a.rts()


def signature(a):
    a.lda(0x40); a.sta(0x4017)
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)


def low_nsf(path):
    a = Asm(0x8000)
    a.label("init")
    # The signature goes at $6000, which the file doesn't reach ($7000).
    signature(a)
    a.check(0x7000, 0xA5, "f2"); a.check(0x7FFF, 0x5A, "f2")
    a.b(0x20, 0x00, 0x78)                       # JSR $7800
    a.cmp(0x77); a.bne("f3")
    for addr, v in ((0x9000, 0x3C), (0xDFFF, 0xC3)):
        a.lda(v); a.sta(addr); a.check(addr, v, "f4")
    a.b(0x4C); a.fix.append((len(a.code), "pass")); a.b(0, 0)
    finish(a, 4)
    code = a.done()
    low = bytearray(0x1000)                     # $7000-$7FFF
    low[0], low[0xFFF] = 0xA5, 0x5A
    low[0x800:0x803] = bytes([0xA9, 0x77, 0x60])  # LDA #$77; RTS
    body = bytes(low) + code
    with open(path, "wb") as f:
        f.write(nsf_header("fds_nsf_low.nsf", 0x7000, a.labels["init"],
                           a.labels["play"]) + body)
    print("wrote", path)


def banks_nsf(path):
    a = Asm(0x8000)
    a.label("init")
    signature(a)
    a.check(0x6FF0, 8, "f2"); a.check(0x7FF0, 9, "f2")
    a.check(0xEFF0, 8, "f3"); a.check(0xFFF0, 9, "f3")
    a.lda(5); a.sta(0x5FF6); a.check(0x6FF0, 5, "f4")
    signature(a)                                # the copy of bank 5 erased it
    a.lda(0x11); a.sta(0x6100); a.check(0x6100, 0x11, "f5")
    a.lda(0x77); a.sta(0xAFF0); a.check(0xAFF0, 0x77, "f6")
    a.b(0x4C); a.fix.append((len(a.code), "pass")); a.b(0, 0)
    finish(a, 6)
    code = a.done()
    data = bytearray(10 * 0x1000)
    data[:len(code)] = code
    for b in range(10):
        data[b * 0x1000 + 0xFF0] = b
    # The signature at $6000-$6003 lands in the copy of bank 8 (and is
    # written again after bank 5 replaces it).
    with open(path, "wb") as f:
        f.write(nsf_header("fds_nsf_banks.nsf", 0x8000, a.labels["init"],
                           a.labels["play"], [0, 1, 2, 3, 4, 5, 8, 9]) + data)
    print("wrote", path)


def main():
    notes = tone_notes()
    tone_nsf(os.path.join(HERE, "nsf_fds.nsf"), [n for n, _ in notes], FDS)
    print("expected:", ",".join(e for _, e in notes))
    register_nsf(os.path.join(HERE, "fds_sound.nsf"))
    low_nsf(os.path.join(HERE, "fds_nsf_low.nsf"))
    banks_nsf(os.path.join(HERE, "fds_nsf_banks.nsf"))


if __name__ == "__main__":
    main()
