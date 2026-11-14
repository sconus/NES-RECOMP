#!/usr/bin/env python3
"""Write tests/mmc5_split.nes: a test of MMC5's vertical split (nesdev
wiki "MMC5", $5200-$5202), made for nesrecomp, and
tests/mmc5_split_pic.nes, a picture of the split's colours (see
pic_rom). Run it again to regenerate them.

The ordinary background is blank (tile 0 everywhere). The split's tiles
come from ExRAM, and tile 2 is solid in its top half (pattern rows 0-3)
in CHR bank 2, and blank in bank 3. (Also tile 4 of bank 2, the same,
and tile 0 of bank 4, solid, for the "ext" layout.)
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
  The edges (step 2 of PLAN-split.md):
  26  "ext" (ExRAM all $04), ExRAM mode 1: outside the split, extended
      attributes pick bank 4, whose tile 0 is solid, so column 10 hits
  27  ... and ExRAM mode 0 there: plain bank 0, blank
  28  ... inside the split, $5202 = 2: tile 4 of bank 2 is solid
  29  ... $5202 = 4: the split ignores the extended attributes' bank
      (tile 4 of bank 4 is blank)
  30  fine X 4, coarse X 3 ($2005 = 28), left 8: the split's last tile
      moves 4 pixels left, so a sprite at x 56 (pixels 56-63) touches it
  31  ... and one at x 60 doesn't
  32  "column 5", the same scroll: column 5 is drawn at pixels 36-43 (the
      coarse scroll doesn't move the split's columns): x 40 touches
  33  ... x 44 doesn't
  34  right side, threshold 20, the same scroll: x 152 touches (156-159)
  35  "attr" (only ExRAM $3E0-$3FF solid), scroll 248: lines 0-7 show
      split row 31 (attribute bytes as tiles), solid on 0-3: y 1 touches
  36  ... scroll 252 (fine Y 4): lines 0-3 are row 31's blank bottom half
  37  "row 5", scroll 248: after 8 lines it wraps to row 0, so row 5 is on
      lines 48-55: y 46 touches
  38  ... and y 30 doesn't (not (248 + line) mod 240)
  39  CHR mode 0 (8 KB banks): the split still uses $5202's 4 KB bank
  40  CHR mode 3 (1 KB banks): the same
  41  $5130 = 1: no effect on the split (CHR is 512 KB, so an upper bit
      would land in an empty bank)
  42  8 x 16 sprites, the B set ($512B) on a blank bank: the split still
      uses $5202 (the sprite is solid on its lower 8 lines)
  43  rendering turned off at line 20 (the MMC5 IRQ flag, polled) and on
      again 34-35 lines later, so the MMC5 sees a frame start at line 55:
      the split restarts from $5201 there, and "row 5" is solid on lines
      95-98. A sprite on 92-99 touches it (88-98 all would).
  44  ... and one on 72-79 doesn't: there row 5 would be if the split's
      count only paused while rendering was off (with no restart at all,
      row 5 would fall on lines 40-47, while rendering is off)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402

LEFT, RIGHT, ON = 0x00, 0x40, 0x80
SOLID = 2                                   # the split's solid tile
EXT = 4                                     # "ext": tile 4, or bank 4
MIDOFF_Y = 92                               # see cases 43-44

# (ExRAM layout, $5200, $5201, $5202, ExRAM mode, sprite x, sprite y, hit?)
# then optional extras: x scroll ($2005), $2000, MMC5 writes before the
# frame, "midoff" (rendering off at line 20 for a while).
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
    # the edges
    ("ext", ON | LEFT | 8, 0, 2, 1, 80, 100, 1),
    ("ext", ON | LEFT | 8, 0, 2, 0, 80, 100, 0),
    ("ext", ON | LEFT | 8, 0, 2, 1, 40, 100, 1),
    ("ext", ON | LEFT | 8, 0, 4, 1, 40, 100, 0),
    ("all", ON | LEFT | 8, 0, 2, 0, 56, 100, 1, dict(xs=28)),
    ("all", ON | LEFT | 8, 0, 2, 0, 60, 100, 0, dict(xs=28)),
    ("col5", ON | LEFT | 8, 0, 2, 0, 40, 100, 1, dict(xs=28)),
    ("col5", ON | LEFT | 8, 0, 2, 0, 44, 100, 0, dict(xs=28)),
    ("all", ON | RIGHT | 20, 0, 2, 0, 152, 100, 1, dict(xs=28)),
    ("attr", ON | LEFT | 8, 248, 2, 0, 40, 1, 1),
    ("attr", ON | LEFT | 8, 252, 2, 0, 40, 1, 0),
    ("row5", ON | LEFT | 8, 248, 2, 0, 40, 46, 1),
    ("row5", ON | LEFT | 8, 248, 2, 0, 40, 30, 0),
    ("all", ON | LEFT | 8, 0, 2, 0, 40, 100, 1,
     dict(pre=[(0x5101, 0), (0x5127, 0)])),
    ("all", ON | LEFT | 8, 0, 2, 0, 40, 100, 1,
     dict(pre=[(0x5101, 3)] + [(0x5120 + i, i) for i in range(8)])),
    ("all", ON | LEFT | 8, 0, 2, 0, 40, 100, 1, dict(pre=[(0x5130, 1)])),
    ("all", ON | LEFT | 8, 0, 2, 0, 40, 92, 1,
     dict(ctrl=0x20, pre=[(0x512B, 3)])),
    ("row5", ON | LEFT | 8, 0, 2, 0, 40, MIDOFF_Y, 1, dict(midoff=1)),
    ("row5", ON | LEFT | 8, 0, 2, 0, 40, MIDOFF_Y - 20, 0, dict(midoff=1)),
]
# After each check, the CHR registers as they were (4 KB mode, bank 0).
RESTORE = [(0x5130, 0), (0x5101, 1), (0x5123, 0), (0x5127, 0)]


def wait_vblank(a):
    here = a.pc()
    a.b(0xAD, 0x02, 0x20, 0x10, (here - (a.pc() + 5)) & 0xFF)  # LDA $2002; BPL


def fill_exram(a, layout):
    """With rendering off, in ExRAM mode 2 (CPU RAM): the split's
    nametable, then mode 0 again (each check sets its own mode)."""
    a.lda(0); a.sta(0x2001)
    a.lda(2); a.sta(0x5104)
    a.lda({"all": SOLID, "ext": EXT}.get(layout, 0))
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
    if layout == "attr":
        a.lda(SOLID)
        for i in range(32):
            a.sta(0x5FE0 + i)
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
    for n, case in enumerate(CASES, 1):
        lay, ctrl, scroll, bank, mode, sx, sy, hit = case[:8]
        extra = case[8] if len(case) > 8 else {}
        wait_vblank(a)
        if lay != layout:
            fill_exram(a, lay)
            layout = lay
            wait_vblank(a)
        a.lda(mode); a.sta(0x5104)
        a.lda(ctrl); a.sta(0x5200)
        a.lda(scroll); a.sta(0x5201)
        a.lda(bank); a.sta(0x5202)
        for addr, v in extra.get("pre", []):
            a.lda(v); a.sta(addr)
        a.lda(0); a.sta(0x2003)
        for v in (sy - 1, 1, 0, sx):            # sprite 0: tile 1, solid
            a.lda(v); a.sta(0x2004)
        a.lda(extra.get("xs", 0)); a.sta(0x2005)
        a.lda(0); a.sta(0x2005)
        a.lda(extra.get("ctrl", 0)); a.sta(0x2000)
        a.lda(0x1E); a.sta(0x2001)              # all on, left 8 pixels too
        if extra.get("midoff"):
            a.lda(20); a.sta(0x5203)
            a.lda_abs(0x5204)                   # clear the flag
            here = a.pc()
            a.lda_abs(0x5204)
            a.b(0x10, (here - (a.pc() + 2)) & 0xFF)     # BPL: until line 20
            a.lda(0); a.sta(0x2001)
            a.b(0xA0, 3, 0xA2, 0)               # LDY #3; LDX #0
            here = a.pc()
            a.b(0xCA)                           # DEX
            a.b(0xD0, (here - (a.pc() + 2)) & 0xFF)
            a.b(0x88)                           # DEY
            a.b(0xD0, (here - (a.pc() + 2)) & 0xFF)
            a.lda(0x1E); a.sta(0x2001)
        wait_vblank(a)
        a.b(0x29, 0x40)                         # AND #$40
        a.cmp(0x40 if hit else 0)
        a.bne("f%d" % n)
        if extra:
            a.lda(0); a.sta(0x2000); a.sta(0x5203)
            for addr, v in RESTORE:
                a.lda(v); a.sta(addr)
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
    assert len(code) <= 0x2000, "code doesn't fit in $E000-$FFFF"
    chr_ = bytearray(0x80000)                   # 128 4 KB banks (512 KB)
    chr_[0x0000 + 1 * 16:0x0000 + 1 * 16 + 8] = b"\xff" * 8   # bank 0 tile 1
    chr_[0x2000 + SOLID * 16:0x2000 + SOLID * 16 + 4] = b"\xff" * 4  # bank 2, top half
    chr_[0x2000 + EXT * 16:0x2000 + EXT * 16 + 4] = b"\xff" * 4       # bank 2, top half
    chr_[0x4000:0x4000 + 8] = b"\xff" * 8                            # bank 4 tile 0
    header = bytes([0x4E, 0x45, 0x53, 0x1A, 2, 64, 0x50, 0x00]) + bytes(8)
    return header + prg + chr_


# The picture (tests/mmc5_split_pic.nes): the split's colours, which
# sprite 0 can't see. ExRAM mode 1, the split on the left 16 tiles with
# $5201 = 20. Its tiles (4, $44, $84 or $C4 of bank 2) and the extended
# tiles on the right (tile 0 of bank 4) all have colour 1 on pattern
# rows 0-1, 2 on rows 2-3 and 3 on rows 4-7, so each 8 x 8 shows which
# palette it got. ExRAM, as written by pic_exram():
#   columns 0-15 of rows 0-29: the split's tiles;
#   columns 16-31: extended attributes, palette (row * 3 + column) % 4;
#   $3C0-$3FF: the split's attribute bytes, all different.
PIC_PALETTES = (0x06, 0x16, 0x26, 0x0A, 0x1A, 0x2A,
                0x02, 0x12, 0x22, 0x08, 0x18, 0x28)
PIC_SCROLL, PIC_THRESHOLD = 20, 16


def pic_exram():
    ex = bytearray(0x400)
    for r in range(30):
        for c in range(32):
            if c < PIC_THRESHOLD:
                ex[r * 32 + c] = (0x04, 0x44, 0x84, 0xC4)[(r + c) % 4]
            else:
                ex[r * 32 + c] = ((r * 3 + c) % 4) << 6 | 4
    for i in range(64):
        ex[0x3C0 + i] = (i * 0x9D + 0x37) & 0xFF
    return ex


def pic_expected():
    """The picture as NES colours, 256 x 240, from the wiki's rules: in
    the split, the row from the split's scroll and the attribute byte
    from ExRAM $3C0 (no extended attributes); outside, the extended
    attribute byte at the tile's own place."""
    ex, rows = pic_exram(), []
    shade = (1, 1, 2, 2, 3, 3, 3, 3)
    for y in range(240):
        line = []
        for x in range(256):
            t = x >> 3
            if t < PIC_THRESHOLD:
                ys = (y + PIC_SCROLL) % 240
                r = ys >> 3
                attr = ex[0x3C0 + (r >> 2) * 8 + (t >> 2)]
                pal = (attr >> (((r & 2) << 1) | (t & 2))) & 3
                ci = shade[ys & 7]
            else:
                pal = ex[(y >> 3) * 32 + t] >> 6
                ci = shade[y & 7]
            line.append(PIC_PALETTES[pal * 3 + ci - 1])
        rows.append(line)
    return rows


def pic_rom():
    a = Asm(0xE000)
    a.label("reset")
    a.b(0x78, 0xD8, 0xA2, 0xFF, 0x9A)           # SEI; CLD; LDX #$FF; TXS
    a.lda(0); a.sta(0x2000); a.sta(0x2001)
    wait_vblank(a); wait_vblank(a)
    a.lda(1); a.sta(0x5101)                     # 4 KB CHR, bank 0
    a.lda(0); a.sta(0x5123); a.sta(0x5127)
    a.lda(0x00); a.sta(0x5105)
    # The ordinary nametable: tile 0; palettes.
    a.lda(0x20); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.lda(0); a.b(0xA0, 4, 0xA2, 0)
    loop = a.pc()
    a.sta(0x2007); a.b(0xCA)
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)
    a.b(0x88)
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)
    a.lda(0x3F); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    for p in range(4):
        for v in (0x0F,) + PIC_PALETTES[p * 3:p * 3 + 3]:
            a.lda(v); a.sta(0x2007)
    a.lda(0); a.sta(0x2003)                     # sprites off screen
    a.lda(0xF0); a.b(0xA2, 0)
    loop = a.pc()
    a.sta(0x2004); a.b(0xCA)
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)
    # ExRAM from the table at $F000 (mode 2 while writing).
    a.lda(2); a.sta(0x5104)
    a.b(0xA2, 0)                                # LDX #0
    loop = a.pc()
    for page in range(4):
        a.b(0xBD, 0x00, 0xF0 + page)            # LDA $F000+page,X
        a.b(0x9D, 0x00, 0x5C + page)            # STA $5C00+page,X
    a.b(0xE8)                                   # INX
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)
    wait_vblank(a)
    a.lda(1); a.sta(0x5104)
    a.lda(ON | LEFT | PIC_THRESHOLD); a.sta(0x5200)
    a.lda(PIC_SCROLL); a.sta(0x5201)
    a.lda(2); a.sta(0x5202)
    a.lda(0); a.sta(0x2005); a.sta(0x2005); a.sta(0x2000)
    a.lda(0x1E); a.sta(0x2001)
    a.label("stop")
    a.b(0x4C); a.fix.append((len(a.code), "stop")); a.b(0, 0)
    a.label("nmi")
    a.b(0x40)
    code = a.done()
    assert len(code) <= 0x1000

    prg = bytearray(0x8000)
    prg[0x6000:0x6000 + len(code)] = code
    prg[0x7000:0x7400] = pic_exram()
    for vec, label in ((0x7FFA, "nmi"), (0x7FFC, "reset"), (0x7FFE, "nmi")):
        t = a.labels[label]
        prg[vec], prg[vec + 1] = t & 0xFF, t >> 8
    chr_ = bytearray(0x8000)
    tile = bytes([0xFF, 0xFF, 0, 0, 0xFF, 0xFF, 0xFF, 0xFF,     # plane 0
                  0, 0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])    # plane 1
    for t in (0x04, 0x44, 0x84, 0xC4):
        chr_[0x2000 + t * 16:0x2000 + t * 16 + 16] = tile
    chr_[0x4000:0x4010] = tile
    header = bytes([0x4E, 0x45, 0x53, 0x1A, 2, 4, 0x50, 0x00]) + bytes(8)
    return header + prg + chr_


def main():
    for name, data in (("mmc5_split.nes", rom()), ("mmc5_split_pic.nes", pic_rom())):
        path = os.path.join(HERE, name)
        with open(path, "wb") as f:
            f.write(data)
        print("wrote", path)


if __name__ == "__main__":
    main()
