#!/usr/bin/env python3
"""Tone test ROMs for nesrecomp's "tones" check (tests/run_tests.py).

A tone ROM plays a list of notes, one at a time, each for NOTE_FRAMES
frames with GAP_FRAMES of silence after it, by writing sound registers.
The runner records the sound and measures each note's pitch and loudness
(relative to the first note). Other generators (one per sound chip)
import tone_rom() and describe their notes; run this file to write
tests/apu_tones.nes, which uses only the APU and proves the check itself.

apu_tones.nes plays, on the APU pulse channels (constant volume, the
length counter halted):

  1  pulse 1, period 253 (440.4 Hz), 50% duty, volume 15   reference
  2  pulse 1, period 126 (880.8 Hz)                        pitch only
  3  pulse 1, 440.4 Hz, volume 7     0.509 as loud (the APU's non-linear
                                     pulse mix: 7 vs 15 gives 0.0760 / 0.1494)
  4  pulse 1, 440.4 Hz, 25% duty     0.866 as loud (RMS of a 25% vs a
                                     50% square: sqrt(0.25 * 0.75) / 0.5)
  5  pulse 2, same as note 1         1.0
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_mmc1_test import Asm  # noqa: E402

NOTE_FRAMES = 30
GAP_FRAMES = 12
CPU_HZ = 1789773


def tone_rom(path, notes, mapper=0, setup=(), prg_kb=32, chr_kb=8,
             mirroring=0):
    """Write an iNES ROM at `path` that plays `notes`.

    notes: list of (start_writes, stop_writes), each a list of
    (address, value) register writes. setup: writes made once at reset
    (mapper set-up, sound chip enables). The program sits in the last
    8 KB of PRG ROM, which must be mapped at $E000 at power-on.
    """
    a = Asm(0xE000)

    def writes(ws):
        for addr, val in ws:
            a.lda(val); a.sta(addr)

    def wait_frames(n):
        # LDX #n; wait for the vblank flag (BIT $2002; BPL); DEX; BNE.
        a.b(0xA2, n, 0x2C, 0x02, 0x20, 0x10, 0xFB, 0xCA, 0xD0, 0xF8)

    a.label("reset")
    a.b(0x78, 0xD8, 0xA2, 0xFF, 0x9A)           # SEI; CLD; LDX #$FF; TXS
    a.lda(0x00); a.sta(0x2000); a.sta(0x2001)   # no NMI, no rendering
    a.lda(0x40); a.sta(0x4017)                  # no frame IRQ
    writes(setup)
    wait_frames(30)                             # let the output settle
    for start, stop in notes:
        writes(start)
        wait_frames(NOTE_FRAMES)
        writes(stop)
        wait_frames(GAP_FRAMES)
    a.label("done")
    here = a.pc()
    a.b(0x4C, here & 0xFF, here >> 8)           # JMP to itself
    a.label("rti")
    a.b(0x40)
    code = a.done()

    prg = bytearray(prg_kb * 1024)
    last = len(prg) - 0x2000
    assert len(code) < 0x1FF0
    prg[last:last + len(code)] = code
    for vec, label in ((0x1FFA, "rti"), (0x1FFC, "reset"), (0x1FFE, "rti")):
        t = a.labels[label]
        prg[last + vec] = t & 0xFF
        prg[last + vec + 1] = t >> 8
    header = bytes([0x4E, 0x45, 0x53, 0x1A, prg_kb // 16, chr_kb // 8,
                    (mapper & 0x0F) << 4 | mirroring, mapper & 0xF0]) + bytes(8)
    with open(path, "wb") as f:
        f.write(header + prg + bytes(chr_kb * 1024))
    print("wrote", path)


def apu_pulse(channel, period, duty=2, volume=15):
    """Start and stop writes for an APU pulse note (constant volume,
    length counter halted, no sweep)."""
    base = 0x4000 + 4 * channel
    ctrl = duty << 6 | 0x30
    start = [(0x4015, 0x03), (base + 1, 0x08), (base, ctrl | volume),
             (base + 2, period & 0xFF), (base + 3, period >> 8)]
    stop = [(base, ctrl)]                       # volume 0
    return start, stop


def pulse_hz(period):
    return CPU_HZ / (16.0 * (period + 1))


APU_NOTES = [
    (apu_pulse(0, 253), "%.1f@1" % pulse_hz(253)),
    (apu_pulse(0, 126), "%.1f@-" % pulse_hz(126)),
    (apu_pulse(0, 253, volume=7), "%.1f@0.509" % pulse_hz(253)),
    (apu_pulse(0, 253, duty=1), "%.1f@0.866" % pulse_hz(253)),
    (apu_pulse(1, 253), "%.1f@1" % pulse_hz(253)),
]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    tone_rom(os.path.join(here, "apu_tones.nes"), [n for n, _ in APU_NOTES])
    print("expected:", ",".join(e for _, e in APU_NOTES))


if __name__ == "__main__":
    main()
