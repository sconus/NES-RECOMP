#!/usr/bin/env python3
"""Write tests/camerica_switch.nes: a Camerica / Codemasters (mapper 71)
test made for nesrecomp (PLAN-mappers3.md step 1). Run it again to
regenerate the ROM.

128 KB PRG (eight 16 KB banks), 8 KB CHR RAM, vertical mirroring in the
header, no submapper (iNES 1.0). The program runs in the last bank,
fixed at $C000 (every bank holds a copy, so a wrongly switched $C000
reports status 5 instead of crashing); byte $BFF0 of each bank (when at
$8000) holds its number.
From the nesdev wiki ("INES Mapper 071"): writes to $C000-$FFFF pick the
16 KB bank at $8000 (bits 0-3); writes to $8000-$9FFF pick one-screen
mirroring (bit 4) on the BF9097, which, without a submapper, takes over
from the header's mirroring at the first such write; $A000-$BFFF is
nothing.

Results use the blargg $6000 protocol; status codes:

  0  passed
  2  $8000 doesn't hold bank 0 at power-on
  3  writing 5 to $C000 didn't switch $8000 to bank 5
  4  writing 3 to $F123 (any address from $C000) didn't switch to bank 3
  5  the last bank moved from $C000 after switching
  6  before any mirroring write, the header's vertical mirroring isn't
     used ($2800 should show what was written at $2000)
  7  writing $10 to $9000 didn't give one-screen mirroring ($2C00 should
     show what was written at $2000)
  8  writing $00 to $9000 didn't give the other screen (the lower one,
     which holds what vertical mirroring put at $2000)
  9  a write to $A000-$BFFF changed the bank or the mirroring
"""
from mappers3_common import start, ppu_write, ppu_check, finish, vectors, write_nes

BANKS = 8
ID = 0xBFF0                 # the bank's number, as seen at $8000
LAST_ID = 0xFFF0            # the same byte of the last bank, at $C000
RTI = 0xFF00


def program():
    a = start(0xC000)
    a.check(ID, 0, "fail2")
    a.lda(5); a.sta(0xC000)
    a.check(ID, 5, "fail3")
    a.lda(3); a.sta(0xF123)
    a.check(ID, 3, "fail4")
    a.check(LAST_ID, BANKS - 1, "fail5")
    # The header's vertical mirroring: $2000 and $2800 are one screen.
    ppu_write(a, 0x2000, 0x11)
    ppu_write(a, 0x2400, 0x22)
    ppu_check(a, 0x2800, 0x11, "fail6")
    # One-screen, the upper screen (the one $2400 showed): $2000 is it.
    a.lda(0x10); a.sta(0x9000)
    ppu_write(a, 0x2000, 0x33)
    ppu_check(a, 0x2C00, 0x33, "fail7")
    # One-screen, the lower one: still $11 from the first write.
    a.lda(0x00); a.sta(0x9000)
    ppu_check(a, 0x2400, 0x11, "fail8")
    # $A000-$BFFF is nothing: neither the bank nor the mirroring moves.
    a.lda(0x16); a.sta(0xA000)
    a.check(ID, 3, "fail9")
    ppu_check(a, 0x2C00, 0x11, "fail9")
    return finish(a, (2, 3, 4, 5, 6, 7, 8, 9))


def main():
    code = program()
    prg = bytearray()
    for bank in range(BANKS):
        # The program (made for $C000) and the vectors in every bank, so
        # that if $C000 wrongly switches, it carries on and says so
        # (status 5) rather than crashing.
        b = bytearray(0x4000)
        b[:len(code)] = code
        vectors(b, 0xC000, 0xC000, RTI)
        b[ID - 0x8000] = bank
        prg += b
    write_nes("camerica_switch.nes", 71, prg, b"", vertical=True)


if __name__ == "__main__":
    main()
