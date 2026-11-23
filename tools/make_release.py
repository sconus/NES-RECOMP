#!/usr/bin/env python3
"""Make build/NES-RECOMP-<version>-mac.zip, the app to give away
(PLAN-standalone.md step 9). Run by `make release`, after `make
app-bundle`. The zip holds one folder, "NES RECOMP <version>":

    NES RECOMP.app        the app (build/nesrecomp.app), signed ad hoc
    READ ME FIRST.txt     what it is, what it needs, how to open it the
                          first time, where things go, the keys, and the
                          support page (app/support.h's link)
    LICENSE.txt           the MIT License (this project's LICENSE)
    SDL LICENSE.txt       SDL's zlib license (the app carries SDL2)

It's zipped with ditto, as the Finder does, so the app's signature and
its symbolic links come out of it as they went in; but without this
Mac's extended attributes (no __MACOSX folder in the zip). The version is the
app's own (`nesrecomp --version`).
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP = os.path.join(ROOT, "build", "nesrecomp.app")

READ_ME = """NES RECOMP {version}
For educational purposes only. By Serge and Claude.
Free software under the MIT License (LICENSE.txt).

WHAT IT IS
Drop an NES game file (.nes, .nsf or .fds) on NES RECOMP's window. It
recompiles the game's 6502 machine code into C, builds it into a program
on your Mac, and plays it. After each game, its "under the hood" screen
shows how much of the game became C, and C there shows the original
6502 instructions next to the C they became.
No games come with it: use your own files.

WHAT IT NEEDS
- A Mac with macOS 11 or later, Apple Silicon or Intel.
- Apple's free C compiler (the Command Line Tools). If it isn't
  installed, NES RECOMP says so when you drop a game: click the TV and
  Apple's installer opens (or type  xcode-select --install  in
  Terminal). When it's done, drop the game again.

OPENING IT THE FIRST TIME
NES RECOMP isn't signed by an Apple-registered developer, so the first
time, macOS stops it and asks you to confirm.
1. Move "NES RECOMP.app" where you like (Applications, say).
2. Double-click it. macOS says it can't open it, or can't check it.
   Close that message (Done or OK).
3. macOS 15 or later: open System Settings, Privacy & Security, scroll
   down to Security, and click "Open Anyway" next to NES RECOMP. Confirm
   with your password or Touch ID, then "Open Anyway" again.
   macOS 11 to 14: instead, Control-click the app, choose Open, then
   Open.
After that, it opens with a double-click like any app.

USING IT
- Drop a game on the window, or click the TV to choose one. The first
  build takes a few seconds; after that, a game starts at once.
- In a game: arrow keys, X (A), Z (B), Return (Start), Right Shift
  (Select); M mutes, R resets, V starts and stops a recording, P saves
  a picture. Esc opens the pause menu: save and load, the volume, the
  window's size, quit. Game controllers work too (hold Select and Start
  for the menu; the shoulder buttons rewind and fast-forward).
- The pause menu's CONTROLLERS page: a button test, to see which pad
  is which player; changing the keys (KEYBOARD 1 and 2) and the pad
  buttons (PADS), kept for the next game; and how to pair an Xbox,
  PlayStation or Switch Pro controller with your Mac.
- The shelf under the TV holds every game you've built, last played
  first, each box showing the game's own title screen. Arrow keys or
  the mouse pick one (the TV shows it), Enter or a click plays it, Page
  Up and Page Down flip pages. Delete takes a game off the shelf (it
  asks first; your game file and saves stay). A dim box means its game
  file was moved: drop it again.
- On the drop screen: I shows who made it (and D there opens the
  support page), H shows "under the hood"
  for the last game; there, C shows its code.
- Games get faster as you play them: the places the game ran in the
  interpreter are written to <game>.missed beside the game file, and
  the next build translates them too.

WHERE THINGS GO
- The games it builds, their logs and its settings:
  your home folder, Library/Application Support/NES RECOMP
  (safe to delete; games are just built again).
- Recordings and pictures: Movies/NES RECOMP in your home folder.
- <game>.missed and <game>.sav (battery saves): beside the game file,
  or in the app's folder if that one can't be written.

SUPPORTING IT
NES RECOMP is free. If you'd like to support it, and the Polygon
Legends channel it comes from:
  {support}
(The same link is in the app: "Support NES RECOMP..." in its menu, and D
on its About screen.)

LICENSES
LICENSE.txt: NES RECOMP, MIT License.
SDL LICENSE.txt: SDL {sdl}, which NES RECOMP carries, zlib License.
"""


def main():
    prog = os.path.join(APP, "Contents", "MacOS", "nesrecomp")
    if not os.path.exists(prog):
        sys.exit("build/nesrecomp.app is missing: run `make app-bundle` first")
    version = subprocess.run([prog, "--version"], capture_output=True, text=True,
                             check=True).stdout.strip()
    vh = open(os.path.join(APP, "Contents", "Resources", "sdl2", "include", "SDL2",
                           "SDL_version.h")).read()
    import re
    sdl = ".".join(re.search(r"#define SDL_%s\s+(\d+)" % k, vh).group(1)
                   for k in ("MAJOR_VERSION", "MINOR_VERSION", "PATCHLEVEL"))
    name = "NES RECOMP %s" % version
    stage = os.path.join(ROOT, "build", "release")
    shutil.rmtree(stage, ignore_errors=True)
    folder = os.path.join(stage, name)
    os.makedirs(folder)
    # ditto copies the bundle as it is: links, permissions, signature.
    subprocess.run(["ditto", APP, os.path.join(folder, "NES RECOMP.app")], check=True)
    with open(os.path.join(folder, "READ ME FIRST.txt"), "w") as f:
        support = subprocess.run([prog, "--support-url"], capture_output=True, text=True,
                                 check=True).stdout.strip()
        f.write(READ_ME.format(version=version, sdl=sdl, support=support))
    shutil.copyfile(os.path.join(ROOT, "LICENSE"), os.path.join(folder, "LICENSE.txt"))
    shutil.copyfile(os.path.join(APP, "Contents", "Resources", "sdl2", "LICENSE.txt"),
                    os.path.join(folder, "SDL LICENSE.txt"))
    zip_path = os.path.join(ROOT, "build", "NES-RECOMP-%s-mac.zip" % version)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    # Without resource forks, extended attributes or ACLs: the app needs
    # none (its signature is in its files), and this Mac's own marks on
    # them (com.apple.provenance, say) aren't for the person who gets it.
    subprocess.run(["ditto", "-c", "-k", "--norsrc", "--noextattr", "--noacl", "--keepParent",
                    folder, zip_path], check=True)
    print("wrote", zip_path)


if __name__ == "__main__":
    main()
