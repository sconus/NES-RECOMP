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
     NSFs banked, at $6000 and too long: the same dumps;
  3. files recomp.py refuses: the same message and exit status;
  4. entry points from --entry and from .missed files in both formats,
     with spaces, blank lines and banks past the last: the same.
Exit status 0 when all pass.
"""
import os
import struct
import subprocess
import sys
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
    }


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

    print("\n%d check(s) failed" % len(fails) if fails else "\nall checks pass")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
