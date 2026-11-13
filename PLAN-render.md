# Plan: colour emphasis and mid-line changes

Goal: the picture shows the three colour-emphasis bits of `$2001`, and
changes a program makes partway through a scanline (scroll, `$2001`,
pattern table, CHR bank) show up from the pixel where the hardware would
show them, not from the next line.

`make test-all` must not get worse at any step; nestest stays exact.

## What happens today

- **Colours** are 6-bit numbers in the frame buffer, turned into RGB by
  `palette.c` from the NTSC signal. `$2001` bits 5-7 (emphasise red,
  green, blue) are stored and ignored.
- **Each visible line is drawn in one go at its dot 1** (`draw_line` in
  `ppu.c`), from the scroll, `$2000`/`$2001` and CHR banks at that
  moment. Only lines with rendering off are drawn dot by dot, which is why
  `full_palette` already works apart from emphasis.
- **Sprite 0 hit and overflow** are worked out from that whole-line
  drawing and flagged at the right dot, which the timing tests check.

## Approach

**Emphasis.** The frame buffer becomes 16-bit: colour (6 bits) plus the
emphasis bits in effect for that pixel. `palette.c` already models the
video signal, so emphasis fits naturally: each bit dims the signal during
the third of the colour cycle that belongs to its colour, and the same
decoding gives all 512 RGB values.

**Mid-line changes.** Draw the background the way the PPU fetches it:

- Each 8 dots, fetch a tile (name, attribute, two pattern bytes) using
  `v` *as it is at that dot*, and move `v` along at the real dots
  (coarse X every 8 dots, Y at 256, horizontal copy at 257, the first
  two tiles of the next line prefetched at 321-336).
- Output each pixel at its own dot, from the fetched tiles and fine X,
  with `$2001` (show background or sprites, left 8 pixels, greyscale,
  emphasis) as it is at that dot.
- Sprites keep their once-per-line search, but their patterns are
  fetched at dots 257-320 of the line before (so a CHR switch takes
  effect where it does on hardware), and they are merged pixel by pixel.
- Sprite 0 hit then happens naturally at the pixel where it occurs,
  replacing the "work out the dot in advance" mechanism.

The PPU already steps dot by dot while catching up, so this adds work
per dot rather than a new loop. It will cost speed; it gets measured, and
a cheaper path for lines where nothing changes is the fallback if it's
too much.

## Steps

### 1. Emphasis (done)
16-bit frame buffer, 512-colour table from the signal model, used by the
window and screenshots. Emphasis taken from `$2001` per pixel on lines
with rendering off, and per line otherwise (mid-line comes in step 2).
Check: `full_palette` should show its full 400-plus colour grid; look at
the screenshot, then accept its new picture. Every other picture check
must stay identical (they don't use emphasis).

Done. The frame buffer holds colour plus emphasis (`uint16_t`), and
`palette.c` builds 512 colours: each emphasis bit multiplies the wave by
0.746 during the six phases where colour 0, 4 or 8 would be high (red,
green, blue respectively, as on the nesdev wiki's NTSC video page), then
decodes as before. `full_palette` now shows eight bands, in the order the
bits count up: none, red, green, red+green (yellow), blue, red+blue
(magenta), green+blue (cyan), all three (darker). Its new picture was
accepted; the other ten pictures are pixel-identical and all 123 tests
still pass. Emphasis is taken per line where rendering is on, per dot
where it's off.

### 2. Background fetched at the real dots (done)
Replace the whole-line background with the fetch pipeline above, and
output pixels per dot. Sprites still drawn per line for now. Every PPU
test must still pass (`sprite_hit_tests`, `ppu_vbl_nmi`, the 2005 PPU
tests, MMC3 scanline timing) and all pictures must stay identical, since
those programs don't change things mid-line. Measure speed on nes15.

Done (`fetch_background` and `output_pixel` in `runtime/ppu.c`):

- Background tiles are fetched at the real dots: the nametable and
  attribute bytes at the start of each 8 dots, the pattern bytes halfway,
  each through `v` as it is then. Coarse X moves on at dots 8, 16 ... 256
  and 328, 336, as on hardware; the first two tiles of each line are
  fetched at dots 321-336 of the line before (or the pre-render line).
- Each pixel is output at its own dot, using fine X and `$2001` (show
  background/sprites, left clips, greyscale, emphasis) as they are then.
- Sprite pixels are still worked out once per line, at dot 1, and merged
  per pixel. Sprite 0 hit is set at the pixel where it happens, which is
  the same dot the old "work it out in advance" code used, so the
  separate `sprite0_line`/`sprite0_dot` bookkeeping is gone.

All 123 tests pass; all 11 pictures and both sounds are identical;
nestest exact. Speed: nes15 6000 frames 3.9-4.1 s (was 3.5), spritecans
4.0-4.2 s (was 3.7-3.9): about 8-13% slower, still about 25 times
faster than a real console, so no fast path is needed.

First look at a mid-line effect: `nmi_sync`'s demo now draws its middle
line (greyscale turned on mid-line), but it starts at x = 84 where the
reference lines start at 80: about one CPU cycle late. For step 4.

### 3. Sprites fetched at the real dots, sprite 0 hit per pixel
Sprite patterns fetched at dots 257-320, merged per pixel; sprite 0 hit
and the per-pixel `$2001` bits from the pipeline. Same checks as step 2.

### 4. Mid-line writes everywhere
Make sure every write that changes the picture brings the PPU up to date
first: `$2000`-`$2007` already do; check mapper CHR switches and
mirroring changes. Check visually with the demos: `nmi_sync`'s demo
(greyscale turned on mid-line, with reference lines showing where the
edge belongs), `window5/colorwin`, `scanline`, `scrolltest`,
`tvpassfail`. Add picture checks for those that look right.

### 5. Suite, README, notes
Accept the new pictures, update the README (the status list, the PPU
description), note speed and anything left approximate.

## Risks
- Speed: per-dot output is more work than drawing a line at a time.
  Measured at step 2; the fallback is to keep the fast path for lines
  with no mid-line writes.
- The timing tests were passed with the whole-line model, including
  sprite 0 hit timing. The new model should be more exact, but it may
  need retuning where the old one was compensating.
- The demos have no pass/fail result, so "looks right" means matching
  what their readmes and sources describe. Those checks are only as good
  as the descriptions.
