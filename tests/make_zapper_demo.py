#!/usr/bin/env python3
"""Write tests/zapper_demo.nes: a Zapper target to try by hand, made for
nesrecomp, and tests/inputs/zapper_demo.txt, a script that fires one hit
and one miss for the picture check. Run it again to regenerate both.

    make run ROM=tests/zapper_demo.nes ARGS="--port2 zapper"

A white 16 x 16 box slides left and right across a black screen. Pull
the trigger (the left mouse button) and the program watches the light
sensor ($4017 bit 3, port 2) for the rest of that frame: light seen is a
hit, none a miss. The two counts are shown at the top in red, which is
too dark for the sensor, so only the box counts.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402

FRAMES, BOX_X, DX, OLD, LIT, F0 = 0x10, 0x11, 0x12, 0x13, 0x14, 0x15
HITS, MISSES = 0x20, 0x23              # three decimal digits each
BOX_Y = 112
OAM = 0x0200
LEFT, RIGHT = 16, 224                  # the box's travel
SOLID = 0x01
HITS_AT, MISSES_AT = 0x2044, 0x2084    # rows 2 and 4, column 4

FONT = {    # 5 x 7, one string per row
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
}


def chr_rom():
    chr_ = bytearray(0x2000)
    chr_[SOLID * 16:SOLID * 16 + 8] = b"\xff" * 8
    for ch, rows in FONT.items():
        t = ord(ch) * 16
        for r, bits in enumerate(rows):
            chr_[t + r] = int(bits, 2) << 2
    return chr_


def rom():
    a = Asm(0xE000)

    def vram(addr):
        a.b(0xAD, 0x02, 0x20)                   # LDA $2002
        a.lda(addr >> 8); a.sta(0x2006); a.lda(addr & 0xFF); a.sta(0x2006)

    def text(addr, s):
        vram(addr)
        for ch in s:
            a.lda(ord(ch)); a.sta(0x2007)

    a.label("reset")
    a.b(0x78, 0xD8, 0xA2, 0xFF, 0x9A)           # SEI; CLD; LDX #$FF; TXS
    a.lda(0x40); a.sta(0x4017)
    a.lda(0x00); a.sta(0x2000); a.sta(0x2001)
    for _ in range(2):
        a.b(0x2C, 0x02, 0x20, 0x10, 0xFB)       # BIT $2002; BPL
    # Zero page and OAM ($0200): all 0, then sprites off screen.
    a.lda(0); a.b(0xA2, 0)
    loop = a.pc()
    a.b(0x95, 0x00, 0x9D, 0x00, 0x02, 0xE8)     # STA 0,X; STA $200,X; INX
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)
    a.lda(0xF0); a.b(0xA2, 0)
    loop = a.pc()
    a.b(0x9D, 0x00, 0x02, 0xE8)                 # STA $200,X; INX
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)
    a.lda(LEFT); a.b(0x85, BOX_X)
    a.lda(1); a.b(0x85, DX)
    for d in range(3):
        a.lda(ord("0")); a.b(0x85, HITS + d, 0x85, MISSES + d)
    # Nametable 0 clear, the labels, the palettes.
    vram(0x2000)
    a.lda(0); a.b(0xA0, 4, 0xA2, 0)
    loop = a.pc()
    a.sta(0x2007); a.b(0xCA)
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)
    a.b(0x88)
    a.b(0xD0, (loop - (a.pc() + 2)) & 0xFF)
    text(HITS_AT + 4, "HITS")
    text(MISSES_AT + 4, "MISSES")
    vram(0x3F00)
    for v in (0x0F, 0x16, 0x16, 0x16):          # background: red text
        a.lda(v); a.sta(0x2007)
    vram(0x3F10)
    for v in (0x0F, 0x30, 0x30, 0x30):          # sprites: white
        a.lda(v); a.sta(0x2007)
    a.lda(0x80); a.sta(0x2000)
    a.lda(0x1E); a.sta(0x2001)                  # background and sprites

    a.label("frame")                            # wait for the NMI
    a.b(0xA5, FRAMES)
    a.b(0xC5, FRAMES, 0xF0, 0xFC)               # CMP FRAMES; BEQ back
    a.label("vblank")
    a.lda(OAM >> 8); a.sta(0x4014)              # sprites
    for at, digits in ((HITS_AT, HITS), (MISSES_AT, MISSES)):
        vram(at)
        for d in range(3):
            a.b(0xA5, digits + d); a.sta(0x2007)
    a.lda(0); a.sta(0x2005); a.sta(0x2005)
    a.lda(0x80); a.sta(0x2000)

    # Move the box, turning at either end.
    a.b(0xA5, BOX_X, 0x18, 0x65, DX, 0x85, BOX_X)   # BOX_X += DX
    a.cmp(RIGHT); a.b(0xF0, 0x04)               # at the right: turn
    a.cmp(LEFT); a.b(0xD0, 0x09)                # not at the left: on
    a.b(0xA5, DX, 0x49, 0xFF, 0x18, 0x69, 0x01, 0x85, DX)  # DX = -DX
    # Four sprites, 2 x 2, at (BOX_X, BOX_Y).
    for i, (dx, dy) in enumerate(((0, 0), (8, 0), (0, 8), (8, 8))):
        a.lda(BOX_Y + dy - 1); a.sta(OAM + 4 * i)
        a.lda(SOLID); a.sta(OAM + 4 * i + 1)
        a.lda(0); a.sta(OAM + 4 * i + 2)
        a.b(0xA5, BOX_X)
        if dx:
            a.b(0x18, 0x69, dx)                 # CLC; ADC #dx
        a.sta(OAM + 4 * i + 3)

    # The trigger: on a new pull, watch the sensor until the next NMI.
    a.lda_abs(0x4017); a.b(0x29, 0x10)          # this frame's trigger
    a.b(0xA8)                                   # TAY
    a.b(0xA5, OLD, 0x84, OLD)                   # LDA OLD; STY OLD
    a.b(0xD0, 0x03)                             # held before: no shot
    a.b(0x98, 0xD0, 0x03)                       # TYA; BNE shoot
    a.b(0x4C); a.fix.append((len(a.code), "frame")); a.b(0, 0)
    a.lda(0); a.b(0x85, LIT)                    # shoot:
    a.b(0xA5, FRAMES, 0x85, F0)
    watch = a.pc()
    a.lda_abs(0x4017); a.b(0x29, 0x08)
    a.b(0xD0, 0x04)                             # dark: skip
    a.lda(1); a.b(0x85, LIT)
    a.b(0xA5, FRAMES, 0xC5, F0)
    a.b(0xF0, (watch - (a.pc() + 2)) & 0xFF)
    a.b(0xA2, HITS + 2)                         # LDX #last hit digit
    a.b(0xA5, LIT)
    a.b(0xD0, 0x02)                             # lit: count a hit
    a.b(0xA2, MISSES + 2)                       # LDX #last miss digit
    count = a.pc()                              # add 1 to the digits at X
    a.b(0xF6, 0x00)                             # INC 0,X
    a.b(0xB5, 0x00)                             # LDA 0,X
    a.cmp(ord("9") + 1)
    a.b(0xD0, 0x08)                             # no carry: done
    a.lda(ord("0")); a.b(0x95, 0x00, 0xCA)      # STA 0,X; DEX
    a.b(0x4C, count & 0xFF, count >> 8)
    a.b(0x4C); a.fix.append((len(a.code), "vblank")); a.b(0, 0)

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


def script():
    # The box starts at LEFT and moves 1 pixel a frame; the program's
    # frame count runs a few frames behind the runtime's, so aim at a
    # spot the box covers for a while and pull while it's there.
    return ("# For tests/zapper_demo.nes (make_zapper_demo.py): one hit, then\n"
            "# one miss, for the picture check.\n"
            "30 aim=%d,%d\n"
            "34 aim=%d,%d trigger\n"
            "40\n"
            "60 aim=off\n"
            "64 aim=off trigger\n"
            "70\n" % (LEFT + 30, BOX_Y + 8, LEFT + 30, BOX_Y + 8))


def main():
    path = os.path.join(HERE, "zapper_demo.nes")
    with open(path, "wb") as f:
        f.write(rom())
    print("wrote", path, "(run with --port2 zapper)")
    spath = os.path.join(HERE, "inputs", "zapper_demo.txt")
    with open(spath, "w") as f:
        f.write(script())
    print("wrote", spath)


if __name__ == "__main__":
    main()
