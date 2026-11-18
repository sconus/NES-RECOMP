#!/usr/bin/env python3
"""Check build/nesrecomp.app (PLAN-gui.md step 4). Run by
`make test-app-bundle`; it opens the app as Finder would, so a window
shows for a few seconds.
  1. what it is: its Info.plist (name, identifier, version, the About
     box's copyright line, the icon, the program, the files it opens),
     its Credits.rtf (the About box's lines, and the support page as a
     link), its menu (About NES RECOMP, then Support NES RECOMP...), its icon (a 1024-pixel
     image inside, with "NES RECOMP" in white on the TV), its program (the same as build/nesrecomp-app), its
     signature;
  2. opening a file with it, as Finder does (`open -a`): the app starts
     with Finder's bare environment, the file reaches it as a drop, it
     builds it (its recompiler and cc found), and plays it. The file is a ROM
     made here that stops at once ("THE GAME STOPPED"), so no game
     window stays open; then the app is asked to quit. The build goes to
     ~/Library/Application Support/NES RECOMP (PLAN-standalone.md step
     4), with the bundle's own runtime, and the bundle is left as it was;
     the check removes the files it made there (the whole folder, if it
     made it).
Exit status 0 when all pass.
"""
import os
import re
import plistlib
import shutil
import subprocess
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP = os.path.join(ROOT, "build", "nesrecomp.app")
OUT = os.path.join(ROOT, "build", "app_check", "bundle")
IDENT = "local.nesrecomp"


def read_png(path):
    """Width, height and rows of (r, g, b) of an 8-bit RGB or RGBA PNG,
    with any of the five row filters."""
    d = open(path, "rb").read()
    i, idat, w, h, ct = 8, b"", 0, 0, 0
    while i < len(d):
        n = int.from_bytes(d[i:i + 4], "big")
        t = d[i + 4:i + 8]
        if t == b"IHDR":
            w, h = int.from_bytes(d[i + 8:i + 12], "big"), int.from_bytes(d[i + 12:i + 16], "big")
            ct = d[i + 17]
        elif t == b"IDAT":
            idat += d[i + 8:i + 8 + n]
        i += 12 + n
    bpp = {2: 3, 6: 4}[ct]
    raw, stride, prev, rows, at = zlib.decompress(idat), w * bpp, bytearray(w * bpp), [], 0
    for _ in range(h):
        f, line = raw[at], bytearray(raw[at + 1:at + 1 + stride])
        at += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b, c = prev[x], prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append([tuple(line[x * bpp:x * bpp + 3]) for x in range(w)])
        prev = line
    return w, h, rows


def listing(top):
    out = []
    for d, _, files in os.walk(top):
        for f in files:
            st = os.lstat(os.path.join(d, f))
            out.append((os.path.relpath(os.path.join(d, f), top), st.st_size, st.st_mtime_ns))
    return sorted(out)


def main():
    fails = []

    def check(name, ok, why=""):
        print("%s  %s%s" % ("ok  " if ok else "FAIL", name, "" if ok else ": " + why))
        if not ok:
            fails.append(name)

    contents = os.path.join(APP, "Contents")
    try:
        info = plistlib.load(open(os.path.join(contents, "Info.plist"), "rb"))
    except (OSError, plistlib.InvalidFileException) as e:
        info = {}
        check("Info.plist", False, str(e))
    APP_VERSION = re.search(r'#define APP_VERSION "([^"]+)"', open(os.path.join(ROOT, "app", "build.h")).read()).group(1)
    want = {
        "CFBundleName": "NES RECOMP", "CFBundleIdentifier": IDENT,
        "CFBundleShortVersionString": APP_VERSION, "CFBundleExecutable": "nesrecomp",
        "CFBundleIconFile": "nesrecomp", "CFBundlePackageType": "APPL",
        "NSHumanReadableCopyright": "For educational purposes only. By Serge and Claude. "
                                    "Free software under the MIT License.",
    }
    wrong = ["%s=%r" % (k, info.get(k)) for k, v in want.items() if info.get(k) != v]
    check("Info.plist: name, version, the About line", not wrong, ", ".join(wrong))
    docs = info.get("CFBundleDocumentTypes", [])
    exts = {e.lower() for d in docs for e in d.get("CFBundleTypeExtensions", [])}
    check("Info.plist: it opens .nes, .nsf and .fds files", {"nes", "nsf", "fds"} <= exts,
          "extensions %s" % sorted(exts))
    lint = subprocess.run(["plutil", "-lint", os.path.join(contents, "Info.plist")],
                          capture_output=True, text=True)
    check("Info.plist is valid", lint.returncode == 0, lint.stdout.strip())
    credits = os.path.join(contents, "Resources", "Credits.rtf")
    text = open(credits).read() if os.path.exists(credits) else ""
    missing = [l for l in ("For educational purposes only", "By Serge and Claude",
                           "Free software under the MIT License") if l not in text]
    check("Credits.rtf: the About box's three lines", text.startswith("{\\rtf1") and not missing,
          "missing %s" % missing if text else "no file")
    url = "https://ko-fi.com/polygonlegends"
    check("Credits.rtf: then the support page, as a link",
          ('HYPERLINK "%s"' % url) in text and "Support it: ko-fi.com/polygonlegends" in text,
          "no link" if text else "no file")
    icns = os.path.join(contents, "Resources", "nesrecomp.icns")
    iconset = os.path.join(OUT, "icon.iconset")
    shutil.rmtree(iconset, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    r = subprocess.run(["iconutil", "-c", "iconset", icns, "-o", iconset], capture_output=True, text=True)
    big = os.path.join(iconset, "icon_512x512@2x.png")
    size = subprocess.run(["sips", "-g", "pixelWidth", big], capture_output=True, text=True).stdout \
        if os.path.exists(big) else ""
    check("the icon: a 1024-pixel image inside", r.returncode == 0 and "pixelWidth: 1024" in size,
          (r.stderr or size).strip()[-80:])
    # The TV's screen in the icon: the picture's screen (92, 24, 116, 86)
    # from the crop at (76, 6), 5 icon pixels a picture pixel, centred.
    white = 0
    if os.path.exists(big):
        _, _, rows = read_png(big)
        for y in range(92 + 18 * 5, 92 + (18 + 86) * 5):
            for x in range(92 + 16 * 5, 92 + (16 + 116) * 5):
                white += min(rows[y][x]) > 200
    # NES RECOMP at 3x: 148 lit dots of the font, 9 picture pixels each,
    # 25 icon pixels each: 33,300 (most of it must be there).
    check("the icon: NES RECOMP in white on the TV", white > 30000, "%d white pixels there" % white)
    prog = os.path.join(contents, "MacOS", "nesrecomp")
    # Signing the bundle rewrites the program's signature (and a byte of
    # its header saying how it was signed): compare their code.
    same = False
    if os.path.exists(prog):
        code = [subprocess.run(["otool", "-tX", p], capture_output=True).stdout
                for p in (prog, os.path.join(ROOT, "build", "nesrecomp-app"))]
        same = len(code[0]) > 1000 and code[0] == code[1]
    check("the program: build/nesrecomp-app (but for its signature), and runnable",
          same and os.access(prog, os.X_OK), "missing or different")
    # Its menu, as the bundle names it, with the support item (no window;
    # `open` replaced so nothing opens).
    m = subprocess.run([prog, "--menu-test"], capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, NESRECOMP_OPEN="/usr/bin/true"))
    items = m.stdout.splitlines()
    check("its menu: \"About NES RECOMP\", then \"Support NES RECOMP\u2026\"",
          items[1:3] == ["About NES RECOMP", "Support NES RECOMP\u2026"], "%s" % items[:4])
    sig = subprocess.run(["codesign", "--verify", "--deep", APP], capture_output=True, text=True)
    check("the signature holds", sig.returncode == 0, sig.stderr.strip()[-80:])

    # 2. opened with a file, as Finder does.
    rom = os.path.join(OUT, "open_test.nes")
    prg = bytearray([0x02] * 0x4000)            # made here: stops at once
    prg[0x3FFA:0x4000] = bytes([0x00, 0xC0, 0x00, 0xC0, 0x00, 0xC0])
    with open(rom, "wb") as f:
        f.write(b"NES\x1a\x01\x01\x00\x00" + bytes(8) + bytes(prg) + bytes(0x2000))
    bdir = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "NES RECOMP")
    logs = [os.path.join(bdir, "open_test" + s) for s in (".log", ".game.log", ".stamp")]
    made = logs + [os.path.join(bdir, "open_test" + s) for s in ("", ".c", ".o")]
    before = listing(APP)
    existed = os.path.isdir(bdir)
    for p in logs:
        if os.path.exists(p):
            os.remove(p)
    started = subprocess.run(["open", "-a", APP, rom], capture_output=True, text=True)
    game_log = logs[1]
    deadline = time.time() + 90
    while time.time() < deadline and not (os.path.exists(game_log) and os.path.getsize(game_log)):
        time.sleep(0.5)
    time.sleep(1)
    subprocess.run(["osascript", "-e", 'tell application id "%s" to quit' % IDENT],
                   capture_output=True, text=True)
    blog = open(logs[0]).read() if os.path.exists(logs[0]) else ""
    glog = open(game_log).read() if os.path.exists(game_log) else ""
    check("opened with a file: the app started", started.returncode == 0, started.stderr.strip())
    check("the file reached it and it built it (its recompiler and cc found)",
          "nesrecomp.app/Contents/MacOS/nesrecomp-recomp " in blog and os.path.exists(logs[2]),
          "build log %s" % ("empty (if macOS asked whether NES RECOMP may use files in the "
                            "Desktop folder, allow it and run this again)" if not blog
                            else blog.strip().splitlines()[-1][:80]))
    check("it played what it built (the game stopped, as made)", "stopped: unknown opcode $02" in glog,
          "game log: %r" % glog[-80:])
    rt = os.path.join(os.path.realpath(APP), "Contents", "Resources", "runtime")
    check("it built in ~/Library/Application Support/NES RECOMP, with the bundle's runtime",
          os.path.exists(os.path.join(bdir, "open_test")) and "-I" + rt + " " in blog,
          "no program there" if not os.path.exists(os.path.join(bdir, "open_test")) else "runtime not %s" % rt)
    check("the bundle is left as it was", listing(APP) == before,
          "%s" % sorted(set(listing(APP)) ^ set(before))[:3])
    for p in made:
        if os.path.exists(p):
            os.remove(p)
    if not existed:                       # the app's folder was made for this check
        shutil.rmtree(bdir, ignore_errors=True)
    time.sleep(1)
    still = subprocess.run(["pgrep", "-f", "nesrecomp.app/Contents/MacOS/nesrecomp"],
                           capture_output=True, text=True).stdout.strip()
    check("asked to quit, it quit", not still, "still running: %s" % still)

    print("\n%d check(s) failed" % len(fails) if fails else "\nall checks pass")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
