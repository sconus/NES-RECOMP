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
  5. the other screens, pixel for pixel on the TV: recompiling (the name,
     cut to fit; the tall "RECOMPILING IN PROGRESS"; the bar filled to the
     progress; each stage's name), the error (the message wrapped), done;
  6. building, with app/build.c as the window uses it (--build, on its
     thread with --trace-progress), into build/app_check/builds:
     - a free test ROM, from a path with spaces: the five stages in
       order, the bar only moving forward and below 1 until the end,
       all 16 runtime files compiled (one in
       Objective-C, for recording); the program runs and passes the
       test ROM's own check; built again, no runtime file is compiled;
     - a file that isn't a ROM: "NOT AN NES ROM", nothing run;
     - a ROM of an unsupported mapper (made here): the recompiler's
       message, stopping at stage 2;
     - a runtime file that doesn't compile (a copy of the project with
       one added): the compiler's message, stopping at stage 4, and no
       program.
  7.-8. playing, and polish (the About screen, the cards, the click,
     the game window's size);
  9. without Apple's C compiler (PLAN-standalone.md step 5):
     - its screen, pixel for pixel, before and after the click (the
       command for Terminal in lower case, as it must be typed);
     - the compiler found where `xcode-select -p` says;
     - with reading /Library/Developer forbidden (sandbox-exec; first
       checked to be), a build stops at stage 1 with that screen and
       compiles nothing, and an xcode-select that fails, or names a folder
       with no clang, does the same; a game already built still plays;
     - a click on the TV there runs `xcode-select --install` (a stand-in
       here, through $NESRECOMP_XCODE_SELECT, that writes down its
       arguments), and a click beside it runs nothing.
Run by `make test-app`. Exit status 0 when all pass.
"""
import os
import re
import shutil
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


def glyph_pixels(font, s, cx, y, sx=1, sy=1):
    """The pixels of a line of text, centred on cx, as the app draws it."""
    x0 = cx - (len(s) * 6 * sx - sx) // 2
    on = set()
    for i, ch in enumerate(s):
        o = ord(ch.upper()) if ch.isalpha() else ord(ch)
        if o < 0x20 or o > 0x5F:
            o = ord("?")
        g = font[o - 0x20]
        for r in range(7):
            for c in range(5):
                if g[r] & (0x10 >> c):
                    for dy in range(sy):
                        for dx in range(sx):
                            on.add((x0 + i * 6 * sx + c * sx + dx, y + r * sy + dy))
    return on


def wrap(msg, width=18, most=5):
    """The app's line breaking (wrap in app/app.c)."""
    lines, p = [], msg
    while p and len(lines) < most:
        p = p.lstrip(" ")
        if len(p) <= width:
            if p:
                lines.append(p)
            break
        cut = width
        while cut > 0 and p[cut] != " ":
            cut -= 1
        if cut == 0:
            cut = width
        lines.append(p[:cut])
        p = p[cut:]
        if len(lines) == most and p:
            lines[-1] = lines[-1][:width - 2] + ".."
    return lines


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

    # 5. the other screens
    cx = sx + sw // 2
    dim = pal[defs["INK_MANE_HI"]]
    bar_x, bar_y, bar_w, bar_h = cx - 50, sy + 58, 100, 8

    def in_bar(x, y):
        return bar_x - 1 <= x < bar_x + bar_w + 1 and bar_y - 1 <= y < bar_y + bar_h + 1

    def screen_text(img, want_white, want_dim, skip=lambda x, y: False):
        bad = 0
        for y in range(sy, sy + sh):
            for x in range(sx, sx + sw):
                if skip(x, y):
                    continue
                bad += (img[y][x] == white) != ((x, y) in want_white)
                bad += (img[y][x] == dim) != ((x, y) in want_dim)
        return bad

    def screen(name, *args):
        path = os.path.join(OUT, name + ".png")
        subprocess.run([APP, "--screenshot", path] + list(args), check=True)
        return read_png(path)[2]

    long_name = "a rather long game name.nes"
    shown = long_name[:16] + ".."
    stages = ["CHECKING THE FILE", "RECOMPILING", "COMPILING THE GAME", "BUILDING RUNTIME", "LINKING"]
    neon, shade = pal[defs["INK_NEON"]], pal[defs["INK_SHADOW"]]
    for stage, progress in ((0, 0.0), (1, 0.13), (2, 0.42), (3, 0.77), (4, 1.0)):
        img = screen("build_%d" % stage, "--show", "build", "--rom", long_name,
                     "--stage", str(stage), "--progress", str(progress))
        w_set = glyph_pixels(font, "RECOMPILING", cx, sy + 20, 1, 2) | \
            glyph_pixels(font, "IN PROGRESS", cx, sy + 38, 1, 2)
        d_set = glyph_pixels(font, shown, cx, sy + 6) | glyph_pixels(font, stages[stage], cx, sy + 72)
        bad = screen_text(img, w_set, d_set, in_bar)
        check("build screen, stage %d: the text" % (stage + 1), not bad, "%d pixel(s) differ" % bad)
        fill = int(progress * bar_w)
        bad = 0
        for y in range(bar_y - 1, bar_y + bar_h + 1):
            for x in range(bar_x - 1, bar_x + bar_w + 1):
                if bar_x <= x < bar_x + bar_w and bar_y <= y < bar_y + bar_h:
                    lit = x - bar_x < fill
                    want = (white if y == bar_y else neon) if lit else shade
                else:
                    want = pal[defs["INK_TEXT_LINE"]]
                bad += img[y][x] != want
        check("build screen, stage %d: the bar at %d%%" % (stage + 1, round(progress * 100)),
              not bad, "%d pixel(s) differ" % bad)
    msg = "mapper 99 is not supported (supported: 0 NROM, 1 MMC1, 2 UxROM, 3 CNROM, 4 MMC3, 5 MMC5)"
    img = screen("error", "--show", "error", "--message", msg)
    lines = wrap(msg)
    w_set = glyph_pixels(font, "CAN'T RECOMPILE", cx, sy + 5, 1, 2)
    for i, line in enumerate(lines):
        w_set |= glyph_pixels(font, line, cx, sy + 25 + i * 9)
    bad = screen_text(img, w_set, glyph_pixels(font, "DROP ANOTHER FILE", cx, sy + 74))
    check("error screen (%d lines, the last cut)" % len(lines), not bad and lines[-1].endswith(".."),
          "%d pixel(s) differ" % bad)
    img = screen("done", "--show", "done", "--rom", "01-basics.nes")
    w_set = glyph_pixels(font, "DONE!", cx, sy + 24, 2, 2) | glyph_pixels(font, "BUILT AND READY", cx, sy + 48)
    d_set = glyph_pixels(font, "01-basics.nes", cx, sy + 8) | glyph_pixels(font, "DROP ANOTHER FILE", cx, sy + 70)
    bad = screen_text(img, w_set, d_set)
    check("done screen", not bad, "%d pixel(s) differ" % bad)

    # 6. building
    builds = os.path.join(OUT, "builds")
    shutil.rmtree(builds, ignore_errors=True)
    roms = os.path.join(OUT, "roms")
    os.makedirs(roms, exist_ok=True)
    free = os.path.join(ROOT, "tests", "roms", "nes-test-roms", "instr_test-v5", "rom_singles",
                        "01-basics.nes")
    spaced = os.path.join(roms, "my game (test).nes")
    shutil.copy(free, spaced)

    # The bar's arithmetic (--progress-model): each stage stays within its
    # share of the bar and never reaches its end, never moves back, the
    # shares add up to the whole bar, and done is the whole bar.
    model = subprocess.run([APP, "--progress-model"], capture_output=True, text=True).stdout
    rows = [l.split() for l in model.splitlines()]
    per = {}
    for r in rows:
        if r[0] != "done":
            per.setdefault(int(r[0]), []).append(float(r[2]))
    starts = [v[0] for _, v in sorted(per.items())]
    problems = []
    for st, vals in sorted(per.items()):
        upper = starts[st + 1] if st + 1 < len(starts) else 1.0
        if any(b < a for a, b in zip(vals, vals[1:])):
            problems.append("stage %d moves back" % (st + 1))
        if max(vals) >= upper:
            problems.append("stage %d reaches %.3f (its end is %.3f)" % (st + 1, max(vals), upper))
    done = [float(r[1]) for r in rows if r[0] == "done"]
    if done != [1.0]:
        problems.append("done is %s" % done)
    if len(starts) != 5 or starts[0] != 0.0:
        problems.append("stages start at %s" % starts)
    # The last stage's end is the whole bar: its share is what is left.
    tail = max(per.get(4, [0]))
    if not (0.99 <= tail < 1.0):
        problems.append("the last stage tops out at %.3f, not just under 1" % tail)
    check("the bar's arithmetic", not problems, "; ".join(problems))

    def build(rom, bdir, trace=True, env=None, app=APP):
        cmd = [app, "--build", rom, "--build-dir", bdir] + (["--trace-progress"] if trace else [])
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
        return r.returncode, r.stdout

    def stages_of(out):
        return [int(m) for m in re.findall(r"^stage (\d)/5", out, re.M)]

    def last_line(out):
        lines = out.strip().splitlines()
        return lines[-1] if lines else ""

    code, out = build(spaced, builds)
    seen = stages_of(out)
    prog = [float(m) for m in re.findall(r"^progress ([0-9.]+) stage", out, re.M)]
    end = re.search(r"^progress ([0-9.]+) end", out, re.M)
    check("build: the five stages in order", code == 0 and seen == [1, 2, 3, 4, 5],
          "exit %d, stages %s" % (code, seen))
    check("build: the bar only moves forward, below 1 until the end",
          len(prog) > 3 and all(b >= a for a, b in zip(prog, prog[1:])) and max(prog) < 1.0
          and end is not None and float(end.group(1)) == 1.0,
          "%d samples, max %.3f, end %s" % (len(prog), max(prog or [0]), end and end.group(1)))
    rt = re.search(r"runtime: .*", out)
    check("build: all runtime files compiled", "runtime: 16 of 16" in out, rt.group(0) if rt else "")
    exe = os.path.join(builds, "my_game__test_")
    ran = subprocess.run([exe, spaced, "--headless", "--frames", "600", "--no-save"],
                         capture_output=True, text=True) if os.path.exists(exe) else None
    check("build: the program runs and passes its test",
          ran is not None and "test status at $6000: $00" in ran.stderr,
          "no program" if ran is None else ran.stderr[-120:])
    # Playing it wrote a .missed beside the ROM: the next build takes it in;
    # the one after has nothing new.
    build(spaced, builds, trace=False)
    code, out = build(spaced, builds, trace=False)
    check("build again, nothing changed: up to date, no stage run",
          code == 0 and "up to date: " in out and stages_of(out) == [1],
          "exit %d, stages %s" % (code, stages_of(out)))
    exe_time = os.path.getmtime(exe) if os.path.exists(exe) else 0
    check("up to date: the program left as it was", exe_time and os.path.getmtime(exe) == exe_time,
          "it changed")
    t = os.path.getmtime(spaced) + 5
    os.utime(spaced, (t, t))                    # the ROM newer: built again
    code, out = build(spaced, builds, trace=False)
    rt = re.search(r"runtime: .*", out)
    check("the ROM changed: built again, no runtime file compiled",
          code == 0 and stages_of(out) == [1, 2, 3, 4, 5] and "runtime: 0 of 16" in out,
          rt.group(0) if rt else "exit %d, stages %s" % (code, stages_of(out)))
    with open(spaced + ".missed", "w") as f:    # a .missed file appears: again
        f.write("")
    code, out = build(spaced, builds, trace=False)
    check("a .missed file appeared: built again", code == 0 and stages_of(out) == [1, 2, 3, 4, 5],
          "exit %d, stages %s" % (code, stages_of(out)))
    os.remove(spaced + ".missed")
    build(spaced, builds, trace=False)
    os.remove(exe)                              # the program gone, its record kept
    code, out = build(spaced, builds, trace=False)
    check("the program deleted: built again", code == 0 and stages_of(out) == [1, 2, 3, 4, 5]
          and os.path.exists(exe), "exit %d, stages %s" % (code, stages_of(out)))
    code, out = build(os.path.join(ROOT, "tests", "suite.txt"), builds, trace=False)
    seen = stages_of(out)
    check("not a ROM: refused", code == 1 and "error: NOT AN NES ROM" in out and seen == [1],
          "exit %d, stages %s" % (code, seen))
    bad_rom = os.path.join(roms, "mapper99.nes")
    with open(bad_rom, "wb") as f:              # made here: mapper 99, empty
        f.write(b"NES\x1a\x01\x01\x30\x60" + bytes(8) + bytes(0x4000 + 0x2000))
    code, out = build(bad_rom, builds, trace=False)
    seen = stages_of(out)
    check("unsupported mapper: the recompiler's message",
          code == 1 and "error: mapper 99 is not supported" in out and seen[-1:] == [2],
          "exit %d, %s" % (code, last_line(out)))
    nestest = os.path.join(ROOT, "tests", "nestest.nes")
    if os.path.exists(nestest + ".missed"):
        code, out = build(nestest, builds, trace=False)
        log = open(os.path.join(builds, "nestest.log")).read() if code == 0 else ""
        check("a ROM's .missed file goes to the recompiler",
              code == 0 and "--missed " + nestest + ".missed" in log, "exit %d" % code)
    fake = os.path.join(OUT, "fakeroot")
    shutil.rmtree(fake, ignore_errors=True)
    shutil.copytree(os.path.join(ROOT, "runtime"), os.path.join(fake, "runtime"))
    # The app and its recompiler copied together, as in the bundle, so
    # the recompiler can be made newer; SDL2 beside them as in build/.
    fbin = os.path.join(fake, "bin")
    os.makedirs(fbin)
    for name in ("nesrecomp-app", "nesrecomp-recomp"):
        shutil.copy2(os.path.join(ROOT, "build", name), fbin)
    os.symlink(os.path.join(ROOT, "build", "sdl2"), os.path.join(fbin, "sdl2"))
    fapp = os.path.join(fbin, "nesrecomp-app")
    fenv = dict(os.environ, NESRECOMP_ROOT=fake)
    fh = os.path.join(OUT, "builds_header")
    shutil.rmtree(fh, ignore_errors=True)
    build(spaced, fh, trace=False, env=fenv, app=fapp)
    rtd = os.path.join(fake, "runtime")
    later = max(os.path.getmtime(os.path.join(rtd, f)) for f in os.listdir(rtd)) + 10
    rtobj = os.path.join(fh, "app-rt")
    for name in os.listdir(rtobj) if os.path.isdir(rtobj) else []:   # objects older...
        os.utime(os.path.join(fh, "app-rt", name), (later - 5, later - 5))
    os.utime(os.path.join(fake, "runtime", "rt.h"), (later, later))  # ...than a header
    code, out = build(spaced, fh, trace=False, env=fenv, app=fapp)
    rt = re.search(r"runtime: .*", out)
    check("a newer runtime header: every runtime file again", code == 0 and "runtime: 16 of 16" in out,
          rt.group(0) if rt else "exit %d" % code)
    code, out = build(spaced, fh, trace=False, env=fenv, app=fapp)
    up = code == 0 and "up to date: " in out
    rc = os.path.join(fbin, "nesrecomp-recomp")
    later = os.path.getmtime(rc) + 20
    os.utime(rc, (later, later))
    code, out = build(spaced, fh, trace=False, env=fenv, app=fapp)
    check("a newer recompiler: built again", up and code == 0 and stages_of(out) == [1, 2, 3, 4, 5],
          "up to date first: %s; then exit %d, stages %s" % (up, code, stages_of(out)))
    with open(os.path.join(fake, "runtime", "zz_broken.c"), "w") as f:
        f.write("this is not C;\n")
    fb = os.path.join(OUT, "builds_broken")
    shutil.rmtree(fb, ignore_errors=True)
    code, out = build(spaced, fb, trace=False, env=dict(os.environ, NESRECOMP_ROOT=fake))
    seen = stages_of(out)
    check("a runtime file that doesn't compile: the compiler's message",
          code == 1 and "error: the C compiler:" in out and seen[-1:] == [4]
          and not os.path.exists(os.path.join(fb, "my_game__test_")),
          "exit %d, %s" % (code, last_line(out)))

    # 7. playing (play.c, as the window uses it after a build)
    for name, title, msg in (("stopped", "THE GAME STOPPED", "unknown opcode $02 at $C000"),):
        img = screen(name, "--show", name, "--message", msg)
        w_set = glyph_pixels(font, title, cx, sy + 5, 1, 2)
        for i, line in enumerate(wrap(msg)):
            w_set |= glyph_pixels(font, line, cx, sy + 25 + i * 9)
        bad = screen_text(img, w_set, glyph_pixels(font, "DROP ANOTHER FILE", cx, sy + 74))
        check("the game-stopped screen", not bad, "%d pixel(s) differ" % bad)
    img = screen("play", "--show", "play", "--rom", "01-basics.nes")
    w_set = glyph_pixels(font, "NOW PLAYING", cx, sy + 30, 1, 2)
    d_set = glyph_pixels(font, "01-basics.nes", cx, sy + 14) | \
        glyph_pixels(font, "QUIT THE GAME TO", cx, sy + 58) | glyph_pixels(font, "COME BACK HERE", cx, sy + 67)
    bad = screen_text(img, w_set, d_set)
    check("the now-playing screen", not bad, "%d pixel(s) differ" % bad)

    pb = os.path.join(OUT, "builds_play")
    shutil.rmtree(pb, ignore_errors=True)
    proms = os.path.join(OUT, "play_roms")
    shutil.rmtree(proms, ignore_errors=True)
    os.makedirs(proms)
    game = os.path.join(proms, "basics.nes")
    shutil.copy(free, game)
    headless = "--headless --frames 600 --no-save"

    def play(*args):
        r = subprocess.run([APP] + list(args), capture_output=True, text=True, timeout=120)
        return r.returncode, r.stdout

    code, out = play("--build", game, "--build-dir", pb, "--then-play", "--play-args", headless)
    glog = os.path.join(pb, "basics.game.log")
    text_log = open(glog).read() if os.path.exists(glog) else ""
    check("build and play: the game ends well", code == 0 and "played: the game ended well" in out,
          "exit %d, %s" % (code, last_line(out)))
    check("build and play: the game ran (its test passed)", "test status at $6000: $00" in text_log,
          "no result in its log")
    first = re.search(r"(\d+) spot\(s\) ran in the interpreter", text_log)
    check("the game wrote its .missed beside the ROM", os.path.exists(game + ".missed"),
          "no %s" % os.path.basename(game + ".missed"))
    code, out = play("--build", game, "--build-dir", pb, "--then-play", "--play-args", headless)
    blog = open(os.path.join(pb, "basics.log")).read()
    text_log = open(glog).read() if os.path.exists(glog) else ""
    again = re.search(r"(\d+) spot\(s\) ran in the interpreter", text_log)
    check("the next build uses it, and less is interpreted",
          code == 0 and "--missed " + game + ".missed" in blog and first and again
          and int(again.group(1)) < int(first.group(1)),
          "exit %d, interpreted %s then %s" % (code, first and first.group(1), again and again.group(1)))
    jam = os.path.join(proms, "jam.nes")
    with open(jam, "wb") as f:                  # made here: every byte $02
        prg = bytearray([0x02] * 0x4000)
        prg[0x3FFA:0x4000] = bytes([0x00, 0xC0, 0x00, 0xC0, 0x00, 0xC0])
        f.write(b"NES\x1a\x01\x01\x00\x00" + bytes(8) + bytes(prg) + bytes(0x2000))
    code, out = play("--build", jam, "--build-dir", pb, "--then-play", "--play-args", headless)
    check("a game that stops: its message", code == 1 and "error: unknown opcode $02 at $C000" in out,
          "exit %d, %s" % (code, last_line(out)))
    crash = os.path.join(proms, "crash.sh")
    with open(crash, "w") as f:
        f.write("#!/bin/sh\nkill -SEGV $$\n")
    os.chmod(crash, 0o755)
    code, out = play("--play-only", crash, game)
    check("a game that crashes: the signal", code == 1 and "error: the game crashed (signal 11" in out,
          "exit %d, %s" % (code, last_line(out)))
    fails3 = os.path.join(proms, "fails.sh")
    with open(fails3, "w") as f:
        f.write("#!/bin/sh\necho 'no window for you'\nexit 3\n")
    os.chmod(fails3, 0o755)
    code, out = play("--play-only", fails3, game)
    check("a game that fails: its status and last line",
          code == 1 and "error: the game ended with status 3: no window for you" in out,
          "exit %d, %s" % (code, last_line(out)))
    code, out = play("--play-only", os.path.join(proms, "no such game"), game)
    check("a game that can't start: said so", code == 1 and "error: couldn't start the game" in out,
          "exit %d, %s" % (code, last_line(out)))

    # 8. polish: the About screen, the controls cards, where a click opens
    # the file picker, and the game window's size remembered.
    img = screen("about", "--show", "about")
    w_set = glyph_pixels(font, "NES RECOMP", cx, sy + 4, 1, 2) | \
        glyph_pixels(font, "BY SERGE AND CLAUDE", cx, sy + 46)
    d_set = set()
    for text_, y in (("FOR EDUCATIONAL", 23), ("PURPOSES ONLY", 32), ("FREE SOFTWARE UNDER", 61),
                     ("THE MIT LICENSE", 70)):
        d_set |= glyph_pixels(font, text_, cx, sy + y)
    bad = screen_text(img, w_set, d_set)
    check("the About screen", not bad, "%d pixel(s) differ" % bad)
    lic_path = os.path.join(ROOT, "LICENSE")
    lic = open(lic_path).read() if os.path.exists(lic_path) else ""
    check("the LICENSE file: MIT, Serge and Claude",
          lic.startswith("MIT License") and "Copyright (c) 2026 Serge and Claude" in lic, "not as expected")

    def at(s, x):                               # text starting at x
        return x + (len(s) * 6 - 1) // 2
    for name, title, rows in (
            ("card", "CONTROLS", [("ARROWS", "D-PAD"), ("X", "A BUTTON"), ("Z", "B BUTTON"),
                                  ("RETURN", "START"), ("R.SHIFT", "SELECT"), ("M", "MUTE"),
                                  ("R", "RESET"), ("V", "RECORD"), ("ESC", "QUIT")]),
            ("card_music", "MUSIC PLAYER", [("LEFT", "LAST SONG"), ("RIGHT", "NEXT SONG"),
                                            ("R", "RESTART"), ("M", "MUTE"), ("V", "RECORD"),
                                            ("ESC", "QUIT")])):
        img = screen(name, "--show", name)
        # Nine rows fit only under a title of one height (PLAN-standalone
        # step 6 added V).
        small = len(rows) > 8
        w_set = glyph_pixels(font, title, cx, sy + (2 if small else 3), 1, 1 if small else 2)
        top = 12 if small else 20
        d_set = set()
        for i, (k, v) in enumerate(rows):
            w_set |= glyph_pixels(font, k, at(k, sx + 9), sy + top + i * 8)
            d_set |= glyph_pixels(font, v, at(v, sx + 57), sy + top + i * 8)
        bad = screen_text(img, w_set, d_set)
        check("the %s card" % title.lower(), not bad, "%d pixel(s) differ" % bad)

    wrong = []
    for size in ((960, 540), (1000, 620), (640, 360), (320, 180)):
        scale = max(1, min(size[0] // W, size[1] // H))
        ox, oy = (size[0] - W * scale) // 2, (size[1] - H * scale) // 2
        x0, y0 = ox + sx * scale, oy + sy * scale
        x1, y1 = ox + (sx + sw) * scale - 1, oy + (sy + sh) * scale - 1
        for x, y, want in ((x0, y0, "tv"), (x1, y1, "tv"), (x0 - 1, y0, "outside"),
                           (x0, y0 - 1, "outside"), (x1 + 1, y1, "outside"), (x1, y1 + 1, "outside"),
                           ((x0 + x1) // 2, (y0 + y1) // 2, "tv")):
            got = subprocess.run([APP, "--hit-test", "%dx%d" % size, str(x), str(y)],
                                 capture_output=True, text=True).stdout.strip()
            if got != want:
                wrong.append("%dx%d (%d,%d): %s" % (size + (x, y, got)))
    check("a click opens the file picker exactly on the TV's screen", not wrong, "; ".join(wrong[:3]))

    remember = os.path.join(OUT, "prefs.txt")
    if os.path.exists(remember):
        os.remove(remember)
    if os.path.exists(exe):
        subprocess.run([exe, spaced, "--headless", "--frames", "10", "--no-save", "--scale", "5",
                        "--remember-size", remember], capture_output=True)
    said = open(remember).read() if os.path.exists(remember) else ""
    check("the game remembers its window's size", said == "game_scale 5\n", repr(said))

    # 9. without Apple's C compiler.
    lower = {                                   # the lowercase letters it draws
        "a": ".....|.....|.###.|....#|.####|#...#|.####",
        "c": ".....|.....|.###.|#....|#....|#...#|.###.",
        "d": "....#|....#|.##.#|#..##|#...#|#..##|.##.#",
        "e": ".....|.....|.###.|#...#|#####|#....|.###.",
        "i": "..#..|.....|.##..|..#..|..#..|..#..|.###.",
        "l": ".##..|..#..|..#..|..#..|..#..|..#..|.###.",
        "n": ".....|.....|#.##.|##..#|#...#|#...#|#...#",
        "o": ".....|.....|.###.|#...#|#...#|#...#|.###.",
        "s": ".....|.....|.####|#....|.###.|....#|####.",
        "t": ".#...|.#...|###..|.#...|.#...|.#..#|..##.",
        "x": ".....|.....|#...#|.#.#.|..#..|.#.#.|#...#",
    }

    def lower_pixels(text_, cx_, y):
        x0 = cx_ - (len(text_) * 6 - 1) // 2
        on = set()
        for i, ch in enumerate(text_):
            if ch in lower:
                for rr, row in enumerate(lower[ch].split("|")):
                    on |= {(x0 + i * 6 + c, y + rr) for c in range(5) if row[c] == "#"}
            else:
                on |= glyph_pixels(font, ch, x0 + i * 6 + 2, y)
        return on

    img = screen("needcc", "--show", "needcc")
    w_set = glyph_pixels(font, "NEEDS APPLE'S", cx, sy + 5, 1, 2) | \
        glyph_pixels(font, "C COMPILER", cx, sy + 21, 1, 2) | \
        glyph_pixels(font, "CLICK TO INSTALL IT", cx, sy + 41) | \
        lower_pixels("xcode-select", cx, sy + 63) | lower_pixels("--install", cx, sy + 72)
    bad = screen_text(img, w_set, glyph_pixels(font, "OR IN TERMINAL:", cx, sy + 54))
    check("the no-compiler screen (the command in lower case)", not bad, "%d pixel(s) differ" % bad)
    img = screen("needcc_clicked", "--show", "needcc_clicked")
    w_set = glyph_pixels(font, "NEEDS APPLE'S", cx, sy + 5, 1, 2) | \
        glyph_pixels(font, "C COMPILER", cx, sy + 21, 1, 2) | \
        glyph_pixels(font, "WHEN IT'S DONE,", cx, sy + 46)
    bad = screen_text(img, w_set, glyph_pixels(font, "DROP THE ROM AGAIN", cx, sy + 60))
    check("the no-compiler screen after the click", not bad, "%d pixel(s) differ" % bad)

    xs = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True).stdout.strip()
    info = subprocess.run([APP, "--sdl-info"], capture_output=True, text=True).stdout
    cc_line = [l for l in info.splitlines() if l.startswith("compiler ")]
    check("the compiler: found where xcode-select -p says",
          xs and len(cc_line) == 1 and cc_line[0][9:].startswith(xs + "/") and cc_line[0].endswith("/clang"),
          "xcode-select %r, app %s" % (xs, cc_line))
    # /Library/Developer unreadable, as on a Mac without the tools. And
    # Apple's stand-ins (/usr/bin/cc and the like) can't run: on such a
    # Mac they pop up Apple's installer, which a wrong app (a break) would
    # otherwise do here on a real Mac.
    nocc = ("(version 1)(allow default)(deny file-read* (subpath \"/Library/Developer\"))"
            "(deny process-exec (literal \"/usr/bin/cc\") (literal \"/usr/bin/clang\")"
            " (literal \"/usr/bin/gcc\") (literal \"/usr/bin/c++\") (literal \"/usr/bin/clang++\")"
            " (literal \"/usr/bin/xcrun\") (literal \"/usr/bin/ld\") (literal \"/usr/bin/make\"))")
    probe = subprocess.run(["sandbox-exec", "-p", nocc, "/bin/ls", "/Library/Developer"],
                           capture_output=True, text=True)
    probe_cc = subprocess.run(["sandbox-exec", "-p", nocc, "/usr/bin/cc", "--version"],
                              capture_output=True, text=True)
    check("the sandbox really forbids reading /Library/Developer, and running cc",
          probe.returncode != 0 and probe_cc.returncode != 0 and "clang" not in probe_cc.stdout,
          "ls %d, cc %d" % (probe.returncode, probe_cc.returncode))
    ncdir = os.path.join(OUT, "builds_nocc")
    shutil.rmtree(ncdir, ignore_errors=True)
    ncrom = os.path.join(roms, "no compiler.nes")
    shutil.copy(free, ncrom)

    def nocc_build(env=None, sandbox=True, *more):
        cmd = [APP, "--build", ncrom, "--build-dir", ncdir] + list(more)
        if sandbox:
            cmd = ["sandbox-exec", "-p", nocc] + cmd
        return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)

    def stopped_at_1(r):
        made = sorted(f for f in os.listdir(ncdir) if f.startswith("no_compiler")) \
            if os.path.isdir(ncdir) else []
        return (r.returncode == 1 and "screen: needcc" in r.stdout and stages_of(r.stdout) == [1]
                and "error: needs Apple's C compiler: xcode-select --install" in r.stdout
                and made == []), made

    r = nocc_build()
    ok, made = stopped_at_1(r)
    check("no compiler: stops at stage 1 with its screen, nothing compiled", ok,
          "exit %d, %s, made %s" % (r.returncode, last_line(r.stdout), made))
    fake = os.path.join(OUT, "fake_xcode_select")
    os.makedirs(fake, exist_ok=True)
    said = os.path.join(fake, "said.txt")
    fails_xs = os.path.join(fake, "fails.sh")
    with open(fails_xs, "w") as f:
        f.write("#!/bin/sh\necho \"$@\" >> '%s'\n"
                "echo 'xcode-select: error: unable to get active developer directory' >&2\nexit 2\n" % said)
    empty_xs = os.path.join(fake, "empty.sh")
    with open(empty_xs, "w") as f:
        f.write("#!/bin/sh\necho '%s'\n" % fake)
    for x in (fails_xs, empty_xs):
        os.chmod(x, 0o755)
    for x, what in ((fails_xs, "an xcode-select that fails"), (empty_xs, "a folder with no clang")):
        r = nocc_build(dict(os.environ, NESRECOMP_XCODE_SELECT=x), False)
        ok, made = stopped_at_1(r)
        check("no compiler, %s: the same" % what, ok,
              "exit %d, %s, made %s" % (r.returncode, last_line(r.stdout), made))
    r = nocc_build(None, False)
    built = r.returncode == 0 and "built: " in r.stdout
    r = nocc_build(None, True, "--then-play", "--play-args", "--headless --frames 600 --no-save")
    check("no compiler, a game already built: up to date, and it plays",
          built and "up to date" in r.stdout and "played: the game ended well" in r.stdout,
          "built first: %s; %s" % (built, last_line(r.stdout)))
    if os.path.exists(said):
        os.remove(said)
    env = dict(os.environ, NESRECOMP_XCODE_SELECT=fails_xs)
    on = subprocess.run([APP, "--click-test", "needcc", "960x540", "480", "200"],
                        capture_output=True, text=True, env=env).stdout
    ran = open(said).read() if os.path.exists(said) else ""
    check("a click on the TV there runs xcode-select --install",
          "click: install" in on and ran == "--install\n", "%r, it was given %r" % (on.strip(), ran))
    if os.path.exists(said):
        os.remove(said)
    off = subprocess.run([APP, "--click-test", "needcc", "960x540", "20", "20"],
                         capture_output=True, text=True, env=env).stdout
    check("a click beside the TV runs nothing", "click: nothing" in off and not os.path.exists(said),
          off.strip())

    print("\n%d check(s) failed" % len(fails) if fails else "\nall checks pass")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
