#!/usr/bin/env python3
"""Write tests/gxrom_switch.nes: a GxROM (mapper 66) test made for
nesrecomp. Run it again to regenerate the ROM.

128 KB PRG (four 32 KB banks) and 32 KB CHR ROM (four 8 KB banks). Every
PRG bank holds the same program at $8000, so execution carries on after a
switch from inside the switched window; byte $FFF0 of each bank holds its
number, and byte 0 of each CHR bank holds $C0 + its number, so the program
can tell which banks are mapped. The register is xxPP xxCC: PRG in bits
4-5, CHR in bits 0-1, with bus conflicts (the ROM byte at the written
address is ANDed with the value).

Results use the blargg $6000 protocol; status codes:

  0  passed
  2  writing $20 didn't switch PRG to bank 2
  3  writing $23 didn't switch CHR to bank 3
  4  bus conflict: $33 written over a ROM byte $21 changed the PRG bank
     (it should become $21: PRG 2, CHR 1)
  5  bus conflict: CHR isn't bank 1 after that write
  6  writing $10 didn't switch PRG to bank 1
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_mmc1_test import Asm  # noqa: E402

BANKS = 4                   # 32 KB PRG banks
CHR_BANKS = 4               # 8 KB CHR banks
ID = 0xFFF0                 # bank number, in every PRG bank
FF_BYTE = 0xFFE0            # $FF: writes here aren't changed by the conflict
B21_BYTE = 0xFFE1           # $21: a write of $33 here becomes $21
RTI = 0xFF00


def program():
    a = Asm(0x8000)
    a.b(0x78, 0xA2, 0xFF, 0x9A)                 # SEI; LDX #$FF; TXS
    a.lda(0x80); a.sta(0x6000)                  # status: running
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)
    a.lda(0x00); a.sta(0x6004)                  # no text

    def read_chr0():
        """A = byte 0 of the CHR bank at PPU $0000 (via $2006/$2007)."""
        a.lda(0x00); a.sta(0x2006); a.sta(0x2006)
        a.lda_abs(0x2007)                       # fills the read buffer
        a.lda_abs(0x2007)

    a.lda(0x20); a.sta(FF_BYTE)                 # PRG 2, CHR 0
    a.check(ID, 2, "fail2")
    a.lda(0x23); a.sta(FF_BYTE)                 # PRG 2, CHR 3
    read_chr0(); a.cmp(0xC3); a.bne("fail3")
    a.lda(0x33); a.sta(B21_BYTE)                # becomes $21: PRG 2, CHR 1
    a.check(ID, 2, "fail4")
    read_chr0(); a.cmp(0xC1); a.bne("fail5")
    a.lda(0x10); a.sta(FF_BYTE)                 # PRG 1, CHR 0
    a.check(ID, 1, "fail6")

    for status, name in ((0, "pass"), (2, "fail2"), (3, "fail3"),
                         (4, "fail4"), (5, "fail5"), (6, "fail6")):
        a.label(name)
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)       # JMP to itself
    # "pass" must follow the last check directly.
    return a


def main():
    a = program()
    code = a.done()
    # The first label after the checks is "pass": make sure it's reached
    # by falling through, not by a jump.
    assert a.labels["pass"] == 0x8000 + code.index(bytes([0xA9, 0x00, 0x8D, 0x00, 0x60]))
    prg = bytearray()
    for bank in range(BANKS):
        b = bytearray(0x8000)
        b[:len(code)] = code
        b[ID - 0x8000] = bank
        b[FF_BYTE - 0x8000] = 0xFF
        b[B21_BYTE - 0x8000] = 0x21
        b[RTI - 0x8000] = 0x40
        for vec, target in ((0xFFFA, RTI), (0xFFFC, 0x8000), (0xFFFE, RTI)):
            b[vec - 0x8000] = target & 0xFF
            b[vec - 0x8000 + 1] = target >> 8
        prg += b
    chr_rom = bytearray()
    for bank in range(CHR_BANKS):
        c = bytearray(0x2000)
        c[0] = 0xC0 + bank
        chr_rom += c
    header = bytes([0x4E, 0x45, 0x53, 0x1A, len(prg) // 0x4000,
                    len(chr_rom) // 0x2000, 0x20, 0x40]) + bytes(8)  # mapper 66
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "gxrom_switch.nes")
    with open(out, "wb") as f:
        f.write(header + prg + chr_rom)
    print("wrote", out)


if __name__ == "__main__":
    main()
