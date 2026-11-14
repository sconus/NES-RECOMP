#!/usr/bin/env python3
"""Write tests/fds_demo.fds: a Famicom Disk System demo to try by hand,
made for nesrecomp, and tests/inputs/fds_demo.txt, a script for the
suite's picture check. Run it again to regenerate both.

    make run ROM=tests/fds_demo.fds

It runs on the project's BIOS and uses most of what this stage added:
  - the boot files: the program, its vectors, the font (a CHR file), a
    message and the saved count;
  - A: loads the other message file from the disk (LoadFiles) and draws
    it (VRAMStructWrite: the message files are VRAM structures);
  - B: adds one to the count and writes it back to the disk (WriteFile;
    the runtime keeps it in tests/fds_demo.fds.sav, so it is still there
    next time);
  - the FDS timer IRQ, started from each NMI, splits the screen: the
    band below the split scrolls sideways;
  - the FDS wavetable plays a tune; Select stops and starts it;
  - VINTWait, the PPUMASK routines, ReadDownPads, SetScroll.

Files (boot code 3): PROGRAM ID 0, VECTORS ID 1, FONT ID 2 (CHR), MSG1
ID 3, MSG2 ID 4 (not a boot file), SAVE ID 1 (last, so writing it hides
nothing).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402
from make_fds_test import disk_info, side_bytes, fds_image  # noqa: E402
from make_split_demo import FONT as SPLIT_FONT, tile  # noqa: E402

CPU_HZ = 1789773
INFO = disk_info(name=b"DMO", boot_code=3)
DISK_ID = INFO[0x0F:0x19]

# Zero page.
PRESS, REQ, SCROLL, NOTE, TICK, MUSIC = 0x10, 0x11, 0x12, 0x13, 0x14, 0x15
WHICH = 0x16                    # the message on screen: 0 MSG1, 1 MSG2
COUNT = 0x0480                  # the saved count (the SAVE file)
MSG = 0x0500                    # where the message files load

FONT = dict(SPLIT_FONT)
FONT.update({
    " ": ["00000"] * 7,
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
    "J": ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    ":": ["00000", "01100", "01100", "00000", "01100", "01100", "00000"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    "!": ["00100", "00100", "00100", "00100", "00100", "00000", "00100"],
})
HEX = "0123456789ABCDEF"
BAR = 0x01                      # a solid tile for the band's edges


def font_chr():
    """The font at tile = ASCII code, colour 3 on 0; tile 1 solid colour 1."""
    c = bytearray(0x1000)
    c[BAR * 16:BAR * 16 + 16] = tile(["11111111"] * 8)
    for ch, rows in FONT.items():
        t = ord(ch) * 16
        c[t:t + 16] = tile(["0" + "".join("3" if b == "1" else "0" for b in r) + "00"
                            for r in rows] + ["00000000"])
    return bytes(c)


def text_record(addr, text):
    return bytes([addr >> 8, addr & 0xFF, len(text)]) + text.encode()


def message(text):
    """A message file: a VRAM structure for row 8, centred, padded."""
    line = text.center(28)
    return text_record(0x2102, line) + b"\xff"


def note_period(hz):
    return round(hz * 2 ** 22 / CPU_HZ)


# A short tune: (Hz, frames); 0 rests.
TUNE = [(523.3, 12), (659.3, 12), (784.0, 12), (1046.5, 24), (784.0, 12), (0, 12),
        (698.5, 12), (880.0, 12), (1046.5, 12), (1174.7, 24), (880.0, 12), (0, 12),
        (659.3, 12), (784.0, 12), (987.8, 12), (1318.5, 24), (987.8, 12), (0, 12),
        (1046.5, 36), (0, 24)]


def program():
    a = Asm(0x6100)

    def w(addr, val):
        a.lda(val); a.sta(addr)

    def zp(addr, val):
        a.lda(val); a.b(0x85, addr)

    def jmp(label):
        a.b(0x4C); a.fix.append((len(a.code), label)); a.b(0, 0)

    def jsr(label):
        a.b(0x20); a.fix.append((len(a.code), label)); a.b(0, 0)

    def word(label):
        a.b(0, 0); a.fix.append((len(a.code) - 2, label))

    def back(op, label):
        a.b(op); a.b((a.labels[label] - (a.pc() + 1)) & 0xFF)

    VINTWAIT, DISPFOBJ, ENPFOBJ, VRAMSTRUCT = 0xE1B2, 0xE161, 0xE16B, 0xE7BB
    LOADFILES, WRITEFILE, READDOWNPADS, SETSCROLL = 0xE1F8, 0xE239, 0xEA1A, 0xEAEA

    a.label("start")
    a.b(0x78, 0xD8)                             # SEI; CLD
    w(0x0100, 0xC0)                             # NMIs to $DFFA
    w(0x0101, 0xC0)                             # IRQs to $DFFE
    for z in (PRESS, REQ, SCROLL, NOTE, TICK, WHICH):
        zp(z, 0)
    zp(MUSIC, 1)
    # The wave: a triangle, written with $4089 bit 7.
    w(0x4089, 0x80)
    for i in range(64):
        w(0x4040 + i, 2 * i if i < 32 else 2 * (63 - i) + 1)
    w(0x4089, 0x00)
    w(0x4080, 0x80 | 0x18)                      # volume, no envelope
    w(0x4087, 0x80)                             # no modulation
    w(0x4083, 0x80)                             # silent until the first note
    # The screen, with rendering off (the BIOS leaves it off).
    jsr("palette")
    a.jsr(VRAMSTRUCT); word("screen")
    a.jsr(VRAMSTRUCT); word("msg_ram")          # MSG1, loaded at boot
    jsr("draw_count")
    # Back on: at the start of a vblank, with the scroll set again (the
    # VRAM writes moved the PPU's address, which it would otherwise draw
    # the rest of the frame from).
    a.label("show")
    zp(0xFC, 0); zp(0xFD, 0)
    zp(0xFF, 0x00)
    a.b(0x2C, 0x02, 0x20)                       # BIT $2002
    a.jsr(VINTWAIT)
    zp(0xFF, 0x80)
    a.jsr(SETSCROLL)                            # $2005 x2, $2000 = $80: NMIs on
    a.jsr(ENPFOBJ)
    a.b(0x58)                                   # CLI (the timer IRQ)
    a.label("main")
    a.b(0xA5, REQ)
    back(0xF0, "main")                          # BEQ main
    # A disk request: off the screen, at vblank.
    a.jsr(VINTWAIT)
    a.jsr(DISPFOBJ)
    w(0x4022, 0x00)                             # the timer off
    a.b(0xA5, REQ, 0x29, 0x02)                  # A (bit 7 -> 1)
    a.b(0xF0, 0x03); jmp("do_load")             # BEQ: not A
    jmp("check_b")
    a.label("do_load")
    a.b(0xA5, WHICH, 0x49, 0x01, 0x85, WHICH)   # the other message
    a.b(0xF0, 0x03); jmp("load_msg2")           # BEQ: back to MSG1
    a.jsr(LOADFILES); word("disk_id"); word("list_msg1")
    jmp("loaded")
    a.label("load_msg2")
    a.jsr(LOADFILES); word("disk_id"); word("list_msg2")
    a.label("loaded")
    a.jsr(VRAMSTRUCT); word("msg_ram")
    a.label("check_b")
    a.b(0xA5, REQ, 0x29, 0x01)                  # B (bit 6 -> 0)
    a.b(0xF0, 0x03); jmp("do_save")
    jmp("done")
    a.label("do_save")
    a.b(0xEE, COUNT & 0xFF, COUNT >> 8)         # INC count
    a.lda(5)                                    # SAVE is file 5
    a.jsr(WRITEFILE); word("disk_id"); word("save_header")
    jsr("draw_count")
    a.label("done")
    zp(REQ, 0)
    jmp("show")

    # NMI: the tune, the pads, the scroll, and the timer for the split.
    a.label("nmi")
    a.b(0x48, 0x8A, 0x48, 0x98, 0x48)           # PHA; TXA; PHA; TYA; PHA
    zp(0xFC, 0); zp(0xFD, 0)
    a.jsr(SETSCROLL)
    # The split: about 156 lines into the picture, just above the band
    # (the timer counts CPU cycles; vblank is 20 lines; 113.67 cycles a
    # line).
    split = int((20 + 156) * 113.67)
    w(0x4020, split & 0xFF); w(0x4021, split >> 8)
    w(0x4022, 0x02)
    a.b(0xE6, SCROLL)                           # INC SCROLL
    a.jsr(READDOWNPADS)
    a.b(0xA5, 0xF5, 0x29, 0xC0)                 # A, B: new presses
    a.b(0xF0, 0x08)
    a.b(0x4A, 0x4A, 0x4A, 0x4A, 0x4A, 0x4A)     # bits 7-6 -> 1-0
    a.b(0x85, REQ)
    # The tune (on unless Select turned it off).
    a.b(0xA5, 0xF5, 0x29, 0x20)                 # Select pressed?
    a.b(0xF0, 0x0D)
    a.b(0xA5, MUSIC, 0x49, 0x01, 0x85, MUSIC)
    a.b(0xD0, 0x05); w(0x4083, 0x80)            # off: stop the wave
    a.b(0xA5, MUSIC)
    a.b(0xF0, 0x03); jsr("tune")
    a.b(0x68, 0xA8, 0x68, 0xAA, 0x68)           # PLA; TAY; PLA; TAX; PLA
    a.b(0x40)                                   # RTI

    a.label("irq")                              # the split: the band scrolls
    a.b(0x48)
    a.lda_abs(0x4030)                           # acknowledge
    a.b(0xA5, SCROLL); a.sta(0x2005)
    a.lda(0x00); a.sta(0x2005)
    a.b(0x68, 0x40)

    a.label("tune")                             # a note every few frames
    a.b(0xA5, TICK)
    a.b(0xF0, 0x03); jmp("tune_wait")
    a.b(0xA6, NOTE)                             # LDX NOTE
    a.b(0xBD, 0, 0); a.fix.append((len(a.code) - 2, "tune_hi"))  # LDA tune_hi,X
    a.sta(0x4083)
    a.b(0xBD, 0, 0); a.fix.append((len(a.code) - 2, "tune_lo"))
    a.sta(0x4082)
    a.b(0xBD, 0, 0); a.fix.append((len(a.code) - 2, "tune_len"))
    a.b(0x85, TICK)
    a.b(0xE8, 0xE0, len(TUNE))                  # INX; CPX #n
    a.b(0xD0, 0x02, 0xA2, 0x00)                 # BNE +2; LDX #0
    a.b(0x86, NOTE)
    a.label("tune_wait")
    a.b(0xC6, TICK)
    a.rts()

    a.label("draw_count")                       # "SAVED: nn" at row 12
    a.b(0x2C, 0x02, 0x20)
    a.lda(0x21); a.sta(0x2006); a.lda(0x8D); a.sta(0x2006)
    a.lda_abs(COUNT); a.b(0x4A, 0x4A, 0x4A, 0x4A, 0xAA)     # LSR x4; TAX
    a.b(0xBD, 0, 0); a.fix.append((len(a.code) - 2, "hex"))
    a.sta(0x2007)
    a.lda_abs(COUNT); a.b(0x29, 0x0F, 0xAA)
    a.b(0xBD, 0, 0); a.fix.append((len(a.code) - 2, "hex"))
    a.sta(0x2007)
    a.rts()

    a.label("palette")
    a.b(0x2C, 0x02, 0x20)
    a.lda(0x3F); a.sta(0x2006); a.lda(0x00); a.sta(0x2006)
    for v in (0x0F, 0x12, 0x22, 0x30, 0x0F, 0x16, 0x26, 0x37) + (0x0F,) * 8:
        w(0x2007, v)
    a.rts()

    a.label("rti")
    a.b(0x40)
    a.label("hex")
    a.b(*HEX.encode())
    a.label("disk_id")
    a.b(*DISK_ID)
    a.label("list_msg1")
    a.b(3, 0xFF)
    a.label("list_msg2")
    a.b(4, 0xFF)
    a.label("save_header")
    a.b(1, *b"SAVE    ", COUNT & 0xFF, COUNT >> 8, 1, 0, 0,
        COUNT & 0xFF, COUNT >> 8, 0)
    a.labels["msg_ram"] = MSG
    a.label("tune_lo")
    a.b(*[note_period(hz) & 0xFF for hz, _ in TUNE])
    a.label("tune_hi")
    a.b(*[(note_period(hz) >> 8) if hz else 0x80 for hz, _ in TUNE])
    a.label("tune_len")
    a.b(*[n for _, n in TUNE])
    a.label("screen")
    rec = b""
    rec += text_record(0x2088, "FAMICOM DISK SYSTEM")
    rec += text_record(0x20CB, "NESRECOMP")
    rec += text_record(0x2186, "SAVED:")
    rec += text_record(0x21C4, "A: LOAD THE OTHER FILE")
    rec += text_record(0x2204, "B: SAVE THE COUNT")
    rec += text_record(0x2244, "SELECT: MUSIC")
    # The band below the split (rows 20-26): edges and scrolling text.
    rec += bytes([0x22, 0x80, 0x40 | 32, BAR])          # row 20
    rec += text_record(0x22C0, "TIMER IRQ SPLIT " * 2)
    rec += text_record(0x2320, "FDS DISK SYSTEM " * 2)
    rec += bytes([0x23, 0x60, 0x40 | 32, BAR])          # row 27
    # Attributes: the band in palette 1.
    rec += bytes([0x23, 0xE8, 0x40 | 16, 0x55])
    a.b(*rec, 0xFF)
    return a


def vectors(a):
    rti, nmi, start, irq = (a.labels[k] for k in ("rti", "nmi", "start", "irq"))
    return bytes([rti & 0xFF, rti >> 8, rti & 0xFF, rti >> 8, nmi & 0xFF, nmi >> 8,
                  start & 0xFF, start >> 8, irq & 0xFF, irq >> 8])


def main():
    a = program()
    code = a.done()
    assert 0x6100 + len(code) <= 0x8000
    files = [
        (0, "PROGRAM", 0x6100, 0, code),
        (1, "VECTORS", 0xDFF6, 0, vectors(a)),
        (2, "FONT", 0x0000, 1, font_chr()),
        (3, "MSG1", MSG, 0, message("HELLO FROM DISK FILE ONE")),
        (4, "MSG2", MSG, 0, message("AND THIS IS FILE TWO!")),
        (1, "SAVE", COUNT, 0, b"\x00"),
    ]
    path = os.path.join(HERE, "fds_demo.fds")
    with open(path, "wb") as f:
        f.write(fds_image([side_bytes(INFO, files)]))
    print("wrote", path)
    script = os.path.join(HERE, "inputs", "fds_demo.txt")
    with open(script, "w") as f:
        f.write("# tests/fds_demo.fds (make_fds_demo.py): load the other message (A),\n"
                "# save the count twice (B), stop the music (Select).\n"
                "100 a\n106\n150 b\n156\n200 b\n206\n250 select\n256\n")
    print("wrote", script)


if __name__ == "__main__":
    main()
