#!/usr/bin/env python3
"""Write tests/irq_timing.nes: checks when the CPU takes an IRQ, made for
nesrecomp. Run it again to regenerate the ROM.

It's an MMC3 board (32 KB PRG, CHR RAM). With rendering off, two writes
to $2006 move the PPU address from $0000 to $1000; that A12 rise clocks
the MMC3 counter by hand, and with the reload value 0 that raises an IRQ
right away. Each check raises the IRQ while I is set, then lets it in a
different way. The handler records `flag` (which the code increments
right after letting the IRQ in) into `seen`.

Status codes ($6000 protocol):
  0  passed
  2  IRQ was taken while the I flag was set (checked across vblanks)
  3  CLI: the instruction after CLI should run before the IRQ
  4  PLP: the same, for PLP clearing I
  5  RTI: the IRQ should come straight after RTI, before the next one
  6  acknowledging through $E000 didn't lower the IRQ line (the handler
     ran 10 times, or an IRQ came after the last check)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_mmc1_test import Asm         # noqa: E402

FLAG, SEEN, COUNT = 0x10, 0x11, 0x12


def code():
    a = Asm(0xE000)
    def sta_zp(z): a.b(0x85, z)
    def lda_zp(z): a.b(0xA5, z)
    def inc_zp(z): a.b(0xE6, z)

    a.b(0x78, 0xD8, 0xA2, 0xFF, 0x9A)            # SEI CLD LDX #$FF TXS
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61, 0x00)):
        a.lda(v); a.sta(0x6001 + i)
    a.lda(0x40); a.sta(0x4017)                   # APU frame IRQ off
    a.lda(0); a.sta(0x2000); a.sta(0x2001)       # rendering off
    a.sta(0xC000)                                # reload value 0

    def raise_irq():
        a.jsr_label("raise")

    def start_check():
        a.lda(0xFF); sta_zp(SEEN)
        raise_irq()
        a.lda(0); sta_zp(FLAG)

    def expect_seen(value, fail):
        a.b(0x78)                                # SEI
        lda_zp(SEEN); a.cmp(value); a.bne(fail)

    a.lda(0); sta_zp(COUNT)

    # 2: nothing happens while I is set, even across two vblanks (when
    # the runtime is busy with other hardware events).
    start_check()
    for _ in range(2):
        a.b(0x2C, 0x02, 0x20)                    # BIT $2002
        a.b(0x10, 0xFB)                          # BPL back to the BIT
    lda_zp(SEEN); a.cmp(0xFF); a.bne("f2")

    # 3: CLI. The INC after CLI runs first, so the handler sees 1.
    a.b(0x58)                                    # CLI (IRQ already pending)
    inc_zp(FLAG)
    a.b(0xEA, 0xEA)
    expect_seen(1, "f3")

    # 4: PLP clearing I behaves like CLI.
    start_check()
    a.lda(0x20); a.b(0x48, 0x28)                 # LDA #$20; PHA; PLP
    inc_zp(FLAG)
    a.b(0xEA, 0xEA)
    expect_seen(1, "f4")

    # 5: RTI restoring I = 0 lets the IRQ in before the next instruction.
    start_check()
    a.b(0xA9, 0, 0x48, 0xA9, 0, 0x48)            # return address (patched)
    ret_hi, ret_lo = len(a.code) - 5, len(a.code) - 2
    a.lda(0x20); a.b(0x48, 0x40)                 # LDA #$20; PHA; RTI
    a.label("after_rti")
    inc_zp(FLAG)
    a.b(0xEA, 0xEA)
    expect_seen(0, "f5")

    # 6: the handler acknowledged with $E000, so after it returns the line
    # is low: with I clear again, nothing more arrives.
    a.lda(0xFF); sta_zp(SEEN)
    a.b(0x58)                                    # CLI
    for _ in range(8):
        a.b(0xEA)
    a.b(0x78)
    lda_zp(SEEN); a.cmp(0xFF); a.bne("f6")

    def finish(status):
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)
    finish(0)
    for n in range(2, 7):
        a.label("f%d" % n)
        finish(n)

    # Raise the IRQ: acknowledge any old one, reload, enable, then clock
    # the counter once with an A12 rise.
    a.label("raise")
    a.sta(0xE000)                                # disable + acknowledge
    a.sta(0xC001)                                # reload on next clock
    a.sta(0xE001)                                # enable
    a.lda(0x00); a.sta(0x2006); a.sta(0x2006)    # v = $0000 (A12 low)
    a.lda(0x10); a.sta(0x2006)
    a.lda(0x00); a.sta(0x2006)                   # v = $1000 (A12 rises)
    a.rts()

    # The handler also counts itself: only 3 IRQs should ever happen, so
    # a line that never goes low shows up as code 6 instead of a hang.
    a.label("irq")
    lda_zp(FLAG); sta_zp(SEEN)
    a.sta(0xE000)                                # acknowledge
    inc_zp(COUNT)
    lda_zp(COUNT); a.cmp(10); a.b(0x90, 3)       # BCC over the JMP
    a.b(0x4C, 0, 0)
    a.fix.append((len(a.code) - 2, "f6"))
    a.b(0x40)                                    # RTI

    a.label("nmi")
    a.b(0x40)

    out = bytearray(a.done())
    target = a.labels["after_rti"]
    out[ret_hi], out[ret_lo] = target >> 8, target & 0xFF
    return out, a.labels


def build():
    body, labels = code()
    prg = bytearray(0x8000)
    prg[0x6000:0x6000 + len(body)] = body        # $E000 is the fixed bank
    for vec, name in ((0x7FFA, "nmi"), (0x7FFC, None), (0x7FFE, "irq")):
        target = labels[name] if name else 0xE000
        prg[vec], prg[vec + 1] = target & 0xFF, target >> 8
    header = bytes([0x4E, 0x45, 0x53, 0x1A, 2, 0, 0x40, 0x00]) + bytes(8)
    return header + prg


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "irq_timing.nes")
    with open(out, "wb") as f:
        f.write(build())
    print("wrote", out)


if __name__ == "__main__":
    main()
