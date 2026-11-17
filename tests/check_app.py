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
       all 18 runtime files compiled (one in
       Objective-C, for recording on the Mac); the program runs and passes the
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
  10. under the hood (PLAN-standalone.md step 7):
     - the screen pixel for pixel, from a history made here (the bars
       scaled to the most spots shown, at least a line each, the last 10
       runs, the latest white), and with no history;
     - the share: rounded down, never 100% while anything ran in the
       interpreter;
     - a free test ROM built without its .missed and played 3 times
       (--then-play): the history grows by one line a game, its numbers
       are the recompiler's and the game's own lines for that run, the
       spots shrink, and a game already built keeps its translated
       count; the last game's name is kept for H;
     - the runtime's own counts, against what is known without them:
       nestest built without its .missed and run from reset (all of it
       translated) counts nothing as interpreted, and, with --trace, as
       many instructions as it traced; run from $C000 (never traced from
       there), nearly all interpreted.
  11. the 6502 next to its C (PLAN-standalone.md step 8), from
     nestest's listing and C: the view pixel for pixel at its start (the
     reset routine), after scrolling (down, down, a page, up), after Tab
     three times (each to the next JSR target or entry), and with a long
     C line cut; and the app's build writes NAME.listing beside NAME.c,
     every instruction's C where the listing says, and a build without
     its listing is built again.
  12. supporting it: the link is Ko-fi's polygonlegends page; D on the
     About screen opens it and another key leaves; the app menu has
     "Support NES RECOMP..." right after About, and choosing it opens
     the page (a stand-in for `open` writes down what it was given, so
     no browser opens).
Run by `make test-app`. Exit status 0 when all pass.

On Windows (PLAN-windows.md step 4; the GitHub workflow runs it there)
the same, with the app in build/windows/app (tools/make_windows_app.py),
but for what is the Mac's alone: 9.'s Apple compiler (its screens are
still checked), and the app menu, which on Windows is the window's own
("Support NES RECOMP..." last, after a line). Its own checks there: the
crash an exception, not a signal; the stand-ins programs
(tests/stand_in.c), not scripts. On both: builds go to the app's folder
(~/Library/Application Support/NES RECOMP, %LOCALAPPDATA%\\NES RECOMP),
and SDL2's library is copied beside each game.
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
sys.path.insert(0, HERE)
import toolchain  # noqa: E402

WIN = toolchain.WIN
EXE = toolchain.EXE
WIN_APP_DIR = os.path.join(ROOT, "build", "windows", "app")
APP = os.environ.get("NESRECOMP_APP") or (os.path.join(WIN_APP_DIR, "nesrecomp-app.exe") if WIN
                                          else os.path.join(ROOT, "build", "nesrecomp-app"))
OUT = os.path.join(ROOT, "build", "app_check")
# The runtime's files a build compiles: its .c, and on the Mac record_mac.m.
RT_N = len(toolchain.runtime_sources())
hung = []                       # a build or game that never finished: the rest skipped


def run_app(cmd, env=None, timeout=300 if WIN else 120):
    """(status, stdout) of the app; after one never finished, nothing more
    is run (status -9)."""
    if hung:
        return -9, "(not run: %s never finished)" % hung[0]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        hung.append(" ".join(os.path.basename(c) for c in cmd[:3]))
        return -9, "(it never finished: %d s)" % timeout
    return r.returncode, r.stdout


class AppRun:
    """run_app's result, as subprocess.run's (returncode, stdout)."""
    def __init__(self, cmd, timeout=300 if WIN else 120, env=None):
        self.returncode, self.stdout = run_app(cmd, env, timeout)


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
        return run_app(cmd, env)

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
    check("build: all runtime files compiled", "runtime: %d of %d" % (RT_N, RT_N) in out,
          rt.group(0) if rt else "")
    exe = os.path.join(builds, "my_game__test_" + EXE)
    beside = os.path.join(builds, "SDL2.dll") if WIN else os.path.join(builds, "lib", "libSDL2.dylib")
    check("build: SDL2's library copied beside the game", os.path.exists(beside), "no %s" % beside)
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
          code == 0 and stages_of(out) == [1, 2, 3, 4, 5] and "runtime: 0 of %d" % RT_N in out,
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
    if WIN:                                     # the app's whole folder
        shutil.copytree(WIN_APP_DIR, fbin)
    else:
        os.makedirs(fbin)
        for name in ("nesrecomp-app", "nesrecomp-recomp"):
            shutil.copy2(os.path.join(ROOT, "build", name), fbin)
        os.symlink(os.path.join(ROOT, "build", "sdl2"), os.path.join(fbin, "sdl2"))
    fapp = os.path.join(fbin, "nesrecomp-app" + EXE)
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
    check("a newer runtime header: every runtime file again",
          code == 0 and "runtime: %d of %d" % (RT_N, RT_N) in out,
          rt.group(0) if rt else "exit %d" % code)
    code, out = build(spaced, fh, trace=False, env=fenv, app=fapp)
    up = code == 0 and "up to date: " in out
    rc = os.path.join(fbin, "nesrecomp-recomp" + EXE)
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
          and not os.path.exists(os.path.join(fb, "my_game__test_" + EXE)),
          "exit %d, %s" % (code, last_line(out)))

    # Where builds go when not told: the app's folder (a scratch home here).
    ahome = os.path.join(OUT, "a home")
    aenv = {k: v for k, v in os.environ.items() if k != "NESRECOMP_ROOT"}
    aenv.update(HOME=ahome, LOCALAPPDATA=os.path.join(ahome, "AppData", "Local"))
    info = subprocess.run([APP, "--sdl-info"], capture_output=True, text=True, env=aenv).stdout
    want = os.path.join(ahome, "AppData", "Local", "NES RECOMP") if WIN else \
        os.path.join(ahome, "Library", "Application Support", "NES RECOMP")
    got = [l[7:] for l in info.splitlines() if l.startswith("builds ")]
    check("builds go to the app's folder (%s)" % want.replace(ahome, "~"), got == [want],
          "%s" % got)

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

    def play(*args, env=None):
        return run_app([APP] + list(args), env)

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
    if WIN:
        # Stand-ins: a program (tests/stand_in.c), told what to do.
        stand_in = os.path.join(proms, "stand_in.exe")
        subprocess.run(toolchain.cc() + ["-O1", "-o", stand_in, os.path.join(HERE, "stand_in.c")],
                       capture_output=True)
        code, out = play("--play-only", stand_in, game, env=dict(os.environ, STANDIN_CRASH="1"))
        check("a game that crashes: the exception",
              code == 1 and "error: the game crashed (exception 0xC0000005, an access violation)" in out,
              "exit %d, %s" % (code, last_line(out)))
        code, out = play("--play-only", stand_in, game,
                         env=dict(os.environ, STANDIN_SAY="no window for you", STANDIN_EXIT="3"))
    else:
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
    w_set = glyph_pixels(font, "NES RECOMP", cx, sy + 3, 1, 2) | \
        glyph_pixels(font, "BY SERGE AND CLAUDE", cx, sy + 42)
    d_set = set()
    for text_, y in (("FOR EDUCATIONAL", 21), ("PURPOSES ONLY", 30), ("FREE SOFTWARE UNDER", 54),
                     ("THE MIT LICENSE", 63)):
        d_set |= glyph_pixels(font, text_, cx, sy + y)
    bad = screen_text(img, w_set, d_set)
    n_set = glyph_pixels(font, "SUPPORT IT: PRESS D", cx, sy + 77)
    bad += sum((img[y][x] == neon) != ((x, y) in n_set)
               for y in range(sy, sy + sh) for x in range(sx, sx + sw))
    check("the About screen (with \"SUPPORT IT: PRESS D\" in pink)", not bad, "%d pixel(s) differ" % bad)

    # Supporting it (app/support.h): the link, D on the About screen, and
    # the app menu's item, with a stand-in for `open` that writes down
    # what it was given (so no browser opens).
    KOFI = "https://ko-fi.com/polygonlegends"
    url = subprocess.run([APP, "--support-url"], capture_output=True, text=True).stdout.strip()
    check("the support link is Ko-fi's polygonlegends page", url == KOFI, repr(url))
    sdir = os.path.join(OUT, "support")
    shutil.rmtree(sdir, ignore_errors=True)
    os.makedirs(sdir)
    said = os.path.join(sdir, "opened.txt")
    if WIN:
        fake_open = os.path.join(sdir, "open.exe")
        subprocess.run(toolchain.cc() + ["-O1", "-o", fake_open, os.path.join(HERE, "stand_in.c")],
                       capture_output=True)
        oenv = dict(os.environ, NESRECOMP_OPEN=fake_open, STANDIN_LOG=said)
    else:
        fake_open = os.path.join(sdir, "open.sh")
        with open(fake_open, "w") as f:
            f.write("#!/bin/sh\necho \"$@\" >> '%s'\n" % said)
        os.chmod(fake_open, 0o755)
        oenv = dict(os.environ, NESRECOMP_OPEN=fake_open)
    r_ = AppRun([APP, "--key-test", "about", "d"], env=oenv)
    got = open(said).read() if os.path.exists(said) else ""
    check("D on the About screen opens the support page", "key: support" in r_.stdout and got == KOFI + "\n",
          "%r, opened %r" % (r_.stdout.strip(), got))
    if os.path.exists(said):
        os.remove(said)
    r_ = AppRun([APP, "--key-test", "about", "x"], env=oenv)
    check("another key on the About screen leaves it, opening nothing",
          "key: leave" in r_.stdout and not os.path.exists(said), r_.stdout.strip())
    r_ = AppRun([APP, "--menu-test", "--choose-support"], env=oenv, timeout=60)
    items = r_.stdout.splitlines()
    got = open(said).read() if os.path.exists(said) else ""
    if WIN:
        check("the window's menu: \"Support NES RECOMP\u2026\" last, after a line (and Close before)",
              len(items) > 4 and items[0] == "added 0" and any("Close" in i for i in items[1:-3])
              and items[-3:-1] == ["-", "Support NES RECOMP\u2026"], "%s" % items)
    else:
        check("the app menu: \"Support NES RECOMP\u2026\" right after About",
              len(items) > 3 and items[0] == "added 0" and items[1].startswith("About ")
              and items[2] == "Support NES RECOMP\u2026", "%s" % items[:4])
    check("choosing it opens the support page", "chose: 0" in r_.stdout and got == KOFI + "\n",
          "%s, opened %r" % (items[-1:], got))
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
        # and the rest, for the code view (step 8)
        "`": ".#...|..#..|.....|.....|.....|.....|.....",
        "b": "#....|#....|#.##.|##..#|#...#|#...#|####.",
        "f": "..##.|.#..#|.#...|###..|.#...|.#...|.#...",
        "g": ".....|.....|.####|#...#|.####|....#|.###.",
        "h": "#....|#....|#.##.|##..#|#...#|#...#|#...#",
        "j": "...#.|.....|..##.|...#.|...#.|#..#.|.##..",
        "k": "#....|#....|#..#.|#.#..|##...|#.#..|#..#.",
        "m": ".....|.....|##.#.|#.#.#|#.#.#|#...#|#...#",
        "p": ".....|.....|####.|#...#|####.|#....|#....",
        "q": ".....|.....|.##.#|#..##|.####|....#|....#",
        "r": ".....|.....|#.##.|##..#|#....|#....|#....",
        "u": ".....|.....|#...#|#...#|#...#|#..##|.##.#",
        "v": ".....|.....|#...#|#...#|#...#|.#.#.|..#..",
        "w": ".....|.....|#...#|#...#|#.#.#|#.#.#|.#.#.",
        "y": ".....|.....|#...#|#...#|.####|....#|.###.",
        "z": ".....|.....|#####|...#.|..#..|.#...|#####",
        "{": "...#.|..#..|..#..|.#...|..#..|..#..|...#.",
        "|": "..#..|..#..|..#..|..#..|..#..|..#..|..#..",
        "}": ".#...|..#..|..#..|...#.|..#..|..#..|.#...",
        "~": ".....|.....|.#...|#.#.#|...#.|.....|.....",
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

    if not WIN:                 # Apple's compiler: the Mac's alone
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

    # 10. under the hood.
    def hood_screen(runs):
        """What the app draws: the texts (white, dim) and the bars."""
        w_set = glyph_pixels(font, "UNDER THE HOOD", cx, sy + 2, 1, 2)
        d_set, bars = set(), {}
        if not runs:
            return w_set, glyph_pixels(font, "PLAY A GAME FIRST", cx, sy + 40), bars
        last = runs[-1]
        native, interp = last[3], last[4]
        if not interp:
            share = "100%"
        else:
            h = native * 10000 // (native + interp)
            share = "%d.%02d%%" % (h // 100, h % 100)
        for text_, y in (("TRANSLATED: %d" % last[1], 19), ("RAN AS C: " + share, 28),
                         ("RUN %d, SPOTS: %d" % (last[0], last[2]), 37)):
            w_set |= glyph_pixels(font, text_, cx, sy + y)
        d_set = glyph_pixels(font, "A SPOT: WHERE THE", cx, sy + 60) | \
            glyph_pixels(font, "INTERPRETER STARTED", cx, sy + 69)
        w_set |= glyph_pixels(font, "C: SEE THE CODE", cx, sy + 78)
        shown = runs[-10:]
        most = max([1] + [r_[2] for r_ in shown])
        width = len(shown) * 11 - 3
        x0 = cx - width // 2
        for i, r_ in enumerate(shown):
            h = max(1, (r_[2] * 12 + most - 1) // most)
            colour = "white" if i == len(shown) - 1 else "neon"
            for yy in range(sy + 58 - h, sy + 58):
                for xx in range(x0 + i * 11, x0 + i * 11 + 8):
                    bars[(xx, yy)] = colour
        return w_set, d_set, bars

    def hood_bad(img, runs):
        w_set, d_set, bars = hood_screen(runs)
        bad = 0
        for y in range(sy, sy + sh):
            for x in range(sx, sx + sw):
                if (x, y) in bars:
                    bad += img[y][x] != (white if bars[(x, y)] == "white" else neon)
                    continue
                bad += (img[y][x] == white) != ((x, y) in w_set)
                bad += (img[y][x] == dim) != ((x, y) in d_set)
                bad += img[y][x] == neon and (x, y) not in w_set | d_set
        return bad

    hist = os.path.join(OUT, "made.history")
    made = [(i + 1, 800 + 3 * i, sp, 1000000 - 7 * i, 7 * i)
            for i, sp in enumerate([40, 33, 20, 25, 12, 9, 9, 4, 2, 1, 0, 0])]
    with open(hist, "w") as f:
        for r_ in made:
            f.write("run %d translated %d spots %d native %d interp %d\n" % r_)
    img = screen("hood", "--show", "hood", "--history", hist)
    bad = hood_bad(img, made)
    check("under the hood: 12 runs (the last 10 as bars), pixel for pixel", not bad,
          "%d pixel(s) differ" % bad)
    few = made[:3]
    with open(hist, "w") as f:
        for r_ in few:
            f.write("run %d translated %d spots %d native %d interp %d\n" % r_)
    img = screen("hood3", "--show", "hood", "--history", hist)
    bad = hood_bad(img, few)
    check("under the hood: 3 runs, pixel for pixel", not bad, "%d pixel(s) differ" % bad)
    img = screen("hood_none", "--show", "hood", "--history", os.path.join(OUT, "no such history"))
    bad = hood_bad(img, [])
    check("under the hood, nothing played yet", not bad, "%d pixel(s) differ" % bad)
    shares = []
    for native, interp, want in ((99999, 1, "99.99%"), (1999999, 1, "99.99%"), (5, 0, "100%"),
                                 (1, 3, "25.00%"), (0, 0, "-")):
        with open(hist, "w") as f:
            f.write("run 1 translated 5 spots 1 native %d interp %d\n" % (native, interp))
        img = screen("hood_share", "--show", "hood", "--history", hist)
        w_set = glyph_pixels(font, "RAN AS C: " + want, cx, sy + 28)
        lit = {(x, y) for y in range(sy + 27, sy + 36) for x in range(sx, sx + sw) if img[y][x] == white}
        shares.append((native, interp, want, lit == w_set))
    check("the share: rounded down, never 100% while anything was interpreted",
          all(ok for *_, ok in shares), "%s" % [s_ for s_ in shares if not s_[3]])

    hb = os.path.join(OUT, "builds_hood")
    shutil.rmtree(hb, ignore_errors=True)
    hroms = os.path.join(OUT, "hood roms")
    shutil.rmtree(hroms, ignore_errors=True)
    os.makedirs(hroms)
    hrom = os.path.join(hroms, "01-basics.nes")
    shutil.copy(free, hrom)                     # no .missed yet
    runs, lines_ok, problems = [], True, []
    for k in range(3):
        pre = None
        if k == 2:      # the third: built first, so the play finds it up to date
            run_app([APP, "--build", hrom, "--build-dir", hb])
            pl = os.path.join(hb, "01-basics.log")
            pre = re.search(r"translated (\d+) instructions", open(pl).read() if os.path.exists(pl) else "")
        r_ = AppRun([APP, "--build", hrom, "--build-dir", hb, "--then-play", "--play-args",
                     "--headless --frames 600 --no-save"], timeout=300)
        m = re.search(r"hood: run (\d+) translated (-?\d+) spots (\d+) native (\d+) interp (\d+)",
                      r_.stdout)
        if not m:
            problems.append("game %d: no hood line (%s)" % (k + 1, last_line(r_.stdout)))
            break
        run_ = tuple(int(g) for g in m.groups())
        runs.append(run_)
        blog = open(os.path.join(hb, "01-basics.log")).read() if os.path.exists(os.path.join(hb, "01-basics.log")) else ""
        gpath = os.path.join(hb, "01-basics.game.log")
        glog = open(gpath).read() if os.path.exists(gpath) else ""
        t = re.search(r"translated (\d+) instructions", blog)
        sp = re.search(r"(\d+) spot\(s\) ran in the interpreter", glog)
        ran = re.search(r"ran (\d+) instruction\(s\) as translated C, (\d+) in the interpreter", glog)
        if k < 2 and (not t or int(t.group(1)) != run_[1]):
            problems.append("game %d: translated %d, the recompiler said %s" % (k + 1, run_[1], t and t.group(1)))
        if k == 2 and ("up to date" not in r_.stdout or not pre or run_[1] != int(pre.group(1))):
            problems.append("game 3 (up to date: %s): translated %d, the build before it said %s" % (
                "up to date" in r_.stdout, run_[1], pre and pre.group(1)))
        if (int(sp.group(1)) if sp else 0) != run_[2]:
            problems.append("game %d: %d spots, the game said %s" % (k + 1, run_[2], sp and sp.group(1)))
        if not ran or (int(ran.group(1)), int(ran.group(2))) != run_[3:]:
            problems.append("game %d: native/interp %s, the game said %s" % (k + 1, run_[3:], ran and ran.groups()))
        if run_[0] != k + 1:
            problems.append("game %d numbered %d" % (k + 1, run_[0]))
    check("3 games: each run's numbers are the recompiler's and the game's own", not problems,
          "; ".join(problems))
    saved = open(os.path.join(hb, "01-basics.history")).read().splitlines() \
        if os.path.exists(os.path.join(hb, "01-basics.history")) else []
    check("the history grows by one line a game (3), as said",
          len(saved) == 3 and all(l == "run %d translated %d spots %d native %d interp %d" % r_
                                  for l, r_ in zip(saved, runs)), "%s" % saved)
    check("the spots shrink as it's played (built again with them), the translation grows",
          len(runs) == 3 and runs[0][2] > runs[1][2] > 0 and runs[1][1] > runs[0][1],
          "%s" % [(r_[1], r_[2]) for r_ in runs])
    nrom = os.path.join(hroms, "nestest.nes")
    shutil.copy(os.path.join(ROOT, "tests", "nestest.nes"), nrom)     # no .missed
    run_app([APP, "--build", nrom, "--build-dir", hb])
    nexe = os.path.join(hb, "nestest" + EXE)

    def counts(*args):
        r_ = subprocess.run([nexe, nrom, "--headless", "--no-save"] + list(args),
                            capture_output=True, text=True, timeout=300)
        m = re.search(r"ran (\d+) instruction\(s\) as translated C, (\d+) in the interpreter", r_.stderr)
        return (int(m.group(1)), int(m.group(2))) if m else None, r_
    c1, _ = counts("--frames", "60")
    c2, tr = counts("--frames", "3", "--trace")
    traced = sum(1 for l in tr.stdout.splitlines() if re.match(r"[0-9A-F]{4} ", l))
    c3, _ = counts("--frames", "60", "--start", "C000")
    for p_ in (nrom + ".missed",):
        if os.path.exists(p_):
            os.remove(p_)
    check("the runtime's counts: nestest from reset, all translated: none interpreted",
          c1 is not None and c1[0] > 100000 and c1[1] == 0, "%s" % (c1,))
    check("the runtime's counts: the total is what --trace traced",
          c2 is not None and traced > 1000 and c2[0] + c2[1] == traced, "%s, %d traced" % (c2, traced))
    check("the runtime's counts: from $C000 (never traced from there), nearly all interpreted",
          c3 is not None and c3[1] > 20 * c3[0] and c3[1] > 1000, "%s" % (c3,))
    lastg = os.path.join(hb, "last-game.txt")
    check("the last game's name kept for H", os.path.exists(lastg) and open(lastg).read() == "01-basics\n",
          repr(open(lastg).read() if os.path.exists(lastg) else None))

    # 11. the 6502 next to its C.
    CW, CH, TOP, ROW = 640, 360, 33, 9
    ROWS = (CH - 20 - TOP) // ROW
    AX, BX, TX, CX_ = 8, 8 + 36, 8 + 36 + 60, 212
    CCH = (CW - 8 - CX_) // 6
    english = dict(re.findall(r'\{ "([A-Z]{3})", "([^"]+)" \}', open(os.path.join(ROOT, "app", "code.c")).read()))

    def model(lst_path, c_path, keys):
        """The view as the app should draw it: {(x, y): colour}."""
        insns, ents, reset = [], [], None
        for l in open(lst_path).read().splitlines():
            m = re.match(r"# (reset|entry|init) ([0-9A-F]{2}):([0-9A-F]{4})", l)
            if m:
                key = (int(m.group(2), 16), int(m.group(3), 16))
                if m.group(1) in ("entry", "init"):
                    ents.append(key)
                if m.group(1) == "reset" or (m.group(1) == "init" and reset is None):
                    reset = key
                continue
            if l.startswith("#"):
                continue
            loc, first, last, by, text_ = l.split("\t")
            insns.append(dict(bank=int(loc[:2], 16), addr=int(loc[3:], 16), first=int(first),
                              last=int(last), bytes=by, text=text_, routine=False))
        clines = open(c_path).read().split("\n")
        where = {(i_["bank"], i_["addr"]): k for k, i_ in enumerate(insns)}
        for e in ents:
            if e in where:
                insns[where[e]]["routine"] = True
        for i_ in insns:
            m = re.match(r"JSR \$([0-9A-F]{4})$", i_["text"])
            if m:
                t = int(m.group(1), 16)
                k = where.get((i_["bank"], t))
                if k is None:
                    k = next((j for j, x in enumerate(insns) if x["addr"] == t), None)
                if k is not None:
                    insns[k]["routine"] = True
        nrows = [max(1, i_["last"] - i_["first"] + 1) for i_ in insns]
        cur = top = where.get(reset, 0)
        for k in keys:
            if k == "tab":
                j = next((j for j in range(cur + 1, len(insns)) if insns[j]["routine"]), None)
                if j is None:
                    j = next((j for j in range(0, cur) if insns[j]["routine"]), cur)
                if insns[j]["routine"]:
                    cur = top = j
                continue
            cur = {"up": max(cur - 1, 0), "down": min(cur + 1, len(insns) - 1),
                   "pgup": max(cur - 10, 0), "pgdn": min(cur + 10, len(insns) - 1)}[k]
            if cur < top:
                top = cur
            while top < cur and sum(nrows[top:cur + 1]) > ROWS:
                top += 1
        pic = {}

        def fill_(x0, y0, x1, y1, col):
            for y in range(y0, y1):
                for x in range(x0, x1):
                    pic[(x, y)] = col

        def write(text_, x, y, col):
            for i, ch in enumerate(text_):
                if ch in lower:
                    for rr, row_ in enumerate(lower[ch].split("|")):
                        for c in range(5):
                            if row_[c] == "#":
                                pic[(x + i * 6 + c, y + rr)] = col
                else:
                    for p_ in glyph_pixels(font, ch if 0x20 <= ord(ch) <= 0x5F else "?", x + i * 6 + 2, y):
                        pic[p_] = col
        wh, dm, ne = white, dim, neon
        fill_(0, 0, CW, CH, pal[defs["INK_SCREEN"]])
        fill_(0, 0, CW, 18, pal[defs["INK_BLACK"]])
        fill_(0, CH - 18, CW, CH, pal[defs["INK_BLACK"]])
        write("UNDER THE HOOD: THE 6502 AND THE C IT BECAME", 8, 6, wh)
        write("nestest.nes", CW - 8 - 6 * 11 + 1, 6, dm)
        write("6502", AX, 22, dm)
        write("C", CX_, 22, dm)
        row, i = 0, top
        while i < len(insns) and row < ROWS:
            ins, y = insns[i], TOP + row * ROW
            if i == cur:
                fill_(0, y - 1, CW, y - 1 + min(nrows[i], ROWS - row) * ROW, pal[defs["INK_SHADOW"]])
            write("%04X" % ins["addr"], AX, y, ne if ins["routine"] else wh)
            write(ins["bytes"], BX, y, dm)
            write(ins["text"], TX, y, wh)
            nc = ins["last"] - ins["first"] + 1
            for k in range(nc):
                if row + k >= ROWS:
                    break
                c = clines[ins["first"] - 1 + k]
                if len(c) > CCH:
                    c = c[:CCH - 2] + ".."
                write(c, CX_, y + k * ROW, dm if k == 0 else wh)
            row += nrows[i]
            i += 1
        write("UP, DOWN: SCROLL   TAB: NEXT ROUTINE   ESC: BACK", 8, CH - 12, dm)
        t = insns[cur]["text"]
        e = "AN UNOFFICIAL OPCODE" if t.startswith("*") else english.get(t[:3], "")
        if e:
            say = "%s: %s" % (t[:4] if t.startswith("*") else t[:3], e)
            write(say, CW - 8 - 6 * len(say) + 1, CH - 12, wh)
        return pic, insns[cur], top

    nl, nc_ = os.path.join(OUT, "nestest.listing"), os.path.join(OUT, "nestest_listed.c")
    subprocess.run([toolchain.recompiler(), os.path.join(ROOT, "tests", "nestest.nes"),
                    "--entry", "C000", "-o", nc_, "--listing", nl], capture_output=True)
    for label, keys in (("at its start (the reset routine)", []),
                        ("after down, down, a page, up", ["down", "down", "pgdn", "up"]),
                        ("after Tab three times", ["tab", "tab", "tab"]),
                        ("after Tab and paging to a cut C line", ["tab", "tab", "down", "down", "down"])):
        path = os.path.join(OUT, "code_%d.png" % len(keys))
        r_ = subprocess.run([APP, "--screenshot", path, "--show", "code", "--listing", nl, "--cfile", nc_,
                             "--rom", "nestest.nes", "--size", "%dx%d" % (CW, CH), "--keys", " ".join(keys)],
                            capture_output=True, text=True)
        img = read_png(path)[2] if r_.returncode == 0 and os.path.exists(path) else None
        pic, at, _ = model(nl, nc_, keys)
        bad = sum(1 for y in range(CH) for x in range(CW) if img is None or img[y][x] != pic[(x, y)])
        check("the code view %s: pixel for pixel (at %04X %s)" % (label, at["addr"], at["text"]),
              not bad, "%d pixel(s) differ" % bad if img else r_.stderr.strip())
    _, at, _ = model(nl, nc_, [])
    check("the code view starts at the reset routine", at["addr"] == 0xC004 and at["routine"], "%s" % at)
    tabs, seen = [], []
    for k in range(1, 6):
        _, at, top_ = model(nl, nc_, ["tab"] * k)
        tabs.append(at["addr"])
    jsr = sorted({int(m_, 16) for m_ in re.findall(r"\tJSR \$([0-9A-F]{4})", open(nl).read())})
    later = [a_ for a_ in jsr if a_ > 0xC004][:5]
    check("Tab goes to each next routine in turn (the JSR targets after the reset routine)",
          tabs == later, "%s, the JSR targets: %s" % (["%04X" % a_ for a_ in tabs], ["%04X" % a_ for a_ in later]))
    lb = os.path.join(hb, "01-basics.listing")
    lc = os.path.join(hb, "01-basics.c")
    rows_ = [l.split("\t") for l in open(lb).read().splitlines() if not l.startswith("#")] \
        if os.path.exists(lb) else []
    cl = open(lc).read().split("\n") if os.path.exists(lc) else []
    okl = rows_ and all(cl[int(r2[1]) - 1].startswith("L_%s_%s:" % tuple(r2[0].split(":"))) for r2 in rows_)
    check("the app's build writes NAME.listing beside NAME.c, each instruction where it says",
          okl, "%d listed" % len(rows_))
    if os.path.exists(lb):
        os.remove(lb)
    r_ = AppRun([APP, "--build", hrom, "--build-dir", hb])
    check("a build without its listing is built again (not up to date)",
          r_.returncode == 0 and "up to date" not in r_.stdout and os.path.exists(lb), last_line(r_.stdout))

    check("every build and game finished (none ran past its time)", not hung, "%s" % hung)
    print("\n%d check(s) failed" % len(fails) if fails else "\nall checks pass")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
