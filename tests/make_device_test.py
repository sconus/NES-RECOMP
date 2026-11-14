#!/usr/bin/env python3
"""Write NES 2.0 copies of the device test ROMs made for nesrecomp, with
byte 15 (the default expansion device, nesdev wiki "NES 2.0") naming the
device each one tests, so they run without any input option. Run it
again (after the generators below) to regenerate them.

  dev_zapper_port2.nes  from zapper_port2.nes (make_zapper_test.py)  $08
  dev_zapper_port1.nes  from zapper_port1.nes                        $49
  dev_vaus_port2.nes    from vaus_port2.nes (make_vaus_test.py)      $0F
  dev_vaus_famicom.nes  from vaus_famicom.nes                        $10
  dev_four_score.nes    from four_score.nes (make_four_test.py)      $02
  dev_four_famicom.nes  from four_famicom.nes                        $03

The rest of the header says what the iNES 1.0 one implied (8 KB of PRG
RAM, for the $6000 protocol; 8 KB of CHR RAM without CHR ROM). With
--device-0 DIR the same copies get device $00 and go to DIR, where each
must fail, as the originals do without their option.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

COPIES = {
    "zapper_port2": 0x08, "zapper_port1": 0x49,
    "vaus_port2": 0x0F, "vaus_famicom": 0x10,
    "four_score": 0x02, "four_famicom": 0x03,
}


def nes2(data, device):
    h = bytearray(data[:16])
    assert h[7] & 0x0C == 0 and not any(h[8:16]), "expected an iNES 1.0 header"
    h[7] |= 0x08
    h[10] = 0x07                                # 8 KB of PRG RAM
    h[11] = 0x07 if h[5] == 0 else 0            # 8 KB of CHR RAM
    h[15] = device
    return bytes(h) + data[16:]


def main():
    out, zero = HERE, "--device-0" in sys.argv
    if zero:
        out = sys.argv[sys.argv.index("--device-0") + 1]
    for name, device in COPIES.items():
        data = open(os.path.join(HERE, name + ".nes"), "rb").read()
        path = os.path.join(out, "dev_%s.nes" % name)
        with open(path, "wb") as f:
            f.write(nes2(data, 0 if zero else device))
        print("wrote", path)


if __name__ == "__main__":
    main()
