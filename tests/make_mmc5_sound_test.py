#!/usr/bin/env python3
"""Write MMC5 sound tests (mapper 5) made for nesrecomp. Run it again to
regenerate them. From the nesdev wiki's "MMC5 audio": two pulses like the
APU's ($5000-$5007), as loud as the APU's for the same values (inverted),
with envelope and length counter clocked at a fixed 240 Hz; an 8-bit PCM
channel at $5011, as loud as the APU's DMC for the same value, where a
write of 0 is ignored but trips the PCM IRQ.

tests/mmc5_sound.nes: blargg $6000 protocol:
   0  passed
   2  length count 20 ran out within 100,000 cycles (240 Hz would take
      148,480)
   3  ... and hadn't run out after 180,000 (so it's clocked slower than
      240 Hz, e.g. at the APU's 120 Hz)
   4  $5015 = 0 didn't clear the length counter
   5  writing 0 to $5011 with $5010 bit 7 set didn't cause an IRQ
   6  $5010 didn't read $80 in the IRQ handler
   7  writing a non-zero value to $5011 caused an IRQ

tests/mmc5_tones.nes: notes for the "tones" check (make_tone_test.py):
  1  APU pulse 1, 440.4 Hz                         reference
  2  MMC5 pulse 1, the same settings               1.0 (same volume)
  3  MMC5 pulse 2                                  1.0
  4  MMC5 pulse 1, volume 7                        0.509 (the APU's curve)
  5  PCM: the CPU writes $E0 and $20 alternately, 4071 cycles a period
     (439.6 Hz); loudness from the DMC's mixing curve
  6  PCM writing $C0 and $00: the $00 writes are ignored, so it's silent
     and not counted
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402
from make_tone_test import (tone_rom, tone_nsf, apu_pulse, apu_pulse_wave,  # noqa: E402
                            pulse_hz, CPU_HZ, level)

COUNT = 0x10
FLAG = 0x11


def mmc5_pulse(channel, period, volume=15, duty=2):
    base = 0x5000 + 4 * channel
    ctrl = duty << 6 | 0x30                     # halt length, constant volume
    start = [(0x5015, 0x03), (base, ctrl | volume),
             (base + 2, period & 0xFF), (base + 3, period >> 8)]
    return start, [(base, ctrl)]


def dmc_level(v):
    """The APU's mix for the DMC alone at level v (the MMC5 PCM's is the
    same for the same value)."""
    return 0.0 if v == 0 else 159.79 / (1.0 / (v / 22638.0) + 100.0)


PCM_PERIOD = 21 + 10 * 405                      # cycles (see pcm_note)
PCM_REPEATS = 220


def pcm_note(high, low):
    """A routine writing high and low to $5011, each held half a period:
    LDA #v; STA $5011; LDX #a; DEX; BNE; LDX #b; DEX; BNE (8 + 5 (a + b)
    cycles a half), twice, then DEY; BNE: 21 + 10 (a + b) cycles."""
    def emit(a):
        a.b(0xA0, PCM_REPEATS)                  # LDY #repeats
        top = a.pc()
        for v in (high, low):
            a.lda(v); a.sta(0x5011)
            a.b(0xA2, 200, 0xCA, 0xD0, 0xFD)    # LDX #200; DEX; BNE
            a.b(0xA2, 205, 0xCA, 0xD0, 0xFD)    # LDX #205; DEX; BNE
        a.b(0x88)                               # DEY
        off = top - (a.pc() + 2)
        a.b(0xD0, off & 0xFF)                   # BNE top
    return emit


def tone_notes():
    p = pulse_hz(253)
    ref = apu_pulse_wave()
    pcm_hz = CPU_HZ / PCM_PERIOD
    pcm_wave = [dmc_level(0xE0), dmc_level(0x20)]
    return [
        (apu_pulse(0, 253), "%.1f@1" % p),
        (mmc5_pulse(0, 253), "%.1f@%s" % (p, level(apu_pulse_wave(), p, ref, p))),
        (mmc5_pulse(1, 253), "%.1f@%s" % (p, level(apu_pulse_wave(), p, ref, p))),
        (mmc5_pulse(0, 253, 7), "%.1f@%s" % (p, level(apu_pulse_wave(volume=7), p, ref, p))),
        ((pcm_note(0xE0, 0x20), [(0x5011, 0x80)]),
         "%.1f@%s" % (pcm_hz, level(pcm_wave, pcm_hz, ref, p))),
        ((pcm_note(0xC0, 0x00), [(0x5011, 0x80)]), None),
    ]


def status_rom(path):
    a = Asm(0xE000)

    def delay_k(k):
        """About 1285 * k cycles."""
        a.b(0xA0, k, 0xA2, 0x00, 0xCA, 0xD0, 0xFD, 0x88, 0xD0, 0xF8)

    a.label("reset")
    a.b(0x78, 0xA2, 0xFF, 0x9A)
    a.lda(0x40); a.sta(0x4017)                  # no APU frame IRQ
    a.lda(0x02); a.sta(0x5102); a.lda(0x01); a.sta(0x5103)  # RAM writable
    a.lda(0x00); a.sta(0x5113)
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)
    a.lda(0x00); a.sta(0x6004)
    a.b(0x85, COUNT)
    # Length index 2 (count 20), not halted, constant volume.
    a.lda(0x01); a.sta(0x5015)
    a.lda(0x1F); a.sta(0x5000)
    a.lda(0xFD); a.sta(0x5002)
    a.lda(0x10); a.sta(0x5003)
    delay_k(78)                                 # ~100,000 cycles
    a.lda_abs(0x5015); a.b(0x29, 0x01); a.cmp(0x01); a.bne("fail2")
    delay_k(62)                                 # ~180,000 in all
    a.lda_abs(0x5015); a.b(0x29, 0x01); a.cmp(0x00); a.bne("fail3")
    a.lda(0x10); a.sta(0x5003)                  # count 20 again
    a.lda(0x00); a.sta(0x5015)
    a.lda_abs(0x5015); a.b(0x29, 0x01); a.cmp(0x00); a.bne("fail4")
    # PCM IRQ.
    a.lda(0x80); a.sta(0x5010)                  # IRQ on, write mode
    a.b(0x58)                                   # CLI
    a.lda(0x40); a.sta(0x5011)                  # non-zero: no IRQ
    a.b(0xA5, COUNT); a.cmp(0); a.bne("fail7")
    a.lda(0x00); a.sta(0x5011)                  # zero: IRQ
    a.b(0xEA, 0xEA)                             # NOP NOP
    a.b(0xA5, COUNT); a.cmp(1); a.bne("fail5")
    a.b(0xA5, FLAG); a.cmp(0x80); a.bne("fail6")
    a.label("pass")
    for status in (0, 2, 3, 4, 5, 6, 7):
        if status:
            a.label("fail%d" % status)
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)
    a.label("irq")
    a.b(0x48, 0xE6, COUNT)                      # PHA; INC COUNT
    a.lda_abs(0x5010); a.b(0x85, FLAG)          # acknowledge, keep the value
    a.b(0x68, 0x40)                             # PLA; RTI
    a.label("nmi")
    a.b(0x40)
    code = a.done()

    prg = bytearray(0x8000)
    last = 0x6000
    prg[last:last + len(code)] = code
    for vec, label in ((0x1FFA, "nmi"), (0x1FFC, "reset"), (0x1FFE, "irq")):
        t = a.labels[label]
        prg[last + vec] = t & 0xFF
        prg[last + vec + 1] = t >> 8
    header = bytes([0x4E, 0x45, 0x53, 0x1A, 2, 1, 0x50, 0x00]) + bytes(8)  # 5
    with open(path, "wb") as f:
        f.write(header + prg + bytes(0x2000))
    print("wrote", path)


def main():
    notes = tone_notes()
    tone_rom(os.path.join(HERE, "mmc5_tones.nes"), [n for n, _ in notes], mapper=5)
    tone_nsf(os.path.join(HERE, "nsf_mmc5.nsf"), [n for n, _ in notes], chips=8)
    print("expected:", ",".join(e for _, e in notes if e))
    status_rom(os.path.join(HERE, "mmc5_sound.nes"))


if __name__ == "__main__":
    main()
