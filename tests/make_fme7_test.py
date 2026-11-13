#!/usr/bin/env python3
"""Write Sunsoft FME-7 / 5B tests (mapper 69) made for nesrecomp. Run it
again to regenerate them.

tests/fme7.nes: banking and IRQ, blargg $6000 protocol:
   0  passed
   2  8 KB PRG banks 4, 5, 6 aren't at $8000, $A000, $C000
   3  command 8 = ROM bank 9: $6000 doesn't show bank 9
   4  command 8 = $C0 (RAM, enabled): $6000 doesn't hold what was written
   5  CHR bank $15 isn't at PPU $0C00
   6  command C = 2 (one-screen low): $2000 and $2400 aren't the same
   7  IRQ, counter 255: fired well before 256 cycles
   8  ... and not fired well after

tests/fme7_tones.nes: notes for the "tones" check (make_tone_test.py),
from the nesdev wiki's "Sunsoft 5B audio": tone CPU / (32 P), envelope
steps every 16 P cycles, 32 steps a ramp; a 5-bit log DAC at 1.5 dB a
step, where volume V is level 2V + 1. How loud the 5B is against the
APU isn't documented, so loudness is only checked between 5B notes:

  1  APU pulse, 440.4 Hz                     reference (not compared)
  2  5B tone A, period 127 (440.4 Hz), volume 15
  3  ... volume 13: 4 levels lower, -6 dB    0.501 as loud as note 2
  4  ... volume 10: 10 levels lower, -15 dB  0.178
  5  tone B, as note 2                       1.0
  6  tone C, as note 2                       1.0
  7  channel A from the envelope, tone off: shape $08 (repeating decay),
     period 8 (437.0 Hz): a 32-step falling sawtooth through the log DAC
  8  shape $0E (repeating up and down), period 4 (437.0 Hz): a triangle
Loudness for 7 and 8 is computed from those step levels through the
output filter model, relative to note 2.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402
from make_tone_test import (tone_rom, tone_nsf, apu_pulse, pulse_hz, CPU_HZ,  # noqa: E402
                            level)

COUNT = 0x10
TAG = 0x1FF0


def dac(n):
    """The 5B's 5-bit log DAC, full scale 1."""
    return 0.0 if n < 2 else 10 ** ((n - 31) * 1.5 / 20)


def reg5b(r, v):
    return [(0xC000, r), (0xE000, v)]


def tone(channel, period, volume=15):
    mixer = 0x3F & ~(1 << channel)              # this channel's tone only
    start = (reg5b(7, mixer) + reg5b(channel * 2, period & 0xFF) +
             reg5b(channel * 2 + 1, period >> 8) + reg5b(8 + channel, volume))
    return start, reg5b(8 + channel, 0)


def envelope(shape, period):
    start = (reg5b(7, 0x3F) + reg5b(11, period & 0xFF) + reg5b(12, period >> 8) +
             reg5b(8, 0x10) + reg5b(13, shape))
    return start, reg5b(8, 0)


def tone_notes():
    p = pulse_hz(253)
    t = CPU_HZ / (32.0 * 127)
    square = [dac(31), 0.0]                     # half high, half low
    saw_hz = CPU_HZ / (16.0 * 8 * 32)
    tri_hz = CPU_HZ / (16.0 * 4 * 64)
    saw = [dac(31 - s) for s in range(32)]
    tri = [dac(s) for s in range(32)] + [dac(31 - s) for s in range(32)]
    return [
        (apu_pulse(0, 253), "%.1f@1" % p),
        (tone(0, 127), "%.1f@-" % t),
        (tone(0, 127, 13), "%.1f@%.3f/2" % (t, dac(27))),
        (tone(0, 127, 10), "%.1f@%.3f/2" % (t, dac(21))),
        (tone(1, 127), "%.1f@1/2" % t),
        (tone(2, 127), "%.1f@1/2" % t),
        (envelope(0x08, 8), "%.1f@%s/2" % (saw_hz, level(saw, saw_hz, square, t))),
        (envelope(0x0E, 4), "%.1f@%s/2" % (tri_hz, level(tri, tri_hz, square, t))),
    ]


def banking_rom(path):
    a = Asm(0xE000)

    def cmd(c, v):
        a.lda(c); a.sta(0x8000); a.lda(v); a.sta(0xA000)

    def delay(n):
        a.b(0xA0, max(1, n // 5), 0x88, 0xD0, 0xFD)

    a.label("reset")
    a.b(0x78, 0xA2, 0xFF, 0x9A)
    cmd(8, 0xC0)                                # RAM at $6000 for the status
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)
    a.lda(0x00); a.sta(0x6004)
    a.b(0x85, COUNT)
    cmd(0x0D, 0x00)                             # IRQ off
    cmd(9, 4); cmd(10, 5); cmd(11, 6)
    a.check(0x9FF0, 4, "fail2"); a.check(0xBFF0, 5, "fail2")
    a.check(0xDFF0, 6, "fail2")
    cmd(8, 0x09)                                # ROM bank 9 at $6000
    a.check(0x7FF0, 9, "fail3")
    cmd(8, 0xC0)                                # RAM again
    a.lda(0x80); a.sta(0x6000)                  # (status: still running)
    a.lda(0xA7); a.sta(0x7000)
    a.check(0x7000, 0xA7, "fail4")
    cmd(3, 0x15)                                # PPU $0C00
    a.lda(0x0C); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.lda_abs(0x2007); a.lda_abs(0x2007)
    a.cmp(0x15); a.bne("fail5")
    cmd(0x0C, 2)                                # one-screen low
    a.lda(0x20); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.lda(0x5A); a.sta(0x2007)
    a.lda(0x24); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.lda_abs(0x2007); a.lda_abs(0x2007)
    a.cmp(0x5A); a.bne("fail6")
    # IRQ: counter 255 wraps past 0 256 cycles after counting starts.
    cmd(0x0E, 0xFF); cmd(0x0F, 0x00)
    a.b(0x58)                                   # CLI
    cmd(0x0D, 0x81)
    delay(200)
    a.b(0xA5, COUNT); a.cmp(0); a.bne("fail7")
    delay(110)
    a.b(0xA5, COUNT); a.cmp(1); a.bne("fail8")
    a.label("pass")
    for status in (0, 2, 3, 4, 5, 6, 7, 8):
        if status:
            a.label("fail%d" % status)
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)
    a.label("irq")
    a.b(0x48, 0xE6, COUNT)                      # PHA; INC COUNT
    a.lda(0x0D); a.sta(0x8000)
    a.lda(0x00); a.sta(0xA000)                  # acknowledge, and stop
    a.b(0x68, 0x40)                             # PLA; RTI
    a.label("nmi")
    a.b(0x40)
    code = a.done()

    prg = bytearray()
    for bank in range(16):
        b = bytearray(0x2000)
        b[TAG] = bank
        prg += b
    last = 15 * 0x2000
    assert len(code) < TAG
    prg[last:last + len(code)] = code
    prg[last + TAG] = 15
    for vec, label in ((0x1FFA, "nmi"), (0x1FFC, "reset"), (0x1FFE, "irq")):
        t = a.labels[label]
        prg[last + vec] = t & 0xFF
        prg[last + vec + 1] = t >> 8
    chr_rom = bytearray()
    for bank in range(64):
        c = bytearray(0x400)
        c[0] = bank
        chr_rom += c
    header = bytes([0x4E, 0x45, 0x53, 0x1A, len(prg) // 0x4000,
                    len(chr_rom) // 0x2000, 0x52, 0x40]) + bytes(8)  # 69, battery
    with open(path, "wb") as f:
        f.write(header + prg + chr_rom)
    print("wrote", path)


def main():
    notes = tone_notes()
    tone_rom(os.path.join(HERE, "fme7_tones.nes"), [n for n, _ in notes],
             mapper=69)
    tone_nsf(os.path.join(HERE, "nsf_5b.nsf"), [n for n, _ in notes], chips=32)
    print("expected:", ",".join(e for _, e in notes))
    banking_rom(os.path.join(HERE, "fme7.nes"))


if __name__ == "__main__":
    main()
