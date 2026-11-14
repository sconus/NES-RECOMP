#!/usr/bin/env python3
"""Write tests/fds_code.fds: a Famicom Disk System test disk made for
nesrecomp, checking that code in RAM which changes never runs from its
old translation (PLAN-fds.md step 3): the program rewrites its own code
in several ways, and two boot files overlap. Run it again to regenerate
it.

One side, boot code 2, files in this order (the recompiler numbers them
4, 5, 6, 7):
   0  ID 1  PRG $6100, the test program and the routines it rewrites
   1  ID 1  PRG $8000, more routines ("B")
   2  ID 2  PRG $8040, loaded over part of B ("C")
   3  ID 1  PRG $DFF6, the vectors
Results through the blargg $6000 protocol:
   0  passed
   2  B's routine at $8020 jumps to $8040, which C replaced: it ran B's
      old code there ($22) instead of C's ($33)
   3  a call to $8040 ran B's code instead of C's
   4  an operand rewritten ($6801, LDA #$11 -> #$5A): the old value
   5  an instruction that rewrites the next one's operand, while
      running: the next one used the old operand
   6  a JMP whose target was rewritten (the low byte of one, the high
      byte of another) went to the old target
   7  a routine replaced by a copy of other code (new opcodes): the
      old routine ran
   8  a write of the value already there changed what the code does
   9  an operand changed and changed back: the wrong value
  10  code at $8000-$DFFF rewritten (LDA #$44 -> #$45): the old value
  11  a routine reached through JMP ($0010), its opcode changed (LDA
      -> LDX): the old instruction ran

It also writes two FDS NSFs, whose code at $8000-$DFFF is in RAM too:
tests/fds_nsf_code.nsf (no bank switching):
   2  an operand at $9001 rewritten (LDA #$11 -> #$5A): the old value
   3  an instruction that rewrites the next one's operand, while
      running: the old operand
   4  a JMP whose target was rewritten went to the old target
tests/fds_nsf_code_banks.nsf (4 KB banks; $9000 holds bank 1, LDA #$11,
or bank 2, LDA #$22):
   2  an operand at $9001 rewritten: the old value
   3  $5FF9 = 2: bank 2's code didn't run
   4  $5FF9 = 1 again: a fresh copy of bank 1, so its code as on the
      disk ($11), not as rewritten
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402
from make_fds_test import disk_info, side_bytes, fds_image  # noqa: E402
from make_fds_sound_test import nsf_header, finish, signature  # noqa: E402


def pad(a, addr):
    assert a.pc() <= addr, "code at $%04X runs into $%04X" % (a.pc(), addr)
    while a.pc() < addr:
        a.b(0x00)


def program():
    a = Asm(0x6100)

    def w(addr, val):
        a.lda(val); a.sta(addr)

    def jmp(label):
        a.b(0x4C); a.fix.append((len(a.code), label)); a.b(0, 0)

    def call(addr, want, fail):
        a.jsr(addr); a.cmp(want); a.bne(fail)

    a.label("start")
    a.b(0x78, 0xD8)                             # SEI; CLD
    w(0x2000, 0x00)
    w(0x6000, 0x80)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        w(0x6001 + i, v)
    # 2, 3: C over B.
    call(0x8020, 0x33, "f2")
    call(0x8040, 0x33, "f3")
    # 4: an operand.
    call(0x6800, 0x11, "f4")
    w(0x6801, 0x5A)
    call(0x6800, 0x5A, "f4")
    # 9: and back.
    w(0x6801, 0x11)
    call(0x6800, 0x11, "f9")
    # 5: rewriting the next instruction while running, twice.
    call(0x6810, 0x77, "f5")
    call(0x6810, 0x77, "f5")
    a.check(0x6816, 0x77, "f5")
    # 6: a JMP's target.
    call(0x6820, 0x01, "f6")
    w(0x6821, 0x26)
    call(0x6820, 0x02, "f6")
    call(0x6830, 0x04, "f6")
    w(0x6832, 0x69)
    call(0x6830, 0x05, "f6")
    # 7: a whole routine, copied over.
    call(0x6840, 0x11, "f7")
    a.b(0xA2, 3)                                # LDX #3
    a.label("copy")
    a.b(0xBD, 0, 0); a.fix.append((len(a.code) - 2, "newcode"))   # LDA newcode,X
    a.b(0x9D, 0x40, 0x68)                       # STA $6840,X
    a.b(0xCA)                                   # DEX
    a.b(0x10, (a.labels["copy"] - (a.pc() + 2)) & 0xFF)           # BPL copy
    call(0x6840, 0x80, "f7")
    # 8: the same value.
    w(0x6861, 0x99)
    call(0x6860, 0x99, "f8")
    # 10: $8000-$DFFF.
    call(0x8080, 0x44, "f10")
    w(0x8081, 0x45)
    call(0x8080, 0x45, "f10")
    # 11: through JMP ($0010), then the opcode changed.
    w(0x0010, 0x80); w(0x0011, 0x68)
    a.lda(0x00)
    call(0x68A0, 0x12, "f11")
    w(0x6880, 0xA2)                             # LDA #$12 -> LDX #$12
    a.lda(0x00); a.b(0xA2, 0x00)                # LDA #0; LDX #0
    a.jsr(0x68A0)
    a.cmp(0x00); a.bne("f11")
    a.b(0x8E, 0x20, 0x00)                       # STX $0020
    a.check(0x0020, 0x12, "f11")
    w(0x6000, 0x00)
    a.label("hang")
    jmp("hang")
    for n in range(2, 12):
        a.label("f%d" % n)
        w(0x6000, n)
        jmp("hang")
    a.label("rti")
    a.b(0x40)
    a.label("newcode")
    a.b(0xA9, 0x40, 0x0A, 0x60)                 # LDA #$40; ASL A; RTS

    pad(a, 0x6800)
    a.b(0xA9, 0x11, 0x60)                       # $6800 LDA #$11; RTS
    pad(a, 0x6810)
    a.b(0xA9, 0x77, 0x8D, 0x16, 0x68)           # $6810 LDA #$77; STA $6816
    a.b(0xA9, 0x00, 0x60)                       # $6815 LDA #$00; RTS
    pad(a, 0x6820)
    a.b(0x4C, 0x23, 0x68)                       # $6820 JMP $6823
    a.b(0xA9, 0x01, 0x60)                       # $6823 LDA #1; RTS
    a.b(0xA9, 0x02, 0x60)                       # $6826 LDA #2; RTS
    pad(a, 0x6830)
    a.b(0x4C, 0x33, 0x68)                       # $6830 JMP $6833
    a.b(0xA9, 0x04, 0x60)                       # $6833 LDA #4; RTS
    pad(a, 0x6840)
    a.b(0xA9, 0x10, 0x18, 0x69, 0x01, 0x60)     # $6840 LDA #$10; CLC; ADC #1; RTS
    pad(a, 0x6860)
    a.b(0xA9, 0x99, 0x60)                       # $6860 LDA #$99; RTS
    pad(a, 0x6880)
    a.b(0xA9, 0x12, 0x60)                       # $6880 LDA #$12; RTS
    pad(a, 0x68A0)
    a.b(0x6C, 0x10, 0x00)                       # $68A0 JMP ($0010)
    pad(a, 0x6933)
    a.b(0xA9, 0x05, 0x60)                       # $6933 LDA #5; RTS
    code = a.done()
    vectors = bytes([a.labels["rti"] & 0xFF, a.labels["rti"] >> 8] * 3 +
                    [a.labels["start"] & 0xFF, a.labels["start"] >> 8,
                     a.labels["rti"] & 0xFF, a.labels["rti"] >> 8])
    return code, vectors


def file_b():
    b = bytearray(0x100)
    b[0x20:0x23] = bytes([0x4C, 0x40, 0x80])     # $8020 JMP $8040
    b[0x40:0x43] = bytes([0xA9, 0x22, 0x60])     # $8040 LDA #$22; RTS
    b[0x80:0x83] = bytes([0xA9, 0x44, 0x60])     # $8080 LDA #$44; RTS
    return bytes(b)


def code_disk():
    code, vectors = program()
    files = [
        (1, "PROGRAM", 0x6100, 0, code),
        (1, "B", 0x8000, 0, file_b()),
        (2, "C", 0x8040, 0, bytes([0xA9, 0x33, 0x60])),     # LDA #$33; RTS
        (1, "VECTORS", 0xDFF6, 0, vectors),
    ]
    return fds_image([side_bytes(disk_info(boot_code=2), files)])


def nsf_code(path):
    a = Asm(0x8000)

    def call(addr, want, fail):
        a.jsr(addr); a.cmp(want); a.bne(fail)

    a.label("init")
    signature(a)
    call(0x9000, 0x11, "f2")
    a.lda(0x5A); a.sta(0x9001)
    call(0x9000, 0x5A, "f2")
    call(0x9010, 0x77, "f3")
    call(0x9010, 0x77, "f3")
    call(0x9020, 0x01, "f4")
    a.lda(0x26); a.sta(0x9021)
    call(0x9020, 0x02, "f4")
    a.b(0x4C); a.fix.append((len(a.code), "pass")); a.b(0, 0)
    finish(a, 4)
    pad(a, 0x9000)
    a.b(0xA9, 0x11, 0x60)                       # $9000 LDA #$11; RTS
    pad(a, 0x9010)
    a.b(0xA9, 0x77, 0x8D, 0x16, 0x90)           # $9010 LDA #$77; STA $9016
    a.b(0xA9, 0x00, 0x60)                       # $9015 LDA #$00; RTS
    pad(a, 0x9020)
    a.b(0x4C, 0x23, 0x90)                       # $9020 JMP $9023
    a.b(0xA9, 0x01, 0x60, 0xA9, 0x02, 0x60)     # $9023, $9026
    code = a.done()
    with open(path, "wb") as f:
        f.write(nsf_header("fds_nsf_code.nsf", 0x8000, a.labels["init"],
                           a.labels["play"]) + code)
    print("wrote", path)


def nsf_code_banks(path):
    a = Asm(0x8000)

    def call(addr, want, fail):
        a.jsr(addr); a.cmp(want); a.bne(fail)

    a.label("init")
    signature(a)
    call(0x9000, 0x11, "f2")
    a.lda(0x5A); a.sta(0x9001)
    call(0x9000, 0x5A, "f2")
    a.lda(2); a.sta(0x5FF9)
    call(0x9000, 0x22, "f3")
    a.lda(1); a.sta(0x5FF9)
    call(0x9000, 0x11, "f4")
    a.b(0x4C); a.fix.append((len(a.code), "pass")); a.b(0, 0)
    finish(a, 4)
    code = a.done()
    data = bytearray(4 * 0x1000)
    data[:len(code)] = code
    data[0x1000:0x1003] = bytes([0xA9, 0x11, 0x60])     # bank 1: LDA #$11; RTS
    data[0x2000:0x2003] = bytes([0xA9, 0x22, 0x60])     # bank 2: LDA #$22; RTS
    with open(path, "wb") as f:
        f.write(nsf_header("fds_nsf_code_banks.nsf", 0x8000, a.labels["init"],
                           a.labels["play"], [0, 1, 3, 3, 3, 3, 3, 3]) + data)
    print("wrote", path)


def main():
    path = os.path.join(HERE, "fds_code.fds")
    with open(path, "wb") as f:
        f.write(code_disk())
    print("wrote", path)
    nsf_code(os.path.join(HERE, "fds_nsf_code.nsf"))
    nsf_code_banks(os.path.join(HERE, "fds_nsf_code_banks.nsf"))


if __name__ == "__main__":
    main()
