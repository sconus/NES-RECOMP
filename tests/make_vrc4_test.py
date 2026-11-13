#!/usr/bin/env python3
"""Write tests/vrc4_21.nes, vrc4_23.nes and vrc4_25.nes: Konami VRC4 tests
made for nesrecomp, one per iNES mapper number. Run it again to
regenerate them.

Each mapper number covers two ways of wiring the chip's register select
lines (A0, A1) to the CPU's address lines. The ROMs write some registers
through one wiring and some through the other, so both decodings are
checked:
  21  VRC4a (A1, A2) and VRC4c (A6, A7)
  23  VRC4f (A0, A1) and VRC4e (A2, A3)
  25  VRC4b (A1, A0) and VRC4d (A3, A2)

128 KB PRG (sixteen 8 KB banks; byte $1FF0 of each holds its number) and
64 KB CHR ROM (sixty-four 1 KB banks; byte 0 of each holds its number).
The program runs from the last 8 KB, which is fixed at $E000.

Results use the blargg $6000 protocol; status codes:

   0  passed
   2  PRG bank 5 written to $8000 isn't at $8000
   3  PRG bank 7 written to $A000 isn't at $A000
   4  $C000 doesn't hold the second-to-last bank (14)
   5  swap mode ($9002 bit 1): $8000 should hold 14 and $C000 bank 5
   6  CHR bank $23 (low nibble 3, high nibble 2) isn't at PPU $0C00
   7  one-screen mirroring (lower): $2000 and $2400 aren't the same
   8  IRQ, cycle mode, latch $00: fired well before 256 cycles
   9  ... and not fired well after 256 cycles
  10  IRQ, scanline mode, latch $FE: fired well before two scanlines
  11  ... and not fired well after two scanlines
  12  acknowledge with A = 0 should stop further IRQs, but one came
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_mmc1_test import Asm  # noqa: E402

PRG_BANKS = 16              # 8 KB
CHR_BANKS = 64              # 1 KB
TAG = 0x1FF0                # bank number, in each 8 KB bank
COUNT = 0x10                # zero page: IRQs taken

# For each mapper: two wirings, each giving the CPU address bits for chip
# register select bits A0 and A1.
WIRINGS = {
    21: ((1, 2), (6, 7)),
    23: ((0, 1), (2, 3)),
    25: ((1, 0), (3, 2)),
}


def reg_addr(mapper, wiring, base, reg):
    a0, a1 = WIRINGS[mapper][wiring]
    return base | (reg & 1) << a0 | (reg >> 1) << a1


def program(mapper):
    a = Asm(0xE000)
    w = lambda wiring, base, reg: reg_addr(mapper, wiring, base, reg)  # noqa: E731

    def delay(n):
        """About n cycles (5 per loop): LDY #k; DEY; BNE."""
        k = max(1, n // 5)
        a.b(0xA0, k, 0x88, 0xD0, 0xFD)

    a.label("reset")
    a.b(0x78, 0xA2, 0xFF, 0x9A)                 # SEI; LDX #$FF; TXS
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)
    a.lda(0x00); a.sta(0x6004)
    a.b(0x85, COUNT)                            # STA COUNT (A = 0)
    a.sta(w(0, 0xF002, 2))                      # IRQ off

    a.lda(5); a.sta(w(0, 0x8000, 0))
    a.check(0x9FF0, 5, "fail2")
    a.lda(7); a.sta(w(1, 0xA000, 0))
    a.check(0xBFF0, 7, "fail3")
    a.check(0xDFF0, PRG_BANKS - 2, "fail4")
    a.lda(0x02); a.sta(w(1, 0x9000, 2))         # swap mode
    a.check(0x9FF0, PRG_BANKS - 2, "fail5")
    a.check(0xDFF0, 5, "fail5")
    a.lda(0x00); a.sta(w(0, 0x9000, 2))         # back to normal

    # CHR bank 3 (PPU $0C00) = $23: low nibble at $C002, high at $C003.
    a.lda(0x03); a.sta(w(0, 0xC000, 2))
    a.lda(0x02); a.sta(w(1, 0xC000, 3))
    a.lda(0x0C); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.lda_abs(0x2007); a.lda_abs(0x2007)
    a.cmp(0x23); a.bne("fail6")

    # One-screen (lower): $2000 and $2400 are the same 1 KB.
    a.lda(0x02); a.sta(w(0, 0x9000, 0))
    a.lda(0x20); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.lda(0x5A); a.sta(0x2007)
    a.lda(0x24); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.lda_abs(0x2007); a.lda_abs(0x2007)
    a.cmp(0x5A); a.bne("fail7")

    # IRQ, cycle mode: latch $00, control E|M (A = 0). The counter is
    # reloaded with 0 and passes $FF 256 cycles after the write.
    a.lda(0x00); a.sta(w(0, 0xF000, 0)); a.sta(w(1, 0xF000, 1))
    a.b(0x58)                                   # CLI
    a.lda(0x06); a.sta(w(1, 0xF000, 2))
    delay(200)
    a.b(0xA5, COUNT); a.cmp(0); a.bne("fail8")
    delay(110)
    a.b(0xA5, COUNT); a.cmp(1); a.bne("fail9")

    # Acknowledge copied A (0) to E, so the counter stopped: no more IRQs.
    delay(600)
    a.b(0xA5, COUNT); a.cmp(1); a.bne("fail12")

    # IRQ, scanline mode: latch $FE, control E (A = 0). Clocks after 114
    # and 228 cycles; the second passes $FF.
    a.lda(0x00); a.b(0x85, COUNT)
    a.lda(0x0E); a.sta(w(1, 0xF000, 0))
    a.lda(0x0F); a.sta(w(0, 0xF000, 1))
    a.lda(0x02); a.sta(w(0, 0xF000, 2))
    delay(180)
    a.b(0xA5, COUNT); a.cmp(0); a.bne("fail10")
    delay(100)
    a.b(0xA5, COUNT); a.cmp(1); a.bne("fail11")

    a.label("pass")
    statuses = [(0, "pass")] + [(n, "fail%d" % n) for n in range(2, 13)]
    for status, name in statuses:
        if name != "pass":
            a.label(name)
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)       # JMP to itself

    a.label("irq")
    a.b(0x48)                                   # PHA
    a.b(0xE6, COUNT)                            # INC COUNT
    a.sta(w(0, 0xF000, 3))                      # acknowledge (E = A)
    a.b(0x68, 0x40)                             # PLA; RTI
    a.label("nmi")
    a.b(0x40)                                   # RTI
    return a


def build(mapper):
    a = program(mapper)
    code = a.done()
    prg = bytearray()
    for bank in range(PRG_BANKS):
        b = bytearray(0x2000)
        b[TAG] = bank
        prg += b
    last = (PRG_BANKS - 1) * 0x2000
    prg[last:last + len(code)] = code
    assert len(code) < TAG
    prg[last + TAG] = PRG_BANKS - 1
    for vec, name in ((0x1FFA, "nmi"), (0x1FFC, "reset"), (0x1FFE, "irq")):
        target = a.labels[name]
        prg[last + vec] = target & 0xFF
        prg[last + vec + 1] = target >> 8
    chr_rom = bytearray()
    for bank in range(CHR_BANKS):
        c = bytearray(0x400)
        c[0] = bank
        chr_rom += c
    header = bytes([0x4E, 0x45, 0x53, 0x1A, len(prg) // 0x4000,
                    len(chr_rom) // 0x2000, (mapper & 0x0F) << 4,
                    mapper & 0xF0]) + bytes(8)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "vrc4_%d.nes" % mapper)
    with open(out, "wb") as f:
        f.write(header + prg + chr_rom)
    print("wrote", out)


if __name__ == "__main__":
    for m in WIRINGS:
        build(m)
