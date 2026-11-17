#!/usr/bin/env python3
"""Put NES RECOMP for Windows together in a folder (PLAN-windows.md step
4): what the app needs beside its program, as app/build.c looks for it.

    python3 tools/make_windows_app.py --cc "ZIG cc [-target x86_64-windows-gnu]"
        --sdl2 SDL2-2.32.10/x86_64-w64-mingw32 --zlib-src zlib-1.3.1
        --recomp nesrecomp-recomp.exe --out build/windows/app
        [--zig zig-x86_64-windows-0.17.1]

makes OUT/:
    nesrecomp-app.exe       the app (a Windows program: no console window)
    SDL2.dll                SDL's, for the app and copied beside each game
    nesrecomp-recomp.exe    the recompiler (built by `make windows`)
    runtime/                the runtime's sources (its .c and .h)
    sdl2/include/SDL2/      SDL's headers, and sdl2/lib/libSDL2.dll.a,
                            to build games against
    zlib/include/, zlib/lib/libz.a
                            zlib (Windows has none), built here
    zig/                    the app's own compiler (PLAN-windows.md step
                            5), from --zig (Zig for Windows, unpacked):
                            zig.exe and LICENSE, and of lib/ only what
                            compiling needs (ZIG_PARTS: the C headers);
        prebuilt/           the C library a link needs (the start-up
                            code, MinGW's and Zig's libraries, Windows's
                            import libraries), made here by linking a
                            tiny program as a game is linked;
        link.txt            that link's command, for app/build.c.
Zig would make the C library on a PC's first build (a minute or so) and
keep it in its cache, but a cache made elsewhere is never used (Zig
records where its files are on the disk), so the library itself is
shipped and the app links with `zig lld-link` against it.

On the Mac, `make windows-app` runs it with Zig building for Windows; on
GitHub's Windows machine, the workflow runs it with Zig there. Without
--zig there's no zig/, and a build says the app's compiler is missing.
"""
import argparse
import glob
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP_SOURCES = ["app.c", "build.c", "play.c", "hood.c", "code.c", "os_win.c", "support_win.c"]
TARGET = ["-target", "x86_64-windows-gnu"]      # any 64-bit PC, not this one's processor
# Of Zig's lib/, what `zig cc -c` needs for Windows: clang's headers, the
# C library's (MinGW's), and std/std.zig, by which Zig knows its lib/.
ZIG_PARTS = ["include", "libc/include/any-windows-any", "std/std.zig"]
# Linked as app/build.c links a game (beside its objects, SDL's import
# library and zlib's): the Windows libraries it names.
LINK_LIBS = ["-lole32"]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit("failed: %s\n%s%s" % (" ".join(cmd), r.stdout, r.stderr))


def tree_size(path):
    return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(path) for f in fs)


def prepare_link(zig_cc, out, zdir):
    """Link a tiny program as a game is linked, with Zig (the full one,
    zig_cc), and keep what it linked against from Zig's cache in
    zdir/prebuilt, its command in zdir/link.txt."""
    # In a folder of its own, with short names relative to it, so Zig's
    # -v line (split at spaces) has no path with a space.
    work = tempfile.mkdtemp(prefix="nesrecomp-link-")
    cache, src, obj, exe, sdl2, zlib = "cache", "tiny.c", "tiny.o", "tiny.exe", "libSDL2.dll.a", "libz.a"
    os.makedirs(os.path.join(work, cache))
    with open(os.path.join(work, src), "w") as f:
        f.write("int main(void) { return 0; }\n")
    shutil.copy2(os.path.join(out, "sdl2", "lib", sdl2), work)
    shutil.copy2(os.path.join(out, "zlib", "lib", zlib), work)
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=cache, ZIG_LOCAL_CACHE_DIR=cache)
    for cmd in (zig_cc + TARGET + ["-O1", "-c", "-o", obj, src],
                zig_cc + TARGET + ["-o", exe, obj, sdl2, zlib] + LINK_LIBS + ["-v"]):
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=work)
        if r.returncode:
            sys.exit("failed: %s\n%s%s" % (" ".join(cmd), r.stdout, r.stderr))
    line = [l for l in r.stderr.splitlines() if l.startswith("lld-link ")]
    if len(line) != 1:
        sys.exit("no lld-link line in Zig's -v:\n" + r.stderr)
    same = lambda a, b: os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(os.path.join(work, b)))
    cache = os.path.join(work, cache)
    pre = os.path.join(zdir, "prebuilt")
    os.makedirs(pre)
    args, objects = [], False
    for a in line[0].split(" ")[1:]:
        p = os.path.join(work, a)
        if a in ("-DEBUG",) or a.startswith(("-PDB:", "-PDBALTPATH:", "-IMPLIB:")):
            continue                            # no debug database, no import library
        elif a.startswith("-OUT:"):
            args.append("-OUT:{out}")
        elif same(p, obj):
            args.append("{objects}")
            objects = True
        elif same(p, sdl2):
            args.append("{sdl2}")
        elif same(p, zlib):
            args.append("{zlib}")
        elif os.path.isfile(p) and os.path.abspath(p).startswith(os.path.abspath(cache) + os.sep):
            name = os.path.basename(p)
            if os.path.exists(os.path.join(pre, name)):
                sys.exit("two of Zig's files named " + name)
            shutil.copy2(p, os.path.join(pre, name))
            args.append("{zig}/prebuilt/" + name)
        elif os.path.exists(p) or "/" in a or "\\" in a:
            sys.exit("a path in Zig's link line that isn't known: " + a)
        else:
            args.append(a)
    if not objects or not any(a.startswith("-OUT:") for a in args):
        sys.exit("Zig's link line hasn't the object or the output:\n" + line[0])
    with open(os.path.join(zdir, "link.txt"), "w", newline="\n") as f:
        f.write("\n".join(args) + "\n")
    shutil.rmtree(work, ignore_errors=True)


def add_zig(zig, zig_cc, out):
    """OUT/zig: Zig's program, its license, the parts of lib/ compiling
    needs, and the prebuilt C library with its link command."""
    zdir = os.path.join(out, "zig")
    os.makedirs(zdir)
    for f in ("zig.exe", "LICENSE"):
        shutil.copy2(os.path.join(zig, f), zdir)
    for part in ZIG_PARTS:
        src, dst = os.path.join(zig, "lib", part), os.path.join(zdir, "lib", part)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
    prepare_link(zig_cc, out, zdir)
    mb = lambda n: "%.1f MB" % (n / 1e6)
    print("zig/: %s (zig.exe %s, lib/ %s, prebuilt/ %s)" % (
        mb(tree_size(zdir)), mb(os.path.getsize(os.path.join(zdir, "zig.exe"))),
        mb(tree_size(os.path.join(zdir, "lib"))), mb(tree_size(os.path.join(zdir, "prebuilt")))))


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--cc", required=True)
    a.add_argument("--sdl2", required=True)
    a.add_argument("--zlib-src", required=True)
    a.add_argument("--recomp", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--zig", help="Zig for Windows, unpacked (zig.exe, lib/)")
    o = a.parse_args()
    cc = shlex.split(o.cc, posix=os.name != "nt")
    if "-target" not in cc:
        cc += TARGET                            # not for this machine's processor
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
    if o.zig:
        add_zig(o.zig, cc[:2] if len(cc) >= 2 and cc[1] == "cc" else cc, out)
    print("made", out)


if __name__ == "__main__":
    main()
