#!/usr/bin/env python3
"""The Bandai LZ93D50's EEPROM is kept in <rom>.sav (PLAN-mappers3.md
step 4). Runs tests/bandai_lz.nes, as the suite built it, three times on
a copy in build/bandai_save:

  1. with no .sav: the program finds EEPROM byte $40 blank, and the .sav
     written afterwards is the EEPROM's 256 bytes, holding what the
     program wrote ($5A at $40; $11, $22 at $FE, $FF; $33 at $F8);
  2. again: it finds $5A at $40 (kept);
  3. with $40 changed to $77 in the .sav: it finds that (so it really
     reads the file).

Run tests/run_tests.py bandai_lz first (make test-ppu does both).
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import toolchain  # noqa: E402

EXE = os.path.join(ROOT, "build", "tests", "tests_bandai_lz.nes" + toolchain.EXE)
WORK = os.path.join(ROOT, "build", "bandai_save")
failed = 0


def check(ok, what):
    global failed
    print(("ok     " if ok else "FAIL   ") + what)
    failed += not ok


def run(rom):
    r = subprocess.run([EXE, rom, "--headless", "--frames", "60"],
                       capture_output=True, text=True, timeout=60)
    return r.stderr


def main():
    if not os.path.exists(EXE):
        sys.exit("%s isn't built: run tests/run_tests.py bandai_lz first" % EXE)
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    rom = os.path.join(WORK, "bandai_lz.nes")
    shutil.copy(os.path.join(HERE, "bandai_lz.nes"), rom)
    sav = rom + ".sav"

    out = run(rom)
    check("test status at $6000: $00" in out, "first run: the test passes")
    check("EEPROM $40: BLANK" in out, "first run: EEPROM byte $40 starts blank")
    data = open(sav, "rb").read() if os.path.exists(sav) else b""
    check(len(data) == 256, "the .sav is the EEPROM's 256 bytes (%d)" % len(data))
    if len(data) == 256:
        check((data[0x40], data[0xFE], data[0xFF], data[0xF8]) == (0x5A, 0x11, 0x22, 0x33),
              "the .sav holds what the program wrote ($40, $FE, $FF, $F8)")

    out = run(rom)
    check("EEPROM $40: KEPT" in out, "second run: byte $40 kept ($5A)")

    if len(data) == 256:
        with open(sav, "r+b") as f:
            f.seek(0x40)
            f.write(b"\x77")
        out = run(rom)
        check("EEPROM $40: OTHER" in out, "with $77 put in the .sav: the program reads that")

    print("\nall checks pass" if not failed else "\n%d check(s) failed" % failed)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
