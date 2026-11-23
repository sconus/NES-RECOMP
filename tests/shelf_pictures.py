#!/usr/bin/env python3
"""Pictures of the app's shelf (PLAN-library.md steps 4 and 5), to look
at rather than check: the Windows run saves them as a download, so the
shelf can be seen as Windows draws it. tests/check_app.py is what checks
it, pixel by pixel.

    python3 tests/shelf_pictures.py [OUT]

OUT (default build/shelf-pictures) gets, in a 1280x720 window (the room
at 2x), with a made-up shelf of 40 games (the title pictures
tests/check_titles.py kept, if it ran, and made-up ones):
  1-empty.png        no games yet: the placeholders
  2-picked.png       page 1, the second game picked, on the TV
  3-page2.png        page 2
  4-missing.png      a game whose ROM is gone, picked
  5-remove.png       Delete: REMOVE FROM THE SHELF? Y / N
"""
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_app  # noqa: E402

ROOT = check_app.ROOT


def made_up(lib, missing=()):
    """A shelf of 40 in folder lib; the games in `missing` with no ROM."""
    shutil.rmtree(lib, ignore_errors=True)
    os.makedirs(lib)
    real = sorted(glob.glob(os.path.join(ROOT, "build", "titles", "*.start.title")))
    tops = [(0xE4, 0x5C, 0x10), (0x00, 0xA8, 0x00), (0x3C, 0xBC, 0xFC), (0xA8, 0x10, 0x00),
            (0x68, 0x44, 0xFC), (0xF8, 0xB8, 0x00), (0x58, 0xD8, 0x54), (0x94, 0x00, 0x84)]
    lines = ["version 1"]
    for i in range(40):
        name = "game_%02d" % (i + 1)
        rom = os.path.join(lib, name + (".nsf" if i == 5 else ".nes"))
        if i not in missing:
            open(rom, "wb").write(b"NESM\x1a" if i == 5 else b"NES\x1a")
        lines.append("%s\t%d\t%s" % (name, 1000 - i, rom))
        if i in (5, 7):                                     # music, and no picture yet
            continue
        if real and i % 4 == 0:
            data = open(real[(i // 4) % len(real)], "rb").read()
        else:
            data = b"NRTITLE1\x00\x01\xf0\x00" + check_app.two_colour_title(
                tops[i % 8], (0, 0, 0) if i % 3 else (0xFC, 0xFC, 0xFC), 90 + i)
        open(os.path.join(lib, name + ".title"), "wb").write(data)
    open(os.path.join(lib, "library.txt"), "w").write("\n".join(lines) + "\n")


def main():
    out = next((a for a in sys.argv[1:] if not a.startswith("-")), os.path.join(ROOT, "build", "shelf-pictures"))
    os.makedirs(out, exist_ok=True)
    work = os.path.join(out, "shelf")
    shots = []
    for name, missing, keys in (("1-empty", None, ""), ("2-picked", (), "right right"),
                                ("3-page2", (), "pgdn right"), ("4-missing", (2,), "right right right"),
                                ("5-remove", (), "right delete")):
        if missing is None:
            shutil.rmtree(work, ignore_errors=True)
            os.makedirs(work)
            open(os.path.join(work, "library.txt"), "w").write("version 1\n")
        else:
            made_up(work, missing)
        path = os.path.join(out, name + ".png")
        args = [check_app.APP, "--screenshot", path, "--size", "1280x720", "--library", work]
        if keys:
            args += ["--shelf-keys", keys]
        r = subprocess.run(args, capture_output=True, text=True)
        ok = r.returncode == 0 and os.path.exists(path)
        shots.append(ok)
        print("%s  %s" % ("ok  " if ok else "FAIL", path if ok else name + ": " + (r.stderr or r.stdout)[-200:]))
    shutil.rmtree(work, ignore_errors=True)
    print("\n%d of %d pictures" % (sum(shots), len(shots)))
    sys.exit(0 if all(shots) else 1)


if __name__ == "__main__":
    main()
