#!/usr/bin/env python3
"""What `make test` does, on any system (PLAN-windows.md step 2; the
Windows test bench runs it): nestest recompiled from $C000 (with its
.missed if there is one), built with the runtime (tests/toolchain.py),
then:
  1. run headless from $C000, tracing every instruction and checking
     each one's cycles: the trace against tests/nestest.log
     (tests/compare_nestest.py), exactly;
  2. the game controller self-test (--test-gamepads);
     the keyboard remapping's self-test (--test-controls);
  3. tests/check_headers.py with the built program.
Exit status 0 when all pass.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import toolchain  # noqa: E402

OUT = os.path.join(ROOT, "build", "nestest_run")


def run(args, **kw):
    r = subprocess.run(args, capture_output=True, text=True, **kw)
    return r


def main():
    os.makedirs(OUT, exist_ok=True)
    rom = os.path.join(HERE, "nestest.nes")
    c = os.path.join(OUT, "nestest.c")
    args = [toolchain.recompiler(), rom, "-o", c, "--entry", "C000"]
    if os.path.exists(rom + ".missed"):
        args += ["--missed", rom + ".missed"]
    r = run(args)
    if r.returncode:
        sys.exit("recompiling failed: " + r.stderr)
    cflags, libs = toolchain.sdl_flags()
    exe = os.path.join(OUT, "nestest" + toolchain.EXE)
    srcs = [os.path.join(ROOT, "runtime", f) for f in toolchain.runtime_sources()]
    r = run(toolchain.cc() + ["-O1", "-Wall", "-I" + os.path.join(ROOT, "runtime")] + cflags +
            ["-o", exe, c] + srcs + libs)
    if r.returncode:
        sys.exit("building failed: " + r.stderr[-2000:])
    print("built", exe, flush=True)
    failed = 0
    trace = os.path.join(OUT, "trace.txt")
    with open(trace, "w") as f:
        r = subprocess.run([exe, rom, "--headless", "--start", "C000", "--trace", "--check-cycles"],
                           stdout=f, stderr=subprocess.PIPE, text=True, timeout=600)
    cmp = run([sys.executable, os.path.join(HERE, "compare_nestest.py"),
               os.path.join(HERE, "nestest.log"), trace])
    print(cmp.stdout.strip() or cmp.stderr.strip(), flush=True)
    failed += cmp.returncode != 0
    g = run([exe, "--test-gamepads"], timeout=120)
    print((g.stdout + g.stderr).strip().splitlines()[-1:] or ["(nothing)"], flush=True)
    if g.returncode:
        print("FAIL  --test-gamepads: exit %d" % g.returncode)
        failed += 1
    c = run([exe, "--test-controls"], timeout=120)
    if c.returncode:
        print("\n".join(l for l in c.stderr.splitlines() if l.startswith("FAIL")))
        print("FAIL  --test-controls: exit %d" % c.returncode)
        failed += 1
    else:
        print(c.stdout.strip().splitlines()[-1:] or ["(nothing)"], flush=True)
    h = run([sys.executable, os.path.join(HERE, "check_headers.py"), exe], timeout=600)
    print(h.stdout.strip().splitlines()[-1] if h.stdout.strip() else h.stderr.strip()[-500:], flush=True)
    if h.returncode:
        print("\n".join(l for l in h.stdout.splitlines() if l.startswith("FAIL")))
        failed += 1
    print("\nall of make test passes" if not failed else "\n%d part(s) of make test failed" % failed)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
