#!/usr/bin/env python3
"""Write tests/mmc3_split.nes: an MMC3 "status bar" picture made for
nesrecomp (PLAN-savestates.md step 1). Run it again to regenerate it.

What games do with the MMC3's scanline IRQ, every frame: the counter is
reloaded in vblank (latch 23), and each time it runs out, the IRQ
handler moves the horizontal scroll, so the picture is a stack of
24-line bands, each shifted 12 pixels more than the one above, and the
whole picture slides one pixel a frame. A wrong IRQ counter puts the
band edges on other lines, which shows in the picture.

It exists for the save-state test (tests/check_states.py): the MMC3 test
ROMs use the IRQ only in short bursts, so a state saved mid-run never
caught a forgotten counter. In the suite it's a "frame" test: a
regression check of the picture, not a correctness check.

32 KB PRG (the program in the fixed last 8 KB at $E000), 8 KB CHR ROM:
tile 0 blank, tiles 1-4 four patterns. The background reads $0000 and
sprites $1000 (all hidden), so the PPU's sprite fetches clock the
counter once a line.
"""
from mappers3_common import Asm, write_nes

FRAME, SPLIT, TMP = 0x20, 0x21, 0x22        # zero page
CTRL = 0x88                                 # NMI on, sprites at $1000


def program():
    a = Asm(0xE000)
    def lda_zp(z): a.b(0xA5, z)
    def sta_zp(z): a.b(0x85, z)
    def inc_zp(z): a.b(0xE6, z)
    def back(op, name):                 # a short branch back to a label
        off = a.labels[name] - (a.pc() + 2)
        assert -128 <= off < 0
        a.b(op, off & 0xFF)
    def wait_vblank():
        a.b(0x2C, 0x02, 0x20, 0x10, 0xFB)   # BIT $2002; BPL back

    a.label("reset")
    a.b(0x78, 0xD8, 0xA2, 0xFF, 0x9A)       # SEI CLD LDX #$FF TXS
    a.lda(0x40); a.sta(0x4017)              # no APU frame IRQ
    a.lda(0); a.sta(0x2000); a.sta(0x2001)
    wait_vblank(); wait_vblank()
    # CHR: R0, R1 = 2 KB banks 0 and 2; R2-R5 = 1 KB banks 4-7. PRG
    # banks 0 and 1 at $8000 and $A000. Horizontal mirroring.
    for reg, bank in enumerate((0, 2, 4, 5, 6, 7, 0, 1)):
        a.lda(reg); a.sta(0x8000)
        a.lda(bank); a.sta(0x8001)
    a.lda(1); a.sta(0xA000)
    # The palette: black, red, green, blue.
    a.lda_abs(0x2002)
    a.lda(0x3F); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    for v in (0x0F, 0x16, 0x2A, 0x12):
        a.lda(v); a.sta(0x2007)
    # Name table 0: tiles 1-4 by column, in 8-pixel stripes; then a
    # blank attribute table.
    a.lda_abs(0x2002)
    a.lda(0x20); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    a.b(0xA0, 0x04)                         # LDY #4 (pages)
    a.b(0xA2, 0x00)                         # LDX #0
    a.label("fill")
    a.b(0x8A, 0x29, 0x03, 0x18, 0x69, 0x01) # TXA AND #3 CLC ADC #1
    a.sta(0x2007)
    a.b(0xE8); back(0xD0, "fill")           # INX; BNE fill
    a.b(0x88); back(0xD0, "fill")           # DEY; BNE fill
    a.lda_abs(0x2002)
    a.lda(0x23); a.sta(0x2006); a.lda(0xC0); a.sta(0x2006)
    a.lda(0); a.b(0xA2, 0x40)               # LDX #64
    a.sta(0x2007); a.b(0xCA, 0xD0, 0xFA)    # STA $2007; DEX; BNE
    # Every sprite below the screen.
    a.lda(0); a.sta(0x2003)
    a.lda(0xFF); a.b(0xA2, 0x00)
    a.sta(0x2004); a.b(0xCA, 0xD0, 0xFA)    # 256 times
    a.lda(0); sta_zp(FRAME); sta_zp(SPLIT)
    a.lda(23); a.sta(0xC000)                # latch: every 24 lines
    a.sta(0xC001)
    a.sta(0xE001)                           # IRQ on
    wait_vblank()
    a.lda(CTRL); a.sta(0x2000)
    a.lda(0x1E); a.sta(0x2001)              # background and sprites on
    a.b(0x58)                               # CLI
    a.label("loop")
    here = a.pc()
    a.b(0x4C, here & 0xFF, here >> 8)

    # Vblank: the next frame starts one pixel further, from band 0.
    a.label("nmi")
    a.b(0x48)                               # PHA
    inc_zp(FRAME)
    a.lda(0); sta_zp(SPLIT)
    a.lda_abs(0x2002)
    lda_zp(FRAME); a.sta(0x2005)
    a.lda(0); a.sta(0x2005)
    a.lda(CTRL); a.sta(0x2000)
    a.sta(0xC001)                           # reload at the next clock
    a.b(0x68, 0x40)                         # PLA RTI

    # The counter ran out: scroll the next band FRAME + 12 * band.
    a.label("irq")
    a.b(0x48)                               # PHA
    inc_zp(SPLIT)
    lda_zp(SPLIT); a.b(0x0A, 0x0A)          # x4
    sta_zp(TMP); a.b(0x0A)                  # x8
    a.b(0x18, 0x65, TMP)                    # CLC; ADC TMP: x12
    a.b(0x18, 0x65, FRAME)                  # CLC; ADC FRAME
    a.b(0x2C, 0x02, 0x20)                   # BIT $2002 (keeps A)
    a.sta(0x2005)
    a.lda(0); a.sta(0x2005)
    a.sta(0xE000)                           # acknowledge
    a.sta(0xE001)                           # and on again
    a.b(0x68, 0x40)                         # PLA RTI
    return a


def chr_rom():
    chr_ = bytearray(0x2000)
    tiles = {
        1: ([0xF0] * 8, [0x00] * 8),        # red left half
        2: ([0x00] * 8, [0xFF] * 8),        # green
        3: ([0x80 >> r for r in range(8)], [0x01 << r for r in range(8)]),
        4: ([0xFF] * 8, [0xFF] * 8),        # blue
    }
    for t, (lo, hi) in tiles.items():
        chr_[t * 16:t * 16 + 8] = bytes(lo)
        chr_[t * 16 + 8:t * 16 + 16] = bytes(hi)
    return chr_


def main():
    a = program()
    code = a.done()
    prg = bytearray(0x8000)
    prg[0x6000:0x6000 + len(code)] = code
    for vec, name in ((0x7FFA, "nmi"), (0x7FFC, "reset"), (0x7FFE, "irq")):
        target = a.labels[name]
        prg[vec], prg[vec + 1] = target & 0xFF, target >> 8
    write_nes("mmc3_split.nes", 4, prg, chr_rom())


if __name__ == "__main__":
    main()
