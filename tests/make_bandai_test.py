#!/usr/bin/env python3
"""Write the Bandai FCG / LZ93D50 tests (mapper 16) made for nesrecomp
(PLAN-mappers3.md step 4). Run it again to regenerate the ROMs.

  tests/bandai_fcg.nes   NES 2.0 submapper 4: the FCG-1/2, registers at
                         $6000-$7FFF, IRQ counter written directly
  tests/bandai_lz.nes    NES 2.0 submapper 5: the LZ93D50, registers at
                         $8000-$FFFF, IRQ latch, a 24C02 EEPROM (256
                         bytes of battery RAM in the header)
  tests/bandai_both.nes  iNES 1.0 (no submapper): both chips decoded,
                         each in its own range; no EEPROM

Each has 128 KB PRG (eight 16 KB banks, the byte at offset $3F00 of each
holding its number) and 128 KB CHR (128 1 KB banks, byte 0 of each
holding its number); the program runs from the fixed last 16 KB.

From the nesdev wiki ("INES Mapper 016"): registers by address AND $000F
(the FCG's range AND $E00F, the LZ93D50's AND $800F): 0-7 CHR, 8 PRG
(bits 0-3), 9 mirroring (0 vertical, 1 horizontal, 2/3 one-screen),
A IRQ enable (any write acknowledges; the LZ93D50 also copies the latch
to the counter), B/C the counter (FCG) or latch (LZ93D50). The counter
counts down every CPU cycle, and a cycle that finds it at 0 raises the
IRQ.

The IRQ checks find the cycle from which instruction it interrupts: the
enabling STA writes on its last cycle (call it cycle 0); the counter's
clocks are cycles 1, 2, ...; with counter C, clock C+1 finds it at 0. A
run of NOPs follows (NOP i takes cycles 2i+1 and 2i+2), and the CPU takes
the IRQ after an instruction whose next-to-last cycle saw the line low:
after NOP i for the first i with 2i+1 >= C+1, so it returns to NOP
i+1 = ceil(C/2)+1. Counters 20 and 21 land on different NOPs, so a
counter one cycle early or late moves one of them.

The EEPROM checks (bandai_lz.nes) speak the 24C02's I2C through $800D
(bit 5 SCL, bit 6 SDA, bit 7 lets SDA go to read) and read bit 4 of
$6000. At the start the program reads EEPROM byte $40 and writes what it
found to the test text ("EEPROM $40: BLANK" for $00, "KEPT" for $5A,
"OTHER"); later it writes $5A there. tests/check_bandai_save.py runs it
twice with its .sav to see the byte kept.

Status codes:
  0  passed
  2  at power-on, $8000 isn't PRG bank 0 or $C000 isn't the last bank
  3  register 8 = 5: $8000 isn't bank 5, or $C000 moved
  4  registers 0-7 = $10-$17: CHR $0000-$1C00 aren't banks $10-$17
  5  register 9 = 0 didn't give vertical mirroring
  6  register 9 = 1 didn't give horizontal mirroring
  7  register 9 = 2 / 3 didn't give one screen, the first / second page
     (the first: what $2000 showed with horizontal mirroring)
  8  the other chip's range: (fcg, at $7F00-$7F0F) a write to $8008 switched PRG;
     (lz) a write to $6008 switched PRG; (both) a write to $6008 didn't
  9  the register at another address (FCG: $6008, as well as $7F08; the
     LZ93D50: $FFF8 for $8008) didn't switch PRG
 10  IRQ, counter 20: didn't return to NOP 11 (one cycle off, or none)
 11  IRQ, counter 21: didn't return to NOP 12
 12  IRQ, enabled with the counter at 0: didn't fire at once (NOP 1)
 13  (fcg, both at $6000) B/C written while counting didn't change the
     counter (the IRQ came); (lz) they did (it didn't come)
 14  enabled then disabled at once: the IRQ came anyway
 15  (lz) the EEPROM didn't acknowledge its device byte $A0
 16  (lz) it didn't acknowledge the word address or a data byte
 17  (lz) reading $FE, $FF back didn't give $11, $22
 18  (lz) the third byte written from $FE didn't wrap to $F8 (the 8-byte
     page)
 19  (lz) the device byte $B0 (not the EEPROM's) was acknowledged
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mappers3_common import Asm, HERE, ppu_write, ppu_check  # noqa: E402

PRG_BANKS = 8                   # 16 KB
CHR_BANKS = 128                 # 1 KB
ID = 0x3F00                     # offset of the bank's number in each 16 KB
NOPS = 40
CONT, RET, ACK = 0xF0, 0xF2, 0xF4   # zero page: continuation, IRQ's return, A register
EE_BYTE, EE_ACK = 0xE0, 0xE1
TEXT = {"BLANK": 0x00, "KEPT": 0x5A}


def start(a):
    a.b(0x78, 0xA2, 0xFF, 0x9A)                 # SEI; LDX #$FF; TXS
    a.lda(0x40); a.sta(0x4017)                  # no APU frame IRQ
    a.lda_abs(0x4015)
    a.lda(0x80); a.sta(0x6000)
    for i, v in enumerate((0xDE, 0xB0, 0x61)):
        a.lda(v); a.sta(0x6001 + i)
    a.lda(0x00); a.sta(0x6004)


def jmp(a, label):
    a.b(0x4C, 0, 0)
    a.fix.append((len(a.code) - 2, label))


def irq_check(a, base, counter, status, expect, b_c_after=None):
    """Enable the IRQ at `base` (the chip's $x000) with `counter` in B/C,
    then NOPs. expect: the NOP the IRQ returns to, "none" or "any"."""
    lo = len(a.code)
    a.lda(0); a.b(0x85, CONT); a.lda(0); a.b(0x85, CONT + 1)
    a.lda((base + 0xA) & 0xFF); a.b(0x85, ACK)
    a.lda((base + 0xA) >> 8); a.b(0x85, ACK + 1)
    a.lda(0); a.sta(base + 0xA)                 # off (the FCG's counter is written while off)
    a.lda(counter & 0xFF); a.sta(base + 0xB)
    a.lda(counter >> 8); a.sta(base + 0xC)
    a.b(0x58)                                   # CLI
    a.lda(1); a.sta(base + 0xA)
    if b_c_after == "off":
        a.lda(0); a.sta(base + 0xA)
    elif b_c_after:
        a.lda(0xFF); a.sta(base + 0xB); a.sta(base + 0xC)
    nop0 = a.pc()
    a.b(*([0xEA] * NOPS))
    if expect == "none":
        a.b(0x78)                               # SEI: as it should be
        a.lda(0); a.sta(base + 0xA)
        jmp(a, "after%d" % status)
    else:
        jmp(a, "fail%d" % status)
    cont = a.pc()
    a.code[lo + 1] = cont & 0xFF
    a.code[lo + 5] = cont >> 8
    if expect == "none":
        jmp(a, "fail%d" % status)
    elif expect != "any":
        want = nop0 + expect
        a.lda_abs(RET); a.cmp(want & 0xFF); a.bne("fail%d" % status)
        a.lda_abs(RET + 1); a.cmp(want >> 8); a.bne("fail%d" % status)
    a.label("after%d" % status)


# --- the EEPROM's I2C, through $800D: bit 5 SCL, bit 6 SDA, bit 7 release
def ee_lines(a, *values):
    for v in values:
        a.lda(v); a.sta(0x800D)


def ee_routines(a):
    a.label("ee_start")
    ee_lines(a, 0x40, 0x60, 0x20, 0x00)         # SDA falls while SCL is high
    a.rts()
    a.label("ee_stop")
    ee_lines(a, 0x00, 0x20, 0x60)               # SDA rises while SCL is high
    a.rts()
    a.label("ee_send")                          # A: the byte; EE_ACK: 0 if acked
    a.b(0x85, EE_BYTE)
    for _ in range(8):
        a.b(0x06, EE_BYTE)                      # ASL: the top bit to C
        a.lda(0x00); a.b(0x90, 2); a.lda(0x40)  # SDA = C
        a.sta(0x800D)
        a.b(0x09, 0x20); a.sta(0x800D)          # SCL up
        a.b(0x29, 0x40); a.sta(0x800D)          # SCL down
    ee_lines(a, 0x80, 0xA0)                     # let go; the ninth clock
    a.lda_abs(0x6000); a.b(0x29, 0x10); a.b(0x85, EE_ACK)
    ee_lines(a, 0x80)
    a.rts()
    a.label("ee_recv")                          # A: the byte
    a.lda(0); a.b(0x85, EE_BYTE)
    for _ in range(8):
        ee_lines(a, 0x80, 0xA0)
        a.lda_abs(0x6000); a.b(0x29, 0x10); a.cmp(0x10)
        a.b(0x26, EE_BYTE)                      # ROL
    ee_lines(a, 0x80)
    a.b(0xA5, EE_BYTE)
    a.rts()
    a.label("ee_ack")                           # the program acknowledges
    ee_lines(a, 0x00, 0x20, 0x00)
    a.rts()
    a.label("ee_nack")
    ee_lines(a, 0x80, 0xA0, 0x80)
    a.rts()


def ee_send(a, value, fail):
    a.lda(value); a.jsr_label("ee_send")
    if fail:
        a.b(0xA5, EE_ACK); a.cmp(0); a.bne(fail)


def ee_read_40(a):
    """Read EEPROM byte $40, before the program writes it, into $E2."""
    a.jsr_label("ee_start"); ee_send(a, 0xA0, "fail15"); ee_send(a, 0x40, "fail16")
    a.jsr_label("ee_start"); ee_send(a, 0xA1, "fail15")
    a.jsr_label("ee_recv"); a.b(0x85, 0xE2)
    a.jsr_label("ee_nack"); a.jsr_label("ee_stop")


def ee_text(a):
    """At the end (the checks write RAM at $6008): the text for $40."""
    words = list(TEXT.items()) + [("OTHER", None)]
    for word, value in words:
        if value is not None:
            a.b(0xA5, 0xE2); a.cmp(value)
            a.b(0xF0, 3); jmp(a, "not_" + word)  # BEQ over the JMP
        for i, ch in enumerate(b"EEPROM $40: " + word.encode() + b"\0"):
            a.lda(ch); a.sta(0x6004 + i)
        jmp(a, "text_done")
        a.label("not_" + word)
    a.label("text_done")


def ee_checks(a):
    # Three bytes from $FE: $FE, $FF, then the page wraps to $F8.
    a.jsr_label("ee_start")
    ee_send(a, 0xA0, "fail15"); ee_send(a, 0xFE, "fail16")
    for v in (0x11, 0x22, 0x33):
        ee_send(a, v, "fail16")
    a.jsr_label("ee_stop")
    # Read $FE and $FF back: a dummy write sets the address, then a read.
    a.jsr_label("ee_start")
    ee_send(a, 0xA0, "fail15"); ee_send(a, 0xFE, "fail16")
    a.jsr_label("ee_start"); ee_send(a, 0xA1, "fail15")
    a.jsr_label("ee_recv"); a.cmp(0x11); a.bne("fail17")
    a.jsr_label("ee_ack")
    a.jsr_label("ee_recv"); a.cmp(0x22); a.bne("fail17")
    a.jsr_label("ee_nack"); a.jsr_label("ee_stop")
    a.jsr_label("ee_start")
    ee_send(a, 0xA0, "fail15"); ee_send(a, 0xF8, "fail16")
    a.jsr_label("ee_start"); ee_send(a, 0xA1, "fail15")
    a.jsr_label("ee_recv"); a.cmp(0x33); a.bne("fail18")
    a.jsr_label("ee_nack"); a.jsr_label("ee_stop")
    # Not the EEPROM's device code: no acknowledge.
    a.jsr_label("ee_start")
    ee_send(a, 0xB0, None)
    a.b(0xA5, EE_ACK); a.cmp(0x10); a.bne("fail19")
    a.jsr_label("ee_stop")
    # Byte $40 = $5A, for the next run.
    a.jsr_label("ee_start")
    ee_send(a, 0xA0, "fail15"); ee_send(a, 0x40, "fail16"); ee_send(a, 0x5A, "fail16")
    a.jsr_label("ee_stop")


def program(kind):
    a = Asm(0xC000)
    start(a)
    if kind == "lz":
        ee_read_40(a)
    # The FCG's registers through their mirror at $7F00: at $6000-$6007
    # they'd overwrite this test's status bytes (in RAM there too).
    base = 0x7F00 if kind == "fcg" else 0x8000
    a.check(0x8000 + ID, 0, "fail2")
    a.check(0xC000 + ID, PRG_BANKS - 1, "fail2")
    a.lda(5); a.sta(base + 8)
    a.check(0x8000 + ID, 5, "fail3")
    a.check(0xC000 + ID, PRG_BANKS - 1, "fail3")
    for i in range(8):
        a.lda(0x10 + i); a.sta(base + i)
    for i in range(8):
        ppu_check(a, i * 0x400, 0x10 + i, "fail4")
    a.lda(0); a.sta(base + 9)
    ppu_write(a, 0x2000, 0x11); ppu_write(a, 0x2400, 0x22)
    ppu_check(a, 0x2800, 0x11, "fail5")
    a.lda(1); a.sta(base + 9)
    ppu_write(a, 0x2000, 0x33)
    ppu_check(a, 0x2400, 0x33, "fail6")
    a.lda(2); a.sta(base + 9)
    ppu_check(a, 0x2400, 0x33, "fail7")         # the first page: $33 from $2000 above
    ppu_write(a, 0x2000, 0x44)
    ppu_check(a, 0x2C00, 0x44, "fail7")
    a.lda(3); a.sta(base + 9)
    ppu_write(a, 0x2000, 0x55)
    ppu_check(a, 0x2C00, 0x55, "fail7")
    a.lda(2); a.sta(base + 9)
    ppu_check(a, 0x2400, 0x44, "fail7")
    # The other range.
    if kind == "fcg":
        a.lda(2); a.sta(0x8008); a.check(0x8000 + ID, 5, "fail8")
        a.lda(3); a.sta(0x6008); a.check(0x8000 + ID, 3, "fail9")
    elif kind == "lz":
        a.lda(2); a.sta(0x6008); a.check(0x8000 + ID, 5, "fail8")
        a.lda(3); a.sta(0xFFF8); a.check(0x8000 + ID, 3, "fail9")
    else:
        a.lda(2); a.sta(0x6008); a.check(0x8000 + ID, 2, "fail8")
        a.lda(3); a.sta(0xFFF8); a.check(0x8000 + ID, 3, "fail9")
    irq_check(a, base, 20, 10, 11)
    irq_check(a, base, 21, 11, 12)
    irq_check(a, base, 0, 12, 1)
    if kind == "lz":
        irq_check(a, base, 20, 13, "any", b_c_after=True)
    elif kind == "fcg":
        irq_check(a, base, 20, 13, "none", b_c_after=True)
    else:
        irq_check(a, 0x6000, 20, 13, "none", b_c_after=True)   # $600A-$600C
    irq_check(a, base, 20, 14, "none", b_c_after="off")
    if kind == "lz":
        ee_checks(a)
        ee_text(a)
    statuses = list(range(2, 20 if kind == "lz" else 15))
    for status in [0] + statuses:
        a.label("pass" if status == 0 else "fail%d" % status)
        a.lda(status); a.sta(0x6000)
        here = a.pc()
        a.b(0x4C, here & 0xFF, here >> 8)
    if kind == "lz":
        ee_routines(a)
    # The IRQ handler: note where it returns to, acknowledge, go on.
    a.label("irq")
    a.b(0x68, 0x68, 0x85, RET, 0x68, 0x85, RET + 1)  # PLA (P); PLA; STA; PLA; STA
    a.lda(0); a.b(0xA0, 0, 0x91, ACK)                 # LDY #0; STA (ACK),Y
    a.b(0x6C, CONT, 0)                                # JMP (CONT)
    a.label("nmi")
    a.b(0x40)
    return a.labels, a.done()


def header(kind):
    f6, f7 = 0x00, 0x10                         # mapper 16, horizontal arrangement
    if kind == "both":
        return bytes([0x4E, 0x45, 0x53, 0x1A, PRG_BANKS, CHR_BANKS // 8, f6, f7]) + bytes(8)
    sub, nvram = (4, 0) if kind == "fcg" else (5, 2)    # 64 << 2 = 256 bytes
    return bytes([0x4E, 0x45, 0x53, 0x1A, PRG_BANKS, CHR_BANKS // 8,
                  f6 | (2 if nvram else 0), f7 | 0x08, sub << 4, 0,
                  0x07 | nvram << 4,             # 8 KB PRG RAM (+ battery RAM)
                  0, 0, 0, 0, 0])


def main():
    for kind in ("fcg", "lz", "both"):
        labels, code = program(kind)
        prg = bytearray(PRG_BANKS * 0x4000)
        for bank in range(PRG_BANKS):
            prg[bank * 0x4000 + ID] = bank
        base = (PRG_BANKS - 1) * 0x4000
        assert len(code) < ID, len(code)
        prg[base:base + len(code)] = code
        for vec, label in ((0xFFFA, "nmi"), (0xFFFC, None), (0xFFFE, "irq")):
            target = labels[label] if label else 0xC000
            prg[base + vec - 0xC000] = target & 0xFF
            prg[base + vec - 0xC000 + 1] = target >> 8
        chr_rom = bytearray(CHR_BANKS * 0x400)
        for bank in range(CHR_BANKS):
            chr_rom[bank * 0x400] = bank
        out = os.path.join(HERE, "bandai_%s.nes" % kind)
        with open(out, "wb") as f:
            f.write(header(kind) + bytes(prg) + bytes(chr_rom))
        print("wrote", out)


if __name__ == "__main__":
    main()
