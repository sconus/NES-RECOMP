/* nesrecomp runtime: what's plugged into the controller ports.

   Standard controllers: writing 1 then 0 to $4016 latches the buttons;
   each read then shifts out one button on bit 0, A first. After all 8,
   an official controller returns 1s.

   Arkanoid "Vaus" paddles (nesdev wiki, "Arkanoid controller"): a knob
   and one button. Writing 1 to $4016 starts a measurement of the knob;
   its result, 9 bits, goes into a shift register that each read clocks
   out most significant bit first, inverted on the wire. Reads after the
   9th repeat the 9th bit (the register's serial input). The real paddle
   takes up to 7 ms to measure and only then loads the register, so its
   reads come from the previous strobe's measurement; here the knob is
   measured at the strobe itself, a frame sooner. The knob is 8 bits
   here (the 9th bit, which games ignore, is 0). The button reads 1 when
   pressed, straight from the switch, whatever the strobe does.
     NES paddle, in a controller port:  bit 4 data, bit 3 button, on that
                                        port's register; bit 0 reads 0
     Famicom paddle, expansion port:    $4017 bit 1 data, $4016 bit 1
                                        button; controllers stay on bit 0 */
#include "input.h"

uint8_t pad_buttons[2];
int port_device[2];             /* DEV_PAD or DEV_VAUS */
int famicom_vaus;
struct vaus vaus[2];

static uint8_t shift[2];
static uint8_t strobe;
/* One shift register per paddle, numbered as in vaus_index. */
static uint16_t vaus_shift[2];

/* Paddles are numbered in order: port 1, port 2, then the Famicom one.
   Returns -1 when that place holds no paddle. place: 0, 1 = the ports,
   2 = the expansion port. */
static int vaus_index(int place) {
    int n = 0;
    for (int p = 0; p < 3; p++) {
        int here = p < 2 ? port_device[p] == DEV_VAUS : famicom_vaus;
        if (!here) continue;
        if (p == place) return n < 2 ? n : -1;
        n++;
    }
    return -1;
}

static void latch(void) {
    shift[0] = pad_buttons[0];
    shift[1] = pad_buttons[1];
}

void input_write_strobe(uint8_t val) {
    uint8_t rising = (uint8_t)(val & 1 & ~strobe);
    strobe = val & 1;
    if (strobe) latch();
    if (rising)
        for (int i = 0; i < 2; i++) vaus_shift[i] = (uint16_t)(vaus[i].knob << 1);
}

/* The next bit of paddle i's register, as it appears on the wire. */
static uint8_t vaus_bit(int i) {
    uint16_t s = vaus_shift[i];
    vaus_shift[i] = (uint16_t)((s << 1 | (s & 1)) & 0x1FF);
    return (uint8_t)(~s >> 8 & 1);
}

uint8_t input_read(int port) {
    if (strobe) latch();      /* while strobe is high, reads keep returning A */
    /* Bits 5-7 aren't driven and keep the last byte on the CPU bus, which
       is the high byte of the address ($40) for a plain LDA $4016. */
    uint8_t v = 0x40;
    int i = vaus_index(port);
    if (i >= 0)
        v |= (uint8_t)(vaus_bit(i) << 4 | vaus[i].fire << 3);
    else if (port_device[port] == DEV_PAD) {
        v |= shift[port] & 1;
        shift[port] = (uint8_t)(shift[port] >> 1 | 0x80);
    }
    int f = vaus_index(2);
    if (f >= 0)
        v |= (uint8_t)((port ? vaus_bit(f) : vaus[f].fire) << 1);
    return v;
}
