#!/usr/bin/env python3
"""Write tests/mmc5_split_demo.nes: MMC5's vertical split to try by hand,
made for nesrecomp, and tests/inputs/mmc5_split_demo.txt, a script for
the suite's picture check. Run it again to regenerate both.

    make run ROM=tests/mmc5_split_demo.nes

A playfield of pillars and clouds scrolls sideways across two
nametables, one pixel a frame. A status panel 8 tiles wide stays put on
the right: it is the split, drawn from ExRAM with CHR bank 1 ($5202).
It shows the playfield's scroll (X, 3 hex digits) and its own vertical
scroll (Y, $5201), and below them rows numbered 04-1C in hex with
coloured blocks, so its scrolling is easy to see.

    Up / Down   scroll the panel ($5201, 0-239, wrapping)
    Left        hold to stop the playfield
    A           move the panel to the other side (right: threshold 24,
                left: threshold 8)

The panel's digits are written in vblank with ExRAM in mode 2 (CPU RAM),
then mode 0 again: in modes 0 and 1 the CPU may only write ExRAM while
the PPU renders.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402
from make_zapper_demo import FONT as ZAPPER_FONT  # noqa: E402

BTN, OLD, XLO, XHI, PY, SIDE, PRESS = 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16
NT_TABLE, EXRAM_TABLE = 0xF000, 0xF800          # in the last 8 KB
RIGHT_SPLIT, LEFT_SPLIT = 0x80 | 0x40 | 24, 0x80 | 8

FONT = dict(ZAPPER_FONT)
FONT.update({     # 5 x 7, one string per row
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
})
HEX = "0123456789ABCDEF"

# The playfield's tiles (CHR bank 0) and the panel's (bank 1).
SKY, CLOUD, BRICK, TOP, GROUND, GRASS = range(6)
P_BG, P_FRAME, P_BLOCK = 0, 1, 2
P_DIGIT, P_X, P_Y = 0x10, 0x20, 0x21

PALETTES = (0x21, 0x02, 0x12, 0x30,     # sky; the panel's dark blue, blue, white
            0x21, 0x16, 0x27, 0x37,     # pillars, red
            0x21, 0x13, 0x23, 0x33,     # pillars, purple
            0x21, 0x17, 0x07, 0x2A)     # ground, and grass


def tile(rows):
    """8 strings of 8 colour digits (0-3) -> 16 bytes of CHR."""
    lo = [int("".join("1" if c in "13" else "0" for c in r), 2) for r in rows]
    hi = [int("".join("1" if c in "23" else "0" for c in r), 2) for r in rows]
    return bytes(lo + hi)


def glyph(ch):
    g = FONT[ch]
    rows = ["1" + "".join("3" if b == "1" else "1" for b in r) + "11" for r in g]
    return tile(rows + ["11111111"])


def chr_rom():
    c = bytearray(0x8000)
    tiles0 = {
        CLOUD: ["00333300", "03333330", "33333333", "33333333",
                "03333330", "00333300", "00000000", "00000000"],
        BRICK: ["11121111", "11121111", "22222222", "11111112",
                "11111112", "22222222", "11121111", "11121111"],
        TOP: ["33333333", "32222223", "22222222", "21111112",
              "21111112", "21111112", "22222222", "11121111"],
        GROUND: ["11111111", "11211111", "11111121", "11111111",
                 "12111111", "11111211", "11111111", "11121111"],
        GRASS: ["33333333", "33333333", "31331333", "11311131",
                "11111111", "11211111", "11111121", "11111111"],
    }
    for n, rows in tiles0.items():
        c[n * 16:n * 16 + 16] = tile(rows)
    tiles1 = {
        P_BG: ["11111111"] * 8,
        P_FRAME: ["22222222"] * 8,
        P_BLOCK: ["11111111"] + ["13333331"] * 6 + ["11111111"],
    }
    for n, rows in tiles1.items():
        c[0x1000 + n * 16:0x1000 + n * 16 + 16] = tile(rows)
    for i, ch in enumerate(HEX):
        c[0x1000 + (P_DIGIT + i) * 16:0x1000 + (P_DIGIT + i) * 16 + 16] = glyph(ch)
    for n, ch in ((P_X, "X"), (P_Y, "Y")):
        c[0x1000 + n * 16:0x1000 + n * 16 + 16] = glyph(ch)
    return bytes(c)


def pillar(col):
    """The pillar's height in tiles at playfield column col (0-63)."""
    return 0 if col % 5 in (0, 4) else min(8, (col * 7 + 3) % 10)


def nametables():
    """Two nametables (columns 0-31, then 32-63), with attributes."""
    out = bytearray()
    for nt in range(2):
        tiles = [[SKY] * 32 for _ in range(30)]
        for x in range(32):
            col = nt * 32 + x
            h = pillar(col)
            for r in range(26 - h, 26):
                tiles[r][x] = TOP if r == 26 - h else BRICK
            tiles[26][x] = GRASS
            for r in (27, 28, 29):
                tiles[r][x] = GROUND
            if (col * 13) % 17 < 3:
                tiles[4][x] = CLOUD
            if (col * 11) % 19 < 2:
                tiles[9][x] = CLOUD
        out += bytes(t for row in tiles for t in row)
        attr = bytearray(64)
        for qr in range(15):
            for qc in range(16):
                r, x = qr * 2, qc * 2
                if r >= 26:
                    pal = 3
                elif any(tiles[rr][xx] in (BRICK, TOP)
                         for rr in (r, r + 1) for xx in (x, x + 1)):
                    pal = 1 + ((nt * 16 + qc) // 2) % 2
                else:
                    pal = 0
                i = (qr // 2) * 8 + qc // 2
                attr[i] |= pal << (((qr & 1) << 2) | ((qc & 1) << 1))
        out += attr
    return bytes(out)


def panel():
    """The panel, 8 x 30 tiles, and each tile's palette."""
    rows, pals = [], []
    for r in range(30):
        if r in (0, 3, 29):
            row = [P_FRAME] * 8
        elif r == 1:
            row = [P_FRAME, P_X, P_BG, P_DIGIT, P_DIGIT, P_DIGIT, P_BG, P_FRAME]
        elif r == 2:
            row = [P_FRAME, P_Y, P_BG, P_BG, P_DIGIT, P_DIGIT, P_BG, P_FRAME]
        else:
            n = 1 + (r * 5) % 4
            row = ([P_FRAME, P_DIGIT + (r >> 4), P_DIGIT + (r & 15), P_BG] +
                   [P_BLOCK] * n + [P_BG] * (4 - n))
        rows.append(row)
        pals.append([0] * 8 if r < 4 else [0] * 4 + [1 + (r // 2) % 3] * 4)
    return rows, pals


def exram():
    """The panel at columns 0-7 (the left split) and 24-31 (the right
    one); the right split's last two fetches (seen with fine X) read
    columns 0 and 1, the panel's left edge. Attributes at $3C0."""
    ex = bytearray(0x400)
    rows, pals = panel()
    for r in range(30):
        for c in range(8):
            for base in (0, 24):
                ex[r * 32 + base + c] = rows[r][c]
                col = base + c
                i = 0x3C0 + (r >> 2) * 8 + (col >> 2)
                ex[i] |= pals[r][c] << (((r & 2) << 1) | (col & 2))
    return bytes(ex)


def rom():
    a = Asm(0xE000)
    br = []                                     # short branches to labels

    def branch(op, label):
        a.b(op, 0)
        br.append((len(a.code) - 1, label))

    def wait_vblank():
        here = a.pc()
        a.b(0xAD, 0x02, 0x20, 0x10, (here - (a.pc() + 5)) & 0xFF)

    def copy_pages(src, n, dst=None):
        """Copy n pages from src to dst, or to $2007 if dst is None."""
        for page in range(n):
            a.b(0xA2, 0)                        # LDX #0
            loop = a.pc()
            a.b(0xBD, 0, (src >> 8) + page)     # LDA src,X
            if dst is None:
                a.sta(0x2007)
            else:
                a.b(0x9D, 0, (dst >> 8) + page)  # STA dst,X
            a.b(0xE8)                           # INX
            a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)

    a.label("reset")
    a.b(0x78, 0xD8, 0xA2, 0xFF, 0x9A)           # SEI; CLD; LDX #$FF; TXS
    a.lda(0); a.sta(0x2000); a.sta(0x2001)
    a.lda(0x40); a.sta(0x4017)
    wait_vblank(); wait_vblank()
    # MMC5: 4 KB CHR, bank 0 for the playfield; vertical mirroring
    # ($2000 and $2800 CIRAM page 0, $2400 and $2C00 page 1).
    a.lda(1); a.sta(0x5101)
    a.lda(0); a.sta(0x5123); a.sta(0x5127)
    a.lda(0x44); a.sta(0x5105)
    a.lda(0x3F); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    for v in PALETTES:
        a.lda(v); a.sta(0x2007)
    a.lda(0x20); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    copy_pages(NT_TABLE, 8)                     # $2000-$27FF
    a.lda(2); a.sta(0x5104)
    copy_pages(EXRAM_TABLE, 4, 0x5C00)
    a.lda(0); a.sta(0x5104)
    a.lda(1); a.sta(0x5202)
    a.lda(0)
    for v in (BTN, OLD, XLO, XHI, PY, SIDE):
        a.b(0x85, v)                            # STA zp
    a.lda(0); a.sta(0x2003)                     # sprites off screen
    a.lda(0xF0); a.b(0xA2, 0)
    loop = a.pc()
    a.sta(0x2004); a.b(0xCA)
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)
    wait_vblank()
    a.lda(0x80); a.sta(0x2000)                  # NMI on
    a.label("idle")
    a.b(0x4C); a.fix.append((len(a.code), "idle")); a.b(0, 0)

    a.label("nmi")
    # Controller 1: A B Select Start Up Down Left Right, bit 7 to bit 0.
    a.lda(1); a.sta(0x4016); a.lda(0); a.sta(0x4016)
    a.b(0xA2, 8)
    loop = a.pc()
    a.lda_abs(0x4016); a.b(0x4A, 0x26, BTN)    # LSR; ROL BTN
    a.b(0xCA)                                   # DEX
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)     # BNE
    a.b(0xA5, OLD, 0x49, 0xFF, 0x25, BTN, 0x85, PRESS)  # PRESS = BTN & ~OLD
    a.b(0xA5, BTN, 0x85, OLD)
    # The playfield moves one pixel, unless Left is held.
    a.b(0xA5, BTN, 0x29, 0x02); branch(0xD0, "moved")
    a.b(0xE6, XLO); branch(0xD0, "moved")
    a.b(0xA5, XHI, 0x49, 0x01, 0x85, XHI)
    a.label("moved")
    # Down / Up: the panel's scroll, 0-239.
    a.b(0xA5, BTN, 0x29, 0x04); branch(0xF0, "no_down")
    a.b(0xE6, PY, 0xA5, PY, 0xC9, 240); branch(0xD0, "no_down")
    a.b(0xA9, 0, 0x85, PY)
    a.label("no_down")
    a.b(0xA5, BTN, 0x29, 0x08); branch(0xF0, "no_up")
    a.b(0xA5, PY); branch(0xD0, "up")
    a.b(0xA9, 240, 0x85, PY)
    a.label("up")
    a.b(0xC6, PY)
    a.label("no_up")
    # A: the other side.
    a.b(0xA5, PRESS, 0x29, 0x80); branch(0xF0, "no_a")
    a.b(0xA5, SIDE, 0x49, 0x01, 0x85, SIDE)
    a.label("no_a")
    # The digits, in both copies of the panel (ExRAM mode 2 meanwhile).
    a.lda(2); a.sta(0x5104)
    for base in (0x5C00, 0x5C18):
        a.b(0xA5, XHI, 0x09, P_DIGIT); a.sta(base + 32 + 3)
        for zp, at in ((XLO, base + 32 + 4), (PY, base + 64 + 4)):
            a.b(0xA5, zp, 0x4A, 0x4A, 0x4A, 0x4A, 0x09, P_DIGIT); a.sta(at)
            a.b(0xA5, zp, 0x29, 0x0F, 0x09, P_DIGIT); a.sta(at + 1)
    a.lda(0); a.sta(0x5104)
    # The split, the scroll, rendering on.
    a.lda(RIGHT_SPLIT); a.b(0xA4, SIDE); a.b(0xF0, 2); a.lda(LEFT_SPLIT)
    a.sta(0x5200)
    a.b(0xA5, PY); a.sta(0x5201)
    a.b(0xA5, XLO); a.sta(0x2005); a.lda(0); a.sta(0x2005)
    a.b(0xA5, XHI, 0x09, 0x80); a.sta(0x2000)
    a.lda(0x1E); a.sta(0x2001)
    a.b(0x40)                                   # RTI

    for pos, label in br:
        a.code[pos] = (a.labels[label] - (a.org + pos + 1)) & 0xFF
    code = a.done()
    assert len(code) <= NT_TABLE - 0xE000, "code too long"

    prg = bytearray(0x8000)
    prg[0x6000:0x6000 + len(code)] = code
    prg[NT_TABLE - 0x8000:NT_TABLE - 0x8000 + 0x800] = nametables()
    prg[EXRAM_TABLE - 0x8000:EXRAM_TABLE - 0x8000 + 0x400] = exram()
    for vec, label in ((0x7FFA, "nmi"), (0x7FFC, "reset"), (0x7FFE, "nmi")):
        t = a.labels[label]
        prg[vec], prg[vec + 1] = t & 0xFF, t >> 8
    header = bytes([0x4E, 0x45, 0x53, 0x1A, 2, 4, 0x50, 0x00]) + bytes(8)
    return header + prg + chr_rom()


SCRIPT = """\
# For tests/mmc5_split_demo.nes (make_split_demo.py): scroll the panel
# down 50 lines, move it to the left, stop the playfield for a while.
100 down
150
170 a
176
200 left
230
"""


def main():
    path = os.path.join(HERE, "mmc5_split_demo.nes")
    with open(path, "wb") as f:
        f.write(rom())
    print("wrote", path)
    path = os.path.join(HERE, "inputs", "mmc5_split_demo.txt")
    with open(path, "w") as f:
        f.write(SCRIPT)
    print("wrote", path)


if __name__ == "__main__":
    main()
