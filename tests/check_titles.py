#!/usr/bin/env python3
"""The game's title picture, --title-out (PLAN-library.md step 3), with
real games: free test ROMs and the project's own.

For each game:
  - an input script presses Start at frame N: the title file holds
    exactly the picture of frame N (the one on screen as Start was
    pressed), as --screenshot saves it for --frames N, and the terminal
    says "title: saved at frame N (Start)";
  - no Start, 700 frames: the picture of frame 600 (10 seconds),
    "title: saved at frame 600 (10 seconds)";
  - without --title-out: no "title:" line, and nothing written.
And a music file (NSF): "has no title screen", and no file.

The rules themselves (a press on a one-colour screen, 30 seconds, the
game ending early, ...) are the runtime's self-test, --test-title (make
test). That taking the picture changes nothing in a game, for every
game of the suite, is in tests/check_states.py (the fast-forward run
takes one).

    python3 tests/check_titles.py
"""
import os
import re
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_tests  # noqa: E402
import toolchain  # noqa: E402

ROOT = run_tests.ROOT
OUT = os.path.join(ROOT, "build", "titles")
# (the ROM, from the project or the test ROM clone; the frame Start is
# pressed at)
GAMES = [("tests/mmc3_split.nes", 120), ("240pee/240pee.nes", 150), ("tests/fds_demo.fds", 400)]
NSF = "tests/nsf_rate.nsf"
fails = []


def check(what, ok, why=""):
    print(("ok    " if ok else "FAIL  ") + what + ("" if ok else ": " + why))
    if not ok:
        fails.append(what)


def rom_path(rom):
    return os.path.join(ROOT, rom) if rom.startswith("tests/") else os.path.join(run_tests.ROMS, rom)


def build(rom, cflags, libs, rt_objs):
    ident = re.sub(r"[^A-Za-z0-9_.-]", "_", rom)
    c_file = os.path.join(OUT, ident + ".c")
    exe = os.path.join(OUT, ident + toolchain.EXE)
    path = rom_path(rom)
    args = [toolchain.recompiler(), path, "-o", c_file]
    if os.path.exists(path + ".missed"):
        args += ["--missed", path + ".missed"]
    r = run_tests.sh(args, cwd=ROOT)
    if r.returncode:
        sys.exit("recompile error: " + r.stderr[-300:])
    r = run_tests.sh(toolchain.cc() + ["-O1", "-Iruntime"] + cflags + ["-o", exe, c_file] +
                     rt_objs + libs, cwd=ROOT)
    if r.returncode:
        sys.exit("compile error: " + r.stderr[:300])
    return exe, ident


def png_rgb(path):
    """The runtime's PNG (8-bit RGB, every row filter 0) as bytes."""
    d = open(path, "rb").read()
    i, idat = 8, b""
    while i < len(d):
        n = struct.unpack(">I", d[i:i + 4])[0]
        if d[i + 4:i + 8] == b"IDAT":
            idat += d[i + 8:i + 8 + n]
        i += 12 + n
    raw = zlib.decompress(idat)
    row = 1 + 256 * 3
    return b"".join(raw[y * row + 1:(y + 1) * row] for y in range(240))


def title_rgb(path):
    """The title file's picture, or None if it isn't one."""
    if not os.path.exists(path):
        return None
    d = open(path, "rb").read()
    if len(d) != 12 + 256 * 240 * 3 or d[:8] != b"NRTITLE1" or d[8:12] != bytes([0, 1, 240, 0]):
        return None
    return d[12:]


def run(exe, ident, tag, args, script=None):
    """Run headless; (stderr, the files' paths)."""
    base = os.path.join(OUT, "%s.%s" % (ident, tag))
    for ext in (".title", ".png"):
        if os.path.exists(base + ext):
            os.remove(base + ext)
    cmd = [exe] + args + ["--headless", "--no-save", "--files-at", base]
    if script:
        with open(base + ".txt", "w") as f:
            f.write(script)
        cmd += ["--input", base + ".txt"]
    r = run_tests.sh(cmd, cwd=ROOT, timeout=120)
    return r.stderr, base


def main():
    os.makedirs(OUT, exist_ok=True)
    cflags, libs = run_tests.sdl_flags()
    rt_objs = run_tests.build_runtime(cflags)
    for rom, n in GAMES:
        exe, ident = build(rom, cflags, libs, rt_objs)
        name = os.path.basename(rom)
        path = rom_path(rom)
        start = "%d start\n%d\n" % (n, n + 6)
        # Start at frame n: that frame's picture.
        err, base = run(exe, ident, "start",
                        [path, "--frames", str(n + 30), "--title-out", os.path.join(OUT, ident + ".start.title")],
                        start)
        got = title_rgb(base + ".title")
        _, shot = run(exe, ident, "shot", [path, "--frames", str(n), "--screenshot",
                                           os.path.join(OUT, ident + ".shot.png")], start)
        want = png_rgb(shot + ".png") if os.path.exists(shot + ".png") else None
        check("%s: Start at frame %d: the title is that frame's picture" % (name, n),
              got is not None and want is not None and got == want,
              "no title file" if got is None else "no screenshot" if want is None else
              "%d of %d bytes differ" % (sum(a != b for a, b in zip(got, want)), len(want)))
        check("%s: the terminal says so" % name, "title: saved at frame %d (Start)\n" % n in err,
              (re.findall(r"title: .*", err) or ["(no title line)"])[0])
        # No Start: frame 600's picture.
        err, base = run(exe, ident, "plain",
                        [path, "--frames", "700", "--title-out", os.path.join(OUT, ident + ".plain.title")])
        got = title_rgb(base + ".title")
        _, shot = run(exe, ident, "shot600", [path, "--frames", "600", "--screenshot",
                                              os.path.join(OUT, ident + ".shot600.png")])
        want = png_rgb(shot + ".png") if os.path.exists(shot + ".png") else None
        check("%s: no Start: the title is frame 600's picture (10 seconds)" % name,
              got is not None and want is not None and got == want,
              "no title file" if got is None else "no screenshot" if want is None else "it differs")
        check("%s: the terminal says so" % name, "title: saved at frame 600 (10 seconds)\n" in err,
              (re.findall(r"title: .*", err) or ["(no title line)"])[0])
        # Without --title-out: nothing.
        before = set(os.listdir(OUT))
        err, _ = run(exe, ident, "none", [path, "--frames", "700"], start)
        made = [f for f in set(os.listdir(OUT)) - before if f.endswith(".title")]
        check("%s: without --title-out, no title" % name, "title:" not in err and not made,
              "said %r, made %s" % (re.findall(r"title: .*", err), made))
    # A music file: no title.
    exe, ident = build(NSF, cflags, libs, rt_objs)
    err, base = run(exe, ident, "nsf", [rom_path(NSF), "--frames", "700", "--title-out",
                                        os.path.join(OUT, ident + ".nsf.title")])
    check("a music file (NSF): no title, and it says why",
          not os.path.exists(base + ".title") and "title: a music file has no title screen" in err,
          (re.findall(r"title: .*", err) or ["(no title line)"])[0])
    print("\n%s" % ("all title checks pass" if not fails else "%d title check(s) failed" % len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
