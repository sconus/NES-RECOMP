#!/usr/bin/env python3
"""Write app/art.h: the pictures of the nesrecomp app (PLAN-gui.md).
Run it again after changing it; it also writes build/app_art.png, the
picture alone, to look at.

The canvas is 320x180, scaled up by whole numbers in the window. It is
drawn here from simple shapes, so it can be changed by editing them:
  - a dark room (a striped wall, a wooden table top);
  - a 1980s TV on the table: a wood cabinet, a rounded screen, a control
    panel with two dials and a speaker grille;
  - in front of it, front and centre, a grey game console of that era:
    a light top with the cartridge slot, a darker front with two
    controller ports, a power button with a red light, and a reset
    button.
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
W, H = 320, 180

# The palette: name -> RGB. The first three are animated by the app.
# The room, the dragon and the sign are in the colours of the user's
# channel, Polygon Legends: a blue-violet to magenta gradient, a red
# dragon with a purple-blue mane and gold horns, white lettering with a
# dark outline.
PALETTE = [
    ("screen", (0x10, 0x18, 0x40)),     # the TV screen's glow (animated)
    ("scan", (0x0A, 0x10, 0x30)),       # its scanlines (animated)
    ("led", (0xE0, 0x20, 0x20)),        # the power light (animated)
    ("wall0", (0x34, 0x26, 0xA8)),      # the wall's gradient, violet...
    ("wall1", (0x50, 0x26, 0xA0)),
    ("wall2", (0x6C, 0x26, 0x98)),
    ("wall3", (0x88, 0x26, 0x92)),
    ("wall4", (0xA4, 0x2A, 0x8A)),      # ...to magenta
    ("table", (0x3A, 0x1E, 0x46)),
    ("table2", (0x2C, 0x16, 0x36)),
    ("table3", (0x6E, 0x3A, 0x86)),     # the table's front edge, lit
    ("shadow", (0x16, 0x0C, 0x20)),
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
SCREEN = (92, 24, 116, 86)              # the TV screen: x, y, w, h

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
    """A console shaped like the NES (front view, the top seen a little):
    the two-tone grey box, the flap on top, the ridges and the black band
    on the right, the dark lower front with the light and the power and
    reset buttons, the two controller ports in the black band."""
    w = 124
    c.rect(x + 2, y + 46, w, 4, "shadow")
    c.outline_rect(x, y, w, 46, "grey", r=1)
    # The top, seen a little: light grey.
    c.rect(x, y, w, 15, "grey_top")
    c.rect(x + 1, y, w - 2, 1, "grey_hi")
    # The flap: a raised panel on the left two thirds of the top.
    c.rect(x + 6, y + 3, 64, 10, "grey_hi")
    c.rect(x + 6, y + 12, 64, 1, "grey")
    c.rect(x + 5, y + 3, 1, 10, "grey")
    c.rect(x + 70, y + 3, 1, 10, "grey")
    # The ridges, between the flap and the black band.
    for yy in range(y + 3, y + 13, 2):
        c.rect(x + 75, yy, 22, 1, "grey")
    # The black band across the top and down the front.
    bx = x + 99
    c.rect(bx, y, 16, 46, "black")
    c.rect(bx, y + 7, 16, 1, "black2")
    c.rect(bx, y + 15, 16, 1, "black2")
    # The front: light above, the darker band below.
    c.rect(x, y + 15, 99, 1, "grey_dark")
    c.rect(x, y + 26, 99, 20, "grey_dark")
    c.rect(x, y + 26, 99, 1, "grey_deep")
    c.rect(x + 115, y + 15, w - 115, 31, "grey")
    c.rect(x + 115, y + 26, w - 115, 20, "grey_dark")
    # The light, then the power and reset buttons.
    c.rect(x + 10, y + 33, 2, 2, "led")
    for bx2 in (x + 15, x + 33):
        c.outline_rect(bx2, y + 31, 15, 6, "grey_deep", r=0)
        c.rect(bx2, y + 31, 15, 1, "grey")
    # The two controller ports, in the black band.
    for py in (y + 18, y + 32):
        c.outline_rect(bx + 4, py, 8, 9, "grey_deep", r=1)
        c.rect(bx + 5, py + 2, 6, 5, "black")
        for k in range(3):
            c.put(bx + 6 + 2 * k, py + 4, "grey_dark")


def draw():
    c = Canvas()
    # The wall: the channel's gradient, from violet at the top left to
    # magenta at the bottom right, dithered between five shades.
    for y in range(126):
        for x in range(W):
            t = (x / W) * 0.65 + (y / 126) * 0.35
            v = t * 4 + (BAYER[y % 4][x % 4] / 16 - 0.5)
            c.put(x, y, "wall%d" % max(0, min(4, int(round(v)))))
    # The table: dark purple planks, a lit front edge, a shadow under it.
    c.rect(0, 126, W, 54, "table")
    for y in (134, 146, 160):
        c.rect(0, y, W, 1, "table2")
    for x0, y0 in ((40, 127), (150, 135), (260, 147), (90, 161), (200, 127)):
        c.rect(x0, y0, 1, 7 if y0 < 147 else 12, "table2")
    c.rect(0, 126, W, 1, "table3")
    c.rect(0, 172, W, 8, "shadow")

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
    sx, sy, sw, sh = SCREEN
    c.outline_rect(sx - 6, sy - 6, sw + 12, sh + 12, "bezel", r=5)
    c.rect(sx - 5, sy - 5, sw + 10, 1, "bezel2")
    c.round_rect(sx - 1, sy - 1, sw + 2, sh + 2, "outline", r=6)
    c.round_rect(sx, sy, sw, sh, "screen", r=5)
    for y in range(sy, sy + sh, 2):             # scanlines
        for x in range(sx, sx + sw):
            if c.px[y][x] == IDX["screen"]:
                c.put(x, y, "scan")
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
