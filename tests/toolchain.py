"""How the test scripts build and run games, on the Mac and on Windows
(PLAN-windows.md step 2). On the Mac it is what they always did: the
Mac's cc, Homebrew's SDL2 through sdl2-config, macOS's zlib. On Windows:

    NESRECOMP_CC         the compiler (default "zig cc")
    NESRECOMP_SDL2       SDL's official Windows build for x86_64 (the
                         x86_64-w64-mingw32 folder of SDL2-devel-...-mingw):
                         its include/SDL2 and lib/libSDL2.dll.a; SDL2.dll
                         (its bin) must be on PATH to run a game
    NESRECOMP_ZLIB_SRC   zlib's source folder (zlib-1.3.1), compiled here
                         once into build/windows/zlib
    NESRECOMP_RECOMP     the recompiler (default build/windows/
                         nesrecomp-recomp.exe)
"""
import os
import shlex
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WIN = os.name == "nt"
EXE = ".exe" if WIN else ""


def cc():
    return shlex.split(os.environ.get("NESRECOMP_CC", "zig cc" if WIN else "cc"), posix=not WIN)


def recompiler():
    if WIN:
        return os.environ.get("NESRECOMP_RECOMP",
                              os.path.join(ROOT, "build", "windows", "nesrecomp-recomp.exe"))
    return os.path.join(ROOT, "build", "nesrecomp-recomp")


def runtime_sources():
    """The runtime's files to compile: its .c, and on the Mac its .m
    (recording through AVFoundation)."""
    ends = (".c",) if WIN else (".c", ".m")
    return sorted(f for f in os.listdir(os.path.join(ROOT, "runtime")) if f.endswith(ends))


def _zlib():
    """zlib for Windows: its headers' folder, and its objects (compiled
    from NESRECOMP_ZLIB_SRC the first time)."""
    src = os.environ["NESRECOMP_ZLIB_SRC"]
    out = os.path.join(ROOT, "build", "windows", "zlib")
    os.makedirs(out, exist_ok=True)
    objs = []
    for f in sorted(os.listdir(src)):
        if f.endswith(".c"):
            o = os.path.join(out, f[:-2] + ".o")
            if not os.path.exists(o):
                r = subprocess.run(cc() + ["-O2", "-c", os.path.join(src, f), "-o", o],
                                   capture_output=True, text=True)
                if r.returncode:
                    raise SystemExit("zlib: " + r.stderr)
            objs.append(o)
    return src, objs


def sdl_flags():
    """(flags to compile the runtime and a game, what to link them with)."""
    if WIN:
        sdl = os.environ["NESRECOMP_SDL2"]
        zinc, zobjs = _zlib()
        return (["-I" + os.path.join(sdl, "include", "SDL2"), "-I" + zinc, "-D_THREAD_SAFE"],
                zobjs + [os.path.join(sdl, "lib", "libSDL2.dll.a"), "-lole32"])
    prefix = subprocess.run(["sdl2-config", "--prefix"], capture_output=True, text=True).stdout.strip()
    cflags = subprocess.run(["sdl2-config", "--cflags"], capture_output=True, text=True).stdout.split()
    return cflags, [os.path.join(prefix, "lib", "libSDL2.dylib"), "-lz", "-lm",
                    "-framework", "AVFoundation", "-framework", "CoreMedia",
                    "-framework", "CoreVideo", "-framework", "Foundation"]
