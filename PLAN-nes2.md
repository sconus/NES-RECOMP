# Plan: NES 2.0 headers

Goal: read the whole NES 2.0 header, and use what it says. That covers the
ROM and RAM sizes, the board variant (the "submapper"), the console it was
made for, and the controller or device it expects. Today both the
recompiler and the runtime read only the 12-bit mapper number from an
NES 2.0 header. Everything else is read as if it were iNES 1.0, so the
runtime guesses where the header could have told it.

`make test-all` must not get worse at any step; nestest stays exact.
iNES 1.0 files must behave exactly as before. `recomp.py` will change
this time (larger ROM sizes), but every ROM in the collection must still
recompile to byte-identical C.

## The header

From the nesdev wiki's "NES 2.0", "NES 2.0 submappers" and "INES" pages.
An NES 2.0 header has byte 7 bits 2-3 = `10`, and the sizes it gives must
fit in the file. Otherwise it is iNES 1.0, or an old dump with junk in
bytes 12-15, which the code already handles.
- Byte 8: mapper bits 8-11 (already read), and the submapper in the
  high 4 bits.
- Byte 9: the high 4 bits of the PRG ROM and CHR ROM sizes. A value of
  `$F` switches to an exponent form: 2^E × (1, 3, 5 or 7) bytes.
- Bytes 10-11: PRG RAM, PRG NVRAM (battery-backed), CHR RAM and CHR
  NVRAM. Each nibble is 0 for none, otherwise 64 << n bytes. CHR RAM
  must be declared here; an NES 2.0 header doesn't imply it from "no
  CHR ROM".
- Byte 12: timing (NTSC, PAL, multi-region, Dendy).
- Byte 7 bits 0-1 and byte 13: the console type (NES/Famicom, Vs.
  System, PlayChoice-10, extended types).
- Byte 14: extra ROMs (PlayChoice-10 and a few odd boards).
- Byte 15: the default expansion device. Examples: `$02` Four Score,
  `$03` Famicom four players, `$08` Zapper on `$4017`, `$49` Zapper on
  `$4016`, `$0F` Arkanoid NES, `$10` Arkanoid Famicom.

## What exists

- `recomp.py` (`Rom.__init__`) and `runtime/cart.c` (`cart_load`) each
  read the header and must agree.
- PRG RAM is always 8 KB at `$6000`, and CHR RAM is 8 KB when there is no
  CHR ROM (Action 53 grows it to 32 KB itself). The battery bit saves all
  8 KB.
- Guesses written down in earlier stages, for want of a submapper:
  - Color Dreams has no bus conflicts; UxROM, CNROM, BNROM and GxROM do.
  - Each VRC2/VRC4 number decodes both of its wirings at once.
  - VRC7 decodes both of its wirings.
  - Namco 163 plays 16.5 dB over the APU.
- The runtime is NTSC only, with no Vs. System or PlayChoice-10 parts.

## Test material

The collection has five NES 2.0 files:
- `other/oam3.nes`: AxROM, 1 KB CHR RAM.
- `other/pulsar.nes`: MMC1, 32 KB PRG NVRAM, 8 KB CHR RAM.
- `other/oc.nes`: NROM.
- `m22chrbankingtest/0-127.nes`: VRC2a.
- `nrom368/fail368.nes`: NROM, multi-region.

All of them run today, so each must run the same afterwards. Everything
else is tested with headers written by the project's own generators:
- existing generated ROMs with NES 2.0 headers;
- small new test ROMs, one per variant, graded through `$6000`.

## Steps

### 1. Read the whole header (done)
- One reading of the header in `recomp.py` and one in `cart.c`, giving
  the same fields: the ROM sizes (with byte 9 and the exponent form) and
  the submapper. Also the four RAM sizes, timing, console type, extra
  ROMs and the expansion device. With iNES 1.0, the fields get today's
  values.
- Refuse a header that can't be right: a PRG ROM that isn't a whole
  number of 8 KB banks, or sizes larger than the file (the wiki then
  says to read it as iNES 1.0). Give a warning, not a refusal, for:
  - a PAL or Dendy program (it runs at NTSC speed);
  - a Vs. System or PlayChoice-10 program;
  - an extended console type;
  - extra ROMs.
- `--info` prints all of it.
- Check:
  - every ROM in the collection recompiles to the same C;
  - `--info` on the five NES 2.0 files;
  - a script that writes headers with each field set and compares
    `recomp.py`'s and `--info`'s readings.
  - Break: byte 9 ignored, the exponent form wrong, the submapper
    nibble swapped, the file-size rule skipped.
- Done: `read_header` in `recomp.py` and `read_header` in `cart.c`
  read every field. With iNES 1.0 the new fields hold what the runtime
  always assumed: 8 KB of PRG RAM (battery-backed with the battery bit)
  and 8 KB of CHR RAM without CHR ROM. Nothing uses the new fields yet;
  steps 2-4 do.
  - Refused by both: no PRG ROM, PRG not a whole number of 8 KB, CHR
    not a whole number of 1 KB, a size over 2^30 bytes, and a file
    shorter than its header says. `recomp.py` didn't check that last
    one before.
  - The runtime warns about PAL/Dendy, Vs. System, PlayChoice-10,
    extended console types and extra ROMs, and runs the program
    anyway.
  - `--info` has three new lines: the header kind and submapper, all
    sizes, then timing, console, extra ROMs and expansion device.
  - `tests/check_headers.py` (now part of `make test`) writes 19
    headers and compares both readings with values written by hand.
    Among them: every field at once, byte 9 for PRG and for CHR, the
    exponent form with multipliers 3 and 7, sizes that must be
    refused, the file-size rule (with and without a trainer), old
    dumps' junk, and byte 13 for each console type.
  - All 319 files under `tests/` recompile to the same C. No ROM in
    the collection gets a new warning, and `--info` on the five NES
    2.0 files reads what they declare.
  - Breaks, all 15 caught (each in one reader):
    - byte 9 ignored (recomp, runtime);
    - the exponent's multiplier, and its bits (one in each);
    - the submapper nibble swapped (both);
    - the file-size rule skipped (both);
    - the trainer left out of that rule;
    - RAM sizes 32 << n;
    - the junk rule applied to NES 2.0;
    - byte 15's top bit kept;
    - byte 13 kept for PlayChoice-10;
    - iNES 1.0's battery RAM;
    - the runtime's truncation check.
  - 174 of 175; nestest exact.

### 2. RAM sizes
- CHR RAM: the size the header gives. Without CHR RAM or ROM, pattern
  reads are 0.
- PRG RAM at `$6000`: none when the header says 0, so reads give the
  open bus and writes go nowhere. Otherwise the size given, mirrored
  across `$6000-$7FFF` when smaller than 8 KB. The `.sav` file holds
  only the NVRAM part.
- MMC1 boards with 16 or 32 KB of PRG RAM (SOROM, SXROM) switch which
  8 KB shows at `$6000`, using bits of the CHR bank registers. `pulsar`
  declares 32 KB.
- Check: a generated test ROM per size, for example:
  - no PRG RAM;
  - 2 KB, to see the mirroring;
  - MMC1 with 32 KB, with banks written and read back;
  - CHR RAM of 16 KB on a board that banks it.
  - Also `pulsar` and `oam3` before and after, and battery saves of
    the right length.
  - Break each part.

### 3. Board variants (submappers)
Use the submapper where the runtime guesses today. Submapper 0 keeps
today's behaviour.
- UxROM, CNROM, AxROM: 1 = no bus conflicts, 2 = bus conflicts.
- BNROM (34): 2 = BNROM (as now). NINA-001 (1) isn't supported; refuse
  it.
- MMC1: 5 = 32 KB of fixed PRG (SEROM, SHROM).
- VRC2/VRC4 (21, 23, 25): 1 and 2 pick one wiring (VRC4a/b/f or
  c/d/e). 3 = VRC2b/VRC2c: a VRC2, with no IRQ and two-screen
  mirroring only, plus the one-bit latch at `$6000-$6FFF` that an
  earlier stage left out.
- VRC7 (85): 1 = VRC7b (A3), 2 = VRC7a (A4), each decoding only its own
  wiring.
- Namco 163 (19): 2 = no sound; 3, 4, 5 = 12, 16.5 and 18.75 dB (the
  middle of each range the wiki gives).
- Check: a generated test ROM per variant that tells the variants apart.
  For example, a write that only the other wiring would decode, and a
  bus conflict that changes the bank. Each fails with the wrong
  submapper. Break each one.

### 4. The expected controller
- With no input options, plug in what byte 15 names:
  - Four Score;
  - Famicom four players;
  - Zapper on port 2 (`$08`) or port 1 (`$49`);
  - Arkanoid NES (port 2) or Famicom.
  The options from the last two stages still win over it. Devices the
  runtime doesn't have (Power Pad, keyboards, two Zappers, ...) give a
  warning and standard controllers.
- `--info` says what was plugged in.
- Check: the Zapper, paddle and four-player test ROMs from the last two
  stages, rebuilt with an NES 2.0 header naming their device, pass
  without any option. Without the header byte they fail as before.
  Break it.

### 5. Suite, README, notes
Accept the new checks, document the header fields and what each does,
update the status list, and write where the stage ended.

## Not in this stage
- PAL and Dendy timing (a different CPU/PPU clock and frame), the Vs.
  System and PlayChoice-10 hardware, and the extended console types.
  These are read and reported only.
- MMC3 variants (MMC6, MC-ACC, NEC's IRQ), NINA-001, and other
  submappers of boards the runtime doesn't have.
- CHR NVRAM saves (no supported board has it).

## Risks
- Real NES 2.0 dumps sometimes get the RAM nibbles wrong. Taking "no
  PRG RAM" literally could break a program that the iNES 1.0 guess of
  8 KB ran. The five files in the collection are the check; if one
  breaks, that will be written down, not hidden.
- Mistakes shared by the recompiler and the runtime: step 1 compares
  the two readings for exactly this reason.
