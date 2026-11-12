#!/usr/bin/env python3
"""Write tests/mmc1_switch.nes: an MMC1 (mapper 1) test made for nesrecomp.
Run it again to regenerate the ROM.

The blargg multi-test ROMs are MMC1 boards but pass even with program
bank switching turned off, so this ROM checks the switching itself.
128 KB PRG (eight 16 KB banks, byte $3FF0 of each holds its number),
CHR RAM. Results use the blargg $6000 protocol; status codes:

  0  passed
  2  5-write serial load of the PRG register picked the wrong bank
  3  a write with bit 7 set didn't throw away a half-finished load
  4  INC on a ROM byte holding $FF: the second (back-to-back) write
     wasn't ignored
  5  code at $8000 switched its own bank but kept running the old one
  6  PRG mode 2 (first bank fixed at $8000, switch $C000) wrong
  7  PRG mode 0 (32 KB switching) wrong
  8  one-screen or vertical mirroring wrong
"""
import os

BANKS = 8                       # 16 KB each
ID = 0x3FF0                     # offset of the bank number in each bank
FF_BYTE = 0xFFE0                # a $FF byte in the last bank, for INC


class Asm:
    """Just enough of a 6502 assembler: bytes, labels, branch fixups."""
    def __init__(self, org):
        self.org, self.code, self.labels, self.fix = org, bytearray(), {}, []

    def pc(self):
        return self.org + len(self.code)

    def label(self, name):
        self.labels[name] = self.pc()

    def b(self, *bytes_):
        self.code.extend(bytes_)

    def lda(self, v): self.b(0xA9, v)
    def sta(self, a): self.b(0x8D, a & 0xFF, a >> 8)
    def lda_abs(self, a): self.b(0xAD, a & 0xFF, a >> 8)
    def cmp(self, v): self.b(0xC9, v)
    def lsr(self): self.b(0x4A)
    def rts(self): self.b(0x60)

    def jsr(self, a): self.b(0x20, a & 0xFF, a >> 8)

    def jsr_label(self, name):
        self.b(0x20, 0, 0)
        self.fix.append((len(self.code) - 2, name))

    def bne(self, name):
        """Branch if not equal, any distance: BEQ over a JMP."""
        self.b(0xF0, 3, 0x4C, 0, 0)
        self.fix.append((len(self.code) - 2, name))

    def write5(self, addr, value):
        """Load an MMC1 register: 5 writes of bit 0, shifting right."""
        self.lda(value)
        for i in range(5):
            self.sta(addr)
            if i < 4:
                self.lsr()

    def check(self, addr, want, fail):
        self.lda_abs(addr)
        self.cmp(want)
        self.bne(fail)

    def done(self):
        for pos, name in self.fix:
            target = self.labels[name]
            self.code[pos], self.code[pos + 1] = target & 0xFF, target >> 8
        return bytes(self.code)


def ram_routine():
    """Mode tests, copied to $0300 and run from RAM, since they move the
    bank the main code lives in. Results go to $10-$13."""
    a = Asm(0x0300)
    a.write5(0x8000, 0x08)       # mode 2, one-screen low
    a.write5(0xE000, 2)          # $C000 = bank 2
    a.lda_abs(0x8000 + ID); a.b(0x85, 0x10)     # expect 0 (fixed first)
    a.lda_abs(0xC000 + ID); a.b(0x85, 0x11)     # expect 2
    a.write5(0x8000, 0x00)       # mode 0: 32 KB, one-screen low
    a.write5(0xE000, 4)          # banks 4 and 5
    a.lda_abs(0x8000 + ID); a.b(0x85, 0x12)     # expect 4
    a.lda_abs(0xC000 + ID); a.b(0x85, 0x13)     # expect 5
    a.write5(0x8000, 0x0C)       # back to mode 3 (last bank at $C000)
    a.rts()
    return a.done()


def main_code(ram):
    a = Asm(0xC000)
    a.b(0x78, 0xD8, 0xA2, 0xFF, 0x9A)            # SEI CLD LDX #$FF TXS
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61, 0x00)):
        a.lda(v); a.sta(0x6001 + i)

    a.write5(0xE000, 2)                          # 2: serial load
    a.check(0x8000 + ID, 2, "f2")

    a.lda(1); a.sta(0xE000); a.sta(0xE000)       # 3: half a load, then reset
    a.lda(0x80); a.sta(0x8000)
    a.write5(0xE000, 3)
    a.check(0x8000 + ID, 3, "f3")

    a.lda(1); a.sta(0xE000)                      # 4: INC $FF byte = reset
    a.b(0xEE, FF_BYTE & 0xFF, FF_BYTE >> 8)      #    (+ ignored 2nd write)
    a.write5(0xE000, 4)
    a.check(0x8000 + ID, 4, "f4")

    a.jsr(0x8000)                                # 5: bank 4 switches itself
    a.cmp(0xAA)                                  #    to 5 and must go on there
    a.bne("f5")

    a.b(0xA2, 0x00)                              # copy RAM routine to $0300
    a.label("copy")
    src = len(a.code)
    a.b(0xBD, 0, 0)                              # LDA src,X (patched)
    a.b(0x9D, 0x00, 0x03)                        # STA $0300,X
    a.b(0xE8, 0xE0, len(ram))                    # INX; CPX #len
    a.b(0xD0, (a.labels["copy"] - (a.pc() + 2)) & 0xFF)
    a.jsr(0x0300)
    for zp, want in ((0x10, 0), (0x11, 2)):
        a.check(zp, want, "f6")
    for zp, want in ((0x12, 4), (0x13, 5)):
        a.check(zp, want, "f7")

    # 8: mirroring. Now mode 3 with one-screen low: $2000 shows at $2C00.
    def vram_write(addr, v):
        a.lda(addr >> 8); a.sta(0x2006); a.lda(addr & 0xFF); a.sta(0x2006)
        a.lda(v); a.sta(0x2007)
    def vram_check(addr, want):
        a.lda(addr >> 8); a.sta(0x2006); a.lda(addr & 0xFF); a.sta(0x2006)
        a.lda_abs(0x2007); a.lda_abs(0x2007); a.cmp(want); a.bne("f8")
    vram_write(0x2000, 0x5A)
    vram_check(0x2C00, 0x5A)
    a.write5(0x8000, 0x0E)                       # mode 3, vertical
    vram_check(0x2800, 0x5A)

    def finish(status):
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)
    finish(0x00)
    for n in range(2, 9):
        a.label("f%d" % n)
        finish(n)

    data = a.pc()                                # RAM routine bytes follow
    a.code[src + 1] = data & 0xFF
    a.code[src + 2] = data >> 8
    a.b(*ram)
    return a.done()


def self_switch(bank):
    """At $8000 in every switchable bank: switch $8000 to bank 5. The
    instruction after the 5th write comes from bank 5."""
    a = Asm(0x8000)
    a.write5(0xE000, 5)
    a.lda(0xAA if bank == 5 else 0x55)
    a.rts()
    return a.done()


def build():
    prg = bytearray()
    for bank in range(BANKS):
        b = bytearray(0x4000)
        if bank == BANKS - 1:
            code = main_code(ram_routine())
            b[:len(code)] = code
            b[FF_BYTE - 0xC000] = 0xFF
            b[0x3F00] = 0x40                     # RTI for NMI and IRQ
            for vec, target in ((0x3FFA, 0xFF00), (0x3FFC, 0xC000),
                                (0x3FFE, 0xFF00)):
                b[vec], b[vec + 1] = target & 0xFF, target >> 8
        else:
            code = self_switch(bank)
            b[:len(code)] = code
        b[ID] = bank
        prg += b
    header = bytes([0x4E, 0x45, 0x53, 0x1A, BANKS, 0, 0x10, 0x00]) + bytes(8)
    return header + prg


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "mmc1_switch.nes")
    with open(out, "wb") as f:
        f.write(build())
    print("wrote", out)


if __name__ == "__main__":
    main()
