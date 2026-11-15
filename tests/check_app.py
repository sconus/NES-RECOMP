#!/usr/bin/env python3
"""Check the nesrecomp app's screens (PLAN-gui.md), from its own
screenshots (build/nesrecomp-app --screenshot), against app/art.h:
  1. the picture: every pixel outside the TV screen and the power light
     is the art's colour;
  2. the text: "DROP YOUR / NES ROM / FILE HERE", in the 5x7 font at
     twice its size, centred on the screen, outlined a pixel all round,
     and nothing else in the text's colour there;
  3. the window: at several sizes, the canvas at the largest whole
     number scale that fits, centred, the rest the border colour (a
     window smaller than the canvas shows it at 1x, cropped);
  4. the idle animation: the screen's glow changes over time, its
     scanlines shimmer every 6 frames, the power light is off for the
     last 10 frames of each second, and nothing else moves (looked at
     on frames on both sides of the shimmer).
Run by `make test-app`. Exit status 0 when all pass.
"""
import os
import re
import struct
import subprocess
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP = os.path.join(ROOT, "build", "nesrecomp-app")
OUT = os.path.join(ROOT, "build", "app_check")


def art():
    src = open(os.path.join(ROOT, "app", "art.h")).read()
    defs = {k: int(v) for k, v in re.findall(r"#define (\w+) (\d+)", src)}
    pal_body = src.split("art_palette[ART_COLOURS][3] = {", 1)[1].split("};", 1)[0]
    pal = [tuple(int(x, 16) for x in m) for m in
           re.findall(r"\{ 0x(..), 0x(..), 0x(..) \}", pal_body)]
    px_body = src.split("art_pixels[ART_H][ART_W] = {", 1)[1].split("};", 1)[0]
    rows = [[int(v) for v in r.split(",")] for r in re.findall(r"\{([0-9,]+)\}", px_body)]
    font_body = src.split("art_font[64][7] = {", 1)[1].split("};", 1)[0]
    vals = [int(v, 16) for v in re.findall(r"0x([0-9A-F]{2})", font_body)]
    font = [vals[i * 7:i * 7 + 7] for i in range(64)]
    return defs, pal, rows, font


def read_png(path):
    d = open(path, "rb").read()
    i, idat = 8, b""
    while i < len(d):
        n = struct.unpack(">I", d[i:i + 4])[0]
        t = d[i + 4:i + 8]
        if t == b"IHDR":
            w, h = struct.unpack(">II", d[i + 8:i + 16])
        elif t == b"IDAT":
            idat += d[i + 8:i + 8 + n]
        i += 12 + n
    raw = zlib.decompress(idat)
    stride = 1 + w * 3
    px = []
    for y in range(h):
        r = raw[y * stride + 1:(y + 1) * stride]
        px.append([tuple(r[x * 3:x * 3 + 3]) for x in range(w)])
    return w, h, px


def shot(name, frame=0, size=None):
    path = os.path.join(OUT, name + ".png")
    cmd = [APP, "--screenshot", path, "--frames", str(frame)]
    if size:
        cmd += ["--size", "%dx%d" % size]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit("screenshot failed: " + r.stderr)
    return read_png(path)


def text_pixels(defs, font, lines, scale=2, gap=6):
    """The canvas pixels the drop screen's text covers."""
    sx, sy, sw, sh = (defs["ART_SCREEN_" + k] for k in "XYWH")
    cx = sx + sw // 2
    top = sy + (sh - (len(lines) * 7 * scale + (len(lines) - 1) * gap)) // 2
    on = set()
    for li, s in enumerate(lines):
        y0 = top + li * (7 * scale + gap)
        x0 = cx - (len(s) * 6 * scale - scale) // 2
        for i, ch in enumerate(s):
            g = font[ord(ch) - 0x20]
            for r in range(7):
                for c in range(5):
                    if g[r] & (0x10 >> c):
                        for dy in range(scale):
                            for dx in range(scale):
                                on.add((x0 + i * 6 * scale + c * scale + dx, y0 + r * scale + dy))
    return on


def main():
    os.makedirs(OUT, exist_ok=True)
    defs, pal, rows, font = art()
    W, H = defs["ART_W"], defs["ART_H"]
    sx, sy, sw, sh = (defs["ART_SCREEN_" + k] for k in "XYWH")
    animated = {defs["INK_SCREEN"], defs["INK_SCAN"], defs["INK_LED"]}
    fails = []

    def check(name, ok, why=""):
        print("%s  %s%s" % ("ok  " if ok else "FAIL", name, "" if ok else ": " + why))
        if not ok:
            fails.append(name)

    w, h, base = shot("drop0")
    check("canvas size", (w, h) == (W, H), "%dx%d" % (w, h))
    on = text_pixels(defs, font, ["DROP YOUR", "NES ROM", "FILE HERE"])
    ring = {(x + dx, y + dy) for x, y in on for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - on
    # 1. the picture
    bad = [(x, y) for y in range(H) for x in range(W)
           if rows[y][x] not in animated and (x, y) not in on and (x, y) not in ring
           and base[y][x] != pal[rows[y][x]]]
    check("the picture", not bad, "%d pixel(s) differ, first at %s" % (len(bad), bad[:1]))
    # 2. the text
    white = pal[defs["INK_TEXT"]]
    missing = [p for p in on if base[p[1]][p[0]] != white]
    extra = [(x, y) for y in range(sy, sy + sh) for x in range(sx, sx + sw)
             if base[y][x] == white and (x, y) not in on]
    check("the text", not missing and not extra,
          "%d text pixel(s) missing, %d extra" % (len(missing), len(extra)))
    dark = pal[defs["INK_TEXT_LINE"]]
    unlined = [p for p in ring if base[p[1]][p[0]] != dark]
    stray = [(x, y) for y in range(sy, sy + sh) for x in range(sx, sx + sw)
             if base[y][x] == dark and (x, y) not in ring]
    check("the text's outline", not unlined and not stray,
          "%d outline pixel(s) not dark, %d dark beyond it" % (len(unlined), len(stray)))
    check("the text is on the screen",
          all(sx <= x < sx + sw and sy <= y < sy + sh for x, y in on), "it runs off")
    # 3. the window
    border = pal[defs["INK_LETTERBOX"]]
    for size in ((640, 360), (1000, 620), (333, 200), (961, 1080), (200, 100)):
        ww, wh, img = shot("drop_%dx%d" % size, size=size)
        scale = max(1, min(size[0] // W, size[1] // H))
        ox, oy = (size[0] - W * scale) // 2, (size[1] - H * scale) // 2
        bad = 0
        for y in range(wh):
            for x in range(ww):
                cx, cy = x - ox, y - oy
                want = (base[cy // scale][cx // scale]
                        if 0 <= cx < W * scale and 0 <= cy < H * scale else border)
                bad += img[y][x] != want
        check("window %dx%d (scale %d)" % (size + (scale,)), (ww, wh) == size and not bad,
              "%d pixel(s) differ" % bad)
    # 4. the animation
    frames = {n: shot("drop_f%d" % n, frame=n)[2] for n in (6, 60, 120, 170)}
    led = [(x, y) for y in range(H) for x in range(W) if rows[y][x] == defs["INK_LED"]]
    screen = [(x, y) for y in range(H) for x in range(W)
              if rows[y][x] == defs["INK_SCREEN"] and (x, y) not in on and (x, y) not in ring]
    still = [(x, y) for y in range(H) for x in range(W) if rows[y][x] not in animated]
    check("the glow changes", len({frames[n][screen[0][1]][screen[0][0]] for n in (60, 120)}
                                  | {base[screen[0][1]][screen[0][0]]}) > 1, "the screen stays the same")
    scan = next((x, y) for y in range(H) for x in range(W)
                if rows[y][x] == defs["INK_SCAN"] and (x, y) not in on and (x, y) not in ring)
    s0 = base[scan[1]][scan[0]]
    s6 = frames[6][scan[1]][scan[0]]
    g0, g6 = base[screen[0][1]][screen[0][0]], frames[6][screen[0][1]][screen[0][0]]
    # Over 6 frames the glow moves the screen and the scanlines a little;
    # the shimmer moves the scanlines more than the screen.
    check("the scanlines shimmer", sum(s6) - sum(s0) > sum(g6) - sum(g0),
          "the scanlines change no more than the screen")
    check("the light blinks", all(base[y][x] == pal[defs["INK_LED"]] for x, y in led) and
          all(frames[170][y][x] != pal[defs["INK_LED"]] for x, y in led) and
          all(frames[120][y][x] == pal[defs["INK_LED"]] for x, y in led),
          "not on at frames 0 and 120 and off at 170")
    moved = [p for p in still for n in frames if frames[n][p[1]][p[0]] != base[p[1]][p[0]]]
    check("nothing else moves", not moved, "%d pixel(s) changed" % len(moved))

    print("\n%d check(s) failed" % len(fails) if fails else "\nall checks pass")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
