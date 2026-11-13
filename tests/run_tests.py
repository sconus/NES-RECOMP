#!/usr/bin/env python3
"""Recompile and run every ROM in tests/suite.txt, headless, and compare the
results with tests/expected.txt.

    python3 tests/run_tests.py            run everything
    python3 tests/run_tests.py sprite_hit only tests whose ROM path matches
    python3 tests/run_tests.py --update   accept today's results as expected

Each ROM goes through the recompiler's feedback loop: build, run, and if
the run added new addresses to <rom>.missed, build and run again (up to
MAX_PASSES times) so the final run uses as much native code as possible.

Exit status is 1 if any test got worse than expected: a pass that now
fails, or a homebrew picture that changed. Tests that now do better are
listed so you can run --update.
"""
import concurrent.futures
import os
import re
import subprocess
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ROMS = os.path.join(HERE, "roms", "nes-test-roms")
SUITE = os.path.join(HERE, "suite.txt")
EXPECTED = os.path.join(HERE, "expected.txt")
BUILD = os.path.join(ROOT, "build", "tests")
MAX_PASSES = 4


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def sdl_flags():
    prefix = sh(["sdl2-config", "--prefix"]).stdout.strip()
    cflags = sh(["sdl2-config", "--cflags"]).stdout.split()
    return cflags, [os.path.join(prefix, "lib", "libSDL2.dylib"), "-lz", "-lm"]


def load_suite():
    tests = []
    for line in open(SUITE):
        line = line.split("#")[0].split()
        if not line:
            continue
        kind, frames, rom = line[0], int(line[1]), line[2]
        # Columns like --mmc3-rev=A are options for the built program.
        options = [c for c in line[3:] if c.startswith("--")]
        line = [c for c in line if not c.startswith("--")]
        extra = line[3] if len(line) > 3 else None
        # For "crc" the 4th column lists accepted checksums, and for
        # "tones" the expected notes, not a script.
        script = extra if kind not in ("crc", "tones") else None
        notes = extra if kind == "tones" else None
        crcs = extra.upper().split(",") if kind == "crc" and extra else []
        name = rom + (" +" + os.path.basename(script) if script else "")
        if options:
            name += " " + " ".join(options)
        if kind == "audio":
            name += " (sound)"          # may share a ROM and script with a picture
        args = []
        for o in options:
            args += o.split("=", 1)
        tests.append(dict(kind=kind, frames=frames, rom=rom, script=script,
                          name=name, crcs=crcs, args=args, notes=notes))
    return tests


def load_expected():
    if not os.path.exists(EXPECTED):
        return {}
    out = {}
    for line in open(EXPECTED):
        if line.strip() and not line.startswith("#"):
            name, result = line.rstrip("\n").split("\t", 1)
            out[name] = result
    return out


def build_runtime(cflags):
    """Compile the runtime once; every test links against these objects."""
    objdir = os.path.join(BUILD, "rt")
    os.makedirs(objdir, exist_ok=True)
    objs = []
    for src in sorted(os.listdir(os.path.join(ROOT, "runtime"))):
        if src.endswith(".c"):
            obj = os.path.join(objdir, src[:-2] + ".o")
            r = sh(["cc", "-O1", "-Wall", "-Iruntime"] + cflags +
                   ["-c", os.path.join("runtime", src), "-o", obj], cwd=ROOT)
            if r.returncode:
                sys.exit("runtime build failed:\n" + r.stderr)
            objs.append(obj)
    return objs


def png_pixels_crc(path):
    """CRC of the decoded pixels, so it doesn't depend on zlib's settings."""
    data = open(path, "rb").read()
    i, idat = 8, b""
    while i < len(data):
        n = int.from_bytes(data[i:i + 4], "big")
        if data[i + 4:i + 8] == b"IDAT":
            idat += data[i + 8:i + 8 + n]
        i += 12 + n
    return "%08x" % zlib.crc32(zlib.decompress(idat))


def wav_samples(path):
    import array
    data = open(path, "rb").read()
    samples = array.array("h")
    samples.frombytes(data[44:44 + (len(data) - 44) // 2 * 2])
    return samples


# apu_mixer tests beep, play a tone plus its inverse (which should cancel
# to near silence if the mixer is right), then beep again. The quietest
# correct result and a deliberately broken mixer set this limit: the
# loudest quarter second between the beeps must stay below this fraction
# of the beeps' loudness.
SILENCE_LIMIT = 0.05


def silence_ratio(path):
    import math
    x = wav_samples(path)
    step = 12000                                    # a quarter second
    rms = [math.sqrt(sum(v * v for v in x[i:i + step]) / step)
           for i in range(0, len(x) - step, step)]
    loud = max(rms)
    beeps = [i for i, r in enumerate(rms) if r > 0.3 * loud]
    if len(beeps) < 2:
        return None, "couldn't find the two beeps"
    first_end = beeps[0]
    while first_end + 1 in beeps:
        first_end += 1
    middle = rms[first_end + 2:beeps[-1] - 1]       # skip the beeps' edges
    if not middle:
        return None, "nothing between the beeps"
    return max(middle) / loud, None


# "tones": a test ROM plays notes one at a time with silence between
# them. Split the recording at the silences and measure each note: its
# pitch (from the spacing of rising zero crossings) and its loudness (RMS,
# relative to the first note). The console's output filters cut low
# frequencies, so loudness is only compared between notes of the same
# pitch and similar waveform; "-" skips it.
TONE_WINDOW = 480               # 10 ms
TONE_PITCH_TOLERANCE = 0.0025   # 0.25 % (an off-by-one period at 440 Hz is 0.4 %)
TONE_LEVEL_TOLERANCE = 0.05     # 5 % (expected levels include the output filters)


def tone_segments(x):
    """(start, end) sample ranges of the notes in recording x."""
    import math
    w = TONE_WINDOW
    rms = [math.sqrt(sum(v * v for v in x[i:i + w]) / w)
           for i in range(0, len(x) - w, w)]
    if not rms or max(rms) == 0:
        return []
    on = [r > 0.02 * max(rms) for r in rms]
    segments, start = [], None
    for i, o in enumerate(on + [False]):
        if o and start is None:
            start = i
        elif not o and start is not None:
            if i - start >= 10:                         # at least 100 ms
                segments.append((start * w, i * w))
            start = None
    return segments


def measure_tone(x, start, end):
    """Pitch in Hz and RMS of the middle 60% of a note."""
    import math
    a = start + (end - start) // 5
    b = end - (end - start) // 5
    seg = x[a:b]
    mean = sum(seg) / len(seg)
    y = [v - mean for v in seg]
    rms = math.sqrt(sum(v * v for v in y) / len(y))
    crossings = []
    for i in range(1, len(y)):
        if y[i - 1] < 0 <= y[i]:
            crossings.append(i - 1 + -y[i - 1] / (y[i] - y[i - 1]))
    if len(crossings) < 3:
        return 0.0, rms
    return 48000.0 * (len(crossings) - 1) / (crossings[-1] - crossings[0]), rms


def check_tones(path, expected):
    """expected: "440@1,880@-,440@0.5/2,...": pitch @ loudness relative to
    note 1, or to note k with "/k"; "-" doesn't check loudness."""
    want = []
    for item in expected.split(","):
        f, lvl = item.split("@")
        rel = 1
        if "/" in lvl:
            lvl, rel = lvl.split("/")
            rel = int(rel)
        want.append((float(f), None if lvl == "-" else float(lvl), rel))
    x = wav_samples(path)
    segs = tone_segments(x)
    if len(segs) != len(want):
        return "fail: heard %d notes, expected %d" % (len(segs), len(want))
    measured = [measure_tone(x, a, b) for a, b in segs]
    for i, ((f, lvl, rel), (hz, rms)) in enumerate(zip(want, measured), 1):
        if abs(hz / f - 1) > TONE_PITCH_TOLERANCE:
            return "fail: note %d is %.1f Hz, expected %.1f" % (i, hz, f)
        ref = measured[rel - 1][1]
        if lvl is not None and abs(rms / ref / lvl - 1) > TONE_LEVEL_TOLERANCE:
            return "fail: note %d is %.3f as loud as note %d, expected %.3f" % (
                i, rms / ref, rel, lvl)
    return "pass"


def judge(test, out, err, png):
    """Return 'pass', 'fail: <why>' or 'frame:<crc>'."""
    stop = re.search(r"stopped: (.*)", err)
    if stop:                            # the CPU hit something it can't run
        return "fail: stopped, " + stop.group(1)
    if test["kind"] == "result":
        m = re.search(r"test status at \$6000: \$([0-9A-F]{2})", err)
        if not m:
            return "fail: no result after %d frames" % test["frames"]
        if m.group(1) == "00":
            return "pass"
        text = err[err.find("test output:") + len("test output:"):]
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        why = lines[-1] if lines else ""
        # blargg prints the reason just above "Failed"; keep both.
        if len(lines) >= 2 and lines[-1].lower().startswith("failed"):
            why = lines[-2] + " / " + lines[-1]
        return "fail: $%s %s" % (m.group(1), why)
    if test["kind"] == "crc":
        lines = [l.strip().upper() for l in out.splitlines()]
        if any(l in test["crcs"] for l in lines):
            return "pass"
        shown = [l for l in lines if re.fullmatch(r"[0-9A-F]{8}", l)]
        return "fail: checksum " + (shown[0] if shown else "not shown")
    if test["kind"] == "text":
        lines = [l.strip() for l in out.splitlines()]
        if any(l.upper() == "PASSED" for l in lines) or "$01" in lines:
            return "pass"
        shown = [l for l in lines
                 if l.upper().startswith(("FAILED", "ERROR", "$"))]
        return "fail: " + (shown[0] if shown else " / ".join(lines)[:60])
    if test["kind"] == "frame":
        if not os.path.exists(png):
            return "fail: no picture"
        return "frame:" + png_pixels_crc(png)
    wav = png[:-4] + ".wav"
    if test["kind"] == "audio":
        if not os.path.exists(wav):
            return "fail: no sound file"
        return "audio:%08x" % zlib.crc32(wav_samples(wav).tobytes())
    if test["kind"] == "tones":
        if not os.path.exists(wav):
            return "fail: no sound file"
        return check_tones(wav, test["notes"])
    if test["kind"] == "silence":
        if not os.path.exists(wav):
            return "fail: no sound file"
        ratio, problem = silence_ratio(wav)
        if problem:
            return "fail: " + problem
        if ratio < SILENCE_LIMIT:
            return "pass"
        return "fail: loudest part between the beeps is %.3f of the beeps" % ratio
    return "fail: unknown kind " + test["kind"]


def run_one(test, cflags, libs, rt_objs):
    # ROMs made for this project live in tests/; the rest are in the clone.
    rom = os.path.join(ROOT if test["rom"].startswith("tests/") else ROMS,
                       test["rom"])
    ident = re.sub(r"[^A-Za-z0-9_.-]", "_", test["name"])
    c_file = os.path.join(BUILD, ident + ".c")
    exe = os.path.join(BUILD, ident)
    png = os.path.join(BUILD, ident + ".png")
    missed = rom + ".missed"

    def read_missed():
        return open(missed).read() if os.path.exists(missed) else ""

    for passes in range(1, MAX_PASSES + 1):
        args = ["python3", "recomp.py", rom, "-o", c_file]
        if os.path.exists(missed):
            args += ["--missed", missed]
        r = sh(args, cwd=ROOT)
        if r.returncode:
            return test, "fail: recompile error " + r.stderr[-200:], passes
        r = sh(["cc", "-O1", "-Iruntime"] + cflags +
               ["-o", exe, c_file] + rt_objs + libs, cwd=ROOT)
        if r.returncode:
            return test, "fail: compile error " + r.stderr[:200], passes
        before = read_missed()
        # --no-save: battery RAM from an earlier run must not change results.
        cmd = [exe, rom, "--headless", "--no-save", "--frames", str(test["frames"])]
        if test["kind"] in ("text", "crc"):
            cmd.append("--dump-text")
        if test["kind"] == "frame":
            cmd += ["--screenshot", png]
        if test["kind"] in ("audio", "silence", "tones"):
            cmd += ["--wav", png[:-4] + ".wav"]
        if test["script"]:
            cmd += ["--input", os.path.join(ROOT, test["script"])]
        cmd += test["args"]
        try:
            r = sh(cmd, cwd=ROOT, timeout=120)
        except subprocess.TimeoutExpired:
            return test, "fail: timed out", passes
        if read_missed() == before:
            break                       # nothing new learned: final result
    return test, judge(test, r.stdout, r.stderr, png), passes


def main():
    update = "--update" in sys.argv
    filters = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not os.path.isdir(ROMS):
        sys.exit("test ROMs not found; clone them first:\n  git clone --depth 1 "
                 "https://github.com/christopherpow/nes-test-roms.git "
                 "tests/roms/nes-test-roms")
    tests = [t for t in load_suite()
             if not filters or any(f in t["name"] for f in filters)]
    expected = load_expected()
    cflags, libs = sdl_flags()
    rt_objs = build_runtime(cflags)

    results = {}
    with concurrent.futures.ThreadPoolExecutor(os.cpu_count() or 4) as pool:
        jobs = [pool.submit(run_one, t, cflags, libs, rt_objs) for t in tests]
        for job in concurrent.futures.as_completed(jobs):
            test, result, passes = job.result()
            results[test["name"]] = (result, passes)

    worse, better, changed, new = [], [], [], []
    passed = 0
    for t in tests:
        name = t["name"]
        result, passes = results[name]
        want = expected.get(name)
        ok = result == "pass" or result.startswith(("frame:", "audio:"))
        passed += result == "pass"
        mark = "ok  " if ok else "FAIL"
        note = ""
        if want is None:
            new.append(name)
            note = "  (new)"
        elif result != want:
            if want == "pass" or want.startswith(("frame:", "audio:")):
                worse.append(name)
                note = "  <-- WORSE, expected " + want
            elif result == "pass":
                better.append(name)
                note = "  <-- better, expected " + want
            else:
                changed.append(name)
                note = "  <-- changed, expected " + want
        shown = result
        if result == want and result.startswith("frame:"):
            shown = "picture matches"
        elif result == want and result.startswith("audio:"):
            shown = "sound matches"
        print("%s %-58s %s%s%s" % (mark, name, shown,
                                    "" if passes == 1 else
                                    " [%d passes]" % passes, note))

    graded = sum(1 for t in tests if t["kind"] not in ("frame", "audio"))
    pics = sum(1 for t in tests if t["kind"] == "frame")
    sounds = sum(1 for t in tests if t["kind"] == "audio")
    print("\n%d of %d tests pass, %d pictures and %d sounds checked."
          % (passed, graded, pics, sounds))
    if worse:
        print("%d got WORSE than expected." % len(worse))
    if better or changed or new:
        print("%d better, %d changed, %d new: run with --update to accept."
              % (len(better), len(changed), len(new)))

    if update:
        merged = dict(expected)
        merged.update({n: r for n, (r, _) in results.items()})
        with open(EXPECTED, "w") as f:
            f.write("# Expected results for tests/run_tests.py. "
                    "Regenerate with --update.\n")
            for t in load_suite():
                if t["name"] in merged:
                    f.write("%s\t%s\n" % (t["name"], merged[t["name"]]))
        print("wrote", os.path.relpath(EXPECTED, ROOT))
        return 0
    return 1 if worse else 0


if __name__ == "__main__":
    sys.exit(main())
