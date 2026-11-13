#!/usr/bin/env python3
"""Write tests/nsf_banks.nsf: an NSF bank-switching test made for nesrecomp.
Run it again to regenerate it.

From the nesdev wiki's "NSF": when any of the header bytes $70-$77 is
non-zero, $8000-$FFFF is eight 4 KB slots, slot i set by writing a bank
number to $5FF8 + i, and those header bytes are the banks each slot
starts with. The file's data is cut into 4 KB banks starting from the
load address's offset within 4 KB (here $100: the file's first byte is
byte $100 of bank 0).

Twelve banks, each with its number at offset $FF0. The test runs in init
(in bank 11, slot $F000) and reports through the blargg $6000 protocol:
   0  passed
   2  a slot doesn't hold the header's starting bank
   3  after $5FF9 = 7, $9000 doesn't hold bank 7, or $8000 (the other
      half of the same 8 KB) changed too
   4  the same address in two banks: JSR $9000 with bank 7 there and
      then bank 8 didn't run each bank's own code
   5  code at $A000 switching its own slot ($5FFA) didn't carry on in
      the new bank's code
   6  the load offset: the file's first byte isn't at $x100 of bank 0

tests/nsf_rate.nsf and tests/nsf_rate_pal.nsf: the play rate, for the
"tones" check. Each play call flips the DMC's output level ($4011)
between $00 and $40, so the sound is a square wave at half the play
rate; then, after a pause, the same flipping every second call, at a
quarter of the rate. The header asks for a play call every 1136 us
(880 Hz, so notes of 440.1 and 220.1 Hz):
  nsf_rate.nsf      NTSC field 1136 us, PAL field 3000 us, an NTSC NSF
  nsf_rate_pal.nsf  NTSC field 3000 us, PAL field 1136 us, PAL only:
                    the PAL rate must be used
A player using the wrong field plays 166.7 and 83.3 Hz.

tests/nsf_two_chips.nsf: an NSF with two expansion chips (VRC6 and 5B,
header byte $7B = $21), whose outputs must both reach the mix: an APU
note (the reference), a VRC6 pulse (as loud as the APU's, as in
vrc6_tones), then a 5B square (loudness not compared).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_mmc1_test import Asm  # noqa: E402
from make_tone_test import tone_nsf  # noqa: E402
import make_fme7_test  # noqa: E402
import make_vrc6_test  # noqa: E402

BANKS = 12
START = [3, 9, 2, 10, 4, 5, 6, 11]      # slot -> starting bank
LOAD = 0x8100
TAG = 0xFF0
FIRST = 0x5A                            # the file's first byte


def put(image, bank, offset, code):
    at = bank * 0x1000 + offset
    image[at:at + len(code)] = code


def build():
    image = bytearray(BANKS * 0x1000)
    for b in range(BANKS):
        image[b * 0x1000 + TAG] = b
    image[0x100] = FIRST

    # Same address, different code: $9000 in banks 7 and 8.
    for bank, value in ((7, 0x70), (8, 0x80)):
        r = Asm(0x9000)
        r.lda(value); r.rts()
        put(image, bank, 0, r.done())
    # Code that switches its own slot: at $A000 in bank 2, it maps bank 1
    # there; the next instruction ($A005) comes from bank 1.
    r = Asm(0xA000)
    r.lda(1); r.sta(0x5FFA)
    r.lda(0x22); r.rts()                # bank 2 carrying on: wrong
    put(image, 2, 0, r.done())
    r = Asm(0xA005)
    r.lda(0x11); r.rts()                # bank 1: right
    put(image, 1, 5, r.done())

    a = Asm(0xF000)
    a.label("init")
    a.b(0x78, 0xD8)                     # SEI; CLD
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)
    a.lda(0x00); a.sta(0x6004)
    for s, bank in enumerate(START):
        a.check(0x8000 + s * 0x1000 + TAG, bank, "fail2")
    a.lda(7); a.sta(0x5FF9)
    a.check(0x9000 + TAG, 7, "fail3")
    a.check(0x8000 + TAG, START[0], "fail3")
    a.jsr(0x9000); a.cmp(0x70); a.bne("fail4")
    a.lda(8); a.sta(0x5FF9)
    a.jsr(0x9000); a.cmp(0x80); a.bne("fail4")
    a.jsr(0xA000); a.cmp(0x11); a.bne("fail5")
    a.lda(0); a.sta(0x5FFB)             # bank 0 at $B000
    a.check(0xB100, FIRST, "fail6")
    a.label("pass")
    for status in (0, 2, 3, 4, 5, 6):
        if status:
            a.label("fail%d" % status)
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)
    a.label("play")
    a.rts()
    a.label("vector")
    a.b(0x40)                           # RTI
    code = a.done()
    assert len(code) < TAG
    put(image, 11, 0, code)
    for vec in (0xFFA, 0xFFC, 0xFFE):
        t = a.labels["vector"]
        put(image, 11, vec, bytes([t & 0xFF, t >> 8]))

    init, play = a.labels["init"], a.labels["play"]
    header = bytearray(0x80)
    header[0:5] = b"NESM\x1a"
    header[5] = 1                       # version
    header[6] = 1                       # songs
    header[7] = 1                       # starting song
    for at, v in ((8, LOAD), (10, init), (12, play), (0x6E, 16639)):
        header[at], header[at + 1] = v & 0xFF, v >> 8
    header[0x0E:0x0E + 9] = b"nsf_banks"
    header[0x2E:0x2E + 9] = b"nesrecomp"
    header[0x70:0x78] = bytes(START)
    return bytes(header) + bytes(image[LOAD & 0xFFF:])


RATE_US = 1136
OTHER_US = 3000
STATE, LEFT, LEVEL = 0x10, 0x11, 0x13   # zero page: phase, calls left (16 bits)


def rate_nsf(ntsc_us, pal_us, pal_only):
    calls = 1e6 / RATE_US                       # play calls a second
    phases = [int(0.5 * calls), int(0.3 * calls), int(0.5 * calls)]
    a = Asm(0x8000)
    a.label("init")
    a.lda(0); a.b(0x85, STATE, 0x85, LEVEL)
    a.lda(phases[0] & 0xFF); a.b(0x85, LEFT)
    a.lda(phases[0] >> 8); a.b(0x85, LEFT + 1)
    a.rts()

    a.label("flip")                             # LEVEL ^= $40 -> $4011
    a.b(0xA5, LEVEL, 0x49, 0x40, 0x85, LEVEL); a.sta(0x4011)
    a.rts()

    a.label("play")
    a.b(0xA5, STATE)                            # LDA STATE
    a.cmp(0); a.bne("not0")
    a.jsr_label("flip")                         # note 1: every call
    a.b(0x4C); a.fix.append((len(a.code), "tick")); a.b(0, 0)
    a.label("not0")
    a.cmp(2); a.bne("tick")                     # 1: the pause
    a.b(0xA5, LEFT, 0x29, 0x01)                 # note 2: every second call
    a.bne("tick")
    a.jsr_label("flip")
    a.label("tick")                             # 16-bit LEFT -= 1
    a.b(0xA5, STATE); a.cmp(3); a.bne("count")
    a.rts()                                     # 3: done, silent
    a.label("count")
    a.b(0xA5, LEFT); a.bne("low")
    a.b(0xC6, LEFT + 1)                         # DEC LEFT+1
    a.label("low")
    a.b(0xC6, LEFT)                             # DEC LEFT
    a.b(0xA5, LEFT, 0x05, LEFT + 1)             # LDA LEFT; ORA LEFT+1
    a.bne("out")
    a.b(0xE6, STATE)                            # next phase
    a.b(0xA6, STATE)                            # LDX STATE
    a.b(0xBD); a.fix.append((len(a.code), "lo")); a.b(0, 0)   # LDA lo,X
    a.b(0x85, LEFT)
    a.b(0xBD); a.fix.append((len(a.code), "hi")); a.b(0, 0)   # LDA hi,X
    a.b(0x85, LEFT + 1)
    a.label("out")
    a.rts()
    a.label("lo")
    a.b(*[p & 0xFF for p in phases], 1)
    a.label("hi")
    a.b(*[p >> 8 for p in phases], 0)
    a.label("vector")
    a.b(0x40)
    code = a.done()

    prg = bytearray(0x8000)
    prg[:len(code)] = code
    t = a.labels["vector"]
    for vec in (0x7FFA, 0x7FFC, 0x7FFE):
        prg[vec], prg[vec + 1] = t & 0xFF, t >> 8
    header = bytearray(0x80)
    header[0:5] = b"NESM\x1a"
    header[5], header[6], header[7] = 1, 1, 1
    for at, v in ((8, 0x8000), (10, a.labels["init"]), (12, a.labels["play"]),
                  (0x6E, ntsc_us), (0x78, pal_us)):
        header[at], header[at + 1] = v & 0xFF, v >> 8
    header[0x0E:0x0E + 8] = b"nsf_rate"
    header[0x2E:0x2E + 9] = b"nesrecomp"
    header[0x7A] = 1 if pal_only else 0
    return bytes(header) + bytes(prg)


def main():
    path = os.path.join(HERE, "nsf_banks.nsf")
    with open(path, "wb") as f:
        f.write(build())
    print("wrote", path)
    for name, ntsc, pal, pal_only in (("nsf_rate", RATE_US, OTHER_US, False),
                                      ("nsf_rate_pal", OTHER_US, RATE_US, True)):
        path = os.path.join(HERE, name + ".nsf")
        with open(path, "wb") as f:
            f.write(rate_nsf(ntsc, pal, pal_only))
        print("wrote", path)
    hz = 1e6 / RATE_US
    print("expected: %.1f@1,%.1f@-" % (hz / 2, hz / 4))
    vrc6 = make_vrc6_test.tone_notes(24)
    fme = make_fme7_test.tone_notes()
    notes = [vrc6[0], vrc6[1], (fme[1][0], fme[1][1].split("@")[0] + "@-")]
    tone_nsf(os.path.join(HERE, "nsf_two_chips.nsf"), [n for n, _ in notes],
             chips=0x21, setup=[(0x9003, 0x00)])
    print("expected:", ",".join(e for _, e in notes))


if __name__ == "__main__":
    main()
