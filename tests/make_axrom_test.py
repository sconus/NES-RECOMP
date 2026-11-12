#!/usr/bin/env python3
"""Write tests/axrom_switch.nes: a tiny AxROM (mapper 7) test made for
nesrecomp. Run it again to regenerate the ROM.

Both 32 KB banks start with the same code at $8000. It switches to bank 1
(with single-screen mirroring, upper screen) from inside the window being
switched, so the very next instruction must come from bank 1. There the
code differs:

  bank 0 continues with: status $02 ("kept running the old bank")
  bank 1 continues with: a nametable check, then status $00 (pass), or
                         $03 if single-screen mirroring didn't work

Results use the blargg $6000 protocol (status at $6000, DE B0 61 at $6001).
"""
import os

def assemble(bank):
    code = bytearray()
    def emit(*b): code.extend(b)
    def sta(addr): emit(0x8D, addr & 0xFF, addr >> 8)
    def lda(v): emit(0xA9, v)

    emit(0x78, 0xA2, 0xFF, 0x9A)             # SEI; LDX #$FF; TXS
    lda(0x80); sta(0x6000)                   # status: running
    lda(0xDE); sta(0x6001)
    lda(0xB0); sta(0x6002)
    lda(0x61); sta(0x6003)
    lda(0x00); sta(0x6004)                   # empty text
    lda(0x11); sta(0x8000)                   # bank 1, one-screen (upper)

    def finish(status):
        lda(status); sta(0x6000)
        here = 0x8000 + len(code)
        emit(0x4C, here & 0xFF, here >> 8)   # JMP to itself

    if bank == 0:
        finish(0x02)
        return code
    # Write $AA at $2000, read back through $2C00. With one-screen
    # mirroring all four nametables are the same 1 KB.
    lda(0x20); sta(0x2006); lda(0x00); sta(0x2006)
    lda(0xAA); sta(0x2007)
    lda(0x2C); sta(0x2006); lda(0x00); sta(0x2006)
    emit(0xAD, 0x07, 0x20)                   # LDA $2007 (fills the buffer)
    emit(0xAD, 0x07, 0x20)                   # LDA $2007
    emit(0xC9, 0xAA)                         # CMP #$AA
    emit(0xD0, 0x00)                         # BNE fail (patched below)
    bne = len(code) - 1
    finish(0x00)
    code[bne] = len(code) - (bne + 1)
    finish(0x03)
    return code


def main():
    prg = bytearray()
    for bank in range(2):
        b = bytearray(0x8000)
        code = assemble(bank)
        b[:len(code)] = code
        rti = 0x7F00
        b[rti] = 0x40                         # RTI for NMI and IRQ
        for vec, target in ((0x7FFA, 0xFF00), (0x7FFC, 0x8000), (0x7FFE, 0xFF00)):
            b[vec] = target & 0xFF
            b[vec + 1] = target >> 8
        prg += b
    header = bytes([0x4E, 0x45, 0x53, 0x1A, len(prg) // 0x4000, 0,
                    0x70, 0x00]) + bytes(8)   # mapper 7, CHR RAM
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "axrom_switch.nes")
    with open(out, "wb") as f:
        f.write(header + prg)
    print("wrote", out)


if __name__ == "__main__":
    main()
