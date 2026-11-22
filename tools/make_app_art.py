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
import subprocess
import sys
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
    ("screen", (0x46, 0x6C, 0xB4)),     # the TV screen's glow (animated)
    ("scan", (0x3C, 0x5E, 0xA2)),       # its scanlines (animated)
    ("led", (0xE0, 0x20, 0x20)),        # the power light (animated)
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
SCREEN = (253, 43, 116, 86)             # where the TV screens' words go: x, y, w, h
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
        self.px = [[IDX["shadow"]] * W for _ in range(H)]

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


# ---- the room: the reference picture itself (PLAN-library.md) ----

REFERENCE = os.path.join(ROOT, "design", "library-reference.jpg")
REF_CROP = (21, 1387)                   # its 16:9 middle, of its 1408 columns
# The shelf's boxes in the picture: 2 rows of 8 a side. Where each box
# stands (its left x, its top y), all 30x47; the app puts the games'
# boxes there (step 4), and until then a placeholder.
SLOT_W, SLOT_H = 30, 47
SLOT_X = ([26 + round(k * 36.6) for k in range(8)] + [326 + round(k * 36.4) for k in range(8)])
SLOT_Y = [230, 292]
# Inside the shelf, where the painted boxes are cleared: each half-row's
# box columns (x0, x1) and its height (y0, y1); the back's colour on each
# line is taken from the gaps between the painted boxes (GAPS).
CLEAR_X = [(25, 315), (325, 612)]
CLEAR_Y = [(222, 279), (286, 340)]
GAPS = [[59, 96, 132, 169, 205, 242, 279], [359, 396, 432, 468, 504, 540, 577]]
GLASS_SEED = (312, 60)                  # a pixel on the TV's glass
LED = (394, 35)                         # the TV's little light (2x2)
ROOM_COLOURS = 1000                     # the picture's colours, kept
# The dragon's sword (step 2): its blade, the bright cyan pixels in this
# box (the hilt's guard, below, left out); the app adds a pulsing cyan
# light to it and, fading, to GLOW_REACH pixels around it.
SWORD_BOX = (448, 100, 500, 164)        # x0, y0, x1, y1 (x1, y1 not in it)
GLOW_REACH = 4
GLOW = []                               # (x, y, strength 1-255)


def sword_glow(rgb):
    """The sword's light: every pixel within GLOW_REACH of the blade, with
    how much of the light it gets (255 on the blade, less further off)."""
    x0, y0, x1, y1 = SWORD_BOX
    blade = {(x, y) for y in range(y0, y1) for x in range(x0, x1)
             if rgb[y][x][1] > 130 and rgb[y][x][2] > 140 and rgb[y][x][0] < 120
             and rgb[y][x][1] > rgb[y][x][0] + 50}
    out = []
    for y in range(y0 - GLOW_REACH, y1 + GLOW_REACH):
        for x in range(x0 - GLOW_REACH, x1 + GLOW_REACH):
            d = min(((x - bx) ** 2 + (y - by) ** 2) ** 0.5 for bx, by in blade
                    if abs(bx - x) <= GLOW_REACH and abs(by - y) <= GLOW_REACH) \
                if any(abs(bx - x) <= GLOW_REACH and abs(by - y) <= GLOW_REACH for bx, by in blade) else 99
            if d <= GLOW_REACH:
                k = 1.0 if d == 0 else 0.55 * (1 - d / (GLOW_REACH + 1)) ** 1.5
                out.append((x, y, max(1, int(round(255 * k)))))
    return out


def read_png_rgb(path):
    """A PNG's pixels as rows of (r, g, b) (8-bit RGB or RGBA)."""
    d = open(path, "rb").read()
    i, idat = 8, b""
    while i < len(d):
        n = struct.unpack(">I", d[i:i + 4])[0]
        t, body = d[i + 4:i + 8], d[i + 8:i + 8 + n]
        if t == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            assert depth == 8 and ctype in (2, 6), (depth, ctype)
        elif t == b"IDAT":
            idat += body
        i += 12 + n
    raw = zlib.decompress(idat)
    bpp = 4 if ctype == 6 else 3
    stride = w * bpp
    rows, prev, p = [], bytearray(stride), 0
    for _ in range(h):
        f = raw[p]
        r = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        for x in range(stride):
            a = r[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1:
                r[x] = (r[x] + a) & 255
            elif f == 2:
                r[x] = (r[x] + b) & 255
            elif f == 3:
                r[x] = (r[x] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                r[x] = (r[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append([tuple(r[x * bpp:x * bpp + 3]) for x in range(w)])
        prev = r
    return rows


def shrink(rows, x0, x1, nw, nh):
    """rows' columns x0-x1 averaged down to nw x nh: each new pixel the
    mean of the area it covers (parts of pixels counted in part)."""
    def spans(n_src, n_dst):
        k, out = n_src / n_dst, []
        for d in range(n_dst):
            a, b, s, ws = d * k, (d + 1) * k, int(d * k), []
            while s < b - 1e-9:
                ws.append((s, min(b, s + 1) - max(a, s)))
                s += 1
            out.append(ws)
        return out
    wx, wy = spans(x1 - x0, nw), spans(len(rows), nh)
    across = [[tuple(sum(row[x0 + s][c] * w for s, w in ws) / sum(w for _, w in ws) for c in range(3))
               for ws in wx] for row in rows]
    return [[tuple(int(round(sum(across[s][x][c] * w for s, w in ws) / sum(w for _, w in ws)))
                   for c in range(3)) for x in range(nw)] for ws in wy]


def reference():
    """The reference picture at 640x360 (rows of RGB)."""
    if not os.path.exists(REFERENCE):
        sys.exit("the room is design/library-reference.jpg (PLAN-library.md), and it isn't there")
    tmp = os.path.join(ROOT, "build", "library-reference.png")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    subprocess.run(["sips", "-s", "format", "png", REFERENCE, "--out", tmp], check=True,
                   capture_output=True)
    return shrink(read_png_rgb(tmp), REF_CROP[0], REF_CROP[1], W, H)


def mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def placeholder(rgb, x0, y0, back):
    """An empty place on the shelf: the faint outline of a box in the
    shelf's own shadows (its window, the little label and sticker), as if
    one had stood there in the dust."""
    for y in range(y0, y0 + SLOT_H):
        for x in range(x0, x0 + SLOT_W):
            edge = x in (x0, x0 + SLOT_W - 1) or y in (y0, y0 + SLOT_H - 1)
            if edge:
                col = mix(back, (190, 160, 220), 0.12)
            else:
                col = mix(back, (190, 160, 220), 0.04)
            rgb[y][x] = col
    for y in range(y0 + 5, y0 + 23):                    # the window
        for x in range(x0 + 4, x0 + SLOT_W - 4):
            inner = x0 + 5 <= x < x0 + SLOT_W - 5 and y0 + 6 <= y < y0 + 22
            rgb[y][x] = mix(back, (0, 0, 0), 0.3) if inner else mix(back, (190, 160, 220), 0.1)
    for x in range(x0 + 4, x0 + 10):                    # the label
        rgb[y0 + 41][x] = mix(back, (190, 160, 220), 0.12)
    for (dx, dy) in ((1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (3, 1), (1, 2), (2, 2)):
        x, y = x0 + 21 + dx, y0 + 39 + dy                # the sticker
        rgb[y][x] = mix(back, (190, 160, 220), 0.12)


def glass(rgb):
    """The TV's glass in the picture: every pixel joined to GLASS_SEED by
    pixels brighter than its dark rim."""
    seen, todo = set(), [GLASS_SEED]
    while todo:
        x, y = todo.pop()
        if (x, y) in seen or sum(rgb[y][x]) < 210:
            continue
        seen.add((x, y))
        todo += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    # Then everything inside its outline (the glass curves outwards only):
    # the words and the cartridge painted on it go too, and the edge is
    # clean. The outline: the convex hull of the pixels' corners.
    pts = sorted({(x + dx, y + dy) for x, y in seen for dx in (0, 1) for dy in (0, 1)})

    def turn(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    hull = []
    for seq in (pts, pts[::-1]):
        half = []
        for p in seq:
            while len(half) >= 2 and turn(half[-2], half[-1], p) <= 0:
                half.pop()
            half.append(p)
        hull += half[:-1]
    inside = Sprite()
    inside.poly(hull, "screen")
    return set(inside.px)


def median_cut(counts, n):
    """counts: colour -> pixels. n colours that stand for them, and which
    each colour becomes."""
    boxes = [list(counts)]
    while len(boxes) < n:
        best, bi, axis = -1, -1, 0
        for i, b in enumerate(boxes):
            if len(b) < 2:
                continue
            for c in range(3):
                vals = [col[c] for col in b]
                score = (max(vals) - min(vals)) * sum(counts[col] for col in b) ** 0.5
                if score > best:
                    best, bi, axis = score, i, c
        if bi < 0:
            break
        b = sorted(boxes[bi], key=lambda col: col[axis])
        total, run, cut = sum(counts[col] for col in b), 0, 1
        for k, col in enumerate(b):
            run += counts[col]
            if run * 2 >= total:
                cut = max(1, min(len(b) - 1, k + 1))
                break
        boxes[bi:bi + 1] = [b[:cut], b[cut:]]
    colours, which = [], {}
    for b in boxes:
        t = sum(counts[col] for col in b)
        colours.append(tuple(int(round(sum(col[c] * counts[col] for col in b) / t)) for c in range(3)))
        for col in b:
            which[col] = len(colours) - 1
    return colours, which


ROOM_PALETTE = []                       # the picture's colours, after PALETTE's


def draw():
    """The room: the reference picture at 640x360, its painted boxes
    cleared to the shelf's back and placeholders drawn where they stood,
    the TV's glass and light left to the app (the screen's two animated
    colours, and the light's)."""
    rgb = reference()
    for (x0, x1), gaps in zip(CLEAR_X, GAPS):
        for (y0, y1) in CLEAR_Y:
            for y in range(y0, y1):
                cols = [rgb[y][g + d] for g in gaps for d in (-1, 0, 1)]
                back = tuple(sum(c[i] for c in cols) // len(cols) for i in range(3))
                for x in range(x0, x1):
                    rgb[y][x] = back
    for y0 in SLOT_Y:
        for x0 in SLOT_X:
            placeholder(rgb, x0, y0, rgb[y0 + 12][x0 + 2])  # (the cleared back there)
    GLOW[:] = sword_glow(rgb)
    screen = glass(rgb)
    top = min(y for _, y in screen)
    counts = {}
    for y in range(H):
        for x in range(W):
            if (x, y) not in screen:
                counts[rgb[y][x]] = counts.get(rgb[y][x], 0) + 1
    colours, which = median_cut(counts, ROOM_COLOURS)
    ROOM_PALETTE[:] = colours
    c = Canvas()
    base = len(PALETTE)
    for y in range(H):
        for x in range(W):
            if (x, y) in screen:
                c.px[y][x] = IDX["scan" if (y - top) % 2 else "screen"]
            else:
                c.px[y][x] = base + which[rgb[y][x]]
    for (x, y) in screen:                               # the glass's dark rim
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) not in screen:
                c.put(x + dx, y + dy, "outline")
    for dx in (0, 1):
        for dy in (0, 1):
            c.put(LED[0] + dx, LED[1] + dy, "led")
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


def all_colours():
    """PALETTE's named colours, then the picture's."""
    return [col for _, col in PALETTE] + ROOM_PALETTE


def png(path, c):
    rgb = all_colours()
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
    lines.append("#define ART_COLOURS %d" % len(all_colours()))
    lines.append("#define ART_NAMED %d                 /* the named ones; then the picture's */" % len(PALETTE))
    lines.append("static const unsigned char art_palette[ART_COLOURS][3] = {")
    for name, (r, g, b) in PALETTE:
        lines.append("    { 0x%02X, 0x%02X, 0x%02X },   /* %s */" % (r, g, b, name))
    for (r, g, b) in ROOM_PALETTE:
        lines.append("    { 0x%02X, 0x%02X, 0x%02X }," % (r, g, b))
    lines.append("};")
    lines.append("/* The shelf's places for boxes (PLAN-library.md): left x, top y, all ART_SLOT_W x ART_SLOT_H. */")
    lines.append("#define ART_SLOT_W %d" % SLOT_W)
    lines.append("#define ART_SLOT_H %d" % SLOT_H)
    lines.append("#define ART_SLOTS_ROW %d" % len(SLOT_X))
    lines.append("#define ART_SLOT_ROWS %d" % len(SLOT_Y))
    lines.append("static const short art_slot_x[ART_SLOTS_ROW] = { %s };" % ", ".join(map(str, SLOT_X)))
    lines.append("static const short art_slot_y[ART_SLOT_ROWS] = { %s };" % ", ".join(map(str, SLOT_Y)))
    lines.append("/* The sword's light (PLAN-library.md step 2): x, y, and how much of it (1-255). */")
    lines.append("#define ART_GLOW_N %d" % len(GLOW))
    lines.append("static const short art_glow[ART_GLOW_N][3] = {")
    for k in range(0, len(GLOW), 8):
        lines.append("    " + " ".join("{%d,%d,%d}," % g for g in GLOW[k:k + 8]))
    lines.append("};")
    lines.append("static const unsigned short art_pixels[ART_H][ART_W] = {")
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
