#!/usr/bin/env python3
"""Check that recomp.py and the runtime read iNES and NES 2.0 headers the
same way, and the way the nesdev wiki describes ("NES 2.0", "INES").

    python3 tests/check_headers.py build/nestest      (part of make test)

Each case is a header with some fields set, and the file around it (how
many bytes follow the header). The script writes it to a temporary .nes,
reads it with recomp.py's read_header and with the runtime's --info, and
compares both with the values written below by hand. Any runtime built
by this project will do: --info reads the file and stops.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from recomp import read_header  # noqa: E402

K = 1024


def header(**b):
    """16 header bytes: "NES" $1A, then byte N from bN=..."""
    h = bytearray(b"NES\x1a" + bytes(12))
    for k, v in b.items():
        if k == "tail":                          # bytes 7-15 as a string
            h[7:7 + len(v)] = v
        else:
            h[int(k[1:])] = v
    return bytes(h)


# (name, header, bytes after the header, expected fields or "refused")
CASES = [
    ("iNES 1.0 NROM", header(b4=1, b5=1, b6=0x01), 24 * K,
     dict(nes2=0, mapper=0, prg_size=16 * K, chr_size=8 * K,
          prg_ram=8 * K, prg_nvram=0, chr_ram=0)),
    ("iNES 1.0 battery, CHR RAM", header(b4=2, b5=0, b6=0x12), 32 * K,
     dict(nes2=0, mapper=1, battery=1, prg_size=32 * K, chr_size=0,
          prg_ram=0, prg_nvram=8 * K, chr_ram=8 * K)),
    ("iNES 1.0 junk in bytes 7-15", header(b4=1, b5=1, b6=0x10,
                                           tail=b"DiskDude!"), 24 * K,
     dict(nes2=0, mapper=1, console=0)),
    ("iNES 1.0 Vs. System bit", header(b4=1, b5=1, b7=0x01), 24 * K,
     dict(nes2=0, console=1, console_ext=0)),
    ("NES 2.0 every field", header(b4=1, b5=1, b6=0x42, b7=0x3B, b8=0x52,
                                   b10=0x97, b11=0x31, b12=3, b13=0x12,
                                   b14=2, b15=0xC9), 24 * K,
     dict(nes2=1, mapper=0x234, submapper=5, battery=1, prg_size=16 * K,
          chr_size=8 * K, prg_ram=8 * K, prg_nvram=32 * K, chr_ram=128,
          chr_nvram=512, timing=3, console=3, console_ext=0x12, misc_roms=2,
          exp_device=0x49)),
    ("NES 2.0 PRG size MSB", header(b4=1, b5=2, b7=0x08, b9=0x01),
     257 * 16 * K + 16 * K,
     dict(nes2=1, prg_size=257 * 16 * K, chr_size=16 * K)),
    ("NES 2.0 CHR size MSB", header(b4=1, b5=1, b7=0x08, b9=0x10),
     16 * K + 257 * 8 * K,
     dict(nes2=1, prg_size=16 * K, chr_size=257 * 8 * K)),
    ("NES 2.0 exponent form", header(b4=14 << 2 | 1, b5=13 << 2 | 0,
                                     b7=0x08, b9=0xFF), 48 * K + 8 * K,
     dict(nes2=1, prg_size=48 * K, chr_size=8 * K)),
    ("NES 2.0 exponent, multiplier 7", header(b4=13 << 2 | 3, b5=10 << 2 | 2,
                                              b7=0x08, b9=0xFF),
     56 * K + 5 * K,
     dict(nes2=1, prg_size=56 * K, chr_size=5 * K)),
    ("NES 2.0 PRG of 4 KB", header(b4=12 << 2, b5=1, b7=0x08, b9=0x0F),
     4 * K + 8 * K, "refused"),
    ("NES 2.0 CHR of 512 bytes", header(b4=1, b5=9 << 2, b7=0x08, b9=0xF0),
     16 * K + 512, "refused"),
    ("NES 2.0 size too large", header(b4=40 << 2, b5=1, b7=0x08, b9=0x0F),
     24 * K, "refused"),
    ("no PRG ROM", header(b4=0, b5=1), 8 * K, "refused"),
    ("NES 2.0 larger than the file: iNES 1.0",
     header(b4=2, b5=1, b6=0x10, b7=0x08, b8=0x01, b9=0x01, b12=1),
     32 * K + 8 * K,
     dict(nes2=0, mapper=1, submapper=0, prg_size=32 * K, timing=0)),
    # CHR is 257 x 8 KB read as NES 2.0, 8 KB read as iNES 1.0.
    ("NES 2.0 with a trainer, fits", header(b4=1, b5=1, b6=0x04, b7=0x08,
                                            b8=0x30, b9=0x10),
     512 + 16 * K + 257 * 8 * K, dict(nes2=1, submapper=3,
                                      chr_size=257 * 8 * K)),
    ("NES 2.0 with a trainer, a byte short",
     header(b4=1, b5=1, b6=0x04, b7=0x08, b8=0x30, b9=0x10),
     512 + 16 * K + 257 * 8 * K - 1, dict(nes2=0, submapper=0,
                                          chr_size=8 * K)),
    ("PRG ROM cut short", header(b4=2, b5=0), 32 * K - 1, "refused"),
    ("NES 2.0 PlayChoice-10: byte 13 not a type",
     header(b4=1, b5=1, b7=0x0A, b13=0x55), 24 * K,
     dict(nes2=1, console=2, console_ext=0)),
    ("NES 2.0 Vs. System", header(b4=1, b5=1, b7=0x09, b13=0x23), 24 * K,
     dict(nes2=1, console=1, console_ext=0x23)),
]

TIMING = ["NTSC", "PAL", "multi-region", "Dendy"]
CONSOLE = ["NES/Famicom", "Vs. System", "PlayChoice-10", "extended"]


def size(text):
    if text == "none":
        return 0
    n, unit = text.split()
    return int(n) * (K if unit == "KB" else 1)


def runtime_fields(exe, path):
    """The header as the runtime's --info prints it, or "refused"."""
    r = subprocess.run([exe, path, "--info"], capture_output=True, text=True)
    if r.returncode:
        return "refused"
    lines = r.stdout.splitlines()
    m1 = re.match(r"  mapper (\d+), PRG .*?(, battery)?$", lines[1])
    m2 = re.match(r"  (NES 2.0|iNES 1.0) header: submapper (\d+)$", lines[2])
    m3 = re.match(r"  PRG ROM (.+), CHR ROM (.+); PRG RAM (.+), PRG NVRAM (.+),"
                  r" CHR RAM (.+), CHR NVRAM (.+)$", lines[3])
    m4 = re.match(r"  timing (.+), console (.+) \(byte 13 \$(..)\), extra ROMs"
                  r" (\d), expansion device \$(..) ", lines[4])
    if not (m1 and m2 and m3 and m4):
        sys.exit("can't read --info:\n" + r.stdout)
    s = [size(t) for t in m3.groups()]
    return dict(mapper=int(m1.group(1)), battery=int(bool(m1.group(2))),
                nes2=int(m2.group(1) == "NES 2.0"), submapper=int(m2.group(2)),
                prg_size=s[0], chr_size=s[1], prg_ram=s[2], prg_nvram=s[3],
                chr_ram=s[4], chr_nvram=s[5],
                timing=TIMING.index(m4.group(1)),
                console=CONSOLE.index(m4.group(2)),
                console_ext=int(m4.group(3), 16), misc_roms=int(m4.group(4)),
                exp_device=int(m4.group(5), 16))


def recomp_fields(data):
    try:
        f = read_header(data)
    except ValueError:
        return "refused"
    return {k: int(v) for k, v in f.items()}


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    exe = sys.argv[1]
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "header.nes")
        for name, h, after, want in CASES:
            data = h + bytes(after)
            with open(path, "wb") as f:
                f.write(data)
            got = {"recomp.py": recomp_fields(data),
                   "runtime": runtime_fields(exe, path)}
            bad = []
            for who, g in got.items():
                if want == "refused" or g == "refused":
                    if g != want:
                        bad.append("%s: %s" % (who, g if g == "refused"
                                                   else "read it"))
                    continue
                for k, v in want.items():
                    if g[k] != v:
                        bad.append("%s: %s = %s, expected %s" % (who, k, g[k], v))
            if want != "refused" and "refused" not in got.values():
                a, b = got["recomp.py"], got["runtime"]
                bad += ["recomp.py and runtime differ: %s %s / %s" % (k, a[k], b[k])
                        for k in b if a[k] != b[k]]
            print("%s  %s" % ("ok  " if not bad else "FAIL", name))
            for line in bad:
                print("        " + line)
            failed += bool(bad)
    print("%d of %d header cases agree" % (len(CASES) - failed, len(CASES)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
