#!/usr/bin/env python3
"""Write tests/txc_switch.nes: a TXC 22211 / JV001 test for mapper 172
(1991 Du Ma Racing), made for nesrecomp (PLAN-mappers3.md step 2). Run it
again to regenerate the ROM.

32 KB PRG that never moves, 32 KB CHR ROM (four 8 KB banks, byte 0 of
each holding $C0 + its number), vertical mirroring in the header.

From the nesdev wiki ("INES Mapper 172", "INES Mapper 136"): mapper 136's
JV001 chip, mounted upside down, so the CPU's data bits D0-D5 reach it as
D5-D0. Registers where address AND $E103 is $4100-$4103: $4102 Input,
$4101 Invert (CPU bit 5), $4103 Mode (CPU bit 5); a $4100 write copies
Input to Register, its low four bits (in the chip's order) inverted if
Invert, or with Mode set counts those four bits up; a read gives Register
with the chip's bits 4-5 inverted if Invert. A write to $8000-$FFFF
copies Register to Output: Output's chip bits 0-1 (CPU bits 5 and 4) are
the CHR bank, and mirroring becomes horizontal (Invert clear) or vertical
(Invert set).

The expected values below are worked out by hand from the wiki, in the
CPU's bit order ("r" is the six bits reversed):

  0  passed
  2  at power-on, CHR isn't bank 0, or the header's vertical mirroring
     isn't in use
  3  Input $2A copied and read back isn't $2A (no inversion: read = Input)
  4  Input $10 (CPU bit 4 = chip bit 1) copied to Output isn't CHR bank 2
  5  that $8000 write, Invert clear, didn't give horizontal mirroring
  6  Invert set: reading Register (Input $10) isn't $13 (the chip's bits
     4-5, CPU bits 1 and 0, inverted)
  7  a $4100 write with Invert set (Register = Input with CPU bits 2-5
     inverted, $2F read with Invert) then $8000 isn't CHR bank 1
  8  that $8000 write, Invert set, didn't give vertical mirroring
  9  that Register read with Invert set isn't $2F
 10  Mode set, a $4100 write counts up, Invert cleared: read isn't $1C
 11  Register $3F counted up isn't $30 (the low four chip bits wrap
     without carrying into bits 4-5): read isn't $03
 12  a write to $4203 (address AND $E103 = $4003, no register) changed
     Mode: the next $4100 write didn't count up to $31 (read $23)
 13  the mirrors $5503 (Mode), $4302 (Input), $5100 ($4100) and $5F00
     (read) don't act as the registers: read isn't $01
"""
from mappers3_common import start, ppu_write, ppu_check, finish, vectors, write_nes

CHR_BANKS = 4
RTI = 0xFF00


def program():
    a = start(0x8000)
    ppu_check(a, 0x0000, 0xC0, "fail2")
    ppu_write(a, 0x2000, 0x11)
    ppu_write(a, 0x2400, 0x22)
    ppu_check(a, 0x2800, 0x11, "fail2")
    # Mode 0, Invert 0: Register = Input, read back as written.
    a.lda(0x2A); a.sta(0x4102)
    a.sta(0x4100)
    a.check(0x4100, 0x2A, "fail3")
    # Input $10: chip bit 1, so CHR bank 2 once copied to Output.
    a.lda(0x10); a.sta(0x4102)
    a.sta(0x4100)
    a.sta(0x8000)
    ppu_check(a, 0x0000, 0xC2, "fail4")
    ppu_write(a, 0x2000, 0x33)
    ppu_check(a, 0x2400, 0x33, "fail5")
    # Invert on: the read flips the chip's bits 4-5 (CPU bits 1 and 0).
    a.lda(0x20); a.sta(0x4101)
    a.check(0x4100, 0x13, "fail6")
    # Copy with Invert: the chip's bits 0-3 (CPU bits 5-2) flip, so
    # Register is chip 001101; Output bits 0-1 = 01: CHR bank 1.
    a.sta(0x4100)
    a.sta(0x8000)
    ppu_check(a, 0x0000, 0xC1, "fail7")
    ppu_write(a, 0x2000, 0x44)
    ppu_check(a, 0x2800, 0x44, "fail8")
    a.check(0x4100, 0x2F, "fail9")
    # Mode 1: count up the low four chip bits (1101 -> 1110); Invert off.
    a.lda(0x20); a.sta(0x4103)
    a.sta(0x4100)
    a.lda(0x00); a.sta(0x4101)
    a.check(0x4100, 0x1C, "fail10")
    # Register $3F, counted up: the low four wrap, bits 4-5 stay.
    a.lda(0x00); a.sta(0x4103)
    a.lda(0x3F); a.sta(0x4102)
    a.sta(0x4100)
    a.lda(0x20); a.sta(0x4103)
    a.sta(0x4100)
    a.check(0x4100, 0x03, "fail11")
    # $4203 is not $4103: Mode stays 1, so $4100 counts up to chip $31.
    a.lda(0x00); a.sta(0x4203)
    a.sta(0x4100)
    a.check(0x4100, 0x23, "fail12")
    # The registers' mirrors: Mode 0 at $5503, Input 1 at $4302 (chip
    # $20), copied by $5100, read at $5F00.
    a.lda(0x00); a.sta(0x5503)
    a.lda(0x01); a.sta(0x4302)
    a.sta(0x5100)
    a.check(0x5F00, 0x01, "fail13")
    return finish(a, range(2, 14))


def main():
    code = program()
    prg = bytearray(0x8000)
    prg[:len(code)] = code
    vectors(prg, 0x8000, 0x8000, RTI)
    chr_rom = bytearray()
    for bank in range(CHR_BANKS):
        c = bytearray(0x2000)
        c[0] = 0xC0 + bank
        chr_rom += c
    write_nes("txc_switch.nes", 172, prg, chr_rom, vertical=True)


if __name__ == "__main__":
    main()
