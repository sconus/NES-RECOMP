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
PALETTE = [
    ("screen", (0x10, 0x18, 0x40)),     # the TV screen's glow (animated)
    ("scan", (0x0A, 0x10, 0x30)),       # its scanlines (animated)
    ("led", (0xE0, 0x20, 0x20)),        # the power light (animated)
    ("wall", (0x1C, 0x1A, 0x2E)),
    ("wall2", (0x22, 0x20, 0x38)),
    ("table", (0x6A, 0x40, 0x24)),
    ("table2", (0x58, 0x34, 0x1C)),
    ("table3", (0x80, 0x52, 0x30)),     # the table's front edge, lit
    ("shadow", (0x12, 0x10, 0x1C)),
    ("wood", (0x8A, 0x52, 0x2A)),       # the TV cabinet
    ("wood2", (0x74, 0x42, 0x20)),      # its grain
    ("wood3", (0xA8, 0x6A, 0x38)),      # its lit edge
    ("outline", (0x10, 0x0C, 0x10)),
    ("bezel", (0x2A, 0x26, 0x2C)),      # around the screen
    ("bezel2", (0x3E, 0x3A, 0x40)),
    ("panel", (0x5A, 0x34, 0x18)),      # the control panel
    ("knob", (0xB8, 0xB0, 0xA0)),
    ("knob2", (0x80, 0x78, 0x6C)),
    ("grille", (0x30, 0x1C, 0x10)),
    ("grey_top", (0xC4, 0xC2, 0xBE)),   # the console
    ("grey_hi", (0xDE, 0xDC, 0xD8)),
    ("grey", (0xA6, 0xA4, 0xA0)),
    ("grey_dark", (0x6C, 0x6A, 0x68)),
    ("black", (0x18, 0x18, 0x1C)),
    ("stripe", (0x2C, 0x2C, 0x30)),     # the console's dark front band
    ("red", (0xB0, 0x1C, 0x24)),
    ("text", (0xF0, 0xF0, 0xF0)),       # text on the screen
    ("text_dim", (0x80, 0x90, 0xC0)),
    ("letterbox", (0x0C, 0x0A, 0x14)),  # around the canvas in the window
    ("bar", (0x40, 0xC8, 0x60)),        # the loading bar (step 2)
]
IDX = {name: i for i, (name, _) in enumerate(PALETTE)}

# Where things are, for the app.
SCREEN = (92, 24, 116, 86)              # the TV screen: x, y, w, h


def font():
    """The runtime's 5x7 font: 64 glyphs, ASCII $20-$5F."""
    src = open(os.path.join(ROOT, "runtime", "nsf.c")).read()
    body = src.split("static const uint8_t font[64][7] = {", 1)[1].split("};", 1)[0]
    vals = [int(v, 16) for v in re.findall(r"0x([0-9A-Fa-f]{2})", body)]
    assert len(vals) == 64 * 7, len(vals)
    return [vals[i * 7:i * 7 + 7] for i in range(64)]


class Canvas:
    def __init__(self):
        self.px = [[IDX["wall"]] * W for _ in range(H)]

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


def draw():
    c = Canvas()
    # The wall: soft vertical stripes.
    for x in range(W):
        if x % 16 < 8:
            for y in range(0, 126):
                c.put(x, y, "wall2")
    # The table: planks, a lit front edge, a shadow under it.
    c.rect(0, 126, W, 54, "table")
    for y in (134, 146, 160):
        c.rect(0, y, W, 1, "table2")
    for x0, y0 in ((40, 127), (150, 135), (260, 147), (90, 161), (200, 127)):
        c.rect(x0, y0, 1, 7 if y0 < 147 else 12, "table2")
    c.rect(0, 126, W, 1, "table3")
    c.rect(0, 172, W, 8, "shadow")

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

    # The console, front and centre, in front of the TV: x 108-212,
    # y 122-170.
    c.rect(110, 168, 104, 4, "shadow")
    c.outline_rect(108, 122, 104, 46, "grey", r=2)
    c.rect(108, 122, 104, 16, "grey_top")      # the light top
    c.rect(109, 122, 102, 1, "grey_hi")
    c.rect(108, 138, 104, 1, "grey_dark")      # where top meets front
    # The cartridge slot, with its flap.
    c.outline_rect(132, 126, 56, 8, "black", r=1)
    c.rect(134, 127, 52, 1, "stripe")
    # The dark band on the front, the ports and the buttons on it.
    c.rect(108, 146, 104, 16, "stripe")
    c.rect(108, 146, 104, 1, "black")
    for px in (114, 128):                       # two controller ports
        c.outline_rect(px, 150, 10, 8, "grey_dark", r=1)
        c.rect(px + 2, 152, 6, 4, "black")
    c.outline_rect(162, 150, 14, 7, "grey", r=1)    # power
    c.outline_rect(182, 150, 14, 7, "grey", r=1)    # reset
    c.rect(163, 151, 12, 1, "grey_hi"); c.rect(183, 151, 12, 1, "grey_hi")
    c.rect(150, 152, 4, 3, "led")               # the power light
    c.rect(108, 163, 104, 1, "grey_dark")
    # A cable from the console up to the TV's side.
    for y in range(124, 129):
        c.put(212 + 1, y, "black")
    for x in range(213, 241):
        c.put(x, 124, "black")
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
