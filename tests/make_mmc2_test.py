#!/usr/bin/env python3
"""Write tests/mmc2_9.nes and tests/mmc4_10.nes: MMC2 (mapper 9) and MMC4
(mapper 10) tests made for nesrecomp. Run it again to regenerate them.

Both chips pick each pattern table's 4 KB CHR bank with a latch that the
PPU flips by reading tile $FD or $FE's second plane ($xFD8 -> $FD, $xFE8
-> $FE). The latches react to any PPU read, so these ROMs drive them
through $2007 with rendering off.

128 KB PRG; byte $1FF0 of each 8 KB bank holds its number. 64 KB CHR ROM
(sixteen 4 KB banks): byte $000 of each holds its number, byte $FE8 holds
$40 + its number. The program runs from the fixed last 8 KB.

Results use the blargg $6000 protocol; status codes:

   0  passed
   2  PRG bank written to $A000 isn't at $8000
   3  the fixed banks aren't the last ones
   4  latch 0 = $FD (read $0FD8): $0000 isn't the $B000 bank
   5  latch 0 = $FE (read $0FE8): $0000 isn't the $C000 bank
   6  latch 1 = $FD (read $1FD8): $1000 isn't the $D000 bank
   7  latch 1 = $FE (read $1FE8): $1000 isn't the $E000 bank
   8  reading $0FD9 (row 1 of tile $FD): MMC2 must ignore it, MMC4 must
      switch latch 0 to $FD
   9  the read that flips a latch must still see the old bank
  10  $F000 mirroring: 0 (vertical) must make $2800 match $2000, then
      1 (horizontal) must make $2400 match it
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_mmc1_test import Asm  # noqa: E402

PRG_BANKS = 16              # 8 KB
CHR_BANKS = 16              # 4 KB
TAG = 0x1FF0


def program(mapper):
    a = Asm(0xE000)

    def ppu_addr(addr):
        a.lda(addr >> 8); a.sta(0x2006); a.lda(addr & 0xFF); a.sta(0x2006)

    def read_ppu(addr):
        """A = PPU byte at addr (the second $2007 read). The PPU reads addr,
        then addr + 1."""
        ppu_addr(addr)
        a.lda_abs(0x2007); a.lda_abs(0x2007)

    def touch(addr):
        """One PPU read at addr, to flip a latch."""
        ppu_addr(addr)
        a.lda_abs(0x2007)

    a.label("reset")
    a.b(0x78, 0xA2, 0xFF, 0x9A)                 # SEI; LDX #$FF; TXS
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)
    a.lda(0x00); a.sta(0x6004)

    # PRG: MMC2 switches 8 KB, MMC4 16 KB, at $8000.
    if mapper == 9:
        a.lda(5); a.sta(0xA000)
        a.check(0x9FF0, 5, "fail2")
        a.check(0xBFF0, PRG_BANKS - 3, "fail3")
        a.check(0xDFF0, PRG_BANKS - 2, "fail3")
    else:
        a.lda(3); a.sta(0xA000)
        a.check(0x9FF0, 6, "fail2")
        a.check(0xBFF0, 7, "fail2")
        a.check(0xDFF0, PRG_BANKS - 2, "fail3")

    a.lda(1); a.sta(0xB000)
    a.lda(2); a.sta(0xC000)
    a.lda(3); a.sta(0xD000)
    a.lda(4); a.sta(0xE000)
    touch(0x0FD8); read_ppu(0x0000); a.cmp(1); a.bne("fail4")
    touch(0x0FE8); read_ppu(0x0000); a.cmp(2); a.bne("fail5")
    touch(0x1FD8); read_ppu(0x1000); a.cmp(3); a.bne("fail6")
    touch(0x1FE8); read_ppu(0x1000); a.cmp(4); a.bne("fail7")

    # Row 1 of tile $FD in the left table (latch 0 is $FE now).
    touch(0x0FD9); read_ppu(0x0000)
    a.cmp(2 if mapper == 9 else 1); a.bne("fail8")

    # Latch 0 to $FD (bank 1), then read $0FE8: that read itself must come
    # from bank 1 ($41), and only later reads from bank 2.
    touch(0x0FD8)
    read_ppu(0x0FE8); a.cmp(0x41); a.bne("fail9")
    read_ppu(0x0000); a.cmp(2); a.bne("fail9")

    # The header says horizontal, so switch to vertical first: $2800
    # mirrors $2000 and $2400 is separate; then horizontal: $2400 mirrors
    # $2000.
    a.lda(0); a.sta(0xF000)                     # vertical
    ppu_addr(0x2000); a.lda(0x5A); a.sta(0x2007)
    ppu_addr(0x2400); a.lda(0xA5); a.sta(0x2007)
    read_ppu(0x2800); a.cmp(0x5A); a.bne("fail10")
    a.lda(1); a.sta(0xF000)                     # horizontal
    read_ppu(0x2400); a.cmp(0x5A); a.bne("fail10")

    a.label("pass")
    for status in [0] + list(range(2, 11)):
        if status:
            a.label("fail%d" % status)
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)
    a.label("nmi")
    a.b(0x40)
    return a


def build(mapper, name):
    a = program(mapper)
    code = a.done()
    prg = bytearray()
    for bank in range(PRG_BANKS):
        b = bytearray(0x2000)
        b[TAG] = bank
        prg += b
    last = (PRG_BANKS - 1) * 0x2000
    assert len(code) < TAG
    prg[last:last + len(code)] = code
    for vec, label in ((0x1FFA, "nmi"), (0x1FFC, "reset"), (0x1FFE, "nmi")):
        target = a.labels[label]
        prg[last + vec] = target & 0xFF
        prg[last + vec + 1] = target >> 8
    chr_rom = bytearray()
    for bank in range(CHR_BANKS):
        c = bytearray(0x1000)
        c[0] = bank
        c[0xFE8] = 0x40 + bank
        chr_rom += c
    header = bytes([0x4E, 0x45, 0x53, 0x1A, len(prg) // 0x4000,
                    len(chr_rom) // 0x2000, (mapper & 0x0F) << 4,
                    mapper & 0xF0]) + bytes(8)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    with open(out, "wb") as f:
        f.write(header + prg + chr_rom)
    print("wrote", out)


if __name__ == "__main__":
    build(9, "mmc2_9.nes")
    build(10, "mmc4_10.nes")
