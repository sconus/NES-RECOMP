#!/usr/bin/env python3
"""Breaks for the Windows test bench (PLAN-windows.md step 1): run by the
GitHub workflow on its Windows machine, after the real check. Each break
is made in a scratch copy of the project on that machine (never in the
repository), the recompiler built from it with Zig, and
tests/check_same_c.py run with it.

    python tests/windows_breaks.py [--cc "zig cc"]

Caught = a check printed a FAIL line (or the suite a "<-- WORSE") and
ended with a failing status (so the workflow would have failed). The copy with no break must pass.
A break whose recompiler fails to build is reported, not counted.
Exit status 0 when the copy with no break passes and every break is
caught.

Step 1's breaks (checked with tests/check_same_c.py) are the mistakes a
Windows build of the recompiler invites:
  - the C written as text (Windows then writes "\\r\\n" line ends);
  - the listing written as text;
  - a ROM read as text (Windows then stops at a byte $1A and turns
    "\\r\\n" into "\\n");
  - a number cut to 32 bits: a key mixing the bank and the address held
    in an `unsigned long`, which is 64 bits on the Mac but 32 on Windows,
    so banks run together.
On the Mac they change nothing, which is why they're checked on Windows.

Step 2's (checked with tests/check_runtime_sys.py, and a few tests of the
suite, tests/run_tests.py, with the runtime of the copy) are in the
runtime's Windows half (runtime/sys.c) and in what it makes:
  - the default folder for pictures wrong on Windows;
  - folders not made two levels deep on Windows;
  - a file's being there never seen on Windows (a second picture in the
    same second written over the first);
  - Ctrl+Break not caught on Windows (the game killed, not ended well);
  - a picture's red and blue swapped;
  - the sound made at 44,100 samples a second instead of 48,000.
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


SAME_C = [["tests/check_same_c.py", "--recompiler", "{exe}"]]
RUNTIME = [["tests/check_runtime_sys.py"],
           ["tests/run_tests.py", "240pee/240pee.nes", "tests/nsf_rate.nsf"]]
BREAKS = [
    ("no break: the copy as it is (must pass)", lambda w: None, SAME_C + RUNTIME),
    ("the C written as text",
     lambda w: sub(w, "recomp/main.c", 'FILE *f = fopen(out, "wb");', 'FILE *f = fopen(out, "w");'), SAME_C),
    ("the listing written as text",
     lambda w: sub(w, "recomp/main.c", 'lf = fopen(listing, "wb");', 'lf = fopen(listing, "w");'), SAME_C),
    ("a ROM read as text",
     lambda w: sub(w, "recomp/rom.c", 'FILE *f = fopen(path, "rb");', 'FILE *f = fopen(path, "r");'), SAME_C),
    ("a number cut to 32 bits (bank and address in an unsigned long)",
     lambda w: sub(w, "recomp/gen.c",
                   "static uint64_t loc_key(int bank, long addr) { return (uint64_t)(uint32_t)bank << 32 | (uint32_t)addr; }",
                   "static uint64_t loc_key(int bank, long addr) { return (unsigned long)((unsigned long)(uint32_t)bank << 32 | (uint32_t)addr); }"),
     SAME_C),
    ("pictures' default folder wrong on Windows",
     lambda w: sub(w, "runtime/sys.c", '"%s\\\\Videos\\\\NES RECOMP"', '"%s\\\\Pictures\\\\NES RECOMP"'), RUNTIME[:1]),
    ("folders not made two levels deep on Windows",
     lambda w: sub(w, "runtime/sys.c", "        if ((*p == '\\\\' || *p == '/') && p[-1] != ':') {",
                   "        if (0) {"), RUNTIME[:1]),
    ("a file's being there never seen on Windows",
     lambda w: sub(w, "runtime/sys.c", "int sys_exists(const char *path) { return _access(path, 0) == 0; }",
                   "int sys_exists(const char *path) { (void)path; return 0; }"), RUNTIME[:1]),
    ("Ctrl+Break not caught on Windows",
     lambda w: sub(w, "runtime/sys.c", "    SetConsoleCtrlHandler(on_console, TRUE);", "    (void)on_console;"), RUNTIME[:1]),
    ("a picture's red and blue swapped",
     lambda w: sub(w, "runtime/screenshot.c", "            r[1 + x * 3] = c >> 16;\n            r[2 + x * 3] = c >> 8;\n            r[3 + x * 3] = (uint8_t)c;",
                   "            r[3 + x * 3] = c >> 16;\n            r[2 + x * 3] = c >> 8;\n            r[1 + x * 3] = (uint8_t)c;"), RUNTIME[1:]),
    ("the sound made at 44,100 samples a second",
     lambda w: sub(w, "runtime/apu.c", "#define SAMPLE_RATE 48000", "#define SAMPLE_RATE 44100"), RUNTIME[1:]),
]


def main():
    args = sys.argv[1:]
    cc = shlex.split(args[args.index("--cc") + 1]) if "--cc" in args else ["zig", "cc"]
    exe = "nesrecomp-recomp.exe" if os.name == "nt" else "nesrecomp-recomp"
    results = []
    only = [a for a in args if not a.startswith("--") and a != (args[args.index("--cc") + 1] if "--cc" in args else None)]
    for name, apply, checks in BREAKS:
        if only and not any(o in name for o in only):
            continue
        work = tempfile.mkdtemp(prefix="nesrecomp break ")
        try:
            # The parts the check uses: the recompiler's source, recomp.py,
            # tests/ (with the test ROM clone), and git's list of files.
            for d in ("recomp", "runtime", "tests", ".git"):         # (tests/ with the ROM clone)
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
            # Each check, from the copy (its runtime too), with its recompiler.
            env = dict(os.environ, NESRECOMP_RECOMP=out)
            outs, errs, status = "", "", 0
            for chk in checks:
                argv = [a.replace("{exe}", out) for a in chk]
                c = subprocess.run([sys.executable, os.path.join(work, argv[0])] + argv[1:], cwd=work,
                                   capture_output=True, text=True, timeout=3600, env=env)
                outs += c.stdout
                errs += c.stderr
                status = status or c.returncode
            # A FAIL line, or the suite's "<-- WORSE" (a picture or sound it
            # shows as "ok" when it only differs from what's expected).
            fl = [l for l in outs.splitlines() if l.startswith("FAIL") or "<-- WORSE" in l]
            if "Traceback" in errs and not fl:
                results.append((name, "CHECK CRASHED (not counted): " + errs.strip().splitlines()[-1]))
            elif fl and status:
                results.append((name, "caught (%d): %s" % (len(fl), "; ".join(l[6:90] for l in fl[:2]))))
            elif fl:
                results.append((name, "FAIL lines, but the check ended well (the workflow wouldn't fail)"))
            else:
                results.append((name, "NOT CAUGHT" if status == 0 else "failed with no FAIL line"))
            print(name, "->", results[-1][1], flush=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    print()
    for name, r in results:
        print("%-64s %s" % (name, r[:150]))
    nb = [r for n, r in results if n.startswith("no break")]
    breaks = [r for n, r in results if not n.startswith("no break")]
    clean = nb == ["NOT CAUGHT"]
    caught = sum(r.startswith("caught") for r in breaks)
    print("\nthe copy with no break %s; %d of %d breaks caught"
          % ("passed" if clean else "wasn't run" if not nb else "DID NOT PASS", caught, len(breaks)))
    sys.exit(0 if clean and caught == len(breaks) else 1)


if __name__ == "__main__":
    main()
