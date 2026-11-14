#!/usr/bin/env python3
"""Write the board variant (NES 2.0 submapper) tests made for nesrecomp,
one ROM per variant (nesdev wiki "NES 2.0 submappers"). Run it again to
regenerate them.

Bus conflicts (submapper 1: none, 2: the written value ANDed with the ROM
byte). Each ROM writes 1 to a ROM byte holding 0, so with conflicts the
board picks bank 0, without them bank 1:
  uxrom_s1/s2.nes   mapper 2, the 16 KB bank at $8000 (tag at $BFF0)
  cnrom_s1/s2.nes   mapper 3, the 8 KB CHR bank (tag at PPU $0000)
  axrom_s1/s2.nes   mapper 7, the 32 KB bank (tag at $BFF0; the same
                    program in both banks)
  1  the bank isn't the one this submapper should pick

  mmc1_s5.nes       mapper 1 submapper 5 (SEROM, SHROM): 32 KB of PRG
                    that never moves. 1: $E000 = 1 moved $8000

VRC2/VRC4 wirings (mappers 21, 23, 25; tags as in make_vrc4_test.py):
  vrc_21_s1/s2, vrc_23_s1/s2, vrc_25_s1/s2.nes   VRC4, one wiring each
  vrc_23_s3, vrc_25_s3.nes                       VRC2b, VRC2c
  1  PRG bank 5 at $8000, through the board's own wiring
  2  CHR bank $13 at PPU $0000, low and high nibble through its wiring
  3  a write to the other wiring's high-nibble address landed as the
     other wiring would decode it (both wirings decoded)
  VRC2 only (no PRG RAM in the header, so the latch answers at $6000):
  4  $9000 = 2 gave one-screen mirroring (VRC4), not vertical
  5  $9002 (register 2) turned on swap mode (VRC4)
  6  the latch: $6000 = 1 reads $61 while $7000 (no RAM) reads $70;
     = $FE reads $60, and $6FFF $6E
  7  an IRQ came (a VRC2 has no IRQ)

VRC7 wirings (mapper 85):
  vrc7_s1.nes  VRC7b (A3): $8008 is the $A000 bank, $8010 the $8000 one
  vrc7_s2.nes  VRC7a (A4): the other way round
  1  the $A000 bank   2  the $8000 bank

Namco 163 loudness (mapper 19): n163_tones_s3/s5.nes, the notes of
n163_tones.nes (make_n163_test.py) at 12 and 18.75 dB. At 18.75 dB the
full-volume squares (notes 2 and 7) clip in the 16-bit output, so they
aren't checked, and the rest are checked against the APU note.

Results are written into the nametable ("PASSED" or "FAILED n") for
--dump-text, as in make_ram_test.py. With --ines1 DIR, the same ROMs get
submapper 0 and are written to DIR, where each must fail.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_ram_test import Test  # noqa: E402
from make_tone_test import tone_rom  # noqa: E402
import make_n163_test  # noqa: E402

COUNT = 0x10                    # zero page: IRQs taken


def header(mapper, sub, prg_kb, chr_kb, prg_ram=0x07, chr_ram=0, nes2=True,
           mirroring=1):
    h = bytearray(b"NES\x1a" + bytes(12))
    h[4], h[5] = prg_kb // 16, chr_kb // 8
    h[6] = (mapper & 0x0F) << 4 | mirroring
    h[7] = mapper & 0xF0
    if nes2:
        h[7] |= 0x08
        h[8] = sub << 4 | mapper >> 8
        h[10], h[11] = prg_ram, chr_ram
    return bytes(h)


def finish(a, checks):
    """PASSED, the FAILED n messages, and the interrupt handlers."""
    a.text("PASSED")
    a.stop()
    for n in checks:
        a.label("f%d" % n)
        a.text("FAILED %d" % n)
        a.stop()
    a.label("nmi")
    a.b(0x40)


def start(a):
    a.label("reset")
    a.b(0x78, 0xD8, 0xA2, 0xFF, 0x9A)           # SEI; CLD; LDX #$FF; TXS
    a.store(0x2000, 0); a.store(0x2001, 0)
    a.store(0x4017, 0x40)                       # no frame IRQ
    for _ in range(2):
        a.b(0x2C, 0x02, 0x20, 0x10, 0xFB)       # BIT $2002; BPL


def vectors(prg, base, a, irq="nmi"):
    """Vectors at the end of the 8 KB at `base` in prg (CPU $E000)."""
    for vec, label in ((0x1FFA, "nmi"), (0x1FFC, "reset"), (0x1FFE, irq)):
        t = a.labels[label]
        prg[base + vec], prg[base + vec + 1] = t & 0xFF, t >> 8


# --- bus conflicts ------------------------------------------------------

def zero_byte(a):
    """Emit a $00 byte in the program (jumped over) and return its address."""
    a.b(0x4C)
    here = a.pc()
    a.b((here + 3) & 0xFF, (here + 3) >> 8)
    zero = a.pc()
    a.b(0x00)
    return zero


def conflict_rom(mapper, sub, nes2=True):
    want = 0 if sub == 2 else 1
    a = Test(0xE000)
    start(a)
    zero = zero_byte(a)
    a.store(zero, 0x01)                         # bank 1, unless conflicts
    if mapper == 3:
        a.ppu_check(0x0000, want, 1)
    else:
        a.check(0xBFF0, want, 1)
    finish(a, [1])
    code = a.done()
    if mapper == 3:                             # 32 KB PRG, 4 x 8 KB CHR
        prg = bytearray(0x8000)
        prg[0x6000:0x6000 + len(code)] = code
        vectors(prg, 0x6000, a)
        chr_ = bytearray(0x8000)
        for b in range(4):
            chr_[b * 0x2000] = b
        return header(3, sub, 32, 32, nes2=nes2) + prg + chr_
    banks = 4 if mapper == 2 else 2             # 16 KB (UxROM), 32 KB (AxROM)
    size = 0x4000 if mapper == 2 else 0x8000
    prg = bytearray(banks * size)
    for b in range(banks):
        prg[b * size + 0x3FF0] = b              # CPU $BFF0 when at $8000
        if mapper == 7 or b == banks - 1:       # the program at $E000
            base = b * size + size - 0x2000
            prg[base:base + len(code)] = code
            vectors(prg, base, a)
    return header(mapper, sub, len(prg) // 1024, 0, chr_ram=0x07,
                  nes2=nes2) + prg


def mmc1_fixed_rom(nes2=True):
    a = Test(0xE000)
    start(a)
    a.store(0x8000, 0x80)
    a.write5(0x8000, 0x0C)                      # PRG mode 3, 8 KB CHR
    a.write5(0xE000, 0x01)                      # would put 16 KB bank 1 at $8000
    a.check(0xBFF0, 0, 1)
    finish(a, [1])
    code = a.done()
    prg = bytearray(0x8000)
    prg[0x3FF0], prg[0x7FF0] = 0, 1             # 16 KB tags
    prg[0x6000:0x6000 + len(code)] = code
    vectors(prg, 0x6000, a)
    return header(1, 5, 32, 0, chr_ram=0x07, nes2=nes2) + prg


# --- VRC2 / VRC4 --------------------------------------------------------

LINES = {21: ((1, 2), (6, 7)), 23: ((0, 1), (2, 3)), 25: ((1, 0), (3, 2))}
TAG = 0x1FF0


def reg_addr(lines, base, reg):
    a0, a1 = lines
    return base | (reg & 1) << a0 | (reg >> 1) << a1


def decode(lines, addr):
    a0, a1 = lines
    return ((addr >> a1) & 1) << 1 | ((addr >> a0) & 1)


def vrc_rom(mapper, sub, nes2=True):
    own = LINES[mapper][0 if sub in (1, 3) else 1]
    other = LINES[mapper][1 if sub in (1, 3) else 0]
    vrc2 = sub == 3
    a = Test(0xE000)
    start(a)
    a.store(reg_addr(own, 0x8000, 0), 5)
    a.check(0x9FF0, 5, 1)
    a.store(reg_addr(own, 0xB000, 0), 3)
    a.store(reg_addr(own, 0xB000, 1), 1)
    a.ppu_check(0x0000, 0x13, 2)
    # The other wiring's address for register 1 ("high nibble of bank 0"):
    # what it is to this board's own wiring.
    addr = reg_addr(other, 0xB000, 1)
    reg = decode(own, addr)
    assert reg in (0, 2), reg                   # never the same register
    want = 0x12 if reg == 0 else 0x13         # both decoded: $23
    a.store(addr, 2)
    a.ppu_check(0x0000, want, 3)
    checks = [1, 2, 3]
    if vrc2:
        a.store(reg_addr(own, 0x9000, 0), 2)    # VRC2: vertical
        a.ppu_store(0x2000, 0x05)               # (not printable: --dump-text)
        a.ppu_store(0x2400, 0x8A)
        a.ppu_check(0x2000, 0x05, 4)
        a.store(reg_addr(own, 0x9000, 2), 2)    # VRC4 would swap
        a.check(0x9FF0, 5, 5)
        a.store(0x6000, 0x01)
        a.check(0x6000, 0x61, 6)
        a.check(0x7000, 0x70, 6)                # not the latch: open bus
        a.store(0x6000, 0xFE)
        a.check(0x6000, 0x60, 6)
        a.check(0x6FFF, 0x6E, 6)
        a.b(0xA9, 0, 0x85, COUNT)               # LDA #0; STA COUNT
        a.store(reg_addr(own, 0xF000, 0), 0x0F)  # latch $FF
        a.store(reg_addr(own, 0xF000, 1), 0x0F)
        a.store(reg_addr(own, 0xF000, 2), 0x06)  # enable, cycle mode
        a.b(0x58)                               # CLI
        a.b(0xA2, 0x00, 0xCA, 0xD0, 0xFD)       # LDX #0; DEX; BNE
        a.b(0x78)                               # SEI
        a.b(0xA5, COUNT); a.cmp(0); a.bne("f7")
        a.store(reg_addr(own, 0x9000, 0), 0)    # vertical again for the text
        checks += [4, 5, 6, 7]
    finish(a, checks)
    a.label("irq")
    a.b(0xE6, COUNT)                            # INC COUNT
    a.store(reg_addr(own, 0xF000, 3), 0)        # acknowledge: stop
    a.b(0x40)
    code = a.done()
    prg = bytearray()
    for bank in range(16):
        b = bytearray(0x2000)
        b[TAG] = bank
        prg += b
    last = 15 * 0x2000
    assert len(code) < TAG
    prg[last:last + len(code)] = code
    vectors(prg, last, a, irq="irq")
    chr_ = bytearray()
    for bank in range(64):
        c = bytearray(0x400)
        c[0] = bank
        chr_ += c
    ram = 0x00 if vrc2 else 0x07
    return header(mapper, sub, 128, 64, prg_ram=ram, nes2=nes2) + prg + chr_


def vrc7_rom(sub, nes2=True):
    a_line, other = (0x8008, 0x8010) if sub == 1 else (0x8010, 0x8008)
    a = Test(0xE000)
    start(a)
    a.store(a_line, 7)                          # the $A000 bank
    a.store(other, 9)                           # to this board: the $8000 bank
    a.check(0xBFF0, 7, 1)
    a.check(0x9FF0, 9, 2)
    finish(a, [1, 2])
    code = a.done()
    prg = bytearray()
    for bank in range(16):
        b = bytearray(0x2000)
        b[TAG] = bank
        prg += b
    last = 15 * 0x2000
    prg[last:last + len(code)] = code
    vectors(prg, last, a)
    return header(85, sub, 128, 8, nes2=nes2) + prg + bytes(0x2000)


# --- Namco 163 loudness -------------------------------------------------

def n163_tones(path, sub, nes2=True):
    notes = make_n163_test.tone_notes()
    tone_rom(path, [n for n, _ in notes], mapper=19,
             setup=make_n163_test.tone_setup())
    data = bytearray(open(path, "rb").read())
    if nes2:
        data[7] |= 0x08
        data[8] = sub << 4
        data[10] = 0x07
    open(path, "wb").write(data)
    # Note 2's level scales with the gain; the others are relative to it.
    # At 18.75 dB note 2 (a full-volume square) clips in the 16-bit
    # output, so there it isn't checked (nor note 7, a full-volume 25%
    # square), and the later notes, otherwise measured against it, are
    # measured against the APU note.
    gain = {3: 3.981, 5: 8.660}[sub] / 6.683
    out = []
    for i, (_, e) in enumerate(notes):
        hz, lv = e.split("@")
        if i == 1:
            full = float(lv) * gain
            e = "%s@%s" % (hz, "-" if sub == 5 else "%.3f" % full)
        elif i == 6 and sub == 5:               # a full-volume square too
            e = "%s@-" % hz
        elif i >= 2 and sub == 5:               # relative to note 2: absolute
            e = "%s@%.3f" % (hz, full * float(lv.split("/")[0]))
        out.append(e)
    return ",".join(out)


def main():
    nes2 = "--ines1" not in sys.argv
    out = HERE if nes2 else sys.argv[sys.argv.index("--ines1") + 1]
    roms = {}
    for m, name in ((2, "uxrom"), (3, "cnrom"), (7, "axrom")):
        for s in (1, 2):
            roms["%s_s%d" % (name, s)] = conflict_rom(m, s, nes2)
    roms["mmc1_s5"] = mmc1_fixed_rom(nes2)
    for m, subs in ((21, (1, 2)), (23, (1, 2, 3)), (25, (1, 2, 3))):
        for s in subs:
            roms["vrc_%d_s%d" % (m, s)] = vrc_rom(m, s, nes2)
    for s in (1, 2):
        roms["vrc7_s%d" % s] = vrc7_rom(s, nes2)
    for name, data in roms.items():
        path = os.path.join(out, name + ".nes")
        with open(path, "wb") as f:
            f.write(data)
    print("wrote %d ROMs to %s" % (len(roms), out))
    for s in (3, 5):
        path = os.path.join(out, "n163_tones_s%d.nes" % s)
        print("n163_tones_s%d expected: %s" % (s, n163_tones(path, s, nes2)))


if __name__ == "__main__":
    main()
