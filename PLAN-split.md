# Plan: MMC5's vertical split screen

Goal: MMC5's vertical split. Part of each scanline's background (the
left or right side, from a column the program picks) is drawn from
ExRAM, with its own vertical scroll and its own 4 KB of CHR, while the
rest of the screen scrolls as usual. Games used it for a status panel
beside a scrolling playfield (the wiki names Uchuu Keibitai SDF and
Bandit Kings of Ancient China).

`make test-all` must not get worse at any step; nestest stays exact.
Programs that never turn the split on draw exactly as before, and
`recomp.py` doesn't change, so every ROM recompiles to the same C.

## The split, from the nesdev wiki ("MMC5")

- `$5200` (`ESxW WWWW`): E turns the split on; S picks the side (0
  left, 1 right); W is a threshold in tiles, 0-31.
  - Left: tiles 0 to W-1 of each line are the split.
  - Right: tiles W and after are the split.
  - The MMC5 finds the place by counting the PPU's 34 nametable fetches
    on each line.
- `$5201`: the split's vertical scroll, 0-239. A counter starts from it
  each vblank and picks the split's nametable row line by line. It
  wraps to the top of the nametable, skipping the attribute rows.
  Values 240-255 show attribute bytes as tiles for the first lines.
  Its low 3 bits give the row within the tile (Nintendo's boards; they
  should match the PPU's fine Y).
- `$5202`: a 4 KB CHR bank for the split's patterns, whatever the CHR
  mode and `$5130` say.
- The split's nametable and attributes always come from ExRAM. ExRAM
  mode 0 or 1 is needed; modes 2 and 3 turn the split off. In mode 1 the
  rest of the screen keeps its extended attributes, while the split uses
  ordinary attributes from ExRAM.
- No horizontal scrolling inside the split: its columns stay put, and
  only the threshold's tile edge moves with fine X. The split is off
  while the background and sprites are both off (`$2001` bits 3-4).

## Left open by the wiki, so chosen here (and written down)

- **Where counting starts.** Tile 0 is the first fetch at dot 321 of
  the line before. So the count matches the 34 tiles the PPU draws from,
  as `ppu.c` already numbers them (2 prefetched, then 32).
- **The ExRAM address.** For split tile n on a split row r, the
  nametable byte is at `r * 32 + (n & 31)`. The attribute byte is at
  `$3C0 + (r / 4) * 8 + (n & 31) / 4`, using the same quarter-of-a-byte
  choice as the PPU.
- **The counter.** It is loaded from `$5201` at the start of the frame
  and moves one line on each rendered line. Row 30 wraps to row 0.
  (Step 2: "the start of the frame" is when the MMC5 sees the frame
  start, as for its IRQ counter. The wiki says that count restarts
  when rendering is turned back on, so the split restarts from `$5201`
  at that line too.)

These match how the split is usually described. With no free program
in the collection using the split, only the project's own test ROMs
check them.

## What exists

- `ppu.c` fetches each background tile in `fetch_background`. MMC5
  already hooks into it: `mapper.nt_read` (nametable mapping, fill
  mode) and `mapper.bg_tile` (extended attributes: a palette and a 4 KB
  CHR bank per tile).
- `mapper.scanline` tells MMC5 about each rendered line.
- `$5200-$5202` are accepted and ignored today.

## Test material

No program in the collection uses the split: `mmc5exram` and
`mmc5test_v2` only write 0 to `$5200`. So the project writes its own
ROMs, graded through `$6000` using **sprite 0 hit** as the probe. The
ordinary nametable is blank and the split's tiles are solid, so a hit
at a given spot says whether the split was drawn there. One probe a
frame, at chosen positions. A demo program gives a picture to look at
by hand.

## Steps

### 1. The split (done)
- `$5200-$5202` stored. The background hook gets the tile's number in
  the line (0-33) and may supply the nametable byte as well as the
  palette and CHR. For a split tile, MMC5 supplies all three from ExRAM
  and `$5202`, with the split counter's row and fine Y.
- The split counter, loaded at the pre-render line and moved on each
  rendered line.
- Check: `make_split_test.py`, graded through `$6000`, sprite 0 probing:
  - left and right sides at two thresholds;
  - the `$5201` scroll (a solid row in ExRAM lands on the expected
    screen row) and its wrap past row 29;
  - `$5202` picks the patterns (solid only in one bank);
  - the split off (bit 7 clear, ExRAM mode 2 or 3) leaves the blank
    background.
  - Break each part.
- Done:
  - `$5200-$5202` are stored. The background hook (`mapper.bg_tile`)
    now also gets the tile's number in the line (`ppu.c`'s slot, 0-33),
    and can replace the nametable byte and choose the pattern row
    (`ppu.fetch_fine`).
  - `mmc5_split_tile` (in `mapper.c`) does the split, with the three
    choices above. The split's vertical position comes from `$5201` as
    loaded on the pre-render line, plus the line number: it wraps at
    240, and from 240-255 it reads the attribute rows first. Extended
    attributes go through the same hook and are unchanged.
  - `make_split_test.py` writes `mmc5_split.nes`: 25 checks, each one
    frame long, probing with sprite 0 hit. The split's tile is solid
    only in its top half, so the pattern row (fine Y) shows.
    - left and right sides, and the threshold's exact edge;
    - `$5202`, bit 7 clear, ExRAM modes 1, 2 and 3;
    - the `$5201` scroll, its wrap and its fine Y;
    - the two prefetched tiles taking the next line's row;
    - a single solid column, for the ExRAM address.
    It passes, and fails ($01) on the runtime from before the step.
  - A slip in my own test ROM, found from a picture: three loops
    branched one byte off, since the branch distance was worked out
    before the `INX` was placed. That left most of ExRAM unfilled, but
    the test still passed, because its probes all sat below line 64.
    It now probes near the top too.
  - A picture at frame 8 shows the expected 64-pixel split on every
    line.
  - Breaks, 13 tried, all caught:
    - the split never drawn;
    - sides swapped;
    - the threshold one tile wider;
    - prefetched tiles on the line before;
    - no wrap at 240;
    - the scroll ignored;
    - fine Y 0;
    - `$5202` ignored;
    - on in ExRAM modes 2 and 3;
    - on without bit 7;
    - the ExRAM column off by one;
    - the ExRAM row off by one;
    - the PPU ignoring the mapper's pattern row.
  - Not checked yet: the split's attributes (sprite 0 can't see colour;
    step 2 checks them by picture), and when `$5201` is loaded (the
    test only writes it in vblank).
  - 206 of 207; the MMC5 pictures are unchanged; nestest exact; all
    319 earlier files give the same C.

### 2. The edges (done)
- Extended attributes (ExRAM mode 1) outside the split and plain ones
  inside.
- Fine X: the threshold moves with it and the split doesn't scroll.
- `$5201` values 240-255.
- CHR mode, `$5130` and 8x16 sprites' A/B sets not touching the
  split's patterns.
- The split stops when rendering is off.
- Check: more cases in the same test ROM (palettes probed through
  which pattern bits are solid, or by picture where sprite 0 can't
  tell). Break each part.
- Done:
  - One change to the runtime: the split's line count now starts where
    the MMC5 sees the frame start (its in-frame flag), not at the top of
    the screen. A frame drawn throughout is unchanged. When rendering is
    turned off mid-frame and back on, the split restarts from `$5201` at
    the line where it came back, as the wiki says the scanline count
    does. `$5201` is read then too (just before line 0, as before).
  - The rest already worked as planned; 19 more checks in
    `mmc5_split.nes` (44 in all):
    - ExRAM mode 1: extended attributes outside the split, `$5202` (not
      the ExRAM byte) inside it;
    - fine X 4 with coarse X 3: the split's edge moves 4 pixels, its
      columns don't move, on both sides;
    - `$5201` 248 and 252: the attribute rows as tiles, their fine Y,
      and the wrap to row 0 after them;
    - CHR mode 0 and 3, `$5130` = 1 (the ROM now has 512 KB of CHR so an
      upper bit would land on a blank bank), 8x16 sprites with the B set
      on a blank bank: the split keeps `$5202`'s bank;
    - rendering off at line 20 (polling the MMC5's IRQ flag) and on at
      line 55: row 5 lands on lines 95-98 (a sprite anywhere on 88-98
      touches it; the check uses 92), and not on 74-77, where it would
      be if the count only paused.
  - `mmc5_split_pic.nes`: a picture of the split's colours. ExRAM mode
    1, the split on the left half with `$5201` = 20, every split
    attribute byte different, and extended attributes on the right. The
    tiles have colours 1, 2 and 3 in bands, so the pattern row shows
    too. I checked every pixel against a model of the wiki's rules (all
    12 colours, none wrong) and looked at it; the suite keeps its CRC.
  - Breaks, 15 tried, all caught:
    - the split taking the extended palette (picture);
    - its attribute byte a column off, or from the screen line, or the
      wrong quarter (picture);
    - columns or threshold following coarse X;
    - `$5201` 240-255 taken mod 240; fine Y 0 on the attribute rows;
    - the bank scaled by CHR mode, given `$5130`, or taken from the
      PPU's banks with 8x16 sprites;
    - no restart (the old count), or a count that only pauses (case 44
      alone also catches it);
    - extended attributes dropped while the split is on; the split
      taking the extended bank.
  - On the step 1 runtime only the restart check fails.
  - 206 of 207, 29 pictures; nestest exact; all 319 earlier files give
    the same C.

### 3. A demo
- `make_split_demo.py`: a playfield scrolling sideways with a split
  status panel on one side and its own vertical scroll. For a try by
  hand, and as a picture check in the suite.

### 4. Suite, README, notes
Accept the new checks, document the split and the choices above,
update the status list, and write where the stage ended.

## Not in this stage
- The MMC5A's extras (`$5207-$520A`, `$5800` CL3/SL3), and the split's
  SL mode (fine Y from the counter alone; no game used it).
- Commercial games with the split: not used, as always.

## Risks
- The three choices above are the open part. Being wrong by a tile or a
  line would shift a game's panel, and only the project's own test ROM
  checks them. The choices will be written in the README so they're
  easy to revisit.
- The background hook runs for every tile. Adding to it must not slow
  ordinary programs, so the split path is only taken while the split is
  on.
