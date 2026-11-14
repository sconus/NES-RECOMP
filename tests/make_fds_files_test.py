#!/usr/bin/env python3
"""Write tests/fds_files.fds: a two-side Famicom Disk System test disk
made for nesrecomp, checking the BIOS's file routines (nesdev wiki "FDS
BIOS") and a side change. Run it again to regenerate it; the input
script tests/inputs/fds_files.txt takes the disk out and puts in side B.

Side A ("FIL", boot code 1), files in this order:
   0  ID 0   PRG $6100, the test program
   1  ID 1   PRG $DFF6, the vectors
   2  ID 5   PRG $7000, a routine: LDA #$55; RTS
   3  ID 6   PRG $7010, $66
   4  ID 5   PRG $7020, $57 (a second file with ID 5)
   5  ID 7   CHR $0100, 16 bytes $C0 + i
   6  ID 8   PRG $0150, $99 (below $0200: a dummy load)
   7  ID 8   PRG $0400, $44
   8  ID 9   PRG $FFF0, 32 bytes (past $FFFF: a dummy load)
   9  ID 1   PRG $7200, a routine: LDA #$11; RTS (a boot file)
  10  ID 10  PRG $7200, a routine: LDA #$AA; RTS
Side B (side number 1, boot code 0):
   0  ID 3   PRG $7300, a routine: LDA #$B3; RTS
Results through the blargg $6000 protocol:
   0  passed
   2  LoadFiles with IDs 5 and 6: not A = 0 and Y = 3, or the files
      aren't there (both ID 5 files, in disk order), or the CHR file
      came too
   4  LoadFiles, ID 7: the CHR file isn't at PPU $0100-$010F
   5  LoadFiles, ID 8 and 9: not Y = 3 (dummy loads count), or a dummy
      load wrote ($0150, or zero page, where the $FFF0 file would wrap
      round), or the $0400 file didn't
   6  code loaded over code: the routine at $7200 didn't change from
      $11 to $AA (it ran from its old translation)
   7  LoadFiles with the empty list: not the three boot files (Y = 3,
      the $7200 routine back to $11)
   8  the disk ID: a wrong licensee, game name, version or side doesn't
      give $04, $05, $06, $07 (with Z clear), or $FF bytes don't match
      anything
  10  GetDiskInfo: the disk ID, file count, the first file's ID and name
      or the disk size is wrong
  11  AppendFile from RAM: an error, the file count isn't 12, or the
      file doesn't load back
  12  AppendFile from VRAM (PPU $0100): the file doesn't load back
  13  WriteFile as file 11: the count isn't 12, the file after it
      (from check 12) still loads, or the new one doesn't
  14  CheckFileCount: 20 (more than 12) isn't error $31, or 12 is an
      error
  15  AdjustFileCount: 13 isn't error $31, or 1 doesn't hide file 11
  16  SetFileCount1 with 11 doesn't show file 11 again; SetFileCount
      with 11 doesn't leave a count of 11
  17  with the disk out ($4032 bit 0 set), LoadFiles isn't error $01
  18  side B: a side A disk ID isn't error $07, or side B's file doesn't
      load (its routine doesn't give $B3)
  19  WriteFile over side B's file 0 with new code (LDA #$5C), loaded
      again: the routine still gives $B3 (the new file kept the old
      one's translation)
While it waits for the side change it stays at $80 (still running):
$81 would make the runtime press reset.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402
from make_fds_test import disk_info, side_bytes, fds_image  # noqa: E402

LOAD_FILES, APPEND_FILE, WRITE_FILE = 0xE1F8, 0xE237, 0xE239
CHECK_COUNT, ADJUST_COUNT, SET_COUNT1, SET_COUNT, DISK_INFO = (
    0xE2B7, 0xE2BB, 0xE301, 0xE305, 0xE32A)
RES_A, RES_Y = 0x10, 0x11           # zero page: each call's A and Y
INFO = 0x0500                        # GetDiskInfo's output
SRC = 0x0600                         # data for AppendFile

SIDE_A = disk_info(name=b"FIL", side=0, boot_code=1)
SIDE_B = disk_info(name=b"FIL", side=1, boot_code=0)


def disk_id(info):
    return info[0x0F:0x19]


def side_a_files(code, vectors):
    return [
        (0, "PROGRAM", 0x6100, 0, code),
        (1, "VECTORS", 0xDFF6, 0, vectors),
        (5, "CODE5", 0x7000, 0, bytes([0xA9, 0x55, 0x60])),
        (6, "D6", 0x7010, 0, b"\x66"),
        (5, "D5", 0x7020, 0, b"\x57"),
        (7, "CHR", 0x0100, 1, bytes(0xC0 + i for i in range(16))),
        (8, "LOW", 0x0150, 0, b"\x99"),
        (8, "SYS", 0x0400, 0, b"\x44"),
        (9, "WRAP", 0xFFF0, 0, bytes([0xAB] * 32)),
        (1, "OLD", 0x7200, 0, bytes([0xA9, 0x11, 0x60])),
        (10, "NEW", 0x7200, 0, bytes([0xA9, 0xAA, 0x60])),
    ]


def program(disk_size):
    """The program; disk_size is what GetDiskInfo should give for side A
    (it depends on the program's own size, but not the other way)."""
    a = Asm(0x6100)

    def w(addr, val):
        a.lda(val); a.sta(addr)

    def jmp(label):
        a.b(0x4C); a.fix.append((len(a.code), label)); a.b(0, 0)

    def word(label):
        a.b(0, 0); a.fix.append((len(a.code) - 2, label))

    def call(entry, *ptrs, A=None):
        """JSR entry with pointers after it; keep A and Y in zero page."""
        if A is not None:
            a.lda(A)
        a.jsr(entry)
        for p in ptrs:
            word(p)
        a.b(0x85, RES_A, 0x84, RES_Y)               # STA RES_A; STY RES_Y

    def zp_is(addr, val, fail):
        a.b(0xA5, addr); a.cmp(val); a.bne(fail)

    def ok(fail):                                   # A was 0
        zp_is(RES_A, 0, fail)

    def count_is(n, fail):
        call(DISK_INFO, "info_out"); ok(fail)
        a.check(INFO + 10, n, fail)

    a.label("start")
    a.b(0x78, 0xD8)                                 # SEI; CLD
    w(0x2000, 0x00)
    w(0x6000, 0x80)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        w(0x6001 + i, v)
    # 2
    call(LOAD_FILES, "id_a", "list_56"); ok("f2"); zp_is(RES_Y, 3, "f2")
    a.jsr(0x7000); a.cmp(0x55); a.bne("f2")
    a.check(0x7010, 0x66, "f2"); a.check(0x7020, 0x57, "f2")
    a.lda(0x01); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.lda_abs(0x2007); a.lda_abs(0x2007); a.cmp(0x00); a.bne("f2")
    # 4
    call(LOAD_FILES, "id_a", "list_7"); ok("f4"); zp_is(RES_Y, 1, "f4")
    for at, v in ((0x0100, 0xC0), (0x010F, 0xCF)):
        a.lda(at >> 8); a.sta(0x2006); a.lda(at & 0xFF); a.sta(0x2006)
        a.lda_abs(0x2007); a.lda_abs(0x2007); a.cmp(v); a.bne("f4")
    # 5
    # Past $FFFF the file would wrap round into zero page.
    a.lda(0x00); a.b(0x85, 0x00, 0x85, 0x0F)        # STA $00; STA $0F
    call(LOAD_FILES, "id_a", "list_89"); ok("f5"); zp_is(RES_Y, 3, "f5")
    a.check(0x0400, 0x44, "f5"); a.check(0x0150, 0x00, "f5")
    zp_is(0x00, 0x00, "f5"); zp_is(0x0F, 0x00, "f5")
    # 6
    a.jsr(0x7200); a.cmp(0x11); a.bne("f6")
    call(LOAD_FILES, "id_a", "list_10"); ok("f6"); zp_is(RES_Y, 1, "f6")
    a.jsr(0x7200); a.cmp(0xAA); a.bne("f6")
    # 7
    call(LOAD_FILES, "id_a", "list_empty"); ok("f7"); zp_is(RES_Y, 3, "f7")
    a.jsr(0x7200); a.cmp(0x11); a.bne("f7")
    # 8
    for label, err in (("id_licensee", 0x04), ("id_name", 0x05),
                       ("id_version", 0x06), ("id_side_b", 0x07)):
        call(LOAD_FILES, label, "list_7")
        a.b(0xF0, 3); jmp("e8_%s" % label)          # BEQ: Z set is wrong
        jmp("f8")
        a.label("e8_%s" % label)
        zp_is(RES_A, err, "f8"); zp_is(RES_Y, 0, "f8")
    call(LOAD_FILES, "id_any", "list_7"); ok("f8"); zp_is(RES_Y, 1, "f8")
    # 10
    call(DISK_INFO, "info_out"); ok("f10")
    for i, v in enumerate(disk_id(SIDE_A)):
        a.check(INFO + i, v, "f10")
    a.check(INFO + 10, 11, "f10")
    a.check(INFO + 11, 0, "f10")                    # file 0's ID
    for i, ch in enumerate(b"PROGRAM "):
        a.check(INFO + 12 + i, ch, "f10")
    a.check(INFO + 11 + 9 * 11, disk_size >> 8, "f10")
    a.check(INFO + 12 + 9 * 11, disk_size & 0xFF, "f10")
    # 11
    for i in range(4):
        w(SRC + i, i + 1)
    call(APPEND_FILE, "id_a", "hdr_ram"); ok("f11")
    count_is(12, "f11")
    call(LOAD_FILES, "id_a", "list_20"); ok("f11"); zp_is(RES_Y, 1, "f11")
    for i in range(4):
        a.check(0x7400 + i, i + 1, "f11")
    # 12
    call(APPEND_FILE, "id_a", "hdr_vram"); ok("f12")
    call(LOAD_FILES, "id_a", "list_21"); ok("f12"); zp_is(RES_Y, 1, "f12")
    for i in range(4):
        a.check(0x7410 + i, 0xC0 + i, "f12")
    # 13
    for i in range(4):
        w(SRC + i, 0x70 + i)
    call(WRITE_FILE, "id_a", "hdr_write", A=11); ok("f13")
    count_is(12, "f13")
    call(LOAD_FILES, "id_a", "list_21"); ok("f13"); zp_is(RES_Y, 0, "f13")
    call(LOAD_FILES, "id_a", "list_22"); ok("f13"); zp_is(RES_Y, 1, "f13")
    a.check(0x7423, 0x73, "f13")
    # 14
    call(CHECK_COUNT, "id_a", A=20); zp_is(RES_A, 0x31, "f14")
    call(CHECK_COUNT, "id_a", A=12); ok("f14")
    count_is(12, "f14")
    # 15
    call(ADJUST_COUNT, "id_a", A=13); zp_is(RES_A, 0x31, "f15")
    call(ADJUST_COUNT, "id_a", A=1); ok("f15")
    count_is(11, "f15")
    call(LOAD_FILES, "id_a", "list_22"); ok("f15"); zp_is(RES_Y, 0, "f15")
    # 16
    call(SET_COUNT1, "id_a", A=11); ok("f16")
    call(LOAD_FILES, "id_a", "list_22"); ok("f16"); zp_is(RES_Y, 1, "f16")
    call(SET_COUNT, "id_a", A=11); ok("f16")
    count_is(11, "f16")
    # 17: the side change.
    a.label("wait_out")
    a.lda_abs(0x4032); a.b(0x29, 0x01)
    a.b(0xF0, (a.labels["wait_out"] - (a.pc() + 2)) & 0xFF)     # BEQ wait_out
    call(LOAD_FILES, "id_a", "list_7"); zp_is(RES_A, 0x01, "f17")
    a.label("wait_in")
    a.lda_abs(0x4032); a.b(0x29, 0x01)
    a.b(0xD0, (a.labels["wait_in"] - (a.pc() + 2)) & 0xFF)      # BNE wait_in
    # 18
    call(LOAD_FILES, "id_a", "list_3"); zp_is(RES_A, 0x07, "f18")
    call(LOAD_FILES, "id_b", "list_3"); ok("f18"); zp_is(RES_Y, 1, "f18")
    a.jsr(0x7300); a.cmp(0xB3); a.bne("f18")
    # 19
    for i, v in enumerate((0xA9, 0x5C, 0x60)):
        w(SRC + i, v)
    call(WRITE_FILE, "id_b", "hdr_code", A=0); ok("f19")
    call(LOAD_FILES, "id_b", "list_3"); ok("f19"); zp_is(RES_Y, 1, "f19")
    a.jsr(0x7300); a.cmp(0x5C); a.bne("f19")
    w(0x6000, 0x00)
    a.label("hang")
    jmp("hang")
    for n in list(range(2, 20)):
        a.label("f%d" % n)
        w(0x6000, n)
        jmp("hang")
    a.label("rti")
    a.b(0x40)

    def data(label, bytes_):
        a.label(label)
        a.b(*bytes_)

    ida = disk_id(SIDE_A)
    data("id_a", ida)
    data("id_b", disk_id(SIDE_B))
    data("id_licensee", bytes([0x99]) + ida[1:])
    data("id_name", ida[:1] + b"FIX" + ida[4:])
    data("id_version", ida[:5] + bytes([7]) + ida[6:])
    data("id_side_b", ida[:6] + bytes([1]) + ida[7:])
    data("id_any", bytes([0xFF] * 10))
    data("list_56", [5, 6, 0xFF])
    data("list_7", [7, 0xFF])
    data("list_89", [8, 9, 0xFF])
    data("list_10", [10, 0xFF])
    data("list_empty", [0xFF])
    data("list_20", [20, 0xFF])
    data("list_21", [21, 0xFF])
    data("list_22", [22, 0xFF])
    data("list_3", [3, 0xFF])

    def header(label, fid, name, addr, size, src, vram):
        data(label, bytes([fid]) + name.ljust(8)[:8] +
             bytes([addr & 0xFF, addr >> 8, size & 0xFF, size >> 8, 0,
                    src & 0xFF, src >> 8, vram]))

    header("hdr_ram", 20, b"SAVE", 0x7400, 4, SRC, 0)
    header("hdr_vram", 21, b"VRAM", 0x7410, 4, 0x0100, 1)
    header("hdr_write", 22, b"WRITE", 0x7420, 4, SRC, 0)
    header("hdr_code", 3, b"NEWB", 0x7300, 3, SRC, 0)
    a.labels["info_out"] = INFO
    return a


def vectors(a):
    rti, start = a.labels["rti"], a.labels["start"]
    return bytes([rti & 0xFF, rti >> 8] * 3 + [start & 0xFF, start >> 8, rti & 0xFF, rti >> 8])


def main():
    a = program(0)
    code = a.done()
    size = sum(len(f[4]) + 261 for f in side_a_files(code, vectors(a)))
    a = program(size)
    code = a.done()
    assert sum(len(f[4]) + 261 for f in side_a_files(code, vectors(a))) == size
    assert 0x6100 + len(code) <= 0x7000
    path = os.path.join(HERE, "fds_files.fds")
    side_a = side_bytes(SIDE_A, side_a_files(code, vectors(a)))
    side_b = side_bytes(SIDE_B, [(3, "SIDEB", 0x7300, 0, bytes([0xA9, 0xB3, 0x60]))])
    with open(path, "wb") as f:
        f.write(fds_image([side_a, side_b]))
    print("wrote", path)
    script = os.path.join(HERE, "inputs", "fds_files.txt")
    with open(script, "w") as f:
        f.write("# tests/fds_files.fds (make_fds_files_test.py): take the disk out,\n"
                "# then put in side B.\n120 disk=eject\n150 disk=2\n")
    print("wrote", script)


if __name__ == "__main__":
    main()
