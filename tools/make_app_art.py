#!/usr/bin/env python3
"""Write app/art.h: the pictures of the nesrecomp app (PLAN-gui.md).
Run it again after changing it; it also writes build/app_art.png, the
picture alone, to look at.

The canvas is 640x360, scaled up by whole numbers in the window. It is
drawn here from simple shapes, so it can be changed by editing them. The
living room of design/library-reference.jpg (PLAN-library.md), redrawn:
  - the wall in the evening light, blue from the window at the left to
    purple at the right, a curtain, a plant on the floor and its shadow;
  - the floorboards and a patterned rug; an armchair at the back right;
    a framed sign: NES RECOMP, POLYGON LEGENDS;
  - the long shelf at the bottom: its top, where a lamp with a warm
    light stands at the left and a plant at the right, and its front
    with two rows on each side (the library's boxes go there, drawn by
    the app);
  - on the shelf, a TV stand: a 1980s TV on it (a wood cabinet, a rounded
    screen, two dials, three buttons and a speaker grille) and, inside,
    a grey game console of that era between two pads;
  - the little cartridge with an arrow for the drop screen (art_cart).
The design is original; it copies no maker's logo, name or shape.

Colours are indexes into a palette. Three indexes are changed by the
app as it runs, for the idle animation: the screen's two colours (its
glow and its scanlines) and the power light.

The font is the runtime's 5x7 one, read from runtime/nsf.c, so there is
one copy of it.
"""
import os
import re
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
W, H = 640, 360

# The palette: name -> RGB. The first three are animated by the app.
# The room, the dragon and the sign are in the colours of the user's
# channel, Polygon Legends: a blue-violet to magenta gradient, a red
# dragon with a purple-blue mane and gold horns, white lettering with a
# dark outline.
PALETTE = [
    ("screen", (0x2A, 0x42, 0x9A)),     # the TV screen's glow (animated)
    ("scan", (0x22, 0x36, 0x84)),       # its scanlines (animated)
    ("led", (0xE0, 0x20, 0x20)),        # the power light (animated)
    ("wall0", (0x2C, 0x5C, 0xE8)),      # the wall's evening light, blue...
    ("wall1", (0x34, 0x48, 0xD8)),
    ("wall2", (0x44, 0x38, 0xC8)),
    ("wall3", (0x58, 0x30, 0xB4)),
    ("wall4", (0x6C, 0x2C, 0xA4)),
    ("wall5", (0x80, 0x2C, 0x98)),      # ...to purple
    ("wall_dark", (0x22, 0x2C, 0x9C)),  # the plant's shadow on it
    ("wall_warm", (0x8C, 0x50, 0xA8)),  # the lamp's light on it
    ("wall_warm2", (0xB4, 0x74, 0x9C)),
    ("base", (0x24, 0x18, 0x50)),       # the skirting board
    ("base_hi", (0x52, 0x44, 0xA0)),
    ("floor0", (0x4E, 0x2E, 0x4C)),     # the floorboards
    ("floor1", (0x40, 0x24, 0x42)),
    ("floor_line", (0x26, 0x14, 0x2A)),
    ("floor_lit", (0x84, 0x4E, 0x4A)),  # lit by the lamp
    ("rug", (0x2E, 0x38, 0x94)),        # the rug
    ("rug_dark", (0x1E, 0x22, 0x68)),
    ("rug_pat", (0x60, 0x4C, 0xB8)),
    ("rug_red", (0x90, 0x3C, 0x70)),
    ("curtain", (0x6C, 0x26, 0x2E)),
    ("curtain_dark", (0x40, 0x14, 0x20)),
    ("curtain_hi", (0x98, 0x40, 0x3E)),
    ("shade", (0xF8, 0xC4, 0x70)),      # the lamp
    ("shade_hi", (0xFF, 0xE8, 0xB0)),
    ("shade_dark", (0xC8, 0x84, 0x44)),
    ("lamp_base", (0x5C, 0x60, 0x88)),
    ("lamp_base_hi", (0x8C, 0x90, 0xB8)),
    ("lamp_base_dark", (0x34, 0x36, 0x5C)),
    ("leaf", (0x2C, 0x8C, 0x50)),       # the plants
    ("leaf_hi", (0x60, 0xC4, 0x5C)),
    ("leaf_dark", (0x18, 0x54, 0x40)),
    ("pot", (0xB4, 0x56, 0x34)),
    ("pot_hi", (0xDC, 0x80, 0x4C)),
    ("pot_dark", (0x76, 0x30, 0x26)),
    ("chair", (0x8E, 0x46, 0x36)),      # the armchair
    ("chair_hi", (0xB2, 0x62, 0x46)),
    ("chair_dark", (0x5C, 0x2A, 0x32)),
    ("shelf_top", (0x9A, 0x60, 0x38)),  # the shelf and the TV stand
    ("shelf_top_hi", (0xC0, 0x84, 0x4E)),
    ("shelf_top_warm", (0xD0, 0x96, 0x58)),
    ("shelf_front", (0x76, 0x48, 0x2A)),
    ("shelf_front_dark", (0x58, 0x34, 0x22)),
    ("shelf_grain", (0x66, 0x3E, 0x26)),
    ("shelf_in", (0x2C, 0x1A, 0x1A)),   # inside it
    ("shelf_in2", (0x1E, 0x10, 0x14)),
    ("shadow", (0x16, 0x0C, 0x20)),
    ("icon_wall0", (0x34, 0x26, 0xA8)),  # the icon's room (draw_icon): its wall...
    ("icon_wall1", (0x50, 0x26, 0xA0)),
    ("icon_wall2", (0x6C, 0x26, 0x98)),
    ("icon_wall3", (0x88, 0x26, 0x92)),
    ("icon_wall4", (0xA4, 0x2A, 0x8A)),
    ("icon_table", (0x3A, 0x1E, 0x46)),  # ...its table...
    ("icon_table2", (0x2C, 0x16, 0x36)),
    ("icon_table3", (0x6E, 0x3A, 0x86)),
    ("icon_screen", (0x10, 0x18, 0x40)), # ...its TV's screen
    ("icon_scan", (0x0A, 0x10, 0x30)),
    ("wood", (0x8A, 0x52, 0x2A)),       # the TV cabinet
    ("wood2", (0x74, 0x42, 0x20)),      # its grain
    ("wood3", (0xA8, 0x6A, 0x38)),      # its lit edge
    ("outline", (0x10, 0x0C, 0x14)),
    ("bezel", (0x2A, 0x26, 0x2C)),      # around the screen
    ("bezel2", (0x3E, 0x3A, 0x40)),
    ("panel", (0x5A, 0x34, 0x18)),      # the control panel
    ("knob", (0xB8, 0xB0, 0xA0)),
    ("knob2", (0x80, 0x78, 0x6C)),
    ("grille", (0x30, 0x1C, 0x10)),
    ("grey_top", (0xCC, 0xCA, 0xC6)),   # the console: its light top...
    ("grey_hi", (0xE4, 0xE2, 0xDE)),
    ("grey", (0xA8, 0xA6, 0xA2)),       # ...its front...
    ("grey_dark", (0x74, 0x72, 0x70)),  # ...its darker lower front
    ("grey_deep", (0x5C, 0x5A, 0x58)),
    ("black", (0x1C, 0x1C, 0x20)),      # the black band
    ("black2", (0x34, 0x34, 0x38)),
    ("red", (0xC8, 0x24, 0x24)),        # the dragon
    ("red_dark", (0x84, 0x14, 0x20)),
    ("red_light", (0xF0, 0x6A, 0x3A)),
    ("gold", (0xF0, 0xC0, 0x3C)),
    ("gold_dark", (0xB0, 0x7C, 0x1C)),
    ("mane", (0x7A, 0x3C, 0xE0)),       # purple
    ("mane_blue", (0x3C, 0x5C, 0xF0)),
    ("mane_hi", (0xB8, 0xA8, 0xFF)),
    ("eye", (0xFF, 0xE8, 0x40)),
    ("fang", (0xF4, 0xF0, 0xE8)),
    ("mouth", (0x3C, 0x08, 0x10)),
    ("neon", (0xFF, 0x5C, 0xD8)),       # the sign's frame
    ("neon_dim", (0x9C, 0x2C, 0x9C)),
    ("text", (0xF0, 0xF0, 0xF0)),       # lettering
    ("text_line", (0x14, 0x0C, 0x1C)),  # its outline
    ("letterbox", (0x10, 0x08, 0x1A)),  # around the canvas in the window
    ("bar", (0x40, 0xC8, 0x60)),        # the loading bar (step 2)
]
IDX = {name: i for i, (name, _) in enumerate(PALETTE)}

# Where things are, for the app.
SCREEN = (262, 40, 116, 86)             # the TV screen: x, y, w, h
ICON_SCREEN = (92, 24, 116, 86)         # the icon's (draw_icon)

# 4x4 ordered dither, for the wall's gradient.
BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def font():
    """The runtime's 5x7 font: 64 glyphs, ASCII $20-$5F."""
    src = open(os.path.join(ROOT, "runtime", "nsf.c")).read()
    body = src.split("static const uint8_t font[64][7] = {", 1)[1].split("};", 1)[0]
    vals = [int(v, 16) for v in re.findall(r"0x([0-9A-Fa-f]{2})", body)]
    assert len(vals) == 64 * 7, len(vals)
    return [vals[i * 7:i * 7 + 7] for i in range(64)]


class Canvas:
    def __init__(self):
        self.px = [[IDX["wall0"]] * W for _ in range(H)]

    def put(self, x, y, c):
        if 0 <= x < W and 0 <= y < H:
            self.px[y][x] = IDX[c]

    def rect(self, x, y, w, h, c):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.put(xx, yy, c)

    def round_rect(self, x, y, w, h, c, r=2):
        """A rectangle with its corners cut by r pixels (a stepped curve)."""
        for yy in range(h):
            inset = 0
            for k in range(r):
                if yy == k or yy == h - 1 - k:
                    inset = r - k
            for xx in range(inset, w - inset):
                self.put(x + xx, y + yy, c)

    def outline_rect(self, x, y, w, h, c, r=2):
        self.round_rect(x - 1, y - 1, w + 2, h + 2, "outline", r + 1)
        self.round_rect(x, y, w, h, c, r)

    def disc(self, cx, cy, rad, c):
        for yy in range(-rad, rad + 1):
            for xx in range(-rad, rad + 1):
                if xx * xx + yy * yy <= rad * rad + rad:
                    self.put(cx + xx, cy + yy, c)

    def text(self, s, cx, y, c="text", line="text_line"):
        """Text in the 5x7 font, centred on cx, outlined all round."""
        glyphs = font()
        x0 = cx - (len(s) * 6 - 1) // 2
        on = set()
        for i, ch in enumerate(s):
            g = glyphs[ord(ch) - 0x20]
            for r in range(7):
                for col in range(5):
                    if g[r] & (0x10 >> col):
                        on.add((x0 + i * 6 + col, y + r))
        for x, yy in on:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    self.put(x + dx, yy + dy, line)
        for x, yy in on:
            self.put(x, yy, c)


class Sprite:
    """Shapes drawn into a layer, then given a dark outline all round and
    put on the canvas: for the dragon."""
    def __init__(self):
        self.px = {}

    def put(self, x, y, c):
        self.px[(int(x), int(y))] = c

    def ellipse(self, cx, cy, rx, ry, c):
        for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
                if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                    self.put(x, y, c)

    def poly(self, pts, c):
        """A filled polygon (pixel centres inside it)."""
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        for y in range(int(min(ys)) - 1, int(max(ys)) + 2):
            for x in range(int(min(xs)) - 1, int(max(xs)) + 2):
                px, py, inside = x + 0.5, y + 0.5, False
                for i in range(len(pts)):
                    (x1, y1), (x2, y2) = pts[i], pts[i - 1]
                    if (y1 > py) != (y2 > py) and px < x1 + (py - y1) * (x2 - x1) / (y2 - y1):
                        inside = not inside
                if inside:
                    self.put(x, y, c)

    def stamp(self, canvas):
        filled = set(self.px)
        for (x, y) in filled:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if (x + dx, y + dy) not in filled:
                    canvas.put(x + dx, y + dy, "outline")
        for (x, y), c in self.px.items():
            canvas.put(x, y, c)


def bezier(pts, t):
    """A point on the Bezier curve through control points pts."""
    while len(pts) > 1:
        pts = [(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t) for a, b in zip(pts, pts[1:])]
    return pts[0]


def dragon(c, hx, hy, s=1.45):
    """The dragon beside the TV: its head facing out (at hx, hy, drawn s
    times the size of its design) and a body coiling down to the table,
    the tail curled there. Shapes only; Sprite.stamp outlines them."""
    def P(dx, dy):
        return (hx + dx * s, hy + dy * s)

    body = Sprite()
    path = [(hx, hy + 10 * s), (hx + 30, hy + 38), (hx - 34, hy + 52), (hx - 22, hy + 84),
            (hx + 4, hy + 96), (hx + 34, hy + 90)]
    steps = 200
    centres = []
    for i in range(steps + 1):
        t = i / steps
        x, y = bezier(path, t)
        centres.append((x, y, 10.0 - 7.0 * t))
    for x, y, r in centres:
        body.ellipse(x, y, r, r, "red")
    # Shading: the far side darker, a gold belly with scale lines, a
    # glint along the middle.
    for (px, py) in list(body.px):
        x, y, r = min(centres, key=lambda q: (q[0] - px) ** 2 + (q[1] - py) ** 2)
        d = px - x
        if d < -r * 0.5:
            body.put(px, py, "red_dark")
        elif d > r * 0.3:
            body.put(px, py, "gold_dark" if py % 3 == 0 else "gold")
        elif abs(d + r * 0.1) < 0.8 and r > 4:
            body.put(px, py, "red_light")
    # A few big spikes along the back, purple with a blue tip.
    for i in range(14, steps - 30, 30):
        x, y, r = centres[i]
        x2, y2, _ = centres[i + 8]
        mx, my = (x + x2) / 2, (y + y2) / 2
        body.poly([(x - r + 2, y), (x2 - r + 2, y2), (mx - r - 7, my - 3)], "mane")
        body.put(mx - r - 5, my - 2, "mane_blue")
    # The tail's tip: a spade, purple.
    x, y, r = centres[-1]
    body.poly([(x - 1, y - 5), (x + 9, y), (x - 1, y + 5), (x + 2, y)], "mane")
    body.poly([(x + 1, y - 2), (x + 6, y), (x + 1, y + 2)], "mane_blue")
    body.stamp(c)

    head = Sprite()
    # The mane: flames behind the head, blue outside, purple within, with
    # light strands, flaring up and out like the logo's.
    for tx, ty, w in ((-21, -6, 5), (-19, -17, 5), (-12, -25, 5), (-4, -30, 5),
                      (4, -30, 5), (12, -25, 5), (19, -17, 5), (21, -6, 5)):
        bx = tx * 0.3
        head.poly([P(bx - w, -3), P(bx + w, -3), P(tx, ty)], "mane_blue")
    for tx, ty, w in ((-15, -14, 4), (-9, -21, 4), (-3, -25, 4), (3, -25, 4),
                      (9, -21, 4), (15, -14, 4)):
        bx = tx * 0.3
        head.poly([P(bx - w, -3), P(bx + w, -3), P(tx, ty)], "mane")
    for tx, ty in ((-8, -19), (-2, -23), (4, -21)):
        for k in range(10):
            x, y = P(tx * k / 10, -5 + (ty + 5) * k / 10)
            head.put(x, y, "mane_hi")
    # The horns: gold, sweeping up and out.
    for side in (-1, 1):
        for i in range(40):
            t = i / 39
            x, y = bezier([P(5 * side, -6), P(14 * side, -9), P(18 * side, -21)], t)
            r = (2.3 - 1.9 * t) * s
            head.ellipse(x, y, r, r, "gold" if t < 0.7 else "gold_dark")
    # The head, the cheek frills, the snout.
    hcx, hcy = P(0, 0)
    head.ellipse(hcx, hcy, 9 * s, 8 * s, "red")
    for side in (-1, 1):
        head.poly([P(6 * side, -2), P(6 * side, 6), P(15 * side, 3)], "red_dark")
        head.poly([P(6 * side, 3), P(6 * side, 9), P(13 * side, 11)], "red_dark")
    x, y = P(0, 6)
    head.ellipse(x, y, 6.5 * s, 5 * s, "red")
    x, y = P(0, -3)
    head.ellipse(x, y, 6 * s, 2.2 * s, "red_light")    # the brow, lit
    # The open mouth, the fangs and the jaw.
    x0, y0 = P(-5, 8)
    x1, y1 = P(5, 11.5)
    for y in range(int(y0), int(y1) + 1):
        for x in range(int(x0), int(x1) + 1):
            head.put(x, y, "mouth")
    x, y = P(0, 13)
    head.ellipse(x, y, 5.5 * s, 2 * s, "red")
    for fx in (-4, 3):                                  # upper fangs
        head.poly([P(fx - 0.2, 7.6), P(fx + 1.6, 7.6), P(fx + 0.4, 10.5)], "fang")
    for fx in (-2.5, 1.5):                              # lower fangs
        head.poly([P(fx - 0.2, 12), P(fx + 1.4, 12), P(fx + 0.6, 9.6)], "fang")
    # Angry eyes under a dark slanted brow; the nostrils.
    for side in (-1, 1):
        head.poly([P(1.5 * side, -1.2), P(6.5 * side, -3.4), P(6.5 * side, -2.0), P(1.5 * side, 0.2)], "outline")
        head.poly([P(2.5 * side, 0.1), P(6.2 * side, -1.6), P(5.8 * side, 1.2), P(2.8 * side, 1.4)], "eye")
        x, y = P(4.5 * side, 0.2)
        head.put(x, y, "outline")
        x, y = P(2.2 * side, 4.5)
        head.put(x, y, "mouth"); head.put(x + side, y, "mouth")
    head.stamp(c)


def console(c, x, y):
    """A console shaped like the NES, front on, as the user drew it: the
    light upper half with a large flap on the left, the darker lower half
    with the light and the power and reset buttons, the black band on the
    right running the full height with two seams, and the two controller
    ports side by side in it, then a narrow light and dark strip."""
    w, h = 124, 46
    split = 26                                  # where light meets dark
    c.rect(x + 2, y + h, w, 4, "shadow")
    c.rect(x - 1, y - 1, w + 2, h + 2, "outline")
    c.rect(x, y, w, split, "grey_top")
    c.rect(x, y + split, w, h - split, "grey_dark")
    c.rect(x, y, w, 1, "grey_hi")
    c.rect(x, y + split, w, 1, "grey_deep")
    # The flap: a lighter panel, a darker edge at its left and bottom.
    c.rect(x + 5, y + 1, 66, 20, "grey")
    c.rect(x + 6, y + 1, 65, 19, "grey_hi")
    # The light, then the power and reset buttons.
    c.rect(x + 10, y + 33, 2, 2, "led")
    for bx in (x + 14, x + 33):
        c.rect(bx, y + 30, 16, 9, "outline")
        c.rect(bx + 1, y + 31, 14, 7, "grey_deep")
        c.rect(bx + 1, y + 31, 14, 1, "grey")
    # The black band, the full height, with two seams in its upper part.
    bx = x + 85
    c.rect(bx, y, 30, h, "black")
    c.rect(bx, y + 20, 30, 1, "black2")
    c.rect(bx, y + 25, 30, 1, "black2")
    # The two controller ports, side by side.
    for px in (bx + 4, bx + 18):
        c.round_rect(px, y + 31, 9, 11, "grey_deep", r=1)
        c.rect(px + 1, y + 33, 7, 6, "black")
        for k in range(3):
            c.put(px + 2 + 2 * k, y + 35, "grey_dark")
    # The narrow strip right of the band: light above, dark below.
    c.rect(x + 115, y, w - 115, split, "grey_top")
    c.rect(x + 115, y + split, w - 115, h - split, "grey_dark")
    c.rect(x + 115, y, w - 115, 1, "grey_hi")


def dith(x, y, t, names):
    """One of names (dark to light, or along a gradient) for t in 0-1,
    dithered with the 4x4 pattern so the steps blend."""
    v = t * (len(names) - 1) + (BAYER[y % 4][x % 4] / 16 - 0.5)
    return names[max(0, min(len(names) - 1, int(round(v))))]


def poly(c, pts, col):
    """A filled polygon straight onto the canvas."""
    s = Sprite()
    s.poly(pts, col)
    for (x, y), cc in s.px.items():
        c.put(x, y, cc)


def leaf(sp, bx, by, ang, length, width, droop=0.0):
    """A pointed leaf from (bx, by) at angle ang (degrees, 0 = right, -90
    = up), curving down by droop; lit along one side, a light midrib."""
    import math
    a = math.radians(ang)
    dx, dy = math.cos(a), math.sin(a)
    nx, ny = -dy, dx
    left, right, mid = [], [], []
    for i in range(13):
        t = i / 12
        w = width * math.sin(math.pi * t) ** 0.8
        cx = bx + dx * length * t
        cy = by + dy * length * t + droop * length * t * t
        left.append((cx + nx * w, cy + ny * w))
        right.append((cx - nx * w, cy - ny * w))
        mid.append((cx, cy))
    sp.poly(left + right[::-1], "leaf")
    sp.poly(mid + right[::-1], "leaf_dark")
    for x, y in mid[1:-2]:
        sp.put(x, y, "leaf_hi")
    for x, y in left[2:-3]:
        sp.put(x, y, "leaf_hi")


def plant(c, x, y, scale=1.0, leaves=None):
    """A potted plant: its pot's top rim at (x, y), its centre; leaves
    fanning up and out."""
    sp = Sprite()
    if leaves is None:
        leaves = [(-160, 40, 9, 0.9), (-132, 52, 10, 0.5), (-108, 64, 10, 0.2), (-80, 68, 10, 0.1),
                  (-52, 54, 10, 0.4), (-22, 40, 9, 0.9), (-145, 30, 8, 1.0), (-94, 44, 9, 0.2),
                  (-66, 46, 9, 0.3), (-36, 28, 8, 1.0)]
    for ang, ln, wd, dr in leaves:
        leaf(sp, x, y - 2, ang, ln * scale, wd * scale, dr)
    sp.stamp(c)
    pw, ph = int(18 * scale), int(26 * scale)
    pot = Sprite()
    pot.poly([(x - pw, y + 4), (x + pw, y + 4), (x + pw * 0.75, y + ph), (x - pw * 0.75, y + ph)], "pot")
    pot.poly([(x + pw * 0.2, y + 4), (x + pw, y + 4), (x + pw * 0.75, y + ph), (x + pw * 0.1, y + ph)],
             "pot_dark")
    for yy in range(y - 2, y + 5):
        for xx in range(x - pw - 2, x + pw + 3):
            pot.put(xx, yy, "pot_hi" if yy < y + 1 else "pot")
    pot.stamp(c)


def controller(c, x, y):
    """A pad of the era, our own shape: a light grey slab with a black
    face, a cross, two small grey keys and two red buttons."""
    c.rect(x - 1, y - 1, 46, 17, "outline")
    c.rect(x, y, 44, 15, "grey_top")
    c.rect(x, y, 44, 1, "grey_hi")
    c.rect(x + 2, y + 3, 40, 10, "black")
    c.rect(x + 6, y + 7, 7, 2, "grey_deep")       # the cross
    c.rect(x + 8, y + 5, 3, 6, "grey_deep")
    c.rect(x + 17, y + 8, 4, 2, "grey")           # select, start
    c.rect(x + 23, y + 8, 4, 2, "grey")
    c.disc(x + 32, y + 9, 2, "red")
    c.disc(x + 38, y + 9, 2, "red")


def cartridge_sprite():
    """The little cartridge and arrow on the drop screen: rows of palette
    names, None for see-through. 15 wide, 24 high."""
    rows = [
        "......GGG......",
        "......GgG......",
        "......GgG......",
        "......GgG......",
        "...GGGGgGGGG...",
        "....GgggggG....",
        ".....GgggG.....",
        "......GgG......",
        ".......G.......",
        "...............",
        "OOOOOOOOOOOOOOO",
        "OhhhhhhhhhhhhhO",
        "OhkkkkkkkkkkkhO",
        "OhkllllllllkkhO",
        "OhkllrrrrllkkhO",
        "OhkllrbbrllkkhO",
        "OhkllrrrrllkkhO",
        "OhkllllllllkkhO",
        "OhkkkkkkkkkkkhO",
        "OhkdkdkdkdkdkhO",
        "OhkkkkkkkkkkkhO",
        "OdddddddddddddO",
        ".OddOOOOOOOddO.",
        "..OO.......OO..",
    ]
    key = {"G": "gold_dark", "g": "gold", "O": "outline", "h": "grey_hi", "k": "grey",
           "l": "grey_dark", "r": "red", "b": "mane_blue", "d": "grey_deep", ".": None}
    return [[key[ch] for ch in row] for row in rows]


def draw():
    c = Canvas()
    import math
    # The wall: the evening light, bright blue at the left (from the
    # window behind the curtain) to purple at the right, dithered.
    for y in range(96):
        for x in range(W):
            t = (x / W) * 0.85 + (y / 96) * 0.15
            c.put(x, y, dith(x, y, t, ["wall0", "wall1", "wall2", "wall3", "wall4", "wall5"]))
    # The plant's shadow on the wall, cast by the window's light.
    sh = Sprite()
    for ang, ln, wd in ((-140, 44, 8), (-115, 56, 8), (-90, 62, 8), (-65, 54, 8), (-40, 42, 8),
                        (-160, 30, 6), (-20, 30, 6)):
        leaf(sh, 100, 92, ang, ln, wd, 0.3)
    for (x, y) in sh.px:
        if y < 96 and (x + y) % 2 == 0 or y < 96 and BAYER[y % 4][x % 4] < 12:
            c.put(x, y, "wall_dark")
    # The skirting board.
    c.rect(0, 96, W, 4, "base")
    c.rect(0, 96, W, 1, "base_hi")
    # The floor: boards running across, their joins further apart nearer.
    joins = [100]
    gap = 5.0
    while joins[-1] < H:
        joins.append(int(joins[-1] + gap))
        gap *= 1.18
    for k in range(len(joins) - 1):
        y0, y1 = joins[k], joins[k + 1]
        for y in range(y0, min(y1, H)):
            for x in range(W):
                c.put(x, y, "floor0" if k % 2 else "floor1")
        c.rect(0, y0, W, 1, "floor_line")
        for x in range((k * 53) % 97, W, 97 + k * 7):
            c.rect(x, y0, 1, y1 - y0, "floor_line")
    # The rug, seen in perspective, with a border and a pattern.
    top, bot = 114, 186
    for y in range(top, bot):
        t = (y - top) / (bot - top)
        xl, xr = int(118 - 50 * t), int(522 + 50 * t)
        for x in range(xl, xr):
            edge = min(x - xl, xr - 1 - x, (y - top) * 2, (bot - 1 - y) * 2)
            col = "rug"
            if edge < 2:
                col = "rug_dark"
            elif edge < 6:
                col = "rug_pat" if (x + y) % 4 < 2 else "rug_red"
            elif edge < 8:
                col = "rug_dark"
            elif (abs((x - 320) % 40 - 20) + abs((y - 150) % 18 - 9) * 2) in (14, 15):
                col = "rug_pat"
            c.put(x, y, col)
    # The curtain at the left, in folds.
    for y in range(0, 190):
        for x in range(0, 30 + (y > 150) * (y - 150) // 6):
            f = (x * 3 + (y // 40)) % 12
            c.put(x, y, "curtain_hi" if f < 2 else "curtain_dark" if f > 8 else "curtain")
    c.rect(0, 0, 40, 3, "outline")              # the rail
    # The plant at the back, on the floor.
    plant(c, 168, 84, 1.0)
    # The sign on the wall, a framed picture (top right).
    c.outline_rect(446, 6, 78, 46, "wood", r=0)
    c.rect(446, 6, 78, 1, "wood3")
    c.rect(450, 10, 70, 38, "shadow")
    c.text("NES RECOMP", 485, 13, c="text")
    c.text("POLYGON", 485, 25, c="neon")
    c.text("LEGENDS", 485, 35, c="neon")
    # The armchair at the back right, turned a little towards us: a tall
    # back with a rounded top and two buttons, a seat cushion, two
    # rolled arms.
    chair = Sprite()
    chair.ellipse(584, 58, 48, 22, "chair")             # the back's top
    for y in range(58, 128):
        for x in range(536, 633):
            chair.put(x, y, "chair")
    for (x, y) in list(chair.px):
        if x > 616:
            chair.put(x, y, "chair_dark")               # its far side, in shade
        elif y < 46 and x < 600:
            chair.put(x, y, "chair_hi")                 # lit along the top
    for bx in (566, 598):                               # the buttons
        chair.put(bx, 74, "chair_dark"); chair.put(bx + 1, 75, "chair_dark")
        chair.put(bx - 1, 75, "chair_dark"); chair.put(bx, 76, "chair_dark")
    for y in range(108, 124):                           # the seat cushion
        for x in range(530, 632):
            chair.put(x, y, "chair_hi" if y < 111 else "chair")
    for y in range(124, 148):                           # the front, under the seat
        for x in range(528, 632):
            chair.put(x, y, "chair_dark")
    chair.ellipse(521, 100, 13, 9, "chair_hi")          # the near arm, rolled
    for y in range(100, 150):
        for x in range(508, 535):
            chair.put(x, y, "chair" if x < 529 else "chair_dark")
    chair.ellipse(521, 101, 7, 5, "chair")
    chair.ellipse(636, 96, 10, 8, "chair_dark")         # the far arm
    chair.stamp(c)
    c.rect(504, 150, 136, 3, "shadow")
    # The shelf's top, seen from a little above, then its front.
    for y in range(188, 210):
        for x in range(10, 630):
            c.put(x, y, "shelf_grain" if (y - 188) % 6 == 5 and (x * 7 + y) % 90 > 20 else "shelf_top")
    c.rect(10, 188, 620, 1, "shelf_front_dark")
    c.rect(10, 209, 620, 5, "shelf_top_hi")
    c.rect(10, 213, 620, 1, "shelf_front_dark")
    c.rect(16, 214, 608, 128, "shelf_front")
    c.rect(16, 214, 608, 2, "shelf_front_dark")
    for (x0, x1) in ((24, 317), (323, 616)):
        for (y0, y1) in ((222, 270), (278, 326)):
            for y in range(y0, y1):
                for x in range(x0, x1):
                    c.put(x, y, "shelf_in2" if y < y0 + 3 or x < x0 + 2 else "shelf_in")
            c.rect(x0 - 1, y1, x1 - x0 + 2, 1, "shelf_top_hi")   # the board's lit edge
    c.rect(16, 342, 608, 4, "shadow")
    for x in (16, 623):
        c.rect(x, 214, 1, 128, "shelf_front_dark")
    # The lamp's warm light on the wall, the floor and the shelf top.
    lx, ly = 66, 128
    warm = {"wall0": ["wall_warm", "wall_warm2"], "wall1": ["wall_warm", "wall_warm2"],
            "wall2": ["wall_warm", "wall_warm2"], "wall_dark": ["wall_warm", "wall_warm"],
            "floor0": ["floor_lit", "floor_lit"], "floor1": ["floor_lit", "floor_lit"],
            "shelf_top": ["shelf_top_hi", "shelf_top_warm"], "shelf_grain": ["shelf_top", "shelf_top_hi"],
            "curtain": ["curtain_hi", "curtain_hi"], "curtain_dark": ["curtain", "curtain"]}
    names = {v: k for k, v in IDX.items()}
    for y in range(0, 214):
        for x in range(0, 200):
            d = math.hypot((x - lx) / 1.25, y - ly) / 80
            if d >= 1:
                continue
            now = names[c.px[y][x]]
            if now in warm:
                t = 1 - d
                if t + (BAYER[y % 4][x % 4] / 16 - 0.5) * 0.5 > 0.35:
                    c.put(x, y, warm[now][1 if t > 0.75 else 0])
    # The lamp: a shade, a round base.
    lamp = Sprite()
    lamp.ellipse(66, 180, 15, 18, "lamp_base")
    lamp.ellipse(60, 174, 6, 9, "lamp_base_hi")
    for y in range(162, 198):
        for x in range(51, 82):
            if (x, y) in lamp.px and x > 72:
                lamp.put(x, y, "lamp_base_dark")
    lamp.ellipse(66, 199, 13, 3, "lamp_base_dark")
    for y in range(140, 162):
        lamp.put(65, y, "lamp_base_dark"); lamp.put(66, y, "lamp_base")
    lamp.poly([(50, 108), (82, 108), (96, 144), (36, 144)], "shade")
    lamp.poly([(70, 108), (82, 108), (96, 144), (78, 144)], "shade_dark")
    lamp.poly([(52, 110), (62, 110), (52, 142), (42, 142)], "shade_hi")
    lamp.stamp(c)
    c.rect(38, 144, 57, 2, "shade_hi")              # the bright rim
    # The TV stand on the shelf, with the console and two pads in it.
    c.rect(198, 202, 245, 7, "shadow")
    c.outline_rect(198, 142, 244, 64, "shelf_front", r=0)
    c.rect(198, 142, 244, 8, "shelf_top")
    c.rect(198, 142, 244, 1, "shelf_top_hi")
    c.rect(198, 149, 244, 1, "shelf_front_dark")
    c.rect(206, 150, 228, 50, "shelf_in")
    c.rect(206, 150, 228, 3, "shelf_in2")
    c.rect(206, 200, 228, 1, "shelf_top_hi")
    console(c, 258, 154)
    controller(c, 210, 185)
    controller(c, 386, 185)
    # The TV: cabinet x 244-420, y 22-142.
    c.rect(250, 140, 166, 3, "shadow")
    c.outline_rect(244, 22, 176, 120, "wood", r=4)
    for y in range(28, 138, 7):                 # the grain
        c.rect(248, y, 168, 1, "wood2")
    c.rect(246, 23, 172, 1, "wood3")            # the lit top edge
    sx, sy, sw, sh = SCREEN
    c.outline_rect(sx - 6, sy - 6, sw + 12, sh + 12, "bezel", r=5)
    c.rect(sx - 5, sy - 5, sw + 10, 1, "bezel2")
    c.round_rect(sx - 1, sy - 1, sw + 2, sh + 2, "outline", r=6)
    c.round_rect(sx, sy, sw, sh, "screen", r=5)
    for y in range(sy, sy + sh, 2):             # scanlines
        for x in range(sx, sx + sw):
            if c.px[y][x] == IDX["screen"]:
                c.put(x, y, "scan")
    # The control panel: two dials, three buttons and a speaker grille.
    c.outline_rect(390, 30, 24, 104, "panel", r=2)
    for cy in (46, 70):
        c.disc(402, cy, 8, "outline")
        c.disc(402, cy, 7, "knob2")
        c.disc(401, cy - 1, 5, "knob")
        c.rect(401, cy - 7, 1, 5, "outline")    # the pointer
    for bx in (394, 401, 408):
        c.rect(bx, 86, 5, 4, "outline")
        c.rect(bx + 1, 86, 3, 3, "knob2")
    for y in range(96, 130, 3):
        c.rect(394, y, 16, 1, "grille")
    # The plant on the shelf's right end. (The dragon sits left of it, in
    # step 2.)
    plant(c, 590, 176, 0.9)
    return c


def draw_icon():
    """The app's icon's picture (tools/make_app_bundle.py): the first
    drop screen's room at 320x180 (PLAN-gui.md), kept as it was so the
    icon stays the same; in the top left of a canvas."""
    c = Canvas()
    # The wall: the channel's gradient, from violet at the top left to
    # magenta at the bottom right, dithered between five shades.
    for y in range(126):
        for x in range(320):
            t = (x / 320) * 0.65 + (y / 126) * 0.35
            v = t * 4 + (BAYER[y % 4][x % 4] / 16 - 0.5)
            c.put(x, y, "icon_wall%d" % max(0, min(4, int(round(v)))))
    # The table: dark purple planks, a lit front edge, a shadow under it.
    c.rect(0, 126, 320, 54, "icon_table")
    for y in (134, 146, 160):
        c.rect(0, y, 320, 1, "icon_table2")
    for x0, y0 in ((40, 127), (150, 135), (260, 147), (90, 161), (200, 127)):
        c.rect(x0, y0, 1, 7 if y0 < 147 else 12, "icon_table2")
    c.rect(0, 126, 320, 1, "icon_table3")
    c.rect(0, 172, 320, 8, "shadow")

    # The sign on the wall, right of the TV.
    c.outline_rect(247, 22, 68, 52, "shadow", r=2)
    c.round_rect(248, 23, 66, 50, "neon_dim", r=2)
    c.round_rect(250, 25, 62, 46, "shadow", r=1)
    c.text("NES RECOMP", 281, 28)
    c.text("TOOL BY", 281, 38)
    c.text("POLYGON", 281, 50)
    c.text("LEGENDS", 281, 60)

    # The TV: cabinet x 80-240, y 12-128, on two short feet.
    c.rect(96, 128, 8, 4, "outline"); c.rect(216, 128, 8, 4, "outline")
    c.rect(84, 128, 152, 3, "shadow")
    c.outline_rect(80, 12, 160, 116, "wood", r=4)
    for y in range(18, 124, 7):                 # the grain
        c.rect(84, y, 152, 1, "wood2")
    c.rect(82, 13, 156, 1, "wood3")             # the lit top edge
    # The bezel and the screen.
    sx, sy, sw, sh = ICON_SCREEN
    c.outline_rect(sx - 6, sy - 6, sw + 12, sh + 12, "bezel", r=5)
    c.rect(sx - 5, sy - 5, sw + 10, 1, "bezel2")
    c.round_rect(sx - 1, sy - 1, sw + 2, sh + 2, "outline", r=6)
    c.round_rect(sx, sy, sw, sh, "icon_screen", r=5)
    for y in range(sy, sy + sh, 2):             # scanlines
        for x in range(sx, sx + sw):
            if c.px[y][x] == IDX["icon_screen"]:
                c.put(x, y, "icon_scan")
    # The control panel: two dials and a speaker grille.
    c.outline_rect(216, 20, 18, 100, "panel", r=2)
    for cy in (32, 52):
        c.disc(225, cy, 6, "outline")
        c.disc(225, cy, 5, "knob2")
        c.disc(224, cy - 1, 4, "knob")
        c.rect(224, cy - 5, 1, 4, "outline")    # the pointer
    for y in range(70, 114, 3):
        c.rect(219, y, 12, 1, "grille")

    # The dragon, left of the TV.
    dragon(c, 42, 49)
    # The console, front and centre, in front of the TV.
    console(c, 98, 122)
    return c


def png(path, c):
    rgb = [col for _, col in PALETTE]
    raw = b"".join(b"\x00" + bytes(v for i in row for v in rgb[i]) for row in c.px)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def main():
    c = draw()
    glyphs = font()
    lines = ["/* The nesrecomp app's pictures, written by tools/make_app_art.py",
             "   (see there for what they are). Do not edit by hand. */",
             "#define ART_W %d" % W, "#define ART_H %d" % H,
             "#define ART_SCREEN_X %d" % SCREEN[0], "#define ART_SCREEN_Y %d" % SCREEN[1],
             "#define ART_SCREEN_W %d" % SCREEN[2], "#define ART_SCREEN_H %d" % SCREEN[3]]
    for i, (name, _) in enumerate(PALETTE):
        lines.append("#define INK_%s %d" % (name.upper(), i))
    lines.append("#define ART_COLOURS %d" % len(PALETTE))
    lines.append("static const unsigned char art_palette[ART_COLOURS][3] = {")
    for name, (r, g, b) in PALETTE:
        lines.append("    { 0x%02X, 0x%02X, 0x%02X },   /* %s */" % (r, g, b, name))
    lines.append("};")
    lines.append("static const unsigned char art_pixels[ART_H][ART_W] = {")
    for row in c.px:
        lines.append("    {" + ",".join(str(v) for v in row) + "},")
    lines.append("};")
    cart = cartridge_sprite()
    lines.append("/* The cartridge and arrow on the drop screen; 255 is see-through. */")
    lines.append("#define ART_CART_W %d" % len(cart[0]))
    lines.append("#define ART_CART_H %d" % len(cart))
    lines.append("static const unsigned char art_cart[ART_CART_H][ART_CART_W] = {")
    for row in cart:
        lines.append("    {" + ",".join(str(255 if v is None else IDX[v]) for v in row) + "},")
    lines.append("};")
    lines.append("/* The runtime's 5x7 font, ASCII $20-$5F; bit 4 is the leftmost pixel. */")
    lines.append("static const unsigned char art_font[64][7] = {")
    for g in glyphs:
        lines.append("    {" + ",".join("0x%02X" % v for v in g) + "},")
    lines.append("};")
    os.makedirs(os.path.join(ROOT, "app"), exist_ok=True)
    path = os.path.join(ROOT, "app", "art.h")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", path)
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    preview = os.path.join(ROOT, "build", "app_art.png")
    png(preview, c)
    print("wrote", preview)


if __name__ == "__main__":
    main()
