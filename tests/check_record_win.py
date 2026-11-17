#!/usr/bin/env python3
"""Check recording gameplay on Windows (PLAN-windows.md step 3): what
tests/check_record.py checks on the Mac, run by the GitHub workflow on its
Windows machine.

It makes the same test ROM (tests/make_av_sync_test.py: a white flash and
a beep starting in the same NMI, once a second), builds it with the
runtime (tests/toolchain.py), records it, and reads the movies back with
tests/read_movie_win.c, built here with Windows' Media Foundation:
  1. --record with --frames 300 and no window: an MP4 with H.264 and AAC;
     300 frames, 1024x960, at 60.0988 a second, frame N at N * 655171 /
     39375000 s (to Media Foundation's 100 ns); frames against the
     runtime's own picture of them (--screenshot), close (H.264 loses a
     little); the flashes 4 frames long, 60 apart; the sound 48 kHz mono,
     as long as the picture, and close to the --wav of the same run (AAC
     loses a little); each beep starting within a frame of its flash;
  2. stopped by Ctrl+Break part way: the movie still opens, with its
     picture and sound;
  3. in a window (muted, about 2 seconds): the same, with sound;
  4. V's way (a script's "record" lines): from one press to the next, in
     the folder given, named by the game and the time, ".mp4", two in the
     same second named apart (" 2"); in sync; P's picture the same as
     --screenshot of that frame;
  5. with no folder given, the movies go to Videos\\NES RECOMP (a scratch
     home here).
Exit status 0 when all pass.
"""
import array
import glob
import math
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import toolchain  # noqa: E402

OUT = os.path.join(ROOT, "build", "record_check_win")
FRAME = 655171 / 39375000                   # seconds
STEP = 1e7                                  # Media Foundation's steps a second
FS = 256 * 240 * 3
READER = None

fails = []


def check(name, ok, why=""):
    print("%s  %s%s" % ("ok   " if ok else "FAIL ", name, "" if ok else ": " + why), flush=True)
    if not ok:
        fails.append(name)


def run(*args, **kw):
    kw.setdefault("timeout", 600)
    return subprocess.run(list(args), capture_output=True, text=True, **kw)


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
    return b"".join(raw[y * stride + 1:(y + 1) * stride] for y in range(h))


class Movie:
    """What read_movie_win says of a movie, and its frames and sound."""
    def __init__(self, path):
        self.path = path
        prefix = os.path.join(OUT, "read_" + re.sub(r"\W", "_", os.path.basename(path)))
        r = run(READER, path, prefix) if os.path.exists(path) else None
        self.ok = bool(r) and r.returncode == 0 and "error" not in r.stdout
        self.text = (r.stdout + r.stderr) if r else "no file"
        self.video = self.audio = self.format = None
        for line in (r.stdout.splitlines() if r else []):
            p = line.split()
            if p[0] == "video" and p[1] != "none":
                self.video = dict(w=int(p[1]), h=int(p[2]), frames=int(p[3]), rate=float(p[4]),
                                  first=int(p[5]), last=int(p[6]), step_min=int(p[7]),
                                  step_max=int(p[8]))
            elif p[0] == "videoformat":
                self.format = dict(codec=p[1], matrix=p[2])
            elif p[0] == "audio" and p[1] != "none":
                self.audio = dict(rate=int(p[1]), channels=int(p[2]), bits=int(p[3]),
                                  format=p[4], samples=int(p[5]), first=int(p[6]), gaps=int(p[7]))
        self.frames = open(prefix + ".frames", "rb").read() if os.path.exists(prefix + ".frames") else b""
        self.pcm = array.array("h")
        if os.path.exists(prefix + ".pcm"):
            self.pcm.frombytes(open(prefix + ".pcm", "rb").read())
        self.first = (self.audio or {}).get("first", 0)

    def frame(self, i):
        return self.frames[i * FS:(i + 1) * FS]

    def flashes(self):
        """Frames whose background (the pixel at 2,2) is white."""
        n = len(self.frames) // FS
        return [i for i in range(n) if sum(self.frames[i * FS + (2 * 256 + 2) * 3:][:3]) > 600]

    def beeps(self):
        """Times (in samples) where a beep starts: loud after at least 2000 quiet."""
        on, quiet = [], 2000
        for i, v in enumerate(self.pcm):
            if abs(v) > 2000:
                if quiet >= 2000:
                    on.append(self.first + i)
                quiet = 0
            else:
                quiet += 1
        return on


def mp4_tracks(path):
    """What the MP4 itself says of each track's time: its time unit
    (ticks a second), its edit list (where it starts), the first few
    frames' lengths (stts) and display offsets (ctts), in ticks."""
    d = open(path, "rb").read()

    def boxes(lo, hi):
        i = lo
        while i + 8 <= hi:
            n, t = struct.unpack(">I4s", d[i:i + 8])
            h = 8
            if n == 1:
                n, h = struct.unpack(">Q", d[i + 8:i + 16])[0], 16
            if n < h:
                break
            yield t.decode("latin-1"), i + h, i + n
            i += n

    def find(lo, hi, *path):
        for t, a, b in boxes(lo, hi):
            if t == path[0]:
                return (a, b) if len(path) == 1 else find(a, b, *path[1:])
        return None

    out = []
    moov = find(0, len(d), "moov")
    for t, a, b in boxes(*moov) if moov else []:
        if t != "trak":
            continue
        tr = {}
        hd = find(a, b, "mdia", "hdlr")
        tr["kind"] = d[hd[0] + 8:hd[0] + 12].decode("latin-1") if hd else "?"
        md = find(a, b, "mdia", "mdhd")
        if md:
            v = d[md[0]]
            tr["timescale"] = struct.unpack(">I", d[md[0] + (20 if v == 1 else 12):][:4])[0]
        el = find(a, b, "edts", "elst")
        if el:
            v, n = d[el[0]], struct.unpack(">I", d[el[0] + 4:el[0] + 8])[0]
            fmt, sz = (">QqI", 20) if v == 1 else (">IiI", 12)
            tr["elst"] = [struct.unpack(fmt, d[el[0] + 8 + k * sz:][:sz])[:2] for k in range(min(n, 4))]
        for name in ("stts", "ctts"):
            bx = find(a, b, "mdia", "minf", "stbl", name)
            if bx:
                n = struct.unpack(">I", d[bx[0] + 4:bx[0] + 8])[0]
                tr[name] = [struct.unpack(">Ii", d[bx[0] + 8 + k * 8:][:8]) for k in range(min(n, 6))]
                tr[name + "_entries"] = n
        out.append(tr)
    return out


def runs(frames):
    out = []
    for f in frames:
        if out and f == out[-1][0] + out[-1][1]:
            out[-1] = (out[-1][0], out[-1][1] + 1)
        else:
            out.append((f, 1))
    return out


def in_sync(m):
    """Each beep within a frame of its flash's start: (ok, details)."""
    starts = [s for s, _ in runs(m.flashes())]
    beeps = [b / 48000 for b in m.beeps()]
    worst = max((abs(b - s * FRAME) / FRAME for s, b in zip(starts, beeps)), default=99)
    return (len(starts) == len(beeps) and starts and worst <= 1.0,
            "%d flash(es), %d beep(s), worst %.2f frame(s) apart" % (len(starts), len(beeps), worst))


def last(s):
    lines = [l for l in s.strip().splitlines() if l.strip()]
    return lines[-1][:160] if lines else "(nothing)"


def build():
    global READER
    rom = os.path.join(OUT, "av_sync.nes")
    subprocess.run([sys.executable, os.path.join(HERE, "make_av_sync_test.py"), rom],
                   capture_output=True, check=True)
    c = os.path.join(OUT, "av_sync.c")
    r = run(toolchain.recompiler(), rom, "-o", c)
    if r.returncode:
        sys.exit("recompiling failed: " + r.stderr)
    cflags, libs = toolchain.sdl_flags()
    game = os.path.join(OUT, "av_sync" + toolchain.EXE)
    srcs = [os.path.join(ROOT, "runtime", f) for f in toolchain.runtime_sources()]
    r = run(*(toolchain.cc() + ["-O1", "-I" + os.path.join(ROOT, "runtime")] + cflags +
              ["-o", game, c] + srcs + libs))
    if r.returncode:
        sys.exit("building the game failed: " + r.stderr[-2000:])
    READER = os.path.join(OUT, "read_movie_win" + toolchain.EXE)
    r = run(*(toolchain.cc() + ["-O1", "-Wall", "-o", READER, os.path.join(HERE, "read_movie_win.c"),
                                "-lmfplat", "-lmfreadwrite", "-lole32"]))
    if r.returncode:
        sys.exit("building read_movie_win failed: " + r.stderr[-2000:])
    return rom, game


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    rom, game = build()

    # 1. 300 frames, no window.
    mov, wav = os.path.join(OUT, "run one.mp4"), os.path.join(OUT, "run.wav")
    r = run(game, rom, "--headless", "--frames", "300", "--record", mov, "--wav", wav)
    check("recording 300 frames: the program says so",
          r.returncode == 0 and "recorded 300 frame(s)" in r.stderr, last(r.stderr))
    m = Movie(mov)
    v, a, f = m.video or {}, m.audio or {}, m.format or {}
    print("     (read back: %s %s %s)" % (v, f, a), flush=True)
    tracks = mp4_tracks(mov) if os.path.exists(mov) else []
    for tr in tracks:
        print("     (in the file: %s)" % tr, flush=True)
    check("the movie opens, with picture and sound", m.ok and m.video and m.audio, last(m.text))
    check("an MP4: the picture H.264, the sound AAC",
          open(mov, "rb").read(12)[4:8] == b"ftyp" and f.get("codec") == "h264" and a.get("format") == "aac",
          "%s %s" % (f, a.get("format")))
    check("the picture: 1024x960 (256x240 at 4x), 300 frames",
          (v.get("w"), v.get("h"), v.get("frames")) == (1024, 960, 300), "%s" % v)
    check("the rate: 60.0988 frames a second",
          abs(v.get("rate", 0) - 39375000 / 655171) < 0.001, "%s" % v.get("rate"))
    # Media Foundation's MP4 keeps the picture's times in its own ticks
    # (about 60,000 a second), so each frame is at N * 655171/39375000 s
    # to the nearest tick: steps of one frame give or take a tick, the
    # first at 0 (as the sound: not shown a frame late), the last where
    # frame 299 belongs.
    exact = FRAME * STEP
    vt = [t for t in tracks if t.get("kind") == "vide"]
    tick = STEP / vt[0]["timescale"] if vt and vt[0].get("timescale") else 1
    check("frame N at N * 655171/39375000 s, from 0 (to the file's tick, %.1f us)" % (tick / 10),
          abs(v.get("first", 99999)) <= tick and exact - tick - 1 <= v.get("step_min", 0) and
          v.get("step_max", 0) <= exact + tick + 1 and abs(v.get("last", 0) - 299 * exact) <= tick + 1,
          "%s" % v)
    check("no frame shown out of its place (the file's display offsets all 0, or undone)",
          vt and (all(o == 0 for _, o in vt[0].get("ctts", [])) or vt[0].get("elst", [(0, -1)])[0][1] == vt[0].get("ctts", [(0, 0)])[0][1]), "%s" % vt)
    check("the colours: BT.709, as the file says", f.get("matrix") == "709", "%s" % f)
    worst = []
    for k in (1, 2, 4, 5, 7, 30, 64, 65, 150, 300):
        png = os.path.join(OUT, "frame%d.png" % k)
        run(game, rom, "--headless", "--frames", str(k), "--screenshot", png)
        want = read_png(png) if os.path.exists(png) else b""
        got = m.frame(k - 1)
        if len(want) != FS or len(got) != FS:
            worst.append((k, "missing"))
            continue
        d = [abs(x - y) for x, y in zip(want, got)]
        worst.append((k, round(sum(d) / len(d), 2), max(d)))
    print("     (frames: %s)" % worst, flush=True)
    bad = [w for w in worst if len(w) == 2 or w[1] > 3 or w[2] > 40]
    check("frames 1, 2, 4, 5, 7, 30, 64, 65, 150, 300: as the runtime drew them (H.264-close)",
          not bad, "%s" % bad)
    fl = runs(m.flashes())
    check("the flashes: 4 frames each, 60 frames apart, 5 of them (no frame lost or doubled)",
          len(fl) == 5 and all(n == 4 for _, n in fl) and
          all(y[0] - x[0] == 60 for x, y in zip(fl, fl[1:])), "%s" % fl)
    check("the sound: 48 kHz, mono", (a.get("rate"), a.get("channels")) == (48000, 1), "%s" % a)
    want_n = 300 * FRAME * 48000
    check("the sound as long as the picture (within two AAC blocks)",
          abs(a.get("first", 0) + a.get("samples", 0) - want_n) <= 2048 and a.get("gaps", 1) == 0,
          "%s, the picture %.0f samples long" % (a, want_n))
    ws = array.array("h")
    if os.path.exists(wav):
        ws.frombytes(open(wav, "rb").read()[44:])
    # The movie's sample i is at m.first + i; the WAV's j at j.
    lo, hi = max(0, m.first), min(len(ws), m.first + len(m.pcm))
    num = sum((ws[j] - m.pcm[j - m.first]) ** 2 for j in range(lo, hi))
    den = sum(ws[j] ** 2 for j in range(lo, hi)) or 1
    rel = math.sqrt(num / den)
    print("     (the sound against the WAV: %.3f of its loudness different, %d samples compared)"
          % (rel, hi - lo), flush=True)
    check("the sound: close to --wav of the same run (AAC-close)",
          len(ws) > 200000 and hi - lo > 200000 and rel < 0.25, "%.3f different" % rel)
    ok, why = in_sync(m)
    print("     (%s)" % why, flush=True)
    check("each beep starts within a frame of its flash", ok, why)

    # 2. stopped by Ctrl+Break part way.
    smov = os.path.join(OUT, "stopped.mp4")
    p = subprocess.Popen([game, rom, "--headless", "--record", smov], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    time.sleep(3)
    p.send_signal(signal.CTRL_BREAK_EVENT)
    try:
        _, err = p.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        p.kill()
        _, err = p.communicate()
    sm = Movie(smov)
    sv, sa = sm.video or {}, sm.audio or {}
    frames = sv.get("frames", 0)
    check("stopped by Ctrl+Break part way: the movie opens, with its picture and sound",
          sm.ok and frames > 30 and sa.get("samples", 0) > 0 and
          abs(sa.get("first", 0) + sa.get("samples", 0) - frames * FRAME * 48000) <= 2048,
          "exit %s, %d frame(s), %s; %s; %s" % (p.returncode, frames, sa, last(err), last(sm.text)))

    # 3. in a window, muted.
    wmov = os.path.join(OUT, "window.mp4")
    t0 = time.time()
    r = run(game, rom, "--frames", "120", "--mute", "--no-save", "--record", wmov)
    took = time.time() - t0
    wm = Movie(wmov)
    wv, wa = wm.video or {}, wm.audio or {}
    check("in a window (muted): 120 frames in about 2 seconds, with the sound",
          r.returncode == 0 and wv.get("frames") == 120 and took > 1.5 and
          abs(wa.get("first", 0) + wa.get("samples", 0) - 120 * FRAME * 48000) <= 2048,
          "exit %d, %s frame(s) in %.1f s, %s; %s" % (r.returncode, wv.get("frames"), took, wa, last(r.stderr)))
    ok, why = in_sync(wm)
    check("in a window: in sync", ok, why)

    # 4. V's way, through a script, into a folder given.
    vdir = os.path.join(OUT, "V recordings")
    script = os.path.join(OUT, "keys.txt")
    with open(script, "w") as fh:
        fh.write("60 record\n180 record\n200 snap\n210 record\n211 record\n")
    r = run(game, rom, "--headless", "--frames", "240", "--input", script, "--record-dir", vdir)
    movies = sorted(glob.glob(os.path.join(vdir, "*.mp4")))
    pics = sorted(glob.glob(os.path.join(vdir, "*.png")))
    names = [os.path.basename(x) for x in movies + pics]
    pat = r"av_sync \d{4}-\d\d-\d\d at \d\d\.\d\d\.\d\d( 2)?\.(mp4|png)$"
    check("V: the movies (.mp4) and P's picture in the folder, named by the game and the time",
          len(movies) == 2 and len(pics) == 1 and all(re.match(pat, n) for n in names),
          "%s; %s" % (names, last(r.stderr)))
    same = None
    for attempt in range(3):
        cdir = os.path.join(OUT, "same second %d" % attempt)
        with open(script, "w") as fh:
            fh.write("10 record\n11 record\n12 record\n13 record\n")
        run(game, rom, "--headless", "--frames", "20", "--input", script, "--record-dir", cdir)
        got = sorted(os.path.basename(x) for x in glob.glob(os.path.join(cdir, "*.mp4")))
        stamps = {re.sub(r"( 2)?\.mp4$", "", n) for n in got}
        if len(got) != 2 or len(stamps) == 1:
            same = got
            break
    check("V: two recordings in the same second: both kept, the second named \" 2\"",
          same is not None and len(same) == 2 and same[0].endswith(" 2.mp4")
          and same[1] == same[0][:-6] + ".mp4", "%s" % same)
    first = [x for x in movies if not x.endswith(" 2.mp4")]
    vm = Movie(first[0] if first else os.path.join(vdir, "none"))
    vv = vm.video or {}
    check("V: from one press to the next: 120 frames, with sound",
          vm.ok and vv.get("frames") == 120 and (vm.audio or {}).get("samples", 0) > 90000,
          "%s %s" % (vv, vm.audio))
    ok, why = in_sync(vm)
    check("V: in sync", ok, why)
    want = os.path.join(OUT, "frame200.png")
    run(game, rom, "--headless", "--frames", "200", "--screenshot", want)
    check("P: the picture is the screen at that frame",
          pics and os.path.exists(want) and read_png(pics[0]) == read_png(want), "%s" % pics)

    # 5. no folder given: Videos\NES RECOMP.
    home = os.path.join(OUT, "a home")
    os.makedirs(home)
    with open(script, "w") as fh:
        fh.write("10 record\n40 record\n")
    r = run(game, rom, "--headless", "--frames", "50", "--input", script,
            env=dict(os.environ, HOME=home, USERPROFILE=home))
    found = glob.glob(os.path.join(home, "Videos", "NES RECOMP", "av_sync *.mp4"))
    check("with no folder given: in Videos\\NES RECOMP", len(found) == 1 and Movie(found[0]).ok,
          "%s; %s" % (found, last(r.stderr)))

    print("\n%d check(s) failed" % len(fails) if fails else "\nall checks pass")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
