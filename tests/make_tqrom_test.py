#!/usr/bin/env python3
"""Write tests/tqrom_switch.nes: a TQROM (mapper 119) test made for
nesrecomp (PLAN-mappers3.md step 3). Run it again to regenerate the ROM.

128 KB PRG (sixteen 8 KB banks, the byte at offset $1E00 of each holding
its number), 64 KB CHR ROM (64 1 KB banks, byte 0 of each holding $80 +
its number), and the board's 8 KB of CHR RAM. The program runs from the
fixed last 8 KB, at $E000.

From the nesdev wiki ("INES Mapper 119"): an MMC3 whose CHR bank numbers
use bit 6 to pick the chip, 0 CHR ROM, 1 CHR RAM; everything else is the
MMC3's. The RAM is 8 KB, so in a RAM bank number only bits 0-2 count.

Status codes:
  0  passed
  2  at power-on (MMC3 R0 = 0, R2 = 4), CHR $0000 isn't ROM bank 0 or
     $1000 isn't ROM bank 4
  3  R2 = $41 (RAM bank 1 at $1000): $A5 written there doesn't read back
  4  R2 = 5 doesn't show ROM bank 5, or R2 = $41 again lost the $A5
  5  R3 = $45 (RAM bank 5) at $1400: $5A written there also changed RAM
     bank 1 at $1000 (less than 8 KB of RAM), or R3 = $4D (bank 13,
     which is bank 5 of 8 KB) doesn't show the $5A
  6  a write to $1000 with ROM bank 5 there changed it
  7  R0 = $42 (a 2 KB bank: RAM 2 at $0000, RAM 3 at $0400): $3C
     written at $0400 isn't seen through R4 = $43 at $1800
  8  with the CHR swap bit ($8000 bit 7), R2 = $41 at $0000 doesn't show
     the RAM's $A5
  9  R5 = $3F (bit 6 clear: ROM) at $1C00 isn't ROM bank 63
 10  the MMC3's PRG banks: R6 = 3 isn't at $8000, or the PRG mode bit
     doesn't swap it to $C000
 11  the MMC3's scanline IRQ (latch 16, rendering on) never came
"""
from mappers3_common import start, ppu_write, ppu_check, finish, write_nes

PRG_BANKS = 16
CHR_BANKS = 64
ID = 0x1E00                 # offset of the bank's number in each 8 KB
RTI = 0xFF00
IRQ = 0xFF10
FLAG = 0x10                 # zero page: set by the IRQ handler


def reg(a, select, value):
    a.lda(select); a.sta(0x8000)
    a.lda(value); a.sta(0x8001)


def program():
    a = start(0xE000)
    a.lda(0x40); a.sta(0x4017)      # no APU frame IRQ: only the MMC3's
    a.lda_abs(0x4015)
    ppu_check(a, 0x0000, 0x80, "fail2")
    ppu_check(a, 0x1000, 0x84, "fail2")
    reg(a, 2, 0x41)
    ppu_write(a, 0x1000, 0xA5)
    ppu_check(a, 0x1000, 0xA5, "fail3")
    reg(a, 2, 5)
    ppu_check(a, 0x1000, 0x85, "fail4")
    reg(a, 2, 0x41)
    ppu_check(a, 0x1000, 0xA5, "fail4")
    reg(a, 3, 0x45)
    ppu_write(a, 0x1400, 0x5A)
    ppu_check(a, 0x1000, 0xA5, "fail5")
    reg(a, 3, 0x4D)
    ppu_check(a, 0x1400, 0x5A, "fail5")
    reg(a, 2, 5)
    ppu_write(a, 0x1000, 0x77)
    ppu_check(a, 0x1000, 0x85, "fail6")
    reg(a, 0, 0x42)
    ppu_write(a, 0x0400, 0x3C)
    reg(a, 4, 0x43)
    ppu_check(a, 0x1800, 0x3C, "fail7")
    reg(a, 0x82, 0x41)
    ppu_check(a, 0x0000, 0xA5, "fail8")
    reg(a, 0x05, 0x3F)              # swap bit off again; R5 is at $1C00
    ppu_check(a, 0x1C00, 0x80 + 63, "fail9")
    reg(a, 6, 3)
    a.check(0x8000 + ID, 3, "fail10")
    a.lda(0x46); a.sta(0x8000)
    a.check(0xC000 + ID, 3, "fail10")
    a.check(0x8000 + ID, 14, "fail10")
    a.lda(0x06); a.sta(0x8000)
    # The IRQ: background at $0000, sprites at $1000, so A12 rises once
    # a line; latch 16, reload, enable, and wait (about 20 frames).
    a.lda(0); a.b(0x85, FLAG)
    a.lda(0x08); a.sta(0x2000)
    a.lda(16); a.sta(0xC000)
    a.sta(0xC001)
    a.sta(0xE001)
    a.lda(0x18); a.sta(0x2001)
    a.b(0x58)                       # CLI
    a.b(0xA2, 0, 0xA0, 0)           # LDX #0; LDY #0
    a.b(0xA5, FLAG, 0xD0, 9,        # loop: LDA flag; BNE got
        0xCA, 0xD0, 0xF9,           # DEX; BNE loop
        0x88, 0xD0, 0xF6)           # DEY; BNE loop
    a.b(0x4C, 0, 0)
    a.fix.append((len(a.code) - 2, "fail11"))
    a.b(0x78)                       # got: SEI
    a.lda(0); a.sta(0x2001)
    return finish(a, range(2, 12))


def main():
    code = program()
    prg = bytearray(PRG_BANKS * 0x2000)
    for bank in range(PRG_BANKS):
        prg[bank * 0x2000 + ID] = bank
    base = (PRG_BANKS - 1) * 0x2000             # the last 8 KB, at $E000
    assert len(code) < ID
    prg[base:base + len(code)] = code
    # NMI to an RTI; the IRQ handler sets the flag and turns the IRQ off.
    prg[base + RTI - 0xE000] = 0x40
    prg[base + IRQ - 0xE000:base + IRQ - 0xE000 + 8] = bytes(
        [0x48, 0xA9, 0x01, 0x85, FLAG, 0x8D, 0x00, 0xE0])  # PHA LDA STA STA $E000
    prg[base + IRQ - 0xE000 + 8:base + IRQ - 0xE000 + 10] = bytes([0x68, 0x40])
    for vec, target in ((0xFFFA, RTI), (0xFFFC, 0xE000), (0xFFFE, IRQ)):
        prg[base + vec - 0xE000] = target & 0xFF
        prg[base + vec - 0xE000 + 1] = target >> 8
    chr_rom = bytearray(CHR_BANKS * 0x400)
    for bank in range(CHR_BANKS):
        chr_rom[bank * 0x400] = 0x80 + bank
    write_nes("tqrom_switch.nes", 119, prg, chr_rom, vertical=True)


if __name__ == "__main__":
    main()
