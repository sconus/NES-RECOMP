#!/usr/bin/env python3
"""Write the RAM size tests made for nesrecomp: one ROM per case, each
with an NES 2.0 header that declares its PRG RAM and CHR RAM (bytes 10
and 11, nesdev wiki "NES 2.0"). Run it again to regenerate them.

  ram_none.nes     NROM, no PRG RAM: $6000-$7FFF is open bus, which
                   for an absolute read is the address's high byte
  ram_2k.nes       NROM, 2 KB PRG RAM and 2 KB CHR RAM, each repeating
                   through its 8 KB
  chr_none.nes     NROM, 8 KB PRG RAM, neither CHR ROM nor CHR RAM:
                   pattern data reads 0 and can't be written
  mmc1_ram32.nes   MMC1, 32 KB of PRG NVRAM (SXROM): CHR bank 0 bits
                   2-3 pick the 8 KB at $6000
  mmc1_ram16.nes   MMC1, 8 KB PRG RAM + 8 KB PRG NVRAM (SOROM): only
                   bit 3 picks
  mmc1_chr16.nes   MMC1, 16 KB of CHR RAM in 4 KB banks

The program can't count on RAM to report a RAM test, so it writes its
result into the nametable, where --dump-text finds it: "PASSED", or
"FAILED n" for the first check that went wrong (numbered in each case
below). With --ines1 the same programs get iNES 1.0 headers (8 KB of
each RAM), written to the directory given, and each must fail.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402


def shift(size):
    """The NES 2.0 nibble for a RAM size: 64 << n bytes, 0 for none."""
    if not size:
        return 0
    n = (size // 64).bit_length() - 1
    assert 64 << n == size
    return n


class Test(Asm):
    def store(self, addr, v):
        self.lda(v); self.sta(addr)

    def check(self, addr, want, n):
        self.lda_abs(addr); self.cmp(want); self.bne("f%d" % n)

    def ppu_addr(self, addr):
        self.lda_abs(0x2002)
        self.lda(addr >> 8); self.sta(0x2006)
        self.lda(addr & 0xFF); self.sta(0x2006)

    def ppu_store(self, addr, v):
        self.ppu_addr(addr); self.store(0x2007, v)

    def ppu_check(self, addr, want, n):
        self.ppu_addr(addr)
        self.lda_abs(0x2007)                    # the buffered read
        self.check(0x2007, want, n)

    def text(self, s):
        self.ppu_addr(0x2042)
        for ch in s:
            self.store(0x2007, ord(ch))

    def stop(self):
        here = self.pc()
        self.b(0x4C, here & 0xFF, here >> 8)


def mmc1_init(a, control):
    a.store(0x8000, 0x80)                       # reset the shift register
    a.write5(0x8000, control)
    a.write5(0xE000, 0x00)                      # PRG bank 0, RAM enabled


def ram_none(a):
    a.store(0x6000, 0xA5)
    a.check(0x6000, 0x60, 1)
    a.store(0x7FFF, 0x5A)
    a.check(0x7FFF, 0x7F, 2)
    return 2


def ram_2k(a):
    a.store(0x6000, 0x11)
    a.store(0x67FF, 0x22)
    a.check(0x6800, 0x11, 1)
    a.check(0x7000, 0x11, 1)
    a.check(0x7FFF, 0x22, 1)
    a.store(0x7800, 0x33)
    a.check(0x6000, 0x33, 2)
    a.ppu_store(0x0000, 0x44)
    a.ppu_store(0x07FF, 0x55)
    a.ppu_check(0x0800, 0x44, 3)
    a.ppu_check(0x1FFF, 0x55, 3)
    a.ppu_store(0x1000, 0x66)
    a.ppu_check(0x0000, 0x66, 4)
    return 4


def chr_none(a):
    a.ppu_store(0x0000, 0x77)
    a.ppu_check(0x0000, 0x00, 1)
    a.store(0x6000, 0x12)
    a.store(0x7000, 0x34)
    a.check(0x6000, 0x12, 2)
    a.check(0x7000, 0x34, 2)
    return 2


def mmc1_ram32(a):
    mmc1_init(a, 0x0C)                          # 8 KB CHR, PRG mode 3
    for b in range(4):
        a.write5(0xA000, b << 2)
        a.store(0x6000, 0x50 | b)
        a.store(0x7FFF, 0xA0 | b)
    for b in range(4):
        a.write5(0xA000, b << 2)
        a.check(0x6000, 0x50 | b, 1 + b)
        a.check(0x7FFF, 0xA0 | b, 5 + b)
    return 8


def mmc1_ram16(a):
    mmc1_init(a, 0x0C)
    a.write5(0xA000, 0x00)
    a.store(0x6000, 0xC0)
    a.write5(0xA000, 0x08)
    a.store(0x6000, 0xC1)
    a.write5(0xA000, 0x04)                      # bit 2: not wired
    a.check(0x6000, 0xC0, 1)
    a.write5(0xA000, 0x0C)
    a.check(0x6000, 0xC1, 2)
    a.write5(0xA000, 0x00)
    a.check(0x6000, 0xC0, 3)
    a.write5(0xA000, 0x08)                      # leave the saved bank in
    return 3


def mmc1_chr16(a):
    mmc1_init(a, 0x1C)                          # 4 KB CHR, PRG mode 3
    for b in range(4):
        a.write5(0xA000, b)
        a.ppu_store(0x0000, 0x60 + b)
        a.ppu_store(0x0FFF, 0x70 + b)
    for b in range(4):
        a.write5(0xA000, b)
        a.ppu_check(0x0000, 0x60 + b, 1 + b)
        a.ppu_check(0x0FFF, 0x70 + b, 5 + b)
    a.write5(0xC000, 3)
    a.ppu_check(0x1000, 0x63, 9)
    return 9


# name: (mapper, CHR ROM in 8 KB, PRG RAM, PRG NVRAM, CHR RAM, test)
CASES = {
    "ram_none": (0, 1, 0, 0, 0, ram_none),
    "ram_2k": (0, 0, 0x800, 0, 0x800, ram_2k),
    "chr_none": (0, 0, 0x2000, 0, 0, chr_none),
    "mmc1_ram32": (1, 0, 0, 0x8000, 0x2000, mmc1_ram32),
    "mmc1_ram16": (1, 0, 0x2000, 0x2000, 0x2000, mmc1_ram16),
    "mmc1_chr16": (1, 0, 0x2000, 0, 0x4000, mmc1_chr16),
}


def rom(mapper, chr_banks, prg_ram, prg_nvram, chr_ram, test, nes2=True):
    a = Test(0xC000)
    a.b(0x78, 0xD8, 0xA2, 0xFF, 0x9A)           # SEI; CLD; LDX #$FF; TXS
    a.store(0x2000, 0); a.store(0x2001, 0)
    for _ in range(2):
        a.b(0x2C, 0x02, 0x20, 0x10, 0xFB)       # BIT $2002; BPL
    checks = test(a)
    a.text("PASSED")
    a.stop()
    for n in range(1, checks + 1):
        a.label("f%d" % n)
        a.text("FAILED %d" % n)
        a.stop()
    a.label("rti")
    a.b(0x40)
    code = a.done()
    prg = bytearray(0x8000)
    prg[0x4000:0x4000 + len(code)] = code
    for vec, label in ((0x7FFA, "rti"), (0x7FFE, "rti")):
        prg[vec], prg[vec + 1] = a.labels[label] & 0xFF, a.labels[label] >> 8
    prg[0x7FFC], prg[0x7FFD] = 0x00, 0xC0
    battery = 2 if prg_nvram else 0
    h = bytearray(b"NES\x1a" + bytes(12))
    h[4], h[5] = 2, chr_banks
    h[6] = (mapper & 0x0F) << 4 | battery | 1   # vertical mirroring
    h[7] = mapper & 0xF0
    if nes2:
        h[7] |= 0x08
        h[10] = shift(prg_nvram) << 4 | shift(prg_ram)
        h[11] = shift(chr_ram)
    return bytes(h) + prg + bytes(chr_banks * 0x2000)


def main():
    nes2 = "--ines1" not in sys.argv
    out = HERE
    if not nes2:
        out = sys.argv[sys.argv.index("--ines1") + 1]
    for name, case in CASES.items():
        path = os.path.join(out, name + ".nes")
        with open(path, "wb") as f:
            f.write(rom(*case, nes2=nes2))
        print("wrote", path)


if __name__ == "__main__":
    main()
