#!/usr/bin/env python3
"""Write the Sunsoft-4 tests (mapper 68) made for nesrecomp
(PLAN-mappers3.md step 5). Run it again to regenerate the ROMs.

From the nesdev wiki ("INES Mapper 068"): 16 KB at $8000 switches
($F000 bits 0-3), the last 16 KB is fixed, $F000 bit 4 enables the PRG
RAM; four 2 KB CHR banks ($8000, $9000, $A000, $B000); $E000 bits 0-1
mirroring (0 vertical, 1 horizontal, 2/3 one screen: the first / second
table) and bit 4 nametables from CHR ROM: the 1 KB banks $C000 (in place
of the first table) and $D000 (the second), bit 7 always taken as 1, so
in the last 128 KB. Each register answers through its whole 4 KB.

tests/sunsoft4_switch.nes: 128 KB PRG (eight 16 KB banks, the byte at
offset $3F00 of each holding its number), 256 KB CHR (256 1 KB banks,
byte 0 of each holding its number), horizontal mirroring in the header.
Status codes:
  0  passed
  2  at power-on, $8000 isn't PRG bank 0 or $C000 the last, or CHR
     $0000 isn't 1 KB bank 0
  3  $F000 = $15: $8000 isn't bank 5, or $C000 moved
  4  CHR: $8000 = 3, $9FFF = 4, $A123 = 5, $BFFF = $7F: PPU $0000/$0400
     aren't 1 KB banks 6/7, $0800 isn't 8, $1000 isn't 10, $1800/$1C00
     aren't $FE/$FF
  5  $E000 = 0 didn't give vertical mirroring (of CIRAM)
  6  $E800 = 1 didn't give horizontal mirroring
  7  $EFFF = 2 / 3 didn't give one screen, the first / second table
  8  ROM nametables, vertical ($E000 = $10, $C000 = 5, $D000 = 6):
     $2000-$2C00 aren't banks $85, $86, $85, $86
  9  ... horizontal ($11): aren't $85, $85, $86, $86
 10  ... one screen ($12, $13): aren't all $85, all $86; or $CFFF = $7F
     isn't bank $FF
 11  a write to a ROM nametable changed it, or went into CIRAM
 12  back to CIRAM ($E000 = 0): CIRAM didn't keep what it had
 13  PRG RAM: with $F000 bit 4 clear, a write to $6100 got through
     (read back once it was enabled again)

tests/sunsoft4_picture.nes: a picture, checked as a regression
(suite "frame"). The background is drawn only from CHR ROM nametables
(CIRAM is never written): above the white square (sprite 0, at line
112) $C000 = 0, bank $80: red horizontal stripes; once sprite 0 is hit
the program writes $C000 = 2, bank $82: blue vertical stripes. With
CIRAM instead, the screen would be black.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mappers3_common import Asm, HERE, start, ppu_write, ppu_check, ppu_read, finish  # noqa: E402

PRG_BANKS = 8                   # 16 KB
CHR_BANKS = 256                 # 1 KB
ID = 0x3F00


def nes(name, prg, chr_rom, f6):
    header = bytes([0x4E, 0x45, 0x53, 0x1A, len(prg) // 0x4000, len(chr_rom) // 0x2000,
                    f6 | 0x40, 0x40]) + bytes(8)      # mapper 68 ($44)
    out = os.path.join(HERE, name)
    with open(out, "wb") as f:
        f.write(header + bytes(prg) + bytes(chr_rom))
    print("wrote", out)


def put_code(code, labels, nmi=None, irq=None):
    prg = bytearray(PRG_BANKS * 0x4000)
    for bank in range(PRG_BANKS):
        prg[bank * 0x4000 + ID] = bank
    base = (PRG_BANKS - 1) * 0x4000
    assert len(code) < ID, len(code)
    prg[base:base + len(code)] = code
    prg[base + 0x3FF0] = 0x40                   # RTI at $FFF0
    for vec, target in ((0xFFFA, 0xFFF0), (0xFFFC, 0xC000), (0xFFFE, 0xFFF0)):
        prg[base + vec - 0xC000] = target & 0xFF
        prg[base + vec - 0xC000 + 1] = target >> 8
    return prg


def switch_program():
    a = start(0xC000)
    a.check(0x8000 + ID, 0, "fail2")
    a.check(0xC000 + ID, PRG_BANKS - 1, "fail2")
    ppu_check(a, 0x0000, 0, "fail2")
    a.lda(0x15); a.sta(0xF000)
    a.check(0x8000 + ID, 5, "fail3")
    a.check(0xC000 + ID, PRG_BANKS - 1, "fail3")
    for addr, v in ((0x8000, 3), (0x9FFF, 4), (0xA123, 5), (0xBFFF, 0x7F)):
        a.lda(v); a.sta(addr)
    for ppu, bank in ((0x0000, 6), (0x0400, 7), (0x0800, 8), (0x1000, 10),
                      (0x1800, 0xFE), (0x1C00, 0xFF)):
        ppu_check(a, ppu, bank, "fail4")
    # CIRAM: T0[0], T1[0] from vertical, then T0[0] = $33 from horizontal.
    a.lda(0); a.sta(0xE000)
    ppu_write(a, 0x2000, 0x11); ppu_write(a, 0x2400, 0x22)
    ppu_check(a, 0x2800, 0x11, "fail5")
    ppu_check(a, 0x2C00, 0x22, "fail5")
    a.lda(1); a.sta(0xE800)
    ppu_write(a, 0x2000, 0x33)
    ppu_check(a, 0x2400, 0x33, "fail6")
    ppu_check(a, 0x2800, 0x22, "fail6")
    a.lda(2); a.sta(0xEFFF)
    ppu_check(a, 0x2C00, 0x33, "fail7")
    a.lda(3); a.sta(0xEFFF)
    ppu_check(a, 0x2000, 0x22, "fail7")
    # Nametables from CHR ROM.
    a.lda(5); a.sta(0xC000)
    a.lda(6); a.sta(0xD000)
    for ctrl, want, status in ((0x10, (0x85, 0x86, 0x85, 0x86), "fail8"),
                               (0x11, (0x85, 0x85, 0x86, 0x86), "fail9"),
                               (0x12, (0x85,) * 4, "fail10"),
                               (0x13, (0x86,) * 4, "fail10")):
        a.lda(ctrl); a.sta(0xE000)
        for i, w in enumerate(want):
            ppu_check(a, 0x2000 + i * 0x400, w, status)
    a.lda(0x7F); a.sta(0xCFFF)
    a.lda(0x12); a.sta(0xE000)
    ppu_check(a, 0x2400, 0xFF, "fail10")
    a.lda(5); a.sta(0xC000)
    # A write to a ROM nametable: nothing changes, CIRAM included.
    ppu_write(a, 0x2000, 0xEE)
    ppu_check(a, 0x2000, 0x85, "fail11")
    a.lda(0x02); a.sta(0xE000)                  # CIRAM, the first table
    ppu_check(a, 0x2000, 0x33, "fail11")
    a.lda(0x00); a.sta(0xE000)
    ppu_check(a, 0x2000, 0x33, "fail12")
    ppu_check(a, 0x2400, 0x22, "fail12")
    # PRG RAM off: a write doesn't land.
    a.lda(0xAA); a.sta(0x6100)
    a.lda(0x05); a.sta(0xF000)
    a.lda(0x77); a.sta(0x6100)
    a.lda(0x15); a.sta(0xF000)
    a.check(0x6100, 0xAA, "fail13")
    return finish(a, range(2, 14)), a.labels


def switch_rom():
    code, labels = switch_program()
    chr_rom = bytearray(CHR_BANKS * 0x400)
    for bank in range(CHR_BANKS):
        chr_rom[bank * 0x400] = bank
    nes("sunsoft4_switch.nes", put_code(code, labels), chr_rom, f6=0)


# --- the picture --------------------------------------------------------
RED, BLUE, BLACK = 0x10, 0x12, 0x13             # background tiles
SOLID = {0x10: 1, 0x11: 2, 0x12: 3, 0x13: 0}    # tile -> colour


def picture_program():
    a = Asm(0xC000)
    a.b(0x78, 0xD8, 0xA2, 0xFF, 0x9A)           # SEI; CLD; stack
    a.lda(0x40); a.sta(0x4017)
    a.lda(0); a.sta(0x2000); a.sta(0x2001)
    for _ in range(2):
        a.b(0x2C, 0x02, 0x20, 0x10, 0xFB)       # wait for vblank
    a.lda(0x10); a.sta(0xF000)                  # PRG bank 0, RAM on
    a.lda(0); a.sta(0x8000)                     # BG tiles: 1 KB banks 0-1
    a.lda(2); a.sta(0xA000)                     # sprites: 1 KB banks 4-5
    a.lda(0); a.sta(0xC000)
    a.lda(1); a.sta(0xD000)
    a.lda(0x10); a.sta(0xE000)                  # vertical, ROM nametables
    for addr, colour in ((0x3F00, 0x0F), (0x3F01, 0x16), (0x3F02, 0x2A),
                         (0x3F03, 0x12), (0x3F11, 0x30)):
        ppu_write(a, addr, colour)
    # OAM at $0200: sprite 0 at line 112 (over a red row), x 124; the rest
    # off screen.
    a.lda(0xF0); a.b(0xA2, 0)
    a.b(0x9D, 0x00, 0x02, 0xE8, 0xD0, 0xFA)     # loop: STA $0200,X; INX; BNE
    for i, v in enumerate((111, 0, 0, 124)):
        a.lda(v); a.sta(0x0200 + i)
    a.label("frame")
    a.b(0x2C, 0x02, 0x20, 0x10, 0xFB)           # wait for vblank
    a.lda(2); a.sta(0x4014)                     # OAM DMA
    a.lda(0); a.sta(0xC000)                     # top: bank $80
    a.lda_abs(0x2002)
    a.lda(0); a.sta(0x2005); a.sta(0x2005)
    a.lda(0x08); a.sta(0x2000)                  # sprites at $1000
    a.lda(0x1E); a.sta(0x2001)
    a.b(0x2C, 0x02, 0x20, 0x70, 0xFB)           # wait: sprite 0 flag clear
    a.b(0x2C, 0x02, 0x20, 0x50, 0xFB)           # wait: sprite 0 hit
    a.lda(2); a.sta(0xC000)                     # the rest: bank $82
    a.b(0x4C, a.labels["frame"] & 0xFF, a.labels["frame"] >> 8)
    return a.done(), a.labels


def tile(colour):
    lo = 0xFF if colour & 1 else 0
    hi = 0xFF if colour & 2 else 0
    return bytes([lo] * 8 + [hi] * 8)


def nametable(fill):
    t = bytearray(0x400)
    for row in range(30):
        for col in range(32):
            t[row * 32 + col] = fill(row, col)
    return t


def picture_rom():
    code, labels = picture_program()
    chr_rom = bytearray(CHR_BANKS * 0x400)
    for t, colour in SOLID.items():             # BG tiles, 1 KB bank 0
        chr_rom[t * 16:t * 16 + 16] = tile(colour)
    chr_rom[4 * 0x400:4 * 0x400 + 16] = tile(1)  # sprite tile 0 (white)
    tables = {
        0x80: nametable(lambda r, c: RED if r % 2 == 0 else BLACK),
        0x81: nametable(lambda r, c: BLACK),
        0x82: nametable(lambda r, c: BLUE if c % 2 == 0 else BLACK),
    }
    for bank, data in tables.items():
        chr_rom[bank * 0x400:bank * 0x400 + 0x400] = data
    nes("sunsoft4_picture.nes", put_code(code, labels), chr_rom, f6=0)


if __name__ == "__main__":
    switch_rom()
    picture_rom()
