#!/usr/bin/env python3
"""
nesrecomp - a static recompiler for NES (6502) programs.

It reads an iNES (.nes) file, traces the reachable 6502 code starting from
the cartridge's interrupt vectors (or entry points you give it), and writes
C source where every 6502 instruction becomes a few lines of C.

The ROM data itself is NOT copied into the output: the generated program
still loads the .nes file at runtime for graphics and data tables. Only the
control flow and instruction logic are translated.

Usage:
    python3 recomp.py game.nes -o build/game.c [--entry C000 ...]

Current scope: mapper 0 (NROM). Bank switching comes later.
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
    # Action 53 switches 16 or 32 KB with either half fixed, depending on a
    # mode the program sets, so no slot is safe to treat as fixed. It
    # starts in its last 32 KB.
    28: dict(name="Action 53", unit=2, fixed={},
             power_on={0: -4, 1: -3, 2: -2, 3: -1}),
}


class Rom:
    def __init__(self, path):
        data = open(path, "rb").read()
        if data[:4] != b"NES\x1a":
            sys.exit("not an iNES file")
        self.prg_banks = data[4]
        self.chr_banks = data[5]
        self.mapper = (data[6] >> 4) | (data[7] & 0xF0)
        if (data[7] & 0x0C) == 0x08:                 # NES 2.0 header
            self.mapper |= (data[8] & 0x0F) << 8
        elif any(data[12:16]):                       # junk in old dumps
            self.mapper &= 0x0F
        trainer = 512 if data[6] & 4 else 0
        start = 16 + trainer
        self.prg = data[start:start + self.prg_banks * 0x4000]
        self.banks = len(self.prg) // 0x2000         # 8 KB banks

        if self.mapper not in MAPPERS:
            sys.exit("mapper %d is not supported (supported: %s)" % (
                self.mapper, ", ".join("%d %s" % (k, v["name"])
                                       for k, v in sorted(MAPPERS.items()))))
        m = MAPPERS[self.mapper]
        self.mapper_name = m["name"]
        self.unit = m["unit"]
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

    def read(self, bank, addr):
        """A program ROM byte, with `bank` in the slot that holds addr."""
        return self.prg[bank * 0x2000 + (addr & 0x1FFF)]

    def resolve(self, frm, addr):
        """The bank that code at location frm = (bank, address) will find at
        CPU address `addr`, or None if it depends on the mapper's state at
        that moment (then the jump must go through dispatch)."""
        if addr < 0x8000:
            return None                      # RAM: not translated ahead
        fbank, faddr = frm
        s_from, s_to = (faddr >> 13) & 3, (addr >> 13) & 3
        if s_to in self.fixed:
            return self.fixed[s_to]
        if s_from == s_to:
            return fbank
        if self.unit and s_from not in self.fixed and \
                s_from // self.unit == s_to // self.unit:
            return (fbank + s_to - s_from) % self.banks
        return None

    def power_on_loc(self, addr):
        return (self.power_on[(addr >> 13) & 3], addr)

    def switches(self, addr):
        """Can the slot holding addr change banks?"""
        return self.unit is not None and ((addr >> 13) & 3) not in self.fixed

    def read16(self, addr):
        b = self.power_on[(addr >> 13) & 3]
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


def may_write_mapper(mode, operand):
    """Could this store reach a mapper register ($8000-$FFFF)?"""
    if mode in ("zp", "zpx", "zpy"):
        return False
    if mode == "abs":
        return (operand[0] | operand[1] << 8) >= 0x8000
    if mode in ("abx", "aby"):
        return (operand[0] | operand[1] << 8) + 0xFF >= 0x8000
    return True


def gen_insn(loc, opc, operand, rom, insns):
    addr = loc[1]
    mnem, mode, cyc, pen = OPS[opc]
    size = SIZE[mode]
    nxt = (addr + size) & 0xFFFF
    out = ["%s: EVENT_CHECK(0x%04X); STEP(0x%04X);" % (lbl(loc), addr, addr)]
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
        # care which cycle a write lands on.
        timed = may_touch_io(mode, operand) or (
            writes and rom.unit is not None and may_write_mapper(mode, operand))
        body += mem_body(mnem, mode, cyc, pen, cross, base, timed)
        # Code in a switchable bank that writes to the mapper may have just
        # switched itself out: carry on through dispatch if so.
        if writes and rom.switches(addr) and may_write_mapper(mode, operand):
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
    lines += [
        "void recomp_run(uint16_t start) {",
        "    uint16_t ea, base; uint8_t v;",
        "    int in_interp = 0;",
        "    (void)ea; (void)base; (void)v;",
        "    pc = start;",
        "dispatch:",
        "    INTERRUPT_CHECK();",
        "    /* Look up the bank mapped at pc right now, as well as pc. */",
        "    switch ((uint32_t)mapper.prg_bank[(pc >> 13) & 3] << 16 | pc) {",
    ]
    for loc in sorted(insns):
        lines.append("    case %s: in_interp = 0; goto %s;" % (key(loc), lbl(loc)))
    lines += [
        "    default:",
        "        if (!in_interp) note_missed(pc);",
        "        in_interp = 1;",
        "        if (!interp_step()) { untranslated(pc); return; }",
        "        goto dispatch;",
        "    }",
        "",
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


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("rom")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--entry", action="append", default=[],
                    help="extra entry point in hex (e.g. C000)")
    ap.add_argument("--missed", action="append", default=[],
                    help="file of addresses a previous run had to interpret;"
                         " they become entry points for native translation")
    args = ap.parse_args()

    rom = Rom(args.rom)

    vectors = [rom.read16(0xFFFA), rom.read16(0xFFFC), rom.read16(0xFFFE)]
    entries = [rom.power_on_loc(v) for v in vectors]
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
    entries = [e for e in entries if e[1] >= 0x8000]
    insns, unknown = trace(rom, entries)

    with open(args.out, "w") as f:
        f.write(generate(rom, insns, unknown, args.rom.split("/")[-1]))

    print("mapper %d (%s), %d KB program ROM" % (
        rom.mapper, rom.mapper_name, len(rom.prg) // 1024))
    print("vectors: NMI=%04X RESET=%04X IRQ=%04X" % tuple(vectors))
    banks = sorted({loc[0] for loc in insns})
    print("translated %d instructions in %d bank(s) -> %s" % (
        len(insns), len(banks), args.out))
    if unknown:
        print("stopped at %d untranslatable spot(s): %s" % (
            len(unknown), " ".join("%02X:%04X" % u for u in sorted(unknown))))


if __name__ == "__main__":
    main()
