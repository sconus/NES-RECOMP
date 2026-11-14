#!/usr/bin/env python3
"""Write tests/fds_boot.fds: a Famicom Disk System test disk made for
nesrecomp, checking the boot load, the state the BIOS leaves and its
NMI/IRQ dispatch (nesdev wiki "FDS BIOS", "Family Computer Disk
System"). Run it again to regenerate it. fds_image() builds disk images
for the other FDS tests too.

One side, boot code 5, files in this order on the disk:
   0  ID 0  nametable $2800, 224 bytes ($5A ^ i)
   1  ID 1  PRG $6100, the test program
   2  ID 2  PRG $DFF6, the vectors (NMI 1-3, reset, IRQ)
   3  ID 3  CHR $0000, 16 bytes ($A0 + i)
   4  ID 4  PRG $0300, $CC (system RAM: loaded)
   5  ID 4  PRG $0150, $99 (below $0200: not written)
   6  ID 5  PRG $7100, $DD (the boot code itself: loaded)
   7  ID 6  PRG $7200, $EE (above the boot code: not loaded)
   8  ID 0  PRG $2000, $80 (writes PPUCTRL: NMIs on, last of all)
Results through the blargg $6000 protocol. After the first boot's
checks it reports $81 ("press reset"), and the second part runs after
the reset:
   0  passed
   2  $7100 isn't $DD, or $7200 isn't 0 (boot files: IDs up to 5)
   3  $0300 isn't $CC, or $0150 isn't 0
   4  the CHR file isn't at PPU $0000
   5  the nametable file isn't at PPU $2800-$28DF
   6  the NMI the $2000 file turned on didn't reach NMI 3 ($DFFA)
      before the reset vector
   7  what the BIOS leaves: $F9 $FF, $FA $2E, $FB-$FD 0, $FE $06, $FF
      $10, $0100 $C0, $0101 $80, $0102 $35, $0103 $AC
   8  $4025 bit 3 set ($2E): $4030 bit 3 isn't set, or the mirroring
      isn't horizontal ($2000 and $2400 the same)
   9  $4025 = $26: $4030 bit 3 isn't clear, or the mirroring isn't
      vertical ($2000 and $2800 the same)
  10  NMI dispatch: $0100 = $40, $80, $C0 don't reach $DFF6, $DFF8,
      $DFFA; or VINTWait ($E1B2, which takes the NMI with $0100 = $00
      through the BIOS's handler at $E19D) doesn't come back with A
      kept, NMIs off in $FF, $0100 as it was, I set and the program's
      NMI not called
  11  IRQ dispatch: with $0101 = $C0 a timer IRQ doesn't reach $DFFE;
      with $80 the BIOS doesn't acknowledge it (and the program hangs,
      or the program's handler runs)
  14  the timer: stopped part way ($4022 = 0) and started again with a
      new reload value (2048), it fires before ~1500 cycles or not by
      ~2500 (writing $4022 with bit 1 loads the counter)
  15  the timer: writes to $4020/$4021 acknowledge its IRQ ($4030 bit 0
      is clear afterwards)
  12  after the reset: $0102 isn't $35
  13  after the reset: the files were loaded again (a byte the first
      boot changed is back)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402

SIDE_BYTES = 65500
FLAGS = 0x0400                  # $0401-$0403 NMI 1-3, $0404 IRQ


def disk_info(name=b"NRC", side=0, boot_code=0):
    """Block 1, 56 bytes."""
    b = bytearray(56)
    b[0] = 1
    b[1:15] = b"*NINTENDO-HVC*"
    b[0x0F] = 0x00                              # licensee
    b[0x10:0x13] = name
    b[0x13] = 0x20                              # game type: normal
    b[0x15] = side
    b[0x19] = boot_code
    b[0x1A:0x1F] = b"\xff" * 5
    b[0x1F:0x22] = bytes([0x86, 0x02, 0x21])    # a date, BCD
    b[0x22] = 0x49
    return bytes(b)


def side_bytes(info, files):
    """files: (id, name, address, type, data). Block 2, then 3 and 4 for
    each file, padded to a side."""
    out = bytearray(info)
    out += bytes([2, len(files)])
    for n, (fid, name, addr, typ, data) in enumerate(files):
        name = name.encode().ljust(8)[:8]
        out += bytes([3, n, fid]) + name + bytes([addr & 0xFF, addr >> 8,
                                                  len(data) & 0xFF, len(data) >> 8, typ])
        out += bytes([4]) + bytes(data)
    assert len(out) <= SIDE_BYTES
    return bytes(out) + bytes(SIDE_BYTES - len(out))


def fds_image(sides):
    """A .fds file with the 16-byte header."""
    return b"FDS\x1a" + bytes([len(sides)]) + bytes(11) + b"".join(sides)


def program():
    a = Asm(0x6100)
    br = []

    def w(addr, val):
        a.lda(val); a.sta(addr)

    def wait_frames(n):
        """About n frames: LDX; LDY #0; DEY; BNE; DEX; BNE (1280 a step)."""
        a.b(0xA2, max(1, n * 23), 0xA0, 0x00)
        here = a.pc()
        a.b(0x88, 0xD0, 0xFD)
        a.b(0xCA, 0xD0, (here - (a.pc() + 3)) & 0xFF)

    def ppu_read(addr):
        a.lda(addr >> 8); a.sta(0x2006); a.lda(addr & 0xFF); a.sta(0x2006)
        a.lda_abs(0x2007); a.lda_abs(0x2007)

    def ppu_write(addr, val):
        a.lda(addr >> 8); a.sta(0x2006); a.lda(addr & 0xFF); a.sta(0x2006)
        w(0x2007, val)

    def jmp(label):
        a.b(0x4C); a.fix.append((len(a.code), label)); a.b(0, 0)

    a.label("start")
    a.b(0x78)                                   # SEI
    w(0x2000, 0x00)
    a.lda_abs(0x0103); a.cmp(0x53); a.b(0xD0, 3); jmp("soft")
    w(0x6000, 0x80)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        w(0x6001 + i, v)
    a.check(0x7100, 0xDD, "f2"); a.check(0x7200, 0x00, "f2")
    a.check(0x0300, 0xCC, "f3"); a.check(0x0150, 0x00, "f3")
    ppu_read(0x0000); a.cmp(0xA0); a.bne("f4")
    ppu_read(0x000F); a.cmp(0xAF); a.bne("f4")
    ppu_read(0x2800); a.cmp(0x5A); a.bne("f5")
    ppu_read(0x28DF); a.cmp(0x5A ^ 0xDF); a.bne("f5")
    a.check(FLAGS + 3, 1, "f6")
    for addr, v in ((0xF9, 0xFF), (0xFA, 0x2E), (0xFB, 0), (0xFC, 0), (0xFD, 0),
                    (0xFE, 0x06), (0xFF, 0x10), (0x0100, 0xC0), (0x0101, 0x80),
                    (0x0102, 0x35), (0x0103, 0xAC)):
        a.check(addr, v, "f7")
    # 8, 9: the nametable arrangement.
    a.lda_abs(0x4030); a.b(0x29, 0x08); a.cmp(0x08); a.bne("f8")
    ppu_write(0x2000, 0x31); ppu_read(0x2400); a.cmp(0x31); a.bne("f8")
    w(0x4025, 0x26)
    a.lda_abs(0x4030); a.b(0x29, 0x08); a.cmp(0x00); a.bne("f9")
    ppu_write(0x2000, 0x42); ppu_read(0x2800); a.cmp(0x42); a.bne("f9")
    w(0x4025, 0x2E)
    # 10: NMI dispatch.
    for mode, flag in ((0x40, 1), (0x80, 2), (0xC0, 3)):
        w(FLAGS + flag, 0)
        w(0x0100, mode); w(0x2000, 0x80); wait_frames(2)
        a.check(FLAGS + flag, 1, "f10")
    w(0x0100, 0xC0); w(FLAGS + 3, 0)
    a.lda(0x10); a.b(0x85, 0xFF)
    a.b(0x2C, 0x02, 0x20)                       # BIT $2002: vblank flag off
    a.lda(0x5A); a.jsr(0xE1B2)                  # VINTWait
    a.b(0x08)                                   # PHP
    a.cmp(0x5A); a.bne("f10")
    a.b(0x68, 0x29, 0x04); a.cmp(0x04); a.bne("f10")    # PLA; AND #4: I set
    a.b(0xA5, 0xFF); a.cmp(0x10); a.bne("f10")
    a.check(0x0100, 0xC0, "f10"); a.check(FLAGS + 3, 0, "f10")
    # 11: IRQ dispatch, with the timer.
    w(0x0101, 0xC0); w(FLAGS + 4, 0)
    w(0x4020, 0x00); w(0x4021, 0x02); w(0x4022, 0x02)
    a.b(0x58); wait_frames(1); a.b(0x78)        # CLI ... SEI
    a.check(FLAGS + 4, 1, "f11")
    w(0x0101, 0x80); w(0x4022, 0x02)
    a.b(0x58); wait_frames(1); a.b(0x78)
    a.check(FLAGS + 4, 1, "f11")
    # 14: $4022 loads the counter. 16384 cycles, stopped after ~1000,
    # then 2048: no IRQ by ~1500 cycles, one by ~2500.
    w(FLAGS + 4, 0); w(0x0101, 0xC0)
    w(0x4020, 0x00); w(0x4021, 0x40); w(0x4022, 0x02)
    a.b(0xA0, 200, 0x88, 0xD0, 0xFD)            # ~1000 cycles
    w(0x4022, 0x00)
    w(0x4020, 0x00); w(0x4021, 0x08); w(0x4022, 0x02)
    a.b(0x58)                                   # CLI
    a.b(0xA0, 255, 0x88, 0xD0, 0xFD, 0xA0, 45, 0x88, 0xD0, 0xFD)    # ~1500
    a.check(FLAGS + 4, 0, "f14")
    a.b(0xA0, 200, 0x88, 0xD0, 0xFD)            # ~1000 more
    a.b(0x78)
    a.check(FLAGS + 4, 1, "f14")
    # 15: $4020/$4021 writes don't acknowledge (the IRQ stays pending).
    a.lda_abs(0x4030)
    w(0x4020, 0x10); w(0x4021, 0x00); w(0x4022, 0x02)
    a.b(0xA0, 40, 0x88, 0xD0, 0xFD)             # ~200 cycles: it fired
    w(0x4020, 0x10); w(0x4021, 0x00)
    a.lda_abs(0x4030); a.b(0x29, 0x01); a.cmp(0x01); a.bne("f15")
    w(0x4022, 0x00)
    # The second part needs a reset.
    w(0x6FFF, 0x22)                             # was $11 on the disk
    w(0x6000, 0x81)
    a.label("hang")
    jmp("hang")

    a.label("soft")
    a.check(0x0102, 0x35, "f12")
    a.check(0x6FFF, 0x22, "f13")
    w(0x6000, 0x00)
    jmp("hang")

    for n in range(2, 16):
        a.label("f%d" % n)
        w(0x6000, n)
        jmp("hang")

    for k in (1, 2, 3):
        a.label("nmi%d" % k)
        a.b(0x48)                               # PHA
        a.b(0xEE, (FLAGS + k) & 0xFF, (FLAGS + k) >> 8)     # INC flag
        w(0x2000, 0x00)
        a.b(0x68, 0x40)                         # PLA; RTI
    a.label("irq")
    a.b(0x48)
    a.b(0xEE, (FLAGS + 4) & 0xFF, (FLAGS + 4) >> 8)
    a.lda_abs(0x4030)
    a.b(0x68, 0x40)
    code = bytearray(a.done())
    assert 0x6100 + len(code) < 0x6FFF
    code += bytes(0x6FFF - 0x6100 - len(code)) + b"\x11"   # $6FFF starts $11
    vectors = b"".join(bytes([a.labels[l] & 0xFF, a.labels[l] >> 8])
                       for l in ("nmi1", "nmi2", "nmi3", "start", "irq"))
    return bytes(code), vectors


def boot_disk():
    code, vectors = program()
    files = [
        (0, "NTFILE", 0x2800, 2, bytes(0x5A ^ i for i in range(224))),
        (1, "PROGRAM", 0x6100, 0, code),
        (2, "VECTORS", 0xDFF6, 0, vectors),
        (3, "CHR", 0x0000, 1, bytes(0xA0 + i for i in range(16))),
        (4, "SYSRAM", 0x0300, 0, b"\xcc"),
        (4, "LOWRAM", 0x0150, 0, b"\x99"),
        (5, "BOOT5", 0x7100, 0, b"\xdd"),
        (6, "NOTBOOT", 0x7200, 0, b"\xee"),
        (0, "NMION", 0x2000, 0, b"\x80"),
    ]
    return fds_image([side_bytes(disk_info(boot_code=5), files)])


def main():
    path = os.path.join(HERE, "fds_boot.fds")
    with open(path, "wb") as f:
        f.write(boot_disk())
    print("wrote", path)


if __name__ == "__main__":
    main()
