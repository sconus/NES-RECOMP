#!/usr/bin/env python3
"""Write tests/fds_helpers.fds: a Famicom Disk System test disk made for
nesrecomp, checking the project BIOS's routines other than the disk ones
(tools/make_fds_bios.py, from the nesdev wiki's "FDS BIOS"). Run it again
to regenerate it; tests/inputs/fds_helpers.txt holds A and Start on
controller 1, Right on controller 2, and (run with --famicom-4p, pads 3
and 4 on the expansion port) B on 3 and Up on 4.

Results through the blargg $6000 protocol (timings with the FDS timer:
it fires a set number of cycles after $4022 is written, seen in $4030
bit 0):
   0  passed
   2  Delay131 isn't 131 cycles, the JSR included (to the cycle)
   3  Delayms isn't 1790 * Y + 5 cycles plus the JSR (to the cycle) for
      Y = 1 and 3, or Y = 0 isn't longer than 65536 cycles (256 ms)
   4  DisPFObj, EnObj, EnPF, DisObj, DisPF, EnPFObj don't leave $FE as
      they should
   5  VINTWait doesn't come back with the vblank flag clear
   6  VRAMStructWrite: a copy, a sub-structure ($4C) that fills, an
      add-32 record, a fill with length 0 (64 bytes), the end; or $FF
      bit 2 isn't clear after
   7  PrepareVRAMString: not A = $FF and the string in the buffer at
      $0302 with $FF after, or a string too big isn't A = 1 and left
      out; WriteVRAMBuffer doesn't put it in VRAM, or doesn't empty the
      buffer
   8  PrepareVRAMStrings: a 3x2 block isn't two rows 32 apart, or a
      block too big isn't A = 1
   9  Pixel2NamConv (72, 41) isn't $2125, or Nam2PixelConv $2125 isn't
      (72, 40)
  10  Random from $12 $34: not $89 $1A, $C4 $8D, $62 $46
  11  SpriteDMA: OAM doesn't hold $0200-$02FF
  12  CounterLogic: the first counter doesn't go 0 -> 9 -> 8, the fast
      ones don't count down every call (stopping at 0), or the slow
      ones don't count only when the first goes round
  13  the controller routines: ReadPads, OrPads, ReadDownPads,
      ReadOrDownPads, the Verify ones, ReadDownExpPads: what's held and
      what's new
  14  VRAMFill: pattern data (16 tiles of $5A), a nametable ($11) and
      its attributes ($E4)
  15  MemFill: pages 5 to 6 (both) aren't $77, or pages 4 and 7 changed
  16  JumpEngine with A = 2 didn't go to the third address
  17  FetchDirectPtr from a routine of the program: the pointer after
      the program's JSR isn't in $00-$01, or the return isn't past it
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402
from make_fds_test import disk_info, side_bytes, fds_image  # noqa: E402

BIOS = dict(Delay131=0xE149, Delayms=0xE153, DisPFObj=0xE161, EnPFObj=0xE16B,
            DisObj=0xE171, EnObj=0xE178, DisPF=0xE17E, EnPF=0xE185,
            VINTWait=0xE1B2, VRAMStructWrite=0xE7BB, FetchDirectPtr=0xE844,
            WriteVRAMBuffer=0xE86A, PrepareVRAMString=0xE8D2,
            PrepareVRAMStrings=0xE8E1, Pixel2NamConv=0xE97D, Nam2PixelConv=0xE997,
            Random=0xE9B1, SpriteDMA=0xE9C8, CounterLogic=0xE9D3, ReadPads=0xE9EB,
            OrPads=0xEA0D, ReadDownPads=0xEA1A, ReadOrDownPads=0xEA1F,
            ReadDownVerifyPads=0xEA36, ReadOrDownVerifyPads=0xEA4C,
            ReadDownExpPads=0xEA68, VRAMFill=0xEA84, MemFill=0xEAD2,
            JumpEngine=0xEAFD)


def program():
    a = Asm(0x6100)

    def w(addr, val):
        a.lda(val); a.sta(addr)

    def zp(addr, val):
        a.lda(val); a.b(0x85, addr)

    def zp_is(addr, val, fail):
        a.b(0xA5, addr); a.cmp(val); a.bne(fail)

    def jmp(label):
        a.b(0x4C); a.fix.append((len(a.code), label)); a.b(0, 0)

    def word(label):
        a.b(0, 0); a.fix.append((len(a.code) - 2, label))

    def bios(name):
        a.jsr(BIOS[name])

    def ppu_is(addr, val, fail):
        a.b(0x2C, 0x02, 0x20)
        a.lda(addr >> 8); a.sta(0x2006); a.lda(addr & 0xFF); a.sta(0x2006)
        a.lda_abs(0x2007); a.lda_abs(0x2007); a.cmp(val); a.bne(fail)

    def timed(routine, y, cycles, fires, fail):
        """Start the timer to fire `cycles` after the $4022 write, call
        the routine (with Y), and check whether it fired by the read of
        $4030 just after."""
        a.lda_abs(0x4030)
        w(0x4020, cycles & 0xFF); w(0x4021, cycles >> 8)
        if y is not None:
            a.b(0xA0, y)
        w(0x4022, 0x02)
        bios(routine)
        a.lda_abs(0x4030); a.b(0x29, 0x01)
        a.cmp(1 if fires else 0); a.bne(fail)
        w(0x4022, 0x00)

    a.label("start")
    a.b(0x78, 0xD8)                             # SEI; CLD
    w(0x2000, 0x00); zp(0xFF, 0x00)
    w(0x6000, 0x80)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        w(0x6001 + i, v)
    # 2, 3: from the $4022 write to the $4030 read: the routine (with
    # its JSR) and the read's 4 cycles; the timer fires after N + 1.
    timed("Delay131", None, 131 + 4 - 1, True, "f2")
    timed("Delay131", None, 131 + 4, False, "f2")
    for y in (1, 3):
        n = 6 + 1790 * y + 5 + 4 - 1
        timed("Delayms", y, n, True, "f3")
        timed("Delayms", y, n + 1, False, "f3")
    timed("Delayms", 0, 0xFFFF, True, "f3")
    # 4
    zp(0xFE, 0x1E)
    for name, want in (("DisPFObj", 0x06), ("EnObj", 0x16), ("EnPF", 0x1E),
                       ("DisObj", 0x0E), ("DisPF", 0x06), ("EnPFObj", 0x1E)):
        bios(name); zp_is(0xFE, want, "f4")
    w(0x2001, 0x00)
    # 5
    w(0x0100, 0xC0); zp(0xFF, 0x00)
    a.b(0x2C, 0x02, 0x20)
    bios("VINTWait")
    a.lda_abs(0x2002); a.b(0x29, 0x80); a.bne("f5")
    # 6
    zp(0xFF, 0x04)
    bios("VRAMStructWrite"); word("vstruct")
    zp_is(0xFF, 0x00, "f6")
    for i, ch in enumerate(b"TEST"):
        ppu_is(0x2000 + i, ch, "f6")
    ppu_is(0x2040, 0xAA, "f6"); ppu_is(0x2044, 0xAA, "f6"); ppu_is(0x2045, 0x00, "f6")
    ppu_is(0x2080, 1, "f6"); ppu_is(0x20A0, 2, "f6"); ppu_is(0x20C0, 3, "f6")
    ppu_is(0x2081, 0, "f6")
    ppu_is(0x2200, 0x55, "f6"); ppu_is(0x223F, 0x55, "f6"); ppu_is(0x2240, 0x00, "f6")
    # 7
    w(0x0300, 0x20); w(0x0301, 0x00); w(0x0302, 0xFF)
    a.lda(0x21); a.b(0xA2, 0x00, 0xA0, 0x03)    # LDX #0; LDY #3
    bios("PrepareVRAMString"); word("abc")
    a.cmp(0xFF); a.bne("f7")
    a.check(0x0301, 6, "f7")
    for i, v in enumerate((0x21, 0x00, 0x03) + tuple(b"ABC") + (0xFF,)):
        a.check(0x0302 + i, v, "f7")
    a.lda(0x21); a.b(0xA2, 0x20, 0xA0, 0x30)
    bios("PrepareVRAMString"); word("abc")
    a.cmp(0x01); a.bne("f7")
    a.check(0x0301, 6, "f7")
    bios("WriteVRAMBuffer")
    a.check(0x0301, 0, "f7"); a.check(0x0302, 0xFF, "f7")
    for i, ch in enumerate(b"ABC"):
        ppu_is(0x2100 + i, ch, "f7")
    # 8
    a.lda(0x21); a.b(0xA2, 0x40)
    bios("PrepareVRAMStrings"); word("block")
    a.cmp(0xFF); a.bne("f8")
    a.check(0x0301, 12, "f8")
    bios("WriteVRAMBuffer")
    for i, ch in enumerate(b"XYZ"):
        ppu_is(0x2140 + i, ch, "f8")
    for i, ch in enumerate(b"UVW"):
        ppu_is(0x2160 + i, ch, "f8")
    ppu_is(0x2143, 0, "f8")
    w(0x0300, 0x08)
    a.lda(0x21); a.b(0xA2, 0x40)
    bios("PrepareVRAMStrings"); word("block")
    a.cmp(0x01); a.bne("f8")
    a.check(0x0301, 0, "f8")
    # 9
    zp(0x02, 72); zp(0x03, 41)
    bios("Pixel2NamConv")
    zp_is(0x00, 0x21, "f9"); zp_is(0x01, 0x25, "f9")
    zp(0x02, 0); zp(0x03, 0)
    bios("Nam2PixelConv")
    zp_is(0x02, 72, "f9"); zp_is(0x03, 40, "f9")
    # 10
    zp(0x10, 0x12); zp(0x11, 0x34)
    for b0, b1 in ((0x89, 0x1A), (0xC4, 0x8D), (0x62, 0x46)):
        a.b(0xA2, 0x10, 0xA0, 0x02)
        bios("Random")
        zp_is(0x10, b0, "f10"); zp_is(0x11, b1, "f10")
    # 11
    a.b(0xA2, 0x00)
    a.label("oam_fill")
    a.b(0x8A, 0x49, 0x5A, 0x9D, 0x00, 0x02, 0xE8)   # TXA; EOR #$5A; STA $0200,X; INX
    a.b(0xD0, (a.labels["oam_fill"] - (a.pc() + 2)) & 0xFF)
    bios("SpriteDMA")
    for at in (0x00, 0x10, 0xFC):
        w(0x2003, at)
        a.lda_abs(0x2004); a.cmp(at ^ 0x5A); a.bne("f11")
    # 12: counters $20 (first), $21-$22 (fast), $23-$24 (slow).
    for addr, v in ((0x20, 0), (0x21, 5), (0x22, 0), (0x23, 3), (0x24, 0)):
        zp(addr, v)
    for want in ((9, 4, 0, 2, 0), (8, 3, 0, 2, 0)):
        a.lda(0x22); a.b(0xA2, 0x20, 0xA0, 0x24)
        bios("CounterLogic")
        for i, v in enumerate(want):
            zp_is(0x20 + i, v, "f12")
    # 13: A + Start on pad 1 ($90), Right on pad 2 ($01), B on pad 3
    # ($40, expansion 1) and Up on pad 4 ($08, expansion 2).
    zp(0xFB, 0x00)
    bios("ReadPads")
    for addr, v in ((0xF5, 0x90), (0xF6, 0x01), (0x00, 0x40), (0x01, 0x08)):
        zp_is(addr, v, "f13")
    zp(0x00, 0x03); zp(0x01, 0x40)
    bios("OrPads")
    zp_is(0xF5, 0x93, "f13"); zp_is(0xF6, 0x41, "f13")
    zp(0xF7, 0); zp(0xF8, 0)
    bios("ReadDownPads")
    for addr, v in ((0xF5, 0x90), (0xF6, 0x01), (0xF7, 0x90), (0xF8, 0x01)):
        zp_is(addr, v, "f13")
    bios("ReadDownPads")
    zp_is(0xF5, 0x00, "f13"); zp_is(0xF6, 0x00, "f13")
    zp(0xF7, 0x10)
    bios("ReadOrDownPads")
    zp_is(0xF5, 0xC0, "f13"); zp_is(0xF7, 0xD0, "f13"); zp_is(0xF8, 0x09, "f13")
    zp(0xF7, 0); zp(0xF8, 0)
    bios("ReadDownVerifyPads")
    zp_is(0xF5, 0x90, "f13"); zp_is(0xF8, 0x01, "f13")
    bios("ReadOrDownVerifyPads")
    zp_is(0xF5, 0x40, "f13"); zp_is(0xF6, 0x08, "f13"); zp_is(0xF7, 0xD0, "f13")
    for addr in (0xF5, 0xF6, 0xF7, 0xF8):
        zp(addr, 0)
    bios("ReadDownExpPads")
    for addr, v in ((0xF1, 0x90), (0xF2, 0x01), (0xF3, 0x40), (0xF4, 0x08),
                    (0xF5, 0x90), (0xF6, 0x01), (0xF7, 0x40), (0xF8, 0x08)):
        zp_is(addr, v, "f13")
    # 14
    a.lda(0x10); a.b(0xA2, 0x5A, 0xA0, 0x01)
    bios("VRAMFill")
    ppu_is(0x1000, 0x5A, "f14"); ppu_is(0x10FF, 0x5A, "f14"); ppu_is(0x1100, 0x00, "f14")
    a.lda(0x24); a.b(0xA2, 0x11, 0xA0, 0xE4)
    bios("VRAMFill")
    ppu_is(0x2400, 0x11, "f14"); ppu_is(0x27BF, 0x11, "f14")
    ppu_is(0x27C0, 0xE4, "f14"); ppu_is(0x27FF, 0xE4, "f14")
    # 15
    w(0x04FF, 0x00); w(0x0700, 0x00)
    a.lda(0x77); a.b(0xA2, 0x05, 0xA0, 0x06)
    bios("MemFill")
    for addr, v in ((0x0500, 0x77), (0x05FF, 0x77), (0x0600, 0x77), (0x06FF, 0x77),
                    (0x04FF, 0x00), (0x0700, 0x00)):
        a.check(addr, v, "f15")
    # 16
    a.lda(2)
    bios("JumpEngine"); word("f16"); word("f16"); word("je_ok")
    a.label("je_ok")
    # 17
    zp(0x00, 0); zp(0x01, 0)
    a.b(0x20); a.fix.append((len(a.code), "own_routine")); a.b(0, 0)
    a.b(0x34, 0x12)                             # the pointer: $1234
    zp_is(0x00, 0x34, "f17"); zp_is(0x01, 0x12, "f17")
    w(0x6000, 0x00)
    a.label("hang")
    jmp("hang")
    for n in range(2, 18):
        a.label("f%d" % n)
        w(0x6000, n)
        jmp("hang")
    a.label("own_routine")
    bios("FetchDirectPtr")
    a.rts()
    a.label("rti")
    a.b(0x40)

    a.label("vstruct")
    a.b(0x20, 0x00, 4, *b"TEST")
    a.b(0x4C); word("vsub")
    a.b(0x20, 0x80, 0x80 | 3, 1, 2, 3)
    a.b(0x22, 0x00, 0x40 | 0, 0x55)
    a.b(0xFF)
    a.label("vsub")
    a.b(0x20, 0x40, 0x40 | 5, 0xAA)
    a.b(0x60)
    a.label("abc")
    a.b(*b"ABC")
    a.label("block")
    a.b(0x23, *b"XYZUVW")
    return a


def main():
    a = program()
    code = a.done()
    assert 0x6100 + len(code) <= 0x8000
    rti, start = a.labels["rti"], a.labels["start"]
    vectors = bytes([rti & 0xFF, rti >> 8] * 3 + [start & 0xFF, start >> 8, rti & 0xFF, rti >> 8])
    files = [(0, "PROGRAM", 0x6100, 0, code), (1, "VECTORS", 0xDFF6, 0, vectors)]
    path = os.path.join(HERE, "fds_helpers.fds")
    with open(path, "wb") as f:
        f.write(fds_image([side_bytes(disk_info(name=b"HLP", boot_code=1), files)]))
    print("wrote", path)
    script = os.path.join(HERE, "inputs", "fds_helpers.txt")
    with open(script, "w") as f:
        f.write("# tests/fds_helpers.fds (make_fds_helpers_test.py): A and Start on\n"
                "# controller 1, Right on 2, B on 3 and Up on 4 (--famicom-4p),\n"
                "# from the start.\n"
                "0 a start 2:right 3:b 4:up\n")
    print("wrote", script)


if __name__ == "__main__":
    main()
