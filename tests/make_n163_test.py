#!/usr/bin/env python3
"""Write Namco 163 tests (mapper 19) made for nesrecomp. Run it again to
regenerate them.

tests/n163.nes: banking, IRQ and sound RAM, blargg $6000 protocol:
   0  passed
   2  8 KB PRG banks 4, 5, 6 aren't at $8000, $A000, $C000
   3  CHR bank $15 isn't at PPU $0C00
   4  CHR value $E0 (nametable RAM page 0) at PPU $0000: a byte written
      to $2000 doesn't appear at $0000
   5  nametables $C000-$D800 = $E0 $E0 $E1 $E1 (horizontal): $2000 and
      $2400 aren't the same
   6  sound RAM: bytes written through $4800 (auto-increment) don't read
      back
   7  IRQ, counter $7FFF - 255: fired well before 255 cycles
   8  ... and not fired well after
   9  $5000 doesn't read back the counter (which stops at $7FFF)

tests/n163_tones.nes: notes for the "tones" check (make_tone_test.py),
from the nesdev wiki's "Namco 163 audio": f = CPU * p / (15 * 65536 *
length * channels); output (sample - 8) * volume, averaged over the
enabled channels; a full one-channel square 16.5 dB above a full APU
square (the middle of the 16-17 dB measured on boards like Rolling
Thunder).

  1  APU pulse, 440.4 Hz                              reference
  2  one channel (8), a 16-sample square (8 x 15, 8 x 0), p = 3867
     (440.0 Hz), volume 15                          16.5 dB: 6.68x
  3  ... volume 7                                   7/15 of note 2
  4  two channels, 8 playing (p doubled), 7 silent: averaged, 1/2
  5  two channels, 7 playing, 8 silent              1/2
  6  one channel, a 16-sample ramp 0..15            from its waveform
  7  one channel, a 25% square stored at wave address 32
Loudness is computed from the waveforms through the output filter model.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402
from make_tone_test import (tone_rom, apu_pulse, apu_pulse_wave,  # noqa: E402
                            pulse_hz, CPU_HZ, level)

COUNT = 0x10
TAG = 0x1FF0
UNIT = 0.1494 * 6.683 / 225     # one step of (sample - 8) * volume

SQUARE = [15] * 8 + [0] * 8
RAMP = list(range(16))
QUARTER = [15] * 4 + [0] * 12


def pack(samples):
    """Nibbles to bytes, low nibble first."""
    return [samples[i] | samples[i + 1] << 4 for i in range(0, len(samples), 2)]


def ram_writes(addr, data):
    """Write sound RAM from addr, through the auto-incrementing port."""
    return [(0xF800, 0x80 | addr)] + [(0x4800, b) for b in data]


def channel_regs(ch, freq, length, wave_addr, volume, count):
    """The 8 register bytes of channel ch (1-8)."""
    top = ((count - 1) << 4) if ch == 8 else 0
    return [freq & 0xFF, 0, (freq >> 8) & 0xFF, 0,
            (256 - length) & 0xFC | (freq >> 16) & 3, 0, wave_addr,
            top | volume]


def note(channels, count):
    """channels: {ch: (freq, length, wave_addr, volume)}. Writes every
    enabled channel's registers (silent ones at volume 0)."""
    start, stop = [], []
    for ch in range(8, 8 - count, -1):
        f, ln, wa, v = channels.get(ch, (0, 16, 0, 0))
        regs = channel_regs(ch, f, ln, wa, v, count)
        base = 0x40 + 8 * (ch - 1)
        start += ram_writes(base, regs)
        quiet = channel_regs(ch, 0, ln, wa, 0, count)
        stop += ram_writes(base + 7, [quiet[7]])
    return start, stop


def hz(p, length, count):
    return CPU_HZ * p / (15 * 65536 * length * count)


def wave_level(samples, volume, count=1):
    return [UNIT * (s - 8) * volume / count for s in samples]


def tone_notes():
    ref = apu_pulse_wave()
    a = pulse_hz(253)
    f1 = hz(3867, 16, 1)
    f2 = hz(7734, 16, 2)

    def lvl(samples, volume, f, count=1, rel=None):
        if rel is None:
            return level(wave_level(samples, volume, count), f, ref, a)
        r_samples, r_vol, r_f, r_count = rel
        return level(wave_level(samples, volume, count), f,
                     wave_level(r_samples, r_vol, r_count), r_f)

    n2 = (SQUARE, 15, f1, 1)
    return [
        (apu_pulse(0, 253), "%.1f@1" % a),
        (note({8: (3867, 16, 0, 15)}, 1), "%.1f@%s" % (f1, lvl(SQUARE, 15, f1))),
        (note({8: (3867, 16, 0, 7)}, 1), "%.1f@%s/2" % (f1, lvl(SQUARE, 7, f1, rel=n2))),
        (note({8: (7734, 16, 0, 15)}, 2), "%.1f@%s/2" % (f2, lvl(SQUARE, 15, f2, 2, rel=n2))),
        (note({7: (7734, 16, 0, 15)}, 2), "%.1f@%s/2" % (f2, lvl(SQUARE, 15, f2, 2, rel=n2))),
        (note({8: (3867, 16, 16, 15)}, 1), "%.1f@%s/2" % (f1, lvl(RAMP, 15, f1, rel=n2))),
        (note({8: (3867, 16, 32, 15)}, 1), "%.1f@%s/2" % (f1, lvl(QUARTER, 15, f1, rel=n2))),
    ]


def tone_setup():
    # Waveforms: the square at sample 0, the ramp at 16, the 25% square at
    # 32 (bytes 0, 8, 16). Sound on ($E000 bit 6 clear).
    return ([(0xE000, 0x00)] + ram_writes(0, pack(SQUARE)) +
            ram_writes(8, pack(RAMP)) + ram_writes(16, pack(QUARTER)))


def banking_rom(path):
    a = Asm(0xE000)

    def delay(n):
        a.b(0xA0, max(1, n // 5), 0x88, 0xD0, 0xFD)

    def ppu_addr(x):
        a.lda(x >> 8); a.sta(0x2006); a.lda(x & 0xFF); a.sta(0x2006)

    a.label("reset")
    a.b(0x78, 0xA2, 0xFF, 0x9A)
    a.lda(0x40); a.sta(0xF800)                  # PRG RAM writable
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)
    a.lda(0x00); a.sta(0x6004)
    a.b(0x85, COUNT)
    a.sta(0x5800)                               # IRQ off
    a.lda(0x04); a.sta(0xE000)
    a.lda(0x05); a.sta(0xE800)
    a.lda(0x06); a.sta(0xF000)
    a.check(0x9FF0, 4, "fail2"); a.check(0xBFF0, 5, "fail2")
    a.check(0xDFF0, 6, "fail2")
    a.lda(0x15); a.sta(0x9800)                  # PPU $0C00
    ppu_addr(0x0C00); a.lda_abs(0x2007); a.lda_abs(0x2007)
    a.cmp(0x15); a.bne("fail3")
    # Nametable RAM page 0 as CHR at $0000 ($E800 bit 6 is clear).
    a.lda(0xE0); a.sta(0x8000)
    a.lda(0xE0); a.sta(0xC000)                  # $2000 = page 0
    ppu_addr(0x2000); a.lda(0x6B); a.sta(0x2007)
    ppu_addr(0x0000); a.lda_abs(0x2007); a.lda_abs(0x2007)
    a.cmp(0x6B); a.bne("fail4")
    # Horizontal: $2000/$2400 page 0, $2800/$2C00 page 1.
    a.lda(0xE0); a.sta(0xC800)
    a.lda(0xE1); a.sta(0xD000); a.sta(0xD800)
    ppu_addr(0x2010); a.lda(0x5A); a.sta(0x2007)
    ppu_addr(0x2410); a.lda_abs(0x2007); a.lda_abs(0x2007)
    a.cmp(0x5A); a.bne("fail5")
    # Sound RAM: write $11 $22 $33 at $10, read back.
    a.lda(0x90); a.sta(0xF800)
    for v in (0x11, 0x22, 0x33):
        a.lda(v); a.sta(0x4800)
    a.lda(0x90); a.sta(0xF800)
    for v in (0x11, 0x22, 0x33):
        a.lda_abs(0x4800); a.cmp(v); a.bne("fail6")
    # IRQ: counter $7FFF - 255 reaches $7FFF 255 cycles later.
    a.lda(0x00); a.sta(0x5000)                  # low byte $00
    a.b(0x58)                                   # CLI
    a.lda(0xFF); a.sta(0x5800)                  # high $7F, enabled: $7F00
    delay(200)
    a.b(0xA5, COUNT); a.cmp(0); a.bne("fail7")
    delay(110)
    a.b(0xA5, COUNT); a.cmp(1); a.bne("fail8")
    a.lda_abs(0x5000); a.cmp(0xFF); a.bne("fail9")
    a.label("pass")
    for status in range(0, 10):
        if status == 1:
            continue
        if status:
            a.label("fail%d" % status)
        # $F800 is also the PRG RAM write protect: the sound RAM address
        # written above made $6000 read-only, so make it writable again.
        a.lda(0x40); a.sta(0xF800)
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)
    a.label("irq")
    a.b(0x48, 0xE6, COUNT)                      # PHA; INC COUNT
    a.lda(0xFF); a.sta(0x5800)                  # acknowledge (stays at $7FFF)
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
                    len(chr_rom) // 0x2000, 0x32, 0x10]) + bytes(8)  # 19, battery
    with open(path, "wb") as f:
        f.write(header + prg + chr_rom)
    print("wrote", path)


def main():
    notes = tone_notes()
    tone_rom(os.path.join(HERE, "n163_tones.nes"), [n for n, _ in notes],
             mapper=19, setup=tone_setup())
    print("expected:", ",".join(e for _, e in notes))
    banking_rom(os.path.join(HERE, "n163.nes"))


if __name__ == "__main__":
    main()
