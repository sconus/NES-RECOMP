#!/usr/bin/env python3
"""Check the release (PLAN-standalone.md step 9). Run by `make
test-release`, after `make release`.
  1. the zip, build/NES-RECOMP-<version>-mac.zip (the version the app's own):
     one folder, "NES RECOMP <version>", holding the app, READ ME
     FIRST.txt, LICENSE.txt and SDL LICENSE.txt and nothing else (no
     __MACOSX folder of this Mac's file attributes); the
     app in it the same, file for file, as build/nesrecomp.app; the
     licenses the project's and SDL's;
  2. the read-me: the version, what it needs (macOS 11, Apple's C
     compiler and `xcode-select --install`), how to open it the first
     time (Open Anyway on macOS 15, Control-click Open before), where
     things go, the licenses;
  3. as a download: the zip copied to a scratch "Downloads" folder and
     marked as a browser marks a download (com.apple.quarantine),
     unzipped with ditto as the Finder does, the app quarantined as the
     Finder leaves it: its signature still whole (codesign --verify
     --deep --strict), and Gatekeeper (spctl --assess) rejects it, as it
     does any app that isn't notarized, which is what the read-me's
     first-time steps are for;
  4. once allowed (the quarantine taken off, as Open Anyway does): step
     4's checks from there (tests/check_standalone.py's "anywhere"),
     the bundle far from this project, with this project, Homebrew and
     Python unreadable, building and playing a free test ROM.
Nothing is opened as an app here, so no window or macOS message shows.
Exit status 0 when all pass.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP = os.path.join(ROOT, "build", "nesrecomp.app")
sys.path.insert(0, HERE)
import check_standalone as standalone  # noqa: E402

fails = []


def check(name, ok, why=""):
    print("%s  %s%s" % ("ok   " if ok else "FAIL ", name, "" if ok else ": " + why))
    if not ok:
        fails.append(name)


def run(*args, **kw):
    kw.setdefault("timeout", 300)
    return subprocess.run(list(args), capture_output=True, text=True, **kw)


def files(top):
    """{relative path: (permissions, bytes), or "->target" for a link} of
    a folder."""
    out = {}
    for d, dirs, fs in os.walk(top):
        for f in fs + [x for x in dirs if os.path.islink(os.path.join(d, x))]:
            p = os.path.join(d, f)
            rel = os.path.relpath(p, top)
            out[rel] = ("->" + os.readlink(p)) if os.path.islink(p) else (
                oct(os.stat(p).st_mode & 0o777), open(p, "rb").read())
    return out


def main():
    prog = os.path.join(APP, "Contents", "MacOS", "nesrecomp")
    if not os.path.exists(prog):
        sys.exit("build/nesrecomp.app is missing: make app-bundle first")
    version = run(prog, "--version").stdout.strip()
    zpath = os.path.join(ROOT, "build", "NES-RECOMP-%s-mac.zip" % version)
    if not os.path.exists(zpath):
        sys.exit("%s is missing: make release first" % zpath)
    top = "NES RECOMP %s/" % version

    # 1. what's in it.
    names = zipfile.ZipFile(zpath).namelist()
    tops = sorted({n[len(top):].split("/")[0] for n in names if n.startswith(top)} - {""})
    check("the zip: one folder, %r, with the app, the read-me and the two licenses" % top[:-1],
          all(n.startswith(top) for n in names) and
          tops == ["LICENSE.txt", "NES RECOMP.app", "READ ME FIRST.txt", "SDL LICENSE.txt"],
          "%s" % (tops or names[:5]))
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="nesrecomp release "))
    try:
        downloads = os.path.join(tmp, "Downloads here")
        os.makedirs(downloads)
        dz = os.path.join(downloads, os.path.basename(zpath))
        shutil.copyfile(zpath, dz)
        # 3. marked as a browser marks a download, unzipped as the Finder does.
        mark = "0083;%08x;Safari;" % int(time.time())
        run("xattr", "-w", "com.apple.quarantine", mark, dz)
        r = run("ditto", "-x", "-k", dz, downloads)
        folder = os.path.join(downloads, top[:-1])
        app = os.path.join(folder, "NES RECOMP.app")
        check("unzipped with ditto, as the Finder does", r.returncode == 0 and os.path.isdir(app),
              r.stderr.strip())
        same = os.path.isdir(app) and files(app) == files(APP)
        check("the app in it: build/nesrecomp.app, file for file, with their permissions (links and "
          "signature too)", same,
              "differs" if os.path.isdir(app) else "missing")

        def text(name):
            p = os.path.join(folder, name)
            return open(p, encoding="utf-8").read() if os.path.exists(p) else ""
        check("LICENSE.txt: the project's MIT License",
              text("LICENSE.txt") == open(os.path.join(ROOT, "LICENSE")).read()
              and text("LICENSE.txt").startswith("MIT License"), "differs")
        sdl_lic = os.path.join(APP, "Contents", "Resources", "sdl2", "LICENSE.txt")
        check("SDL LICENSE.txt: SDL's zlib license, as the app carries it",
              text("SDL LICENSE.txt") == open(sdl_lic).read() and "provided 'as-is'" in text("SDL LICENSE.txt"),
              "differs")
        # 2. the read-me.
        rm = text("READ ME FIRST.txt")
        wants = ["NES RECOMP %s" % version, "macOS 11", "xcode-select --install", "Open Anyway",
                 "Privacy & Security", "Control-click", "Application Support/NES RECOMP",
                 "Movies/NES RECOMP", "MIT License", "SDL %s" % standalone.SDL_VERSION,
                 "For educational purposes only", "No games come with it",
                 "SUPPORTING IT", "https://ko-fi.com/polygonlegends", "Esc opens the pause menu",
                 "CONTROLLERS page", "PADS", "pair an Xbox", "The shelf under the TV",
                 "Delete takes a game off the shelf"]
        missing = [w for w in wants if w not in rm]
        check("READ ME FIRST: the version, what it needs, opening it the first time, where things go, "
              "the licenses", not missing, "missing %s" % missing)
        long_lines = [l for l in rm.splitlines() if len(l) > 72]
        check("READ ME FIRST: plain text, lines of 72 or fewer", rm and not long_lines,
              "%d longer" % len(long_lines))
        # The app quarantined, as the Finder leaves what it unzips from a
        # download (ditto may already have; then it's set as the Finder
        # would).
        q = run("xattr", "-p", "com.apple.quarantine", app)
        if q.returncode:
            run("xattr", "-w", "com.apple.quarantine", mark, app)
            q = run("xattr", "-p", "com.apple.quarantine", app)
        check("as a download: the app quarantined", q.returncode == 0 and q.stdout.strip(), q.stderr.strip())
        v = run("codesign", "--verify", "--deep", "--strict", "-v", app)
        check("as a download: its signature whole (codesign --verify --deep --strict)",
              v.returncode == 0 and "valid on disk" in v.stderr and "Designated Requirement" in v.stderr,
              v.stderr.strip()[-120:])
        g = run("spctl", "--assess", "--type", "execute", "-vv", app)
        check("as a download: Gatekeeper rejects it until it's allowed (not notarized), as the read-me "
              "says", g.returncode != 0 and "rejected" in g.stderr, "exit %d: %s" % (g.returncode, g.stderr.strip()))
        # 4. once allowed: step 4's checks, from there.
        run("xattr", "-dr", "com.apple.quarantine", app)
        q = run("xattr", "-p", "com.apple.quarantine", os.path.join(app, "Contents", "MacOS", "nesrecomp"))
        check("allowed (the quarantine off, as Open Anyway does)", q.returncode != 0, q.stdout.strip())
        print("      step 4's checks, on the app from the zip:")
        standalone.APP = app
        before = len(standalone.fails)
        standalone.anywhere(None)
        n = len(standalone.fails) - before
        check("once allowed, the app from the zip passes step 4's checks", n == 0,
              "%d failed: %s" % (n, standalone.fails[before:]))
    finally:
        for d, dirs, _ in os.walk(tmp):
            for x in dirs:
                try:
                    os.chmod(os.path.join(d, x), 0o755)
                except OSError:
                    pass
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d check(s) failed" % len(fails) if fails else "\nall checks pass")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
