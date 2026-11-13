#!/usr/bin/env python3
"""Write Konami VRC7 tests (mapper 85) made for nesrecomp. Run it again to
regenerate them.

tests/vrc7.nes: banking and IRQ, writing through both the VRC7a (A4,
$x010) and VRC7b (A3, $x008) addresses; blargg $6000 protocol:
   0  passed
   2  8 KB PRG banks 4 ($8000), 5 ($8010), 6 ($9000) aren't in place
   3  PRG bank 7 through $8008 (VRC7b) isn't at $A000
   4  CHR bank $15 through $B010 isn't at PPU $0C00
   5  $E000 = 2 (one-screen low): $2000 and $2400 aren't the same
   6  IRQ, cycle mode, latch $00: fired well before 256 cycles
   7  ... and not fired well after

tests/vrc7_tones.nes: notes for the "tones" check (make_tone_test.py).
A custom instrument that's nearly a pure sine: the modulator at total
level 63 (-47 dB), feedback 0, both operators attack 15, decay 0,
sustained. From the nesdev wiki's "VRC7 audio": f = 49716 Hz * F /
2^(19 - octave) times the multiplier; volume 3 dB a step. How loud the
VRC7 is against the APU isn't documented, so loudness is only checked
between VRC7 notes:

  1  APU pulse, 440.4 Hz                       reference (not compared)
  2  channel 0, F 290, octave 4 (440.0 Hz), volume 0 (loudest)
  3  ... volume 4: -12 dB                      0.251 as loud as note 2
  4  ... carrier multiplier 2 (880.0 Hz)       a sine at 880 vs 440
  5  channel 5, as note 2                      1.0
  6  ... carrier half-sine waveform            computed from its shape
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402
from make_tone_test import tone_rom, tone_nsf, apu_pulse, pulse_hz, level  # noqa: E402

COUNT = 0x10
TAG = 0x1FF0

# The near-sine custom instrument, registers $00-$07.
PATCH = [0x21, 0x21, 0x3F, 0x00, 0xF0, 0xF0, 0x0F, 0x0F]


def opll(reg, val):
    return [(0x9010, reg), (0x9030, val)]


def fm_note(ch, fnum, octave, volume=0, patch_changes=()):
    start, stop = [], []
    for r, v in patch_changes:
        start += opll(r, v)
    start += opll(0x30 + ch, volume)
    start += opll(0x10 + ch, fnum & 0xFF)
    start += opll(0x20 + ch, 0x10 | octave << 1 | fnum >> 8)    # key on
    stop += opll(0x20 + ch, octave << 1 | fnum >> 8)            # key off
    for r, v in patch_changes:
        stop += opll(r, PATCH[r])
    return start, stop


def fm_hz(fnum, octave, mult=1):
    return 49716.0 * fnum / 2 ** (19 - octave) * mult


def sine(n=64, half=False):
    out = []
    for i in range(n):
        s = math.sin(2 * math.pi * (i + 0.5) / n)
        out.append(0.0 if half and s < 0 else s)
    return out


def tone_notes():
    p = pulse_hz(253)
    f = fm_hz(290, 4)
    f2 = fm_hz(290, 4, 2)
    return [
        (apu_pulse(0, 253), "%.1f@1" % p),
        (fm_note(0, 290, 4), "%.1f@-" % f),
        (fm_note(0, 290, 4, volume=4), "%.1f@%.3f/2" % (f, 10 ** (-12 / 20))),
        (fm_note(0, 290, 4, patch_changes=[(1, 0x22)]),
         "%.1f@%s/2" % (f2, level(sine(), f2, sine(), f))),
        (fm_note(5, 290, 4), "%.1f@1/2" % f),
        (fm_note(0, 290, 4, patch_changes=[(3, 0x10)]),
         "%.1f@%s/2" % (f, level(sine(half=True), f, sine(), f))),
    ]


def tone_setup():
    out = [(0xE000, 0x00)]                       # sound on
    for r, v in enumerate(PATCH):
        out += opll(r, v)
    return out


def banking_rom(path):
    a = Asm(0xE000)

    def delay(n):
        a.b(0xA0, max(1, n // 5), 0x88, 0xD0, 0xFD)

    a.label("reset")
    a.b(0x78, 0xA2, 0xFF, 0x9A)
    a.lda(0x40); a.sta(0x4017)
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)
    a.lda(0x00); a.sta(0x6004)
    a.b(0x85, COUNT)
    a.sta(0xF000)                                # IRQ off
    a.lda(4); a.sta(0x8000)
    a.lda(5); a.sta(0x8010)
    a.lda(6); a.sta(0x9000)
    a.check(0x9FF0, 4, "fail2"); a.check(0xBFF0, 5, "fail2")
    a.check(0xDFF0, 6, "fail2")
    a.lda(7); a.sta(0x8008)
    a.check(0xBFF0, 7, "fail3")
    a.lda(0x15); a.sta(0xB010)                   # PPU $0C00
    a.lda(0x0C); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.lda_abs(0x2007); a.lda_abs(0x2007)
    a.cmp(0x15); a.bne("fail4")
    a.lda(0x02); a.sta(0xE000)                   # one-screen low
    a.lda(0x20); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.lda(0x5A); a.sta(0x2007)
    a.lda(0x24); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.lda_abs(0x2007); a.lda_abs(0x2007)
    a.cmp(0x5A); a.bne("fail5")
    a.lda(0x00); a.sta(0xE010)                   # latch $00
    a.b(0x58)
    a.lda(0x06); a.sta(0xF000)                   # cycle mode, on
    delay(200)
    a.b(0xA5, COUNT); a.cmp(0); a.bne("fail6")
    delay(110)
    a.b(0xA5, COUNT); a.cmp(1); a.bne("fail7")
    a.label("pass")
    for status in (0, 2, 3, 4, 5, 6, 7):
        if status:
            a.label("fail%d" % status)
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)
    a.label("irq")
    a.b(0x48, 0xE6, COUNT)
    a.sta(0xF010)                                # acknowledge (E = A = 0)
    a.b(0x68, 0x40)
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
                    len(chr_rom) // 0x2000, 0x52, 0x50]) + bytes(8)  # 85
    with open(path, "wb") as f:
        f.write(header + prg + chr_rom)
    print("wrote", path)


def main():
    notes = tone_notes()
    tone_rom(os.path.join(HERE, "vrc7_tones.nes"), [n for n, _ in notes],
             mapper=85, setup=tone_setup())
    tone_nsf(os.path.join(HERE, "nsf_vrc7.nsf"), [n for n, _ in notes],
             chips=2, setup=tone_setup())
    print("expected:", ",".join(e for _, e in notes))
    banking_rom(os.path.join(HERE, "vrc7.nes"))


if __name__ == "__main__":
    main()
