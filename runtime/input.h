/* nesrecomp runtime: controllers and paddles on $4016/$4017. */
#ifndef NESRECOMP_INPUT_H
#define NESRECOMP_INPUT_H
#include <stdint.h>

/* Button bits, in the order the controller shifts them out. */
enum {
    BTN_A = 0x01, BTN_B = 0x02, BTN_SELECT = 0x04, BTN_START = 0x08,
    BTN_UP = 0x10, BTN_DOWN = 0x20, BTN_LEFT = 0x40, BTN_RIGHT = 0x80,
};

/* What a controller port holds (--port1 / --port2). */
enum { DEV_PAD, DEV_VAUS };
extern int port_device[2];
/* A Famicom Arkanoid paddle in the expansion port (--famicom-vaus). */
extern int famicom_vaus;

/* Buttons held right now on each controller; the window code sets these. */
extern uint8_t pad_buttons[2];
/* The paddles, numbered port 1, port 2, Famicom (the first two plugged
   in): the knob's position 0-255 and the button, 0 or 1. */
struct vaus { uint8_t knob, fire; };
extern struct vaus vaus[2];

void input_write_strobe(uint8_t val);       /* CPU write to $4016 */
uint8_t input_read(int port);               /* CPU read of $4016 / $4017 */

#endif
