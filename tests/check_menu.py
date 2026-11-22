#!/usr/bin/env python3
"""The pause menu (PLAN-pause.md step 1), headless, driven by input-script
menu lines ("100 menu down ok", see runtime/main.c).

- Its pictures: the menu's box and text, pixel by pixel, against what
  runtime/menu.c's layout and the runtime's 5x7 font say they should be
  (the cursor on RESUME; on SLOT after picking slot 2; a saved slot's
  date), and the game behind it darkened.
- SAVE STATE then LOAD STATE from the menu: the frames after the load
  are the frames after the save, fingerprint for fingerprint, and the
  slot's file is written.
- RESET from the menu: the same frames as the script's own reset word
  (as R does).
- The slot picked in the menu is the file written: slot 2 writes
  .state2, not .state1.
- Opening and closing happen at the same frame (no game runs meanwhile).
- SOUND and WINDOW (step 3): their pictures; the volume scales what the
  speakers get (--speaker-out), by 3 dB a step, and OFF silences it, from
  the frame the menu closes; --volume does the same from the start; what
  was picked is written on exit (--remember-size), and the window's
  steps reach FULL (headless: a pretend window, 4X at most).
- CONTROLLERS (PLAN-controllers.md step 1): its page, listing what each
  slot holds, and the button test, pixel by pixel, with a virtual
  controller in slot 2 (the script's pad= word) holding buttons; the
  terminal names each fresh press, not one held as the test opened;
  only leave (Esc, Home) gets off the test page, not B or the others;
  and the game doesn't move meanwhile.

How the menu changes nothing over the whole suite is in
tests/check_states.py.

    python3 tests/check_menu.py
"""
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_tests  # noqa: E402
import toolchain  # noqa: E402

ROOT = run_tests.ROOT
OUT = os.path.join(ROOT, "build", "menu")
GAMES = [("tests/mmc3_split.nes", None), ("tests/fds_demo.fds", "tests/inputs/fds_demo.txt")]

failures = 0


def check(what, ok, why=""):
    global failures
    print(("ok    " if ok else "FAIL  ") + what + ("" if ok else ": " + why))
    failures += not ok


def layout():
    src = open(os.path.join(ROOT, "runtime", "menu.c")).read()
    d = {k: int(v, 0) for k, v in
         re.findall(r"#define ((?:MENU|INK|TEST|CTRL)_\w+) (0x[0-9A-F]+|\d+)", src)}
    d["parts"] = {name: tuple(map(int, xywh)) for name, *xywh in
                  re.findall(r"\{ PART_(\w+), (\d+), (\d+), (\d+), (\d+) \}", src)}
    return d


def font():
    src = open(os.path.join(ROOT, "runtime", "nsf.c")).read()
    body = src.split("font[64][7] = {", 1)[1].split("};", 1)[0]
    vals = [int(v, 16) for v in re.findall(r"0x([0-9A-F]{2})", body)]
    return [vals[i * 7:i * 7 + 7] for i in range(64)]


def text_pixels(fnt, s, x0, y0):
    """draw_text_5x7's lit pixels."""
    on = set()
    for i, ch in enumerate(s):
        o = ord(ch.upper())
        if o < 0x20 or o > 0x5F:
            o = ord("?")
        g = fnt[o - 0x20]
        for r in range(7):
            for c in range(5):
                if g[r] & (0x10 >> c):
                    on.add((x0 + i * 6 + c, y0 + r))
    return on


def expected_box(L, fnt, cursor, slot, info, sound="10", window="3X"):
    """The menu's box as menu.c draws it: {(x, y): colour}."""
    want = {}
    x0, y0, w, h = L["MENU_BOX_X"], L["MENU_BOX_Y"], L["MENU_BOX_W"], L["MENU_BOX_H"]
    for y in range(y0 - 1, y0 + h + 1):
        for x in range(x0 - 1, x0 + w + 1):
            inside = x0 <= x < x0 + w and y0 <= y < y0 + h
            want[(x, y)] = L["INK_BOX"] if inside else L["INK_EDGE"]
    title = "PAUSED"
    for p in text_pixels(fnt, title, 128 - (len(title) * 6 - 1) // 2, L["MENU_TITLE_Y"]):
        want[p] = L["INK_TITLE"]
    items = ["RESUME", "SAVE STATE", "LOAD STATE", "SLOT  < %d >" % slot, "RESET",
             "SOUND < %s >" % sound, "WINDOW < %s >" % window, "CONTROLLERS", "QUIT"]
    for i, name in enumerate(items):
        y = L["MENU_ITEM_Y"] + i * L["MENU_LINE_H"]
        for p in text_pixels(fnt, name, L["MENU_ITEM_X"], y):
            want[p] = L["INK_PICKED"] if i == cursor else L["INK_ITEM"]
        if i == 3:
            for p in text_pixels(fnt, info, L["MENU_INFO_X"], y):
                want[p] = L["INK_ITEM"]
    for p in text_pixels(fnt, ">", L["MENU_CURSOR_X"], L["MENU_ITEM_Y"] + cursor * L["MENU_LINE_H"]):
        want[p] = L["INK_CURSOR"]
    return want


def frame_box(want, L, x0, y0, w, h):
    for y in range(y0 - 1, y0 + h + 1):
        for x in range(x0 - 1, x0 + w + 1):
            inside = x0 <= x < x0 + w and y0 <= y < y0 + h
            want[(x, y)] = L["INK_BOX"] if inside else L["INK_EDGE"]


def centred(want, fnt, s, y, ink):
    for p in text_pixels(fnt, s, 128 - (len(s) * 6 - 1) // 2, y):
        want[p] = ink


def expected_controllers(L, fnt, cursor, names):
    """The CONTROLLERS page; names[i] is slot i's (None: empty)."""
    want = {}
    frame_box(want, L, L["MENU_BOX_X"], L["MENU_BOX_Y"], L["MENU_BOX_W"], L["MENU_BOX_H"])
    centred(want, fnt, "CONTROLLERS", L["MENU_TITLE_Y"], L["INK_TITLE"])
    for i, item in enumerate(["BUTTON TEST", "BACK"]):
        for p in text_pixels(fnt, item, L["MENU_ITEM_X"], L["MENU_ITEM_Y"] + i * L["MENU_LINE_H"]):
            want[p] = L["INK_PICKED"] if i == cursor else L["INK_ITEM"]
    for p in text_pixels(fnt, ">", L["MENU_CURSOR_X"], L["MENU_ITEM_Y"] + cursor * L["MENU_LINE_H"]):
        want[p] = L["INK_CURSOR"]
    for i, n in enumerate(names):
        line = "%d %s" % (i + 1, n[:L["CTRL_LIST_CHARS"]]) if n else "%d -" % (i + 1)
        for p in text_pixels(fnt, line, L["MENU_CURSOR_X"], L["CTRL_LIST_Y"] + i * L["CTRL_LIST_H"]):
            want[p] = L["INK_ITEM"]
    return want


def expected_test(L, fnt, pads):
    """The button test; pads[i] for controllers 1-4 and keyboards 1-2:
    None (empty), or (label, the lit parts' names)."""
    want = {}
    frame_box(want, L, L["TEST_BOX_X"], L["TEST_BOX_Y"], L["TEST_BOX_W"], L["TEST_BOX_H"])
    centred(want, fnt, "BUTTON TEST", L["TEST_TITLE_Y"], L["INK_TITLE"])
    for i, pad in enumerate(pads):
        x = L["TEST_COL1"] if i % 2 else L["TEST_COL0"]
        y = L["TEST_ROW0"] + (i // 2) * L["TEST_ROW_H"]
        label = pad[0] if pad else "%d -" % (i + 1)
        lit = pad[1] if pad else ()
        for p in text_pixels(fnt, label, x, y):
            want[p] = L["INK_PICKED"] if lit else L["INK_ITEM"]
        if not pad:
            for p in text_pixels(fnt, "NO CONTROLLER", x, y + L["TEST_PAD_DY"] + L["TEST_BODY_Y"] + 13):
                want[p] = L["INK_NONE"]
            continue
        py = y + L["TEST_PAD_DY"]
        for yy in range(L["TEST_BODY_H"]):
            for xx in range(L["TEST_BODY_W"]):
                want[(x + L["TEST_BODY_X"] + xx, py + L["TEST_BODY_Y"] + yy)] = L["INK_BODY"]
        for name, (px, pyy, w, h) in L["parts"].items():
            ink = (L["INK_LIT"] if name in lit else
                   L["INK_OFF_OUT"] if pyy < L["TEST_BODY_Y"] else L["INK_OFF"])
            for yy in range(h):
                for xx in range(w):
                    want[(x + px + xx, py + pyy + yy)] = ink
    centred(want, fnt, "TO LEAVE: ESC, HOME, OR HOLD SEL+START", L["TEST_FOOT_Y"], L["INK_ITEM"])
    return want


def controllers(exe, rom, base, name, L, fnt):
    files = os.path.join(OUT, name + ".ctrl")
    page, test, held, after = (os.path.join(OUT, name + x + ".raw")
                               for x in (".ctrl", ".test", ".held", ".after"))
    keys = ["up up ok",                         # CONTROLLERS (above QUIT)
            "pad=2:none shot=%s" % page,        # a virtual controller in slot 2
            "pad=2:a ok",                       # A held as the test opens
            "pad=2:a+b",                        # B pressed, A still held
            "pad=2:none pad=2:a+start+lb",      # let go, then pressed: lit
            "shot=%s" % test,
            "ok back up down left right",       # these only light up (no keyboard
            "shot=%s" % held,                   # headless): still the test page
            "pad=2:home leave",                 # Esc: back to CONTROLLERS
            "shot=%s" % after,
            "back back"]
    err, rows = run(exe, rom, ["60 menu " + " ".join(keys)], base, 90, name + ".ctrl", files)
    virt = "NESRECOMP VIRTUAL CONTROLLER"
    why = picture_ok(page, expected_controllers(L, fnt, 0, [None, virt, None, None]))
    check("%s: the CONTROLLERS page, a controller in slot 2" % name, not why, why or "")
    keyb = ("KEYBOARD 1", ()), ("KEYBOARD 2", ())
    want = expected_test(L, fnt, [None, ("2 VIRTUAL", ("A", "START", "LB")), None, None] + list(keyb))
    why = picture_ok(test, want)
    check("%s: the button test, A, Start and LB lit on controller 2" % name, not why, why or "")
    why = picture_ok(held, want)
    check("%s: OK, back and the arrows don't leave the button test" % name, not why, why or "")
    why = picture_ok(after, expected_controllers(L, fnt, 0, [None, virt, None, None]))
    check("%s: leave goes back to CONTROLLERS" % name, not why, why or "")
    said = [ln for ln in err.splitlines() if ln.startswith(("frame 60:", "controller ", "keyboard "))]
    check("%s: the terminal names each fresh press (not A held as it opened)" % name,
          said == ["frame 60: MENU", "frame 60: CONTROLLERS", "frame 60: BUTTON TEST",
                   "controller 2: B", "controller 2: START", "controller 2: A", "controller 2: LB",
                   "controller 2: HOME", "frame 60: CONTROLLERS", "frame 60: MENU CLOSED (RESUME)"],
          repr(said))
    _, plain = run(exe, rom, [], base, 90, name + ".ctrlplain", os.path.join(OUT, name + ".cp"))
    check("%s: the controllers' pages don't move the game" % name,
          len(rows) == 90 and rows == plain, "%d frames, differ from the plain run" % len(rows))


def read_raw(path):
    d = open(path, "rb").read()
    return [d[i] | d[i + 1] << 8 for i in range(0, len(d), 2)]


def picture_ok(path, want):
    if not os.path.exists(path):
        return "no picture"
    pic = read_raw(path)
    if len(pic) != 256 * 240:
        return "%d pixels, not 256x240" % len(pic)
    bad = sum(1 for (x, y), c in want.items() if pic[y * 256 + x] != c)
    # The game behind it, darkened: only the palette's two darkest rows'
    # colours (0x00-0x1C) and black.
    lit = sum(1 for i, c in enumerate(pic) if (i % 256, i // 256) not in want and
              (c > 0x1C or (c & 0x0F) == 0x0D) and c != 0x0F)
    if bad or lit:
        return "%d pixel(s) of the menu differ, %d behind it not darkened" % (bad, lit)
    return None


def build(rom, cflags, libs, rt_objs):
    ident = re.sub(r"[^A-Za-z0-9_.-]", "_", rom)
    c_file = os.path.join(OUT, ident + ".c")
    exe = os.path.join(OUT, ident + toolchain.EXE)
    path = os.path.join(ROOT, rom)
    args = [toolchain.recompiler(), path, "-o", c_file]
    if os.path.exists(path + ".missed"):
        args += ["--missed", path + ".missed"]
    r = run_tests.sh(args, cwd=ROOT)
    if r.returncode:
        sys.exit("recompile error: " + r.stderr[-300:])
    r = run_tests.sh(toolchain.cc() + ["-O1", "-Iruntime"] + cflags + ["-o", exe, c_file] +
                     rt_objs + libs, cwd=ROOT)
    if r.returncode:
        sys.exit("compile error: " + r.stderr[:300])
    return exe


def run(exe, rom, script_lines, base_script, frames, tag, files, extra=()):
    """Run headless with the game's script plus `script_lines`; returns
    (stderr, the frames' fingerprints, 32 bytes each)."""
    script = os.path.join(OUT, tag + ".txt")
    with open(script, "w") as f:
        if base_script:
            f.write(open(os.path.join(ROOT, base_script)).read() + "\n")
        f.write("\n".join(script_lines) + "\n")
    prints = os.path.join(OUT, tag + ".prints")
    r = run_tests.sh([exe, os.path.join(ROOT, rom), "--headless", "--no-save",
                      "--files-at", files, "--frames", str(frames), "--input", script,
                      "--prints-out", prints] + list(extra), cwd=ROOT, timeout=120)
    data = open(prints, "rb").read() if os.path.exists(prints) else b""
    return r.stderr, [data[i:i + 32] for i in range(0, len(data), 32)]


SOUND_GAMES = ("fds_demo.fds",)        # mmc3_split.nes is silent
GAIN = [0] + [round(32768 * 10 ** (-3 * (10 - n) / 20)) for n in range(1, 11)]


def samples(path):
    d = open(path, "rb").read() if os.path.exists(path) else b""
    return [int.from_bytes(d[i:i + 2], "little", signed=True) for i in range(0, len(d) - 1, 2)]


def scaled(xs, level):
    return [(x * GAIN[level]) >> 15 for x in xs]


def split_ok(full, got, level):
    """got is full up to some sample, then full at `level`: where, or why not."""
    if len(got) != len(full):
        return None, "%d samples, not %d" % (len(got), len(full))
    k = next((i for i, (a, b) in enumerate(zip(full, got)) if a != b), len(full))
    if k == 0 or k == len(full):
        return None, "changed at sample %d of %d" % (k, len(full))
    if got[k:] != scaled(full[k:], level):
        return None, "after sample %d not the volume asked for" % k
    return k, ""


def sound_and_window(exe, rom, base, name, L, fnt):
    down5 = "down down down down down"
    # Pictures: SOUND turned down three steps, WINDOW up two (to FULL).
    pic = os.path.join(OUT, name + ".sw.raw")
    run(exe, rom, ["60 menu %s left left left down right right shot=%s back" % (down5, pic)],
        base, 70, name + ".swpic", os.path.join(OUT, name + ".swpic"))
    why = picture_ok(pic, expected_box(L, fnt, 6, 1, "EMPTY", "7", "FULL"))
    check("%s: the menu with SOUND at 7 and WINDOW at FULL" % name, not why, why or "")
    pic = os.path.join(OUT, name + ".sw2.raw")
    run(exe, rom, ["60 menu %s ok down left shot=%s back" % (down5, pic)],
        base, 70, name + ".swpic2", os.path.join(OUT, name + ".swpic2"))
    why = picture_ok(pic, expected_box(L, fnt, 6, 1, "EMPTY", "OFF", "2X"))
    check("%s: the menu with SOUND OFF and WINDOW at 2X" % name, not why, why or "")

    # The speakers' sound: plain, then turned down to 5 at frame 40, then off.
    def speakers(tag, lines, extra=()):
        out = os.path.join(OUT, name + "." + tag + ".pcm")
        err, _ = run(exe, rom, lines, base, 120, name + "." + tag,
                     os.path.join(OUT, name + "." + tag), ["--speaker-out", out] + list(extra))
        return samples(out), err
    if name not in SOUND_GAMES:
        return remembered(exe, rom, base, name, down5)
    full, _ = speakers("full", [])
    check("%s: the speakers get sound (or the next checks prove nothing)" % name,
          len(full) > 48000 and any(full), "%d samples" % len(full))
    five, err = speakers("five", ["40 menu %s left left left left left back" % down5])
    k, why = split_ok(full, five, 5)
    check("%s: SOUND 5 in the menu: the speakers 15 dB quieter from then on" % name, k, why)
    # From the frame it closed, frame 40's end (798.7 samples a frame;
    # the first sample that differs can be a little later, as a 0 stays 0).
    if k:
        f = k / (48000 / 60.0988)
        check("%s: ... from about the frame the menu closed (%.1f)" % (name, f), 39 <= f <= 41.5,
              "from sample %d (frame %.1f)" % (k, f))
    off, _ = speakers("off", ["40 menu %s ok back" % down5])
    k, why = split_ok(full, off, 0)
    check("%s: SOUND OFF in the menu silences the speakers" % name, k, why)
    to_off, _ = speakers("tooff", ["40 menu %s %s back" % (down5, " ".join(["left"] * 10))])
    k, why = split_ok(full, to_off, 0)
    check("%s: ten steps down is OFF" % name, k, why)
    start, _ = speakers("start5", [], ["--volume", "5"])
    check("%s: --volume 5 from the start" % name, start == scaled(full, 5),
          "%d samples, %d differ" % (len(start), sum(a != b for a, b in zip(start, scaled(full, 5)))))
    # The blip: each change in the menu plays one at the new volume (none
    # for OFF), so it can be heard with the game paused. The full-volume
    # blip comes from 9 -> 10; the rest must be it, scaled exactly.
    def blips(tag, lines, extra=()):
        speakers(tag, lines, extra)
        b = samples(os.path.join(OUT, name + "." + tag + ".pcm.blip"))
        return [b[i:i + 2400] for i in range(0, len(b), 2400)]
    ref = blips("blipfull", ["40 menu %s right" % down5], ["--volume", "9"])
    check("%s: a blip at 10 (or the next checks prove nothing)" % name,
          len(ref) == 1 and len(ref[0]) == 2400 and max(ref[0]) > 4000,
          "%d blip(s)" % len(ref))
    if ref:
        down = blips("blipdown", ["40 menu %s left left left left left" % down5])
        check("%s: five steps down: five blips, at 9, 8, 7, 6, 5" % name,
              down == [scaled(ref[0], v) for v in (9, 8, 7, 6, 5)],
              "%d blip(s); %s" % (len(down), [max(b) for b in down]))
        to_off = blips("blipoff", ["40 menu %s %s right" % (down5, " ".join(["left"] * 10))])
        check("%s: down to OFF and up to 1: no blip for OFF" % name,
              to_off == [scaled(ref[0], v) for v in (9, 8, 7, 6, 5, 4, 3, 2, 1, 1)],
              "%d blip(s)" % len(to_off))
        toggle = blips("bliptoggle", ["40 menu %s ok ok" % down5])
        check("%s: Return: off (no blip), on again (a blip at 10)" % name,
              toggle == [ref[0]], "%d blip(s)" % len(toggle))
        quiet = blips("blipnone", ["40 menu %s back" % down5], ["--volume", "6"])
        check("%s: no blip without a change" % name, quiet == [], "%d blip(s)" % len(quiet))

    # Only the speakers: the game's own sound (the fingerprints) unchanged.
    _, rows_full = run(exe, rom, [], base, 120, name + ".fp1", os.path.join(OUT, name + ".fp1"))
    _, rows_five = run(exe, rom, [], base, 120, name + ".fp2", os.path.join(OUT, name + ".fp2"),
                       ["--volume", "3", "--sound-off"])
    check("%s: the volume doesn't change the game or its own sound" % name,
          rows_full == rows_five and len(rows_full) == 120, "the fingerprints differ")

    remembered(exe, rom, base, name, down5)


def remembered(exe, rom, base, name, down5):
    # Remembered: the size and the volume picked in the menu, on exit.
    prefs = os.path.join(OUT, name + ".prefs.txt")
    run(exe, rom, ["40 menu %s left left down left back" % down5], base, 60, name + ".rem",
        os.path.join(OUT, name + ".rem"), ["--remember-size", prefs])
    said = open(prefs).read() if os.path.exists(prefs) else ""
    check("%s: SOUND 8 and WINDOW 2X from the menu are remembered" % name,
          said == "game_scale 2\nvolume 8\nsound_off 0\n", repr(said))
    run(exe, rom, ["40 menu %s ok down right right back" % down5], base, 60, name + ".rem2",
        os.path.join(OUT, name + ".rem2"), ["--remember-size", prefs])
    said = open(prefs).read() if os.path.exists(prefs) else ""
    check("%s: SOUND OFF, and full screen keeps the last window size" % name,
          said == "game_scale 4\nvolume 10\nsound_off 1\n", repr(said))


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    cflags, libs = run_tests.sdl_flags()
    rt_objs = run_tests.build_runtime(cflags)
    L, fnt = layout(), font()
    for rom, base in GAMES:
        name = os.path.basename(rom)
        exe = build(rom, cflags, libs, rt_objs)
        files = os.path.join(OUT, name + ".pics")
        a, b, c = (os.path.join(OUT, name + x + ".raw") for x in (".a", ".b", ".c"))
        # Pictures: as it opens; on SLOT after picking 2; then slot 1 saved.
        err, _ = run(exe, rom, ["60 menu shot=%s back" % a,
                                "61 menu down down down right shot=%s left back" % b,
                                "62 menu down ok",
                                "63 menu shot=%s back" % c], base, 70, name + ".pics", files)
        check("%s: the menu as it opens" % name,
              not picture_ok(a, expected_box(L, fnt, 0, 1, "EMPTY")),
              picture_ok(a, expected_box(L, fnt, 0, 1, "EMPTY")) or "")
        why = picture_ok(b, expected_box(L, fnt, 3, 2, "EMPTY"))
        check("%s: the menu on SLOT, slot 2 picked" % name, not why, why or "")
        saved = files + ".state1"
        info = "?"
        if os.path.exists(saved):
            t = time.localtime(os.path.getmtime(saved))
            info = "%d %s %02d:%02d" % (t.tm_mday, time.strftime("%b", t).upper(), t.tm_hour, t.tm_min)
        why = picture_ok(c, expected_box(L, fnt, 0, 1, info))
        check("%s: a saved slot shows its date (%s)" % (name, info), not why, why or "")
        opened = re.findall(r"frame (\d+): MENU\n", err)
        closed = re.findall(r"frame (\d+): MENU CLOSED", err)
        check("%s: the menu opens at the frames asked for, and closes there" % name,
              opened == closed == ["60", "61", "62", "63"], "opened %s, closed %s" % (opened, closed))

        # SAVE at 40, LOAD at 100: the frames after the load are those after the save.
        files = os.path.join(OUT, name + ".saveload")
        err, rows = run(exe, rom, ["40 menu down ok", "100 menu down down ok"], base, 200,
                        name + ".saveload", files)
        same = len(rows) >= 160 and all(rows[100 + k] == rows[40 + k] for k in range(60))
        check("%s: SAVE then LOAD from the menu plays the same frames again" % name,
              same and "SLOT 1 SAVED" in err and "SLOT 1 LOADED" in err,
              "%d frames; %s" % (len(rows), err[-300:]))
        check("%s: SAVE wrote the slot's file" % name, os.path.exists(files + ".state1"),
              "no " + files + ".state1")

        # RESET from the menu, and the script's reset word, at frame 50.
        _, menu_rows = run(exe, rom, ["50 menu down down down down ok"], base, 150,
                           name + ".reset_menu", os.path.join(OUT, name + ".rm"))
        _, word_rows = run(exe, rom, ["50 reset"] if not base else [], base, 150,
                           name + ".reset_word", os.path.join(OUT, name + ".rw"))
        if base:    # the reset word goes in the game's own script, in order
            lines = open(os.path.join(ROOT, base)).read().splitlines()
            merged = os.path.join(OUT, name + ".reset_word.base.txt")
            keep = [ln for ln in lines if not ln.strip() or ln.lstrip().startswith("#")
                    or int(ln.split()[0]) < 50]
            later = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")
                     and int(ln.split()[0]) >= 50]
            # The buttons held at frame 50 stay held (a line replaces them all).
            held = ""
            for ln in keep:
                if ln.strip() and not ln.lstrip().startswith("#"):
                    held = " ".join(w for w in ln.split()[1:] if not w.startswith(("disk=", "record", "snap")))
            open(merged, "w").write("\n".join(keep + ["50 reset " + held] + later) + "\n")
            _, word_rows = run(exe, rom, [], os.path.relpath(merged, ROOT), 150,
                               name + ".reset_word", os.path.join(OUT, name + ".rw"))
        _, plain_rows = run(exe, rom, [], base, 150, name + ".plain", os.path.join(OUT, name + ".pl"))
        check("%s: the reset changes the game (or the next check proves nothing)" % name,
              menu_rows != plain_rows, "the same frames as with no reset")
        check("%s: RESET from the menu is the reset button" % name,
              len(menu_rows) == 150 and menu_rows == word_rows,
              "%d and %d frames, first different: %s" % (
                  len(menu_rows), len(word_rows),
                  next((i + 1 for i, (p, q) in enumerate(zip(menu_rows, word_rows)) if p != q), "-")))

        # Slot 2 picked, then SAVE: .state2, not .state1.
        files = os.path.join(OUT, name + ".slot")
        run(exe, rom, ["40 menu down down down right up up ok"], base, 60, name + ".slot", files)
        check("%s: SAVE after picking slot 2 writes slot 2" % name,
              os.path.exists(files + ".state2") and not os.path.exists(files + ".state1"),
              "state1 %s, state2 %s" % (os.path.exists(files + ".state1"),
                                       os.path.exists(files + ".state2")))
        sound_and_window(exe, rom, base, name, L, fnt)
        controllers(exe, rom, base, name, L, fnt)
    print("\nall menu checks pass" if not failures else "\n%d menu check(s) failed" % failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
