#!/usr/bin/env python3
"""Write tests/nsf_banks.nsf: an NSF bank-switching test made for nesrecomp.
Run it again to regenerate it.

From the nesdev wiki's "NSF": when any of the header bytes $70-$77 is
non-zero, $8000-$FFFF is eight 4 KB slots, slot i set by writing a bank
number to $5FF8 + i, and those header bytes are the banks each slot
starts with. The file's data is cut into 4 KB banks starting from the
load address's offset within 4 KB (here $100: the file's first byte is
byte $100 of bank 0).

Twelve banks, each with its number at offset $FF0. The test runs in init
(in bank 11, slot $F000) and reports through the blargg $6000 protocol:
   0  passed
   2  a slot doesn't hold the header's starting bank
   3  after $5FF9 = 7, $9000 doesn't hold bank 7, or $8000 (the other
      half of the same 8 KB) changed too
   4  the same address in two banks: JSR $9000 with bank 7 there and
      then bank 8 didn't run each bank's own code
   5  code at $A000 switching its own slot ($5FFA) didn't carry on in
      the new bank's code
   6  the load offset: the file's first byte isn't at $x100 of bank 0
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402

BANKS = 12
START = [3, 9, 2, 10, 4, 5, 6, 11]      # slot -> starting bank
LOAD = 0x8100
TAG = 0xFF0
FIRST = 0x5A                            # the file's first byte


def put(image, bank, offset, code):
    at = bank * 0x1000 + offset
    image[at:at + len(code)] = code


def build():
    image = bytearray(BANKS * 0x1000)
    for b in range(BANKS):
        image[b * 0x1000 + TAG] = b
    image[0x100] = FIRST

    # Same address, different code: $9000 in banks 7 and 8.
    for bank, value in ((7, 0x70), (8, 0x80)):
        r = Asm(0x9000)
        r.lda(value); r.rts()
        put(image, bank, 0, r.done())
    # Code that switches its own slot: at $A000 in bank 2, it maps bank 1
    # there; the next instruction ($A005) comes from bank 1.
    r = Asm(0xA000)
    r.lda(1); r.sta(0x5FFA)
    r.lda(0x22); r.rts()                # bank 2 carrying on: wrong
    put(image, 2, 0, r.done())
    r = Asm(0xA005)
    r.lda(0x11); r.rts()                # bank 1: right
    put(image, 1, 5, r.done())

    a = Asm(0xF000)
    a.label("init")
    a.b(0x78, 0xD8)                     # SEI; CLD
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)
    a.lda(0x00); a.sta(0x6004)
    for s, bank in enumerate(START):
        a.check(0x8000 + s * 0x1000 + TAG, bank, "fail2")
    a.lda(7); a.sta(0x5FF9)
    a.check(0x9000 + TAG, 7, "fail3")
    a.check(0x8000 + TAG, START[0], "fail3")
    a.jsr(0x9000); a.cmp(0x70); a.bne("fail4")
    a.lda(8); a.sta(0x5FF9)
    a.jsr(0x9000); a.cmp(0x80); a.bne("fail4")
    a.jsr(0xA000); a.cmp(0x11); a.bne("fail5")
    a.lda(0); a.sta(0x5FFB)             # bank 0 at $B000
    a.check(0xB100, FIRST, "fail6")
    a.label("pass")
    for status in (0, 2, 3, 4, 5, 6):
        if status:
            a.label("fail%d" % status)
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)
    a.label("play")
    a.rts()
    a.label("vector")
    a.b(0x40)                           # RTI
    code = a.done()
    assert len(code) < TAG
    put(image, 11, 0, code)
    for vec in (0xFFA, 0xFFC, 0xFFE):
        t = a.labels["vector"]
        put(image, 11, vec, bytes([t & 0xFF, t >> 8]))

    init, play = a.labels["init"], a.labels["play"]
    header = bytearray(0x80)
    header[0:5] = b"NESM\x1a"
    header[5] = 1                       # version
    header[6] = 1                       # songs
    header[7] = 1                       # starting song
    for at, v in ((8, LOAD), (10, init), (12, play), (0x6E, 16639)):
        header[at], header[at + 1] = v & 0xFF, v >> 8
    header[0x0E:0x0E + 9] = b"nsf_banks"
    header[0x2E:0x2E + 9] = b"nesrecomp"
    header[0x70:0x78] = bytes(START)
    return bytes(header) + bytes(image[LOAD & 0xFFF:])


def main():
    path = os.path.join(HERE, "nsf_banks.nsf")
    with open(path, "wb") as f:
        f.write(build())
    print("wrote", path)


if __name__ == "__main__":
    main()
