#!/usr/bin/env python3
"""Pictures of the pause menu's CONTROLLERS pages (PLAN-controllers.md
step 5), to look at rather than check: the Windows run saves them as a
download, so Windows' pairing help can be seen as Windows draws it.
tests/check_menu.py is what checks them, pixel by pixel.

    python3 tests/menu_pictures.py [OUT] [--pairing-for mac|windows]

OUT (default build/menu-pictures) gets, each three times the NES's
size: the CONTROLLERS page, the button test with a virtual pad holding
A and Start, KEYBOARD 1, PADS, the PAIRING HELP list and each of its
pages, for the system asked for (default: the one this runs on).
"""
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_menu  # noqa: E402
import run_tests  # noqa: E402

ROM = "tests/mmc3_split.nes"


def bigger(path, s=3):
    """The PNG at `path`, s times the size with sharp pixels (written
    beside it, as NAME_3x.png); the small one is removed."""
    d = open(path, "rb").read()
    i, idat = 8, b""
    while i < len(d):
        n, = struct.unpack(">I", d[i:i + 4])
        kind, body = d[i + 4:i + 8], d[i + 8:i + 8 + n]
        i += 12 + n
        if kind == b"IHDR":
            w, h, _, ct = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            idat += body
    bpp = {2: 3, 6: 4}[ct]
    raw, rows, prev, k = zlib.decompress(idat), [], bytearray(w * bpp), 0
    for _ in range(h):
        f, line = raw[k], bytearray(raw[k + 1:k + 1 + w * bpp])
        k += 1 + w * bpp
        for x in range(len(line)):
            a = line[x - bpp] if x >= bpp else 0
            b, c = prev[x], prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line))
        prev = line
    out = b"".join((b"\0" + b"".join(r[x * bpp:(x + 1) * bpp] * s for x in range(w))) * s for r in rows)

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    with open(path[:-4] + "_3x.png", "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w * s, h * s, 8, ct, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(out)) + chunk(b"IEND", b""))
    os.remove(path)


def main():
    args = sys.argv[1:]
    system = "windows" if sys.platform == "win32" else "mac"
    if "--pairing-for" in args:
        i = args.index("--pairing-for")
        system = args[i + 1]
        del args[i:i + 2]
    out = os.path.abspath(args[0] if args else os.path.join(run_tests.ROOT, "build", "menu-pictures"))
    os.makedirs(out, exist_ok=True)
    check_menu.OUT = out
    cflags, libs = run_tests.sdl_flags()
    exe = check_menu.build(ROM, cflags, libs, run_tests.build_runtime(cflags))
    L = check_menu.layout()

    def shot(name):
        return "shot=" + os.path.join(out, name + ".png")
    pages = len(check_menu.PAIR_PAGES[system])
    menu = ["up up ok", shot("1-controllers"),
            "pad=1:none ok pad=1:a+start", shot("2-button-test"), "pad=1:none leave",
            "down ok", shot("3-keyboard-1"), "back",
            "down down ok", shot("4-pads"), "back",
            "down ok", shot("5-pairing-help")]
    for p in range(pages):
        title = L["pages"][check_menu.PAIR_PAGES[system][p]][0]
        menu += ["ok", shot("6-pairing-%d-%s" % (p + 1, title.lower().replace(" ", "-"))), "back", "down"]
    menu += ["back back back"]
    files = os.path.join(out, "files")
    err, _ = check_menu.run(exe, ROM, ["60 menu " + " ".join(menu)], None, 70, "pictures", files,
                            ["--pairing-for", system, "--controls", os.path.join(out, "controls.txt")])
    made = sorted(n for n in os.listdir(out) if n.endswith(".png") and not n.endswith("_3x.png"))
    for n in made:
        bigger(os.path.join(out, n))
    want = 5 + pages
    print("%d of %d pictures of the CONTROLLERS pages (%s pairing help) in %s" % (len(made), want, system, out))
    if len(made) != want:
        print(err[-600:])
        sys.exit(1)


if __name__ == "__main__":
    main()
