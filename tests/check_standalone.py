#!/usr/bin/env python3
"""Check the standalone app (PLAN-standalone.md). Run by
`make test-standalone`, after `make app-bundle`. Step 1, SDL2 inside the
app:
  1. the app's own SDL2 (build/sdl2, from tools/build_sdl2.sh): for
     Intel and Apple Silicon, macOS 11 on, named @rpath/libSDL2.dylib,
     needing only Apple's libraries;
  2. the program (build/nesrecomp-app): both kinds of Mac, macOS 11 on,
     loading SDL2 through its rpath (beside it, or the bundle's
     Frameworks), nothing else but Apple's;
  3. the bundle: the library, SDL's headers and license, and nothing in
     it that names /opt/homebrew; the recompiler in C beside the program
     (step 3), for both kinds of Mac, and no mention of Python;
  4. building and playing a free test ROM with the bundle's program,
     with reading /opt/homebrew and /usr/local forbidden (sandbox-exec;
     first checked to really forbid it): it builds, the game passes its
     test, links only @rpath/libSDL2.dylib and finds it in lib/ beside
     itself (a copy the build made, replacing an old one left there), and
     loads that copy;
  5. the same as an Intel Mac would, under Rosetta (skipped if Rosetta
     isn't installed): the game is built for Intel and passes;
  6. a game still runs after the app that built it is gone;
  7. a newer SDL header builds the game and the runtime again;
  8. an app whose SDL headers, or whose recompiler, are missing says so,
     rather than building.
In 4. to 6., Python can't run either: the recompiling is the bundle's own.
Step 4, the app works from anywhere:
  9. the bundle carries the runtime's sources (the same as runtime/);
     nothing in the bundle names this project's folder or this Mac's
     home folder; the bundle's version is the program's;
 10. a copy of the bundle in a folder whose name has spaces, a ROM
     elsewhere, and reading this project's folder forbidden as well (first
     checked to be): it builds and plays the ROM, passing its test, with
     the copy's own runtime; the build goes to ~/Library/Application
     Support/NES RECOMP (a scratch home here) and the bundle is left as it
     was; ROM.missed is kept beside the ROM;
 11. the app moved: the game still runs, and building again is "up to
     date"; another app version (in the build's record): built again;
 12. a ROM in a folder that can't be written: it still builds and plays,
     its .missed kept in the app's folder (NAME.missed) and used by the
     next build;
 13. the runtime missing: the build says so.
Exit status 0 when all pass.
"""
import os
import re
import shutil
import subprocess
import stat
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SDL = os.path.join(ROOT, "build", "sdl2")
LIB = os.path.join(SDL, "lib", "libSDL2.dylib")
PROG = os.path.join(ROOT, "build", "nesrecomp-app")
APP = os.path.join(ROOT, "build", "nesrecomp.app")
OUT = os.path.join(ROOT, "build", "app_check", "standalone")
FREE = os.path.join(ROOT, "tests", "roms", "nes-test-roms", "instr_test-v5", "rom_singles",
                    "01-basics.nes")
SDL_VERSION = "2.32.10"
MINOS = "11.0"
# Homebrew and /usr/local out of reach, and Python can't run at all
# (step 3): no program with "python" in its path starts, and Python's
# frameworks can't be read.
DENY = ('(version 1)(allow default)'
        '(deny file-read* (subpath "/opt/homebrew") (subpath "/usr/local")'
        ' (subpath "/Library/Frameworks/Python.framework")'
        ' (subpath "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework"))'
        '(deny process-exec (regex #"python"))')
HEADLESS = "--headless --frames 600 --no-save"

fails = []


def check(name, ok, why=""):
    print("%s  %s%s" % ("ok   " if ok else "FAIL ", name, "" if ok else ": " + why))
    if not ok:
        fails.append(name)


def run(*args, **kw):
    kw.setdefault("timeout", 300)
    return subprocess.run(list(args), capture_output=True, text=True, **kw)


def archs(path):
    r = run("lipo", "-archs", path)
    return sorted(r.stdout.split()) if r.returncode == 0 else []


def minos(path, arch):
    out = run("otool", "-arch", arch, "-l", path).stdout
    m = re.findall(r"cmd LC_BUILD_VERSION.*?minos (\S+)", out, re.S)
    return m[0] if m else None


def linked(path, arch=None):
    """The libraries a Mach-O file loads (its own name left out)."""
    args = ["otool"] + (["-arch", arch] if arch else []) + ["-L", path]
    out = run(*args).stdout.splitlines()[1:]
    libs = [l.strip().split(" (")[0] for l in out if l.startswith("\t")]
    if path.endswith(".dylib") and libs:
        libs = libs[1:]                          # the first is its own id
    return libs


def rpaths(path):
    return re.findall(r"cmd LC_RPATH\s+cmdsize \d+\s+path (\S+)", run("otool", "-l", path).stdout)


def apple_only(libs):
    return all(l.startswith("/usr/lib/") or l.startswith("/System/Library/") for l in libs)


def code(path):
    return run("otool", "-tX", path).stdout


def build_play(prog, rom, bdir, sandbox=True, rosetta=False):
    cmd = [prog, "--build", rom, "--build-dir", bdir, "--then-play", "--play-args", HEADLESS]
    if rosetta:
        cmd = ["arch", "-x86_64"] + cmd
    if sandbox:
        cmd = ["sandbox-exec", "-p", DENY] + cmd
    r = run(*cmd)
    name = os.path.splitext(os.path.basename(rom))[0]
    glog = os.path.join(bdir, name + ".game.log")
    text = open(glog).read() if os.path.exists(glog) else ""
    return r, os.path.join(bdir, name), text


def last(s):
    lines = [l for l in s.strip().splitlines() if l.strip()]
    return lines[-1][:100] if lines else "(nothing)"


def scan(top, needles):
    """Files under top whose bytes hold any of needles, with the text."""
    hits = []
    for d, _, files in os.walk(top):
        for f in files:
            p = os.path.join(d, f)
            if os.path.islink(p):
                continue
            data = open(p, "rb").read()
            for n in needles:
                at = data.find(n)
                if at >= 0:
                    lo, hi = data.rfind(b"\0", 0, at) + 1, data.find(b"\0", at)
                    hits.append((os.path.relpath(p, top), data[lo:hi if hi >= 0 else len(data)][:100]))
                    break
    return hits


def listing(top):
    """Every file in a folder, with its size and time."""
    out = []
    for d, _, files in os.walk(top):
        for f in files:
            st = os.lstat(os.path.join(d, f))
            out.append((os.path.relpath(os.path.join(d, f), top), st.st_size, st.st_mtime_ns))
    return sorted(out)


def anywhere(blib):
    """Step 4: the app works from anywhere (9. to 13.)."""
    contents = os.path.join(APP, "Contents")
    # 9. what the bundle carries.
    brt = os.path.join(contents, "Resources", "runtime")
    src = sorted(f for f in os.listdir(os.path.join(ROOT, "runtime")) if f.endswith((".c", ".h", ".m")))
    have = sorted(os.listdir(brt)) if os.path.isdir(brt) else []
    same = have == src and all(open(os.path.join(brt, f), "rb").read() ==
                               open(os.path.join(ROOT, "runtime", f), "rb").read() for f in have)
    check("the bundle: the runtime's %d .c, .m and .h files" % len(src), same and "rt.h" in have
          and "record_mac.m" in have,
          "%d of %d, missing %s" % (len(have), len(src), sorted(set(src) - set(have))[:3]))
    home = os.path.expanduser("~")
    needles = [ROOT.encode(), os.path.realpath(ROOT).encode(), home.encode()]
    hits = scan(APP, needles)
    check("the bundle: nothing in it names this project's folder or %s" % home, not hits, "%s" % hits[:3])
    bprog = os.path.join(contents, "MacOS", "nesrecomp")
    ver = run(bprog, "--version").stdout.strip()
    import plistlib
    pl = plistlib.load(open(os.path.join(contents, "Info.plist"), "rb"))
    check("the bundle's version is the program's", ver and pl.get("CFBundleShortVersionString") == ver
          and pl.get("CFBundleVersion") == ver, "program %r, Info.plist %r" % (ver, pl.get("CFBundleVersion")))

    # 10. a copy of the bundle, far from the project.
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="nesrecomp check "))
    try:
        anywhere_in(tmp, blib, ver)
    finally:
        for d, dirs, _ in os.walk(tmp):
            for x in dirs:
                os.chmod(os.path.join(d, x), 0o755)
        shutil.rmtree(tmp, ignore_errors=True)


def anywhere_in(tmp, blib, ver):
    deny = DENY.replace('(deny file-read* ', '(deny file-read* (subpath "%s") ' % ROOT)
    probe = run("sandbox-exec", "-p", deny, "/bin/cat", os.path.join(ROOT, "Makefile"))
    check("the sandbox really forbids reading this project's folder too",
          probe.returncode != 0 and "not permitted" in probe.stderr, "it could read it")
    place = os.path.join(tmp, "Some Apps", "NES RECOMP.app")
    shutil.copytree(APP, place, symlinks=True)
    before = listing(place)
    prog = os.path.join(place, "Contents", "MacOS", "nesrecomp")
    home = os.path.join(tmp, "a home")
    os.makedirs(home)
    roms = os.path.join(tmp, "my roms")
    os.makedirs(roms)
    rom = os.path.join(roms, "basics test.nes")
    shutil.copy(FREE, rom)
    env = dict(os.environ, HOME=home)
    env.pop("NESRECOMP_ROOT", None)

    def go(*extra, prog=prog, sandbox=True):
        cmd = [prog, "--build", rom] + list(extra)
        if sandbox:
            cmd = ["sandbox-exec", "-p", deny] + cmd
        return run(*cmd, env=env, cwd=tmp)

    r = go("--then-play", "--play-args", HEADLESS)
    bdir = os.path.join(home, "Library", "Application Support", "NES RECOMP")
    name = "basics_test"
    glog = os.path.join(bdir, name + ".game.log")
    glog = open(glog).read() if os.path.exists(glog) else ""
    check("far from the project, without it, Homebrew or Python: builds and plays, the test passes",
          r.returncode == 0 and "played: the game ended well" in r.stdout and
          "test status at $6000: $00" in glog, last(r.stdout + r.stderr + glog))
    blog = os.path.join(bdir, name + ".log")
    blog = open(blog).read() if os.path.exists(blog) else ""
    check("the build used the copy's own runtime",
          "-I" + os.path.join(place, "Contents", "Resources", "runtime") + " " in blog
          and ROOT not in blog, last(blog))
    check("the build went to ~/Library/Application Support/NES RECOMP",
          os.path.exists(os.path.join(bdir, name)) and os.path.exists(os.path.join(bdir, name + ".stamp")),
          "%s" % (sorted(os.listdir(bdir)) if os.path.isdir(bdir) else "no such folder"))
    check("the bundle is left as it was (nothing written inside it)", listing(place) == before,
          "%s" % sorted(set(listing(place)) ^ set(before))[:3])
    check("ROM.missed is kept beside the ROM (its folder can be written)",
          os.path.exists(rom + ".missed") and not os.path.exists(os.path.join(bdir, name + ".missed")),
          "%s" % sorted(os.listdir(roms)))
    stamp = os.path.join(bdir, name + ".stamp")
    st = open(stamp).read() if os.path.exists(stamp) else ""
    check("the build's record holds the app's version", st.startswith("app %s rom " % ver), st[:40])

    # 11. the app moved. (Playing wrote ROM.missed, so build once first.)
    first = go()
    moved = os.path.join(tmp, "Elsewhere", "NES RECOMP moved.app")
    os.makedirs(os.path.dirname(moved))
    os.rename(place, moved)
    mprog = os.path.join(moved, "Contents", "MacOS", "nesrecomp")
    again = go(prog=mprog)
    check("the app moved: building again is up to date",
          first.returncode == 0 and "built: " in first.stdout and again.returncode == 0
          and "up to date" in again.stdout, last(again.stdout))
    game = os.path.join(bdir, name)
    r3 = run("sandbox-exec", "-p", deny, game, rom, *HEADLESS.split(), cwd=tmp) \
        if os.path.exists(game) else None
    check("the app moved: the game still runs and passes",
          r3 is not None and r3.returncode == 0 and "test status at $6000: $00" in r3.stdout + r3.stderr,
          last((r3.stdout + r3.stderr) if r3 else "no game"))
    go(prog=mprog)                               # the game wrote ROM.missed again
    st = open(stamp).read() if os.path.exists(stamp) else ""
    if st:
        with open(stamp, "w") as f:
            f.write(st.replace("app %s " % ver, "app 0.0-older ", 1))
    newer = go(prog=mprog)
    check("another app version: built again", newer.returncode == 0 and "up to date" not in newer.stdout
          and "stage 2/5" in newer.stdout and "built: " in newer.stdout, last(newer.stdout))

    # 12. a ROM in a folder that can't be written.
    locked = os.path.join(tmp, "locked roms")
    os.makedirs(locked)
    lrom = os.path.join(locked, "basics locked.nes")
    shutil.copy(FREE, lrom)
    os.chmod(locked, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP)
    lname = "basics_locked"
    r4 = run("sandbox-exec", "-p", deny, mprog, "--build", lrom, "--then-play", "--play-args", HEADLESS,
             env=env, cwd=tmp)
    lg = os.path.join(bdir, lname + ".game.log")
    lg = open(lg).read() if os.path.exists(lg) else ""
    check("a ROM in a folder that can't be written: it builds and plays, the test passes",
          r4.returncode == 0 and "test status at $6000: $00" in lg, last(r4.stdout + r4.stderr + lg))
    kept = os.path.join(bdir, lname + ".missed")
    check("...its .missed kept in the app's folder", os.path.exists(kept) and os.path.getsize(kept) > 0
          and sorted(os.listdir(locked)) == ["basics locked.nes"],
          "app's folder: %s, ROM's: %s" % (os.path.exists(kept), sorted(os.listdir(locked))))
    r5 = run("sandbox-exec", "-p", deny, mprog, "--build", lrom, env=env, cwd=tmp)
    l2 = os.path.join(bdir, lname + ".log")
    l2 = open(l2).read() if os.path.exists(l2) else ""
    check("...and the next build uses it", r5.returncode == 0 and "up to date" not in r5.stdout and
          " --missed " + kept in l2, last(r5.stdout + l2))

    # 13. the runtime missing.
    shutil.rmtree(os.path.join(moved, "Contents", "Resources", "runtime"))
    other = os.path.join(roms, "other.nes")
    shutil.copy(FREE, other)
    gone = run("sandbox-exec", "-p", deny, mprog, "--build", other, env=env, cwd=tmp)
    check("the runtime missing: the build says so",
          gone.returncode != 0 and "error: the app's runtime is missing" in gone.stdout, last(gone.stdout))


def main():
    for p, what in ((LIB, "make sdl2"), (PROG, "make app"), (APP, "make app-bundle"), (FREE, "the test ROM clone")):
        if not os.path.exists(p):
            sys.exit("%s is missing: %s first" % (p, what))
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)

    # 1. the library.
    a = archs(LIB)
    check("SDL2: for Intel and Apple Silicon", a == ["arm64", "x86_64"], "%s" % a)
    mins = {x: minos(LIB, x) for x in ("arm64", "x86_64")}
    check("SDL2: macOS %s and later, both halves" % MINOS, all(v == MINOS for v in mins.values()), "%s" % mins)
    ident = run("otool", "-D", LIB).stdout.splitlines()[-1:]
    check("SDL2: named @rpath/libSDL2.dylib", ident == ["@rpath/libSDL2.dylib"], "%s" % ident)
    libs = linked(LIB, "arm64") + linked(LIB, "x86_64")
    check("SDL2: needs only Apple's libraries", libs and apple_only(libs),
          "%s" % [l for l in libs if not apple_only([l])])
    vh = open(os.path.join(SDL, "include", "SDL2", "SDL_version.h")).read()
    ver = ".".join((re.search(r"#define SDL_%s\s+(\d+)" % k, vh) or re.search("()", "")).group(1)
                   for k in ("MAJOR_VERSION", "MINOR_VERSION", "PATCHLEVEL"))
    check("SDL2: the headers are version %s" % SDL_VERSION, ver == SDL_VERSION, ver)

    # 2. the program.
    a = archs(PROG)
    check("the app: for Intel and Apple Silicon", a == ["arm64", "x86_64"], "%s" % a)
    mins = {x: minos(PROG, x) for x in ("arm64", "x86_64")}
    check("the app: macOS %s and later" % MINOS, all(v == MINOS for v in mins.values()), "%s" % mins)
    libs = linked(PROG, "arm64") + linked(PROG, "x86_64")
    others = [l for l in libs if l != "@rpath/libSDL2.dylib"]
    check("the app: SDL2 through its rpath, otherwise only Apple's",
          "@rpath/libSDL2.dylib" in libs and apple_only(others), "%s" % libs)
    rp = rpaths(PROG)
    check("the app: looks for it beside itself and in the bundle's Frameworks",
          "@executable_path/sdl2/lib" in rp and "@executable_path/../Frameworks" in rp, "%s" % rp)

    # 3. the bundle.
    contents = os.path.join(APP, "Contents")
    blib = os.path.join(contents, "Frameworks", "libSDL2.dylib")
    check("the bundle: SDL2 in Frameworks (the same code as build/sdl2's)",
          os.path.exists(blib) and code(blib) == code(LIB) and len(code(LIB)) > 1000,
          "missing or different")
    binc = os.path.join(contents, "Resources", "sdl2", "include", "SDL2")
    src_h = sorted(os.listdir(os.path.join(SDL, "include", "SDL2")))
    have_h = sorted(os.listdir(binc)) if os.path.isdir(binc) else []
    same_h = have_h == src_h and all(
        open(os.path.join(binc, h), "rb").read() == open(os.path.join(SDL, "include", "SDL2", h), "rb").read()
        for h in have_h)
    check("the bundle: SDL's %d headers" % len(src_h), same_h and "SDL.h" in have_h,
          "%d of %d" % (len(have_h), len(src_h)))
    lic = os.path.join(contents, "Resources", "sdl2", "LICENSE.txt")
    check("the bundle: SDL's license",
          os.path.exists(lic) and open(lic).read() == open(os.path.join(SDL, "LICENSE.txt")).read()
          and "provided 'as-is'" in open(lic).read(), "missing or different")
    named, py = [], []
    for d, _, files in os.walk(APP):
        for f in files:
            p = os.path.join(d, f)
            data = open(p, "rb").read()
            found, at = set(), data.find(b"/opt/homebrew")
            while at >= 0:                   # the whole string around it
                lo, hi = data.rfind(b"\0", 0, at) + 1, data.find(b"\0", at)
                found.add(data[lo:hi if hi >= 0 else len(data)][:120])
                at = data.find(b"/opt/homebrew", at + 1)
            if found:
                named.append((os.path.relpath(p, APP), sorted(found)[:3]))
            # The recompiler names recomp.py, in its help and in a comment
            # of the C it writes (which must match recomp.py's); the app's
            # program shouldn't, and neither should name Python.
            if f.startswith("nesrecomp") and (b"python" in data.lower() or
                                              (f == "nesrecomp" and b"recomp.py" in data)):
                py.append(os.path.relpath(p, APP))
    check("the bundle: nothing in it names /opt/homebrew", not named, "%s" % named)
    check("the bundle's programs don't name Python (nor the app recomp.py)", not py, "%s" % py)
    brc = os.path.join(contents, "MacOS", "nesrecomp-recomp")
    rc = os.path.join(ROOT, "build", "nesrecomp-recomp")
    check("the bundle: the recompiler in C beside the program (build/nesrecomp-recomp's code)",
          os.path.exists(brc) and os.access(brc, os.X_OK) and code(brc) == code(rc)
          and len(code(rc)) > 1000, "missing or different")
    a = archs(brc) if os.path.exists(brc) else []
    mins = {x: minos(brc, x) for x in a}
    check("the recompiler: for Intel and Apple Silicon, macOS %s on" % MINOS,
          a == ["arm64", "x86_64"] and all(v == MINOS for v in mins.values()), "%s %s" % (a, mins))
    libs = linked(brc, "arm64") + linked(brc, "x86_64") if a else []
    check("the recompiler: needs only Apple's libraries", libs and apple_only(libs), "%s" % libs)
    bprog = os.path.join(contents, "MacOS", "nesrecomp")
    info = run(bprog, "--sdl-info").stdout.strip().splitlines() + ["", ""]
    check("the bundle's program finds the bundle's SDL2",
          info[0] == "sdl2 found " + os.path.realpath(blib), info[0])
    check("the bundle's program finds the bundle's recompiler",
          info[1] == "recompiler " + os.path.realpath(brc), info[1])

    # 4. build and play with Homebrew out of reach.
    probe = run("sandbox-exec", "-p", DENY, "/bin/cat", "/opt/homebrew/lib/libSDL2.dylib")
    probe2 = run("sandbox-exec", "-p", DENY, "/bin/ls", "/usr/local")
    check("the sandbox really forbids reading /opt/homebrew and /usr/local",
          probe.returncode != 0 and "not permitted" in probe.stderr and probe2.returncode != 0,
          "it could read them")
    py_probe = [run("sandbox-exec", "-p", DENY, p, "-c", "print(1)")
                for p in ("/usr/bin/python3", "/Library/Developer/CommandLineTools/usr/bin/python3")]
    check("the sandbox really stops Python from running",
          all(r.returncode != 0 and r.stdout.strip() != "1" for r in py_probe),
          "%s" % [(r.returncode, r.stdout.strip()) for r in py_probe])
    roms = os.path.join(OUT, "roms")
    os.makedirs(roms)
    rom = os.path.join(roms, "basics.nes")
    shutil.copy(FREE, rom)
    bdir = os.path.join(OUT, "builds")
    # An old copy of the library left there (another size, an old time),
    # as after an update of the app: the build must replace it.
    os.makedirs(os.path.join(bdir, "lib"))
    stale = os.path.join(bdir, "lib", "libSDL2.dylib")
    with open(stale, "wb") as f:
        f.write((open(blib, "rb").read() if os.path.exists(blib) else b"") + b"an old copy")
    os.utime(stale, (1600000000, 1600000000))
    r, game, glog = build_play(bprog, rom, bdir)
    check("without Homebrew: it builds and plays a free test ROM",
          r.returncode == 0 and "played: the game ended well" in r.stdout, last(r.stdout + r.stderr))
    check("without Homebrew: the game passes its test", "test status at $6000: $00" in glog,
          last(glog))
    blog = open(os.path.join(bdir, "basics.log")).read() if os.path.exists(os.path.join(bdir, "basics.log")) else ""
    check("without Python: the bundle's recompiler did the recompiling",
          "$ " + os.path.realpath(brc) + " " + rom + " -o " in blog and "python" not in blog.lower(),
          last(blog))
    glibs = linked(game) if os.path.exists(game) else []
    check("the game: SDL2 through its rpath, otherwise only Apple's",
          "@rpath/libSDL2.dylib" in glibs and apple_only([l for l in glibs if l != "@rpath/libSDL2.dylib"]),
          "%s" % glibs)
    grp = rpaths(game) if os.path.exists(game) else []
    copy = os.path.join(bdir, "lib", "libSDL2.dylib")
    check("the game: finds it in lib/ beside itself, a copy of the app's (an old one replaced)",
          grp == ["@executable_path/lib"] and os.path.exists(copy)
          and os.path.exists(blib) and open(copy, "rb").read() == open(blib, "rb").read(),
          "rpath %s" % grp)
    loaded = []
    if os.path.exists(game):
        r2 = subprocess.run([game, rom] + HEADLESS.split(), capture_output=True, text=True,
                            env=dict(os.environ, DYLD_PRINT_LIBRARIES="1"), timeout=120)
        loaded = [l.split()[-1] for l in r2.stderr.splitlines() if "libSDL2" in l and l.startswith("dyld")]
    check("the game loads that copy", loaded == [os.path.realpath(copy)], "%s" % loaded)

    # 5. as on an Intel Mac.
    if run("arch", "-x86_64", "/usr/bin/true").returncode != 0:
        print("skip  as an Intel Mac: Rosetta isn't installed")
    else:
        os.remove(rom + ".missed") if os.path.exists(rom + ".missed") else None
        xdir = os.path.join(OUT, "builds_intel")
        r, game_x, glog = build_play(bprog, rom, xdir, rosetta=True)
        check("as an Intel Mac (Rosetta), without Homebrew: builds, plays, passes",
              r.returncode == 0 and "test status at $6000: $00" in glog, last(r.stdout + r.stderr + glog))
        check("as an Intel Mac: the game is an Intel program",
              os.path.exists(game_x) and archs(game_x) == ["x86_64"], "%s" % (archs(game_x) if os.path.exists(game_x) else "none"))

    # 6. a game outlives the app that built it: a copy of the app (its
    # name with spaces) builds it, then the copy is removed.
    moved = os.path.join(OUT, "NES RECOMP copy.app")
    shutil.copytree(APP, moved, symlinks=True)
    mprog = os.path.join(moved, "Contents", "MacOS", "nesrecomp")
    mdir = os.path.join(OUT, "builds_moved")
    r, game_m, _ = build_play(mprog, rom, mdir)
    shutil.rmtree(moved)
    r3 = run(game_m, rom, *HEADLESS.split()) if os.path.exists(game_m) else None
    check("a game still runs after the app that built it is gone",
          r.returncode == 0 and r3 is not None and r3.returncode == 0
          and "test status at $6000: $00" in r3.stdout + r3.stderr,
          last((r3.stdout + r3.stderr) if r3 else r.stdout))

    # 7. and 8., with another copy of the app.
    shutil.copytree(APP, moved, symlinks=True)
    sdir = os.path.join(OUT, "builds_header")
    first = run(mprog, "--build", rom, "--build-dir", sdir)
    again = run(mprog, "--build", rom, "--build-dir", sdir)
    vh = os.path.join(moved, "Contents", "Resources", "sdl2", "include", "SDL2", "SDL_version.h")
    later = time.time() + 10                     # newer than the runtime just compiled
    if os.path.exists(vh):
        os.utime(vh, (later, later))
    newer = run(mprog, "--build", rom, "--build-dir", sdir)
    m = re.search(r"runtime: (\d+) of (\d+) file", newer.stdout)
    check("a newer SDL header: the game and every runtime file built again",
          first.returncode == 0 and "up to date" in again.stdout and "up to date" not in newer.stdout
          and newer.returncode == 0 and m and m.group(1) == m.group(2),
          last(newer.stdout))
    shutil.rmtree(os.path.join(moved, "Contents", "Resources", "sdl2", "include"), ignore_errors=True)
    gone = run(mprog, "--build", rom, "--build-dir", os.path.join(OUT, "builds_noheaders"))
    check("SDL's headers missing: the build says so",
          gone.returncode != 0 and "error: the app's SDL2 is missing" in gone.stdout, last(gone.stdout))
    mrc = os.path.join(moved, "Contents", "MacOS", "nesrecomp-recomp")
    if os.path.exists(mrc):
        os.remove(mrc)
    shutil.copytree(os.path.join(APP, "Contents", "Resources", "sdl2", "include"),
                    os.path.join(moved, "Contents", "Resources", "sdl2", "include"))
    gone = run(mprog, "--build", rom, "--build-dir", os.path.join(OUT, "builds_norecomp"))
    check("the recompiler missing: the build says so",
          gone.returncode != 0 and "error: the app's recompiler is missing" in gone.stdout,
          last(gone.stdout))
    shutil.rmtree(moved)

    anywhere(blib)

    print("\n%d check(s) failed" % len(fails) if fails else "\nall checks pass")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
