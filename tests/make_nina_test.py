#!/usr/bin/env python3
"""Write tests/nina_switch.nes: an AVE NINA-03/06 (mapper 79) test made
for nesrecomp (PLAN-mappers3.md step 1). Run it again to regenerate the
ROM.

64 KB PRG (two 32 KB banks) and 64 KB CHR ROM (eight 8 KB banks). Every
PRG bank holds the same program at $8000, so it carries on after a
switch; byte $FFF0 of each bank holds its number, and byte 0 of each CHR
bank holds $C0 + its number. From the nesdev wiki ("INES Mapper 079"):
one register, at the addresses in $4100-$5FFF where A8 is set (address
AND $E100 = $4100): bit 3 the 32 KB PRG bank, bits 0-2 the 8 KB CHR
bank. Nothing at $8000-$FFFF.

Results use the blargg $6000 protocol; status codes:

  0  passed
  2  writing $08 to $4100 didn't switch PRG to bank 1
  3  writing $0D to $4100 didn't switch CHR to bank 5 (PRG staying 1)
  4  writing $00 to $5100 (A8 set) didn't switch back to PRG 0, CHR 0
  5  writing $0F to $4200 (A8 clear) switched something
  6  writing $0F to $8000 (no register there) switched something
  7  writing $0A to $5F00 didn't give PRG 1, CHR 2
"""
from mappers3_common import start, ppu_check, finish, vectors, write_nes

BANKS = 2
CHR_BANKS = 8
ID = 0xFFF0
RTI = 0xFF00


def program():
    a = start(0x8000)
    a.lda(0x08); a.sta(0x4100)
    a.check(ID, 1, "fail2")
    a.lda(0x0D); a.sta(0x4100)
    ppu_check(a, 0x0000, 0xC5, "fail3")
    a.check(ID, 1, "fail3")
    a.lda(0x00); a.sta(0x5100)
    a.check(ID, 0, "fail4")
    ppu_check(a, 0x0000, 0xC0, "fail4")
    a.lda(0x0F); a.sta(0x4200)
    a.check(ID, 0, "fail5")
    ppu_check(a, 0x0000, 0xC0, "fail5")
    a.lda(0x0F); a.sta(0x8000)
    a.check(ID, 0, "fail6")
    ppu_check(a, 0x0000, 0xC0, "fail6")
    a.lda(0x0A); a.sta(0x5F00)
    a.check(ID, 1, "fail7")
    ppu_check(a, 0x0000, 0xC2, "fail7")
    return finish(a, (2, 3, 4, 5, 6, 7))


def main():
    code = program()
    prg = bytearray()
    for bank in range(BANKS):
        b = bytearray(0x8000)
        b[:len(code)] = code
        b[ID - 0x8000] = bank
        vectors(b, 0x8000, 0x8000, RTI)
        prg += b
    chr_rom = bytearray()
    for bank in range(CHR_BANKS):
        c = bytearray(0x2000)
        c[0] = 0xC0 + bank
        chr_rom += c
    write_nes("nina_switch.nes", 79, prg, chr_rom)


if __name__ == "__main__":
    main()
