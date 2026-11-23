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
- KEYBOARD 1 and 2 (PLAN-controllers.md step 3), pixel by pixel: as
  it opens, waiting for a key, a key the window keeps refused, a clash
  swapped, Esc and 5 seconds of nothing keeping the old key; the
  terminal says each; the --controls file written as changed, DEFAULTS
  bringing the usual keys back (and the other player's key that
  clashed), a garbled file giving the usual keys; and a run with the
  changed file playing the same frames as without it.
- PADS (PLAN-controllers.md step 4), pixel by pixel: as it opens,
  waiting for a pad button, a button held as it started not taken, a
  shoulder refused, a clash swapped, Esc and 5 seconds keeping the old
  one, and the button test lighting by the new layout; the terminal
  says each; the file written as changed and read back by a new run;
  DEFAULTS; a file giving A the Home button; the game unmoved.
- PAIRING HELP (PLAN-controllers.md step 2): its list and each page of
  steps, pixel by pixel, for the Mac and for Windows (--pairing-for);
  without the option, the system this runs on; every page fits its box;
  the terminal names each page; and the game doesn't move meanwhile.

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
         re.findall(r"#define ((?:MENU|INK|TEST|CTRL|PAIR|KEYS|ALLKEYS)_\w+) (0x[0-9A-F]+|\d+)", src)}
    d["pages"] = {name: re.findall(r'"((?:[^"\\]|\\.)*)"', body) for name, body in
                  re.findall(r"static const char \*const (pair_\w+)\[\] = \{(.*?)NULL,\n\};",
                             src, re.S)}
    d["pair_names"] = re.findall(r'"([^"]*)"', src.split("pair_names[PAIR_COUNT] = {", 1)[1]
                                 .split("};", 1)[0])
    d["PAIR_FOOT"] = re.search(r'#define PAIR_FOOT "([^"]*)"', src).group(1)
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
             "SOUND < %s >" % sound, "WINDOW < %s >" % window, "CONTROLLERS", "ALL KEYS", "QUIT"]
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
    for i, item in enumerate(["BUTTON TEST", "KEYBOARD 1", "KEYBOARD 2", "PADS", "PAIRING HELP", "BACK"]):
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


def expected_pairing(L, fnt, title, cursor):
    """The PAIRING HELP list, in the menu's box."""
    want = {}
    frame_box(want, L, L["MENU_BOX_X"], L["MENU_BOX_Y"], L["MENU_BOX_W"], L["MENU_BOX_H"])
    centred(want, fnt, title, L["MENU_TITLE_Y"], L["INK_TITLE"])
    for i, item in enumerate(L["pair_names"]):
        for p in text_pixels(fnt, item, L["MENU_ITEM_X"], L["MENU_ITEM_Y"] + i * L["MENU_LINE_H"]):
            want[p] = L["INK_PICKED"] if i == cursor else L["INK_ITEM"]
    for p in text_pixels(fnt, ">", L["MENU_CURSOR_X"], L["MENU_ITEM_Y"] + cursor * L["MENU_LINE_H"]):
        want[p] = L["INK_CURSOR"]
    return want


def expected_pair_text(L, fnt, page):
    """A page of steps: its title, then its lines, in the bigger box."""
    want = {}
    frame_box(want, L, L["TEST_BOX_X"], L["TEST_BOX_Y"], L["TEST_BOX_W"], L["TEST_BOX_H"])
    centred(want, fnt, page[0], L["TEST_TITLE_Y"], L["INK_TITLE"])
    for i, line in enumerate(page[1:]):
        for p in text_pixels(fnt, line, L["PAIR_LINE_X"], L["PAIR_LINE_Y"] + i * L["PAIR_LINE_H"]):
            want[p] = L["INK_ITEM"]
    centred(want, fnt, L["PAIR_FOOT"], L["TEST_FOOT_Y"], L["INK_ITEM"])
    return want


PAIR_PAGES = {"mac": ["pair_mac_xbox", "pair_mac_ps", "pair_mac_switch", "pair_console"],
              "windows": ["pair_win_xbox", "pair_win_ps", "pair_win_switch", "pair_console"]}


def pairing_fits(L):
    """Every page's lines fit the box, above its footer (checked once)."""
    bad = []
    for name, page in L["pages"].items():
        long = [ln for ln in page[1:] if len(ln) > L["PAIR_CHARS"]]
        if long or len(page) - 1 > L["PAIR_LINES"] or len(page[0]) * 6 > L["TEST_BOX_W"]:
            bad.append("%s: %d lines, too long: %r" % (name, len(page) - 1, long))
    last_y = L["PAIR_LINE_Y"] + (L["PAIR_LINES"] - 1) * L["PAIR_LINE_H"] + 7
    if L["PAIR_LINE_X"] + L["PAIR_CHARS"] * 6 - 1 > L["TEST_BOX_X"] + L["TEST_BOX_W"] - 4:
        bad.append("PAIR_CHARS wider than the box")
    if last_y >= L["TEST_FOOT_Y"] - 2:
        bad.append("PAIR_LINES runs into the footer")
    check("pairing help: every page fits its box (%d pages)" % len(L["pages"]),
          not bad and len(L["pages"]) == 7, "; ".join(bad) or "%d pages" % len(L["pages"]))


def pairing(exe, rom, base, name, L, fnt):
    here = "windows" if sys.platform == "win32" else "mac"
    for system in ("mac", "windows", None):
        tag = "%s.pair_%s" % (name, system or "default")
        pics = [os.path.join(OUT, "%s.%d.raw" % (tag, k)) for k in range(5)]
        keys = ["up up up ok down down down down ok",  # CONTROLLERS, PAIRING HELP
                "shot=%s ok shot=%s back" % (pics[0], pics[1]),   # the list, XBOX
                "down ok shot=%s leave" % pics[2],  # PLAYSTATION (Esc goes back)
                "down ok shot=%s ok" % pics[3],     # SWITCH PRO (OK goes back too)
                "down ok shot=%s back" % pics[4],   # ON A CONSOLE TOO?
                "down ok",                          # BACK: to CONTROLLERS
                "back back"]
        extra = ["--pairing-for", system] if system else []
        err, rows = run(exe, rom, ["60 menu " + " ".join(keys)], base, 90, tag,
                        os.path.join(OUT, tag), extra)
        shown = system or here
        title = "PAIRING HELP (%s)" % shown.upper()
        pages = [L["pages"][p] for p in PAIR_PAGES[shown]]
        what = system or "no --pairing-for, on %s" % here
        why = picture_ok(pics[0], expected_pairing(L, fnt, title, 0))
        why = why and "the list: " + why
        for k, page in enumerate(pages):
            if not why:
                why = picture_ok(pics[k + 1], expected_pair_text(L, fnt, page))
                why = why and "%s: %s" % (page[0], why)
        check("%s: pairing help (%s): the list and its four pages" % (name, what), not why, why or "")
        said = [ln[len("frame 60: "):] for ln in err.splitlines() if ln.startswith("frame 60:")]
        want = (["MENU", "CONTROLLERS", title] +
                [x for page in pages for x in (page[0], title)] +
                ["CONTROLLERS", "MENU", "MENU CLOSED (RESUME)"])
        check("%s: pairing help (%s): the terminal names each page" % (name, what),
              said == want, repr(said))
        if system is None:
            _, plain = run(exe, rom, [], base, 90, name + ".pairplain", os.path.join(OUT, name + ".pp"))
            check("%s: the pairing pages don't move the game" % name,
                  len(rows) == 90 and rows == plain, "%d frames, differ from the plain run" % len(rows))


BUTTONS = ["UP", "DOWN", "LEFT", "RIGHT", "B", "A", "SELECT", "START"]
USUAL = [["UP", "DOWN", "LEFT", "RIGHT", "Z", "X", "RIGHT SHIFT", "RETURN"],
         ["W", "S", "A", "D", "F", "G", "Q", "E"]]
USUAL_FILE = [["Up", "Down", "Left", "Right", "Z", "X", "Right Shift", "Return"],
              ["W", "S", "A", "D", "F", "G", "Q", "E"]]


# The pads' usual layout: as the PADS page shows it, and as the file says.
USUAL_PAD = ["D-PAD UP", "D-PAD DOWN", "D-PAD LEFT", "D-PAD RIGHT", "BOTTOM BUTTON", "RIGHT BUTTON",
             "SELECT", "START"]
USUAL_PAD_FILE = ["dpad_up", "dpad_down", "dpad_left", "dpad_right", "bottom", "right", "select", "start"]


def controls_text(names, pads=USUAL_PAD_FILE):
    """controls.txt as the game writes it, for these keys (SDL's names)
    and pad buttons (the file's names)."""
    return ("# nesrecomp's keys and pad buttons (the pause menu's CONTROLLERS writes this):\n"
            "# keyboard 1 or 2 or the pads, NES button, the key as SDL names it\n"
            "# or the pad button by position\nversion 2\n" +
            "".join("keyboard%d %s %s\n" % (p + 1, b.lower(), names[p][i])
                    for p in range(2) for i, b in enumerate(BUTTONS)) +
            "".join("pad %s %s\n" % (b.lower(), pads[i]) for i, b in enumerate(BUTTONS)))


def expected_keys(L, fnt, player, cursor, names, waiting=False, status=""):
    """A KEYBOARD page (player 1 or 2), or PADS (player 0): names are its
    eight keys or pad buttons as shown."""
    want = {}
    frame_box(want, L, L["MENU_BOX_X"], L["MENU_BOX_Y"], L["MENU_BOX_W"], L["MENU_BOX_H"])
    centred(want, fnt, "KEYBOARD %d" % player if player else "PADS", L["MENU_TITLE_Y"], L["INK_TITLE"])
    for i, item in enumerate(BUTTONS + ["DEFAULTS", "BACK"]):
        y = L["MENU_ITEM_Y"] + i * L["KEYS_LINE_H"]
        ink = L["INK_PICKED"] if i == cursor else L["INK_ITEM"]
        for p in text_pixels(fnt, item, L["MENU_ITEM_X"], y):
            want[p] = ink
        if i < 8:
            key, kink = ("...", L["INK_CURSOR"]) if waiting and i == cursor else \
                (names[i][:L["KEYS_KEY_CHARS"]], ink)
            for p in text_pixels(fnt, key, L["KEYS_KEY_X"], y):
                want[p] = kink
    for p in text_pixels(fnt, ">", L["MENU_CURSOR_X"], L["MENU_ITEM_Y"] + cursor * L["KEYS_LINE_H"]):
        want[p] = L["INK_CURSOR"]
    centred(want, fnt, status, L["KEYS_STATUS_Y"], L["INK_ITEM"])
    return want


def keyboards(exe, rom, base, name, L, fnt):
    ctl = os.path.join(OUT, name + ".controls.txt")
    if os.path.exists(ctl):
        os.remove(ctl)
    pics = {k: os.path.join(OUT, "%s.keys.%s.raw" % (name, k))
            for k in ("open", "wait", "refused", "swapped", "cancel", "almost", "timeout", "k2")}
    keys = ["up up up ok down ok",                 # CONTROLLERS, KEYBOARD 1
            "shot=%s" % pics["open"],
            "ok shot=%s" % pics["wait"],        # UP: waiting for a key
            "key=m shot=%s" % pics["refused"],  # the window's: still waiting
            "key=w shot=%s" % pics["swapped"],  # keyboard 2's UP: swapped
            "down down down down down ok leave shot=%s" % pics["cancel"],     # A, then Esc
            "ok wait=299 shot=%s" % pics["almost"],                           # not yet
            "wait=1 shot=%s" % pics["timeout"],                               # 5 s of nothing
            "ok key=k",                         # A is K
            "back down ok shot=%s" % pics["k2"],                              # KEYBOARD 2
            "back back back"]
    err, _ = run(exe, rom, ["60 menu " + " ".join(keys)], base, 90, name + ".keys",
                 os.path.join(OUT, name + ".keys"), ["--controls", ctl])
    p1 = list(USUAL[0])
    p1[0] = "W"
    wants = {"open": expected_keys(L, fnt, 1, 0, USUAL[0]),
             "wait": expected_keys(L, fnt, 1, 0, USUAL[0], True, "PRESS A KEY (ESC: CANCEL)"),
             "refused": expected_keys(L, fnt, 1, 0, USUAL[0], True, "THE WINDOW USES THAT KEY"),
             "swapped": expected_keys(L, fnt, 1, 0, p1, False, "SWAPPED WITH KEYBOARD 2 UP"),
             "cancel": expected_keys(L, fnt, 1, 5, p1, False, "KEPT AS IT WAS"),
             "almost": expected_keys(L, fnt, 1, 5, p1, True, "PRESS A KEY (ESC: CANCEL)"),
             "timeout": expected_keys(L, fnt, 1, 5, p1, False, "NO KEY: KEPT AS IT WAS"),
             "k2": expected_keys(L, fnt, 2, 0, ["UP"] + USUAL[1][1:])}
    why = None
    for k, want in wants.items():
        why = picture_ok(pics[k], want)
        if why:
            why = "%s: %s" % (k, why)
            break
    check("%s: KEYBOARD pages: opened, waiting, refused, swapped, Esc, 4.98 s, 5 s, keyboard 2" % name,
          not why, why or "")
    said = [ln for ln in err.splitlines() if ln.startswith(("keyboard ", "controls: "))]
    check("%s: KEYBOARD pages: the terminal says each" % name, said == [
        "controls: %s not there yet: the usual keys" % ctl,
        "keyboard 1: press a key for UP", "keyboard 1: M is the window's",
        "keyboard 1: UP is now W (swapped: keyboard 2 UP is now UP)",
        "keyboard 1: press a key for A", "keyboard 1: A kept as X",
        "keyboard 1: press a key for A", "keyboard 1: A kept as X (no key in 5 seconds)",
        "keyboard 1: press a key for A", "keyboard 1: A is now K"], repr(said))
    changed = [list(USUAL_FILE[0]), list(USUAL_FILE[1])]
    changed[0][0], changed[0][5], changed[1][0] = "W", "K", "Up"
    got = open(ctl).read() if os.path.exists(ctl) else ""
    check("%s: KEYBOARD pages: --controls written as changed" % name,
          got == controls_text(changed), repr(got[-200:]))

    # The changed keys change nothing in the game (only the window reads them).
    _, rows = run(exe, rom, [], base, 90, name + ".keysplay", os.path.join(OUT, name + ".kp"),
                  ["--controls", ctl])
    _, plain = run(exe, rom, [], base, 90, name + ".keysplain", os.path.join(OUT, name + ".kq"))
    after = open(ctl).read() if os.path.exists(ctl) else ""
    check("%s: changed keys play the same frames, and the file is only read" % name,
          len(rows) == 90 and rows == plain and after == got,
          "%d frames, %s" % (len(rows), "same file" if after == got else "file changed"))

    # DEFAULTS on keyboard 1: its keys, and keyboard 2's UP (it had Up).
    err, _ = run(exe, rom, ["60 menu up up up ok down ok " + "down " * 8 + "ok back back back"], base, 70,
                 name + ".keysdef", os.path.join(OUT, name + ".kd"), ["--controls", ctl])
    got = open(ctl).read() if os.path.exists(ctl) else ""
    check("%s: DEFAULTS: the usual keys, and keyboard 2's UP back on W" % name,
          got == controls_text(USUAL_FILE) and "keyboard 1: the usual keys" in err, repr(got[-200:]))

    # A garbled file: the usual keys, said, and the page shows them.
    with open(ctl, "w") as f:
        f.write("version 1\nkeyboard1 a\x01\x02 nonsense\n")
    pic = os.path.join(OUT, name + ".keys.garbled.raw")
    err, rows = run(exe, rom, ["60 menu up up up ok down ok shot=%s back back back" % pic], base, 90,
                    name + ".keysbad", os.path.join(OUT, name + ".kb"), ["--controls", ctl])
    why = picture_ok(pic, expected_keys(L, fnt, 1, 0, USUAL[0]))
    check("%s: a garbled --controls file: the usual keys, said" % name,
          not why and "controls: %s line 2 not understood: the usual keys" % ctl in err
          and len(rows) == 90, why or err[-200:])


def pads(exe, rom, base, name, L, fnt):
    """The PADS page (PLAN-controllers.md step 4), with a virtual pad in
    slot 1; pad= names places on it (b the bottom face button, a the
    right, y the top)."""
    ctl = os.path.join(OUT, name + ".padctl.txt")
    if os.path.exists(ctl):
        os.remove(ctl)
    pics = {k: os.path.join(OUT, "%s.pads.%s.raw" % (name, k))
            for k in ("open", "wait", "held", "refused", "swapped", "cancel", "timeout", "test")}
    keys = ["up up up ok down down down ok",       # CONTROLLERS, PADS
            "pad=1:none shot=%s" % pics["open"],
            "down down down down down pad=1:y ok shot=%s" % pics["wait"],   # A, top held
            "pad=1:y shot=%s" % pics["held"],   # held since before: not the answer
            "pad=1:rb shot=%s" % pics["refused"],                           # a shoulder
            "pad=1:none pad=1:b shot=%s" % pics["swapped"],                 # bottom: B's
            "ok leave shot=%s" % pics["cancel"],                            # Esc
            "ok wait=300 shot=%s" % pics["timeout"],                        # 5 s
            "up ok pad=1:y",                    # B on the top button
            "back up up up ok",                 # the button test, with that layout
            "pad=1:none pad=1:y+b+a shot=%s" % pics["test"],
            "leave back back"]
    err, rows = run(exe, rom, ["60 menu " + " ".join(keys)], base, 90, name + ".pads",
                    os.path.join(OUT, name + ".pads"), ["--controls", ctl])
    swapped = list(USUAL_PAD)
    swapped[4], swapped[5] = "RIGHT BUTTON", "BOTTOM BUTTON"
    waiting = "PRESS A BUTTON (HOME: CANCEL)"
    wants = {"open": expected_keys(L, fnt, 0, 0, USUAL_PAD),
             "wait": expected_keys(L, fnt, 0, 5, USUAL_PAD, True, waiting),
             "held": expected_keys(L, fnt, 0, 5, USUAL_PAD, True, waiting),
             "refused": expected_keys(L, fnt, 0, 5, USUAL_PAD, True, "THAT BUTTON STAYS AS IT IS"),
             "swapped": expected_keys(L, fnt, 0, 5, swapped, False, "SWAPPED WITH B"),
             "cancel": expected_keys(L, fnt, 0, 5, swapped, False, "KEPT AS IT WAS"),
             "timeout": expected_keys(L, fnt, 0, 5, swapped, False, "NO BUTTON: KEPT AS IT WAS"),
             "test": expected_test(L, fnt, [("1 VIRTUAL", ("A", "B")), None, None, None,
                                            ("KEYBOARD 1", ()), ("KEYBOARD 2", ())])}
    why = None
    for k, want in wants.items():
        why = picture_ok(pics[k], want)
        if why:
            why = "%s: %s" % (k, why)
            break
    check("%s: PADS: opened, waiting, held, refused, swapped, Esc, 5 s, the button test after" % name,
          not why, why or "")
    said = [ln for ln in err.splitlines() if ln.startswith(("pads: ", "controls: "))]
    check("%s: PADS: the terminal says each" % name, said == [
        "controls: %s not there yet: the usual keys" % ctl,
        "pads: press a button for A", "pads: RIGHT SHOULDER stays as it is",
        "pads: A is now BOTTOM BUTTON (swapped: B is now RIGHT BUTTON)",
        "pads: press a button for A", "pads: A kept as BOTTOM BUTTON",
        "pads: press a button for A", "pads: A kept as BOTTOM BUTTON (no button in 5 seconds)",
        "pads: press a button for B", "pads: B is now TOP BUTTON"], repr(said))
    changed = list(USUAL_PAD_FILE)
    changed[4], changed[5] = "top", "bottom"
    got = open(ctl).read() if os.path.exists(ctl) else ""
    check("%s: PADS: --controls written as changed" % name,
          got == controls_text(USUAL_FILE, changed), repr(got[-200:]))
    # Read back by a new run: the PADS page shows the changed layout.
    pic = os.path.join(OUT, name + ".pads.again.raw")
    run(exe, rom, ["60 menu up up up ok down down down ok shot=%s back back back" % pic], base, 70,
        name + ".padsagain", os.path.join(OUT, name + ".pa"), ["--controls", ctl])
    again = list(USUAL_PAD)
    again[4], again[5] = "TOP BUTTON", "BOTTOM BUTTON"
    why = picture_ok(pic, expected_keys(L, fnt, 0, 0, again))
    check("%s: PADS: the changed file read back by a new run" % name, not why, why or "")
    _, plain = run(exe, rom, [], base, 90, name + ".padsplain", os.path.join(OUT, name + ".pp"))
    check("%s: the PADS page doesn't move the game" % name,
          len(rows) == 90 and rows == plain, "%d frames, differ from the plain run" % len(rows))

    # DEFAULTS: the usual pad, the keys left as they are.
    err, _ = run(exe, rom, ["60 menu up up up ok down down down ok " + "down " * 8 + "ok back back back"],
                 base, 70, name + ".padsdef", os.path.join(OUT, name + ".pd"), ["--controls", ctl])
    got = open(ctl).read() if os.path.exists(ctl) else ""
    check("%s: PADS DEFAULTS: the usual pad" % name,
          got == controls_text(USUAL_FILE) and "pads: the usual buttons" in err, repr(got[-200:]))

    # A file giving A the Home button: the usual keys and pad, said.
    with open(ctl, "w") as f:
        f.write("version 2\npad a guide\n")
    pic = os.path.join(OUT, name + ".pads.bad.raw")
    err, _ = run(exe, rom, ["60 menu up up up ok down down down ok shot=%s back back back" % pic], base, 70,
                 name + ".padsbad", os.path.join(OUT, name + ".pb"), ["--controls", ctl])
    why = picture_ok(pic, expected_keys(L, fnt, 0, 0, USUAL_PAD))
    check("%s: a --controls file giving A the Home button: the usual pad, said" % name,
          not why and "controls: %s line 2 not understood: the usual keys" % ctl in err, why or err[-200:])


# ALL KEYS (PLAN-keys.md step 1): what each page must say, written here
# (not read from menu.c), so a key left off the page is caught.
ALLKEYS_FOOT = "< > THE OTHER PAGE    ESC: BACK"
WINDOW_KEYS = [("ESC", "THIS MENU"), ("M", "SOUND ON / OFF"), ("R", "RESET"),
               ("V", "RECORD A MOVIE, AND STOP"), ("P", "SAVE A PICTURE"),
               ("CMD+S", "SAVE A STATE IN THE SLOT"), ("CMD+L", "LOAD THE SLOT'S STATE"),
               ("CMD+1-4", "PICK THE SLOT"), ("DELETE", "REWIND (HELD)"), ("LEFT OF 1", "FAST X4 (HELD)"),
               ("CMD+= / -", "WINDOW BIGGER / SMALLER"), ("CMD+F", "FULL SCREEN"),
               ("1-9", "DISK SIDE (FDS GAMES)"), ("0", "EJECT THE DISK (FDS)")]
SHORT = {"RIGHT SHIFT": "R.SHIFT", "LEFT SHIFT": "L.SHIFT", "BACKSPACE": "BKSPACE"}
ALL_ORDER = ["UP", "DOWN", "LEFT", "RIGHT", "A", "B", "START", "SELECT"]


def window_keys(system):
    if system == "mac":
        return WINDOW_KEYS
    return [(k.replace("CMD", "CTRL").replace("DELETE", "BKSPACE"), d) for k, d in WINDOW_KEYS]


def pad_short(n):
    if n.endswith(" BUTTON"):
        return n[:-7]
    return n.replace("LEFT STICK", "L.STICK").replace("RIGHT STICK", "R.STICK")


def allkeys_lines(page, keys, pad_names, system):
    """ALL KEYS page 1 or 2: [(row, text, header?)]; keys[p][i] and
    pad_names[i] in BUTTONS order, as the KEYBOARD and PADS pages name them."""
    if page == 2:
        return [(i, "%-11s%s" % kd, False) for i, kd in enumerate(window_keys(system))]
    out = [(0, "         KEYBOARD 1   KEYBOARD 2", True)]
    for i, b in enumerate(ALL_ORDER):
        k = BUTTONS.index(b)
        out.append((1 + i, "%-9s%-13s%s" % (b, SHORT.get(keys[0][k], keys[0][k]), SHORT.get(keys[1][k], keys[1][k])),
                    False))
    out.append((10, "PADS", True))
    for j in range(0, 8, 2):
        b1, b2 = ALL_ORDER[j], ALL_ORDER[j + 1]
        out.append((11 + j // 2, "%-7s%-12s%-7s%s" % (b1, pad_short(pad_names[BUTTONS.index(b1)]), b2,
                                                      pad_short(pad_names[BUTTONS.index(b2)])), False))
    out += [(15, "SELECT+START HELD, OR HOME: MENU", False), (16, "LB: REWIND   RB: FAST X4", False)]
    return out


def expected_allkeys(L, fnt, page, keys=USUAL, pad_names=USUAL_PAD, system="mac"):
    want = {}
    frame_box(want, L, L["TEST_BOX_X"], L["TEST_BOX_Y"], L["TEST_BOX_W"], L["TEST_BOX_H"])
    centred(want, fnt, "ALL KEYS 2/2: THE WINDOW" if page == 2 else "ALL KEYS 1/2: THE GAME",
            L["TEST_TITLE_Y"], L["INK_TITLE"])
    for row, text, head in allkeys_lines(page, keys, pad_names, system):
        if len(text) > 37:
            want[("too long", text)] = 0
        for p in text_pixels(fnt, text, L["ALLKEYS_X"], L["ALLKEYS_Y"] + row * L["ALLKEYS_LINE_H"]):
            want[p] = L["INK_CURSOR"] if head else L["INK_ITEM"]
    centred(want, fnt, ALLKEYS_FOOT, L["TEST_FOOT_Y"], L["INK_ITEM"])
    return want


def allkeys(exe, rom, base, name, L, fnt):
    here = "windows" if sys.platform == "win32" else "mac"
    to_page = "down " * 8 + "ok"                    # ALL KEYS, the 9th line
    # The page on this system: 1, then OK and Right flip, Left back; leave
    # goes back to the menu; the game's frames as if never opened.
    pics = [os.path.join(OUT, "%s.allkeys.%d.raw" % (name, k)) for k in range(5)]
    err, rows = run(exe, rom, ["60 menu %s shot=%s ok shot=%s right shot=%s left shot=%s leave shot=%s back"
                               % ((to_page,) + tuple(pics))], base, 90, name + ".allkeys",
                    os.path.join(OUT, name + ".ak"))
    why = picture_ok(pics[0], expected_allkeys(L, fnt, 1, system=here)) or \
        picture_ok(pics[1], expected_allkeys(L, fnt, 2, system=here)) or \
        picture_ok(pics[2], expected_allkeys(L, fnt, 1, system=here)) or \
        picture_ok(pics[3], expected_allkeys(L, fnt, 2, system=here))
    check("%s: ALL KEYS: page 1 (the game), OK and Right flip to page 2 (the window) and back, "
          "pixel by pixel (%s)" % (name, here), not why, why or "")
    why = picture_ok(pics[4], expected_box(L, fnt, 8, 1, "EMPTY"))
    check("%s: ALL KEYS: leave goes back to the menu, ALL KEYS still picked" % name, not why, why or "")
    said = [ln[len("frame 60: "):] for ln in err.splitlines() if ln.startswith("frame 60:")]
    want = ["MENU", "ALL KEYS 1/2", "ALL KEYS 2/2", "ALL KEYS 1/2", "ALL KEYS 2/2", "MENU",
            "MENU CLOSED (RESUME)"]
    check("%s: ALL KEYS: the terminal names each page; leave goes back to the menu" % name,
          said == want, repr(said))
    _, plain = run(exe, rom, [], base, 90, name + ".akplain", os.path.join(OUT, name + ".akp"))
    check("%s: ALL KEYS doesn't move the game" % name, len(rows) == 90 and rows == plain,
          "%d frames, differ from the plain run" % len(rows))
    # Both systems' names for the window's keys.
    for system in ("mac", "windows"):
        pic = os.path.join(OUT, "%s.allkeys.%s.raw" % (name, system))
        run(exe, rom, ["60 menu %s right shot=%s back back" % (to_page, pic)], base, 70,
            "%s.allkeys_%s" % (name, system), os.path.join(OUT, name + ".ak" + system),
            ["--pairing-for", system])
        why = picture_ok(pic, expected_allkeys(L, fnt, 2, system=system))
        check("%s: ALL KEYS page 2 for %s (%s)" % (name, system, "CMD, DELETE" if system == "mac" else
                                                    "CTRL, BKSPACE"), not why, why or "")
    # Keys moved (A to K on keyboard 1, the pads' A to the top button):
    # page 1 shows them; back (Z) goes back too.
    ctl = os.path.join(OUT, name + ".allkeys.controls.txt")
    moved = [list(USUAL_FILE[0]), list(USUAL_FILE[1])]
    moved[0][BUTTONS.index("A")] = "K"
    pads_ = list(USUAL_PAD_FILE)
    pads_[BUTTONS.index("A")] = "top"
    open(ctl, "w").write(controls_text(moved, pads_))
    pic = os.path.join(OUT, "%s.allkeys.moved.raw" % name)
    err, _ = run(exe, rom, ["60 menu %s shot=%s back back" % (to_page, pic)], base, 70,
                 name + ".allkeys_moved", os.path.join(OUT, name + ".akm"), ["--controls", ctl])
    shown = [list(USUAL[0]), list(USUAL[1])]
    shown[0][BUTTONS.index("A")] = "K"
    pad_shown = list(USUAL_PAD)
    pad_shown[BUTTONS.index("A")] = "TOP BUTTON"
    why = picture_ok(pic, expected_allkeys(L, fnt, 1, shown, pad_shown, here))
    said = [ln[len("frame 60: "):] for ln in err.splitlines() if ln.startswith("frame 60:")]
    check("%s: ALL KEYS shows the keys as they are now (A on K, the pads' A on TOP); Z goes back" % name,
          not why and said[-2:] == ["MENU", "MENU CLOSED (RESUME)"], why or repr(said))


def controllers(exe, rom, base, name, L, fnt):
    files = os.path.join(OUT, name + ".ctrl")
    page, test, held, after = (os.path.join(OUT, name + x + ".raw")
                               for x in (".ctrl", ".test", ".held", ".after"))
    keys = ["up up up ok",                         # CONTROLLERS (above ALL KEYS, QUIT)
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
                   "controller 2: HOME", "frame 60: CONTROLLERS", "frame 60: MENU",
                   "frame 60: MENU CLOSED (RESUME)"],
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
    # A script line is words split at spaces, so a picture's path is given
    # from the project folder, where the game runs: the folder's own path
    # may have a space (the Windows run's scratch copies, "nesrecomp break
    # ...", do).
    script_lines = [l.replace("shot=" + ROOT + os.sep, "shot=") for l in script_lines]
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
    pairing_fits(L)
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
        allkeys(exe, rom, base, name, L, fnt)
        pairing(exe, rom, base, name, L, fnt)
        keyboards(exe, rom, base, name, L, fnt)
        pads(exe, rom, base, name, L, fnt)
    print("\nall menu checks pass" if not failures else "\n%d menu check(s) failed" % failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
