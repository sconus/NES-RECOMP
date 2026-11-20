#!/usr/bin/env python3
"""
nesrecomp - a static recompiler for NES (6502) programs.

It reads an iNES (.nes) file, traces the reachable 6502 code starting from
the cartridge's interrupt vectors (or entry points you give it), and writes
C source where every 6502 instruction becomes a few lines of C. An NSF
music file works the same way, starting from its init and play routines.

The ROM data itself is NOT copied into the output: the generated program
still loads the .nes (or .nsf) file at runtime for graphics and data tables. Only the
control flow and instruction logic are translated.

Usage:
    python3 recomp.py game.nes -o build/game.c [--entry C000 ...]

Mappers: see MAPPERS below.
"""
import argparse
import sys

# ---------------------------------------------------------------------------
# Opcode table: opcode -> (mnemonic, addressing mode, base cycles, page-cross
# penalty on reads). Built from the regular patterns of the 6502 encoding.
# ---------------------------------------------------------------------------
OPS = {}


def op(code, mnem, mode, cyc, pen=False):
    OPS[code] = (mnem, mode, cyc, pen)


# "Group 1" ALU ops share one layout of addressing modes.
for base, m in [(0x00, "ORA"), (0x20, "AND"), (0x40, "EOR"), (0x60, "ADC"),
                (0xA0, "LDA"), (0xC0, "CMP"), (0xE0, "SBC")]:
    op(base + 0x09, m, "imm", 2)
    op(base + 0x05, m, "zp", 3)
    op(base + 0x15, m, "zpx", 4)
    op(base + 0x0D, m, "abs", 4)
    op(base + 0x1D, m, "abx", 4, True)
    op(base + 0x19, m, "aby", 4, True)
    op(base + 0x01, m, "izx", 6)
    op(base + 0x11, m, "izy", 5, True)
op(0x85, "STA", "zp", 3); op(0x95, "STA", "zpx", 4); op(0x8D, "STA", "abs", 4)
op(0x9D, "STA", "abx", 5); op(0x99, "STA", "aby", 5)
op(0x81, "STA", "izx", 6); op(0x91, "STA", "izy", 6)

# Shifts and rotates.
for base, m in [(0x00, "ASL"), (0x20, "ROL"), (0x40, "LSR"), (0x60, "ROR")]:
    op(base + 0x0A, m, "acc", 2)
    op(base + 0x06, m, "zp", 5)
    op(base + 0x16, m, "zpx", 6)
    op(base + 0x0E, m, "abs", 6)
    op(base + 0x1E, m, "abx", 7)
for base, m in [(0xE0, "INC"), (0xC0, "DEC")]:
    op(base + 0x06, m, "zp", 5); op(base + 0x16, m, "zpx", 6)
    op(base + 0x0E, m, "abs", 6); op(base + 0x1E, m, "abx", 7)

# Loads / stores / compares for X and Y.
op(0xA2, "LDX", "imm", 2); op(0xA6, "LDX", "zp", 3); op(0xB6, "LDX", "zpy", 4)
op(0xAE, "LDX", "abs", 4); op(0xBE, "LDX", "aby", 4, True)
op(0xA0, "LDY", "imm", 2); op(0xA4, "LDY", "zp", 3); op(0xB4, "LDY", "zpx", 4)
op(0xAC, "LDY", "abs", 4); op(0xBC, "LDY", "abx", 4, True)
op(0x86, "STX", "zp", 3); op(0x96, "STX", "zpy", 4); op(0x8E, "STX", "abs", 4)
op(0x84, "STY", "zp", 3); op(0x94, "STY", "zpx", 4); op(0x8C, "STY", "abs", 4)
op(0xE0, "CPX", "imm", 2); op(0xE4, "CPX", "zp", 3); op(0xEC, "CPX", "abs", 4)
op(0xC0, "CPY", "imm", 2); op(0xC4, "CPY", "zp", 3); op(0xCC, "CPY", "abs", 4)
op(0x24, "BIT", "zp", 3); op(0x2C, "BIT", "abs", 4)

# Branches.
for code, m in [(0x10, "BPL"), (0x30, "BMI"), (0x50, "BVC"), (0x70, "BVS"),
                (0x90, "BCC"), (0xB0, "BCS"), (0xD0, "BNE"), (0xF0, "BEQ")]:
    op(code, m, "rel", 2)

# Jumps, calls, interrupts.
op(0x4C, "JMP", "abs", 3); op(0x6C, "JMP", "ind", 5); op(0x20, "JSR", "abs", 6)
op(0x60, "RTS", "imp", 6); op(0x40, "RTI", "imp", 6); op(0x00, "BRK", "imp", 7)

# Single-byte implied instructions.
for code, m in [(0x18, "CLC"), (0x38, "SEC"), (0x58, "CLI"), (0x78, "SEI"),
                (0xB8, "CLV"), (0xD8, "CLD"), (0xF8, "SED"), (0xAA, "TAX"),
                (0xA8, "TAY"), (0xBA, "TSX"), (0x8A, "TXA"), (0x9A, "TXS"),
                (0x98, "TYA"), (0xCA, "DEX"), (0x88, "DEY"), (0xE8, "INX"),
                (0xC8, "INY"), (0xEA, "NOP")]:
    op(code, m, "imp", 2)
op(0x48, "PHA", "imp", 3); op(0x08, "PHP", "imp", 3)
op(0x68, "PLA", "imp", 4); op(0x28, "PLP", "imp", 4)

# Commonly used "unofficial" opcodes (some commercial games rely on these).
for code in (0x1A, 0x3A, 0x5A, 0x7A, 0xDA, 0xFA):
    op(code, "NOP", "imp", 2)
for code in (0x80, 0x82, 0x89, 0xC2, 0xE2):
    op(code, "NOP", "imm", 2)
for code in (0x04, 0x44, 0x64):
    op(code, "NOP", "zp", 3)
for code in (0x14, 0x34, 0x54, 0x74, 0xD4, 0xF4):
    op(code, "NOP", "zpx", 4)
op(0x0C, "NOP", "abs", 4)
for code in (0x1C, 0x3C, 0x5C, 0x7C, 0xDC, 0xFC):
    op(code, "NOP", "abx", 4, True)
op(0xA3, "LAX", "izx", 6); op(0xA7, "LAX", "zp", 3); op(0xAF, "LAX", "abs", 4)
op(0xB3, "LAX", "izy", 5, True); op(0xB7, "LAX", "zpy", 4)
op(0xBF, "LAX", "aby", 4, True)
op(0x83, "SAX", "izx", 6); op(0x87, "SAX", "zp", 3); op(0x8F, "SAX", "abs", 4)
op(0x97, "SAX", "zpy", 4)
op(0xEB, "SBC", "imm", 2)
for base, m in [(0x00, "SLO"), (0x20, "RLA"), (0x40, "SRE"), (0x60, "RRA"),
                (0xC0, "DCP"), (0xE0, "ISB")]:
    op(base + 0x03, m, "izx", 8); op(base + 0x07, m, "zp", 5)
    op(base + 0x0F, m, "abs", 6); op(base + 0x13, m, "izy", 8)
    op(base + 0x17, m, "zpx", 6); op(base + 0x1B, m, "aby", 7)
    op(base + 0x1F, m, "abx", 7)

# The rest of the stable unofficial opcodes. instr_test-v5 checks the
# immediate ones plus SHY/SHX; the others follow the nesdev wiki.
op(0x0B, "ANC", "imm", 2); op(0x2B, "ANC", "imm", 2)
op(0x4B, "ALR", "imm", 2); op(0x6B, "ARR", "imm", 2)
op(0xCB, "AXS", "imm", 2)
op(0x8B, "XAA", "imm", 2); op(0xAB, "LXA", "imm", 2)     # "unstable" on hardware
op(0x9C, "SHY", "abx", 5); op(0x9E, "SHX", "aby", 5)
op(0x9F, "AHX", "aby", 5); op(0x93, "AHX", "izy", 6)
op(0x9B, "TAS", "aby", 5); op(0xBB, "LAS", "aby", 4, True)
# Not translated: the 12 "JAM" opcodes ($02, $12, ... $F2), which lock up
# a real CPU. Running into one stops the program with a message.

SIZE = {"imp": 1, "acc": 1, "imm": 2, "zp": 2, "zpx": 2, "zpy": 2, "izx": 2,
        "izy": 2, "rel": 2, "abs": 3, "abx": 3, "aby": 3, "ind": 3}

READS = {"ORA", "AND", "EOR", "ADC", "SBC", "LDA", "LDX", "LDY", "CMP", "CPX",
         "CPY", "BIT", "LAX", "NOP", "ANC", "ALR", "ARR", "AXS", "XAA", "LXA",
         "LAS"}
RMW = {"ASL", "LSR", "ROL", "ROR", "INC", "DEC", "SLO", "RLA", "SRE", "RRA",
       "DCP", "ISB"}
STORES = {"STA": "A", "STX": "X", "STY": "Y", "SAX": "(A & X)"}
# Stores that AND the value with (high byte of the base address + 1), and
# when indexing crosses a page, use that value as the new high byte too.
HIGH_STORES = {"SHY": "Y", "SHX": "X", "AHX": "(A & X)", "TAS": "SP"}
BRANCH = {"BPL": "!N", "BMI": "N", "BVC": "!V", "BVS": "V",
          "BCC": "!C", "BCS": "C", "BNE": "!Z", "BEQ": "Z"}


# ---------------------------------------------------------------------------
# Cycle maps: what the CPU puts on the bus during each cycle of each opcode,
# one letter per cycle. The runtime replays these when a DMA or interrupt
# lands inside an instruction (runtime/cycles.c). Lowercase x, y, t and c are
# cycles that only happen sometimes; every other letter always happens.
# ---------------------------------------------------------------------------
CYCLE_KEY = {
    "F": "read the opcode",
    "1": "read operand byte 1 (pc + 1)",
    "2": "read operand byte 2 (pc + 2)",
    "n": "dummy read of pc + 1 (one-byte instructions)",
    "z": "dummy read of the zero-page base, before adding X or Y",
    "L": "read the pointer's low byte",
    "H": "read the pointer's high byte",
    "d": "dummy read of the address before its high byte is fixed",
    "x": "same dummy read, only when adding X crosses a page",
    "y": "same dummy read, only when adding Y crosses a page",
    "r": "read the effective address",
    "w": "write the effective address",
    "m": "write the old value back (read-modify-write)",
    "s": "dummy read of the stack before pulling",
    "u": "pull: read the stack",
    "U": "push: write the stack",
    "j": "JSR's internal cycle (dummy read of the stack)",
    "k": "RTS's internal cycle (dummy read of the return address)",
    "v": "read the vector's low byte",
    "V": "read the vector's high byte",
    "t": "taken branch: dummy read of the next opcode",
    "c": "taken branch to another page: dummy read of the half-fixed target",
}
WRITE_CYCLES = "wmU"          # every other letter is a read
OPTIONAL_CYCLES = "xytc"


def cycle_map(mnem, mode):
    """Bus cycles of one opcode, as letters from CYCLE_KEY."""
    special = {
        "JMP": {"abs": "F12", "ind": "F12LH"}, "JSR": {"abs": "F1jUU2"},
        "RTS": {"imp": "Fnsuuk"}, "RTI": {"imp": "Fnsuuu"},
        "BRK": {"imp": "F1UUUvV"},
        "PHA": {"imp": "FnU"}, "PHP": {"imp": "FnU"},
        "PLA": {"imp": "Fnsu"}, "PLP": {"imp": "Fnsu"},
    }
    if mnem in special:
        return special[mnem][mode]
    if mode in ("imp", "acc"):
        return "Fn"
    if mode == "imm":
        return "F1"
    if mode == "rel":
        return "F1tc"
    if mnem in READS:
        access = "r"
    elif mnem in RMW:
        access = "rmw"
    elif mnem in STORES or mnem in HIGH_STORES:
        access = "w"
    else:
        raise ValueError("no cycle map for %s %s" % (mnem, mode))
    # Indexed reads only spend the fix-up cycle on a page cross; writes and
    # read-modify-writes always do.
    fix = {"abx": "x", "aby": "y", "izy": "y"}.get(mode, "")
    if fix and access != "r":
        fix = "d"
    prefix = {"zp": "F1", "zpx": "F1z", "zpy": "F1z", "abs": "F12",
              "abx": "F12", "aby": "F12", "izx": "F1zLH", "izy": "F1LH"}[mode]
    return prefix + fix + access


def check_cycle_maps():
    """Each map must agree with the opcode table's cycle counts."""
    for opc, (mnem, mode, cyc, pen) in OPS.items():
        m = cycle_map(mnem, mode)
        fixed = sum(1 for ch in m if ch not in OPTIONAL_CYCLES)
        optional = "".join(ch for ch in m if ch in OPTIONAL_CYCLES)
        want = "tc" if mode == "rel" else ("x" if mode == "abx" else "y") if pen else ""
        assert set(m) <= set(CYCLE_KEY), "$%02X: unknown letter in %s" % (opc, m)
        assert fixed == cyc, "$%02X %s %s: map %s has %d cycles, table says %d" % (
            opc, mnem, mode, m, fixed, cyc)
        assert optional == want, "$%02X %s %s: map %s, optional cycles should be %r" % (
            opc, mnem, mode, m, want)


check_cycle_maps()


# ---------------------------------------------------------------------------
# ROM loading
# ---------------------------------------------------------------------------
# How each supported mapper lays out program ROM, in 8 KB banks and the four
# CPU slots $8000/$A000/$C000/$E000. This is all the recompiler needs to
# know about a mapper; the runtime does the actual switching.
#   unit:  how many slots switch together (2 = 16 KB, 4 = 32 KB), or None
#          if program ROM never moves.
#   fixed: slot -> bank for slots that never switch (negative counts from
#          the last bank).
#   power_on: slot -> bank at reset (where the vectors are read).
NSF_MAPPER = 0x1000                  # runtime/nsf.h: MAPPER_NSF
FDS_MAPPER = 0x1001                  # runtime/fds.h: MAPPER_FDS
MAPPERS = {
    0:  dict(name="NROM",  unit=None),
    # MMC1 can fix either half or switch all 32 KB, depending on a mode
    # the program sets, so no slot is safe to treat as fixed.
    1:  dict(name="MMC1",  unit=2, fixed={},
             power_on={0: 0, 1: 1, 2: -2, 3: -1}),
    3:  dict(name="CNROM", unit=None),
    2:  dict(name="UxROM", unit=2, fixed={2: -2, 3: -1},
             power_on={0: 0, 1: 1, 2: -2, 3: -1}),
    # MMC3: 8 KB slots switch one by one; $8000 and $C000 trade places
    # with the PRG mode bit; only $E000 never moves.
    4:  dict(name="MMC3",  unit=1, fixed={3: -1},
             power_on={0: 0, 1: 1, 2: -2, 3: -1}),
    7:  dict(name="AxROM", unit=4, fixed={}, power_on={0: 0, 1: 1, 2: 2, 3: 3}),
    34: dict(name="BNROM", unit=4, fixed={}, power_on={0: 0, 1: 1, 2: 2, 3: 3}),
    11: dict(name="Color Dreams", unit=4, fixed={}, power_on={0: 0, 1: 1, 2: 2, 3: 3}),
    66: dict(name="GxROM", unit=4, fixed={}, power_on={0: 0, 1: 1, 2: 2, 3: 3}),
    # Konami VRC2/VRC4: 8 KB banks at $8000 and $A000, the last 8 KB fixed;
    # VRC4 can swap $8000 with $C000 (the second-to-last bank), so only
    # $E000 is safe to treat as fixed (like MMC3). Four mapper numbers for
    # the same chips wired to different address lines.
    21: dict(name="VRC4", unit=1, fixed={3: -1}, power_on={0: 0, 1: 1, 2: -2, 3: -1}),
    22: dict(name="VRC2", unit=1, fixed={3: -1}, power_on={0: 0, 1: 1, 2: -2, 3: -1}),
    23: dict(name="VRC4", unit=1, fixed={3: -1}, power_on={0: 0, 1: 1, 2: -2, 3: -1}),
    25: dict(name="VRC4", unit=1, fixed={3: -1}, power_on={0: 0, 1: 1, 2: -2, 3: -1}),
    # MMC2: 8 KB at $8000 switches, the last three 8 KB are fixed. MMC4:
    # 16 KB at $8000 switches, the last 16 KB is fixed.
    9:  dict(name="MMC2", unit=1, fixed={1: -3, 2: -2, 3: -1},
             power_on={0: 0, 1: -3, 2: -2, 3: -1}),
    10: dict(name="MMC4", unit=2, fixed={2: -2, 3: -1},
             power_on={0: 0, 1: 1, 2: -2, 3: -1}),
    # MMC5: every slot can switch (even $E000, by $5117), in 8 KB steps,
    # and the bank registers are at $5113-$5117: stores there may switch
    # the running code out too (low_regs). Power-on: $5117 = $FF, and
    # the other bank registers are assumed $FF too, so all four slots hold
    # the last 8 KB.
    5:  dict(name="MMC5", unit=1, fixed={}, power_on={0: -1, 1: -1, 2: -1, 3: -1},
             low_regs=(0x5100, 0x5117)),
    # Konami VRC6: 16 KB at $8000 and 8 KB at $C000 switch, the last 8 KB
    # is fixed. Mapper 26 is the same chip with two address lines swapped.
    24: dict(name="VRC6", unit=1, fixed={3: -1}, power_on={0: 0, 1: 1, 2: -2, 3: -1}),
    26: dict(name="VRC6", unit=1, fixed={3: -1}, power_on={0: 0, 1: 1, 2: -2, 3: -1}),
    # Bandai FCG-1/2 and LZ93D50: 16 KB at $8000 switches, the last 16 KB
    # is fixed. The FCG's registers are at $6000-$7FFF, so stores there
    # may switch the running code out.
    16: dict(name="Bandai FCG", unit=2, fixed={2: -2, 3: -1},
             power_on={0: 0, 1: 1, 2: -2, 3: -1}, low_regs=(0x6000, 0x7FFF)),
    # Namco 163: three 8 KB slots switch, $E000 is the last bank.
    19: dict(name="Namco 163", unit=1, fixed={3: -1}, power_on={0: 0, 1: 1, 2: 2, 3: -1}),
    # Konami VRC7: three 8 KB slots switch, $E000 is the last bank.
    85: dict(name="VRC7", unit=1, fixed={3: -1}, power_on={0: 0, 1: 1, 2: 2, 3: -1}),
    # Sunsoft FME-7: three 8 KB slots switch, $E000 is the last bank.
    69: dict(name="FME-7", unit=1, fixed={3: -1}, power_on={0: 0, 1: 1, 2: 2, 3: -1}),
    # Action 53 switches 16 or 32 KB with either half fixed, depending on a
    # mode the program sets, so no slot is safe to treat as fixed. It
    # starts in its last 32 KB.
    28: dict(name="Action 53", unit=2, fixed={},
             power_on={0: -4, 1: -3, 2: -2, 3: -1}),
    # Camerica / Codemasters: 16 KB at $8000 switches, the last 16 KB is
    # fixed (like UxROM).
    71: dict(name="Camerica", unit=2, fixed={2: -2, 3: -1},
             power_on={0: 0, 1: 1, 2: -2, 3: -1}),
    # AVE NINA-03/06: 32 KB switched by a register at $4100-$5FFF (where
    # A8 is set), so stores there may switch the running code out.
    79: dict(name="NINA-03/06", unit=4, fixed={}, power_on={0: 0, 1: 1, 2: 2, 3: 3},
             low_regs=(0x4100, 0x5FFF)),
    # Caltron 6-in-1: 32 KB switched by the address of a write to
    # $6000-$67FF.
    41: dict(name="Caltron 6-in-1", unit=4, fixed={}, power_on={0: 0, 1: 1, 2: 2, 3: 3},
             low_regs=(0x6000, 0x67FF)),
    # Active Enterprises (Action 52, Cheetahmen II): the written address
    # picks 32 KB, or the same 16 KB twice, so both halves switch.
    228: dict(name="Active Enterprises", unit=2, fixed={},
              power_on={0: 0, 1: 1, 2: 2, 3: 3}),
    # NTDEC / Asder (mapper 112): like MMC3 without its mode bits, so
    # $8000 and $A000 switch and the last 16 KB never moves.
    112: dict(name="NTDEC 112", unit=1, fixed={2: -2, 3: -1},
              power_on={0: 0, 1: 1, 2: -2, 3: -1}),
    # TQROM (mapper 119): an MMC3 with CHR RAM beside its CHR ROM; the
    # program banks are the MMC3's.
    119: dict(name="TQROM", unit=1, fixed={3: -1},
              power_on={0: 0, 1: 1, 2: -2, 3: -1}),
    # TXC 22211 / JV001, mapper 172 (1991 Du Ma Racing): only CHR and
    # mirroring switch; 32 KB of PRG that never moves.
    172: dict(name="TXC 172", unit=None),
    # An NSF music file (not an iNES mapper; the runtime uses the same
    # number): 32 KB at $8000 that never moves.
    NSF_MAPPER: dict(name="NSF", unit=None),
    # A Famicom Disk System image: RAM at $6000-$DFFF, where the program
    # is loaded from disk, and the project's BIOS at $E000
    # (runtime/fds_bios.h), which never moves. See Rom.load_fds.
    FDS_MAPPER: dict(name="FDS", unit=None),
}


def fds_bios():
    """nesrecomp's FDS BIOS, from runtime/fds_bios.h (tools/make_fds_bios.py)."""
    import os
    import re
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "runtime", "fds_bios.h")
    body = open(path).read().split("{", 1)[1]
    data = bytes(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", body))
    if len(data) != 0x2000:
        sys.exit("%s: expected 8 KB" % path)
    return data


FDS_SIDE = 65500
FDS_FIRST_TAG = 4                    # runtime/fds.h
# FDS BIOS routines that take pointers in the bytes after the JSR and
# return past them (tools/make_fds_bios.py): entry -> how many. None:
# it never returns there (JumpEngine: a table of addresses follows).
FDS_INLINE_POINTERS = {0xE1F8: 2, 0xE237: 2, 0xE239: 2, 0xE2B7: 1, 0xE2BB: 1,
                       0xE301: 1, 0xE305: 1, 0xE32A: 1,
                       0xE7BB: 1, 0xE8D2: 1, 0xE8E1: 1, 0xEAFD: None}


def fds_side_files(side):
    """The files of one disk side, as runtime/fds.c's side_files reads
    them: dicts of number, id, addr, type, data."""
    if side[56] != 2:
        return []
    count, at, out = side[57], 58, []
    while len(out) < count and len(out) < 256 and at + 17 <= FDS_SIDE and side[at] == 3:
        h = side[at:at + 16]
        f = dict(number=h[1], id=h[2], addr=h[11] | h[12] << 8,
                 size=h[13] | h[14] << 8, type=h[15])
        at += 16
        if side[at] != 4 or at + 1 + f["size"] > FDS_SIDE:
            break
        f["data"] = side[at + 1:at + 1 + f["size"]]
        at += 1 + f["size"]
        out.append(f)
    return out


def rom_size(lsb, msb, unit):
    """A ROM size from an NES 2.0 header: the LSB byte and the 4-bit MSB
    in `unit`s, or, when the MSB is $F, the exponent form EEEEEEMM:
    2^E x (MM*2+1) bytes."""
    if msb == 0xF:
        e, mm = lsb >> 2, lsb & 3
        if e > 30:
            raise ValueError("ROM size 2^%d bytes is too large" % e)
        return (1 << e) * (mm * 2 + 1)
    return (msb << 8 | lsb) * unit


def ram_size(shift):
    """A RAM size nibble from bytes 10-11: 0 for none, else 64 << n."""
    return 64 << shift if shift else 0


def read_header(data):
    """Read an iNES header (16 bytes at the start of `data`), as iNES 1.0
    or NES 2.0 (nesdev wiki "NES 2.0", "INES"). runtime/cart.c reads it
    the same way; tests/check_headers.py compares the two. Returns a dict
    of every field; with iNES 1.0 the fields NES 2.0 adds get the values
    the runtime has always assumed."""
    if len(data) < 16:
        raise ValueError("truncated: the file is shorter than its header says")
    h = data[:16]
    battery = (h[6] & 2) != 0
    trainer = (h[6] & 4) != 0
    head = 16 + (512 if trainer else 0)
    nes2 = (h[7] & 0x0C) == 0x08
    if nes2:
        prg = rom_size(h[4], h[9] & 0x0F, 0x4000)
        chr_ = rom_size(h[5], h[9] >> 4, 0x2000)
        if head + prg + chr_ > len(data):    # the wiki: then not NES 2.0
            nes2 = False
    clean = nes2 or not any(h[12:16])        # old dumps put junk in 12-15
    f = dict(nes2=nes2, battery=battery, trainer=trainer,
             mapper=(h[6] >> 4) | (h[7] & 0xF0), submapper=0,
             console=h[7] & 3 if clean else 0, console_ext=0,
             timing=0, misc_roms=0, exp_device=0)
    if nes2:
        f["mapper"] |= (h[8] & 0x0F) << 8
        f.update(submapper=h[8] >> 4, prg_size=prg, chr_size=chr_,
                 prg_ram=ram_size(h[10] & 0x0F), prg_nvram=ram_size(h[10] >> 4),
                 chr_ram=ram_size(h[11] & 0x0F), chr_nvram=ram_size(h[11] >> 4),
                 timing=h[12] & 3, misc_roms=h[14] & 3, exp_device=h[15] & 0x7F,
                 console_ext=h[13] if f["console"] in (1, 3) else 0)
    else:
        if not clean:
            f["mapper"] &= 0x0F
        f.update(prg_size=h[4] * 0x4000, chr_size=h[5] * 0x2000,
                 prg_ram=0 if battery else 0x2000,
                 prg_nvram=0x2000 if battery else 0,
                 chr_ram=0x2000 if h[5] == 0 else 0, chr_nvram=0)
    if head + f["prg_size"] + f["chr_size"] > len(data):
        raise ValueError("truncated: the file is shorter than its header says")
    if f["prg_size"] == 0:
        raise ValueError("header lists no PRG ROM")
    if f["prg_size"] % 0x2000:
        raise ValueError("PRG ROM of %d bytes is not a whole number of 8 KB"
                         " banks" % f["prg_size"])
    if f["chr_size"] % 0x400:
        raise ValueError("CHR ROM of %d bytes is not a whole number of 1 KB"
                         " banks" % f["chr_size"])
    return f


class Rom:
    def __init__(self, path):
        try:
            data = open(path, "rb").read()
        except OSError:
            sys.exit("%s: can't open the file" % path)
        self.nsf = None
        self.ram_top = 0x8000               # code below this is RAM
        self.files = None                   # an FDS's files (load_fds)
        self.inline = {}                    # JSR targets that return later
        if data[:5] == b"NESM\x1a":
            self.load_nsf(data)
            return
        if data[:4] == b"FDS\x1a" or data[:15] == b"\x01*NINTENDO-HVC*":
            self.load_fds(data)
            return
        if data[:4] != b"NES\x1a":
            sys.exit("not an iNES, NSF or FDS file")
        try:
            self.header = read_header(data)
        except ValueError as e:
            sys.exit("%s: %s" % (path, e))
        self.mapper = self.header["mapper"]
        start = 16 + (512 if self.header["trainer"] else 0)
        self.prg = data[start:start + self.header["prg_size"]]
        self.slot_bits = 13                          # 8 KB slots and banks
        self.banks = len(self.prg) // 0x2000

        if self.mapper not in MAPPERS:
            sys.exit("mapper %d is not supported (supported: %s)" % (
                self.mapper, ", ".join("%d %s" % (k, v["name"])
                                       for k, v in sorted(MAPPERS.items()))))
        m = MAPPERS[self.mapper]
        self.mapper_name = m["name"]
        self.unit = m["unit"]
        sub = self.header["submapper"]
        if self.mapper == 34 and sub == 1:
            sys.exit("mapper 34 submapper 1 (NINA-001) is not supported")
        # Do stores to $8000-$FFFF (or low_regs) reach anything? Yes for a
        # mapper that switches banks; for an NSF, when it has sound chips.
        self.high_writes = self.unit is not None
        if self.mapper == 1 and sub == 5:
            # SEROM, SHROM: 32 KB that never moves, though the MMC1's
            # other registers (CHR, mirroring) still take writes.
            self.unit = None
        self.low_regs = m.get("low_regs")
        if self.unit is None:                    # nothing moves: NROM layout
            self.power_on = {s: s % self.banks for s in range(4)}
            self.fixed = dict(self.power_on)
        else:
            self.power_on = {s: b % self.banks for s, b in m["power_on"].items()}
            self.fixed = {s: b % self.banks for s, b in m["fixed"].items()}
            if self.mapper == 1 and self.banks > 32:
                # 512 KB MMC1 boards start in the first 256 KB, so the
                # "last" bank at power-on is the last of that half.
                self.power_on.update({2: 30, 3: 31})

    def load_fds(self, data):
        """A disk image. Its program comes from disk into RAM at run time,
        so each PRG file is a "bank" of its own, placed at its load
        address ($6000-$DFFF only) and numbered as runtime/fds.h numbers
        them: every file of every side in disk order, from FDS_FIRST_TAG
        (files past 255 aren't translated). The BIOS is bank 3, at $E000.
        The runtime tags RAM by file (code_owner), so translated code runs
        only where its file's bytes still are. Tracing starts from the
        BIOS's vectors and from the program's, at $DFF6-$DFFF, as the boot
        files leave them."""
        self.mapper = FDS_MAPPER
        self.mapper_name = "FDS"
        self.prg = bytes(0x6000) + fds_bios()
        self.slot_bits = 13
        self.unit = None
        self.low_regs = None
        self.high_writes = False
        self.power_on = {s: s for s in range(4)}
        self.fixed = dict(self.power_on)
        self.ram_top = 0xE000
        self.inline = FDS_INLINE_POINTERS
        body = data[16:] if data[:4] == b"FDS\x1a" else data
        sides = [body[i:i + FDS_SIDE] for i in range(0, len(body) - FDS_SIDE + 1, FDS_SIDE)]
        self.files = {}                      # tag -> (first address, bytes)
        self.boot_owner = [0] * 0x8000       # $6000-$DFFF after the boot load
        boot = bytearray(0x8000)
        tag = FDS_FIRST_TAG
        for n, side in enumerate(sides):
            for f in fds_side_files(side):
                t = tag if tag <= 255 else 0
                tag += 1
                if f["type"] != 0:
                    continue
                lo, hi = max(f["addr"], 0x6000), min(f["addr"] + f["size"], 0xE000)
                if t and lo < hi:
                    self.files[t] = (lo, f["data"][lo - f["addr"]:hi - f["addr"]])
                if n == 0 and f["id"] <= side[0x19]:      # a boot file
                    for i, b in enumerate(f["data"]):
                        a = (f["addr"] + i) & 0xFFFF
                        if 0x6000 <= a < 0xE000:
                            boot[a - 0x6000] = b
                            self.boot_owner[a - 0x6000] = t
        self.banks = 256
        self.boot_ram = bytes(boot)
        self.files_count = tag - FDS_FIRST_TAG

    def fds_entries(self):
        """The program's vectors at $DFF6-$DFFF after the boot load, as
        locations: in the file whose byte is there."""
        out = []
        for v in range(0xDFF6, 0xE000, 2):
            t = self.boot_ram[v - 0x6000] | self.boot_ram[v + 1 - 0x6000] << 8
            if t >= 0xE000:
                out.append((3, t))
            elif 0x6000 <= t < 0xE000 and self.boot_owner[t - 0x6000]:
                out.append((self.boot_owner[t - 0x6000], t))
        return out

    def load_nsf(self, data):
        """An NSF: the init and play routines are the entry points (see
        runtime/nsf.h). Without bank switching, the program sits at its
        load address in 32 KB at $8000 that never moves. With it, the
        program is cut into 4 KB banks (the first starting at the load
        address's offset within 4 KB), $8000-$FFFF is eight 4 KB slots
        that each switch alone ($5FF8-$5FFF), and the header gives the
        starting bank of each."""
        if len(data) < 0x80:
            sys.exit("NSF header is cut short")
        h = data[:0x80]
        load, init, play = (h[i] | h[i + 1] << 8 for i in (8, 10, 12))
        self.nsf = dict(load=load, init=init, play=play, chips=h[0x7B] & 0x3F)
        self.mapper = NSF_MAPPER
        self.mapper_name = "NSF"
        chips = h[0x7B] & 0x3F
        start = list(h[0x70:0x78])
        body = data[0x80:]
        if any(start):
            off = load & 0xFFF
            size = (off + len(body) + 0xFFF) & ~0xFFF
            if size == 0:
                sys.exit("NSF has no program")
            prg = bytearray(size)
            prg[off:off + len(body)] = body
            self.prg = bytes(prg)
            self.slot_bits = 12
            self.banks = size // 0x1000
            self.unit = 1
            self.fixed = {}
            self.power_on = {s: b % self.banks for s, b in enumerate(start)}
            self.low_regs = (0x5FF8, 0x5FFF)
            self.high_writes = True
            return
        # An FDS NSF may load from $6000 (the RAM there); that part is
        # RAM to the recompiler, left to the interpreter.
        if load < (0x6000 if chips & 4 else 0x8000):
            sys.exit("NSF loads below $%04X" % (0x6000 if chips & 4 else 0x8000))
        if load < 0x8000:
            body, load = body[0x8000 - load:], 0x8000
        prg = bytearray(0x8000)
        body = body[:0x10000 - load]
        prg[load - 0x8000:load - 0x8000 + len(body)] = body
        self.prg = bytes(prg)
        self.slot_bits = 13
        self.banks = 4
        self.unit = None
        self.low_regs = None
        self.high_writes = chips != 0
        self.power_on = {s: s for s in range(4)}
        self.fixed = dict(self.power_on)

    def slot(self, addr):
        """Which program slot ($8000 up) holds CPU address addr."""
        return (addr >> self.slot_bits) & ((0x8000 >> self.slot_bits) - 1)

    def read(self, bank, addr):
        """A program ROM byte, with `bank` in the slot that holds addr."""
        if self.files and bank in self.files:
            lo, data = self.files[bank]
            return data[addr - lo]
        size = 1 << self.slot_bits
        return self.prg[bank * size + (addr & (size - 1))]

    def resolve(self, frm, addr):
        """The bank that code at location frm = (bank, address) will find at
        CPU address `addr`, or None if it depends on the mapper's state at
        that moment (then the jump must go through dispatch)."""
        if self.files is not None:
            # An FDS: the BIOS, or the same file while it lasts.
            if addr >= 0xE000:
                return 3
            if frm[0] in self.files and self.in_file(frm[0], addr):
                return frm[0]
            return None
        if addr < self.ram_top:
            return None                      # RAM: not translated ahead
        fbank, faddr = frm
        s_from, s_to = self.slot(faddr), self.slot(addr)
        if s_to in self.fixed:
            return self.fixed[s_to]
        if s_from == s_to:
            return fbank
        if self.unit and s_from not in self.fixed and \
                s_from // self.unit == s_to // self.unit:
            return (fbank + s_to - s_from) % self.banks
        return None

    def in_file(self, tag, addr):
        lo, data = self.files[tag]
        return lo <= addr < lo + len(data)

    def translatable(self, loc):
        """Can code at loc be translated ahead?"""
        bank, addr = loc
        if self.files is not None:
            if bank in self.files:
                return self.in_file(bank, addr)
            return bank == 3 and addr >= 0xE000
        return addr >= self.ram_top

    def guard_tag(self, loc):
        """For code in RAM that the runtime tags (code_owner in rt.h): the
        tag its bytes must have, else None (ROM)."""
        bank, addr = loc
        if self.files is not None:
            return bank if 0x6000 <= addr < 0xE000 else None
        if self.nsf and self.nsf["chips"] & 4 and 0x8000 <= addr < 0xE000:
            return 1                         # an FDS NSF's code in RAM
        return None

    def guarded(self):
        """Does any code here run from RAM that can change?"""
        return self.files is not None or bool(self.nsf and self.nsf["chips"] & 4)

    def power_on_loc(self, addr):
        return (self.power_on[self.slot(addr)], addr)

    def switches(self, addr):
        """Can the slot holding addr change banks?"""
        return self.unit is not None and self.slot(addr) not in self.fixed

    def read16(self, addr):
        b = self.power_on[self.slot(addr)]
        return self.read(b, addr) | (self.read(b, addr + 1) << 8)


# ---------------------------------------------------------------------------
# Tracing: find every reachable instruction by following control flow.
# Code is identified by location = (8 KB bank, CPU address).
# ---------------------------------------------------------------------------
def trace(rom, entries):
    insns = {}          # location -> (opcode, operand bytes)
    unknown = set()     # locations/addresses we can't translate
    work = list(entries)
    while work:
        loc = work.pop()
        while loc not in insns and loc not in unknown:
            bank, addr = loc
            opc = rom.read(bank, addr)
            if opc not in OPS:
                unknown.add(loc)
                break
            mnem, mode, _, _ = OPS[opc]
            size = SIZE[mode]
            operand = []
            for i in range(1, size):
                b = rom.resolve(loc, (addr + i) & 0xFFFF)
                if b is None:
                    break
                operand.append(rom.read(b, (addr + i) & 0xFFFF))
            if len(operand) != size - 1:     # operand lies in an unknown bank
                unknown.add(loc)
                break
            insns[loc] = (opc, operand)
            nxt = (addr + size) & 0xFFFF
            targets = []
            if mode == "rel":
                off = operand[0] - 256 if operand[0] >= 128 else operand[0]
                targets.append((nxt + off) & 0xFFFF)
            if mnem in ("JMP", "JSR") and mode == "abs":
                targets.append(operand[0] | (operand[1] << 8))
            for t in targets:
                b = rom.resolve(loc, t)
                if b is not None:
                    work.append((b, t))
            if mnem in ("JMP", "RTS", "RTI", "BRK"):
                break
            if mnem == "JSR" and targets[0] in rom.inline:
                # It returns past the pointers that follow the JSR.
                if rom.inline[targets[0]] is None:
                    break
                nxt = (nxt + 2 * rom.inline[targets[0]]) & 0xFFFF
            b = rom.resolve(loc, nxt)
            if b is None:
                break
            loc = (b, nxt)
    return insns, unknown


# ---------------------------------------------------------------------------
# C code generation
# ---------------------------------------------------------------------------
def lbl(loc):
    return "L_%02X_%04X" % loc


def key(loc):
    """The value dispatch switches on: bank in the high bits, then pc."""
    return "0x%06X" % (loc[0] << 16 | loc[1])


def ea_code(mode, operand):
    """Return (C statements computing `ea`, C expression for page-cross)."""
    if mode == "zp":
        return "ea = 0x%02X;" % operand[0], "0"
    if mode == "zpx":
        return "ea = (uint8_t)(0x%02X + X);" % operand[0], "0"
    if mode == "zpy":
        return "ea = (uint8_t)(0x%02X + Y);" % operand[0], "0"
    if mode == "abs":
        return "ea = 0x%04X;" % (operand[0] | operand[1] << 8), "0"
    if mode in ("abx", "aby"):
        base = operand[0] | operand[1] << 8
        r = "X" if mode == "abx" else "Y"
        return ("ea = (uint16_t)(0x%04X + %s);" % (base, r),
                "((0x%02X + %s) > 0xFF)" % (base & 0xFF, r))
    if mode == "izx":
        z = operand[0]
        return ("{ uint8_t p = (uint8_t)(0x%02X + X); "
                "ea = rd(p) | (rd((uint8_t)(p + 1)) << 8); }" % z), "0"
    if mode == "izy":
        z = operand[0]
        return ("base = rd(0x%02X) | (rd(0x%02X) << 8); "
                "ea = (uint16_t)(base + Y);" % (z, (z + 1) & 0xFF),
                "(((base & 0xFF) + Y) > 0xFF)")
    raise ValueError(mode)


READ_OPS = {
    "ORA": "A |= v; setzn(A);",
    "AND": "A &= v; setzn(A);",
    "EOR": "A ^= v; setzn(A);",
    "ADC": "adc(v);",
    "SBC": "adc(v ^ 0xFF);",
    "LDA": "A = v; setzn(A);",
    "LDX": "X = v; setzn(X);",
    "LDY": "Y = v; setzn(Y);",
    "LAX": "A = X = v; setzn(A);",
    "CMP": "cmp(A, v);",
    "CPX": "cmp(X, v);",
    "CPY": "cmp(Y, v);",
    "BIT": "Z = (A & v) == 0; N = v >> 7; V = (v >> 6) & 1;",
    "NOP": "(void)v;",
    "ANC": "A &= v; setzn(A); C = N;",
    "ALR": "A &= v; A = lsr(A);",
    "ARR": "A &= v; A = (uint8_t)(A >> 1 | C << 7); setzn(A); "
           "C = (A >> 6) & 1; V = C ^ ((A >> 5) & 1);",
    "AXS": "{ uint8_t ax = A & X; C = ax >= v; X = (uint8_t)(ax - v); "
           "setzn(X); }",
    # XAA and LXA mix in "magic" bits that vary between consoles; $FF is
    # the value the instr_test-v5 ROMs expect for LXA.
    "XAA": "A = (A | 0xFF) & X & v; setzn(A);",
    "LXA": "A = X = (A | 0xFF) & v; setzn(A);",
    "LAS": "A = X = SP = v & SP; setzn(A);",
}

RMW_OPS = {
    "ASL": "v = asl(v);",
    "LSR": "v = lsr(v);",
    "ROL": "v = rol(v);",
    "ROR": "v = ror(v);",
    "INC": "v++; setzn(v);",
    "DEC": "v--; setzn(v);",
    "SLO": "v = asl(v); A |= v; setzn(A);",
    "RLA": "v = rol(v); A &= v; setzn(A);",
    "SRE": "v = lsr(v); A ^= v; setzn(A);",
    "RRA": "v = ror(v); adc(v);",
    "DCP": "v--; cmp(A, v);",
    "ISB": "v++; adc(v ^ 0xFF);",
}

IMPLIED = {
    "CLC": "C = 0;", "SEC": "C = 1;", "CLI": "{ uint8_t oi = I; I = 0; cpu_i_change(oi, 2); }", "SEI": "{ uint8_t oi = I; I = 1; cpu_i_change(oi, 2); }",
    "CLV": "V = 0;", "CLD": "D = 0;", "SED": "D = 1;",
    "TAX": "X = A; setzn(X);", "TAY": "Y = A; setzn(Y);",
    "TSX": "X = SP; setzn(X);", "TXA": "A = X; setzn(A);",
    "TXS": "SP = X;", "TYA": "A = Y; setzn(A);",
    "DEX": "X--; setzn(X);", "DEY": "Y--; setzn(Y);",
    "INX": "X++; setzn(X);", "INY": "Y++; setzn(Y);",
    "NOP": "",
    "PHA": "push(A);", "PHP": "push(getP(1));",
    "PLA": "A = pop(); setzn(A);", "PLP": "{ uint8_t oi = I; setP(pop()); cpu_i_change(oi, 4); }",
}


def may_touch_io(mode, operand):
    """Could this access land on $2000-$401F (PPU, APU, controllers)?
    Those need the access on the right cycle; RAM and ROM don't care."""
    if mode in ("zp", "zpx", "zpy"):
        return False                    # zero page is always RAM
    if mode == "abs":
        a = operand[0] | operand[1] << 8
        return 0x2000 <= a < 0x4020
    if mode in ("abx", "aby"):
        a = operand[0] | operand[1] << 8
        return a <= 0x401F and a + 0xFF >= 0x2000
    return True                         # pointers: could be anywhere


def mem_body(mnem, mode, cyc, pen, cross, base, timed, value=None):
    """C statements for a load, store or read-modify-write, after `ea` is
    computed. `base` is the address before indexing (for dummy reads).

    Untimed: do the access, then add the cycles (fast; for RAM/ROM).
    Timed: add cycles up to the bus cycle where the real CPU makes each
    access, so the PPU sees reads and writes at the right moment. Indexed
    modes also make the CPU's "dummy" read from the not-yet-carried
    address, and read-modify-write writes the old value back first."""
    indexed = mode in ("abx", "aby", "izy")
    unfixed = "(uint16_t)((%s & 0xFF00) | (ea & 0xFF))" % base
    if mnem in HIGH_STORES:
        pre = ["SP = A & X;"] if mnem == "TAS" else []
        pre.append("v = (uint8_t)(%s & ((%s >> 8) + 1)); "
                   "if ((%s ^ ea) & 0xFF00) ea = (uint16_t)((ea & 0xFF) | v << 8);"
                   % (HIGH_STORES[mnem], base, base))
        return pre + mem_body("STA", mode, cyc, pen, cross, base, timed,
                              value="v")
    if not timed:
        if mnem in STORES:
            return ["wr(ea, %s);" % (value or STORES[mnem]), "cycles += %d;" % cyc]
        if mnem in RMW:
            return ["v = rd(ea); %s wr(ea, v);" % RMW_OPS[mnem],
                    "cycles += %d;" % cyc]
        out = ["v = rd(ea); %s" % READ_OPS[mnem]]
        if pen and cross != "0":
            return out + ["cycles += %d + %s;" % (cyc, cross)]
        return out + ["cycles += %d;" % cyc]
    if mnem in STORES:
        val = value or STORES[mnem]
        if indexed:
            return ["cycles += %d; dummy_rd(%s); cycles += 1;" % (cyc - 2, unfixed),
                    "wr(ea, %s); cycles += 1;" % val]
        return ["cycles += %d; wr(ea, %s); cycles += 1;" % (cyc - 1, val)]
    if mnem in RMW:
        pre = ("cycles += %d; dummy_rd(%s); cycles += 1;" % (cyc - 4, unfixed)
               if indexed else "cycles += %d;" % (cyc - 3))
        return [pre, "v = rd(ea); cycles += 1; wr(ea, v); cycles += 1;",
                RMW_OPS[mnem], "wr(ea, v); cycles += 1;"]
    out = ["cycles += %d;" % (cyc - 1)]
    if pen and cross != "0":
        out.append("if (%s) { dummy_rd(%s); cycles += 1; }" % (cross, unfixed))
    return out + ["v = rd(ea); cycles += 1; %s" % READ_OPS[mnem]]


def goto(frm, tgt, rom, insns):
    """C for a jump from location frm to CPU address tgt: straight to its
    label when we know which bank it lands in and it was translated;
    otherwise through dispatch, which looks at the banks mapped right now
    (RAM code, a switchable bank, or a spot the tracer stopped at)."""
    b = rom.resolve(frm, tgt)
    if b is not None and (b, tgt) in insns:
        return "goto %s;" % lbl((b, tgt))
    return "{ pc = 0x%04X; goto dispatch; }" % tgt


def may_write_mapper(mode, operand, rom):
    """Could this store reach a mapper register ($8000-$FFFF, or the
    mapper's low_regs range such as MMC5's $5100-$5117)?"""
    if mode in ("zp", "zpx", "zpy"):
        return False
    lo, hi = rom.low_regs or (0x8000, 0x8000)
    if mode == "abs":
        a = operand[0] | operand[1] << 8
        return a >= 0x8000 or lo <= a <= hi
    if mode in ("abx", "aby"):
        a = operand[0] | operand[1] << 8
        return a + 0xFF >= 0x8000 or (a <= hi and a + 0xFF >= lo)
    return True


def gen_insn(loc, opc, operand, rom, insns):
    addr = loc[1]
    mnem, mode, cyc, pen = OPS[opc]
    size = SIZE[mode]
    nxt = (addr + size) & 0xFFFF
    tag = rom.guard_tag(loc)
    if tag is None:
        out = ["%s: EVENT_CHECK(0x%04X); STEP(0x%04X);" % (lbl(loc), addr, addr)]
    else:
        # Code in RAM: only while its bytes are the ones translated.
        own = [(addr + i) & 0xFFFF for i in range(size)]
        cond = " || ".join("code_owner[0x%04X] != %d" % (a - 0x6000, tag)
                           for a in own if 0x6000 <= a < 0xE000)
        out = ["%s: EVENT_CHECK(0x%04X);" % (lbl(loc), addr),
               "    if (%s) { pc = 0x%04X; goto changed; }" % (cond, addr),
               "    ram_native++; STEP(0x%04X);" % addr]
    body = []
    falls = True

    if mode == "imp" and mnem in IMPLIED:
        body.append(IMPLIED[mnem])
        body.append("cycles += %d;" % cyc)
    elif mode == "acc":
        body.append(RMW_OPS[mnem].replace("v", "A"))
        body.append("cycles += %d;" % cyc)
    elif mode == "imm":
        body.append("v = 0x%02X; %s" % (operand[0], READ_OPS[mnem]))
        body.append("cycles += %d;" % cyc)
    elif mode == "rel":
        off = operand[0] - 256 if operand[0] >= 128 else operand[0]
        tgt = (nxt + off) & 0xFFFF
        extra = 2 if (tgt & 0xFF00) != (nxt & 0xFF00) else 1
        body.append("cycles += %d;" % cyc)
        body.append("if (%s) { cycles += %d; %s }"
                    % (BRANCH[mnem], extra, goto(loc, tgt, rom, insns)))
    elif mnem == "JMP" and mode == "abs":
        tgt = operand[0] | operand[1] << 8
        body.append("cycles += 3; %s" % goto(loc, tgt, rom, insns))
        falls = False
    elif mnem == "JMP" and mode == "ind":
        p = operand[0] | operand[1] << 8
        hi = (p & 0xFF00) | ((p + 1) & 0xFF)   # the famous 6502 page-wrap bug
        body.append("pc = rd(0x%04X) | (rd(0x%04X) << 8); cycles += 5; "
                    "goto dispatch;" % (p, hi))
        falls = False
    elif mnem == "JSR":
        tgt = operand[0] | operand[1] << 8
        ret = (addr + 2) & 0xFFFF
        body.append("push(0x%02X); push(0x%02X); cycles += 6; %s"
                    % (ret >> 8, ret & 0xFF, goto(loc, tgt, rom, insns)))
        falls = False
    elif mnem == "RTS":
        body.append("pc = pop(); pc |= pop() << 8; pc++; cycles += 6; "
                    "goto dispatch;")
        falls = False
    elif mnem == "RTI":
        body.append("setP(pop()); pc = pop(); pc |= pop() << 8; "
                    "cycles += 6; cpu_irq_poll(0); goto dispatch;")
        falls = False
    elif mnem == "BRK":
        ret = (addr + 2) & 0xFFFF
        body.append("push(0x%02X); push(0x%02X); push(getP(1)); I = 1; "
                    "pc = brk_vector(); cycles += 7; goto dispatch;"
                    % (ret >> 8, ret & 0xFF))
        falls = False
    else:
        calc, cross = ea_code(mode, operand)
        body.append(calc)
        base = ("base" if mode == "izy" else
                "0x%04X" % (operand[0] | operand[1] << 8) if size == 3 else "ea")
        writes = mnem in STORES or mnem in RMW or mnem in HIGH_STORES
        # Writes that may reach a mapper are timed too: some mappers (MMC1)
        # care which cycle a write lands on, and a sound chip's change
        # should land on the right cycle.
        timed = may_touch_io(mode, operand) or (
            writes and rom.high_writes and may_write_mapper(mode, operand, rom))
        body += mem_body(mnem, mode, cyc, pen, cross, base, timed)
        # Code in a switchable bank that writes to the mapper may have just
        # switched itself out: carry on through dispatch if so.
        if writes and rom.switches(addr) and may_write_mapper(mode, operand, rom):
            body.append("if (mapper.bank_changed) { mapper.bank_changed = 0; "
                        "pc = 0x%04X; goto dispatch; }" % nxt)

    out.append("    " + " ".join(body))
    if falls:
        out.append("    " + goto(loc, nxt, rom, insns))
    return out


def interp_ea(mode):
    """Like ea_code, but operands are read at runtime (for the interpreter)."""
    return {
        "zp": ("ea = o1;", "0"),
        "zpx": ("ea = (uint8_t)(o1 + X);", "0"),
        "zpy": ("ea = (uint8_t)(o1 + Y);", "0"),
        "abs": ("ea = o1 | (o2 << 8);", "0"),
        "abx": ("base = o1 | (o2 << 8); ea = (uint16_t)(base + X);",
                "(((base & 0xFF) + X) > 0xFF)"),
        "aby": ("base = o1 | (o2 << 8); ea = (uint16_t)(base + Y);",
                "(((base & 0xFF) + Y) > 0xFF)"),
        "izx": ("{ uint8_t p = (uint8_t)(o1 + X); "
                "ea = rd(p) | (rd((uint8_t)(p + 1)) << 8); }", "0"),
        "izy": ("base = rd(o1) | (rd((uint8_t)(o1 + 1)) << 8); "
                "ea = (uint16_t)(base + Y);", "(((base & 0xFF) + Y) > 0xFF)"),
    }[mode]


def gen_interp_case(opc):
    """One case of the fallback interpreter, from the same opcode table."""
    mnem, mode, cyc, pen = OPS[opc]
    size = SIZE[mode]
    b = []
    adv = "pc += %d;" % size
    if mode == "imp" and mnem in IMPLIED:
        b += [IMPLIED[mnem], "cycles += %d;" % cyc, adv]
    elif mode == "acc":
        b += [RMW_OPS[mnem].replace("v", "A"), "cycles += %d;" % cyc, adv]
    elif mode == "imm":
        b += ["v = o1;", READ_OPS[mnem], "cycles += %d;" % cyc, adv]
    elif mode == "rel":
        b += ["cycles += 2;",
              "if (%s) { uint16_t n = pc + 2; uint16_t t = n + (int8_t)o1; "
              "cycles += ((t & 0xFF00) != (n & 0xFF00)) ? 2 : 1; pc = t; }"
              " else pc += 2;" % BRANCH[mnem]]
    elif mnem == "JMP" and mode == "abs":
        b += ["pc = o1 | (o2 << 8); cycles += 3;"]
    elif mnem == "JMP" and mode == "ind":
        b += ["{ uint16_t p = o1 | (o2 << 8); "
              "pc = rd(p) | (rd((p & 0xFF00) | ((p + 1) & 0xFF)) << 8); }"
              " cycles += 5;"]
    elif mnem == "JSR":
        b += ["{ uint16_t r = pc + 2; push(r >> 8); push(r & 0xFF); }"
              " pc = o1 | (o2 << 8); cycles += 6;"]
    elif mnem == "RTS":
        b += ["pc = pop(); pc |= pop() << 8; pc++; cycles += 6;"]
    elif mnem == "RTI":
        b += ["setP(pop()); pc = pop(); pc |= pop() << 8; cycles += 6;"
              " cpu_irq_poll(0);"]
    elif mnem == "BRK":
        b += ["{ uint16_t r = pc + 2; push(r >> 8); push(r & 0xFF); }"
              " push(getP(1)); I = 1; pc = brk_vector(); cycles += 7;"]
    else:
        calc, cross = interp_ea(mode)
        b.append(calc)
        base = "base" if mode in ("abx", "aby", "izy") else "ea"
        b += mem_body(mnem, mode, cyc, pen, cross, base,
                      mode not in ("zp", "zpx", "zpy"))
        b.append(adv)
    return "    case 0x%02X: %s break;" % (opc, " ".join(b))


def gen_interpreter():
    lines = [
        "/* Fallback interpreter: runs one instruction at pc. Used only when",
        "   execution reaches code the tracer could not see ahead of time. */",
        "int interp_step(void) {",
        "    uint16_t ea, base; uint8_t v;",
        "    (void)ea; (void)base; (void)v;",
        "    insn_pc = pc; insn_start = cycles;",
        "    STEP(pc);",
        "    uint8_t opc = rd(pc), o1 = rd(pc + 1), o2 = rd(pc + 2);",
        "    (void)o2;",
        "    switch (opc) {",
    ]
    for opc in sorted(OPS):
        lines.append(gen_interp_case(opc))
    lines += ["    default: return 0;", "    }", "    return 1;", "}", ""]
    return lines


def gen_cycle_maps():
    lines = ["/* Bus cycles of each opcode, one letter per cycle; the key is",
             "   CYCLE_KEY in recomp.py. Used by runtime/cycles.c. */",
             "const char *const cycle_map[256] = {"]
    for opc in sorted(OPS):
        mnem, mode = OPS[opc][:2]
        lines.append('    [0x%02X] = "%s",  /* %s %s */' % (
            opc, cycle_map(mnem, mode), mnem, mode))
    lines += ["};", ""]
    return lines


def generate(rom, insns, unknown, src_name):
    lines = [
        "/* Generated by nesrecomp from %s. Do not edit by hand. */" % src_name,
        '#include "rt.h"',
        '#include "mapper.h"',
        "",
    ]
    lines += gen_interpreter()
    lines += gen_cycle_maps()
    bank_now = ("mapper.prg_bank[(pc >> 13) & 3]" if rom.slot_bits == 13
                else "mapper.prg_bank_4k[(pc >> 12) & 7]")
    if rom.files is not None:          # an FDS: RAM is keyed by file
        bank_now = ("(pc >= 0x6000 && pc < 0xE000 ? code_owner[pc - 0x6000] : %s)"
                    % bank_now)
    lines += [
        "void recomp_run(uint16_t start) {",
        "    uint16_t ea, base; uint8_t v;",
        "    int in_interp = 0;",
        "    (void)ea; (void)base; (void)v;",
        "    pc = start;",
        "dispatch:",
        "    INTERRUPT_CHECK();",
        "    /* Look up the bank mapped at pc right now, as well as pc. */",
        "    switch ((uint32_t)%s << 16 | pc) {" % bank_now,
    ]
    for loc in sorted(insns):
        lines.append("    case %s: in_interp = 0; goto %s;" % (key(loc), lbl(loc)))
    lines += [
        "    default:",
        "        if (!in_interp) note_missed(pc);",
        "        in_interp = 1;",
    ]
    if rom.guarded():
        lines += [
            "        if (pc >= 0x6000 && pc < 0xE000) ram_interp++;",
            "        if (!interp_step()) { untranslated(pc); return; }",
            "        goto dispatch;",
            "    }",
            "",
            "changed:  /* code in RAM that isn't what was translated any more */",
            "    ram_interp++;",
            "    in_interp = 1;",
            "    if (!interp_step()) { untranslated(pc); return; }",
            "    goto dispatch;",
            "",
        ]
    else:
        lines += [
            "        if (!interp_step()) { untranslated(pc); return; }",
            "        goto dispatch;",
            "    }",
            "",
        ]
    lines += [
        "event: {  /* hardware needs attention; pc holds the next address */",
        "        uint16_t vector = runtime_event();",
        "        if (vector) take_interrupt(vector);",
        "        goto dispatch;",
        "    }",
        "",
    ]
    for loc in sorted(insns):
        opc, operand = insns[loc]
        lines += gen_insn(loc, opc, operand, rom, insns)
    lines.append("}")
    return "\n".join(lines) + "\n"


def dump_rom(rom, entries):
    """--dump-rom: what was read, one fact a line, for comparing with the C
    version's reading of the same file (tests/check_recomp.py)."""
    import zlib

    def slots(d):
        return " ".join("%d:%d" % kv for kv in sorted(d.items()))
    if rom.nsf is None and rom.files is None:
        print("header " + " ".join("%s=%d" % (k, int(v)) for k, v in sorted(rom.header.items())))
    print("mapper %d %s" % (rom.mapper, rom.mapper_name))
    print("unit %s" % ("none" if rom.unit is None else rom.unit))
    print("slot_bits %d banks %d ram_top %04X high_writes %d" % (
        rom.slot_bits, rom.banks, rom.ram_top, rom.high_writes))
    print("low_regs %s" % ("none" if not rom.low_regs else "%04X-%04X" % rom.low_regs))
    print("power_on " + slots(rom.power_on))
    print("fixed " + slots(rom.fixed))
    print("prg %d %08X" % (len(rom.prg), zlib.crc32(rom.prg)))
    print("nsf " + ("none" if rom.nsf is None else
                    "load=%(load)04X init=%(init)04X play=%(play)04X chips=%(chips)d" % rom.nsf))
    print("inline " + " ".join("%04X:%s" % (a, "none" if n is None else n)
                               for a, n in sorted(rom.inline.items())))
    print("guarded %d" % rom.guarded())
    if rom.files is not None:
        print("files_count %d" % rom.files_count)
        for t, (lo, data) in sorted(rom.files.items()):
            print("file %d %04X %d %08X" % (t, lo, len(data), zlib.crc32(data)))
        print("boot_ram %08X boot_owner %08X" % (zlib.crc32(rom.boot_ram),
                                                 zlib.crc32(bytes(rom.boot_owner))))
    print("entries " + " ".join("%02X:%04X" % e for e in entries))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("rom")
    ap.add_argument("-o", "--out")
    # For checking the C version (recomp/, PLAN-standalone.md step 2a):
    # print everything read from the file, and the entry points, and stop.
    ap.add_argument("--dump-rom", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--entry", action="append", default=[],
                    help="extra entry point in hex (e.g. C000)")
    ap.add_argument("--missed", action="append", default=[],
                    help="file of addresses a previous run had to interpret;"
                         " they become entry points for native translation")
    args = ap.parse_args()
    if not args.out and not args.dump_rom:
        ap.error("the following arguments are required: -o/--out")

    rom = Rom(args.rom)

    vectors = [rom.read16(0xFFFA), rom.read16(0xFFFC), rom.read16(0xFFFE)]
    entries = [rom.power_on_loc(v) for v in vectors]
    if rom.nsf:                  # no reset: the runtime calls init and play
        entries += [rom.power_on_loc(rom.nsf[k]) for k in ("init", "play")
                    if rom.nsf[k] >= 0x8000]  # an FDS NSF's code in RAM: interpreted
    if rom.files is not None:
        entries += rom.fds_entries()
    entries += [rom.power_on_loc(int(e, 16)) for e in args.entry]
    for path in args.missed:
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            if ":" in line:                      # BB:AAAA
                b, a = line.split(":")
                entries.append((int(b, 16) % rom.banks, int(a, 16)))
            else:                                # old format: AAAA
                entries.append(rom.power_on_loc(int(line, 16)))
    entries = [e for e in entries if rom.translatable(e)]
    if args.dump_rom:
        dump_rom(rom, entries)
        return
    insns, unknown = trace(rom, entries)

    with open(args.out, "w") as f:
        f.write(generate(rom, insns, unknown, args.rom.split("/")[-1]))

    if rom.mapper == FDS_MAPPER:
        print("FDS disk image, %d file(s): the BIOS and %d PRG file(s) in RAM"
              " can be translated" % (rom.files_count, len(rom.files)))
    elif not rom.nsf:
        print("mapper %d (%s), %d KB program ROM" % (
            rom.mapper, rom.mapper_name, len(rom.prg) // 1024))
    if rom.nsf:
        print("NSF: load=%(load)04X init=%(init)04X play=%(play)04X" % rom.nsf)
    else:
        print("vectors: NMI=%04X RESET=%04X IRQ=%04X" % tuple(vectors))
    banks = sorted({loc[0] for loc in insns})
    print("translated %d instructions in %d bank(s) -> %s" % (
        len(insns), len(banks), args.out))
    if unknown:
        print("stopped at %d untranslatable spot(s): %s" % (
            len(unknown), " ".join("%02X:%04X" % u for u in sorted(unknown))))


if __name__ == "__main__":
    main()
