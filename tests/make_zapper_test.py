#!/usr/bin/env python3
"""Write the Zapper tests made for nesrecomp: one ROM per wiring and their
shared input script tests/inputs/zapper.txt. Run it again to regenerate
them.

  zapper_port2.nes    --port2=zapper     $4017 bit 3 light, bit 4 trigger
  zapper_port1.nes    --port1=zapper     the same on $4016
  zapper_famicom.nes  --famicom-zapper   on $4017, as in port 2, with
                                         controller 2 still on bit 0

From the nesdev wiki's "Zapper": bit 3 reads 0 while the sensor sees
light, which it does from when the beam draws a bright spot under the
aim until about 26 scanlines later for white, 24 for light grey, 19 for
dark grey. Bit 4 is the trigger (1 = pulled here, as on the simpler
guns). The wiki gives no area or brightness threshold; nesrecomp looks
at the 5 x 5 pixels around the aim and doesn't count colours darker
than dark grey ($00), such as blue $11 (see runtime/input.c).

The ROM draws 16 x 16 boxes on black, with rows 32-47 holding white
($30, x 32-47), light grey ($10, x 96-111) and dark grey ($00, x
160-175), and rows 128-143 a blue box ($11, x 32-47). For each case the
script aims the gun, and the ROM, from the start of a vblank, reads the
sensor once a scanline (every 114 cycles) for 256 samples: sample i is
about scanline i - 21. It finds the first and last samples that saw
light and compares them with where the beam passes the box under the
aim and how long that colour keeps the sensor lit: the first must be
the line the box starts under the aim or one later (the read may come
before the beam reaches the aim's column); the last, the line the
light runs out or one before.

Results use the blargg $6000 protocol, with the first and last sample
of every case so far (hex, FF = none) as text: 0 = passed, otherwise
  2 + 2 * case   the first lit sample is wrong (or something was lit)
  3 + 2 * case   the last lit sample is wrong
  40  the trigger didn't read 1 while pulled   41  or 0 when released
  42  a bit nothing drives wasn't 0
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402

FRAMES = 0x10                   # zero page: NMI count
TEXT = 0x11                     # zero page: next free byte of the text
FIRST, LAST = 0x12, 0x13
TABLE = 0x0300                  # the 256 samples (bit 3 of each read)
RADIUS = 2
SAMPLE_LINE0 = -21              # scanline of sample 0

# Boxes: (left, top, size, scanlines of light)
WHITE = (32, 32, 16, 26)
LGREY = (96, 32, 16, 24)
DGREY = (160, 32, 16, 19)
BLUE = (32, 128, 16, 0)
BOXES = [WHITE, LGREY, DGREY, BLUE]

CASES = [               # (aim or None for aim=off)
    None,
    (128, 200),         # black
    (40, 40),           # white
    (104, 40),          # light grey
    (168, 40),          # dark grey
    (40, 136),          # blue: too dark
    (49, 40),           # white's right edge 2 pixels away: still seen
    (51, 40),           # 4 pixels away: not seen
    (40, 31),           # above the white box, its top row in the area
]
CASE_FRAME0, CASE_EVERY = 20, 16
TRIGGER_FRAME = CASE_FRAME0 + CASE_EVERY * len(CASES)


def expected(aim):
    """(first, last) lit sample the model predicts, or None for no light."""
    if aim is None:
        return None
    ax, ay = aim
    best = None
    for left, top, size, lines in BOXES:
        if not lines:
            continue
        xs = range(max(left, ax - RADIUS), min(left + size, ax + RADIUS + 1))
        ys = range(max(top, ay - RADIUS), min(top + size, ay + RADIUS + 1))
        if not xs or not ys:
            continue
        first, last = ys[0], ys[-1] + lines
        best = (first, last) if best is None else best
    if best is None:
        return None
    return best[0] - SAMPLE_LINE0, best[1] - SAMPLE_LINE0


def chr_rom():
    chr_ = bytearray(0x2000)
    for tile, (lo, hi) in ((1, (0xFF, 0xFF)), (2, (0xFF, 0)), (3, (0, 0xFF))):
        chr_[tile * 16:tile * 16 + 8] = bytes([lo]) * 8
        chr_[tile * 16 + 8:tile * 16 + 16] = bytes([hi]) * 8
    return chr_


def rom(reg, zero_bits):
    a = Asm(0xE000)
    a.label("reset")
    a.b(0x78, 0xD8, 0xA2, 0xFF, 0x9A)           # SEI; CLD; LDX #$FF; TXS
    a.lda(0x40); a.sta(0x4017)                  # no APU frame IRQ
    a.lda(0x00); a.sta(0x2000); a.sta(0x2001)
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)
    a.lda(0x00); a.sta(0x6004)
    a.b(0x85, FRAMES)
    a.lda(0x04); a.b(0x85, TEXT)
    for _ in range(2):                          # PPU warm-up
        a.b(0x2C, 0x02, 0x20, 0x10, 0xFB)       # BIT $2002; BPL

    def vram(addr):
        a.b(0xAD, 0x02, 0x20)                   # LDA $2002
        a.lda(addr >> 8); a.sta(0x2006); a.lda(addr & 0xFF); a.sta(0x2006)

    # Clear nametable 0 and its attributes: 4 x 256 zeros.
    vram(0x2000)
    a.lda(0); a.b(0xA0, 4, 0xA2, 0)             # LDY #4; LDX #0
    loop = a.pc()
    a.sta(0x2007); a.b(0xCA)                    # STA $2007; DEX
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)
    a.b(0x88)                                   # DEY
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)
    for (left, top, size, _), tile in zip(BOXES, (1, 3, 2, 2)):
        for row in range(top // 8, (top + size) // 8):
            vram(0x2000 + row * 32 + left // 8)
            a.lda(tile)
            for _ in range(size // 8):
                a.sta(0x2007)
    vram(0x23E1)                                # the blue box: palette 1
    a.lda(0x01); a.sta(0x2007)
    vram(0x3F00)
    for v in (0x0F, 0x00, 0x10, 0x30, 0x0F, 0x11, 0x11, 0x11):
        a.lda(v); a.sta(0x2007)
    a.b(0xAD, 0x02, 0x20)                       # LDA $2002
    a.lda(0); a.sta(0x2005); a.sta(0x2005)
    a.lda(0x80); a.sta(0x2000)                  # NMI on, nametable 0
    a.lda(0x0A); a.sta(0x2001)                  # background on

    def wait_frame(n):
        # LDA FRAMES; CMP #n; BCC back
        a.b(0xA5, FRAMES, 0xC9, n, 0x90, 0xFA)

    fails = set()
    for c, aim in enumerate(CASES):
        wait_frame(CASE_FRAME0 + CASE_EVERY * c)
        a.b(0xA5, FRAMES)                       # then the next NMI
        a.b(0xC5, FRAMES, 0xF0, 0xFC)           # CMP FRAMES; BEQ back
        a.jsr_label("sample")
        a.jsr_label("scan")
        want = expected(aim)
        code = 2 + 2 * c
        fails.update((code, code + 1))
        if want is None:
            a.b(0xA5, FIRST); a.cmp(0xFF); a.bne("fail%d" % code)
        else:
            first, last = want
            # first in [first, first + 1]: (FIRST - first) < 2
            a.b(0xA5, FIRST, 0x38, 0xE9, first)     # LDA; SEC; SBC #first
            a.cmp(2); a.b(0x90, 3)                  # CMP #2; BCC +3
            a.b(0x4C); a.fix.append((len(a.code), "fail%d" % code)); a.b(0, 0)
            # last in [last - 1, last]: (LAST - (last - 1)) < 2
            a.b(0xA5, LAST, 0x38, 0xE9, last - 1)
            a.cmp(2); a.b(0x90, 3)
            a.b(0x4C); a.fix.append((len(a.code), "fail%d" % (code + 1))); a.b(0, 0)

    # The trigger: pulled at TRIGGER_FRAME, released 10 frames later.
    wait_frame(TRIGGER_FRAME + 5)
    a.lda_abs(reg); a.b(0x29, 0x10); a.cmp(0x10); a.bne("fail40")
    wait_frame(TRIGGER_FRAME + 15)
    a.lda_abs(reg); a.b(0x29, 0x10); a.bne("fail41")
    a.lda_abs(reg); a.b(0x29, zero_bits); a.bne("fail42")
    fails.update((40, 41, 42))

    a.label("pass")
    for status in [0] + sorted(fails):
        if status:
            a.label("fail%d" % status)
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)

    # sample: 256 reads of the sensor, 114 cycles apart, into TABLE. In
    # one page, so no branch takes the extra cycle of crossing one.
    while (a.pc() & 0xFF) > 0xE0:
        a.b(0xEA)
    a.label("sample")
    a.b(0xA2, 0x00)                             # LDX #0
    top = a.pc()
    a.lda_abs(reg)                              # 4
    a.b(0x9D, TABLE & 0xFF, TABLE >> 8)         # STA TABLE,X   5
    a.b(0xA0, 19)                               # LDY #19       2
    d = a.pc()
    a.b(0x88)                                   # DEY
    a.b(0xD0, (d - (a.pc() + 2)) & 0xFF)        # BNE: 19*5-1 in all
    a.b(0xEA, 0xEA)                             # NOP NOP       4
    a.b(0xE8)                                   # INX           2
    a.b(0xD0, (top - (a.pc() + 2)) & 0xFF)      # BNE top       3
    a.rts()
    assert a.labels["sample"] >> 8 == (a.pc() - 1) >> 8

    # scan: FIRST, LAST = first and last samples with bit 3 clear (light
    # seen), $FF if none; both appended to the text as hex and a space.
    a.label("scan")
    a.lda(0xFF); a.b(0x85, FIRST, 0x85, LAST)
    a.b(0xA2, 0x00)                             # LDX #0
    top = a.pc()
    a.b(0xBD, TABLE & 0xFF, TABLE >> 8)         # LDA TABLE,X
    a.b(0x29, 0x08, 0xD0, 0x0A)                 # AND #8; BNE next (+10)
    a.b(0xA5, FIRST, 0xC9, 0xFF, 0xD0, 0x02)    # LDA FIRST; CMP #$FF; BNE +2
    a.b(0x86, FIRST)                            # STX FIRST
    a.b(0x86, LAST)                             # STX LAST
    a.b(0xE8)                                   # next: INX
    a.b(0xD0, (top - (a.pc() + 2)) & 0xFF)
    for zp in (FIRST, LAST):
        a.b(0xA5, zp); a.jsr_label("hex")
    a.lda(0x20); a.jsr_label("putc")
    a.rts()

    a.label("hex")                              # A as two hex digits
    a.b(0x48, 0x4A, 0x4A, 0x4A, 0x4A)           # PHA; LSR x4
    a.jsr_label("digit")
    a.b(0x68, 0x29, 0x0F)                       # PLA; AND #$0F
    a.label("digit")
    a.cmp(10); a.b(0x90, 0x02, 0x69, 0x06)      # CMP #10; BCC +2; ADC #6
    a.b(0x69, 0x30)                             # ADC #'0'
    a.label("putc")                             # text[TEXT++] = A, then 0
    a.b(0xA4, TEXT)                             # LDY TEXT
    a.b(0x99, 0x00, 0x60)                       # STA $6000,Y
    a.lda(0); a.b(0x99, 0x01, 0x60)             # STA $6001,Y
    a.b(0xE6, TEXT)                             # INC TEXT
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
    return bytes([0x4E, 0x45, 0x53, 0x1A, 2, 1, 0, 0]) + bytes(8) + prg + chr_rom()


WIRINGS = {
    "zapper_port2": ("--port2=zapper", 0x4017, 0x07),
    "zapper_port1": ("--port1=zapper", 0x4016, 0x07),
    "zapper_famicom": ("--famicom-zapper", 0x4017, 0x06),
}


def script():
    lines = ["# For tests/zapper_*.nes (make_zapper_test.py): the aim for",
             "# each case, set 8 frames before it (the ROM's frame count",
             "# runs a few frames behind), then the trigger."]
    for c, aim in enumerate(CASES):
        tok = "aim=off" if aim is None else "aim=%d,%d" % aim
        lines.append("%d %s" % (CASE_FRAME0 + CASE_EVERY * c - 8, tok))
    lines.append("%d trigger" % TRIGGER_FRAME)
    lines.append("%d" % (TRIGGER_FRAME + 10))
    return "\n".join(lines) + "\n"


def main():
    for name, (option, reg, zero_bits) in WIRINGS.items():
        path = os.path.join(HERE, name + ".nes")
        with open(path, "wb") as f:
            f.write(rom(reg, zero_bits))
        print("wrote", path, "(run with %s)" % option)
    spath = os.path.join(HERE, "inputs", "zapper.txt")
    with open(spath, "w") as f:
        f.write(script())
    print("wrote", spath)
    for aim in CASES:
        want = expected(aim)
        print("  aim %-10s expect %s" % (aim, "none" if want is None else
              "first %02X-%02X, last %02X-%02X" % (want[0], want[0] + 1,
                                                   want[1] - 1, want[1])))


if __name__ == "__main__":
    main()
