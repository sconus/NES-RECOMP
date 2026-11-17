#!/usr/bin/env python3
"""Put NES RECOMP for Windows together in a folder (PLAN-windows.md step
4): what the app needs beside its program, as app/build.c looks for it.

    python3 tools/make_windows_app.py --cc "ZIG cc [-target x86_64-windows-gnu]"
        --sdl2 SDL2-2.32.10/x86_64-w64-mingw32 --zlib-src zlib-1.3.1
        --recomp nesrecomp-recomp.exe --out build/windows/app

makes OUT/:
    nesrecomp-app.exe       the app (a Windows program: no console window)
    SDL2.dll                SDL's, for the app and copied beside each game
    nesrecomp-recomp.exe    the recompiler (built by `make windows`)
    runtime/                the runtime's sources (its .c and .h)
    sdl2/include/SDL2/      SDL's headers, and sdl2/lib/libSDL2.dll.a,
                            to build games against
    zlib/include/, zlib/lib/libz.a
                            zlib (Windows has none), built here
On the Mac, `make windows-app` runs it with Zig building for Windows; on
GitHub's Windows machine, the workflow runs it with Zig there. Step 5
adds Zig itself (zig/ in OUT); until then, a build uses a Zig on PATH.
"""
import argparse
import glob
import os
import shlex
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP_SOURCES = ["app.c", "build.c", "play.c", "hood.c", "code.c", "os_win.c", "support_win.c"]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit("failed: %s\n%s%s" % (" ".join(cmd), r.stdout, r.stderr))


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--cc", required=True)
    a.add_argument("--sdl2", required=True)
    a.add_argument("--zlib-src", required=True)
    a.add_argument("--recomp", required=True)
    a.add_argument("--out", required=True)
    o = a.parse_args()
    cc = shlex.split(o.cc, posix=os.name != "nt")
    ar = [cc[0], "ar"]                          # Zig's own: `zig ar`
    out = os.path.abspath(o.out)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)

    # zlib, as a library to link games and the app with.
    zobj = os.path.join(os.path.dirname(out), "app-zlib")
    shutil.rmtree(zobj, ignore_errors=True)
    os.makedirs(zobj)
    objs = []
    for src in sorted(glob.glob(os.path.join(o.zlib_src, "*.c"))):
        obj = os.path.join(zobj, os.path.basename(src)[:-2] + ".o")
        run(cc + ["-O2", "-c", src, "-o", obj])
        objs.append(obj)
    os.makedirs(os.path.join(out, "zlib", "include"))
    os.makedirs(os.path.join(out, "zlib", "lib"))
    run(ar + ["rcs", os.path.join(out, "zlib", "lib", "libz.a")] + objs)
    for h in ("zlib.h", "zconf.h"):
        shutil.copy2(os.path.join(o.zlib_src, h), os.path.join(out, "zlib", "include"))

    # SDL: its DLL beside the app, its headers and import library.
    shutil.copytree(os.path.join(o.sdl2, "include", "SDL2"), os.path.join(out, "sdl2", "include", "SDL2"))
    os.makedirs(os.path.join(out, "sdl2", "lib"))
    shutil.copy2(os.path.join(o.sdl2, "lib", "libSDL2.dll.a"), os.path.join(out, "sdl2", "lib"))
    shutil.copy2(os.path.join(o.sdl2, "bin", "SDL2.dll"), out)

    # The runtime's sources (the Mac's Objective-C left out) and the recompiler.
    os.makedirs(os.path.join(out, "runtime"))
    for f in sorted(os.listdir(os.path.join(ROOT, "runtime"))):
        if f.endswith((".c", ".h")):
            shutil.copy2(os.path.join(ROOT, "runtime", f), os.path.join(out, "runtime"))
    shutil.copy2(o.recomp, os.path.join(out, "nesrecomp-recomp.exe"))

    # The app: a Windows program (no console window when opened).
    inc = ["-I" + os.path.join(out, "sdl2", "include", "SDL2"), "-I" + os.path.join(out, "zlib", "include"),
           "-D_THREAD_SAFE", "-I" + os.path.join(ROOT, "app")]
    run(cc + ["-O1", "-Wall", "-Werror"] + inc + ["-o", os.path.join(out, "nesrecomp-app.exe")] +
        [os.path.join(ROOT, "app", f) for f in APP_SOURCES] +
        [os.path.join(out, "sdl2", "lib", "libSDL2.dll.a"), os.path.join(out, "zlib", "lib", "libz.a"),
         "-lole32", "-lcomdlg32", "-lshell32", "-Wl,--subsystem,windows"])
    print("made", out)


if __name__ == "__main__":
    main()
