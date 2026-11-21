#!/usr/bin/env python3
"""Save states over the whole suite (PLAN-savestates.md step 1).

For every ROM in tests/suite.txt (with its input script and options):
recompile it, then run it headless with --state-test N M: N frames,
save a state, M more frames noting a fingerprint of each (picture, RAM,
sound), load the state, the same M frames again. Every fingerprint must
match. N is a third of the suite's frame count (at most 600), so the
state is taken mid-run, not at power-on, and inside the input script.

    python3 tests/check_states.py            every ROM
    python3 tests/check_states.py mmc3       only names matching

The runs keep their .missed notes in build/states/, not beside the ROMs,
so the suite's own files don't change.
"""
import concurrent.futures
import os
import re
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
    try:
        r = run_tests.sh(cmd, cwd=ROOT, timeout=120)
    except run_tests.subprocess.TimeoutExpired:
        return test, "fail: timed out"
    m = re.search(r"state test: (.*)", r.stderr)
    if not m:
        stop = re.search(r"stopped: (.*)", r.stderr)
        return test, "fail: " + (stop.group(1) if stop else "no state test result")
    line = m.group(1)
    return test, line if line.startswith("pass") else "fail: " + line


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
    print("\n%d of %d ROMs load their state and run on the same" % (len(tests) - failed, len(tests)))
    if sizes:
        print("state size: %d to %d bytes" % (min(sizes), max(sizes)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
