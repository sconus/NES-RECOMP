"""What the test ROMs of PLAN-mappers3.md share: the assembler (from
make_mmc1_test.py), the blargg $6000 status protocol, PPU reads and
writes through $2006/$2007, and writing the .nes file."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_mmc1_test import Asm  # noqa: E402,F401

HERE = os.path.dirname(os.path.abspath(__file__))


def start(org=0x8000):
    """A program that starts with SEI, a stack, and status "running" in
    the blargg $6000 protocol (the signature DE B0 61, no text)."""
    a = Asm(org)
    a.b(0x78, 0xA2, 0xFF, 0x9A)                 # SEI; LDX #$FF; TXS
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)
    a.lda(0x00); a.sta(0x6004)
    return a


def ppu_addr(a, addr):
    a.lda_abs(0x2002)                           # reset the address latch
    a.lda(addr >> 8); a.sta(0x2006)
    a.lda(addr & 0xFF); a.sta(0x2006)


def ppu_write(a, addr, value):
    ppu_addr(a, addr)
    a.lda(value); a.sta(0x2007)


def ppu_read(a, addr):
    """A = the PPU byte at addr (the first read only fills the buffer)."""
    ppu_addr(a, addr)
    a.lda_abs(0x2007)
    a.lda_abs(0x2007)


def ppu_check(a, addr, want, fail):
    ppu_read(a, addr)
    a.cmp(want)
    a.bne(fail)


def finish(a, statuses):
    """The end: "pass" (status 0) right after the last check, then one
    label per failure code, each storing its status and stopping."""
    for status in [0] + list(statuses):
        a.label("pass" if status == 0 else "fail%d" % status)
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)       # JMP to itself
    code = a.done()
    assert a.labels["pass"] == a.org + code.index(bytes([0xA9, 0x00, 0x8D, 0x00, 0x60]))
    return code


def vectors(bank, base, reset, rti):
    """Put the vectors (NMI and IRQ to an RTI, reset) in a bank that ends
    at $FFFF; base is the CPU address of the bank's first byte."""
    bank[rti - base] = 0x40
    for vec, target in ((0xFFFA, rti), (0xFFFC, reset), (0xFFFE, rti)):
        bank[vec - base] = target & 0xFF
        bank[vec - base + 1] = target >> 8


def write_nes(name, mapper, prg, chr_rom, vertical=False, submapper=None):
    """Write tests/NAME: an iNES header (NES 2.0 when a submapper is
    given), the PRG and CHR ROM. No CHR ROM means 8 KB of CHR RAM."""
    f6 = (mapper & 0x0F) << 4 | (1 if vertical else 0)
    f7 = mapper & 0xF0
    if submapper is None:
        header = bytes([0x4E, 0x45, 0x53, 0x1A, len(prg) // 0x4000,
                        len(chr_rom) // 0x2000, f6, f7]) + bytes(8)
    else:
        header = bytes([0x4E, 0x45, 0x53, 0x1A, len(prg) // 0x4000,
                        len(chr_rom) // 0x2000, f6, f7 | 0x08,
                        submapper << 4 | (mapper >> 8), 0,
                        0x07,                       # 8 KB PRG RAM
                        0 if chr_rom else 0x07,     # 8 KB CHR RAM if no ROM
                        0, 0, 0, 0])
    out = os.path.join(HERE, name)
    with open(out, "wb") as f:
        f.write(header + bytes(prg) + bytes(chr_rom))
    print("wrote", out)
