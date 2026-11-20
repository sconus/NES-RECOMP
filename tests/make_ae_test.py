#!/usr/bin/env python3
"""Write tests/ae_switch.nes: an Active Enterprises (mapper 228, Action 52
and Cheetahmen II) test made for nesrecomp (PLAN-mappers3.md step 2). Run
it again to regenerate the ROM.

1.5 MB PRG (96 16 KB banks: three 512 KB chips, laid out as Action 52's
are) and 512 KB CHR ROM (64 8 KB banks), vertical mirroring in the
header. Every 16 KB bank holds the same program at its start (it runs at
$8000, so it carries on after any switch) and the vectors; byte $3FF0 of
each bank holds its number in the file (seen at $BFF0 or $FFF0), and
byte 0 of each CHR bank holds its number.

From the nesdev wiki ("INES Mapper 228"): a write to $8000-$FFFF sets
everything from its address, ..MH HPPP PPS. CCCC, and its data, .... ..CC:
M mirroring (0 vertical, 1 horizontal), HH the 512 KB chip, PPPPP the
16 KB bank in it, S the mode (0: 32 KB, the even bank at $8000 and the odd
one at $C000; 1: the same 16 KB at both), and the 8 KB CHR bank
CCCC CC. Socket 2 is empty, so chip 3 is the file's third 512 KB. The
games expect $00 written at power-on and on reset.

Results use the blargg $6000 protocol; status codes:

  0  passed
  2  at power-on, $8000 doesn't hold bank 0 and $C000 bank 1
  3  32 KB mode, bank 6: $8000 isn't bank 6 or $C000 isn't bank 7
  4  32 KB mode, bank 7 written: bit 0 not ignored (should stay 6 and 7)
  5  16 KB mode, bank 9: both halves aren't bank 9
  6  chip 1, bank 3 (16 KB mode) isn't the file's bank 35
  7  chip 3, bank 2 (16 KB mode) isn't the file's bank 66 (the gap)
  8  CHR bank 46 (address bits 1011, data bits 10) isn't at PPU $0000
  9  mirroring bit clear: vertical isn't in use ($2800 should show $2000)
 10  mirroring bit set: horizontal isn't in use ($2400 should show $2000)
 11  a write at $C000-$FFFF (A14 set) isn't the same register: 16 KB
     bank 4 at both halves
 12  after the reset button, $8000 isn't bank 0 and $C000 bank 1
"""
from mappers3_common import start, ppu_write, ppu_check, finish, vectors, write_nes

CHIP_BANKS = 32             # 16 KB banks in a 512 KB chip
BANKS = 3 * CHIP_BANKS
CHR_BANKS = 64
ID_LO = 0xBFF0              # the number of the bank at $8000
ID_HI = 0xFFF0              # the number of the bank at $C000
RTI = 0xFF00
MARK = 0x0700               # console RAM: $5A once the reset was asked for


def reg(chip=0, bank=0, mode16=False, horizontal=False, chr_hi=0, a14=False):
    """The register's address: ..MH HPPP PPS. CCCC, from $8000."""
    return (0x8000 | (0x4000 if a14 else 0) | (0x2000 if horizontal else 0) |
            chip << 11 | bank << 6 | (0x20 if mode16 else 0) | chr_hi)


def jmp(a, name):
    a.b(0x4C, 0, 0)
    a.fix.append((len(a.code) - 2, name))


def program():
    a = start(0x8000)
    # Second time here, after the reset button: check the banks it left.
    a.lda_abs(MARK); a.cmp(0x5A)
    a.b(0xD0, 3)                                # BNE: first time, carry on
    jmp(a, "after_reset")

    a.check(ID_LO, 0, "fail2")
    a.check(ID_HI, 1, "fail2")
    a.lda(0); a.sta(reg(bank=6))
    a.check(ID_LO, 6, "fail3")
    a.check(ID_HI, 7, "fail3")
    a.lda(0); a.sta(reg(bank=7))
    a.check(ID_LO, 6, "fail4")
    a.check(ID_HI, 7, "fail4")
    a.lda(0); a.sta(reg(bank=9, mode16=True))
    a.check(ID_LO, 9, "fail5")
    a.check(ID_HI, 9, "fail5")
    a.lda(0); a.sta(reg(chip=1, bank=3, mode16=True))
    a.check(ID_LO, 35, "fail6")
    a.check(ID_HI, 35, "fail6")
    a.lda(0); a.sta(reg(chip=3, bank=2, mode16=True))
    a.check(ID_LO, 66, "fail7")
    a.check(ID_HI, 66, "fail7")
    # CHR 46 = 1011 10: the high bits from the address, the low from data
    # (the data's other bits set, to show they're ignored).
    a.lda(0xFE); a.sta(reg(chr_hi=0x0B))
    ppu_check(a, 0x0000, 46, "fail8")
    # Mirroring clear (the last write): vertical, $2000 = $2800.
    ppu_write(a, 0x2000, 0x11)
    ppu_write(a, 0x2400, 0x22)
    ppu_check(a, 0x2800, 0x11, "fail9")
    # Mirroring set: horizontal, $2000 = $2400.
    a.lda(0); a.sta(reg(horizontal=True))
    ppu_write(a, 0x2000, 0x33)
    ppu_check(a, 0x2400, 0x33, "fail10")
    a.lda(0); a.sta(reg(bank=4, mode16=True, a14=True))
    a.check(ID_LO, 4, "fail11")
    a.check(ID_HI, 4, "fail11")
    # Leave bank 9 in both halves, and ask for the reset button.
    a.lda(0); a.sta(reg(bank=9, mode16=True))
    a.lda(0x5A); a.sta(MARK)
    a.lda(0x81); a.sta(0x6000)
    here = a.pc()
    a.b(0x4C, here & 0xFF, here >> 8)           # wait for it

    a.label("after_reset")
    a.lda(0); a.sta(MARK)
    a.check(ID_LO, 0, "fail12")
    a.check(ID_HI, 1, "fail12")
    return finish(a, range(2, 13))


def main():
    code = program()
    prg = bytearray()
    for bank in range(BANKS):
        b = bytearray(0x4000)
        b[:len(code)] = code
        b[ID_HI - 0xC000] = bank
        vectors(b, 0xC000, 0x8000, RTI)
        prg += b
    chr_rom = bytearray()
    for bank in range(CHR_BANKS):
        c = bytearray(0x2000)
        c[0] = bank
        chr_rom += c
    write_nes("ae_switch.nes", 228, prg, chr_rom, vertical=True)


if __name__ == "__main__":
    main()
