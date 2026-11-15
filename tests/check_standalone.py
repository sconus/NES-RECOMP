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
     it that names /opt/homebrew;
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
  8. an app whose SDL headers are missing says so, rather than building.
Exit status 0 when all pass.
"""
import os
import re
import shutil
import subprocess
import sys
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
DENY = ('(version 1)(allow default)'
        '(deny file-read* (subpath "/opt/homebrew") (subpath "/usr/local"))')
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
    # Until step 3, the program puts Homebrew's bin on PATH, to find
    # python3 for recomp.py: those two strings, and nothing else.
    allowed = {b"/opt/homebrew/bin:/usr/local/bin:%s", b"/opt/homebrew/bin"}
    named = []
    for d, _, files in os.walk(APP):
        for f in files:
            p = os.path.join(d, f)
            found = set(re.findall(rb"[^\0]*/opt/homebrew[^\0]*", open(p, "rb").read()))
            if found - allowed:
                named.append((os.path.relpath(p, APP), sorted(found - allowed)[:3]))
    check("the bundle: nothing in it names /opt/homebrew (but PATH, for python3)", not named,
          "%s" % named)
    bprog = os.path.join(contents, "MacOS", "nesrecomp")
    info = run(bprog, "--sdl-info").stdout.strip()
    check("the bundle's program finds the bundle's SDL2",
          info == "sdl2 found " + os.path.realpath(blib), info)

    # 4. build and play with Homebrew out of reach.
    probe = run("sandbox-exec", "-p", DENY, "/bin/cat", "/opt/homebrew/lib/libSDL2.dylib")
    probe2 = run("sandbox-exec", "-p", DENY, "/bin/ls", "/usr/local")
    check("the sandbox really forbids reading /opt/homebrew and /usr/local",
          probe.returncode != 0 and "not permitted" in probe.stderr and probe2.returncode != 0,
          "it could read them")
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
    shutil.rmtree(moved)

    print("\n%d check(s) failed" % len(fails) if fails else "\nall checks pass")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
