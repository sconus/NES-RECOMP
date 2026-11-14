#!/usr/bin/env python3
"""Write runtime/fds_bios.h: nesrecomp's own Famicom Disk System BIOS.
Run it again after changing it. recomp.py reads the same file.

Nintendo's BIOS can't be used, so this one is written from the nesdev
wiki's description ("FDS BIOS"), keeping its addresses where programs
depend on them: the vectors at $FFFA-$FFFF, the handlers the dispatch
reaches, and (as later steps add them) the documented routines. Every
byte not used holds $02, an opcode that stops a 6502: a program calling
a routine this BIOS doesn't have stops there, with a message naming the
address, instead of running into something else.

Reset (both power-on and the reset button):
  - the registers and their copies in zero page as the wiki lists them:
    $4023 = $00 then $83, $4025 = $2E ($FA), $4026 = $FF ($F9), $FB-$FD
    = 0, PPUCTRL $10 ($FF), PPUMASK copy $06 ($FE), the APU frame counter
    $C0, FDS sound $4080 = $80 and $408A = $E8;
  - $0100 = $C0 (NMIs to the program's third vector) and $0101 = $80;
  - a soft reset ($0102 = $35 and $0103 = $53 or $AC) sets $0103 = $53
    and goes to the program's reset vector, $DFFC;
  - otherwise the boot: the runtime loads every file of the disk whose
    ID is at most the disk's boot code (asked through $4028, a register
    the real hardware doesn't have). Then the BIOS waits for the next
    vblank, sets $0102 = $35, $0103 = $AC and goes to $DFFC.
    The wait stands in for the real BIOS's license check, which this one
    can't do (the text it compares is Nintendo's). A program whose boot
    files turn on NMIs gets its NMI (through $0100) before the reset
    vector, as on the real console, where that is how the license
    check is skipped. The wait is a delay loop of a little over a frame,
    not a poll of $2002, which could swallow that vblank's NMI.
NMI: $0100 bits 7-6: 00 VINTWait's handler ($E19D), 01 $DFF6, 10
$DFF8, 11 $DFFA.
IRQ: $0101 bits 7-6: 11 $DFFE, 10 acknowledge and delay ($E1EF: Delay131
after reading $4030), 00 and 01 the disk transfer handlers ($E1D9,
$E1CE), which only acknowledge (this BIOS's file routines don't use the
drive).
The file routines, at the wiki's addresses, with their pointers after
the JSR and their error number in A (Z set when 0):
  $E1F8 LoadFiles (Y = files loaded), $E237 AppendFile (LDA #$FF, then
  WriteFile), $E239 WriteFile, $E2B7 CheckFileCount, $E2BB
  AdjustFileCount, $E301 SetFileCount1, $E305 SetFileCount, $E32A
  GetDiskInfo.
Each stores A in $4029 and asks the runtime ($4028), which does the
work against the disk image at once (runtime/fds.c), moves the return
address past the pointers, and leaves A (and LoadFiles' Y) in $4029
and $402A. The lower-level routines they use on the real BIOS
(CheckDiskHeader, GetNumFiles, FileMatchTest, ...) aren't here: those
read the disk byte by byte.
The other routines, at the wiki's addresses (a JMP there, the code
after the reset code), written from its descriptions:
  $E149 Delay131: 131 cycles, the JSR included; A is kept.
  $E153 Delayms: Y milliseconds (0 = 256), 1790 * Y + 5 cycles from the
        first byte of the routine to the end of its RTS (the wiki
        doesn't say which instructions its count covers; this leaves
        out the JSR). X, Y change.
  $E161 DisPFObj, $E16B EnPFObj, $E171 DisObj, $E178 EnObj, $E17E
        DisPF, $E185 EnPF: clear or set PPUMASK bits 3-4 in $FE (both,
        sprites, background) and write it to $2001.
  $E1B2 VINTWait: saves A and $0100, sets $0100 to 0 and turns NMIs on
        ($FF bit 7); the NMI comes to $E19D, which drops the interrupt,
        puts $0100 back, turns NMIs off, reads $2002 and returns to
        VINTWait's caller with A as it was and I set, as the wiki says.
  $E7BB VRAMStructWrite: the VRAM structure the pointer after the JSR
        points to: records of a big-endian address, a byte (bits 0-5
        the length, 0 = 64; bit 6 fill with one byte; bit 7 add 32),
        the data; $4C ptr calls a sub-structure, $60 returns from one,
        any other byte with bit 7 set ends it. VRAM increment 1 in $FF
        and $2000 afterwards.
  $E844 FetchDirectPtr: for a routine called by the program: the
        pointer after the program's JSR into $00-$01, the program's
        return address moved past it.
  $E86A WriteVRAMBuffer: the records at $0302 (address high, low, a
        length, the data; any first byte with bit 7 set ends them) to
        VRAM; then the buffer is empty ($0301 = 0, $0302 = $FF).
  $E8D2 PrepareVRAMString: A high and X low address, Y bytes from the
        pointer, added at $0302 + [$0301] with $FF after; A = $FF, or
        A = 1 and nothing added if the end would pass [$0300].
  $E8E1 PrepareVRAMStrings: the same for a block: its first byte is
        height (high nybble) and width; a row per string, 32 apart.
  $E97D Pixel2NamConv ($02 = Y, $03 = X pixels to $00-$01 in the
        nametable at $2000) and $E997 Nam2PixelConv (back, to the
        tile's corner).
  $E9B1 Random: Y bytes from zero page X shifted right one bit, the
        new top bit bit 1 of the first byte XOR bit 1 of the second
        (the wiki doesn't give the feedback; this is a choice).
  $E9C8 SpriteDMA: $0200-$02FF to OAM.
  $E9D3 CounterLogic: counters from zero page X: the first counts 9 to
        0 and round; X+1 to A count down to 0 every call; A+1 to Y
        count down to 0 when the first goes round (the wiki's table
        gives the ends as "A, Y"; this is that reading).
  $E9EB ReadPads ($F5-$F6 the pads, $00-$01 the expansion port, with
        $FB as the latch's other bits), $EA0D OrPads, $EA1A
        ReadDownPads, $EA1F ReadOrDownPads, $EA36 ReadDownVerifyPads,
        $EA4C ReadOrDownVerifyPads (new presses in $F5-$F6, held
        buttons in $F7-$F8; "Verify" reads until two reads agree), $EA68
        ReadDownExpPads ($F5-$F8 held, $F1-$F4 new: pad 1, pad 2,
        expansion 1, 2).
  $EA84 VRAMFill: A < $20: 16 * Y tiles of pattern data from $A00 set
        to X (Y = 0: 256 rows); else the nametable at $A00 set to X and
        its attributes to Y.
  $EAD2 MemFill: RAM pages X to Y (both included) set to A. A range
        with page 1 overwrites the stack, the return address too.
  $EAEA SetScroll: $2002 read, $2005 = $FD then $FC, $2000 = $FF.
  $EAFD JumpEngine: jumps to entry A of the table of addresses after
        the JSR.
Not here: the VRAM read buffer routines (ReadVRAMBuffer,
GetVRAMBufferByte; the wiki calls their use speculation), ReadKeyboard,
LoadTileset and UploadObject.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from make_mmc1_test import Asm  # noqa: E402

SERVICE = 0x4028        # BIOS -> runtime requests (runtime/fds.c)
ARG = 0x4029            # a routine's A; after it, the result A
RESULT_Y = 0x402A       # after LoadFiles, Y
BOOT_LOAD = 1
# The file routines: (name, entry, request, gives Y), the requests as in
# runtime/fds.c.
ROUTINES = [("LoadFiles", 0xE1F8, 2, True), ("WriteFile", 0xE239, 3, False),
            ("CheckFileCount", 0xE2B7, 4, False), ("AdjustFileCount", 0xE2BB, 5, False),
            ("SetFileCount1", 0xE301, 6, False), ("SetFileCount", 0xE305, 7, False),
            ("GetDiskInfo", 0xE32A, 8, False)]
APPEND_FILE = 0xE237    # LDA #$FF, into WriteFile
# The other routines after the file routines' stubs: (entry, label).
HELPERS = [(0xE7BB, "VRAMStructWrite"), (0xE844, "FetchDirectPtr"),
           (0xE86A, "WriteVRAMBuffer"), (0xE8D2, "PrepareVRAMString"),
           (0xE8E1, "PrepareVRAMStrings"), (0xE97D, "Pixel2NamConv"),
           (0xE997, "Nam2PixelConv"), (0xE9B1, "Random"), (0xE9C8, "SpriteDMA"),
           (0xE9D3, "CounterLogic"), (0xE9EB, "ReadPads"), (0xEA0D, "OrPads"),
           (0xEA1A, "ReadDownPads"), (0xEA1F, "ReadOrDownPads"),
           (0xEA36, "ReadDownVerifyPads"), (0xEA4C, "ReadOrDownVerifyPads"),
           (0xEA68, "ReadDownExpPads"), (0xEA84, "VRAMFill"), (0xEAD2, "MemFill"),
           (0xEAEA, "SetScroll"), (0xEAFD, "JumpEngine")]
STOP = 0x02             # a 6502 opcode that halts the CPU


def org(a, addr):
    """Fill with STOP up to addr."""
    assert a.pc() <= addr, "code at $%04X runs into $%04X" % (a.pc(), addr)
    while a.pc() < addr:
        a.b(STOP)


def jmp_ind(a, addr):
    a.b(0x6C, addr & 0xFF, addr >> 8)


def helpers(a):
    """The bodies of the routines other than the disk ones."""
    def br(op, label):                  # a short branch to a label
        a.b(op, 0)
        a.rel.append((len(a.code) - 1, label))

    def jmp(label):
        a.b(0x4C); a.fix.append((len(a.code), label)); a.b(0, 0)

    def jsr(label):
        a.b(0x20); a.fix.append((len(a.code), label)); a.b(0, 0)
    BNE, BEQ, BCS, BCC, BPL, BMI = 0xD0, 0xF0, 0xB0, 0x90, 0x10, 0x30

    # Delay131: JSR 6 + JMP 3 + 116 here + RTS 6.
    a.label("Delay131")
    a.b(0x48, 0xA9, 15)                 # PHA; LDA #15
    a.label("d131")
    a.b(0x38, 0xE9, 0x01)               # SEC; SBC #1
    br(BNE, "d131")                     # 7 a turn, 104 in all
    a.b(0x24, 0x00, 0x68)               # BIT $00; PLA
    a.rts()
    # Delayms: each millisecond 1790 cycles; entered past the first BIT,
    # so with the JMP and the RTS: 1790 * Y + 5.
    a.label("dms_turn")
    a.b(0x24, 0x00)                     # BIT $00 (3)
    a.label("dms")
    a.b(0xA2, 254)                      # LDX #254 (2)
    a.label("dms_in")
    a.b(0xCA, 0xEA)                     # DEX; NOP
    br(BNE, "dms_in")                   # 7 a turn: 1777
    a.b(0x24, 0x00, 0x88)               # BIT $00 (3); DEY (2)
    br(BNE, "dms_turn")                 # (3)
    a.rts()
    a.labels["Delayms"] = a.labels["dms"]

    for label, op, bits in (("DisPFObj", 0x29, 0xE7), ("EnPFObj", 0x09, 0x18),
                            ("DisObj", 0x29, 0xEF), ("EnObj", 0x09, 0x10),
                            ("DisPF", 0x29, 0xF7), ("EnPF", 0x09, 0x08)):
        a.label(label)
        a.b(0xA5, 0xFE, op, bits, 0x85, 0xFE)   # LDA $FE; AND/ORA; STA $FE
        a.sta(0x2001)
        a.rts()

    a.label("VINTWait")
    a.b(0x48)                           # PHA
    a.lda_abs(0x0100); a.b(0x48)        # LDA $0100; PHA
    a.lda(0x00); a.sta(0x0100)
    a.b(0xA5, 0xFF, 0x09, 0x80, 0x85, 0xFF)     # LDA $FF; ORA #$80; STA $FF
    a.sta(0x2000)
    a.label("vint_loop")
    jmp("vint_loop")
    a.label("vint_nmi")
    a.b(0x68, 0x68, 0x68)               # the NMI's P and return address
    a.b(0x68); a.sta(0x0100)            # PLA; STA $0100
    a.b(0xA5, 0xFF, 0x29, 0x7F, 0x85, 0xFF)     # LDA $FF; AND #$7F; STA $FF
    a.sta(0x2000)
    a.b(0x2C, 0x02, 0x20)               # BIT $2002
    a.b(0x68)                           # PLA
    a.rts()

    # FetchDirectPtr: the stack has its own return address, then the
    # program's (pointing at the JSR's last byte).
    a.label("FetchDirectPtr")
    a.b(0xBA)                           # TSX
    a.b(0xBD, 0x03, 0x01, 0x85, 0x00)   # LDA $0103,X; STA $00
    a.b(0xBD, 0x04, 0x01, 0x85, 0x01)   # LDA $0104,X; STA $01
    a.b(0xA0, 0x01, 0xB1, 0x00, 0x48)   # LDY #1; LDA ($00),Y; PHA
    a.b(0xC8, 0xB1, 0x00, 0x48)         # INY; LDA ($00),Y; PHA
    a.b(0xBD, 0x03, 0x01, 0x18, 0x69, 0x02, 0x9D, 0x03, 0x01)   # ret += 2
    a.b(0xBD, 0x04, 0x01, 0x69, 0x00, 0x9D, 0x04, 0x01)
    a.b(0x68, 0x85, 0x01, 0x68, 0x85, 0x00)     # PLA; STA $01; PLA; STA $00
    a.rts()

    def inc_ptr_y():
        """$00-$01 += Y."""
        a.b(0x98, 0x18, 0x65, 0x00, 0x85, 0x00)     # TYA; CLC; ADC $00; STA $00
        a.b(0xA5, 0x01, 0x69, 0x00, 0x85, 0x01)     # LDA $01; ADC #0; STA $01

    a.label("VRAMStructWrite")
    jsr("FetchDirectPtr")
    a.b(0xA5, 0xFF, 0x29, 0xFB, 0x85, 0xFF)     # increment 1
    a.sta(0x2000)
    a.label("vs_next")
    a.b(0xA0, 0x00, 0xB1, 0x00)         # LDY #0; LDA ($00),Y
    a.b(0xC9, 0x4C); br(BEQ, "vs_call")
    a.b(0xC9, 0x60); br(BEQ, "vs_ret")
    a.b(0xAA); br(BMI, "vs_end")        # TAX (sets N); BMI: the end
    a.b(0x2C, 0x02, 0x20)               # BIT $2002
    a.sta(0x2006)
    a.b(0xC8, 0xB1, 0x00); a.sta(0x2006)        # INY; LDA ($00),Y; STA $2006
    a.b(0xC8, 0xB1, 0x00, 0x48)         # INY; LDA ($00),Y; PHA (the flags)
    a.b(0xA5, 0xFF, 0x29, 0xFB)         # LDA $FF; AND #$FB
    a.b(0xAA, 0x68, 0x48)               # TAX; PLA; PHA
    a.b(0x10, 0x04, 0x8A, 0x09, 0x04, 0xAA)     # BPL +4; TXA; ORA #4; TAX
    a.b(0x8E, 0x00, 0x20)               # STX $2000
    a.b(0x68, 0x48, 0x29, 0x3F)         # PLA; PHA; AND #$3F
    a.b(0xD0, 0x02, 0xA9, 0x40)         # BNE +2; LDA #64
    a.b(0xAA, 0xC8, 0x68)               # TAX (the count); INY; PLA (flags)
    a.b(0x29, 0x40); br(BNE, "vs_fill")
    a.label("vs_copy")
    a.b(0xB1, 0x00); a.sta(0x2007)      # LDA ($00),Y; STA $2007
    a.b(0xC8, 0xCA); br(BNE, "vs_copy") # INY; DEX; BNE
    jmp("vs_step")
    a.label("vs_fill")
    a.b(0xB1, 0x00)                     # LDA ($00),Y
    a.label("vs_fill_loop")
    a.sta(0x2007)
    a.b(0xCA); br(BNE, "vs_fill_loop")
    a.b(0xC8)                           # INY: past the one byte
    a.label("vs_step")
    inc_ptr_y()
    jmp("vs_next")
    a.label("vs_call")                  # push where it is, go to the sub
    a.b(0xA5, 0x01, 0x48, 0xA5, 0x00, 0x48)     # LDA $01; PHA; LDA $00; PHA
    a.b(0xC8, 0xB1, 0x00, 0xAA)         # INY; LDA ($00),Y; TAX
    a.b(0xC8, 0xB1, 0x00, 0x85, 0x01, 0x86, 0x00)   # INY; LDA; STA $01; STX $00
    jmp("vs_next")
    a.label("vs_ret")                   # back to the $4C, then past it
    a.b(0x68, 0x85, 0x00, 0x68, 0x85, 0x01)     # PLA; STA $00; PLA; STA $01
    a.b(0xA0, 0x03)                     # LDY #3
    inc_ptr_y()
    jmp("vs_next")
    a.label("vs_end")
    a.b(0xA5, 0xFF); a.sta(0x2000)      # LDA $FF; STA $2000 (increment 1)
    a.rts()

    a.label("WriteVRAMBuffer")
    a.b(0xA2, 0x00)                     # LDX #0 (index into $0302)
    a.label("wb_next")
    a.b(0xBD, 0x02, 0x03); br(BMI, "wb_end")    # LDA $0302,X
    a.b(0x2C, 0x02, 0x20); a.sta(0x2006)
    a.b(0xE8, 0xBD, 0x02, 0x03); a.sta(0x2006)  # INX; LDA $0302,X
    a.b(0xE8, 0xBC, 0x02, 0x03)         # INX; LDY $0302,X (the length)
    a.b(0xE8)                           # INX
    a.b(0xC0, 0x00); br(BEQ, "wb_next") # CPY #0
    a.label("wb_copy")
    a.b(0xBD, 0x02, 0x03); a.sta(0x2007)
    a.b(0xE8, 0x88); br(BNE, "wb_copy") # INX; DEY
    jmp("wb_next")
    a.label("wb_end")
    a.lda(0x00); a.sta(0x0301)
    a.lda(0xFF); a.sta(0x0302)
    a.b(0xA5, 0xFF); a.sta(0x2000)
    a.rts()

    # PrepareVRAMString: $02 high, $03 low, $04 length, $00-$01 data.
    a.label("PrepareVRAMString")
    a.b(0x85, 0x02, 0x86, 0x03, 0x84, 0x04)     # STA $02; STX $03; STY $04
    jsr("FetchDirectPtr")
    jsr("pvs_add")
    a.rts()
    # pvs_add: one string ($02-$04 from ($00)), or A = 1 if it can't fit.
    a.label("pvs_add")
    a.b(0xAD, 0x01, 0x03, 0x18, 0x69, 0x03)     # LDA $0301; CLC; ADC #3
    br(BCS, "pvs_full")
    a.b(0x65, 0x04); br(BCS, "pvs_full")        # ADC $04
    a.b(0xCD, 0x00, 0x03); br(BEQ, "pvs_fits")  # CMP $0300
    br(BCS, "pvs_full")
    a.label("pvs_fits")
    a.b(0x85, 0x05)                     # STA $05 (the new end)
    a.b(0xAE, 0x01, 0x03)               # LDX $0301
    a.b(0xA5, 0x02, 0x9D, 0x02, 0x03, 0xE8)     # LDA $02; STA $0302,X; INX
    a.b(0xA5, 0x03, 0x9D, 0x02, 0x03, 0xE8)
    a.b(0xA5, 0x04, 0x9D, 0x02, 0x03, 0xE8)
    a.b(0xA0, 0x00)
    a.label("pvs_copy")
    a.b(0xC4, 0x04); br(BEQ, "pvs_done")        # CPY $04
    a.b(0xB1, 0x00, 0x9D, 0x02, 0x03, 0xE8, 0xC8)   # LDA ($00),Y; STA $0302,X; INX; INY
    jmp("pvs_copy")
    a.label("pvs_done")
    a.lda(0xFF); a.b(0x9D, 0x02, 0x03)  # the end mark
    a.b(0xA5, 0x05); a.sta(0x0301)
    a.lda(0xFF)
    a.rts()
    a.label("pvs_full")
    a.lda(0x01)
    a.rts()

    # PrepareVRAMStrings: rows of the block, each a string, 32 apart. All
    # or nothing: the room is checked first.
    a.label("PrepareVRAMStrings")
    a.b(0x85, 0x02, 0x86, 0x03)         # STA $02; STX $03
    jsr("FetchDirectPtr")
    a.b(0xA0, 0x00, 0xB1, 0x00)         # LDY #0; LDA ($00),Y: the size
    a.b(0x48, 0x29, 0x0F, 0x85, 0x04)   # PHA; AND #$0F; STA $04 (width)
    a.b(0x68, 0x4A, 0x4A, 0x4A, 0x4A, 0x85, 0x06)   # PLA; LSR x4; STA $06 (rows)
    a.b(0xE6, 0x00, 0xD0, 0x02, 0xE6, 0x01)     # past the size byte
    # Room: $0301 + rows * (3 + width) <= $0300.
    a.b(0xAD, 0x01, 0x03, 0xA6, 0x06)   # LDA $0301; LDX $06
    br(BEQ, "pss_room_ok")
    a.label("pss_room")
    a.b(0x18, 0x69, 0x03); br(BCS, "pvs_full")  # CLC; ADC #3
    a.b(0x65, 0x04); br(BCS, "pvs_full")        # ADC $04
    a.b(0xCA); br(BNE, "pss_room")
    a.b(0xCD, 0x00, 0x03); br(BEQ, "pss_room_ok")
    br(BCS, "pvs_full")
    a.label("pss_room_ok")
    a.label("pss_row")
    a.b(0xA5, 0x06); br(BEQ, "pss_done")        # LDA $06 (rows left)
    jsr("pvs_add")
    a.b(0xA5, 0x00, 0x18, 0x65, 0x04, 0x85, 0x00)   # data += width
    a.b(0xA5, 0x01, 0x69, 0x00, 0x85, 0x01)
    a.b(0xA5, 0x03, 0x18, 0x69, 0x20, 0x85, 0x03)   # address += 32
    a.b(0xA5, 0x02, 0x69, 0x00, 0x85, 0x02)
    a.b(0xC6, 0x06)                     # DEC $06
    jmp("pss_row")
    a.label("pss_done")
    a.lda(0xFF)
    a.rts()

    a.label("Pixel2NamConv")            # $2000 + (Y / 8) * 32 + X / 8
    a.b(0xA5, 0x02, 0x4A, 0x4A, 0x4A, 0x4A, 0x4A, 0x4A)     # LDA $02; LSR x6
    a.b(0x09, 0x20, 0x85, 0x00)         # ORA #$20; STA $00
    a.b(0xA5, 0x02, 0x29, 0x38, 0x0A, 0x0A, 0x85, 0x01)     # (Y & $38) << 2
    a.b(0xA5, 0x03, 0x4A, 0x4A, 0x4A, 0x05, 0x01, 0x85, 0x01)   # | X >> 3
    a.rts()
    a.label("Nam2PixelConv")
    a.b(0xA5, 0x01, 0x0A, 0x0A, 0x0A, 0x85, 0x03)   # X = (low & $1F) << 3
    a.b(0xA5, 0x01, 0x4A, 0x4A, 0x29, 0x38, 0x85, 0x02)     # (low >> 2) & $38
    a.b(0xA5, 0x00, 0x29, 0x03, 0x4A, 0x6A, 0x6A)   # (high & 3) << 6, via ROR
    a.b(0x05, 0x02, 0x85, 0x02)         # ORA $02; STA $02
    a.rts()

    a.label("Random")
    a.b(0xB5, 0x00, 0x29, 0x02, 0x85, 0x00)     # LDA 0,X; AND #2; STA $00
    a.b(0xB5, 0x01, 0x29, 0x02, 0x45, 0x00)     # LDA 1,X; AND #2; EOR $00
    a.b(0x18, 0xF0, 0x01, 0x38)         # CLC; BEQ +1; SEC
    a.label("rnd_shift")
    a.b(0x76, 0x00, 0xE8, 0x88)         # ROR 0,X; INX; DEY
    br(BNE, "rnd_shift")
    a.rts()

    a.label("SpriteDMA")
    a.lda(0x00); a.sta(0x2003)
    a.lda(0x02); a.sta(0x4014)
    a.rts()

    a.label("CounterLogic")
    a.b(0x85, 0x00)                     # STA $00 (the last fast counter)
    a.lda(0x00); a.b(0x48)              # LDA #0; PHA (went round?)
    a.b(0xB5, 0x00); br(BNE, "cl_first")
    a.b(0x68, 0xA9, 0x01, 0x48)         # PLA; LDA #1; PHA
    a.b(0xA9, 0x0A, 0x95, 0x00)         # LDA #10; STA 0,X
    a.label("cl_first")
    a.b(0xD6, 0x00)                     # DEC 0,X
    a.label("cl_fast")
    a.b(0xE4, 0x00); br(BCS, "cl_slow") # CPX $00
    a.b(0xE8, 0xB5, 0x00); br(BEQ, "cl_fast")   # INX; LDA 0,X
    a.b(0xD6, 0x00); jmp("cl_fast")
    a.label("cl_slow")
    a.b(0x68); br(BEQ, "cl_out")        # PLA: only when it went round
    a.b(0x84, 0x00)                     # STY $00
    a.label("cl_slow_loop")
    a.b(0xE4, 0x00); br(BCS, "cl_out")
    a.b(0xE8, 0xB5, 0x00); br(BEQ, "cl_slow_loop")
    a.b(0xD6, 0x00); jmp("cl_slow_loop")
    a.label("cl_out")
    a.rts()

    a.label("ReadPads")
    a.b(0xA5, 0xFB, 0x09, 0x01); a.sta(0x4016)  # LDA $FB; ORA #1; STA $4016
    a.b(0xA5, 0xFB); a.sta(0x4016)
    a.b(0xA2, 0x08)
    a.label("rp_bit")
    a.lda_abs(0x4016); a.b(0x4A, 0x26, 0xF5, 0x4A, 0x26, 0x00)  # LSR; ROL $F5; LSR; ROL $00
    a.lda_abs(0x4017); a.b(0x4A, 0x26, 0xF6, 0x4A, 0x26, 0x01)
    a.b(0xCA); br(BNE, "rp_bit")
    a.rts()
    a.label("OrPads")
    a.b(0xA5, 0xF5, 0x05, 0x00, 0x85, 0xF5)
    a.b(0xA5, 0xF6, 0x05, 0x01, 0x85, 0xF6)
    a.rts()
    a.label("read_or")
    jsr("ReadPads"); jmp("OrPads")
    a.label("downs")                    # $F5-$F6 now, $F7-$F8 before
    a.b(0xA2, 0x01)
    a.label("downs_loop")
    a.b(0xB5, 0xF5, 0x48, 0x55, 0xF7, 0x35, 0xF5, 0x95, 0xF5)   # new presses
    a.b(0x68, 0x95, 0xF7, 0xCA); br(BPL, "downs_loop")
    a.rts()
    a.label("ReadDownPads")
    jsr("ReadPads"); jmp("downs")
    a.label("ReadOrDownPads")
    jsr("read_or"); jmp("downs")
    for name, reader in (("ReadDownVerifyPads", "ReadPads"),
                         ("ReadOrDownVerifyPads", "read_or")):
        a.label(name)
        jsr(reader)
        a.label(name + "_again")
        a.b(0xA5, 0xF5, 0x48, 0xA5, 0xF6, 0x48)
        jsr(reader)
        a.b(0x68, 0xC5, 0xF6); br(BNE, name + "_pull")
        a.b(0x68, 0xC5, 0xF5); br(BNE, name + "_again")
        jmp("downs")
        a.label(name + "_pull")
        a.b(0x68); jmp(name + "_again")
    a.label("ReadDownExpPads")
    for zp in (0xF5, 0xF6, 0xF7, 0xF8):
        a.b(0xA5, zp, 0x48)
    jsr("ReadPads")
    a.b(0xA5, 0x00, 0x85, 0xF7, 0xA5, 0x01, 0x85, 0xF8)
    a.b(0xA2, 0x03)
    a.label("rde_loop")
    a.b(0x68, 0x55, 0xF5, 0x35, 0xF5, 0x95, 0xF1)   # PLA; EOR; AND; STA $F1,X
    a.b(0xCA); br(BPL, "rde_loop")
    a.rts()

    a.label("VRAMFill")
    a.b(0x85, 0x00, 0x86, 0x01, 0x84, 0x02)     # STA $00; STX $01; STY $02
    a.b(0xA5, 0xFF, 0x29, 0xFB, 0x85, 0xFF); a.sta(0x2000)
    a.b(0x2C, 0x02, 0x20, 0xA5, 0x00); a.sta(0x2006)
    a.lda(0x00); a.sta(0x2006)
    a.b(0xA5, 0x00, 0xC9, 0x20); br(BCS, "vf_nt")
    a.b(0xA5, 0x01, 0xA6, 0x02, 0xA0, 0x00)     # LDA $01; LDX $02; LDY #0
    a.label("vf_pt")
    a.sta(0x2007); a.b(0x88); br(BNE, "vf_pt")
    a.b(0xCA); br(BNE, "vf_pt")
    a.rts()
    a.label("vf_nt")
    a.b(0xA5, 0x01, 0xA2, 0x03, 0xA0, 0x00)     # 3 * 256
    a.label("vf_nt_loop")
    a.sta(0x2007); a.b(0x88); br(BNE, "vf_nt_loop")
    a.b(0xCA); br(BNE, "vf_nt_loop")
    a.b(0xA0, 0xC0)                     # and 192
    a.label("vf_nt_rest")
    a.sta(0x2007); a.b(0x88); br(BNE, "vf_nt_rest")
    a.b(0xA5, 0x02, 0xA0, 0x40)         # the attributes, 64
    a.label("vf_attr")
    a.sta(0x2007); a.b(0x88); br(BNE, "vf_attr")
    a.rts()

    a.label("MemFill")
    a.b(0x86, 0x01, 0xAA)               # STX $01; TAX (the value)
    a.b(0x98, 0x48)                     # TYA; PHA (the last page)
    a.lda(0x00); a.b(0x85, 0x00)
    a.label("mf_page")
    a.b(0x8A, 0xA4, 0x01); br(BNE, "mf_ptr")    # TXA; LDY $01
    a.label("mf_zp")                    # page 0: not through ($00)
    a.b(0x99, 0x00, 0x00, 0xC8); br(BNE, "mf_zp")   # STA $0000,Y; INY
    a.lda(0x00); a.b(0x85, 0x00, 0x85, 0x01)
    jmp("mf_cmp")
    a.label("mf_ptr")
    a.b(0xA0, 0x00)
    a.label("mf_loop")
    a.b(0x91, 0x00, 0xC8); br(BNE, "mf_loop")   # STA ($00),Y; INY
    a.label("mf_cmp")
    a.b(0x68, 0x48, 0xC5, 0x01); br(BEQ, "mf_end")  # PLA; PHA; CMP $01
    a.b(0xE6, 0x01); jmp("mf_page")
    a.label("mf_end")
    a.b(0x68)
    a.rts()

    a.label("SetScroll")
    a.b(0x2C, 0x02, 0x20)
    a.b(0xA5, 0xFD); a.sta(0x2005)
    a.b(0xA5, 0xFC); a.sta(0x2005)
    a.b(0xA5, 0xFF); a.sta(0x2000)
    a.rts()

    a.label("JumpEngine")
    a.b(0x0A, 0xA8, 0xC8)               # ASL; TAY; INY
    a.b(0x68, 0x85, 0x00, 0x68, 0x85, 0x01)     # the return address
    a.b(0xB1, 0x00, 0xAA, 0xC8, 0xB1, 0x00)     # LDA ($00),Y; TAX; INY; LDA
    a.b(0x85, 0x01, 0x86, 0x00)         # STA $01; STX $00
    jmp_ind(a, 0x0000)


def bios():
    a = Asm(0xE000)
    a.rel = []

    def w(addr, val):
        a.lda(val); a.sta(addr)

    def ack_rti():
        a.b(0x48); a.lda_abs(0x4030); a.b(0x68, 0x40)   # PHA; LDA $4030; PLA; RTI

    def jmp_at(addr, label):
        org(a, addr)
        a.b(0x4C); a.fix.append((len(a.code), label)); a.b(0, 0)

    for addr, label in ((0xE149, "Delay131"), (0xE153, "Delayms"),
                        (0xE161, "DisPFObj"), (0xE16B, "EnPFObj"), (0xE171, "DisObj"),
                        (0xE178, "EnObj"), (0xE17E, "DisPF"), (0xE185, "EnPF"),
                        (0xE19D, "vint_nmi"),           # NMI 00: VINTWait's
                        (0xE1B2, "VINTWait")):
        jmp_at(addr, label)
    org(a, 0xE1CE)                      # IRQ 01: disk byte transfer
    ack_rti()
    org(a, 0xE1D9)                      # IRQ 00: disk skip bytes
    ack_rti()
    org(a, 0xE1EF)                      # IRQ 10: acknowledge and delay
    a.b(0x48); a.lda_abs(0x4030)        # PHA; LDA $4030
    a.b(0x20, 0x49, 0xE1)               # JSR Delay131
    a.b(0x68, 0x40)                     # PLA; RTI

    for name, entry, _, _ in ROUTINES:
        if entry == 0xE239:
            org(a, APPEND_FILE)
            a.lda(0xFF)                     # AppendFile = WriteFile at $FF
        org(a, entry)
        a.b(0x4C); a.fix.append((len(a.code), name)); a.b(0, 0)
    org(a, 0xE600)
    for name, _, req, gives_y in ROUTINES:
        a.label(name)
        a.sta(ARG)
        w(SERVICE, req)
        if gives_y:
            a.b(0xAC, RESULT_Y & 0xFF, RESULT_Y >> 8)   # LDY $402A
        a.lda_abs(ARG)
        a.rts()
    for addr, label in HELPERS:
        jmp_at(addr, label)

    org(a, 0xF000)
    a.label("reset")
    a.b(0x78, 0xD8)                     # SEI; CLD
    w(0x2000, 0x10); a.b(0x85, 0xFF)    # STA $FF
    w(0x2001, 0x00)
    a.lda(0x06); a.b(0x85, 0xFE)
    a.b(0xA2, 0xFF, 0x9A)               # LDX #$FF; TXS
    for _ in range(2):                  # the PPU warms up
        here = a.pc()
        a.b(0x2C, 0x02, 0x20, 0x10, (here - (a.pc() + 5)) & 0xFF)
    w(0x4023, 0x00); w(0x4023, 0x83)
    w(0x4025, 0x2E); a.b(0x85, 0xFA)
    w(0x4026, 0xFF); a.b(0x85, 0xF9)
    w(0x4017, 0xC0)
    a.lda(0x00); a.b(0x85, 0xFB, 0x85, 0xFC, 0x85, 0xFD)
    w(0x4080, 0x80); w(0x408A, 0xE8)
    w(0x0100, 0xC0); w(0x0101, 0x80)
    # Soft reset?
    a.lda_abs(0x0102); a.cmp(0x35); a.b(0xD0, 0)
    to_boot1 = len(a.code) - 1
    a.lda_abs(0x0103); a.cmp(0x53); a.b(0xF0, 0)
    to_soft = len(a.code) - 1
    a.cmp(0xAC); a.b(0xD0, 0)
    to_boot2 = len(a.code) - 1
    a.label("soft")
    w(0x0103, 0x53)
    a.b(0x4C); a.fix.append((len(a.code), "start")); a.b(0, 0)
    a.label("boot")
    w(SERVICE, BOOT_LOAD)
    # A little over a frame (24 * 256 * 5 cycles), so a vblank passes. Not
    # by polling $2002, which could swallow that vblank's NMI.
    a.b(0xA2, 24, 0xA0, 0x00)           # LDX #24; LDY #0
    here = a.pc()
    a.b(0x88, 0xD0, 0xFD)               # DEY; BNE
    a.b(0xCA, 0xD0, (here - (a.pc() + 3)) & 0xFF)   # DEX; BNE
    w(0x0102, 0x35); w(0x0103, 0xAC)
    a.label("start")
    a.b(0x58)                           # CLI
    jmp_ind(a, 0xDFFC)
    for pos, label in ((to_boot1, "boot"), (to_boot2, "boot"), (to_soft, "soft")):
        a.code[pos] = (a.labels[label] - (a.org + pos + 1)) & 0xFF

    a.label("nmi")
    a.b(0x2C, 0x00, 0x01)               # BIT $0100
    a.b(0x30, 8)                        # BMI high (skip the next 8 bytes)
    a.b(0x50, 3)                        # BVC mode 00
    jmp_ind(a, 0xDFF6)                  # 01
    a.b(0x4C, 0x9D, 0xE1)               # 00: JMP $E19D
    a.b(0x50, 3)                        # high: BVC 10
    jmp_ind(a, 0xDFFA)                  # 11
    jmp_ind(a, 0xDFF8)                  # 10

    a.label("irq")
    a.b(0x2C, 0x01, 0x01)               # BIT $0101
    a.b(0x30, 8)                        # BMI high
    a.b(0x50, 3)                        # BVC 00
    a.b(0x4C, 0xCE, 0xE1)               # 01: JMP $E1CE
    a.b(0x4C, 0xD9, 0xE1)               # 00: JMP $E1D9
    a.b(0x50, 3)                        # high: BVC 10
    jmp_ind(a, 0xDFFE)                  # 11
    a.b(0x4C, 0xEF, 0xE1)               # 10: JMP $E1EF

    helpers(a)
    org(a, 0xFFFA)
    for label in ("nmi", "reset", "irq"):
        t = a.labels[label]
        a.b(t & 0xFF, t >> 8)
    for pos, label in a.rel:
        off = a.labels[label] - (a.org + pos + 1)
        assert -128 <= off <= 127, "branch to %s too far" % label
        a.code[pos] = off & 0xFF
    code = a.done()
    assert len(code) == 0x2000
    return code


def main():
    data = bios()
    lines = ["/* nesrecomp's own FDS BIOS, written by tools/make_fds_bios.py",
             "   (see there for what it does). Do not edit by hand. */",
             "static const unsigned char fds_bios[0x2000] = {"]
    for i in range(0, len(data), 16):
        lines.append("    " + ", ".join("0x%02X" % b for b in data[i:i + 16]) + ",")
    lines.append("};")
    path = os.path.join(ROOT, "runtime", "fds_bios.h")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    main()
