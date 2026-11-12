"""List the iNES header facts for every .nes file under the given folders.

    python3 tests/romlist.py tests/roms            # every ROM
    python3 tests/romlist.py tests/roms --nrom     # only mapper 0 (NROM)

Columns: mapper, PRG KB, CHR KB (0 = the cartridge uses CHR RAM),
mirroring (H, V or 4 for four-screen), B if battery-backed PRG RAM, path.
"""
import os
import sys


def header(path):
    with open(path, "rb") as f:
        h = f.read(16)
    if len(h) < 16 or h[:4] != b"NES\x1a":
        return None
    mapper = (h[6] >> 4) | (h[7] & 0xF0)
    if (h[7] & 0x0C) == 0x08:              # NES 2.0: four more mapper bits
        mapper |= (h[8] & 0x0F) << 8
    elif any(h[12:16]):                   # junk in old dumps ("DiskDude!")
        mapper &= 0x0F
    mirror = "4" if h[6] & 8 else ("V" if h[6] & 1 else "H")
    return mapper, h[4] * 16, h[5] * 8, mirror, "B" if h[6] & 2 else "-"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    nrom_only = "--nrom" in sys.argv
    rows = []
    for top in args or ["tests/roms"]:
        for root, _, files in os.walk(top):
            for name in files:
                if name.lower().endswith(".nes"):
                    path = os.path.join(root, name)
                    info = header(path)
                    if info and (not nrom_only or info[0] == 0):
                        rows.append(info + (os.path.relpath(path, top),))
    rows.sort(key=lambda r: r[5])
    for m, prg, chr_, mir, bat, path in rows:
        print("%3d %4d %4d %s %s  %s" % (m, prg, chr_, mir, bat, path))
    print("%d ROM(s)" % len(rows), file=sys.stderr)


if __name__ == "__main__":
    main()
