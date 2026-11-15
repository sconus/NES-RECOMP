#!/usr/bin/env python3
"""Check recording gameplay (PLAN-standalone.md step 6). Run by
`make test-record`.

It makes a test ROM (tests/make_av_sync_test.py: a white flash and a beep
starting in the same NMI, once a second), builds it as `make game` does,
records it, and reads the movies back with tests/read_movie.m, built here
with Apple's AVFoundation, the library QuickTime and editors use:
  1. --record with --frames 300 and no window: 300 frames, 1024x960, at
     60.0988 a second, each frame exactly 655171/39375000 s after the
     last; frames against the runtime's own picture of them (its
     --screenshot), close (H.264 loses a little); the flashes 4 frames
     long, 60 apart; the sound uncompressed, 48 kHz mono 16-bit, the same
     samples as the --wav of the same run; each beep starting within a
     frame of its flash;
  2. stopped by Ctrl+C or a quit signal part way: the movie still opens,
     with its picture and sound;
  3. in a window (muted, about 2 seconds): the same, with sound;
  4. V's way (a script's "record" lines, which run what V runs): from
     one press to the next, in the folder given, named by the game and
     the date and time, a second recording not replacing the first, two
     started in the same second named apart (" 2"); in sync too; and
     P's picture ("snap") the same as --screenshot of that frame;
  5. with no folder given, the movies go to ~/Movies/NES RECOMP (a
     scratch home here).
Exit status 0 when all pass.
"""
import array
import glob
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
OUT = os.path.join(ROOT, "build", "record_check")
FRAME = 655171 / 39375000                   # seconds
FRAME_NUM, FRAME_DEN = 655171, 39375000
FS = 256 * 240 * 3

fails = []


def check(name, ok, why=""):
    print("%s  %s%s" % ("ok   " if ok else "FAIL ", name, "" if ok else ": " + why))
    if not ok:
        fails.append(name)


def run(*args, **kw):
    kw.setdefault("timeout", 300)
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
    """What read_movie says of a movie, and its frames and sound."""
    def __init__(self, path):
        self.path = path
        prefix = os.path.join(OUT, "read_" + re.sub(r"\W", "_", os.path.basename(path)))
        r = run(READER, path, prefix)
        self.ok = r.returncode == 0
        self.text = r.stdout + r.stderr
        self.video = self.audio = None
        for line in r.stdout.splitlines():
            p = line.split()
            if p[0] == "video" and p[1] != "none":
                self.video = dict(w=int(p[1]), h=int(p[2]), frames=int(p[3]), rate=float(p[4]),
                                  first=int(p[5]), last=int(p[6]), step_min=int(p[7]),
                                  step_max=int(p[8]), scale=int(p[9]))
            elif p[0] == "audio" and p[1] != "none":
                self.audio = dict(rate=int(p[1]), channels=int(p[2]), bits=int(p[3]),
                                  format=p[4], samples=int(p[5]), first=int(p[6]))
        self.frames = open(prefix + ".frames", "rb").read() if os.path.exists(prefix + ".frames") else b""
        self.pcm = array.array("h")
        if os.path.exists(prefix + ".pcm"):
            self.pcm.frombytes(open(prefix + ".pcm", "rb").read())

    def frame(self, i):
        return self.frames[i * FS:(i + 1) * FS]

    def flashes(self):
        """Frames whose background (the pixel at 2,2) is white."""
        n = len(self.frames) // FS
        return [i for i in range(n) if sum(self.frames[i * FS + (2 * 256 + 2) * 3:][:3]) > 600]

    def beeps(self):
        """Samples where a beep starts: loud after at least 2000 quiet."""
        on, quiet = [], 2000
        for i, v in enumerate(self.pcm):
            if abs(v) > 2000:
                if quiet >= 2000:
                    on.append(i)
                quiet = 0
            else:
                quiet += 1
        return on


def runs(frames):
    """[(start, length)] of consecutive frame numbers."""
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
    pairs = list(zip(starts, beeps))
    worst = max((abs(b - s * FRAME) / FRAME for s, b in pairs), default=99)
    return (len(starts) == len(beeps) and starts and worst <= 1.0,
            "%d flash(es), %d beep(s), worst %.2f frame(s) apart" % (len(starts), len(beeps), worst))


def last(s):
    lines = [l for l in s.strip().splitlines() if l.strip()]
    return lines[-1][:120] if lines else "(nothing)"


def main():
    global READER
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    rom = os.path.join(OUT, "av_sync.nes")
    r = run("python3", os.path.join(HERE, "make_av_sync_test.py"), rom)
    if r.returncode:
        sys.exit("making the test ROM failed: " + r.stderr)
    r = run("make", "-s", "game", "ROM=" + rom, cwd=ROOT)
    game = os.path.join(ROOT, "build", "av_sync")
    if r.returncode or not os.path.exists(game):
        sys.exit("building it failed: " + r.stdout + r.stderr)
    READER = os.path.join(OUT, "read_movie")
    r = run("cc", "-O1", "-Wall", "-fobjc-arc", "-mmacosx-version-min=11.0", "-o", READER,
            os.path.join(HERE, "read_movie.m"), "-framework", "AVFoundation", "-framework", "CoreMedia",
            "-framework", "CoreVideo", "-framework", "Foundation")
    if r.returncode:
        sys.exit("building read_movie failed: " + r.stderr)

    # 1. 300 frames, no window.
    mov, wav = os.path.join(OUT, "run one.mov"), os.path.join(OUT, "run.wav")
    r = run(game, rom, "--headless", "--frames", "300", "--record", mov, "--wav", wav)
    check("recording 300 frames: the program says so",
          r.returncode == 0 and "recorded 300 frame(s)" in r.stderr, last(r.stderr))
    m = Movie(mov)
    v = m.video or {}
    check("the movie opens, with picture and sound", m.ok and m.video and m.audio, last(m.text))
    check("the picture: 1024x960 (256x240 at 4x), 300 frames",
          (v.get("w"), v.get("h"), v.get("frames")) == (1024, 960, 300), "%s" % v)
    check("the rate: 60.0988 frames a second",
          abs(v.get("rate", 0) - 39375000 / 655171) < 0.001, "%s" % v.get("rate"))
    check("each frame exactly 655171/39375000 s after the last, from 0",
          v.get("scale") and v.get("first") == 0 and
          v.get("step_min") * FRAME_DEN == FRAME_NUM * v.get("scale") and
          v.get("step_min") == v.get("step_max"), "%s" % v)
    worst = []
    for k in (1, 2, 4, 5, 7, 30, 64, 65, 150, 300):
        png = os.path.join(OUT, "frame%d.png" % k)
        run(game, rom, "--headless", "--frames", str(k), "--screenshot", png)
        want = read_png(png) if os.path.exists(png) else b""
        got = m.frame(k - 1)
        if len(want) != FS or len(got) != FS:
            worst.append((k, "missing"))
            continue
        d = [abs(a - b) for a, b in zip(want, got)]
        worst.append((k, round(sum(d) / len(d), 2), max(d)))
    bad = [w for w in worst if len(w) == 2 or w[1] > 3 or w[2] > 40]
    check("frames 1, 2, 4, 5, 7, 30, 64, 65, 150, 300: as the runtime drew them (H.264-close)",
          not bad, "%s" % bad)
    fl = runs(m.flashes())
    check("the flashes: 4 frames each, 60 frames apart, 5 of them (no frame lost or doubled)",
          len(fl) == 5 and all(n == 4 for _, n in fl) and
          all(b[0] - a[0] == 60 for a, b in zip(fl, fl[1:])), "%s" % fl)
    a = m.audio or {}
    check("the sound: uncompressed, 48 kHz, mono, 16-bit, from 0",
          (a.get("format"), a.get("rate"), a.get("channels"), a.get("bits"), a.get("first")) ==
          ("lpcm", 48000, 1, 16, 0), "%s" % a)
    ws = array.array("h")
    if os.path.exists(wav):
        ws.frombytes(open(wav, "rb").read()[44:])
    check("the sound: the same samples as --wav of the same run (%d)" % len(ws),
          len(ws) > 200000 and list(ws) == list(m.pcm),
          "%d in the movie, %d in the WAV, first difference at %s" % (
              len(m.pcm), len(ws), next((i for i, (x, y) in enumerate(zip(ws, m.pcm)) if x != y), "-")))
    ok, why = in_sync(m)
    check("each beep starts within a frame of its flash", ok, why)

    # 2. stopped by a signal part way.
    for sig, name in ((signal.SIGINT, "Ctrl+C"), (signal.SIGTERM, "a quit signal")):
        smov = os.path.join(OUT, "stopped %d.mov" % sig)
        p = subprocess.Popen([game, rom, "--headless", "--record", smov],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1.5)
        p.send_signal(sig)
        try:
            _, err = p.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            p.kill()
            _, err = p.communicate()
        sm = Movie(smov)
        sv, sa = sm.video or {}, sm.audio or {}
        frames = sv.get("frames", 0)
        check("stopped by %s part way: the movie opens, with its picture and sound" % name,
              sm.ok and frames > 30 and sa.get("samples", 0) > 0
              and abs(sa.get("samples", 0) - frames * FRAME * 48000) < 1600,
              "exit %s, %d frame(s), %d sample(s); %s" % (p.returncode, frames, sa.get("samples", 0),
                                                          last(err)))

    # 3. in a window, muted.
    wmov = os.path.join(OUT, "window.mov")
    t0 = time.time()
    r = run(game, rom, "--frames", "120", "--mute", "--no-save", "--record", wmov)
    took = time.time() - t0
    wm = Movie(wmov)
    wv, wa = wm.video or {}, wm.audio or {}
    check("in a window (muted): 120 frames in about 2 seconds, with the sound",
          r.returncode == 0 and wv.get("frames") == 120 and took > 1.5 and
          abs(wa.get("samples", 0) - 120 * FRAME * 48000) < 800,
          "exit %d, %s frame(s) in %.1f s, %s sample(s); %s" % (
              r.returncode, wv.get("frames"), took, wa.get("samples"), last(r.stderr)))
    ok, why = in_sync(wm)
    check("in a window: in sync", ok, why)

    # 4. V's way, through a script, into a folder given.
    vdir = os.path.join(OUT, "V recordings")
    script = os.path.join(OUT, "keys.txt")
    with open(script, "w") as f:
        f.write("60 record\n180 record\n200 snap\n210 record\n211 record\n")
    r = run(game, rom, "--headless", "--frames", "240", "--input", script, "--record-dir", vdir)
    movies = sorted(glob.glob(os.path.join(vdir, "*.mov")))
    pics = sorted(glob.glob(os.path.join(vdir, "*.png")))
    names = [os.path.basename(p) for p in movies + pics]
    pat = r"av_sync \d{4}-\d\d-\d\d at \d\d\.\d\d\.\d\d( 2)?\.(mov|png)$"
    check("V: the movies and P's picture in the folder, named by the game and the time",
          len(movies) == 2 and len(pics) == 1 and all(re.match(pat, n) for n in names), "%s" % names)
    taken = [n for n in names if n.endswith(".mov")]
    stamps = [re.sub(r"( 2)?\.mov$", "", n) for n in taken]
    check("V: a second recording doesn't replace the first (in the same second, \" 2\")",
          len(taken) == 2 and (stamps[0] != stamps[1] or
                               sorted(taken) == [stamps[0] + " 2.mov", stamps[0] + ".mov"]),
          "%s" % taken)
    # Two recordings started in the same second: the second gets " 2".
    # (Each run takes a few milliseconds; if one happens to straddle a
    # second, it's tried again.)
    same = None
    for attempt in range(3):
        cdir = os.path.join(OUT, "same second %d" % attempt)
        with open(script, "w") as f:
            f.write("10 record\n11 record\n12 record\n13 record\n")
        run(game, rom, "--headless", "--frames", "20", "--input", script, "--record-dir", cdir)
        got = sorted(os.path.basename(p) for p in glob.glob(os.path.join(cdir, "*.mov")))
        stamps = {re.sub(r"( 2)?\.mov$", "", n) for n in got}
        if len(got) != 2 or len(stamps) == 1:
            same = got
            break
    check("V: two recordings in the same second: both kept, the second named \" 2\"",
          same is not None and len(same) == 2 and same[0].endswith(" 2.mov")
          and same[1] == same[0][:-6] + ".mov", "%s" % same)
    first = [p for p in movies if not p.endswith(" 2.mov")]
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

    # 5. no folder given: ~/Movies/NES RECOMP.
    home = os.path.join(OUT, "a home")
    os.makedirs(home)
    with open(script, "w") as f:
        f.write("10 record\n40 record\n")
    r = run(game, rom, "--headless", "--frames", "50", "--input", script,
            env=dict(os.environ, HOME=home))
    found = glob.glob(os.path.join(home, "Movies", "NES RECOMP", "av_sync *.mov"))
    check("with no folder given: in ~/Movies/NES RECOMP", len(found) == 1 and Movie(found[0]).ok,
          "%s; %s" % (found, last(r.stderr)))

    print("\n%d check(s) failed" % len(fails) if fails else "\nall checks pass")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
