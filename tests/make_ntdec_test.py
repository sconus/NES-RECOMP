#!/usr/bin/env python3
"""Write tests/ntdec_switch.nes: an NTDEC / Asder (mapper 112) test made
for nesrecomp (PLAN-mappers3.md step 3). Run it again to regenerate the
ROM.

128 KB PRG (sixteen 8 KB banks, the byte at offset $1E00 of each holding
its number), 128 KB CHR ROM (128 1 KB banks, byte 0 of each holding its
number), vertical mirroring in the header. The program runs from the
last 8 KB, at $E000.

From the nesdev wiki ("INES Mapper 112"): registers where address AND
$E001 is $8000 (bank select, bits 0-2), $A000 (bank data) and $E000
(bit 0: 0 horizontal arrangement = vertical mirroring, 1 vertical
arrangement = horizontal mirroring). Select 0/1: the 8 KB PRG banks at
$8000/$A000; 2/3: the 2 KB CHR banks at $0000/$0800; 4-7: the 1 KB CHR
banks at $1000-$1C00. No mode bits. What the wiki leaves open, taken
from the MMC3 it imitates: $C000-$FFFF is the last 16 KB, and a 2 KB
bank number counts 1 KB banks with its low bit ignored.

Status codes:
  0  passed
  2  at power-on, $8000 isn't PRG bank 0, $A000 bank 1, $C000 bank 14,
     or CHR $0000 bank 0
  3  select 0, data 5: $8000 isn't PRG bank 5
  4  select $F9 (1, with bits 3-7 set), data 9: $A000 isn't PRG bank 9
  5  select $C0 (bits 3-7 set, MMC3's mode bits) then data 7: $8000
     isn't bank 7, or $C000 moved from bank 14 (there are no mode bits)
  6  select 2, data 5: CHR $0000/$0400 aren't 1 KB banks 4/5
  7  select 3, data 9: CHR $0800/$0C00 aren't 8/9
  8  select $84 (4, with MMC3's CHR swap bit), data $20: CHR $1000
     isn't bank $20 or $0000 moved from bank 4; then selects 5-7, data
     $21-$23: CHR $1000-$1C00 aren't $20-$23
  9  the header's vertical mirroring isn't in use before $E000 is written
 10  $E000 = 1 didn't give horizontal mirroring
 11  $E000 = 0 didn't give vertical mirroring again
 12  a write to $8001 or $A001 (no register there) changed a bank, or
     the registers don't answer at $9FFE (select) and $BFFE (data)
 13  writes to $C000 and $C001 (MMC3's IRQ registers; none here) changed
     a bank or the mirroring
"""
from mappers3_common import start, ppu_write, ppu_check, finish, vectors, write_nes

PRG_BANKS = 16
CHR_BANKS = 128
ID = 0x1E00                 # offset of the bank's number in each 8 KB
RTI = 0xFF00


def reg(a, select, value, sel_addr=0x8000, data_addr=0xA000):
    a.lda(select); a.sta(sel_addr)
    a.lda(value); a.sta(data_addr)


def program():
    a = start(0xE000)
    a.check(0x8000 + ID, 0, "fail2")
    a.check(0xA000 + ID, 1, "fail2")
    a.check(0xC000 + ID, 14, "fail2")
    ppu_check(a, 0x0000, 0, "fail2")
    reg(a, 0, 5)
    a.check(0x8000 + ID, 5, "fail3")
    reg(a, 0xF9, 9)
    a.check(0xA000 + ID, 9, "fail4")
    reg(a, 0xC0, 7)
    a.check(0x8000 + ID, 7, "fail5")
    a.check(0xC000 + ID, 14, "fail5")
    a.check(0xA000 + ID, 9, "fail5")
    reg(a, 2, 5)
    ppu_check(a, 0x0000, 4, "fail6")
    ppu_check(a, 0x0400, 5, "fail6")
    reg(a, 3, 9)
    ppu_check(a, 0x0800, 8, "fail7")
    ppu_check(a, 0x0C00, 9, "fail7")
    reg(a, 0x84, 0x20)
    ppu_check(a, 0x1000, 0x20, "fail8")
    ppu_check(a, 0x0000, 4, "fail8")
    for sel in (5, 6, 7):
        reg(a, sel, 0x20 + sel - 4)
    for i in range(4):
        ppu_check(a, 0x1000 + i * 0x400, 0x20 + i, "fail8")
    ppu_check(a, 0x0000, 4, "fail8")
    # Mirroring: the header's vertical, then horizontal, then vertical.
    ppu_write(a, 0x2000, 0x11)
    ppu_write(a, 0x2400, 0x22)
    ppu_check(a, 0x2800, 0x11, "fail9")
    a.lda(1); a.sta(0xE000)
    ppu_write(a, 0x2000, 0x33)
    ppu_check(a, 0x2400, 0x33, "fail10")
    a.lda(0); a.sta(0xE000)
    ppu_write(a, 0x2000, 0x44)
    ppu_check(a, 0x2800, 0x44, "fail11")
    # Odd addresses are nothing; $9FFE and $BFFE are the registers.
    a.lda(1); a.sta(0x8000)
    a.lda(0); a.sta(0x8001)
    a.lda(3); a.sta(0xA001)
    a.check(0xA000 + ID, 9, "fail12")
    reg(a, 1, 6, 0x9FFE, 0xBFFE)
    a.check(0xA000 + ID, 6, "fail12")
    a.check(0x8000 + ID, 7, "fail12")
    # $C000/$C001: no IRQ registers, nothing changes.
    a.lda(2); a.sta(0xC000)
    a.lda(1); a.sta(0xC001)
    a.check(0x8000 + ID, 7, "fail13")
    a.check(0xA000 + ID, 6, "fail13")
    ppu_write(a, 0x2000, 0x55)
    ppu_check(a, 0x2800, 0x55, "fail13")
    return finish(a, range(2, 14))


def main():
    code = program()
    prg = bytearray(PRG_BANKS * 0x2000)
    for bank in range(PRG_BANKS):
        prg[bank * 0x2000 + ID] = bank
    base = (PRG_BANKS - 1) * 0x2000             # the last 8 KB, at $E000
    assert len(code) < ID
    prg[base:base + len(code)] = code
    last8 = prg[base:]
    vectors(last8, 0xE000, 0xE000, RTI)
    prg[base:] = last8
    chr_rom = bytearray(CHR_BANKS * 0x400)
    for bank in range(CHR_BANKS):
        chr_rom[bank * 0x400] = bank
    write_nes("ntdec_switch.nes", 112, prg, chr_rom, vertical=True)


if __name__ == "__main__":
    main()
