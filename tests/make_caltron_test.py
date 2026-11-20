#!/usr/bin/env python3
"""Write tests/caltron_switch.nes: a Caltron 6-in-1 (mapper 41) test made
for nesrecomp (PLAN-mappers3.md step 1). Run it again to regenerate the
ROM.

256 KB PRG (eight 32 KB banks) and 128 KB CHR ROM (sixteen 8 KB banks).
Every PRG bank holds the same program at $8000, so it carries on after a
switch; byte $FFF0 of each bank holds its number, and byte 0 of each CHR
bank holds $C0 + its number. From the nesdev wiki ("INES Mapper 041"):

  $6000-$67FF  the address is the value: ..MC CEPP, the 32 KB PRG bank
               in bits 0-2 (EPP), bit 2 (E) also lets the inner register
               be written, CC bits 2-3 of the CHR bank, M mirroring
               (0 vertical, 1 horizontal);
  $8000-$FFFF  the inner register, written only while E is set: bits 0-1
               of the CHR bank, with bus conflicts.

The real board has no RAM at $6000; this ROM's header gives it 8 KB so
the status protocol works. Its writes to $6000-$6004 (the status and the
signature) also reach the outer register, harmlessly: every bank holds
the same program, and each check sets the register first. The checks
write the register at $6700-$673F (only A0-A5 count), which keeps them
off the status bytes and shows the register answers through the range.

Results use the blargg $6000 protocol; status codes:

  0  passed
  2  a write to $6703 didn't switch PRG to bank 3
  3  with E set ($6706: PRG 6), writing 2 to the inner register didn't
     give CHR bank 2
  4  a write to $671E (PRG 6, CC 3) didn't give CHR 3*4+2 = 14
  5  with E clear ($6718), the inner register took a write (CHR moved
     from 12+2)
  6  bus conflict: 3 written over a ROM byte 1 should give inner 1 (CHR 1,
     with $6704)
  7  a write to $6720 (M set) didn't give horizontal mirroring
  8  a write to $6700 (M clear) didn't give vertical mirroring
  9  a write to $6805 (above $67FF) switched something
"""
from mappers3_common import start, ppu_write, ppu_check, finish, vectors, write_nes

BANKS = 8
CHR_BANKS = 16
ID = 0xFFF0
FF_BYTE = 0xFFE0            # $FF: a write here isn't changed by the conflict
B01_BYTE = 0xFFE1           # $01: a write of 3 here becomes 1
RTI = 0xFF00


def program():
    a = start(0x8000)
    a.sta(0x6703)
    a.check(ID, 3, "fail2")
    a.sta(0x6706)                               # PRG 6, E set, CC 0
    a.lda(2); a.sta(FF_BYTE)
    ppu_check(a, 0x0000, 0xC2, "fail3")
    a.sta(0x671E)                               # PRG 6, CC 3
    a.check(ID, 6, "fail4")
    ppu_check(a, 0x0000, 0xCE, "fail4")
    a.sta(0x6718)                               # PRG 0, CC 3, E clear
    a.lda(1); a.sta(FF_BYTE)                    # ignored
    ppu_check(a, 0x0000, 0xCE, "fail5")
    a.sta(0x6704)                               # PRG 4, E set, CC 0
    a.lda(3); a.sta(B01_BYTE)                   # becomes 1
    ppu_check(a, 0x0000, 0xC1, "fail6")
    a.sta(0x6720)                               # horizontal, PRG 0
    ppu_write(a, 0x2000, 0x55)
    ppu_write(a, 0x2800, 0x66)
    ppu_check(a, 0x2400, 0x55, "fail7")
    a.sta(0x6700)                               # vertical, PRG 0
    ppu_check(a, 0x2400, 0x66, "fail8")
    a.sta(0x6805)                               # not a register
    a.check(ID, 0, "fail9")
    ppu_check(a, 0x2400, 0x66, "fail9")
    return finish(a, (2, 3, 4, 5, 6, 7, 8, 9))


def main():
    code = program()
    prg = bytearray()
    for bank in range(BANKS):
        b = bytearray(0x8000)
        b[:len(code)] = code
        b[ID - 0x8000] = bank
        b[FF_BYTE - 0x8000] = 0xFF
        b[B01_BYTE - 0x8000] = 0x01
        vectors(b, 0x8000, 0x8000, RTI)
        prg += b
    chr_rom = bytearray()
    for bank in range(CHR_BANKS):
        c = bytearray(0x2000)
        c[0] = 0xC0 + bank
        chr_rom += c
    write_nes("caltron_switch.nes", 41, prg, chr_rom)


if __name__ == "__main__":
    main()
