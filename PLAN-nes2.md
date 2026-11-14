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

### 2. RAM sizes (done)
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
- Done:
  - The `$6000` RAM is the header's PRG RAM, then its PRG NVRAM. At
    least 8 KB is always allocated, so the `$6000` protocol readers
    and MMC5's first bank have memory. `mapper.ram6000_size` says how
    much the CPU sees: smaller RAM repeats through the 8 KB.
  - With none, a read gives the address's high byte. That is the
    open bus after an absolute read, the usual case. RAM that a mapper
    switches off still reads 0, as before, so iNES 1.0 files don't
    change.
  - MMC1 with more than 8 KB picks the bank from CHR bank 0: bits 2-3
    for 32 KB (bit 2 is A13, bit 3 is A14, as the wiki gives, so save
    files match), bit 3 alone for 16 KB. MMC5 keeps its own 64 KB, and
    FME-7's RAM is the header's.
  - The `.sav` file holds only the NVRAM part, and nothing is saved
    when the header declares none. For SOROM, the second 8 KB is
    saved: the wiki says the battery is on the second chip, and the
    plain RAM is laid out first.
  - CHR RAM is the declared size (at least 1 KB, repeated by the bank
    arithmetic). With neither CHR ROM nor CHR RAM, 8 KB of zeros that
    can't be written. Action 53 still grows its CHR RAM to 32 KB, but
    only for iNES 1.0 headers.
  - `make_ram_test.py` writes six ROMs:
    - `ram_none`, `ram_2k`, `chr_none`;
    - `mmc1_ram32`, `mmc1_ram16`, `mmc1_chr16`.
    Each writes PASSED or FAILED n into the nametable (a `text` test),
    since a RAM test can't count on RAM to report. All six pass. With
    iNES 1.0 headers (`--ines1 DIR`), all six fail.
  - Saves, checked by hand: SXROM saves 32 KB with banks 0-3 in order,
    SOROM saves 8 KB holding bank 1, and `pulsar` saves 32 KB.
  - The five NES 2.0 files in the collection give the same picture at
    frame 600 as before the change. `oam3` now has 1 KB of CHR RAM
    and the plain NROM files have no `$6000` RAM, with no visible
    difference.
  - Breaks, 10 tried, all caught:
    - no RAM read as 8 KB;
    - open bus as 0;
    - small RAM not repeated;
    - CHR RAM always 8 KB;
    - no CHR made writable;
    - MMC1 banking off;
    - SOROM decoded like SXROM;
    - SXROM's two bits swapped;
    - the whole RAM saved;
    - the save always 8 KB.
    Swapping SXROM's bits only shows in the save file's layout: a
    program can't tell, so the first save check (one byte) missed it.
    It now checks all four banks, but the save checks aren't in the
    suite.
  - Not checked: loading a `.sav` back into the NVRAM part, and Action
    53 with an NES 2.0 header (the collection's are iNES 1.0).
  - 180 of 181; nestest exact; all 319 earlier files give the same C.

### 3. Board variants (submappers) (done)
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
- Done, as planned, plus two things the plan didn't list:
  - MMC3 submapper 4 (NEC's MMC3, whose reload of 0 disables the IRQ)
    selects the runtime's existing MMC3A behaviour; `--mmc3-rev` still
    wins.
  - Namco 163 submapper 1 (deprecated) has no sound, as the wiki says.
  - A submapper the runtime doesn't tell apart (MMC6, MC-ACC, ...)
    runs as submapper 0, with a warning.
  - In the recompiler, MMC1 submapper 5 has no switching PRG, so it
    drops the bank-change checks after mapper writes. NINA-001 is
    refused by both the recompiler and the runtime.
  - The VRC2 chip (mapper 22, or 23/25 submapper 3) is now separate
    from VRC2a's CHR shift, which stays mapper 22 only. The latch
    exists only when the header declares no PRG RAM, so iNES 1.0 files
    (8 KB of RAM) don't change. It answers at `$6000-$6FFF` with bit 0
    and the open bus's other bits.
  - `make_variant_test.py` writes 17 `text` ROMs and two `tones` ROMs:
    - bus conflicts for UxROM, CNROM, AxROM (submappers 1, 2);
    - MMC1 submapper 5;
    - VRC4 21/23/25 submappers 1 and 2;
    - VRC2b/VRC2c;
    - VRC7 submappers 1 and 2;
    - Namco 163 at 12 and 18.75 dB.
    All pass. With submapper 0 (`--ines1 DIR`), each fails, except the
    ones whose variant is the old default (UxROM/CNROM 2, AxROM 1).
  - Found on the way: at 18.75 dB, a full-volume Namco 163 square clips
    in the runtime's 16-bit output (7.874 measured for 8.659). Those
    two notes aren't checked; the others are checked against the APU
    note. A slip in my own test (CHR bank $43 of 64) was caught because
    the ROM failed with every submapper.
  - By hand, on patched copies in the scratchpad:
    - blargg's MMC3 rev A test with submapper 4 passes with no option;
      rev B with submapper 4 fails, and passes with `--mmc3-rev B`;
    - NINA-001 is refused by both;
    - mapper 4 submapper 1 gives the warning;
    - Namco 163 submapper 2 plays only the APU note.
  - Breaks, 18 tried, all caught in the end:
    - bus conflicts: submapper 1 ignored, submapper 2 ignored, AxROM
      never conflicting;
    - MMC1 submapper 5 ignored;
    - VRC wirings: both decoded, 1 and 2 swapped;
    - VRC2 run as VRC4;
    - VRC2: IRQ writes reaching the IRQ, IRQ left on;
    - the latch: off, other bits 0, through `$7FFF`;
    - VRC7 wirings swapped;
    - Namco 163: submapper ignored, 3 and 5 swapped, 2 still
      sounding;
    - MMC3 submapper 4 ignored;
    - the recompiler ignoring submapper 5.

    Two of them needed work first:
    - The latch through `$7FFF` was first missed, because the test read
      `$7000` while the latch held 0. It now reads it while the latch
      holds 1.
    - The IRQ break first changed only the writes, which do nothing
      without the IRQ's timer, so it is now one break of both.

    Two are caught in other ways:
    - The recompiler ignoring submapper 5 only changes the generated C
      (22 lines of bank-change checks), not behaviour, so it was
      checked by comparing the C.
    - The MMC3 and Namco 163 submapper 2 breaks were caught by the
      by-hand checks, which aren't in the suite.
  - 199 of 200; nestest exact; all 319 earlier files give the same C.

### 4. The expected controller (done)
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
- Done:
  - With none of the input options (`--port1`, `--port2`,
    `--famicom-vaus`, `--famicom-zapper`, `--four-score`, `--famicom-4p`,
    `--hori-4p`), `main.c` plugs in what byte 15 names and says so on
    stderr:
    - `$02` Four Score;
    - `$03` Famicom four players;
    - `$08` Zapper in port 2;
    - `$49` Zapper in port 1;
    - `$0F` Arkanoid paddle in port 2;
    - `$10` the Famicom paddle.
  - `$00` and `$01` change nothing. Any other value gets a warning and
    standard controllers: the Power Pad, keyboards, two Zappers, Hori's
    8-player wiring (`$06`), two paddles with the data recorder (`$11`),
    the Vs. System's.
  - Any input option means the header is not used at all.
  - `--info` names the device, or says it isn't supported.
  - `make_device_test.py` writes NES 2.0 copies of six test ROMs from
    the last two stages, each naming its device:
    - Zapper in port 2 and port 1;
    - paddle in port 2 and the Famicom's;
    - Four Score and Famicom four players.
    In the suite they run with their scripts and no option, and all
    pass. With device `$00` (`--device-0 DIR`), and with `--port1 pad`
    added, every one fails, as the originals do without their option.
    By hand: device `$0B` (Power Pad) gives the warning and runs.
  - The Famicom Zapper and Hori's adapter have no byte 15 value of
    their own, so their test ROMs have no copy.
  - Breaks, all 6 caught:
    - the header ignored;
    - options not winning;
    - `$08` and `$49` swapped;
    - `$0F` as the Famicom paddle;
    - `$02` as Famicom four players;
    - `$03` as Hori's adapter.
  - 205 of 206; nestest exact; all 319 earlier files give the same C.

### 5. Suite, README, notes
Accept the new checks, document the header fields and what each does,
update the status list, and write where the stage ended.

## Not in this stage
- PAL and Dendy timing (a different CPU/PPU clock and frame), the Vs.
  System and PlayChoice-10 hardware, and the extended console types.
  These are read and reported only.
- MMC3 variants other than NEC's (MMC6, MC-ACC, T9552), NINA-001, and
  other submappers of boards the runtime doesn't have.
- CHR NVRAM saves (no supported board has it).

## Risks
- Real NES 2.0 dumps sometimes get the RAM nibbles wrong. Taking "no
  PRG RAM" literally could break a program that the iNES 1.0 guess of
  8 KB ran. The five files in the collection are the check; if one
  breaks, that will be written down, not hidden.
- Mistakes shared by the recompiler and the runtime: step 1 compares
  the two readings for exactly this reason.
