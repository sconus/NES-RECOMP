#!/usr/bin/env python3
"""Write the four-player tests made for nesrecomp: one ROM per wiring and
their shared input script tests/inputs/four.txt. Run it again to
regenerate them.

From the nesdev wiki's "Four player adapters", after one strobe:
  four_score.nes   --four-score   $4016 bit 0: controller 1, controller 3,
                                  then 0,0,0,1,0,0,0,0; $4017 bit 0:
                                  controller 2, controller 4, then
                                  0,0,1,0,0,0,0,0; 1s after that
  four_famicom.nes --famicom-4p   controllers 1 and 2 on bit 0 and 3 and 4
                                  on bit 1 of $4016 and $4017, 8 reads
                                  each, then 1s
  four_hori.nes    --hori-4p      1 and 2 on bit 0 as usual; on bit 1 the
                                  Four Score's sequence with the two
                                  signatures swapped

At set frames the ROM reads each line (port register and bit) 24 times
after a strobe, compares the three bytes with what the script holds
then, and that reads 25 to 34 return 1 (0 on a line nothing drives). Before each, it makes 5
reads and strobes again, so a strobe must start the sequence over.
Results use the blargg $6000 protocol: 0 = passed, otherwise
16 * check + 2 + 2 * line + (0: the 24 reads wrong, 1: reads 25-34),
with the lines in the order WIRINGS lists them below.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402
from make_joy_test import NAMES, as_read  # noqa: E402

FRAMES = 0x10                   # zero page: NMI count
GOT = 0x11                      # zero page: the three bytes read

CHECKS = [                      # (frame, controllers 1-4)
    (30, (["a"], ["b"], ["select"], ["start"])),
    (50, (["up", "start"], [], NAMES, ["left", "b"])),
    (70, (NAMES, ["right"], [], ["down", "a"])),
    (90, ([], [], [], [])),
    (110, (["b"], NAMES, ["a", "up"], NAMES)),
]


def sig(read):
    """A signature byte as the ROM builds it: 1 at the given read (0-7)."""
    return 0x80 >> read


# Per wiring: the lines to read, each (register, bit mask, function from
# the four controllers' bytes to the three bytes expected, or None for a
# line nothing drives, which must read 0 throughout).
def standard(n):
    return lambda c: [c[n], 0xFF, 0xFF]


def four(first, second, read):
    return lambda c: [c[first], c[second], sig(read)]


WIRINGS = {
    "four_score": ("--four-score", [
        (0x4016, 0x01, four(0, 2, 3)),
        (0x4017, 0x01, four(1, 3, 2)),
        (0x4016, 0x02, None),           # nothing on bit 1: always 0
        (0x4017, 0x02, None)]),
    "four_famicom": ("--famicom-4p", [
        (0x4016, 0x01, standard(0)),
        (0x4017, 0x01, standard(1)),
        (0x4016, 0x02, standard(2)),
        (0x4017, 0x02, standard(3))]),
    "four_hori": ("--hori-4p", [
        (0x4016, 0x01, standard(0)),
        (0x4017, 0x01, standard(1)),
        (0x4016, 0x02, four(0, 2, 2)),
        (0x4017, 0x02, four(1, 3, 3))]),
}


def rom(lines):
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

    def strobe():
        a.lda(0x01); a.sta(0x4016); a.lda(0x00); a.sta(0x4016)

    def read8(reg, mask, dest):
        a.b(0xA2, 0x08)                         # LDX #8
        loop = a.pc()
        a.lda_abs(reg); a.b(0x29, mask)         # AND #mask
        a.cmp(1)                                # C = bit set
        a.b(0x26, dest)                         # ROL dest
        a.b(0xCA)                               # DEX
        a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF) # BNE loop

    fails = set()
    for c, (frame, pads) in enumerate(CHECKS):
        # Wait for the NMI count: LDA FRAMES; CMP #frame; BCC back.
        a.b(0xA5, FRAMES, 0xC9, frame, 0x90, 0xFA)
        bytes_ = [as_read(p) for p in pads]
        for n, (reg, mask, want) in enumerate(lines):
            code = 16 * c + 2 + 2 * n
            fails.update((code, code + 1))
            strobe()
            for _ in range(5):                  # part way, then start over
                a.lda_abs(reg)
            strobe()
            for k in range(3):
                read8(reg, mask, GOT + k)
            for k, v in enumerate(want(bytes_) if want else [0, 0, 0]):
                a.b(0xA5, GOT + k); a.cmp(v); a.bne("fail%d" % code)
            for _ in range(10):
                a.lda_abs(reg); a.b(0x29, mask); a.cmp(mask if want else 0)
                a.bne("fail%d" % (code + 1))

    a.label("pass")
    for status in [0] + sorted(fails):
        if status:
            a.label("fail%d" % status)
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)

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
    lines = ["# For tests/four_*.nes (make_four_test.py): four controllers,",
             "# changed 10 frames before each of the ROMs' checks."]
    for frame, pads in CHECKS:
        tokens = []
        for n, names in enumerate(pads):
            tokens += [("%d:" % (n + 1) if n else "") + b for b in names]
        lines.append(" ".join([str(frame - 10)] + tokens))
    return "\n".join(lines) + "\n"


def main():
    for name, (option, lines) in WIRINGS.items():
        path = os.path.join(HERE, name + ".nes")
        with open(path, "wb") as f:
            f.write(rom(lines))
        print("wrote", path, "(run with %s)" % option)
    spath = os.path.join(HERE, "inputs", "four.txt")
    with open(spath, "w") as f:
        f.write(script())
    print("wrote", spath)


if __name__ == "__main__":
    main()
