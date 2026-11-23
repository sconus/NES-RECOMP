#!/usr/bin/env python3
"""The keys say the same everywhere (PLAN-keys.md step 2): the window's
own keys, as runtime/video_sdl.c answers them, against the pause menu's
ALL KEYS page (runtime/menu.c's window_keys table), the README's tables
and the app's cards (app/app.c), so a key added later can't be left off
one of them.

For each of the window's keys, this check knows: the names it has in
video_sdl.c, its name on the page (the Mac's; Windows' is the same with
CTRL for CMD and BKSPACE for DELETE), what the README says for it, and
its name on a card (or none: the window's size and the disk's keys
aren't on the cards). Then:
  - every key video_sdl.c names is one of these, or one of the menu's
    own moves (the arrows, Return, Space, X, Z inside the menu);
  - every one of these is still in video_sdl.c;
  - the page lists exactly these, with both systems' names;
  - the README mentions each;
  - the cards have each that should be on one.

    python3 tests/check_keys.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# (video_sdl.c's names for it, the page's (Mac's) name, the README's
# words for it, the card's name or None)
WINDOW = [
    (["SDLK_ESCAPE"], "ESC", "| Escape |", "ESC"),
    (["SDLK_m"], "M", "| M |", "M"),
    (["SDLK_r"], "R", "| R |", "R"),
    (["SDLK_v"], "V", "| V |", "V"),
    (["SDLK_p"], "P", "| P |", "P"),
    (["SDLK_s"], "CMD+S", "| Cmd+S |", "CMD+S"),
    (["SDLK_l"], "CMD+L", "| Cmd+L |", "CMD+L"),
    (["SDLK_1", "SDLK_4"], "CMD+1-4", "| Cmd+1 to Cmd+4 |", "CMD+1-4"),
    (["SDL_SCANCODE_BACKSPACE"], "DELETE", "| Backspace (held", "DELETE"),
    (["SDL_SCANCODE_GRAVE", "SDL_SCANCODE_NONUSBACKSLASH"], "LEFT OF 1", "the key left of 1", "` KEY"),
    (["SDLK_EQUALS", "SDLK_PLUS", "SDLK_KP_PLUS", "SDLK_MINUS", "SDLK_KP_MINUS"], "CMD+= / -",
     "Cmd+= and Cmd+-", None),
    (["SDLK_f"], "CMD+F", "Cmd+F makes it full screen", None),
    (["SDLK_9"], "1-9", "| 1-9 |", None),
    (["SDLK_0"], "0", "0 takes the disk out", None),
]
MENU_MOVES = {"SDLK_UP", "SDLK_DOWN", "SDLK_LEFT", "SDLK_RIGHT", "SDLK_RETURN", "SDLK_KP_ENTER",
              "SDLK_SPACE", "SDLK_x", "SDLK_z"}
fails = []


def check(what, ok, why=""):
    print(("ok    " if ok else "FAIL  ") + what + ("" if ok else ": " + why))
    if not ok:
        fails.append(what)


def windows_name(mac):
    return mac.replace("CMD", "CTRL").replace("DELETE", "BKSPACE")


def main():
    sdl = open(os.path.join(ROOT, "runtime", "video_sdl.c")).read()
    menu = open(os.path.join(ROOT, "runtime", "menu.c")).read()
    readme = open(os.path.join(ROOT, "README.md")).read()
    app = open(os.path.join(ROOT, "app", "app.c")).read()

    named = set(re.findall(r"\b(SDLK_\w+|SDL_SCANCODE_\w+)\b", sdl))
    known = {n for names, *_ in WINDOW for n in names}
    check("every key the game's window answers to is one this check knows (%d)" % len(named),
          named <= known | MENU_MOVES, "unknown: %s" % sorted(named - known - MENU_MOVES))
    check("and every key this check knows is still answered to (%d)" % len(WINDOW),
          known <= named, "gone: %s" % sorted(known - named))

    body = menu.split("window_keys[] = {", 1)[1].split("};", 1)[0]
    page = re.findall(r'\{ "([^"]*)", "([^"]*)", "([^"]*)" \}', body)
    want = [mac for _, mac, _, _ in WINDOW]
    check("the ALL KEYS page lists exactly these keys, in order",
          [m for m, _, _ in page] == want, "%s" % [m for m, _, _ in page])
    wrong = [(m, w) for m, w, _ in page if w != windows_name(m)]
    check("...with Windows' names (Ctrl for Cmd, Bkspace for Delete)", not wrong, "%s" % wrong)

    missing = [words for _, _, words, _ in WINDOW if words not in readme]
    check("the README mentions each of them", not missing, "missing %s" % missing)

    cards = ""
    for name in ("card_game", "card_states"):
        cards += app.split("static const char *const %s[][2] = {" % name, 1)[1].split("};", 1)[0]
    mac_cards = re.sub(r"#ifdef _WIN32.*?#else", "", cards, flags=re.S)      # the Mac's lines
    on_cards = re.findall(r'\{ "([^"]*)", "[^"]*" \}', mac_cards)
    missing = [card for _, _, _, card in WINDOW if card and card not in on_cards]
    check("the app's cards have each of them that belongs on one (all but the window's size and the "
          "disk's keys)", not missing, "missing %s" % missing)
    win_cards = re.sub(r"#else.*?#endif", "", cards, flags=re.S)
    on_win = re.findall(r'\{ "([^"]*)", "[^"]*" \}', win_cards)
    missing = [windows_name(card).replace("DELETE", "BKSPACE") for _, _, _, card in WINDOW
               if card and windows_name(card) not in on_win]
    check("...on Windows too (Ctrl, Bkspace)", not missing, "missing %s" % missing)

    print("\n%s" % ("all key checks pass" if not fails else "%d key check(s) failed" % len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
