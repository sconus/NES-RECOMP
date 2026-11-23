# Plan: releasing NES RECOMP 2.1

Goal: everything since v2.0 (2026-11-18, tag on 214391a) on the GitHub
Releases page, for the Mac and for Windows, as v2.0 was: two zips made
on this Mac, checked here and on GitHub's Windows machines, tried by you
on real machines, then published on your go-ahead.

What's new since 2.0:
- 9 more mappers from your own games: 71, 79, 41, 228, 172, 112, 119,
  16 (with its EEPROM save), 68 (`PLAN-mappers3.md`);
- save states in 4 slots, rewind (Backspace) and fast-forward (the key
  left of 1) (`PLAN-savestates.md`);
- the pause menu: save, load, slot, reset, sound, window size, quit,
  from the keyboard or a pad (`PLAN-pause.md`);
- the Controllers page: a button test, changing keys and pad buttons,
  pairing help (`PLAN-controllers.md`);
- the library: the living room, the shelf of your games with their
  title screens, playing from a box, missing ROMs, removing
  (`PLAN-library.md`);
- ALL KEYS in the pause menu, K for the cards (`PLAN-keys.md`).

At every step:
- `make test-all` as before (230 of 231, test28 the known failure), the
  same C;
- deliberate breaks for anything new (the release checks);
- nothing published, tagged or pushed beyond main without your words
  for it.

## Decisions for you (my recommendation first)

1. **The number.** **2.1** (recommended, your name for it): the same
   app, grown. The other choice: **3.0**, as the library changes the
   app's first screen and much was added; either works, the number is
   in one place.
2. **Who publishes.** **You, on github.com** (recommended): I make the
   two zips and write the notes in a file; you open the Releases page,
   make the release from the tag, paste the notes and drop the two
   zips (the same as 2.0). The other choice: I do it in the browser
   pane, where you're signed in, once you say so; the zips' upload may
   still need your hand there.
3. **Testing on real machines first.** **Yes** (recommended): the Mac
   zip opened as someone new would (Open Anyway), and the Windows zip
   in your Boot Camp Windows, with a short list to try (below). The
   other choice: publish on the checks alone; quicker, but the shelf,
   ALL KEYS and a real pad haven't been tried on Windows by a person.

## The hard part, and the answer

**A new version builds every game again, once.** Each build's record
(`NAME.stamp`) holds the app's version, so after 2.1 the first play of
each game builds it again (a few seconds), then never again. The shelf
still finds every game already built (from those records, and from
`library.txt`), so nobody's shelf comes up empty. The notes say so.

**The version is in one place,** `APP_VERSION` in `app/build.h`: the
app's `--version`, the Mac bundle's Info.plist, the Windows program's
version, both zips' names and both READ ME FIRSTs come from it, and
their checks read it from there. The README names the zips (2.0 today)
by hand; those lines change too.

**A green Windows run first.** Runs 59 to 61 (the library's end and ALL
KEYS) were still running when this plan was written; the release is
made from a commit whose Windows run is green, and step 1 checks it.

## What you'd try (step 2)

On the Mac, from the zip:
- Open Anyway the first time; the room and the shelf (your games
  already built appear on it);
- drop a ROM; play it, press Start on its title: its box gets the
  picture; pick it with the arrows and the mouse, Enter, a click;
- move a ROM: its box dims; drop it again; Delete a game, Y and N, Esc;
- K for the cards; in a game, Esc, ALL KEYS (both pages), CONTROLLERS;
  save, load, rewind, fast-forward; a pad if you have one at hand.
On Windows (Boot Camp), from the zip: the same, plus SmartScreen's
"Run anyway", and your Xbox pad.

## Steps

### 1. Version 2.1, the zips, the notes
- Check the Windows runs since 2.0's last (59, 60, 61) are green; if
  not, read why and fix first.
- `APP_VERSION` 2.1; the README's zip names.
- `make release` and `make release-windows`: both zips; `make
  test-release`, `test-release-windows`, `test-app-bundle`,
  `test-standalone`, and `make test-all`.
- The release notes, in `build/RELEASE-NOTES-2.1.md` (what's new, for
  each system, the one-time rebuild, how to open it the first time),
  for you to read.
- Breaks: the bundle's version not the app's; a zip named for the old
  version; a READ ME FIRST with the old version.
- Commit on "Commit and push"; its Windows run is the one the release
  is made from, and must be green.

**Where step 1 ended (2026-11-22).** The three decisions as
recommended (2.1; you publish; a try on real machines first).
- Windows runs: 59 (the library's end) green; 60 and 61 (ALL KEYS) had
  passed every step but their last, the breaks, still running: look
  again before the commit.
- `APP_VERSION` is 2.1 (`app/build.h`); the README's three zip names.
- The zips: `build/NES-RECOMP-2.1-mac.zip` (2.5 MB) and
  `build/NES-RECOMP-2.1-windows.zip` (72.9 MB), made on this Mac.
- The release notes: `build/RELEASE-NOTES-2.1.md` (what's new, the
  one-time rebuild, each system's download and first opening, the
  support link), for you to read and change.
- `tests/check_release.py` and `tests/check_release_windows.py`: a zip
  named for another version is now a FAIL line, not a stop (the break
  below found it stopping with no FAIL line).

The checks: `make test-release`, `test-app-bundle`, `test-standalone`,
`test-release-windows`, all pass (104 "ok" lines); `make test-all` 230
of 231 as before (test28), 240 of 240; the same C.

Breaks, each in a scratch copy:

| broken | caught by |
| --- | --- |
| the Mac zip named for 2.0 | `make test-release`, 1 FAIL (0 at first: it stopped with "make release first"; now a FAIL line) |
| the Mac READ ME FIRST saying 2.0 | `make test-release`, 1 |
| the bundle's Info.plist saying 2.0 | `make test-app-bundle`, 1 |

### 2. Your try on real machines
- The list above, on the Mac and in Boot Camp, with the zips from
  step 1. Anything you find is fixed here, with a check where one can
  be written, and the zips made again.

### 3. Publishing
- On your go-ahead only: the tag `v2.1` on the release commit, pushed;
  the GitHub release "NES RECOMP 2.1" with both zips and the notes
  (decision 2).
- After: the README's Releases link already points at the latest; the
  memory notes and `PLAN-release-2.1.md` say where it ended.

## Not in this plan
- Notarizing the Mac app (the Apple Developer Program): Open Anyway
  stays, as in 2.0.
- Signing the Windows program: SmartScreen's "Run anyway" stays.
- Retiring `recomp.py`.

## Risks
- **The Windows zip is 70 MB or more** (Zig comes with it, as in 2.0);
  GitHub takes files up to 2 GB, so it's only slow to upload.
- **Something found in step 2** means step 1's zips are made again;
  that's what step 2 is for.
- **Keystrokes landing in Windows' search** while playing (seen in 2.0,
  most likely the Windows key) is still open; the notes can mention it.
