#!/usr/bin/env python3
"""Make build/nesrecomp.app, the app you double-click (PLAN-gui.md step 4),
from build/nesrecomp-app (`make app`). Run by `make app-bundle`.

    nesrecomp.app/Contents/
        Info.plist          its name, version, copyright line, icon, and
                            the files it opens (.nes, .nsf, .fds), so a
                            ROM can be dropped on its Dock icon or opened
                            with it from Finder
        MacOS/nesrecomp     the program
        Resources/
            nesrecomp.icns  the icon: the TV and the console from the
                            app's picture, on the wall's gradient in a
                            rounded square
            Credits.rtf     what the Mac's About box shows under the name

The program still uses the project folder it was built in (recomp.py,
runtime/), as `make app` does; the app is a way to start it.
"""
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import make_app_art as art  # noqa: E402

NAME = "NES RECOMP"
IDENT = "local.nesrecomp"
VERSION = "1.0"
COPYRIGHT = ("For educational purposes only. By Serge and Claude. "
             "Free software under the MIT License.")
CREDITS = ["For educational purposes only", "By Serge and Claude",
           "Free software under the MIT License"]
ICON_CROP = (76, 6, 168, 168)           # the TV and the console: x, y, w, h
# What the icon takes from the picture: the TV (with its feet) and the
# console (with its shadow); the rest is the gradient.
KEEP = [(79, 11, 240, 131), (97, 121, 223, 171)]


def write_png(path, rows):
    """rows: lists of (r, g, b, a)."""
    h, w = len(rows), len(rows[0])
    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in rows)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def icon_master():
    """The 1024x1024 icon: a rounded square of the wall's gradient (its
    pixels 8 icon pixels wide), the TV and the console drawn 5 icon
    pixels a canvas pixel, centred."""
    c = art.draw()
    pal = [col for _, col in art.PALETTE]
    size, radius, inset = 1024, 180, 80
    rows = [[(0, 0, 0, 0)] * size for _ in range(size)]
    cx0, cy0, cw, ch = ICON_CROP
    scale = 5
    ox, oy = (size - cw * scale) // 2, (size - ch * scale) // 2
    # The crop just catches the tip of the dragon's tail: its colours (the
    # TV and the console use none of them) show the gradient instead.
    dragon = {art.IDX[k] for k in ("red", "red_dark", "red_light", "gold", "gold_dark",
                                    "mane", "mane_blue", "mane_hi", "eye", "fang", "mouth")}
    for y in range(size):
        for x in range(size):
            # Inside the rounded square?
            ix, iy = min(x - inset, size - 1 - inset - x), min(y - inset, size - 1 - inset - y)
            if ix < 0 or iy < 0:
                continue
            if ix < radius and iy < radius and (radius - ix) ** 2 + (radius - iy) ** 2 > radius ** 2:
                continue
            px, py = (x - ox) // scale, (y - oy) // scale
            ax, ay = cx0 + px, cy0 + py
            inside = 0 <= px < cw and 0 <= py < ch and any(
                bx0 <= ax <= bx1 and by0 <= ay <= by1 for bx0, by0, bx1, by1 in KEEP)
            if inside and c.px[ay][ax] not in dragon:
                col = pal[c.px[cy0 + py][cx0 + px]]
            else:
                gx, gy = x // 8, y // 8
                t = gx / 128 * 0.65 + gy / 128 * 0.35
                v = t * 4 + (art.BAYER[gy % 4][gx % 4] / 16 - 0.5)
                col = pal[art.IDX["wall%d" % max(0, min(4, int(round(v))))]]
            rows[y][x] = col + (255,)
    return rows


def make_icns(dest):
    work = os.path.join(ROOT, "build", "nesrecomp.iconset")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    master = os.path.join(work, "icon_512x512@2x.png")
    write_png(master, icon_master())
    for s in (16, 32, 128, 256, 512):
        for mult, suffix in ((1, ""), (2, "@2x")):
            if s == 512 and mult == 2:
                continue
            out = os.path.join(work, "icon_%dx%d%s.png" % (s, s, suffix))
            subprocess.run(["sips", "-z", str(s * mult), str(s * mult), master, "--out", out],
                           check=True, capture_output=True)
    subprocess.run(["iconutil", "-c", "icns", work, "-o", dest], check=True)


def credits_rtf():
    body = "\\\n".join(CREDITS)
    return ("{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Helvetica;}}\n"
            "\\f0\\fs22\\qc " + body + "\n}\n")


def main():
    exe = os.path.join(ROOT, "build", "nesrecomp-app")
    if not os.path.exists(exe):
        sys.exit("build/nesrecomp-app is missing: run `make app` first")
    app = os.path.join(ROOT, "build", "nesrecomp.app")
    shutil.rmtree(app, ignore_errors=True)
    contents = os.path.join(app, "Contents")
    os.makedirs(os.path.join(contents, "MacOS"))
    os.makedirs(os.path.join(contents, "Resources"))
    shutil.copy2(exe, os.path.join(contents, "MacOS", "nesrecomp"))
    make_icns(os.path.join(contents, "Resources", "nesrecomp.icns"))
    with open(os.path.join(contents, "Resources", "Credits.rtf"), "w") as f:
        f.write(credits_rtf())
    plist = {
        "CFBundleName": NAME,
        "CFBundleDisplayName": NAME,
        "CFBundleIdentifier": IDENT,
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "CFBundleExecutable": "nesrecomp",
        "CFBundleIconFile": "nesrecomp",
        "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "NSHumanReadableCopyright": COPYRIGHT,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "CFBundleDocumentTypes": [{
            "CFBundleTypeName": "NES program",
            "CFBundleTypeRole": "Viewer",
            "LSHandlerRank": "Alternate",
            "CFBundleTypeExtensions": ["nes", "nsf", "fds", "NES", "NSF", "FDS"],
            "LSItemContentTypes": ["public.data"],
        }],
    }
    with open(os.path.join(contents, "Info.plist"), "wb") as f:
        plistlib.dump(plist, f)
    # An ad-hoc signature over the whole bundle (no identity), as the Mac
    # expects of an app.
    subprocess.run(["codesign", "--force", "--deep", "-s", "-", app], check=True,
                   capture_output=True)
    print("wrote", app)


if __name__ == "__main__":
    main()
