# Plan: the Zapper in the app, and with the keyboard

Goal: a light-gun game dropped on the app gets a Zapper, and it can be
aimed with the keyboard as well as the mouse.

## Where it is now

- The runtime has the Zapper (PLAN-zapper.md): `--port2 zapper`,
  `--port1 zapper` or `--famicom-zapper` plug it in, and it aims where
  the mouse points (the pointer becomes a cross), with the left button
  as the trigger.
- It's plugged in by itself only when the ROM has an NES 2.0 header
  that names it as the game's device (byte 15: `$08` Zapper in port 2,
  `$49` in port 1). Most ROM files have the older iNES header, which
  doesn't say, so a gun game dropped on the app gets a controller in
  port 2 instead, and the gun doesn't respond at all.

## Choices

- **Switching the Zapper on, in the app** (recommended): Tab, while
  the game plays, switches port 2 between controller 2 and the Zapper,
  with a short note on screen ("ZAPPER IN PORT 2"). The app remembers
  the choice per game, so the next time it starts with the Zapper. A
  header that names the Zapper still plugs it in by itself.
  - Another way: a list of known gun games (by the file's checksum).
    It needs no key, but it would be a list of commercial games' files,
    which this project can't check against, and it misses hacks and
    homebrew. Not recommended.
- **Aiming with the keyboard** (recommended): the Zapper takes
  controller 2's place, so it takes controller 2's keys. W, A, S and D
  move the aim, faster while held, and G (controller 2's A button)
  pulls the trigger. A cross is drawn where it aims, over the picture,
  and the gun's sensor doesn't see that cross (it reads the game's
  picture as the beam draws it). The mouse still works: whichever moved
  last aims. The arrows, X, Z, Return and Right Shift stay controller
  1's, which gun games use for their menus.
  - Another way: the arrows aim and Space fires, with controller 1
    moved elsewhere. That would change keys every other game uses.
- **A game controller:** its right stick aims and a shoulder button
  fires, if one is plugged in. Small to add with the keyboard.

## Steps

### 1. The Zapper switched on in a game, and remembered
- Tab in the runtime switches port 2 between the controller and the
  Zapper; the screen shows which for a second.
- The game writes the choice beside its build (`NAME.settings` in the
  app's folder); the app passes it back as `--port2 zapper` next time.
- The keys card (shown before a game) mentions Tab for the Zapper.
- Checks: a build of the project's own Zapper test ROM
  (`tests/zapper_test.nes`), switched to the Zapper by an input script
  pressing Tab, hits its target; the next build starts with the
  Zapper; a header naming the Zapper still wins.
- Breaks: Tab ignored, the choice not saved, the app not passing it on.

### 2. Aiming with the keyboard and a controller
- W A S D move the aim (one pixel a frame, four while held for half a
  second), G fires; a gamepad's right stick and right shoulder too.
- A cross drawn over the picture where it aims, not seen by the gun's
  sensor; hidden when the mouse aims.
- The README's Zapper section and the read-mes (Mac and Windows).
- Checks: input scripts aiming with keys at the test ROM's target (a
  hit) and beside it (a miss); the cross not changing what the sensor
  sees; the mouse taking over when it moves.
- Breaks: the aim moving the wrong way, the sensor seeing the cross,
  the trigger on the wrong key, the mouse never taking over.

Both steps checked on the Mac and on GitHub's Windows machine; a release
(2.1) is a separate decision.

## Risks
- Tab is free today, but some players may press it by habit (it's
  Alt+Tab's partner). The note on screen makes a switch obvious, and
  Tab switches back.
- A gun game that also needs controller 2 (rare) can't have both
  through this switch: `--port1 zapper` or the header still cover it.
