#!/usr/bin/env python3
"""Write the Arkanoid paddle tests made for nesrecomp: four ROMs, one per
wiring, and their shared input script tests/inputs/vaus.txt. Run it again
to regenerate them.

From the nesdev wiki's "Arkanoid controller": writing 1 to $4016 starts
a measurement of the knob, which then comes out one bit per read, most
significant bit first and inverted (so games EOR it with $FF); reads
after the 9th repeat the 9th bit, which is 0 here, so they read as 1.
The button reads 1 when pressed, whatever the strobe does.

  vaus_port1.nes    --port1 vaus     $4016: bit 4 knob, bit 3 button;
                                     controller 2 still on $4017 bit 0
  vaus_port2.nes    --port2 vaus     the same on $4017 (where Arkanoid
                                     looks); controller 1 on $4016 bit 0
  vaus_famicom.nes  --famicom-vaus   $4017 bit 1 knob, $4016 bit 1
                                     button; both controllers on bit 0
  vaus_two.nes      --port1 vaus --port2 vaus: two paddles, the script's
                                     knob/fire and 2:knob/2:fire

At set frames the ROM reads everything and compares it with what the
script holds then (it changes 10 frames before each check; a line with
no knob= leaves the knob where it was). Results use the blargg $6000
protocol: 0 = passed, otherwise 16 * check + what was wrong:
   2  first paddle: the 8 knob bits      6  second paddle: the knob
   3  first paddle: reads 9 and 10       7  second: reads 9 and 10
   4  first paddle: the button           8  second: the button
   5  first: the button, strobe held 1   9  second: button, strobe 1
  10  controller 1 ($4016 bit 0)        11  controller 2 ($4017 bit 0)
  12  a bit that nothing drives wasn't 0 (bit 0 under an NES paddle,
      bits 2-4 with only the Famicom paddle)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402
from make_joy_test import NAMES, as_read  # noqa: E402

FRAMES = 0x10                   # zero page: NMI count
GOT = 0x11                      # zero page: the byte read

# (frame, knob 1, fire 1, knob 2, fire 2, controller 1, controller 2);
# None: no knob= on that line, so it must keep its last value.
CHECKS = [
    (30, 0x00, 1, 0xFF, 0, ["a"], ["b"]),
    (50, 0xFF, 0, 0x00, 1, ["up", "start"], ["left", "select"]),
    (70, 0xA5, 1, 0x3C, 1, [], NAMES),
    (90, None, 0, None, 0, NAMES, []),
    (110, 0x62, 1, 0xF2, 0, ["b"], ["a"]),
]

# Where a paddle's lines are: (knob register, knob bit, button register,
# button bit). Bits nothing drives, per register, for check 12.
NES1 = (0x4016, 0x10, 0x4016, 0x08)
NES2 = (0x4017, 0x10, 0x4017, 0x08)
FAMI = (0x4017, 0x02, 0x4016, 0x02)
WIRINGS = {
    # name: (options, paddles, controllers present, {register: zero bits})
    "vaus_port1": ("--port1=vaus", [NES1], [1], {0x4016: 0x07}),
    "vaus_port2": ("--port2=vaus", [NES2], [0], {0x4017: 0x07}),
    "vaus_famicom": ("--famicom-vaus", [FAMI], [0, 1],
                     {0x4016: 0x1C, 0x4017: 0x1C}),
    "vaus_two": ("--port1=vaus --port2=vaus", [NES1, NES2], [],
                 {0x4016: 0x07, 0x4017: 0x07}),
}


def knobs():
    """The knob each check expects, carrying over lines without knob=."""
    out, last = [], [0, 0]
    for _, k1, _, k2, _, _, _ in CHECKS:
        last = [k1 if k1 is not None else last[0],
                k2 if k2 is not None else last[1]]
        out.append(tuple(last))
    return out


def rom(paddles, pads, zero_bits):
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

    def read8(reg, mask):
        """GOT = 8 reads of reg's mask bit, the first read in bit 7."""
        a.b(0xA2, 0x08)                         # LDX #8
        loop = a.pc()
        a.lda_abs(reg); a.b(0x29, mask)         # AND #mask
        a.cmp(1)                                # C = bit set
        a.b(0x26, GOT)                          # ROL GOT
        a.b(0xCA)                               # DEX
        a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF) # BNE loop

    def expect_bit(reg, mask, on, fail):
        a.lda_abs(reg); a.b(0x29, mask); a.cmp(mask if on else 0); a.bne(fail)

    fails = set()
    want_knobs = knobs()
    for c, (frame, _, f1, _, f2, p1, p2) in enumerate(CHECKS):
        base = 16 * c
        # Wait for the NMI count: LDA FRAMES; CMP #frame; BCC back.
        a.b(0xA5, FRAMES, 0xC9, frame, 0x90, 0xFA)
        for n, (kreg, kbit, freg, fbit) in enumerate(paddles):
            knob, fire = want_knobs[c][n], (f1, f2)[n]
            codes = [base + k + 4 * n for k in (2, 3, 4, 5)]
            fails.update(codes)
            strobe()
            read8(kreg, kbit)
            a.b(0xA5, GOT); a.cmp(knob ^ 0xFF); a.bne("fail%d" % codes[0])
            for _ in range(2):                  # reads 9 and 10: the 9th bit
                expect_bit(kreg, kbit, True, "fail%d" % codes[1])
            for _ in range(2):
                expect_bit(freg, fbit, fire, "fail%d" % codes[2])
            a.lda(0x01); a.sta(0x4016)          # the button, strobe held 1
            expect_bit(freg, fbit, fire, "fail%d" % codes[3])
            a.lda(0x00); a.sta(0x4016)
        for port in pads:
            code = base + 10 + port
            fails.add(code)
            strobe()
            read8(0x4016 + port, 0x01)
            a.b(0xA5, GOT); a.cmp(as_read((p1, p2)[port]))
            a.bne("fail%d" % code)
        for reg, bits in sorted(zero_bits.items()):
            fails.add(base + 12)
            a.lda_abs(reg); a.b(0x29, bits); a.bne("fail%d" % (base + 12))

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
    lines = ["# For tests/vaus_*.nes (make_vaus_test.py): the paddles and",
             "# controllers, changed 10 frames before each of the ROMs' checks."]
    for frame, k1, f1, k2, f2, p1, p2 in CHECKS:
        tokens = []
        if k1 is not None:
            tokens.append("knob=%d" % k1)
        if f1:
            tokens.append("fire")
        if k2 is not None:
            tokens.append("2:knob=%d" % k2)
        if f2:
            tokens.append("2:fire")
        tokens += p1 + ["2:" + n for n in p2]
        lines.append(" ".join([str(frame - 10)] + tokens))
    return "\n".join(lines) + "\n"


def main():
    for name, (options, paddles, pads, zero_bits) in WIRINGS.items():
        path = os.path.join(HERE, name + ".nes")
        with open(path, "wb") as f:
            f.write(rom(paddles, pads, zero_bits))
        print("wrote", path, "(run with %s)" % options)
    spath = os.path.join(HERE, "inputs", "vaus.txt")
    with open(spath, "w") as f:
        f.write(script())
    print("wrote", spath)


if __name__ == "__main__":
    main()
