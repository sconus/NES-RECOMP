#!/usr/bin/env python3
"""The runtime's system parts (runtime/sys.c, PLAN-windows.md step 2), on
whichever system it runs (the Windows test bench runs it):
  1. a picture (P, through a script's "snap") saved into a folder given
     that doesn't exist yet, two levels deep, with spaces in its names;
  2. with no folder given, into the system's own: Movies/NES RECOMP on
     the Mac, Videos\\NES RECOMP on Windows (in a scratch home here);
  3. two pictures in the same second kept apart (" 2");
  4. asked to quit from outside (Ctrl+C on the Mac, Ctrl+Break on
     Windows, as a console sends them), a running game ends well: it says
     it was stopped and does what it does on quitting (its "ran ..." line).
It builds one free test ROM with the runtime (tests/toolchain.py).
Exit status 0 when all pass.
"""
import glob
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import toolchain  # noqa: E402

fails = []


def check(name, ok, why=""):
    print("%s  %s%s" % ("ok   " if ok else "FAIL ", name, "" if ok else ": " + why), flush=True)
    if not ok:
        fails.append(name)


def main():
    out = os.path.join(ROOT, "build", "sys_check")
    os.makedirs(out, exist_ok=True)
    # A ROM that runs until stopped: the picture-and-sound test ROM.
    rom = os.path.join(out, "av_sync.nes")
    subprocess.run([sys.executable, os.path.join(HERE, "make_av_sync_test.py"), rom],
                   capture_output=True, check=True)
    c = os.path.join(out, "av_sync.c")
    r = subprocess.run([toolchain.recompiler(), rom, "-o", c], capture_output=True, text=True)
    if r.returncode:
        sys.exit("recompiling failed: " + r.stderr)
    cflags, libs = toolchain.sdl_flags()
    exe = os.path.join(out, "av_sync" + toolchain.EXE)
    srcs = [os.path.join(ROOT, "runtime", f) for f in toolchain.runtime_sources()]
    r = subprocess.run(toolchain.cc() + ["-O1", "-I" + os.path.join(ROOT, "runtime")] + cflags +
                       ["-o", exe, c] + srcs + libs, capture_output=True, text=True)
    if r.returncode:
        sys.exit("building failed: " + r.stderr[-2000:])
    tmp = tempfile.mkdtemp(prefix="nesrecomp sys ")
    try:
        script = os.path.join(tmp, "keys.txt")
        with open(script, "w") as f:
            f.write("10 snap\n11 snap\n")
        # 1. and 3.: into a folder given, not there yet, two levels deep.
        given = os.path.join(tmp, "my pictures", "NES shots")
        r = subprocess.run([exe, rom, "--headless", "--frames", "20", "--input", script,
                            "--record-dir", given], capture_output=True, text=True, timeout=120)
        got = sorted(os.path.basename(p) for p in glob.glob(os.path.join(given, "*.png")))
        check("a picture into a folder given that isn't there yet (made, two levels deep)",
              len(got) >= 1, "%s; %s" % (got, r.stderr.strip()[-200:]))
        stamps = {re.sub(r"( 2)?\.png$", "", n) for n in got}
        check("two pictures in the same second kept apart",
              len(got) == 2 and (len(stamps) == 2 or any(n.endswith(" 2.png") for n in got)), "%s" % got)
        # 2. with no folder given: the system's own, in a scratch home.
        home = os.path.join(tmp, "a home")
        os.makedirs(home)
        env = dict(os.environ, HOME=home, USERPROFILE=home)
        r = subprocess.run([exe, rom, "--headless", "--frames", "20", "--input", script],
                           capture_output=True, text=True, timeout=120, env=env)
        where = os.path.join(home, "Videos", "NES RECOMP") if toolchain.WIN else \
            os.path.join(home, "Movies", "NES RECOMP")
        got = glob.glob(os.path.join(where, "av_sync *.png"))
        check("with no folder given: in %s" % where.replace(home, "~"), len(got) == 2,
              "%s; %s" % (got, r.stderr.strip()[-200:]))
        # 4. asked to quit from outside.
        kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if toolchain.WIN else {}
        p = subprocess.Popen([exe, rom, "--headless"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, **kw)
        time.sleep(2)
        p.send_signal(signal.CTRL_BREAK_EVENT if toolchain.WIN else signal.SIGINT)
        try:
            _, err = p.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
            _, err = p.communicate()
        check("asked to quit from outside: it ends well (stopped, its quitting done)",
              "stopped by a signal" in err and "ran " in err and "instruction(s) as translated C" in err,
              "exit %s, %r" % (p.returncode, err.strip()[-200:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d check(s) failed" % len(fails) if fails else "\nall checks pass")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
