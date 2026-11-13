#!/usr/bin/env python3
"""Write tests/joy2.nes and its input script tests/inputs/joy2.txt: a
two-controller test made for nesrecomp. Run it again to regenerate both.

The ROM counts frames in its NMI handler. At set frames it reads both
controllers (strobe $4016, then 8 reads each of $4016 and $4017) and
compares them with what the script holds at that point; it also checks
that a 9th read returns 1, as on an official controller. The script
changes the buttons 10 frames before each read.

Results use the blargg $6000 protocol; status 0 = passed, otherwise
2 * check + 2 for controller 1 wrong, 2 * check + 3 for controller 2:

  check 0 (frame 30):  1: A          2: B
  check 1 (frame 50):  1: Up Start   2: Left Select
  check 2 (frame 70):  1: none       2: all eight
  check 3 (frame 90):  1: all eight  2: none
  check 4 (frame 110): both released
  12  a 9th read of $4016 didn't return 1
  13  with the strobe held at 1, reads didn't keep returning A
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402

FRAMES = 0x10                   # zero page: NMI count
PAD = 0x11                      # zero page: the two bytes read

NAMES = ["a", "b", "select", "start", "up", "down", "left", "right"]
CHECKS = [                      # (frame, controller 1 buttons, controller 2)
    (30, ["a"], ["b"]),
    (50, ["up", "start"], ["left", "select"]),
    (70, [], NAMES),
    (90, NAMES, []),
    (110, [], []),
]


def as_read(buttons):
    """The byte the ROM builds: 8 reads, each shifted in from the right
    with ROL, so A (read first) ends in bit 7."""
    v = 0
    for i, n in enumerate(NAMES):
        if n in buttons:
            v |= 0x80 >> i
    return v


def rom():
    a = Asm(0xE000)
    a.label("reset")
    a.b(0x78, 0xD8, 0xA2, 0xFF, 0x9A)           # SEI; CLD; LDX #$FF; TXS
    a.lda(0x40); a.sta(0x4017)                  # no APU frame IRQ
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)
    a.lda(0x00); a.sta(0x6004)
    a.b(0x85, FRAMES)
    for _ in range(2):                          # PPU warm-up
        a.b(0x2C, 0x02, 0x20, 0x10, 0xFB)       # BIT $2002; BPL
    a.lda(0x80); a.sta(0x2000)                  # NMI on

    for i, (frame, p1, p2) in enumerate(CHECKS):
        # Wait for the NMI count: LDA FRAMES; CMP #frame; BCC back.
        a.b(0xA5, FRAMES, 0xC9, frame, 0x90, 0xFA)
        a.jsr_label("read")
        a.b(0xA5, PAD); a.cmp(as_read(p1)); a.bne("fail%d" % (2 * i + 2))
        a.b(0xA5, PAD + 1); a.cmp(as_read(p2)); a.bne("fail%d" % (2 * i + 3))
        if i == 0:
            # A is held on controller 1: with the strobe left at 1, every
            # read keeps returning A's state.
            a.lda(0x01); a.sta(0x4016)
            for _ in range(3):
                a.lda_abs(0x4016); a.b(0x29, 0x01); a.cmp(0x01); a.bne("fail13")
            a.lda(0x00); a.sta(0x4016)
    # A 9th read of $4016 after the last 8.
    a.lda_abs(0x4016); a.b(0x29, 0x01); a.cmp(0x01); a.bne("fail12")

    a.label("pass")
    statuses = [0] + list(range(2, 2 * len(CHECKS) + 2)) + [12, 13]
    for status in statuses:
        if status:
            a.label("fail%d" % status)
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)

    a.label("read")                             # PAD, PAD+1 = both controllers
    a.lda(0x01); a.sta(0x4016); a.lda(0x00); a.sta(0x4016)
    for port, dest in ((0x4016, PAD), (0x4017, PAD + 1)):
        a.b(0xA2, 0x08)                         # LDX #8
        loop = a.pc()
        a.lda_abs(port)
        a.b(0x4A)                               # LSR A (bit 0 to carry)
        a.b(0x26, dest)                         # ROL dest
        a.b(0xCA)                               # DEX
        a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF) # BNE loop
    a.rts()

    a.label("nmi")
    a.b(0xE6, FRAMES, 0x40)                     # INC FRAMES; RTI
    code = a.done()

    prg = bytearray(0x8000)
    prg[0x6000:0x6000 + len(code)] = code
    for vec, label in ((0x7FFA, "nmi"), (0x7FFC, "reset"), (0x7FFE, "nmi")):
        t = a.labels[label]
        prg[vec] = t & 0xFF
        prg[vec + 1] = t >> 8
    return bytes([0x4E, 0x45, 0x53, 0x1A, 2, 1, 0, 0]) + bytes(8) + prg + bytes(0x2000)


def script():
    lines = ["# For tests/joy2.nes (make_joy_test.py): buttons on both",
             "# controllers, changed 10 frames before each of the ROM's checks."]
    for frame, p1, p2 in CHECKS:
        tokens = p1 + ["2:" + n for n in p2]
        lines.append(" ".join([str(frame - 10)] + tokens))
    return "\n".join(lines) + "\n"


def main():
    path = os.path.join(HERE, "joy2.nes")
    with open(path, "wb") as f:
        f.write(rom())
    print("wrote", path)
    spath = os.path.join(HERE, "inputs", "joy2.txt")
    with open(spath, "w") as f:
        f.write(script())
    print("wrote", spath)


if __name__ == "__main__":
    main()
