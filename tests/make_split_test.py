#!/usr/bin/env python3
"""Write tests/mmc5_split.nes: a test of MMC5's vertical split (nesdev
wiki "MMC5", $5200-$5202), made for nesrecomp. Run it again to
regenerate it.

The ordinary background is blank (tile 0 everywhere). The split's tiles
come from ExRAM, and tile 2 is solid in its top half (pattern rows 0-3)
in CHR bank 2, and blank in bank 3.
So sprite 0 hit says whether the split was drawn under the sprite. Each
check is one frame: during vblank it sets the split and puts sprite 0
(a solid 8 x 8) somewhere, then reads $2002 bit 6 at the next vblank.

ExRAM layouts: "all", tile 2 everywhere; "row 5", tile 2 only in row 5
(split lines 40-47, solid on 40-43); "column 5", tile 2 only in column 5. Results use the blargg $6000 protocol: 0 = passed,
otherwise the number of the first check that went wrong:
   1  left side, threshold 8: column 5 is the split
   2  ... column 10 isn't
   3  ... sprite at x 60 (columns 7 and 8) touches the split
   4  ... sprite at x 64 (column 8 only) doesn't
   5  right side, threshold 20: column 19 isn't the split
   6  ... column 20 is
   7  $5202 = 3: the split's patterns from bank 3 (blank)
   8  $5200 bit 7 clear: no split
   9  ExRAM mode 2: no split
  10  ExRAM mode 3: no split
  11  ExRAM mode 1: the split still works
  12  "row 5", scroll 0: drawn on lines 40-47
  13  ... and not on 56-63
  14  scroll 16: row 5 on lines 24-31
  15  ... and no longer on 40-47
  16  scroll 200: wraps at 240, so row 5 on lines 80-87
  17  ... and not on 40-47
  18  scroll 3 (fine Y): row 5 on lines 37-44: a sprite on 30-37 touches
  19  ... one on 28-35 doesn't
  20  "all": near the top too (lines 10-17)
  21  "row 5", threshold 2 (only the two tiles fetched at the end of the
      line before), a sprite on lines 33-40: line 40's tiles must come
      from split line 40, not 39
  22  scroll 4: row 5 on lines 36-43, its solid top half on 36-39, so a
      sprite on 40-47 doesn't touch it (the pattern row is the split's
      fine Y, not 0)
  23  ... and one on 33-40 does
  24  "column 5" (tile 2 only in column 5 of every row): column 5 is solid
  25  ... and column 6 isn't (the ExRAM byte is picked by column)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402

LEFT, RIGHT, ON = 0x00, 0x40, 0x80
SOLID = 2                                   # the split's solid tile

# (ExRAM layout, $5200, $5201, $5202, ExRAM mode, sprite x, sprite y, hit?)
CASES = [
    ("all", ON | LEFT | 8, 0, 2, 0, 40, 100, 1),
    ("all", ON | LEFT | 8, 0, 2, 0, 80, 100, 0),
    ("all", ON | LEFT | 8, 0, 2, 0, 60, 100, 1),
    ("all", ON | LEFT | 8, 0, 2, 0, 64, 100, 0),
    ("all", ON | RIGHT | 20, 0, 2, 0, 152, 100, 0),
    ("all", ON | RIGHT | 20, 0, 2, 0, 160, 100, 1),
    ("all", ON | LEFT | 8, 0, 3, 0, 40, 100, 0),
    ("all", LEFT | 8, 0, 2, 0, 40, 100, 0),
    ("all", ON | LEFT | 8, 0, 2, 2, 40, 100, 0),
    ("all", ON | LEFT | 8, 0, 2, 3, 40, 100, 0),
    ("all", ON | LEFT | 8, 0, 2, 1, 40, 100, 1),
    ("row5", ON | LEFT | 8, 0, 2, 0, 40, 40, 1),
    ("row5", ON | LEFT | 8, 0, 2, 0, 40, 56, 0),
    ("row5", ON | LEFT | 8, 16, 2, 0, 40, 24, 1),
    ("row5", ON | LEFT | 8, 16, 2, 0, 40, 40, 0),
    ("row5", ON | LEFT | 8, 200, 2, 0, 40, 80, 1),
    ("row5", ON | LEFT | 8, 200, 2, 0, 40, 40, 0),
    ("row5", ON | LEFT | 8, 3, 2, 0, 40, 30, 1),
    ("row5", ON | LEFT | 8, 3, 2, 0, 40, 28, 0),
    ("all", ON | LEFT | 8, 0, 2, 0, 40, 10, 1),
    ("row5", ON | LEFT | 2, 0, 2, 0, 0, 33, 1),
    ("row5", ON | LEFT | 8, 4, 2, 0, 40, 40, 0),
    ("row5", ON | LEFT | 8, 4, 2, 0, 40, 33, 1),
    ("col5", ON | LEFT | 8, 0, 2, 0, 40, 100, 1),
    ("col5", ON | LEFT | 8, 0, 2, 0, 48, 100, 0),
]


def wait_vblank(a):
    here = a.pc()
    a.b(0xAD, 0x02, 0x20, 0x10, (here - (a.pc() + 5)) & 0xFF)  # LDA $2002; BPL


def fill_exram(a, layout):
    """With rendering off, in ExRAM mode 2 (CPU RAM): the split's
    nametable, then mode 0 again (each check sets its own mode)."""
    a.lda(0); a.sta(0x2001)
    a.lda(2); a.sta(0x5104)
    a.lda(SOLID if layout == "all" else 0)
    a.b(0xA2, 0x00)                             # LDX #0
    loop = a.pc()
    for page in (0x5C, 0x5D, 0x5E, 0x5F):
        a.b(0x9D, 0x00, page)                   # STA page00,X
    a.b(0xE8)                                   # INX
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)     # BNE
    if layout == "row5":
        a.lda(SOLID)
        for col in range(32):
            a.sta(0x5C00 + 5 * 32 + col)
    if layout == "col5":
        a.lda(SOLID)
        for row in range(30):
            a.sta(0x5C00 + row * 32 + 5)


def rom():
    a = Asm(0xE000)
    a.label("reset")
    a.b(0x78, 0xD8, 0xA2, 0xFF, 0x9A)           # SEI; CLD; LDX #$FF; TXS
    a.lda(0); a.sta(0x2000); a.sta(0x2001)
    a.lda(0x40); a.sta(0x4017)
    wait_vblank(a); wait_vblank(a)
    # MMC5: PRG RAM writable, its bank 0 at $6000; 4 KB CHR mode, bank 0
    # for both pattern tables (A set).
    a.lda(2); a.sta(0x5102); a.lda(1); a.sta(0x5103)
    a.lda(0); a.sta(0x5113)
    a.lda(1); a.sta(0x5101)
    a.lda(0); a.sta(0x5123); a.sta(0x5127)
    a.lda(0x00); a.sta(0x5105)                  # all four: CIRAM page 0
    a.lda(0x80); a.sta(0x6000)                  # running
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)
    # The ordinary nametable: tile 0 (blank); palettes.
    a.b(0xAD, 0x02, 0x20)
    a.lda(0x20); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.lda(0); a.b(0xA0, 4, 0xA2, 0)
    loop = a.pc()
    a.sta(0x2007); a.b(0xCA)                    # DEX
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)
    a.b(0x88)                                   # DEY
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)
    a.lda(0x3F); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    for v in (0x0F, 0x30, 0x30, 0x30) * 8:
        a.lda(v); a.sta(0x2007)
    # Every sprite off screen.
    a.lda(0); a.sta(0x2003)
    a.lda(0xF0); a.b(0xA2, 0)
    loop = a.pc()
    a.sta(0x2004); a.b(0xCA)                    # DEX
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)

    layout = None
    for n, (lay, ctrl, scroll, bank, mode, sx, sy, hit) in enumerate(CASES, 1):
        wait_vblank(a)
        if lay != layout:
            fill_exram(a, lay)
            layout = lay
            wait_vblank(a)
        a.lda(mode); a.sta(0x5104)
        a.lda(ctrl); a.sta(0x5200)
        a.lda(scroll); a.sta(0x5201)
        a.lda(bank); a.sta(0x5202)
        a.lda(0); a.sta(0x2003)
        for v in (sy - 1, 1, 0, sx):            # sprite 0: tile 1, solid
            a.lda(v); a.sta(0x2004)
        a.lda(0); a.sta(0x2005); a.sta(0x2005)
        a.lda(0x00); a.sta(0x2000)
        a.lda(0x1E); a.sta(0x2001)              # all on, left 8 pixels too
        wait_vblank(a)
        a.b(0x29, 0x40)                         # AND #$40
        a.cmp(0x40 if hit else 0)
        a.bne("f%d" % n)
    a.lda(0); a.sta(0x2001)
    a.lda(0); a.sta(0x6000)
    a.label("stop")
    a.b(0x4C); a.fix.append((len(a.code), "stop")); a.b(0, 0)
    for n in range(1, len(CASES) + 1):
        a.label("f%d" % n)
        a.lda(0); a.sta(0x2001)
        a.lda(n); a.sta(0x6000)
        a.b(0x4C); a.fix.append((len(a.code), "stop")); a.b(0, 0)
    a.label("nmi")
    a.b(0x40)
    code = a.done()

    prg = bytearray(0x8000)
    prg[0x6000:0x6000 + len(code)] = code
    for vec, label in ((0x7FFA, "nmi"), (0x7FFC, "reset"), (0x7FFE, "nmi")):
        t = a.labels[label]
        prg[vec], prg[vec + 1] = t & 0xFF, t >> 8
    chr_ = bytearray(0x8000)                    # eight 4 KB banks
    chr_[0x0000 + 1 * 16:0x0000 + 1 * 16 + 8] = b"\xff" * 8   # bank 0 tile 1
    chr_[0x2000 + SOLID * 16:0x2000 + SOLID * 16 + 4] = b"\xff" * 4  # bank 2, top half
    header = bytes([0x4E, 0x45, 0x53, 0x1A, 2, 4, 0x50, 0x00]) + bytes(8)
    return header + prg + chr_


def main():
    path = os.path.join(HERE, "mmc5_split.nes")
    with open(path, "wb") as f:
        f.write(rom())
    print("wrote", path)


if __name__ == "__main__":
    main()
