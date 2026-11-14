#!/usr/bin/env python3
"""Write runtime/fds_bios.h: nesrecomp's own Famicom Disk System BIOS.
Run it again after changing it. recomp.py reads the same file.

Nintendo's BIOS can't be used, so this one is written from the nesdev
wiki's description ("FDS BIOS"), keeping its addresses where programs
depend on them: the vectors at $FFFA-$FFFF, the handlers the dispatch
reaches, and (as later steps add them) the documented routines. Every
byte not used holds $02, an opcode that stops a 6502: a program calling
a routine this BIOS doesn't have stops there, with a message naming the
address, instead of running into something else.

Reset (both power-on and the reset button):
  - the registers and their copies in zero page as the wiki lists them:
    $4023 = $00 then $83, $4025 = $2E ($FA), $4026 = $FF ($F9), $FB-$FD
    = 0, PPUCTRL $10 ($FF), PPUMASK copy $06 ($FE), the APU frame counter
    $C0, FDS sound $4080 = $80 and $408A = $E8;
  - $0100 = $C0 (NMIs to the program's third vector) and $0101 = $80;
  - a soft reset ($0102 = $35 and $0103 = $53 or $AC) sets $0103 = $53
    and goes to the program's reset vector, $DFFC;
  - otherwise the boot: the runtime loads every file of the disk whose
    ID is at most the disk's boot code (asked through $4028, a register
    the real hardware doesn't have). Then the BIOS waits for the next
    vblank, sets $0102 = $35, $0103 = $AC and goes to $DFFC.
    The wait stands in for the real BIOS's license check, which this one
    can't do (the text it compares is Nintendo's). A program whose boot
    files turn on NMIs gets its NMI (through $0100) before the reset
    vector, as on the real console, where that is how the license
    check is skipped. The wait is a delay loop of a little over a frame,
    not a poll of $2002, which could swallow that vblank's NMI.
NMI: $0100 bits 7-6: 00 the BIOS's own handler ($E19D, as VINTWait
uses it: turn NMIs off and return), 01 $DFF6, 10 $DFF8, 11 $DFFA.
IRQ: $0101 bits 7-6: 11 $DFFE, 10 acknowledge ($E1EF), 00 and 01 the
disk transfer handlers ($E1D9, $E1CE), which for now also only
acknowledge.
The file routines, at the wiki's addresses, with their pointers after
the JSR and their error number in A (Z set when 0):
  $E1F8 LoadFiles (Y = files loaded), $E237 AppendFile (LDA #$FF, then
  WriteFile), $E239 WriteFile, $E2B7 CheckFileCount, $E2BB
  AdjustFileCount, $E301 SetFileCount1, $E305 SetFileCount, $E32A
  GetDiskInfo.
Each stores A in $4029 and asks the runtime ($4028), which does the
work against the disk image at once (runtime/fds.c), moves the return
address past the pointers, and leaves A (and LoadFiles' Y) in $4029
and $402A. The lower-level routines they use on the real BIOS
(CheckDiskHeader, GetNumFiles, FileMatchTest, ...) aren't here: those
read the disk byte by byte.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from make_mmc1_test import Asm  # noqa: E402

SERVICE = 0x4028        # BIOS -> runtime requests (runtime/fds.c)
ARG = 0x4029            # a routine's A; after it, the result A
RESULT_Y = 0x402A       # after LoadFiles, Y
BOOT_LOAD = 1
# The file routines: (name, entry, request, gives Y), the requests as in
# runtime/fds.c.
ROUTINES = [("LoadFiles", 0xE1F8, 2, True), ("WriteFile", 0xE239, 3, False),
            ("CheckFileCount", 0xE2B7, 4, False), ("AdjustFileCount", 0xE2BB, 5, False),
            ("SetFileCount1", 0xE301, 6, False), ("SetFileCount", 0xE305, 7, False),
            ("GetDiskInfo", 0xE32A, 8, False)]
APPEND_FILE = 0xE237    # LDA #$FF, into WriteFile
STOP = 0x02             # a 6502 opcode that halts the CPU


def org(a, addr):
    """Fill with STOP up to addr."""
    assert a.pc() <= addr, "code at $%04X runs into $%04X" % (a.pc(), addr)
    while a.pc() < addr:
        a.b(STOP)


def jmp_ind(a, addr):
    a.b(0x6C, addr & 0xFF, addr >> 8)


def bios():
    a = Asm(0xE000)

    def w(addr, val):
        a.lda(val); a.sta(addr)

    def ack_rti():
        a.b(0x48); a.lda_abs(0x4030); a.b(0x68, 0x40)   # PHA; LDA $4030; PLA; RTI

    org(a, 0xE19D)                      # NMI 00: VINTWait's handler
    a.b(0x48)                           # PHA
    a.b(0xA5, 0xFF, 0x29, 0x7F, 0x85, 0xFF)     # LDA $FF; AND #$7F; STA $FF
    a.sta(0x2000)
    a.b(0x68, 0x40)                     # PLA; RTI
    org(a, 0xE1CE)                      # IRQ 01: disk byte transfer
    ack_rti()
    org(a, 0xE1D9)                      # IRQ 00: disk skip bytes
    ack_rti()
    org(a, 0xE1EF)                      # IRQ 10: acknowledge and delay
    ack_rti()

    for name, entry, _, _ in ROUTINES:
        if entry == 0xE239:
            org(a, APPEND_FILE)
            a.lda(0xFF)                     # AppendFile = WriteFile at $FF
        org(a, entry)
        a.b(0x4C); a.fix.append((len(a.code), name)); a.b(0, 0)
    org(a, 0xE600)
    for name, _, req, gives_y in ROUTINES:
        a.label(name)
        a.sta(ARG)
        w(SERVICE, req)
        if gives_y:
            a.b(0xAC, RESULT_Y & 0xFF, RESULT_Y >> 8)   # LDY $402A
        a.lda_abs(ARG)
        a.rts()

    org(a, 0xF000)
    a.label("reset")
    a.b(0x78, 0xD8)                     # SEI; CLD
    w(0x2000, 0x10); a.b(0x85, 0xFF)    # STA $FF
    w(0x2001, 0x00)
    a.lda(0x06); a.b(0x85, 0xFE)
    a.b(0xA2, 0xFF, 0x9A)               # LDX #$FF; TXS
    for _ in range(2):                  # the PPU warms up
        here = a.pc()
        a.b(0x2C, 0x02, 0x20, 0x10, (here - (a.pc() + 5)) & 0xFF)
    w(0x4023, 0x00); w(0x4023, 0x83)
    w(0x4025, 0x2E); a.b(0x85, 0xFA)
    w(0x4026, 0xFF); a.b(0x85, 0xF9)
    w(0x4017, 0xC0)
    a.lda(0x00); a.b(0x85, 0xFB, 0x85, 0xFC, 0x85, 0xFD)
    w(0x4080, 0x80); w(0x408A, 0xE8)
    w(0x0100, 0xC0); w(0x0101, 0x80)
    # Soft reset?
    a.lda_abs(0x0102); a.cmp(0x35); a.b(0xD0, 0)
    to_boot1 = len(a.code) - 1
    a.lda_abs(0x0103); a.cmp(0x53); a.b(0xF0, 0)
    to_soft = len(a.code) - 1
    a.cmp(0xAC); a.b(0xD0, 0)
    to_boot2 = len(a.code) - 1
    a.label("soft")
    w(0x0103, 0x53)
    a.b(0x4C); a.fix.append((len(a.code), "start")); a.b(0, 0)
    a.label("boot")
    w(SERVICE, BOOT_LOAD)
    # A little over a frame (24 * 256 * 5 cycles), so a vblank passes. Not
    # by polling $2002, which could swallow that vblank's NMI.
    a.b(0xA2, 24, 0xA0, 0x00)           # LDX #24; LDY #0
    here = a.pc()
    a.b(0x88, 0xD0, 0xFD)               # DEY; BNE
    a.b(0xCA, 0xD0, (here - (a.pc() + 3)) & 0xFF)   # DEX; BNE
    w(0x0102, 0x35); w(0x0103, 0xAC)
    a.label("start")
    a.b(0x58)                           # CLI
    jmp_ind(a, 0xDFFC)
    for pos, label in ((to_boot1, "boot"), (to_boot2, "boot"), (to_soft, "soft")):
        a.code[pos] = (a.labels[label] - (a.org + pos + 1)) & 0xFF

    a.label("nmi")
    a.b(0x2C, 0x00, 0x01)               # BIT $0100
    a.b(0x30, 8)                        # BMI high (skip the next 8 bytes)
    a.b(0x50, 3)                        # BVC mode 00
    jmp_ind(a, 0xDFF6)                  # 01
    a.b(0x4C, 0x9D, 0xE1)               # 00: JMP $E19D
    a.b(0x50, 3)                        # high: BVC 10
    jmp_ind(a, 0xDFFA)                  # 11
    jmp_ind(a, 0xDFF8)                  # 10

    a.label("irq")
    a.b(0x2C, 0x01, 0x01)               # BIT $0101
    a.b(0x30, 8)                        # BMI high
    a.b(0x50, 3)                        # BVC 00
    a.b(0x4C, 0xCE, 0xE1)               # 01: JMP $E1CE
    a.b(0x4C, 0xD9, 0xE1)               # 00: JMP $E1D9
    a.b(0x50, 3)                        # high: BVC 10
    jmp_ind(a, 0xDFFE)                  # 11
    a.b(0x4C, 0xEF, 0xE1)               # 10: JMP $E1EF

    org(a, 0xFFFA)
    for label in ("nmi", "reset", "irq"):
        t = a.labels[label]
        a.b(t & 0xFF, t >> 8)
    code = a.done()
    assert len(code) == 0x2000
    return code


def main():
    data = bios()
    lines = ["/* nesrecomp's own FDS BIOS, written by tools/make_fds_bios.py",
             "   (see there for what it does). Do not edit by hand. */",
             "static const unsigned char fds_bios[0x2000] = {"]
    for i in range(0, len(data), 16):
        lines.append("    " + ", ".join("0x%02X" % b for b in data[i:i + 16]) + ",")
    lines.append("};")
    path = os.path.join(ROOT, "runtime", "fds_bios.h")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    main()
