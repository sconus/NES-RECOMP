#!/usr/bin/env python3
"""Check NES RECOMP's Windows zip (PLAN-windows.md step 6), as
tools/make_windows_release.py made it: build/NES-RECOMP-<version>-windows.zip.

    python3 tests/check_release_windows.py [ZIP]
    python3 tests/check_release_windows.py --write-prebuilt [ZIP]

Anywhere (`make test-release-windows` on the Mac):
  - one folder, "NES RECOMP <version>", holding what the app needs: the
    app as "NES RECOMP.exe", SDL2.dll, the recompiler, every runtime
    file, SDL's headers and import library, zlib, the app's Zig with its
    prebuilt C library; and nothing left over (no nesrecomp-app.exe, no
    debug database);
  - the licenses: MIT, SDL's, zlib's, Zig's, LLVM's and MinGW-w64's;
  - no file naming the folders of this machine (the one checking it);
  - the read-me's points: unzipping first, SmartScreen's "More info" and
    "Run anyway", where things go, the keys, the support link;
  - the prebuilt C library the same, file for file, as the Mac's
    (tests/windows_prebuilt.txt, written there with --write-prebuilt),
    so a zip made on the Mac carries what was checked on Windows.
On Windows (GitHub's machine), the zip unpacked into a folder with spaces
in its name, every file marked as downloaded from the Internet as a
browser marks it (the "Mark of the Web", Zone.Identifier), then:
  - NES RECOMP.exe's version (Windows's own reading of it), its icon, and
    its manifest (Windows's UTF-8 setting);
  - with no other compiler reachable, it builds a free test ROM named
    with accents and Japanese, and the game passes its test.
"""
import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import make_windows_release as rel  # noqa: E402

WIN = os.name == "nt"
OUT = os.path.join(ROOT, "build", "release_windows_check")
SUMS = os.path.join(HERE, "windows_prebuilt.txt")
fails = []


def check(name, ok, why=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, "" if ok else ": " + str(why)[:300]))
    if not ok:
        fails.append(name)


# Where the Mac's Zig (on Apple's ARM processor) and Windows's (on an x86
# PC) make different bytes, found on GitHub's Windows machine in step 6:
# two long-double constants in zigc.lib, the limits hypotl rescales at,
# which Zig works out while compiling, differ in their lowest bits (the
# Mac's arithmetic for long doubles is in software, the PC's is the x87's).
# Neither the runtime nor the recompiler's C uses long doubles. Any other
# difference still counts. (file, section number, its size): bytes.
SAME_BUT = {("zigc.lib", 22, 376): (320, 321, 352, 353)}


def coff_parts(body, file=""):
    """An x86-64 object's parts that go into a game, made independent of
    the order of its symbol table: each section (name, flags, bytes, and
    its relocations by symbol name), and the set of symbols (name, value,
    section, type, class). None if it isn't one."""
    if len(body) < 20 or body[:2] != b"\x64\x86":
        return None
    ns, _, st, nsym = struct.unpack("<HIII", body[2:16])
    strtab = body[st + 18 * nsym:]

    def sname(raw):
        if raw[:4] == b"\0\0\0\0":
            off = struct.unpack("<I", raw[4:8])[0]
            raw = strtab[off:strtab.index(b"\0", off)]
        # Zig numbers its unnamed constants (__anon_N) differently on each
        # machine: the number doesn't count.
        return re.sub(rb"__anon_\d+", b"__anon", raw.rstrip(b"\0"))
    names, k = {}, 0
    syms = []
    while k < nsym:
        e = body[st + 18 * k:st + 18 * k + 18]
        name = sname(e[:8])
        value, sec, typ, cls, aux = struct.unpack("<IhHBB", e[8:18])
        names[k] = name
        auxb = bytearray(body[st + 18 * (k + 1):st + 18 * (k + 1 + aux)] if name != b".file" else b"")
        if cls == 3 and aux and any(f == file and n == sec for f, n, _ in SAME_BUT):
            auxb[8:12] = bytes(4)       # that section's checksum (of the bytes SAME_BUT allows)
        auxb = bytes(auxb)
        syms.append((name, value, sec, typ, cls, auxb))
        k += 1 + aux
    secs = []
    for i in range(ns):
        h = body[20 + 40 * i:60 + 40 * i]
        sn = h[:8].rstrip(b"\0")
        if sn.startswith(b"/"):
            off = int(sn[1:])
            sn = strtab[off:strtab.index(b"\0", off)]
        size, ptr, rptr, _, nrel, _, flags = struct.unpack("<IIIIHHI", h[16:40])
        rel = sorted((struct.unpack("<I", body[rptr + 10 * j:rptr + 10 * j + 4])[0],
                      names.get(struct.unpack("<I", body[rptr + 10 * j + 4:rptr + 10 * j + 8])[0], b"?"),
                      struct.unpack("<H", body[rptr + 10 * j + 8:rptr + 10 * j + 10])[0]) for j in range(nrel))
        data = bytearray(body[ptr:ptr + size] if ptr else b"")
        for q in SAME_BUT.get((file, i + 1, size), ()):
            data[q] = 0
        secs.append((sn, flags, hashlib.sha256(bytes(data)).hexdigest(), rel))
    return {"sections": repr(secs).encode(), "symbols": repr(sorted(syms)).encode()}


def parts_of(data, file=""):
    """A prebuilt file's parts, by name: an archive's members (named
    without the folder they were made in; not its index, which counts
    those names), each object's parts (coff_parts)."""
    out = {}

    def add(name, body):
        c = coff_parts(body, file)
        if c is None:
            out[name] = hashlib.sha256(body).hexdigest()
        else:
            for k, v in c.items():
                out[name + ":" + k] = hashlib.sha256(v).hexdigest()
    if not data.startswith(b"!<arch>\n"):
        add("", data)
        return out
    i, longnames, seen = 8, b"", {}
    while i + 60 <= len(data):
        h = data[i:i + 60]
        nm, size = h[:16].decode("latin1").strip(), int(h[48:58].decode().strip() or 0)
        body = data[i + 60:i + 60 + size]
        i += 60 + size + (size & 1)
        if nm == "//":
            longnames = body
            continue
        if nm in ("/", "/SYM64/"):
            continue
        if nm.startswith("/") and nm[1:].isdigit():
            off = int(nm[1:])
            ends = [x for x in (longnames.find(b"\0", off), longnames.find(b"\n", off)) if x >= 0]
            nm = longnames[off:min(ends) if ends else len(longnames)].decode("latin1")
        nm = re.split(r"[\\/]", nm.rstrip("/"))[-1]
        seen[nm] = seen.get(nm, 0) + 1
        add("%s#%d" % (nm, seen[nm]), body)
    return out


def prebuilt_sums(z, top):
    """Each prebuilt file's fingerprint, of what goes into a game
    (parts_of), so the folder Zig made it in and the order of its
    symbols don't count; and, by kind of part (its sections, its symbols,
    the rest), a fingerprint each, to say which differs."""
    pre = top + "/zig/prebuilt/"
    sums, parts = {}, {}
    for n in sorted(z.namelist()):
        if n.startswith(pre) and not n.endswith("/"):
            p = parts_of(z.read(n), n[len(pre):])
            kinds = {}
            for k, h in sorted(p.items()):          # by kind: sections, symbols, the rest
                kind = k.rsplit(":", 1)[1] if ":" in k else "other"
                kinds.setdefault(kind, []).append((k.rsplit(":", 1)[0], h))
            parts[n[len(pre):]] = {k: hashlib.sha256(repr(v).encode()).hexdigest() for k, v in kinds.items()}
            sums[n[len(pre):]] = hashlib.sha256(repr(sorted(p.items())).encode()).hexdigest()
    return sums, parts


def windows_part(zip_path, top, version):
    import ctypes
    from ctypes import wintypes
    where = os.path.join(OUT, "unzipped here (with spaces)")
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(where)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(where)
    folder = os.path.join(where, top)
    marked = 0
    for d, _, fs in os.walk(folder):
        for f in fs:
            with open(os.path.join(d, f) + ":Zone.Identifier", "w") as m:
                m.write("[ZoneTransfer]\r\nZoneId=3\r\nHostUrl=https://github.com/\r\n")
            marked += 1
    exe = os.path.join(folder, "NES RECOMP.exe")
    zone = open(exe + ":Zone.Identifier").read() if os.path.exists(exe) else ""
    check("unzipped, every file marked as downloaded (%d)" % marked, "ZoneId=3" in zone, repr(zone))

    # The version, as Windows reads it (GetFileVersionInfo).
    ver = ctypes.WinDLL("version")
    n = ver.GetFileVersionInfoSizeW(exe, None)
    got = {}
    if n:
        buf = ctypes.create_string_buffer(n)
        ver.GetFileVersionInfoW(exe, 0, n, buf)
        for key in ("ProductName", "ProductVersion", "FileVersion", "OriginalFilename"):
            p, ln = ctypes.c_void_p(), wintypes.UINT()
            if ver.VerQueryValueW(buf, "\\StringFileInfo\\040904B0\\" + key, ctypes.byref(p), ctypes.byref(ln)):
                got[key] = ctypes.wstring_at(p, ln.value).rstrip("\x00")
    check("NES RECOMP.exe's version is %s (Windows's reading)" % version,
          got.get("ProductVersion") == version and got.get("FileVersion") == version
          and got.get("ProductName") == "NES RECOMP", got)
    shell = ctypes.WinDLL("shell32")
    shell.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    icons = shell.ExtractIconExW(exe, -1, None, None, 0)
    check("NES RECOMP.exe has its icon", icons >= 1, "%d icon(s)" % icons)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.LoadLibraryExW.restype = ctypes.c_void_p
    k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD]
    k32.FindResourceW.restype = ctypes.c_void_p
    k32.FindResourceW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    k32.LoadResource.restype = ctypes.c_void_p
    k32.LoadResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k32.LockResource.restype = ctypes.c_void_p
    k32.LockResource.argtypes = [ctypes.c_void_p]
    k32.SizeofResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    def manifest(path):
        h = k32.LoadLibraryExW(path, None, 0x2)             # LOAD_LIBRARY_AS_DATAFILE
        if not h:
            return ""
        r = k32.FindResourceW(h, ctypes.c_void_p(1), ctypes.c_void_p(24))   # RT_MANIFEST
        if not r:
            return ""
        return ctypes.string_at(k32.LockResource(k32.LoadResource(h, r)), k32.SizeofResource(h, r)).decode("utf-8", "replace")
    for prog in ("NES RECOMP.exe", "nesrecomp-recomp.exe"):
        m = manifest(os.path.join(folder, prog))
        check("%s has Windows's UTF-8 setting (its manifest)" % prog,
              re.search(r"<activeCodePage[^>]*>UTF-8</activeCodePage>", m) is not None, m[:120])
    r = subprocess.run([exe, "--version"], capture_output=True, text=True)
    check("NES RECOMP.exe --version says %s" % version, r.stdout.strip() == version, repr(r.stdout))

    # A build and a play, with no other compiler reachable, of a free test
    # ROM with accents and Japanese in its name, in a folder with spaces.
    roms = os.path.join(OUT, "my ROMs")
    os.makedirs(roms)
    rom = os.path.join(roms, "Café テスト (test).nes")
    shutil.copy(os.path.join(ROOT, "tests", "roms", "nes-test-roms", "instr_test-v5", "rom_singles",
                             "01-basics.nes"), rom)
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    env = {k: v for k, v in os.environ.items() if k not in ("NESRECOMP_ROOT", "NESRECOMP_RECOMP")}
    env["PATH"] = os.path.join(sysroot, "System32") + ";" + sysroot
    builds = os.path.join(OUT, "my builds")
    t0 = time.time()
    try:
        b = subprocess.run([exe, "--build", rom, "--build-dir", builds], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env, timeout=600)
        code, said = b.returncode, b.stdout
    except subprocess.TimeoutExpired:
        code, said = -9, "(never finished)"
    took = time.time() - t0
    print("     the first build, from the unzipped folder: %.1f s" % took)
    games = [f for f in os.listdir(builds) if f.endswith(".exe")] if os.path.isdir(builds) else []
    check("from the zip, with no other compiler: a ROM named with accents and Japanese builds",
          code == 0 and len(games) == 1, "exit %d, %s; %s" % (code, (said.strip().splitlines() or ["?"])[-1], games))
    ran = subprocess.run([os.path.join(builds, games[0]), rom, "--headless", "--frames", "600", "--no-save"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                         timeout=300) if len(games) == 1 else None
    check("...and its game opens it and passes its test",
          ran is not None and "test status at $6000: $00" in ran.stderr,
          "no game" if ran is None else ran.stderr[-200:])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    version = rel.app_version()
    zip_path = args[0] if args else os.path.join(ROOT, "build", "NES-RECOMP-%s-windows.zip" % version)
    if not os.path.exists(zip_path):
        sys.exit("no %s: make it first (make release-windows)" % zip_path)
    top = "NES RECOMP %s" % version
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if "--write-prebuilt" in sys.argv:
            sums, parts = prebuilt_sums(z, top)
            with open(SUMS, "w", newline="\n") as f:
                f.write("# The prebuilt C library in a Windows zip made on the Mac (make\n"
                        "# release-windows): a fingerprint per file of what goes into a game\n"
                        "# (each object's sections, relocations and symbols; not the folder\n"
                        "# Zig made it in, nor its symbols' order or numbering, nor SAME_BUT's\n"
                        "# bytes), then each file's sections,\n"
                        "# symbols and the rest.\n"
                        "# tests/check_release_windows.py checks a zip made elsewhere carries\n"
                        "# the same.\n")
                for n, h in sums.items():
                    f.write("%s  %s\n" % (h, n))
                for n in sorted(parts):
                    for k, h in sorted(parts[n].items()):
                        f.write("%s  %s|%s\n" % (h, n, k))
            print("wrote", SUMS, "(%d files)" % len(sums))
            return
        print("checking", zip_path, "(%.1f MB)" % (os.path.getsize(zip_path) / 1e6))
        tops = {n.split("/", 1)[0] for n in names}
        check('one folder, "%s"' % top, tops == {top}, sorted(tops)[:5])
        inside = {n[len(top) + 1:] for n in names if n.startswith(top + "/")}
        rt = sorted("runtime/" + f for f in os.listdir(os.path.join(ROOT, "runtime")) if f.endswith((".c", ".h")))
        need = ["NES RECOMP.exe", "SDL2.dll", "nesrecomp-recomp.exe", "READ ME FIRST.txt", "LICENSE.txt",
                "sdl2/include/SDL2/SDL.h", "sdl2/lib/libSDL2.dll.a", "zlib/include/zlib.h", "zlib/lib/libz.a",
                "zig/zig.exe", "zig/LICENSE", "zig/link.txt", "zig/prebuilt/game.res", "zig/prebuilt/crt2.obj",
                "zig/lib/std/std.zig", "zig/lib/libc/include/any-windows-any/windows.h",
                "zig/lib/include/stddef.h"] + rt
        missing = [n for n in need if n not in inside]
        check("what the app needs is there (%d files, every runtime file)" % len(need), not missing, missing)
        extra = sorted(n for n in inside if n == "nesrecomp-app.exe" or n.endswith((".pdb", ".m", ".part"))
                       or n.startswith("runtime/") and n not in rt)
        check("nothing left over (no nesrecomp-app.exe, no debug database)", not extra, extra)
        link = z.read(top + "/zig/link.txt").decode() if top + "/zig/link.txt" in names else ""
        pre = [l.split("/", 2)[-1] for l in link.splitlines() if l.startswith("{zig}/prebuilt/")]
        lost = [p for p in pre if "zig/prebuilt/" + p not in inside]
        check("every prebuilt file link.txt names is there (%d)" % len(pre), pre and not lost, lost)
        sigs = {"LICENSE.txt": ["MIT License", "Serge and Claude"],
                "licenses/SDL LICENSE.txt": ["Sam Lantinga", "provided 'as-is'"],
                "licenses/zlib LICENSE.txt": ["Jean-loup Gailly", "Mark Adler"],
                "licenses/Zig LICENSE.txt": ["The MIT License (Expat)", "Zig contributors"],
                "licenses/LLVM LICENSE.txt": ["Apache License", "LLVM Exceptions"],
                "licenses/MinGW-w64 LICENSE.txt": ["mingw-w64 project", "Zope Public License"]}
        bad = []
        for n, words in sigs.items():
            t = z.read(top + "/" + n).decode("utf-8", "replace") if n in inside else ""
            if not all(w in t for w in words):
                bad.append(n)
        check("the licenses: MIT, SDL's, zlib's, Zig's, LLVM's, MinGW-w64's", not bad, bad)

        # No file naming this machine's folders.
        tmp = os.path.join(OUT, "scan")
        shutil.rmtree(OUT, ignore_errors=True)
        os.makedirs(tmp)
        found = []
        pats = rel.machine_paths()
        for n in names:
            if n.endswith("/"):
                continue
            data = z.read(n)
            hit = next((p for p in pats if p in data), None)
            if hit:
                found.append("%s: %r" % (n, hit[:60]))
        check("no file names this machine's folders (%d patterns)" % len(pats), not found, found[:4])

        me = z.read(top + "/READ ME FIRST.txt").decode("utf-8", "replace") if "READ ME FIRST.txt" in inside else ""
        points = ["NES RECOMP %s for Windows" % version, "Extract All", "Windows protected your PC",
                  '"More info"', '"Run anyway"', "%LOCALAPPDATA%\\NES RECOMP", "Videos\\NES RECOMP",
                  "Enter (Start)", "Esc opens the pause menu", "Alt+Space", rel.support_url(), "Windows 10 (version 1903",
                  "licenses\\LLVM LICENSE.txt", "licenses\\MinGW-w64 LICENSE.txt",
                  "CONTROLLERS page", "PADS", "pair an Xbox", "The shelf under the TV",
                  "Delete takes a game off the shelf", "ALL KEYS: every key and button", "K shows the keys' cards"]
        miss = [p for p in points if p not in me]
        check("the read-me's points (%d)" % len(points), not miss, miss)
        check("the read-me has Windows's line ends", "\r\n" in me and "\n" not in me.replace("\r\n", ""), "")

        sums, parts = prebuilt_sums(z, top)
        want, want_parts = {}, {}
        if os.path.exists(SUMS):
            for l in open(SUMS):
                if l.strip() and not l.startswith("#"):
                    h, n = l.rstrip("\n").split("  ", 1)
                    if "|" in n:
                        f, k = n.split("|", 1)
                        want_parts.setdefault(f, {})[k] = h
                    else:
                        want[n] = h
        differ = sorted(set(want) ^ set(sums) | {n for n in want if n in sums and want[n] != sums[n]})
        why = []
        for n in differ:
            a, b = want_parts.get(n, {}), parts.get(n, {})
            bad = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
            why.append("%s (%d of %d parts differ: %s)" % (n, len(bad), len(set(a) | set(b)), bad[:4]))
        check("the prebuilt C library is the Mac's, file for file, in what goes into a game "
              "(%d, tests/windows_prebuilt.txt)" % len(want), want and not differ, "; ".join(why))
    if WIN:
        windows_part(zip_path, top, version)
    else:
        print("     (the rest is checked on Windows)")
    print("\n%s" % ("all checks pass" if not fails else "%d check(s) failed" % len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
