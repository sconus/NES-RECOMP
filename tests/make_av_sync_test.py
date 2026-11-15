#!/usr/bin/env python3
"""The picture-and-sound test ROM for recording (PLAN-standalone.md step 6,
tests/check_record.py): an NROM program, made here.

The screen: a pattern of tiles in three colours (small squares and
stripes) with gaps where the background colour shows, so a movie of it
has detail to compare and a background to watch.

Once a second (every 60 frames, counted in the NMI), in the same NMI:
  - the background colour turns white ($30), and
  - pulse 1 starts a 440 Hz beep (period 253, 50% duty, full volume);
4 frames later both stop (the background black again, the pulse
silenced). So in a recording each beep must start with its flash.

    python3 tests/make_av_sync_test.py [OUT]     (default build/av_sync.nes)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_mmc1_test import Asm  # noqa: E402

FLASH_EVERY = 60        # frames
FLASH_FRAMES = 4
PALETTE = [0x0F, 0x16, 0x2A, 0x12]      # black, red, green, blue
WHITE = 0x30


def chr_rom():
    """Tile 0 empty (the background), 1 squares of 2x2 pixels in colours
    1-3, 2 stripes of colours 1 and 2, 3 solid colour 3."""
    data = bytearray(8192)

    def tile(n, colour):
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                c = colour(x, y)
                lo |= (c & 1) << (7 - x)
                hi |= (c >> 1) << (7 - x)
            data[n * 16 + y] = lo
            data[n * 16 + 8 + y] = hi
    tile(1, lambda x, y: 1 + (x // 2 + y // 2) % 3)
    tile(2, lambda x, y: 1 + (y // 2) % 2)
    tile(3, lambda x, y: 3)
    return bytes(data)


def nametable():
    """32x30 tiles, then the attributes (all palette 0)."""
    t = bytearray()
    for row in range(30):
        for col in range(32):
            t.append((col + row * 2) % 4)
    return bytes(t) + bytes(64)


def program():
    a = Asm(0xC000)

    def jmp(name):
        a.b(0x4C, 0, 0)
        a.fix.append((len(a.code) - 2, name))

    def back(op, name):                         # a short branch back
        off = a.labels[name] - (a.pc() + 2)
        assert -128 <= off < 0
        a.b(op, off & 0xFF)

    a.label("reset")
    a.b(0x78, 0xD8, 0xA2, 0xFF, 0x9A)           # SEI; CLD; LDX #$FF; TXS
    a.lda(0x00); a.sta(0x2000); a.sta(0x2001)   # no NMI, no rendering
    a.lda(0x40); a.sta(0x4017)                  # no frame IRQ
    for _ in range(2):                          # two vblanks: the PPU is ready
        a.label("vb%d" % _)
        a.b(0x2C, 0x02, 0x20)                   # BIT $2002
        back(0x10, "vb%d" % _)                  # BPL
    # The palette.
    a.b(0x2C, 0x02, 0x20)
    a.lda(0x3F); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.b(0xA2, 0x00)                             # LDX #0
    a.label("pal_loop")
    a.b(0xBD, 0, 0); a.fix.append((len(a.code) - 2, "palette"))   # LDA palette,X
    a.sta(0x2007)
    a.b(0xE8, 0xE0, 4)                          # INX; CPX #4
    back(0xD0, "pal_loop")
    # The nametable and attributes: 1024 bytes from the table.
    a.lda(0x20); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.b(0xA9, 0); a.fix.append((len(a.code) - 1, "lo:table"))
    a.b(0x85, 0x10)                             # STA $10
    a.b(0xA9, 0); a.fix.append((len(a.code) - 1, "hi:table"))
    a.b(0x85, 0x11)                             # STA $11
    a.b(0xA2, 4, 0xA0, 0)                       # LDX #4; LDY #0
    a.label("nt_loop")
    a.b(0xB1, 0x10)                             # LDA ($10),Y
    a.sta(0x2007)
    a.b(0xC8)                                   # INY
    back(0xD0, "nt_loop")
    a.b(0xE6, 0x11, 0xCA)                       # INC $11; DEX
    back(0xD0, "nt_loop")
    a.lda(0x00); a.b(0x85, 0x00)                # the frame count, from 0
    a.sta(0x2005); a.sta(0x2005)
    a.lda(0x80); a.sta(0x2000)                  # NMI on
    a.lda(0x0A); a.sta(0x2001)                  # the background, all of it
    a.label("forever")
    jmp("forever")

    # The NMI: the flash and the beep together.
    a.label("nmi")
    a.b(0x48)                                   # PHA
    a.b(0x8A, 0x48)                             # TXA; PHA
    a.b(0xA5, 0x00)                             # LDA $00
    a.bne("not_start")
    a.b(0xA2, WHITE)                            # LDX #$30
    a.jsr_label("set_back")
    a.lda(0x01); a.sta(0x4015)                  # pulse 1 on
    a.lda(0xBF); a.sta(0x4000)                  # 50%, held, constant volume 15
    a.lda(0x08); a.sta(0x4001)                  # no sweep
    a.lda(253); a.sta(0x4002)                   # 440 Hz
    a.lda(0x00); a.sta(0x4003)                  # starts it
    jmp("count")
    a.label("not_start")
    a.cmp(FLASH_FRAMES)
    a.bne("count")
    a.b(0xA2, PALETTE[0])                       # LDX #black
    a.jsr_label("set_back")
    a.lda(0x00); a.sta(0x4015)                  # silence
    a.label("count")
    a.b(0xE6, 0x00, 0xA5, 0x00)                 # INC $00; LDA $00
    a.cmp(FLASH_EVERY)
    a.bne("out")
    a.lda(0x00); a.b(0x85, 0x00)
    a.label("out")
    a.b(0x68, 0xAA, 0x68, 0x40)                 # PLA; TAX; PLA; RTI

    # The background colour = X, then the scroll put back.
    a.label("set_back")
    a.b(0x2C, 0x02, 0x20)
    a.lda(0x3F); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.b(0x8E, 0x07, 0x20)                       # STX $2007
    a.lda(0x00); a.sta(0x2006); a.sta(0x2006); a.sta(0x2005); a.sta(0x2005)
    a.lda(0x80); a.sta(0x2000)
    a.rts()
    a.label("rti")
    a.b(0x40)

    a.label("palette")
    a.b(*PALETTE)
    a.label("table")
    a.b(*nametable())
    # The table's address, split for the two LDA #s.
    t = a.labels["table"]
    fixed = []
    for pos, name in a.fix:
        if name == "lo:table":
            a.code[pos] = t & 0xFF
        elif name == "hi:table":
            a.code[pos] = t >> 8
        else:
            fixed.append((pos, name))
    a.fix = fixed
    return a


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "av_sync.nes")
    a = program()
    code = a.done()
    prg = bytearray(0x4000)
    assert len(code) < 0x3FF0
    prg[:len(code)] = code
    for vec, label in ((0x3FFA, "nmi"), (0x3FFC, "reset"), (0x3FFE, "rti")):
        prg[vec], prg[vec + 1] = a.labels[label] & 0xFF, a.labels[label] >> 8
    header = bytes([0x4E, 0x45, 0x53, 0x1A, 1, 1, 0, 0]) + bytes(8)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "wb") as f:
        f.write(header + bytes(prg) + chr_rom())
    print("wrote", out)


if __name__ == "__main__":
    main()
