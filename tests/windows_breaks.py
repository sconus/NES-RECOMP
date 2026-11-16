#!/usr/bin/env python3
"""Breaks for the Windows test bench (PLAN-windows.md step 1): run by the
GitHub workflow on its Windows machine, after the real check. Each break
is made in a scratch copy of the project on that machine (never in the
repository), the recompiler built from it with Zig, and
tests/check_same_c.py run with it.

    python tests/windows_breaks.py [--cc "zig cc"]

Caught = the check printed a FAIL line and ended with a failing status
(so the workflow would have failed). The copy with no break must pass.
A break whose recompiler fails to build is reported, not counted.
Exit status 0 when the copy with no break passes and every break is
caught.

The breaks are the mistakes a Windows build invites:
  - the C written as text (Windows then writes "\\r\\n" line ends);
  - the listing written as text;
  - a ROM read as text (Windows then stops at a byte $1A and turns
    "\\r\\n" into "\\n");
  - a number cut to 32 bits: a key mixing the bank and the address held
    in an `unsigned long`, which is 64 bits on the Mac but 32 on Windows,
    so banks run together.
On the Mac they change nothing, which is why they're checked on Windows.
"""
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def sub(work, path, old, new):
    p = os.path.join(work, path)
    s = open(p, encoding="utf-8").read()
    assert s.count(old) == 1, (path, old, s.count(old))
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s.replace(old, new))


BREAKS = [
    ("no break: the copy as it is (must pass)", lambda w: None),
    ("the C written as text",
     lambda w: sub(w, "recomp/main.c", 'FILE *f = fopen(out, "wb");', 'FILE *f = fopen(out, "w");')),
    ("the listing written as text",
     lambda w: sub(w, "recomp/main.c", 'lf = fopen(listing, "wb");', 'lf = fopen(listing, "w");')),
    ("a ROM read as text",
     lambda w: sub(w, "recomp/rom.c", 'FILE *f = fopen(path, "rb");', 'FILE *f = fopen(path, "r");')),
    ("a number cut to 32 bits (bank and address in an unsigned long)",
     lambda w: sub(w, "recomp/gen.c",
                   "static uint64_t loc_key(int bank, long addr) { return (uint64_t)(uint32_t)bank << 32 | (uint32_t)addr; }",
                   "static uint64_t loc_key(int bank, long addr) { return (unsigned long)((unsigned long)(uint32_t)bank << 32 | (uint32_t)addr); }")),
]


def main():
    args = sys.argv[1:]
    cc = shlex.split(args[args.index("--cc") + 1]) if "--cc" in args else ["zig", "cc"]
    exe = "nesrecomp-recomp.exe" if os.name == "nt" else "nesrecomp-recomp"
    results = []
    for name, apply in BREAKS:
        work = tempfile.mkdtemp(prefix="nesrecomp break ")
        try:
            # The parts the check uses: the recompiler's source, recomp.py,
            # tests/ (with the test ROM clone), and git's list of files.
            for d in ("recomp", "runtime", "tests", ".git"):
                shutil.copytree(os.path.join(ROOT, d), os.path.join(work, d), symlinks=True,
                                ignore=shutil.ignore_patterns("build"))
            shutil.copy(os.path.join(ROOT, "recomp.py"), work)
            apply(work)
            out = os.path.join(work, "build", exe)
            os.makedirs(os.path.dirname(out))
            srcs = sorted(os.path.join(work, "recomp", f) for f in os.listdir(os.path.join(work, "recomp"))
                          if f.endswith(".c"))
            b = subprocess.run(cc + ["-O2", "-o", out] + srcs, capture_output=True, text=True)
            if b.returncode:
                results.append((name, "BUILD FAILED (not counted): " + (b.stderr.strip().splitlines() or ["?"])[-1]))
                print(name, "->", results[-1][1], flush=True)
                continue
            c = subprocess.run([sys.executable, os.path.join(work, "tests", "check_same_c.py"),
                                "--recompiler", out], capture_output=True, text=True, timeout=1800)
            fl = [l for l in c.stdout.splitlines() if l.startswith("FAIL")]
            if "Traceback" in c.stderr and not fl:
                results.append((name, "CHECK CRASHED (not counted): " + c.stderr.strip().splitlines()[-1]))
            elif fl and c.returncode:
                results.append((name, "caught (%d): %s" % (len(fl), "; ".join(l[6:90] for l in fl[:2]))))
            elif fl:
                results.append((name, "FAIL lines, but the check ended well (the workflow wouldn't fail)"))
            else:
                results.append((name, "NOT CAUGHT" if c.returncode == 0 else "failed with no FAIL line"))
            print(name, "->", results[-1][1], flush=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    print()
    for name, r in results:
        print("%-64s %s" % (name, r[:150]))
    clean = results and results[0][1] == "NOT CAUGHT"
    caught = sum(r.startswith("caught") for _, r in results[1:])
    print("\nthe copy with no break %s; %d of %d breaks caught"
          % ("passed" if clean else "DID NOT PASS", caught, len(results) - 1))
    sys.exit(0 if clean and caught == len(results) - 1 else 1)


if __name__ == "__main__":
    main()
