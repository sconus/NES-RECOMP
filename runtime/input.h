/* nesrecomp runtime: standard controllers on $4016/$4017. */
#ifndef NESRECOMP_INPUT_H
#define NESRECOMP_INPUT_H
#include <stdint.h>

/* Button bits, in the order the controller shifts them out. */
enum {
    BTN_A = 0x01, BTN_B = 0x02, BTN_SELECT = 0x04, BTN_START = 0x08,
    BTN_UP = 0x10, BTN_DOWN = 0x20, BTN_LEFT = 0x40, BTN_RIGHT = 0x80,
};

/* Buttons held right now on each controller; the window code sets these. */
extern uint8_t pad_buttons[2];

void input_write_strobe(uint8_t val);       /* CPU write to $4016 */
uint8_t input_read(int port);               /* CPU read of $4016 / $4017 */

#endif
