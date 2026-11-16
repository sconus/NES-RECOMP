#!/usr/bin/env python3
"""The same C on every system (PLAN-windows.md step 1).

    python3 tests/check_same_c.py --write
        on the Mac: recompile every ROM, NSF and disk image under tests/
        (the project's own, and the free test ROM clone's, as git lists
        them) with build/nesrecomp-recomp, alone and with --listing, and
        nestest as `make test` recompiles it (--entry C000); and write
        down the fingerprints (SHA-256) of each C file, each listing and
        what it printed, in tests/same_c.txt
    python3 tests/check_same_c.py [--recompiler PATH]
        anywhere (the Windows test bench runs it with
        build/windows/nesrecomp-recomp.exe): recompile them all again with
        that recompiler and check:
          1. every file's C, listing and printed lines are byte for byte
             what the Mac's recompiler made (tests/same_c.txt): the same
             C on every system;
          2. what it reads from each file (--dump-rom) is what recomp.py
             reads, line for line, on this system;
          3. a file it refuses, it refuses with the same message.
        Exit status 0 when all pass, 1 otherwise.

Printed lines are compared with the ROM's path written as ROM and the
output paths as OUT and LST (they differ between machines), and line ends
as "\\n", since Windows prints "\\r\\n"; the files themselves are
compared as bytes.
"""
import hashlib
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIST = os.path.join(HERE, "same_c.txt")
CLONE = os.path.join(HERE, "roms", "nes-test-roms")
OUT = os.path.join(ROOT, "build", "same_c")
EXTS = (".nes", ".nsf", ".fds")
# A recompile takes milliseconds; one taking this long has gone wrong
# (looping forever, say), and counts as a different result, not a crash.
LIMIT = 60
# After one hasn't finished, the rest aren't started (each could take the
# whole minute): the check has failed already.
gave_up = []

fails = []


def check(name, ok, why=""):
    print("%s  %s%s" % ("ok   " if ok else "FAIL ", name, "" if ok else ": " + why))
    sys.stdout.flush()
    if not ok:
        fails.append(name)


def git_files(where):
    r = subprocess.run(["git", "-C", where, "ls-files"], capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l.lower().endswith(EXTS)]


def roms():
    """(name as written down, path) of every file to recompile: the
    project's own under tests/, and the clone's, as git tracks them."""
    out = [(p, os.path.join(ROOT, p)) for p in git_files(ROOT) if p.startswith("tests/")]
    if os.path.isdir(CLONE):
        out += [("tests/roms/nes-test-roms/" + p, os.path.join(CLONE, p)) for p in git_files(CLONE)]
    return sorted(out)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def norm(text, *paths):
    for p, word in paths:
        text = text.replace(p, word)
    return text.replace("\r\n", "\n")


def recompile(recomp, name, path, extra, tag):
    """The fingerprints of one recompile: exit status, C, listing, what it
    printed (stdout and stderr)."""
    c = os.path.join(OUT, tag + ".c")
    lst = os.path.join(OUT, tag + ".lst")
    for f in (c, lst):
        if os.path.exists(f):
            os.remove(f)
    if gave_up:
        return "not-run - - -"
    try:
        r = subprocess.run([recomp, path, "-o", c, "--listing", lst] + extra, capture_output=True,
                           timeout=LIMIT)
    except subprocess.TimeoutExpired:
        gave_up.append(name)
        return "didn't-finish - - -"
    printed = norm(r.stdout.decode("utf-8", "replace") + "\0" + r.stderr.decode("utf-8", "replace"),
                   (c, "OUT"), (lst, "LST"), (path, "ROM"))
    fp = [str(r.returncode),
          sha(open(c, "rb").read()) if os.path.exists(c) else "-",
          sha(open(lst, "rb").read()) if os.path.exists(lst) else "-",
          sha(printed.encode())]
    for f in (c, lst):
        if os.path.exists(f):
            os.remove(f)
    return " ".join(fp)


def jobs():
    out = [(name, path, [], "a%d" % i) for i, (name, path) in enumerate(roms())]
    out.append(("tests/nestest.nes --entry C000", os.path.join(HERE, "nestest.nes"), ["--entry", "C000"], "n"))
    return out


def main():
    args = sys.argv[1:]
    write = "--write" in args
    recomp = os.path.join(ROOT, "build", "nesrecomp-recomp")
    if "--recompiler" in args:
        recomp = os.path.abspath(args[args.index("--recompiler") + 1])
    if not os.path.exists(recomp):
        sys.exit("%s is missing" % recomp)
    os.makedirs(OUT, exist_ok=True)
    js = jobs()
    with ThreadPoolExecutor(8) as ex:
        got = list(ex.map(lambda j: (j[0], recompile(recomp, *j)), js))
    if write:
        with open(LIST, "w", newline="\n") as f:
            f.write("# The C the Mac's recompiler writes for each file under tests/ (PLAN-windows.md step 1):\n"
                    "# name <tab> exit status, SHA-256 of the C, of the listing, of what it printed.\n"
                    "# Written by `python3 tests/check_same_c.py --write`; checked on every system.\n")
            for name, fp in got:
                f.write("%s\t%s\n" % (name, fp))
        print("wrote %s: %d files" % (os.path.relpath(LIST, ROOT), len(got)))
        return
    want = {}
    for l in open(LIST, encoding="utf-8"):
        if not l.startswith("#") and "\t" in l:
            name, fp = l.rstrip("\n").split("\t")
            want[name] = fp
    have = dict(got)
    missing = sorted(set(want) - set(have))
    extra = sorted(set(have) - set(want))
    check("the same files as on the Mac (%d)" % len(want), not missing and not extra,
          "missing %s, new %s" % (missing[:3], extra[:3]))
    check("every recompile finished (within %d s each)" % LIMIT, not gave_up,
          "%s didn't finish, so the rest weren't run" % (gave_up[0] if gave_up else ""))
    common = sorted(set(want) & set(have))
    differ = [n for n in common if want[n] != have[n]]

    def what(n):
        a, b = want[n].split(), have[n].split()
        parts = ["exit status (or didn't finish)", "C", "listing", "printed lines"]
        return n + ": " + ", ".join(p for p, x, y in zip(parts, a, b) if x != y)
    refused = sum(1 for n in common if want[n].split()[0] != "0")
    check("%d recompiles: the C, the listing and the printed lines byte for byte the Mac's "
          "(%d refused as the Mac refuses them)" % (len(common), refused),
          common and not differ, "%d differ, first %s" % (len(differ), what(differ[0])) if differ else "")

    # 2. and 3.: what it reads, against recomp.py on this system.
    py = [sys.executable, os.path.join(ROOT, "recomp.py")]

    def dump(job):
        name, path, extra, _ = job
        if gave_up:
            return name, (0, "", ""), (0, "", "")
        rp = subprocess.run(py + [path, "--dump-rom"] + extra, capture_output=True, timeout=300)
        try:
            rc = subprocess.run([recomp, path, "--dump-rom"] + extra, capture_output=True, timeout=LIMIT)
        except subprocess.TimeoutExpired:
            gave_up.append(name)
            return name, (rp.returncode, norm(rp.stdout.decode("utf-8", "replace")), ""), (None, "didn't finish", "")
        p = (rp.returncode, norm(rp.stdout.decode("utf-8", "replace")), norm(rp.stderr.decode("utf-8", "replace")))
        c = (rc.returncode, norm(rc.stdout.decode("utf-8", "replace")), norm(rc.stderr.decode("utf-8", "replace")))
        return name, p, c
    with ThreadPoolExecutor(8) as ex:
        dumps = list(ex.map(dump, js))
    read = [d for d in dumps if d[1][0] == 0]
    bad = [d for d in read if d[1] != d[2]]
    check("%d files: read as recomp.py reads them (--dump-rom), line for line" % len(read),
          read and not bad, "%d differ, first %s" % (len(bad), bad[0][0]) if bad else "")
    ref = [d for d in dumps if d[1][0] != 0]
    bad = [d for d in ref if (d[2][0], d[2][2].strip().splitlines()[-1:]) !=
           (d[1][0], d[1][2].strip().splitlines()[-1:])]
    check("%d files it refuses: the same status and message as recomp.py" % len(ref), not bad,
          "%s: %r vs %r" % (bad[0][0], bad[0][1][2][-80:], bad[0][2][2][-80:]) if bad else "")

    print("\n%d check(s) failed" % len(fails) if fails else "\nall checks pass")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
