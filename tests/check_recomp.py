#!/usr/bin/env python3
"""Check the recompiler in C (build/nesrecomp-recomp, PLAN-standalone.md
step 2) against recomp.py, the reference. Run by `make test-recomp`.
Step 2a, reading the file (--dump-rom, which prints everything read and
the entry points, from both):
  1. every ROM, NSF and disk image under tests/ (the test ROM clone and
     the project's own), read alone and with its .missed file: the two
     dumps are the same, line for line;
  2. files made here for the cases the collection lacks: a trainer, an
     old dump's junk in bytes 12-15, NES 2.0 fields and its exponent
     sizes, an NES 2.0 header claiming more than the file holds, a 512
     KB MMC1, MMC1 submapper 5, disk images with and without a header,
     two sides, more than 252 files, files reaching past $6000-$DFFF,
     NSFs banked, at $6000 and too long, and a program using every
     opcode with the operands at the C writer's edges ($4018-$4020,
     $5100-$5118, $8000, page crossings, branches of +127 and -128) as
     NROM and MMC1, and its writing opcodes as MMC5: the same dumps;
  3. files recomp.py refuses: the same message and exit status;
  4. entry points from --entry and from .missed files in both formats,
     with spaces, blank lines and banks past the last: the same.
Step 2b, the C they write:
  5. every file under tests/, alone and with its .missed, and nestest as
     `make test` recompiles it, and the files made in 2.: the same C, byte
     for byte, and the same printed lines (the path written to aside);
  6. how long each takes for all of them (printed; not a check).
Step 3, who uses it:
  7. `make game`, `make test` (nestest) and the test suite recompile with
     build/nesrecomp-recomp, not recomp.py: what make would run, and one
     suite test run with a python3 first on PATH that only fails.
Step 8, the listing (--listing FILE, the C version only):
  8. every file of 5. (alone, with its .missed, and those made here):
     the C is byte for byte the same with --listing as without; the
     listing has a line for each instruction translated (as many as the
     "translated N instructions" line says); each instruction's lines in
     the .c start with its label and its EVENT_CHECK, and end where the
     next instruction's label (or the end of recomp_run) begins;
  9. nestest's listing (as `make test` recompiles it) against
     tests/nestest.log, an independent listing of the same program: for
     every address both have, the same bytes and the same 6502 text (up
     to the log's " = " or " @ ", where it shows memory).
Exit status 0 when all pass.
"""
import os
import struct
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
C = os.path.join(ROOT, "build", "nesrecomp-recomp")
PY = os.path.join(ROOT, "recomp.py")
OUT = os.path.join(ROOT, "build", "recomp_check")

fails = []


def check(name, ok, why=""):
    print("%s  %s%s" % ("ok   " if ok else "FAIL ", name, "" if ok else ": " + why))
    if not ok:
        fails.append(name)


def both(args):
    """(status, stdout, stderr) of recomp.py and of the C version."""
    rp = subprocess.run(["python3", PY] + args, capture_output=True, text=True, timeout=120)
    rc = subprocess.run([C] + args, capture_output=True, text=True, timeout=120)
    return (rp.returncode, rp.stdout, rp.stderr), (rc.returncode, rc.stdout, rc.stderr)


def first_difference(a, b):
    la, lb = a.splitlines(), b.splitlines()
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else "(nothing)"
        y = lb[i] if i < len(lb) else "(nothing)"
        if x != y:
            return "line %d: recomp.py %r, C %r" % (i + 1, x[:70], y[:70])
    return "same lines"


def same_dump(args):
    """None if both read it the same and succeed, else why not."""
    p, c = both(args + ["--dump-rom"])
    if p[0] != 0:
        return "recomp.py failed: %s" % p[2].strip()[-80:]
    if c != p:
        if c[0] != p[0]:
            return "C exit %d: %s" % (c[0], c[2].strip()[-80:])
        return first_difference(p[1] + p[2], c[1] + c[2])
    return None


def same_c(args, tag):
    """None if both write the same C and print the same lines, else why
    not. Also the seconds each took."""
    outs = [os.path.join(OUT, "c", "%s.%s.c" % (tag, w)) for w in ("py", "c")]
    res, took = [], []
    for cmd, o in ((["python3", PY], outs[0]), ([C], outs[1])):
        if os.path.exists(o):
            os.remove(o)
        t0 = time.time()
        r = subprocess.run(cmd + args + ["-o", o], capture_output=True, text=True, timeout=300)
        took.append(time.time() - t0)
        text = open(o, "rb").read() if os.path.exists(o) else None
        res.append((r.returncode, r.stdout.replace(o, "OUT"), r.stderr, text))
    p, c = res
    for o in outs:
        if os.path.exists(o):
            os.remove(o)
    if p[0] != 0:
        return "recomp.py failed: %s" % p[2].strip()[-80:], took
    if c[0] != 0:
        return "C exit %d: %s" % (c[0], c[2].strip()[-80:]), took
    if c[3] != p[3]:
        a, b = p[3].decode(errors="replace"), (c[3] or b"").decode(errors="replace")
        return "the C differs, " + first_difference(a, b), took
    if c[1:3] != p[1:3]:
        return "printed lines differ, " + first_difference(p[1] + p[2], c[1] + c[2]), took
    return None, took


def listing_ok(args, tag):
    """None if --listing leaves the C alone and lists every instruction
    where it is in the .c, else why not."""
    d = os.path.join(OUT, "lst")
    plain, with_l, lst = (os.path.join(d, "%s.%s" % (tag, x)) for x in ("plain.c", "l.c", "lst"))
    r1 = subprocess.run([C] + args + ["-o", plain], capture_output=True, text=True, timeout=120)
    r2 = subprocess.run([C] + args + ["-o", with_l, "--listing", lst], capture_output=True, text=True,
                        timeout=120)
    try:
        if r1.returncode or r2.returncode:
            return "exit %d / %d: %s" % (r1.returncode, r2.returncode, (r2.stderr or r1.stderr).strip()[-80:])
        a, b = open(plain, "rb").read(), open(with_l, "rb").read()
        if a != b:
            return "the C differs with --listing, " + first_difference(a.decode(errors="replace"),
                                                                      b.decode(errors="replace"))
        lines = b.decode(errors="replace").split("\n")
        rows = [l.split("\t") for l in open(lst).read().splitlines() if not l.startswith("#")]
        import re as _re
        m = _re.search(r"translated (\d+) instructions", r2.stdout)
        if not m or int(m.group(1)) != len(rows):
            return "%d listed, the recompiler said %s" % (len(rows), m and m.group(1))
        for row in rows:
            loc, first, last = row[0], int(row[1]), int(row[2])
            bank, addr = loc.split(":")
            label = "L_%s_%s:" % (bank, addr)
            if not (1 <= first <= last < len(lines)):
                return "%s: lines %d-%d" % (loc, first, last)
            if not lines[first - 1].startswith(label) or "EVENT_CHECK(0x%s)" % addr not in lines[first - 1]:
                return "%s: line %d is %r" % (loc, first, lines[first - 1][:50])
            if any(l.startswith("L_") for l in lines[first:last]):
                return "%s: lines %d-%d hold another label" % (loc, first, last)
            after = lines[last]
            if not (after.startswith("L_") or after == "}"):
                return "%s: line %d after it is %r" % (loc, last + 1, after[:50])
        return None
    finally:
        for f in (plain, with_l, lst):
            if os.path.exists(f):
                os.remove(f)


# --- files made here ------------------------------------------------------

def ines(prg16, chr8, b6=0, b7=0, rest=b"\0" * 8, prg=None, size=None, trainer=False):
    """An iNES file: a header from its fields, then PRG (patterned, so
    banks differ, with vectors) and CHR."""
    h = bytes([0x4E, 0x45, 0x53, 0x1A, prg16 & 0xFF, chr8 & 0xFF, b6, b7]) + rest
    n = prg16 * 0x4000 if size is None else size
    if prg is None:
        prg = bytearray((i * 7 + (i >> 13)) & 0xFF for i in range(n))
        if n >= 6:
            prg[n - 6:] = bytes([0x00, 0x80, 0x00, 0x80, 0x00, 0x80])
    return h + (bytes(512) if trainer else b"") + bytes(prg) + bytes(chr8 * 0x2000)


def nes2(prg_lsb, chr_lsb, mapper, sub=0, b9=0, b10=0, b11=0, b12=0, b13=0, b14=0, b15=0,
         b6=0, console=0, size=None, chr_size=0, battery=False):
    h = bytes([0x4E, 0x45, 0x53, 0x1A, prg_lsb, chr_lsb,
               (mapper & 0x0F) << 4 | b6 | (2 if battery else 0),
               (mapper & 0xF0) | 0x08 | console,
               (mapper >> 8) | sub << 4, b9, b10, b11, b12, b13, b14, b15])
    prg = bytearray((i * 5 + (i >> 13)) & 0xFF for i in range(size))
    prg[size - 6:] = bytes([0x10, 0x80, 0x20, 0x80, 0x30, 0x80])
    return h + bytes(prg) + bytes(chr_size)


def fds_file(number, fid, addr, data, ftype=0):
    head = bytes([3, number, fid]) + b"FILENAME" + struct.pack("<HH", addr, len(data)) + bytes([ftype])
    return head + bytes([4]) + bytes(data)


def fds_side(files, boot_id=0, count=None):
    s = bytearray(65500)
    s[0] = 1
    s[1:15] = b"*NINTENDO-HVC*"
    s[0x19] = boot_id
    s[56], s[57] = 2, len(files) if count is None else count
    at = 58
    for f in files:
        s[at:at + len(f)] = f
        at += len(f)
    return bytes(s)


def code(addr, n):
    return bytes(((addr + i) * 3) & 0xFF for i in range(n))


def nsf(load, init, play, body, banks=None, chips=0):
    h = bytearray(0x80)
    h[0:5] = b"NESM\x1a"
    h[5], h[6], h[7] = 1, 1, 1
    struct.pack_into("<HHH", h, 8, load, init, play)
    if banks:
        h[0x70:0x78] = bytes(banks)
    h[0x7B] = chips
    return bytes(h) + bytes(body)


def made_good():
    vec = bytes([0x00, 0x60, 0x10, 0x60, 0x20, 0x60])
    boot = fds_file(0, 0, 0x6000, code(0x6000, 0x300)) + fds_file(1, 1, 0xDFF6, bytes(4) + vec)
    many = [fds_file(i, 9, 0x6000, b"") for i in range(200)]
    # Tags count every file from 4: the 252nd file is tag 255, the last
    # translated, and the next, tag 256, isn't.
    late = [fds_file(i, 9, 0x7000, b"") for i in range(51)] + [
        fds_file(51, 9, 0x8000, code(0x8000, 64)), fds_file(52, 9, 0x9000, code(0x9000, 64))]
    return {
        "trainer.nes": ines(2, 1, b6=0x04, trainer=True),
        "diskdude.nes": ines(2, 1, b6=0x40, b7=0x40, rest=b"DiskDude!"[1:]),
        "junk_mapper.nes": ines(2, 0, b6=0x10, b7=0x30, rest=bytes([0, 0, 0, 0, 0, 0, 0, 7])),
        "battery_chrram.nes": ines(2, 0, b6=0x02),
        "nes2_mmc3_fields.nes": nes2(4, 0, 4, sub=2, b10=0x75, b11=0x07, b12=1, b14=2, b15=0x2A,
                                     size=0x10000, battery=True),
        "nes2_vs.nes": nes2(2, 0, 0, b13=0x35, console=1, size=0x8000),
        "nes2_playchoice.nes": nes2(2, 0, 0, b13=0x47, console=2, size=0x8000),
        "nes2_ext.nes": nes2(2, 0, 0, b13=0x0B, console=3, size=0x8000),
        "nes2_exp_8k.nes": nes2(13 << 2, 0, 0, b9=0x0F, size=0x2000),
        "nes2_exp_24k.nes": nes2(13 << 2 | 1, 0, 0, b9=0x0F, size=0x6000),
        "nes2_msb.nes": nes2(0, 0, 1, b9=0x01, size=0x400000),
        # NES 2.0's sizes say 4 MB, more than the file: read as iNES 1.0
        "nes2_claims_more.nes": ines(2, 0, b7=0x08, rest=bytes([0, 0x01, 0, 0, 0, 0, 0, 0])),
        "nes2_vrc7.nes": nes2(2, 0, 85, size=0x8000),
        "mmc1_512k.nes": ines(32, 0, b6=0x10),
        "mmc1_256k.nes": ines(16, 0, b6=0x10),
        "mmc1_serom.nes": nes2(2, 0, 1, sub=5, size=0x8000),
        "mmc5.nes": ines(8, 1, b6=0x50),
        "vrc4_25.nes": ines(8, 1, b6=0x90, b7=0x10),
        "action53.nes": ines(16, 0, b6=0xC0, b7=0x10),
        "bnrom.nes": ines(4, 0, b6=0x20, b7=0x20),
        "mmc2.nes": ines(8, 2, b6=0x90),
        "nrom_8k.nes": nes2(13 << 2, 0, 0, b9=0x0F, size=0x2000),
        "fds_header.fds": b"FDS\x1a\x01" + bytes(11) + fds_side([boot], boot_id=1),
        "fds_bare.fds": fds_side([boot], boot_id=1),
        "fds_two_sides.fds": b"FDS\x1a\x02" + bytes(11) + fds_side([boot], boot_id=1)
        + fds_side([fds_file(0, 0, 0x9000, code(0x9000, 100)), fds_file(1, 1, 0xA000, code(0xA000, 10), 1)]),
        "fds_edges.fds": fds_side([fds_file(0, 0, 0x5F00, code(0x5F00, 0x200)),
                                   fds_file(1, 0, 0xDF00, code(0xDF00, 0x200)),
                                   fds_file(2, 5, 0x7000, code(0x7000, 0x40))] , boot_id=1),
        "fds_many.fds": fds_side(many, boot_id=0) + fds_side(late),
        "fds_count_short.fds": fds_side([boot], boot_id=1, count=5),
        "fds_partial_side.fds": b"FDS\x1a\x01" + bytes(11) + fds_side([boot], boot_id=1) + bytes(1000),
        "nsf_8000.nsf": nsf(0x8000, 0x8000, 0x8003, code(0x8000, 0x2000)),
        "nsf_c123.nsf": nsf(0xC123, 0xC123, 0xC200, code(0xC123, 0x1000)),
        "nsf_too_long.nsf": nsf(0xC000, 0xC000, 0xC003, code(0xC000, 0x9000)),
        "nsf_fds_6000.nsf": nsf(0x6000, 0x6000, 0x8000, code(0x6000, 0x4000), chips=4),
        "nsf_fds_banked.nsf": nsf(0x8000, 0x8000, 0x8003, code(0x8000, 0x3000), banks=[0, 1, 2, 0, 1, 2, 0, 1], chips=4),
        "nsf_banked_off.nsf": nsf(0x8345, 0x8345, 0x9000, code(0x8345, 0x5000), banks=[0, 1, 2, 3, 4, 5, 9, 2]),
        "nsf_banked_wrap.nsf": nsf(0x8000, 0x8000, 0x8003, code(0x8000, 0x2000), banks=[7, 0, 0, 0, 0, 0, 0, 1], chips=1),
        "nsf_chips_vrc6.nsf": nsf(0x8000, 0x8000, 0x8003, code(0x8000, 0x8000), chips=1),
        "every_opcode_nrom.nes": made_every_opcode(0x00, 0x00, 2),
        "every_opcode_mmc1.nes": made_every_opcode(0x10, 0x00, 8),
        "every_store_mmc5.nes": made_every_opcode(0x50, 0x00, 8, writes_only=True),
    }


# Operands to try for each addressing mode: the edges of what the C
# writer decides on (I/O at $2000-$401F, mapper writes from $8000 or a
# mapper's low registers, page crossings, zero-page wrap).
MODE_OPERANDS = {
    "imm": [[0x80]], "zp": [[0x10], [0xFF]], "zpx": [[0xFF]], "zpy": [[0xFF]],
    "izx": [[0xFF]], "izy": [[0x10], [0xFF]],
    "abs": [[0x00, 0x03], [0xFF, 0x1F], [0x02, 0x20], [0x18, 0x40], [0x1F, 0x40], [0x20, 0x40],
            [0x10, 0x51], [0x17, 0x51], [0x18, 0x51], [0x00, 0x80], [0xFF, 0x7F]],
    "abx": [[0x00, 0x02], [0x01, 0x1F], [0x19, 0x40], [0x20, 0x40], [0x01, 0x50], [0x18, 0x51],
            [0x01, 0x7F], [0x00, 0x80]],
    "aby": [[0x00, 0x02], [0x01, 0x1F], [0x19, 0x40], [0x20, 0x40], [0x01, 0x50], [0x01, 0x7F]],
    "ind": [[0xFF, 0x12], [0x00, 0x03]],
}


def made_every_opcode(b6, b7, prg16, writes_only=False):
    """A program using every opcode of recomp.py's table, each with the
    operands above, in blocks the tracer reaches: main calls each block
    (JSR), and each ends with RTS. Branches go nowhere special (0), a page
    away, +127 and -128. Opcodes that end a block (JMP, RTS, RTI, BRK)
    are blocks of their own. writes_only: only the opcodes that write
    memory (for MMC5, whose program must fit in 8 KB)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("recomp_ref", PY)
    ref = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ref)
    blocks = []
    for opc in sorted(ref.OPS):
        mnem, mode, _, _ = ref.OPS[opc]
        writes = mnem in ref.STORES or mnem in ref.RMW or mnem in ref.HIGH_STORES
        if writes_only and (not writes or mode in ("acc", "imp")):
            continue
        if mode == "rel":
            for off in (0x00, 0x7F, 0x80, 0x40):
                blocks.append(bytes([opc, off, 0x60]))
        elif mnem == "JSR":
            blocks.append(bytes([opc, 0x00, 0x80, 0x60]))           # calls main's start
        elif mode in ("imp", "acc"):
            blocks.append(bytes([opc]) + (b"" if mnem in ("RTS", "RTI", "BRK") else b"\x60"))
        else:
            for operand in MODE_OPERANDS[mode]:
                end = b"" if mnem == "JMP" else b"\x60"
                blocks.append(bytes([opc] + operand) + end)
    # The program as the CPU sees it at $8000-$FFFF at power-on...
    image = bytearray([0xEA] * 0x8000)
    main = 0x8000
    at = 0x8000 + 3 * len(blocks) + 3 + 0x40
    calls = bytearray()
    for blk in blocks:
        if (at & 0xFF) > 0xF0:                   # a page away for some branches
            at += 0x20
        calls += bytes([0x20, at & 0xFF, at >> 8])
        image[at - 0x8000:at - 0x8000 + len(blk)] = blk
        at += len(blk) + 3
    calls += bytes([0x4C, main & 0xFF, main >> 8])
    image[0:len(calls)] = calls
    end = at - 0x8000
    # ...placed in the banks the mapper has there at power-on (8 KB
    # slots): NROM's 32 KB as it is; MMC1's first two banks and last two;
    # MMC5's last bank in every slot, so the program must fit in 8 KB.
    n8 = prg16 * 2
    slots = {0x00: [0, 1, 2, 3], 0x10: [0, 1, n8 - 2, n8 - 1], 0x50: [n8 - 1] * 4}[b6]
    if b6 == 0x50:
        assert end < 0x1FFA, "the program doesn't fit in 8 KB"
        image[0x1FFA:0x2000] = bytes([0x00, 0x80, 0x00, 0x80, 0x00, 0x80])
        image[0x2000:] = image[0:0x2000] * 3
    assert end < 0x7FFA, "the program doesn't fit"
    image[0x7FFA:] = bytes([0x00, 0x80, 0x00, 0x80, 0x00, 0x80])
    prg = bytearray([0xEA] * (n8 * 0x2000))
    for slot, bank in enumerate(slots):
        prg[bank * 0x2000:(bank + 1) * 0x2000] = image[slot * 0x2000:(slot + 1) * 0x2000]
    h = bytes([0x4E, 0x45, 0x53, 0x1A, prg16, 0, b6, b7]) + bytes(8)
    return h + bytes(prg)


def made_bad():
    return {
        "not_a_rom.nes": b"hello, this is text\n",
        "empty.nes": b"",
        "short_header.nes": b"NES\x1a\x02\x01\x00",
        "truncated.nes": ines(2, 1)[:0x6000],
        "no_prg.nes": ines(0, 1, size=0),
        "prg_odd.nes": nes2(12 << 2 | 1, 0, 0, b9=0x0F, size=0x3000),   # 12 KB
        "chr_odd.nes": nes2(2, 0x03 << 2 | 0, 0, b9=0xF0, size=0x8000, chr_size=8),
        "chr_tiny.nes": nes2(2, 9 << 2, 0, b9=0xF0, size=0x8000, chr_size=0x200),
        "too_large.nes": nes2(31 << 2, 0, 0, b9=0x0F, size=0x8000),
        "mapper_99.nes": ines(2, 1, b6=0x30, b7=0x60),
        "mapper_300.nes": nes2(2, 0, 300, size=0x8000),
        "nina001.nes": nes2(2, 0, 34, sub=1, size=0x8000),
        "nsf_low.nsf": nsf(0x7000, 0x7000, 0x7003, code(0x7000, 0x100)),
        "nsf_fds_low.nsf": nsf(0x5000, 0x5000, 0x5003, code(0x5000, 0x100), chips=4),
        "nsf_short.nsf": nsf(0x8000, 0x8000, 0x8003, b"")[:0x40],
        "nsf_banked_empty.nsf": nsf(0x8000, 0x8000, 0x8003, b"", banks=[0, 0, 0, 0, 0, 0, 0, 1]),
        "missing_file.nes": None,
    }


def main():
    for p, what in ((C, "make recomp"),):
        if not os.path.exists(p):
            sys.exit("%s is missing: %s first" % (p, what))
    os.makedirs(OUT, exist_ok=True)

    # 1. every file under tests/.
    files = []
    for d, _, fs in os.walk(HERE):
        for f in fs:
            if f.lower().endswith((".nes", ".nsf", ".fds")):
                files.append(os.path.join(d, f))
    files.sort()
    refused_both = []

    def one(path):
        out = []
        p, c = both([path, "--dump-rom"])
        if p[0] != 0:
            out.append(("refused", path, c == p, first_difference(p[2], c[2])))
        else:
            why = None if c == p else first_difference(p[1] + p[2], c[1] + c[2])
            out.append(("alone", path, why is None, why))
        if os.path.exists(path + ".missed"):
            why = same_dump([path, "--missed", path + ".missed"])
            out.append(("missed", path, why is None, why))
        return out

    with ThreadPoolExecutor(8) as ex:
        results = [r for rs in ex.map(one, files) for r in rs]
    alone = [r for r in results if r[0] == "alone"]
    missed = [r for r in results if r[0] == "missed"]
    refused = [r for r in results if r[0] == "refused"]
    bad = [r for r in alone if not r[2]]
    check("all %d files under tests/ that recomp.py reads: read the same" % len(alone), not bad,
          "%d differ, first %s: %s" % (len(bad), os.path.relpath(bad[0][1], ROOT), bad[0][3]) if bad else "")
    bad = [r for r in missed if not r[2]]
    check("the %d with a .missed file, read with it: the same entry points" % len(missed), not bad,
          "%d differ, first %s: %s" % (len(bad), os.path.relpath(bad[0][1], ROOT), bad[0][3]) if bad else "")
    bad = [r for r in refused if not r[2]]
    check("the %d under tests/ it refuses: the same message" % len(refused), not bad,
          "%s: %s" % (os.path.relpath(bad[0][1], ROOT), bad[0][3]) if bad else "")
    nestest = os.path.join(HERE, "nestest.nes")
    why = same_dump([nestest, "--entry", "C000", "--missed", nestest + ".missed"])
    check("nestest as `make test` reads it (--entry C000, its .missed)", why is None, why or "")

    # 2. files made here.
    good = made_good()
    gdir = os.path.join(OUT, "good")
    os.makedirs(gdir, exist_ok=True)
    for name, data in good.items():
        path = os.path.join(gdir, name)
        with open(path, "wb") as f:
            f.write(data)
        why = same_dump([path])
        check("made: %s" % name, why is None, why or "")

    # 3. files it refuses.
    bdir = os.path.join(OUT, "bad")
    os.makedirs(bdir, exist_ok=True)
    for name, data in made_bad().items():
        path = os.path.join(bdir, name)
        if data is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            with open(path, "wb") as f:
                f.write(data)
        p, c = both([path, "--dump-rom"])
        check("refused: %s (%s)" % (name, p[2].strip().split(": ")[-1][:50]),
              p[0] == 1 and c == p and p[2].strip() and "Traceback" not in p[2],
              "recomp.py %d %r, C %d %r" % (p[0], p[2].strip()[-70:], c[0], c[2].strip()[-70:]))

    # 4. entry points.
    rom = os.path.join(gdir, "mmc1_256k.nes")
    m = os.path.join(OUT, "test.missed")
    with open(m, "w") as f:
        f.write("0F:8123\n\n  03:A000  \n1F:C000\n41:E000\n8100\nC000\n\nfe:ffff\n0x02:0x9000\n")
    why = same_dump([rom, "--missed", m, "--entry", "E000", "--entry", "0x8100", "--entry", " 9000"])
    check("--missed in both formats, spaces, blank lines, banks past the last; --entry", why is None, why or "")
    m2 = os.path.join(OUT, "test2.missed")
    with open(m2, "w") as f:
        f.write("6000\n7FFF:8000\n05:6100\n")
    why = same_dump([rom, "--missed", m, "--missed", m2])
    check("two .missed files, and addresses below $8000 dropped", why is None, why or "")
    nb = os.path.join(gdir, "nsf_banked_off.nsf")
    why = same_dump([nb, "--missed", m, "--entry", "A000"])
    check("entry points in a banked NSF (4 KB slots)", why is None, why or "")
    fd = os.path.join(gdir, "fds_two_sides.fds")
    with open(os.path.join(OUT, "fds.missed"), "w") as f:
        f.write("04:6100\n04:9000\n06:9010\n03:E100\n03:6000\n05:DFF6\n")
    why = same_dump([fd, "--missed", os.path.join(OUT, "fds.missed")])
    check("entry points in a disk image: in a file, in the BIOS, outside both", why is None, why or "")

    # 5. the C, and 6. the time.
    os.makedirs(os.path.join(OUT, "c"), exist_ok=True)
    readable = [r[1] for r in alone]
    jobs = []
    for i, path in enumerate(readable):
        jobs.append(("alone", path, [path], "a%d" % i))
        if os.path.exists(path + ".missed"):
            jobs.append(("missed", path, [path, "--missed", path + ".missed"], "m%d" % i))
    for i, name in enumerate(good):
        jobs.append(("made", name, [os.path.join(gdir, name)], "g%d" % i))
    with ThreadPoolExecutor(8) as ex:
        done = list(ex.map(lambda j: (j[0], j[1]) + same_c(j[2], j[3]), jobs))
    for kind, label in (("alone", "all %d readable files under tests/: the same C and lines"),
                        ("missed", "the %d with a .missed file, recompiled with it: the same"),
                        ("made", "the %d files made in 2.: the same")):
        rows = [d for d in done if d[0] == kind]
        bad = [d for d in rows if d[2]]
        check(label % len(rows), rows and not bad,
              "%d differ, first %s: %s" % (len(bad), os.path.relpath(bad[0][1], ROOT) if kind != "made"
                                            else bad[0][1], bad[0][2]) if bad else "none")
    why, _ = same_c([nestest, "--entry", "C000", "--missed", nestest + ".missed"], "nestest")
    check("nestest as `make test` recompiles it: the same", why is None, why or "")
    py_t = sum(d[3][0] for d in done)
    c_t = sum(d[3][1] for d in done)
    print("      (%d recompiles: recomp.py %.1f s of work, the C version %.1f s, %.0fx faster)"
          % (len(done), py_t, c_t, py_t / c_t if c_t else 0))
    big = max(readable, key=os.path.getsize)
    _, took = same_c([big], "big")
    print("      (the largest, %s, %d KB: recomp.py %.2f s, the C version %.3f s)"
          % (os.path.relpath(big, ROOT), os.path.getsize(big) // 1024, took[0], took[1]))

    # 8. the listing.
    os.makedirs(os.path.join(OUT, "lst"), exist_ok=True)
    with ThreadPoolExecutor(8) as ex:
        ldone = list(ex.map(lambda j: (j[0], j[1], listing_ok(j[2], "L" + j[3])), jobs))
    bad = [d for d in ldone if d[2]]
    check("--listing, all %d recompiles of 5.: the C unchanged, every instruction listed where it is"
          % len(ldone), ldone and not bad,
          "%d wrong, first %s: %s" % (len(bad), bad[0][1] if bad[0][0] == "made"
                                       else os.path.relpath(bad[0][1], ROOT), bad[0][2]) if bad else "none")
    why = listing_ok([nestest, "--entry", "C000", "--missed", nestest + ".missed"], "Lnestest")
    check("--listing, nestest as `make test` recompiles it: the same", why is None, why or "")

    # 9. nestest's listing against nestest.log.
    nl = os.path.join(OUT, "nestest.lst")
    subprocess.run([C, nestest, "--entry", "C000", "--missed", nestest + ".missed", "-o",
                    os.path.join(OUT, "nestest.c"), "--listing", nl], capture_output=True)
    listed = {}
    for l in open(nl).read().splitlines() if os.path.exists(nl) else []:
        if not l.startswith("#"):
            row = l.split("\t")
            listed[row[0][3:]] = (row[3], row[4])
    compared, wrong = set(), []
    for l in open(os.path.join(HERE, "nestest.log")):
        pc, by, text = l[:4], l[6:14].strip(), l[15:48].rstrip()
        for cut in (" = ", " @ "):
            if cut in text:
                text = text[:text.index(cut)]
        text = text.strip()
        if pc in listed and pc not in compared:
            compared.add(pc)
            if listed[pc] != (by, text):
                wrong.append((pc, listed[pc], (by, text)))
    check("nestest's listing against nestest.log: %d instructions, the same bytes and 6502 text"
          % len(compared), len(compared) > 6000 and not wrong, "%d differ, first %s" % (
              len(wrong), wrong[0]) if wrong else "only %d compared" % len(compared))

    # 7. the project's own tools use the C version.
    def make_n(*args):
        r = subprocess.run(["make", "-n", "-B"] + list(args), cwd=ROOT, capture_output=True, text=True)
        # The lines that recompile the ROM (not the one building the recompiler).
        return [l for l in r.stdout.splitlines() if "tests/nestest.nes -o " in l]
    for what, args in (("make game", ["game", "ROM=tests/nestest.nes"]),
                       ("make test (nestest)", ["build/nestest.c"])):
        lines = make_n(*args)
        check("%s recompiles with build/nesrecomp-recomp" % what,
              lines and all(l.startswith("build/nesrecomp-recomp ") for l in lines),
              "%s" % (lines[:1] or "no recompile line"))
    stub = os.path.join(OUT, "stub")
    os.makedirs(stub, exist_ok=True)
    with open(os.path.join(stub, "python3"), "w") as f:
        f.write("#!/bin/sh\necho 'python3 was called' >&2\nexit 7\n")
    os.chmod(os.path.join(stub, "python3"), 0o755)
    env = dict(os.environ, PATH=stub + ":" + os.environ.get("PATH", ""))
    r = subprocess.run([sys.executable, os.path.join(HERE, "run_tests.py"), "01-basics"], cwd=ROOT,
                       capture_output=True, text=True, env=env, timeout=600)
    check("the test suite recompiles without Python (a test with python3 made to fail)",
          r.returncode == 0 and "1 of 1 tests pass" in r.stdout and "python3 was called" not in r.stdout + r.stderr,
          (r.stdout + r.stderr).strip().splitlines()[-1][:100] if (r.stdout + r.stderr).strip() else "no output")

    print("\n%d check(s) failed" % len(fails) if fails else "\nall checks pass")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
