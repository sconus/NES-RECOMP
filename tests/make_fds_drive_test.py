#!/usr/bin/env python3
"""Write tests/fds_drive.fds: a Famicom Disk System test disk made for
nesrecomp that reads its own blocks through the drive's registers
($4024-$4025, $4030-$4032; nesdev wiki "Family Computer Disk System",
"FDS disk format"), by polling and by IRQ, and writes one back. Run it
again to regenerate it.

One side, boot code 1:
   0  ID 0  PRG $6100, the test program
   1  ID 1  PRG $DFF6, the vectors
   2  ID 5  PRG $7000, "ORIGINAL" (rewritten through the drive)
Results through the blargg $6000 protocol:
   0  passed
   2  block 1 (the disk info): not ready ($4032 bit 1) isn't 1 before
      the motor starts and 0 after; the block doesn't start with 1 and
      "*NINTENDO-HVC*"; or its CRC is flagged bad ($4030 bit 4)
   3  the first byte didn't come about 28300 bits (3537 bytes) after
      the start: between about 3200 and 4000 byte times
   4  one byte to the next isn't about 149 cycles (11-18 turns of a
      9-cycle loop, after the ~25 cycles of reading the first)
   5  block 2: not 2 and a file count of 3, or a bad CRC
  11  reading $4030 cleared the transfer flag, or reading $4031 didn't
   6  the CRC checked one byte early isn't flagged bad
   7  file 1's data block, read by the transfer IRQ ($4025 bit 7,
      through $0101 = $C0): the bytes aren't the vectors, or a bad CRC
   8  file 2's data block, written through $4024 in write mode (the gap,
      the $80 mark, the block, $4025 bit 4 for the CRC): LoadFiles
      doesn't load the new bytes
   9  read back through the drive: not the new bytes, or a bad CRC
  10  at the end of the side: $4030 bit 6 (end of head) isn't set, or
      $4032 bit 1 (not ready) isn't; after a transfer reset ($4025 bit
      0 = 0) and a new start, block 1 doesn't come first again
  12  with $4025 bit 5 clear, a byte still arrived (over about 450 byte
      times, blocks 2-4 going past)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402
from make_fds_test import disk_info, side_bytes, fds_image  # noqa: E402

RESET, START, READ, READ_CRC, READ_IRQ = 0x2E, 0x2D, 0x6D, 0x7D, 0xED
WRITE, WRITE_ON, WRITE_CRC = 0x29, 0x69, 0x79
COUNT, CRC_FLAG = 0x20, 0x22        # zero page: bytes to read, $4030 bit 4
BUF = 0x0500
LOAD_FILES = 0xE1F8
OLD, NEW = b"ORIGINAL", b"REWRITE!"
INFO = disk_info(name=b"DRV", boot_code=1)


def program(program_size):
    """The program; program_size is its own file's size (it reads past
    that file's data block)."""
    a = Asm(0x6100)

    def w(addr, val):
        a.lda(val); a.sta(addr)

    def jmp(label):
        a.b(0x4C); a.fix.append((len(a.code), label)); a.b(0, 0)

    def jsr(label):
        a.b(0x20); a.fix.append((len(a.code), label)); a.b(0, 0)

    def back(op, label):
        a.b(op)
        a.b((a.labels[label] - (a.pc() + 1)) & 0xFF)

    def wait_flag():
        here = "wf%d" % len(a.code)
        a.label(here)
        a.b(0x2C, 0x30, 0x40)                       # BIT $4030
        back(0x10, here)                            # BPL

    def count(n):
        a.lda(n & 0xFF); a.b(0x85, COUNT); a.lda(n >> 8); a.b(0x85, COUNT + 1)

    def block(n, fail, crc_ok=True):
        """Read a block of n bytes into BUF (from the next mark)."""
        count(n); jsr("read_block")
        a.b(0xA5, CRC_FLAG); a.cmp(0 if crc_ok else 0x10); a.bne(fail)

    a.label("start")
    a.b(0x78, 0xD8)                                 # SEI; CLD
    w(0x2000, 0x00)
    w(0x6000, 0x80)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        w(0x6001 + i, v)
    # 2, 3, 4: block 1, timing the gap and a byte.
    w(0x4025, RESET)
    a.lda_abs(0x4032); a.b(0x29, 0x02); a.cmp(0x02); a.bne("f2")
    w(0x4025, START)
    a.lda_abs(0x4032); a.b(0x29, 0x02); a.cmp(0x00); a.bne("f2")
    w(0x4025, READ)
    a.b(0xA2, 0x00, 0xA0, 0x00)                     # LDX #0; LDY #0
    a.label("gap")                                  # 12 cycles a turn (13 per 256)
    a.b(0xE8, 0xD0, 0x01, 0xC8)                     # INX; BNE +1; INY
    a.b(0x2C, 0x30, 0x40)
    back(0x10, "gap")
    # 3200-4000 bytes = 478,000-597,000 cycles: Y (256 turns each) 155-194.
    a.b(0xC0, 155); a.b(0xB0, 3); jmp("f3")         # CPY #155; BCS
    a.b(0xC0, 195); a.b(0x90, 3); jmp("f3")         # CPY #195; BCC
    a.lda_abs(0x4031); a.sta(BUF)
    a.b(0xA0, 0x00)
    a.label("period")
    a.b(0xC8)                                       # INY (9 cycles a turn)
    a.b(0x2C, 0x30, 0x40)
    back(0x10, "period")
    a.lda_abs(0x4031); a.sta(BUF + 1)
    a.b(0xC0, 11); a.b(0xB0, 3); jmp("f4")
    a.b(0xC0, 19); a.b(0x90, 3); jmp("f4")
    count(54); a.b(0xA2, 2); jsr("read_body")
    a.b(0xA5, CRC_FLAG); a.bne("f2")
    a.check(BUF, 1, "f2")
    for i, ch in enumerate(b"*NINTENDO-HVC*"):
        a.check(BUF + 1 + i, ch, "f2")
    # 5, 11: block 2, with the transfer flag looked at closely.
    w(0x4025, START)
    a.b(0xA0, 100, 0x88, 0xD0, 0xFD)                # 3 byte times: past the CRC
    a.lda_abs(0x4031)                               # the flag a byte after it left
    w(0x4025, READ)
    wait_flag()
    a.lda_abs(0x4030); a.lda_abs(0x4030)            # it stays set
    a.b(0x29, 0x80); a.cmp(0x80); a.bne("f11")
    a.lda_abs(0x4031); a.sta(BUF)
    a.lda_abs(0x4030); a.b(0x29, 0x80); a.cmp(0x00); a.bne("f11")
    count(1); a.b(0xA2, 1); jsr("read_body")
    a.b(0xA5, CRC_FLAG); a.bne("f5")
    a.check(BUF, 2, "f5"); a.check(BUF + 1, 3, "f5")
    # 6: file 0's header, its CRC checked a byte early.
    block(15, "f6", crc_ok=False)
    a.check(BUF, 3, "f6")
    # File 0's data (the program itself).
    block(1 + program_size, "f6")
    # File 1's header, then its data by IRQ.
    block(16, "f7")
    w(0x0101, 0xC0)
    w(0x4025, START)
    a.b(0xA0, 100, 0x88, 0xD0, 0xFD)
    a.lda_abs(0x4031)
    a.b(0xA2, 0x00)                                 # LDX #0
    w(0x4025, READ_IRQ)
    a.b(0x58)                                       # CLI
    a.label("irq_wait")
    a.b(0xE0, 11)                                   # CPX #11
    back(0xD0, "irq_wait")
    w(0x4025, READ_CRC)
    a.b(0x78)                                       # SEI
    wait_flag(); a.lda_abs(0x4031)
    wait_flag(); a.lda_abs(0x4031)
    a.lda_abs(0x4030); a.b(0x29, 0x10); a.bne("f7")
    a.check(BUF, 4, "f7")
    a.b(0xA2, 0)
    a.label("vec_check")
    a.b(0xBD, (BUF + 1) & 0xFF, (BUF + 1) >> 8)     # LDA BUF+1,X
    a.b(0xDD, 0, 0); a.fix.append((len(a.code) - 2, "vectors"))   # CMP vectors,X
    a.bne("f7")
    a.b(0xE8, 0xE0, 10)                             # INX; CPX #10
    back(0xD0, "vec_check")
    # 8: file 2's header, then its data block written anew.
    block(16, "f8")
    a.check(BUF + 2, 5, "f8")                       # ID 5
    w(0x4025, WRITE)                                # zeros go out
    a.b(0xA0, 200, 0x88, 0xD0, 0xFD)                # ~7 byte times of gap
    w(0x4024, 0x80)
    w(0x4025, WRITE_ON)
    for v in (0x04,) + tuple(NEW):
        wait_flag()
        w(0x4024, v)
    wait_flag()                                     # the last byte is out
    w(0x4025, WRITE_CRC)
    a.b(0xA2, 140)                                  # the CRC, then a gap
    a.label("gap_out")                              # over the old block
    wait_flag()
    a.b(0x8D, 0x24, 0x40)                           # STA $4024 (clears it)
    a.b(0xCA)
    back(0xD0, "gap_out")
    w(0x4025, RESET)
    for i in range(8):
        w(0x7000 + i, 0)
    a.jsr(LOAD_FILES)
    a.b(0, 0); a.fix.append((len(a.code) - 2, "disk_id"))
    a.b(0, 0); a.fix.append((len(a.code) - 2, "list_5"))
    a.cmp(0); a.bne("f8")
    for i, ch in enumerate(NEW):
        a.check(0x7000 + i, ch, "f8")
    # 9: read it back through the drive.
    w(0x4025, START)
    for n in (56, 2, 16, 1 + program_size, 16, 11, 16):
        block(n, "f9")
    block(9, "f9")
    a.check(BUF, 4, "f9")
    for i, ch in enumerate(NEW):
        a.check(BUF + 1 + i, ch, "f9")
    # 10: on to the end of the side.
    a.label("to_end")
    a.lda_abs(0x4030); a.b(0x29, 0x40)
    back(0xF0, "to_end")                            # BEQ
    a.lda_abs(0x4032); a.b(0x29, 0x02); a.cmp(0x02); a.bne("f10")
    w(0x4025, RESET)
    a.lda_abs(0x4030); a.b(0x29, 0x40); a.bne("f10")
    w(0x4025, START)
    block(56, "f10")
    a.check(BUF, 1, "f10")
    # 12: bit 5 clear: nothing comes (65,000 cycles, past blocks 2-4).
    w(0x4025, READ & ~0x20 & ~0x40)
    a.lda_abs(0x4031)
    w(0x4025, READ & ~0x20)
    a.b(0xA2, 0x00, 0xA0, 0x00)
    a.label("no5")                                  # 13 cycles a turn
    a.b(0x2C, 0x30, 0x40); a.b(0x30, 3); jmp("no5_ok")  # BIT; BMI: a byte came
    jmp("f12")
    a.label("no5_ok")
    a.b(0xE8, 0xD0, 0x02, 0xC8, 0xEA)               # INX; BNE +2; INY; NOP
    a.b(0xC0, 20)                                   # CPY #20 (5120 turns)
    back(0xD0, "no5")
    w(0x4025, RESET)
    w(0x6000, 0x00)
    a.label("hang")
    jmp("hang")
    for n in range(2, 13):
        a.label("f%d" % n)
        w(0x4025, RESET)
        w(0x6000, n)
        jmp("hang")

    # read_block: wait for the next mark (bit 6 off for 3 byte times,
    # then on), then read_body: COUNT bytes to BUF+X, then the CRC,
    # leaving $4030 bit 4 in CRC_FLAG. Bytes go on coming after the
    # CRC while bit 6 is on, and the flag the last one raised stays set
    # (only $4031 and $4024 clear it), so $4031 is read once on the way.
    a.label("read_block")
    w(0x4025, START)
    a.b(0xA0, 100, 0x88, 0xD0, 0xFD)
    a.lda_abs(0x4031)
    w(0x4025, READ)
    a.b(0xA2, 0x00)
    a.label("read_body")
    a.label("rb_loop")
    wait_flag()
    a.lda_abs(0x4031)
    a.b(0x9D, BUF & 0xFF, BUF >> 8)                 # STA BUF,X
    a.b(0xE8)                                       # INX
    a.b(0xA5, COUNT, 0xD0, 0x02, 0xC6, COUNT + 1)   # LDA COUNT; BNE +2; DEC COUNT+1
    a.b(0xC6, COUNT)                                # DEC COUNT
    a.b(0xA5, COUNT, 0x05, COUNT + 1)               # LDA COUNT; ORA COUNT+1
    back(0xD0, "rb_loop")
    w(0x4025, READ_CRC)
    wait_flag(); a.lda_abs(0x4031)
    wait_flag(); a.lda_abs(0x4031)
    a.lda_abs(0x4030); a.b(0x29, 0x10); a.b(0x85, CRC_FLAG)
    a.rts()

    a.label("irq")                                  # one byte into BUF,X
    a.b(0x48)
    a.lda_abs(0x4031)
    a.b(0x9D, BUF & 0xFF, BUF >> 8)
    a.b(0xE8, 0x68, 0x40)                           # INX; PLA; RTI
    a.label("rti")
    a.b(0x40)
    a.label("disk_id")
    a.b(*INFO[0x0F:0x19])
    a.label("list_5")
    a.b(5, 0xFF)
    a.label("vectors")
    a.b(*bytes(10))                                 # filled in by main()
    return a


def vectors(a):
    rti, start, irq = a.labels["rti"], a.labels["start"], a.labels["irq"]
    return bytes([rti & 0xFF, rti >> 8] * 3 + [start & 0xFF, start >> 8, irq & 0xFF, irq >> 8])


def build():
    a = program(0)
    size = len(a.done())
    a = program(size)
    code = bytearray(a.done())
    assert len(code) == size
    vec = vectors(a)
    at = a.labels["vectors"] - 0x6100
    code[at:at + 10] = vec
    assert 0x6100 + len(code) <= 0x7000
    return bytes(code), vec


def main():
    code, vec = build()
    files = [
        (0, "PROGRAM", 0x6100, 0, code),
        (1, "VECTORS", 0xDFF6, 0, vec),
        (5, "DATA", 0x7000, 0, OLD),
    ]
    path = os.path.join(HERE, "fds_drive.fds")
    with open(path, "wb") as f:
        f.write(fds_image([side_bytes(INFO, files)]))
    print("wrote", path)


if __name__ == "__main__":
    main()
