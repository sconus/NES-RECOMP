#!/usr/bin/env python3
"""Write VRC6 tests made for nesrecomp, for mappers 24 and 26 (the same
chip with address lines A0 and A1 swapped). Run it again to regenerate.

tests/vrc6_tones_24.nes, vrc6_tones_26.nes: notes for the "tones" check
(see make_tone_test.py). Expected values, from the nesdev wiki's "VRC6
audio": pulse pitch CPU / (16 (t + 1)), sawtooth CPU / (14 (t + 1)); a
full-volume VRC6 pulse is as loud as a full-volume APU pulse, and the DAC
is linear.

  1  APU pulse 1, period 253, volume 15                  reference
  2  VRC6 pulse 1, period 253, duty 8/16, volume 15      1.0
  3  ... volume 7                    0.467 (linear: 7/15; the APU's
                                     non-linear mix would give 0.509)
  4  ... duty 4/16                   0.866 (RMS of 25% vs 50%)
  5  ... duty 1/16                   0.484 (sqrt(1/16 * 15/16) / 0.5)
  6  VRC6 pulse 2, as note 2         1.0
  7  VRC6 pulse 1, period 4063, with $9003 = 2 (16x: period 253)   1.0
  8  sawtooth, rate 42, period 290 (439.3 Hz)                      pitch
  9  sawtooth, rate 21               0.494 as loud as note 8 (the RMS of
                                     its 5-bit steps, 0 2 5 7 10 13 15,
                                     against 0 5 10 15 21 26 31)

tests/vrc6_24.nes, vrc6_26.nes: banking and IRQ, blargg $6000 protocol:
   0  passed
   2  16 KB PRG bank 3 isn't at $8000-$BFFF
   3  8 KB PRG bank 5 isn't at $C000
   4  CHR bank $15 isn't at PPU $0C00
   5  $B003 = $08 (one-screen low): $2000 and $2400 aren't the same
   6  IRQ, cycle mode, latch $00: fired well before 256 cycles
   7  ... and not fired well after
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402
from make_tone_test import (tone_rom, apu_pulse, pulse_hz, CPU_HZ,  # noqa: E402
                            APU_PULSE_MIX, apu_pulse_wave, level)

COUNT = 0x10                    # zero page: IRQs taken
TAG = 0x1FF0                    # bank number, in each 8 KB bank


def reg(mapper, addr):
    """The CPU address of VRC6 register `addr` on this mapper."""
    if mapper == 26:
        addr = (addr & ~3) | (addr & 1) << 1 | (addr >> 1 & 1)
    return addr


def vrc6_pulse(mapper, channel, period, duty=7, volume=15):
    base = 0x9000 + 0x1000 * channel
    start = [(reg(mapper, base), duty << 4 | volume),
             (reg(mapper, base + 1), period & 0xFF),
             (reg(mapper, base + 2), 0x80 | period >> 8)]
    stop = [(reg(mapper, base + 2), 0x00)]
    return start, stop


def vrc6_saw(mapper, period, rate):
    start = [(reg(mapper, 0xB000), rate),
             (reg(mapper, 0xB001), period & 0xFF),
             (reg(mapper, 0xB002), 0x80 | period >> 8)]
    stop = [(reg(mapper, 0xB002), 0x00)]
    return start, stop


VRC6_UNIT = APU_PULSE_MIX[15] / 15     # a full VRC6 pulse = a full APU pulse


def vrc6_pulse_wave(duty=7, volume=15):
    return [VRC6_UNIT * volume * (s <= duty) for s in range(16)]


def vrc6_saw_wave(rate):
    """The 14 steps of one sawtooth period: the accumulator is reset, then
    the rate is added on every other clock; the output is its top 5 bits."""
    acc, out = 0, []
    for clock in range(14):
        if clock == 0:
            acc = 0
        elif clock % 2 == 0:
            acc = (acc + rate) & 0xFF
        out.append(VRC6_UNIT * (acc >> 3))
    return out


def tone_notes(mapper):
    p = pulse_hz(253)
    saw = CPU_HZ / (14.0 * 291)
    ref = apu_pulse_wave()

    def lvl(wave, hz):
        return level(wave, hz, ref, p)
    shifted = vrc6_pulse(mapper, 0, 4063)
    shifted = ([(reg(mapper, 0x9003), 0x02)] + shifted[0],
               shifted[1] + [(reg(mapper, 0x9003), 0x00)])
    return [
        (apu_pulse(0, 253), "%.1f@1" % p),
        (vrc6_pulse(mapper, 0, 253), "%.1f@%s" % (p, lvl(vrc6_pulse_wave(), p))),
        (vrc6_pulse(mapper, 0, 253, volume=7),
         "%.1f@%s" % (p, lvl(vrc6_pulse_wave(volume=7), p))),
        (vrc6_pulse(mapper, 0, 253, duty=3),
         "%.1f@%s" % (p, lvl(vrc6_pulse_wave(duty=3), p))),
        (vrc6_pulse(mapper, 0, 253, duty=0),
         "%.1f@%s" % (p, lvl(vrc6_pulse_wave(duty=0), p))),
        (vrc6_pulse(mapper, 1, 253), "%.1f@%s" % (p, lvl(vrc6_pulse_wave(), p))),
        (shifted, "%.1f@%s" % (pulse_hz(4063 >> 4), lvl(vrc6_pulse_wave(), p))),
        (vrc6_saw(mapper, 290, 42), "%.1f@%s" % (saw, lvl(vrc6_saw_wave(42), saw))),
        (vrc6_saw(mapper, 290, 21), "%.1f@%s" % (saw, lvl(vrc6_saw_wave(21), saw))),
    ]


def banking_rom(mapper, path):
    a = Asm(0xE000)
    r = lambda addr: reg(mapper, addr)  # noqa: E731

    def delay(n):
        a.b(0xA0, max(1, n // 5), 0x88, 0xD0, 0xFD)

    a.label("reset")
    a.b(0x78, 0xA2, 0xFF, 0x9A)
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)
    a.lda(0x00); a.sta(0x6004)
    a.b(0x85, COUNT)
    a.sta(r(0xF001))                            # IRQ off
    a.lda(3); a.sta(r(0x8000))                  # 16 KB bank 3: 8 KB 6, 7
    a.check(0x9FF0, 6, "fail2"); a.check(0xBFF0, 7, "fail2")
    a.lda(5); a.sta(r(0xC000))
    a.check(0xDFF0, 5, "fail3")
    a.lda(0x15); a.sta(r(0xD003))               # PPU $0C00
    a.lda(0x0C); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.lda_abs(0x2007); a.lda_abs(0x2007)
    a.cmp(0x15); a.bne("fail4")
    a.lda(0x28); a.sta(r(0xB003))               # mode 0, one-screen low
    a.lda(0x20); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.lda(0x5A); a.sta(0x2007)
    a.lda(0x24); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.lda_abs(0x2007); a.lda_abs(0x2007)
    a.cmp(0x5A); a.bne("fail5")
    # IRQ, cycle mode, latch $00: passes $FF 256 cycles after the write.
    a.lda(0x00); a.sta(r(0xF000))
    a.b(0x58)                                   # CLI
    a.lda(0x06); a.sta(r(0xF001))
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
    a.b(0x48, 0xE6, COUNT)                      # PHA; INC COUNT
    a.sta(r(0xF002))                            # acknowledge (E = A = 0)
    a.b(0x68, 0x40)                             # PLA; RTI
    a.label("nmi")
    a.b(0x40)
    code = a.done()

    prg = bytearray()
    for bank in range(16):                      # 128 KB
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
    for bank in range(64):                      # 64 KB of 1 KB banks
        c = bytearray(0x400)
        c[0] = bank
        chr_rom += c
    header = bytes([0x4E, 0x45, 0x53, 0x1A, len(prg) // 0x4000,
                    len(chr_rom) // 0x2000, (mapper & 0x0F) << 4,
                    mapper & 0xF0]) + bytes(8)
    with open(path, "wb") as f:
        f.write(header + prg + chr_rom)
    print("wrote", path)


def main():
    for mapper in (24, 26):
        notes = tone_notes(mapper)
        tone_rom(os.path.join(HERE, "vrc6_tones_%d.nes" % mapper),
                 [n for n, _ in notes], mapper=mapper,
                 setup=[(reg(mapper, 0x9003), 0x00), (reg(mapper, 0xB003), 0x20)])
        print("expected:", ",".join(e for _, e in notes))
        banking_rom(mapper, os.path.join(HERE, "vrc6_%d.nes" % mapper))


if __name__ == "__main__":
    main()
