#!/usr/bin/env python3
"""Save states, rewind and fast-forward over the whole suite
(PLAN-savestates.md steps 1-4).

For every ROM in tests/suite.txt (with its input script and options):
recompile it, then run it headless with --state-test N M: N frames,
save a state, M more frames noting a fingerprint of each (picture, RAM,
sound), load the state, the same M frames again. Every fingerprint must
match. N is a third of the suite's frame count (at most 600), so the
state is taken mid-run, not at power-on, and inside the input script.

Then the same across two runs (step 2): one run saves the state to a
file and notes the fingerprints (--state-out), quits, and a fresh run
loads the file at the start (--state-in) and must match them. Last, a
few state files that must be refused: one from another game, one with
an older format number, one that isn't a state, one cut short.

And rewind (step 3): --rewind-test N M plays N + M frames, rewinds M,
and plays forward again; every frame on the way must be the right one
and match the first time through. Once with the usual ring (600
frames), once with a ring of 50, so it fills and rewind stops at the
oldest frame kept.

And fast-forward (step 4): the same frames played with the key held
the whole run (--hold-fast) must come out exactly as without it, frame
by frame (--prints-out: picture, RAM, sound, code counts).

    python3 tests/check_states.py            every ROM
    python3 tests/check_states.py mmc3       only names matching

The runs keep their .missed notes in build/states/, not beside the ROMs,
so the suite's own files don't change.
"""
import concurrent.futures
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_tests  # noqa: E402
import toolchain  # noqa: E402

ROOT = run_tests.ROOT
OUT = os.path.join(ROOT, "build", "states")
M = 120


def frames_for(test):
    return max(10, min(test["frames"] // 3, 600))


def run_one(test, cflags, libs, rt_objs):
    rom = os.path.join(ROOT if test["rom"].startswith("tests/") else run_tests.ROMS,
                       test["rom"])
    ident = re.sub(r"[^A-Za-z0-9_.-]", "_", test["name"])
    c_file = os.path.join(OUT, ident + ".c")
    exe = os.path.join(OUT, ident + toolchain.EXE)
    args = [toolchain.recompiler(), rom, "-o", c_file]
    if os.path.exists(rom + ".missed"):
        args += ["--missed", rom + ".missed"]
    r = run_tests.sh(args, cwd=ROOT)
    if r.returncode:
        return test, "fail: recompile error " + r.stderr[-200:]
    r = run_tests.sh(toolchain.cc() + ["-O1", "-Iruntime"] + cflags +
                     ["-o", exe, c_file] + rt_objs + libs, cwd=ROOT)
    if r.returncode:
        return test, "fail: compile error " + r.stderr[:200]
    cmd = [exe, rom, "--headless", "--no-save",
           "--files-at", os.path.join(OUT, ident),
           "--state-test", str(frames_for(test)), str(M)]
    if test["script"]:
        cmd += ["--input", os.path.join(ROOT, test["script"])]
    # Options for the runner itself (--translated) aren't the program's.
    cmd += [a for a in test["args"] if a != "--ram-stats"]
    test["cmd"] = cmd
    line = state_run(cmd)
    if not line.startswith("pass"):
        return test, "fail: " + line + " (in one run)"
    # Across two runs: save to a file and quit, then load it in a new run.
    state_file = os.path.join(OUT, ident + ".state")
    test["state_file"] = state_file
    for f in (state_file, state_file + ".prints"):
        if os.path.exists(f):
            os.remove(f)
    out = state_run(cmd + ["--state-out", state_file])
    if not out.startswith("saved"):
        return test, "fail: " + out + " (saving to a file)"
    two = state_run(cmd + ["--state-in", state_file])
    if not two.startswith("pass"):
        return test, "fail: " + two + " (loading in a new run)"
    # Rewind: the same command, with --rewind-test in place of --state-test.
    at = cmd.index("--state-test")
    rw_cmd = cmd[:at] + ["--rewind-test", cmd[at + 1], cmd[at + 2]] + cmd[at + 3:]
    for ring in ([], ["--rewind-frames", "50"]):
        rw = rewind_run(rw_cmd + ring)
        if not rw.startswith("pass"):
            return test, "fail: " + rw + (" (rewind, ring of 50)" if ring else " (rewind)")
    m = re.search(r"\(\d+ kept, (\d+) bytes\)", rewind_run(rw_cmd))
    test["rewind_bytes"] = int(m.group(1)) if m else 0
    # Fast-forward held the whole run: the same frames, frame by frame.
    plain = cmd[:at] + ["--frames", str(int(cmd[at + 1]) + M)] + cmd[at + 3:]
    prints = []
    for extra in ([], ["--hold-fast"]):
        out = os.path.join(OUT, ident + (".fast" if extra else ".plain") + ".prints")
        try:
            run_tests.sh(plain + extra + ["--prints-out", out], cwd=ROOT, timeout=120)
        except run_tests.subprocess.TimeoutExpired:
            return test, "fail: timed out (fast-forward)"
        prints.append(open(out, "rb").read() if os.path.exists(out) else b"")
    if not prints[0]:
        return test, "fail: no frames noted (fast-forward)"
    if prints[0] != prints[1]:
        n = min(len(prints[0]), len(prints[1])) // 32
        k = next((i for i in range(n) if prints[0][i * 32:i * 32 + 32] != prints[1][i * 32:i * 32 + 32]), n)
        return test, "fail: fast-forward changed the game: frame %d differs (%d frames, %d)" % (
            k + 1, len(prints[0]) // 32, len(prints[1]) // 32)
    return test, line + "; from a file in a new run; rewind; fast-forward (%d frames)" % (
        len(prints[0]) // 32)


def rewind_run(cmd):
    try:
        r = run_tests.sh(cmd, cwd=ROOT, timeout=120)
    except run_tests.subprocess.TimeoutExpired:
        return "timed out"
    m = re.search(r"rewind test: (.*)", r.stderr)
    if not m:
        return "no rewind test result"
    line = m.group(1)
    return line[len("FAIL: "):] if line.startswith("FAIL: ") else line


def state_run(cmd, want=None):
    """The program's "state test:" line, or what went wrong. With `want`,
    the line of a refused load must name it."""
    try:
        r = run_tests.sh(cmd, cwd=ROOT, timeout=120)
    except run_tests.subprocess.TimeoutExpired:
        return "timed out"
    if want is not None:
        return "refused" if (want in r.stderr and "the state didn't load" in r.stderr) \
            else "not refused: " + r.stderr[-300:]
    m = re.search(r"state test: (.*)", r.stderr)
    if not m:
        stop = re.search(r"stopped: (.*)", r.stderr)
        return stop.group(1) if stop else "no state test result"
    line = m.group(1)
    return line[len("FAIL: "):] if line.startswith("FAIL: ") else line


def refusals(tests):
    """State files that must be refused, whole: from another game, an
    older format, not a state at all, cut short."""
    good = [t for t in tests if t.get("state_file") and os.path.exists(t["state_file"])]
    roms = {}
    for t in good:
        roms.setdefault(t["cmd"][1], t)
    if len(roms) < 2:
        return ["fail: need two games with state files to check refusals"]
    a, b = list(roms.values())[:2]
    data = open(a["state_file"], "rb").read()
    bad = os.path.join(OUT, "refused.state")
    cases = [
        ("from another game", a["state_file"], b, "IS ANOTHER GAME'S"),
        ("an older format", data[:16] + (0).to_bytes(4, "little") + data[20:], a,
         "IS AN OLDER FORMAT"),
        ("not a state", b"NESRECOMP STATX\n" + data[16:], a, "ISN'T A STATE"),
        ("cut short", data[:-1], a, "ISN'T A STATE"),
        ("one byte too many", data + b"\0", a, "ISN'T A STATE"),
    ]
    out = []
    for what, src, test, want in cases:
        if isinstance(src, bytes):
            with open(bad, "wb") as f:
                f.write(src)
            path = bad
        else:
            path = src
        # The fingerprints are read before the load: any will do.
        if path != a["state_file"]:
            shutil.copyfile(a["state_file"] + ".prints", path + ".prints")
        r = state_run(test["cmd"] + ["--state-in", path], want=want)
        out.append(("ok  " if r == "refused" else "FAIL") + "  a state " + what +
                   ": " + r)
    return out


def main():
    filters = [a for a in sys.argv[1:] if not a.startswith("--")]
    os.makedirs(OUT, exist_ok=True)
    seen, tests = set(), []
    for t in run_tests.load_suite():
        if t["rom"].endswith(".nsf"):
            continue                    # NSF music gets no save states
        # A sound test may share its ROM, script and options with a picture.
        key = (t["rom"], t["script"], tuple(t["args"]))
        if key in seen or (filters and not any(f in t["name"] for f in filters)):
            continue
        seen.add(key)
        tests.append(t)
    cflags, libs = run_tests.sdl_flags()
    rt_objs = run_tests.build_runtime(cflags)
    results = {}
    with concurrent.futures.ThreadPoolExecutor(os.cpu_count() or 4) as pool:
        for job in concurrent.futures.as_completed(
                [pool.submit(run_one, t, cflags, libs, rt_objs) for t in tests]):
            test, result = job.result()
            results[test["name"]] = result
    failed = 0
    sizes = []
    for t in tests:
        result = results[t["name"]]
        ok = result.startswith("pass")
        failed += not ok
        m = re.search(r"state of (\d+) bytes", result)
        if m:
            sizes.append(int(m.group(1)))
        print("%s  %s  %s" % ("ok  " if ok else "FAIL", t["name"], result))
    print("\n%d of %d ROMs load their state and run on the same, in one run,"
          " from a file in a new one, rewind, and fast-forward" % (len(tests) - failed, len(tests)))
    print()
    for line in refusals(tests):
        print(line)
        failed += line.startswith("FAIL")
    if sizes:
        print("state size: %d to %d bytes" % (min(sizes), max(sizes)))
    rw = sorted(t.get("rewind_bytes", 0) for t in tests if t.get("rewind_bytes"))
    if rw:
        print("rewind memory (up to 600 frames kept, %d of them rewound): %d to %d bytes (median %d)" %
              (M, rw[0], rw[-1], rw[len(rw) // 2]))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
