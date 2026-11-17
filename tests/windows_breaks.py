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

Step 3's (checked with tests/check_record_win.py) are in recording on
Windows (runtime/record_win.c):
  - the sound a frame late;
  - a frame dropped;
  - the wrong rate (60 frames a second, not 60.0988);
  - no sound;
  - a file not finished on quit;
  - frames shown out of order (H.264's High profile, with B-frames: the
    picture a frame behind the sound).

Step 4's (checked with tests/check_app.py, with the app put together
from the copy by tools/make_windows_app.py) are in the app's Windows
half (app/os_win.c, support_win.c) and its build (app/build.c):
  - a path with a space breaking a build (an argument with a space not
    quoted for Windows);
  - the app's folder in the wrong place;
  - a build that never finishes (a program's end never seen);
  - SDL2.dll not beside a game;
  - the support link wrong in the window's menu.
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
RECORD = [["tests/check_record_win.py"]]
APP = [["tests/check_app.py"]]


def wrong_rate(w):
    sub(w, "runtime/record_win.c", "set_pair(a, &MF_MT_FRAME_RATE, FRAME_DEN, FRAME_NUM);",
        "set_pair(a, &MF_MT_FRAME_RATE, 60, 1);")
    sub(w, "runtime/record_win.c", "{ return (n * 10482736 + 31) / 63; }", "{ return n * 10000000 / 60; }")


BREAKS = [
    ("no break: the copy as it is (must pass)", lambda w: None, SAME_C + RUNTIME + RECORD + APP),
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
    ("recording: the sound a frame late",
     lambda w: sub(w, "runtime/record_win.c", "(DWORD)n * 2, 0, sample_time(at),",
                   "(DWORD)n * 2, 0, sample_time(at + 800),"), RECORD),
    ("recording: a frame dropped",
     lambda w: sub(w, "runtime/record_win.c", "    long long n = frames++;\n",
                   "    long long n = frames++;\n    if (n == 100) return;\n"), RECORD),
    ("recording: the wrong rate (60 a second)", wrong_rate, RECORD),
    ("recording: no sound",
     lambda w: sub(w, "runtime/record_win.c", "    if (!writer || n <= 0) return;\n    long long at",
                   "    return;\n    long long at"), RECORD),
    ("recording: the file not finished on quit",
     lambda w: sub(w, "runtime/record_win.c", "HRESULT hr = IMFSinkWriter_Finalize(writer);",
                   "HRESULT hr = S_OK;"), RECORD),
    ("recording: frames shown out of order (B-frames)",
     lambda w: sub(w, "runtime/record_win.c", "&MF_MT_MPEG2_PROFILE, 66);", "&MF_MT_MPEG2_PROFILE, 100);"), RECORD),
    ("app: a path with a space breaking a build",
     lambda w: sub(w, "app/os_win.c", 'int q = !*a || wcspbrk(a, L" \\t\\"") != NULL;',
                   'int q = !*a || wcspbrk(a, L"\\t\\"") != NULL;'), APP),
    ("app: its folder in the wrong place",
     lambda w: sub(w, "app/os_win.c", 'snprintf(out, n, "%s\\\\NES RECOMP", base);',
                   'snprintf(out, n, "%s\\\\NES-RECOMP", base);'), APP),
    ("app: a build that never finishes (a program's end never seen)",
     lambda w: sub(w, "app/os_win.c", "    if (r == WAIT_TIMEOUT) return 0;",
                   "    if (r == WAIT_TIMEOUT || r == WAIT_OBJECT_0) return 0;"), APP),
    ("app: SDL2.dll not beside a game",
     lambda w: sub(w, "app/build.c", '    snprintf(dest, n, "%s/SDL2.dll", build_dir);',
                   '    snprintf(dest, n, "%s/SDL2.dll.copy", build_dir);'), APP),
    ("app: the support link wrong in the window's menu",
     lambda w: sub(w, "app/support_win.c", "        support_open();\n        return 0;",
                   '        os_open_url("https://ko-fi.com/");\n        return 0;'), APP),
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
            for d in ("recomp", "runtime", "app", "tools", "tests", ".git"):  # (tests/ with the ROM clone)
                shutil.copytree(os.path.join(ROOT, d), os.path.join(work, d), symlinks=True,
                                ignore=shutil.ignore_patterns("build"))
            for f in ("recomp.py", "LICENSE"):
                shutil.copy(os.path.join(ROOT, f), work)
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
            # The app, from the copy, when a check needs it.
            if any(chk in APP for chk in checks):
                a = subprocess.run([sys.executable, os.path.join(work, "tools", "make_windows_app.py"),
                                    "--cc", " ".join(cc), "--sdl2", os.environ["NESRECOMP_SDL2"],
                                    "--zlib-src", os.environ["NESRECOMP_ZLIB_SRC"], "--recomp", out,
                                    "--out", os.path.join(work, "build", "windows", "app")],
                                   capture_output=True, text=True)
                if a.returncode:
                    results.append((name, "BUILD FAILED (not counted): the app: " +
                                    ((a.stdout + a.stderr).strip().splitlines() or ["?"])[-1]))
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
