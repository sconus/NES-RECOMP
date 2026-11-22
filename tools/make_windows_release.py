#!/usr/bin/env python3
"""Make build/NES-RECOMP-<version>-windows.zip, NES RECOMP for Windows to
give away (PLAN-windows.md step 6). Run by `make release-windows`, from
the app's folder as tools/make_windows_app.py made it with --zig.

    python3 tools/make_windows_release.py --app build/windows/release-app

The zip holds one folder, "NES RECOMP <version>":

    NES RECOMP.exe        the app (nesrecomp-app.exe), with its icon,
                          version and Windows's UTF-8 setting
    SDL2.dll              SDL's, for the app and copied beside each game
    nesrecomp-recomp.exe  the recompiler
    runtime/ sdl2/ zlib/  what a game is built from
    zig/                  the app's own compiler, with the prebuilt C
                          library (PLAN-windows.md step 5)
    READ ME FIRST.txt     what it is, what it needs, Windows's first-time
                          warning (SmartScreen), where things go, the keys,
                          the support page (app/support.h's link)
    LICENSE.txt           the MIT License (this project's LICENSE)
    licenses/             what it carries: SDL's (zlib License), zlib's,
                          Zig's (MIT), and what Zig carries: LLVM's
                          (Apache 2.0 with LLVM Exceptions, for its
                          compiler and clang's headers) and MinGW-w64's
                          (its C library's headers and the prebuilt
                          library made from it)

The version is APP_VERSION in app/build.h (the app's --version). Nothing
in it may name the folders of the machine that made it (its home, this
project's folder, its temporary folder): the zip isn't written if a file
does.
"""
import argparse
import os
import re
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# licenses/NAME: where it comes from, from --app, --zig, --sdl2-license,
# --zlib-src.
LICENSES = [
    ("SDL LICENSE.txt", "sdl2"),
    ("zlib LICENSE.txt", "zlib"),
    ("Zig LICENSE.txt", "zig"),
    ("LLVM LICENSE.txt", "llvm"),
    ("MinGW-w64 LICENSE.txt", "mingw"),
]

READ_ME = """NES RECOMP {version} for Windows
For educational purposes only. By Serge and Claude.
Free software under the MIT License (LICENSE.txt).

WHAT IT IS
Drop an NES game file (.nes, .nsf or .fds) on NES RECOMP's window. It
recompiles the game's 6502 machine code into C, builds it into a program
on your PC, and plays it. After each game, its "under the hood" screen
shows how much of the game became C, and C there shows the original
6502 instructions next to the C they became.
No games come with it: use your own files.

WHAT IT NEEDS
- Windows 10 (version 1903 or later) or Windows 11, 64-bit.
- Nothing else: its C compiler (Zig) comes with it, in the zig folder.

OPENING IT THE FIRST TIME
1. Unzip it first: right-click the zip, "Extract All...", and choose
   where (Documents, say). It doesn't run from inside the zip.
2. Open the folder and double-click "NES RECOMP.exe".
3. NES RECOMP isn't signed by a registered developer, so the first
   time, Windows SmartScreen says "Windows protected your PC". Click
   "More info", then "Run anyway".
After that, it opens with a double-click like any program. Keep the
folder together: NES RECOMP uses the files beside it.

USING IT
- Drop a game on the window, or click the TV to choose one. The first
  build takes a few seconds; after that, a game starts at once.
- In a game: arrow keys, X (A), Z (B), Enter (Start), Right Shift
  (Select); M mutes, R resets, V starts and stops a recording, P saves
  a picture. Esc opens the pause menu: save and load, the volume, the
  window's size, quit. Game controllers work too (hold Select and Start
  for the menu; the shoulder buttons rewind and fast-forward).
- On the drop screen: I shows who made it (and D there opens the
  support page), H shows "under the hood" for the last game; there, C
  shows its code.
- Games get faster as you play them: the places the game ran in the
  interpreter are written to <game>.missed beside the game file, and
  the next build translates them too.

WHERE THINGS GO
- The games it builds, their logs and its settings:
  %LOCALAPPDATA%\\NES RECOMP (in your user folder, AppData\\Local;
  safe to delete; games are just built again).
- Recordings (MP4) and pictures: Videos\\NES RECOMP in your user folder.
- <game>.missed and <game>.sav (battery saves): beside the game file,
  or in the app's folder if that one can't be written.

SUPPORTING IT
NES RECOMP is free. If you'd like to support it, and the Polygon
Legends channel it comes from:
  {support}
(The same link is in the app: "Support NES RECOMP..." in its window's
menu, behind the icon at its top left or Alt+Space, and D on its About
screen.)

LICENSES
LICENSE.txt: NES RECOMP, MIT License.
licenses\\SDL LICENSE.txt: SDL {sdl}, which NES RECOMP carries, zlib License.
licenses\\zlib LICENSE.txt: zlib {zlib}, which games are built with, zlib License.
licenses\\Zig LICENSE.txt: Zig {zig}, the C compiler in the zig folder, MIT License.
licenses\\LLVM LICENSE.txt: LLVM, which Zig is built on (its compiler and
  clang's headers), Apache License 2.0 with LLVM Exceptions.
licenses\\MinGW-w64 LICENSE.txt: MinGW-w64, the C library's headers and the
  prebuilt library in zig\\prebuilt, made from it (its own notices inside).
"""


def app_version():
    h = open(os.path.join(ROOT, "app", "build.h")).read()
    return re.search(r'#define APP_VERSION "([^"]+)"', h).group(1)


def support_url():
    s = open(os.path.join(ROOT, "app", "support.h")).read()
    return re.search(r'#define SUPPORT_URL "([^"]+)"', s).group(1)


def machine_paths():
    """This machine's folders that a file mustn't name, as bytes (UTF-8
    and UTF-16, with either slash)."""
    dirs = {os.path.expanduser("~"), ROOT, tempfile.gettempdir(), os.path.realpath(tempfile.gettempdir())}
    if sys.platform == "darwin":
        dirs.add("/var/folders/")
    pats = set()
    for d in dirs:
        if len(d) < 6:
            continue
        for v in {d, d.replace("\\", "/"), d.replace("/", "\\"), d.lower(), d.lower().replace("\\", "/")}:
            pats.add(v.encode())
            pats.add(v.encode("utf-16-le"))
    return sorted(pats)


def naming_machine(files):
    """(file, path found) for each file that names this machine's folders."""
    pats = machine_paths()
    found = []
    for rel, path in files:
        data = open(path, "rb").read()
        for p in pats:
            if p in data:
                found.append((rel, p.decode("utf-16-le") if b"\x00" in p else p.decode()))
                break
    return found


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--app", required=True, help="the app's folder (make_windows_app.py --zig)")
    a.add_argument("--zig", required=True, help="Zig for Windows, unpacked (its licenses)")
    a.add_argument("--sdl2-license", required=True, help="SDL's LICENSE.txt")
    a.add_argument("--zlib-src", required=True, help="zlib's source (its LICENSE)")
    a.add_argument("--out", help="the zip (default build/NES-RECOMP-VERSION-windows.zip)")
    o = a.parse_args()
    version = app_version()
    name = "NES RECOMP %s" % version
    out = o.out or os.path.join(ROOT, "build", "NES-RECOMP-%s-windows.zip" % version)
    if not os.path.exists(os.path.join(o.app, "zig", "link.txt")):
        sys.exit("%s has no zig\\link.txt: make it with make_windows_app.py --zig" % o.app)

    # What goes in: the app's folder (its program renamed), then the text.
    files = []                                  # (path in the folder, file on disk)
    for d, dirs, fs in os.walk(o.app):
        dirs.sort()
        for f in sorted(fs):
            path = os.path.join(d, f)
            rel = os.path.relpath(path, o.app).replace(os.sep, "/")
            if rel == "nesrecomp-app.exe":
                rel = "NES RECOMP.exe"
            files.append((rel, path))
    src = {"sdl2": o.sdl2_license, "zlib": os.path.join(o.zlib_src, "LICENSE"),
           "zig": os.path.join(o.zig, "LICENSE"),
           "llvm": os.path.join(o.zig, "lib", "libcxx", "LICENSE.TXT"),
           "mingw": os.path.join(o.zig, "lib", "libc", "mingw", "COPYING")}
    texts = {"LICENSE.txt": open(os.path.join(ROOT, "LICENSE"), "rb").read()}
    for lname, key in LICENSES:
        texts["licenses/" + lname] = open(src[key], "rb").read()
    vh = open(os.path.join(o.app, "sdl2", "include", "SDL2", "SDL_version.h")).read()
    sdl = ".".join(re.search(r"#define SDL_%s\s+(\d+)" % k, vh).group(1)
                   for k in ("MAJOR_VERSION", "MINOR_VERSION", "PATCHLEVEL"))
    zv = re.search(r'#define ZLIB_VERSION "([^"]+)"', open(os.path.join(o.app, "zlib", "include", "zlib.h")).read())
    zig_v = re.search(r"zig-x86_64-windows-([0-9.]+)", os.path.basename(os.path.abspath(o.zig)))
    texts["READ ME FIRST.txt"] = READ_ME.format(
        version=version, support=support_url(), sdl=sdl, zlib=zv.group(1),
        zig=zig_v.group(1) if zig_v else "").replace("\n", "\r\n").encode()

    bad = naming_machine(files)
    if bad:
        sys.exit("these name this machine's folders, so the zip isn't written:\n" +
                 "\n".join("  %s: %s" % b for b in bad))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, path in files:
            z.write(path, name + "/" + rel)
        for rel in sorted(texts):
            z.writestr(zipfile.ZipInfo(name + "/" + rel, date_time=(2026, 1, 1, 0, 0, 0)),
                       texts[rel], zipfile.ZIP_DEFLATED)
    os.replace(tmp, out)
    print("wrote %s (%.1f MB)" % (out, os.path.getsize(out) / 1e6))


if __name__ == "__main__":
    main()
