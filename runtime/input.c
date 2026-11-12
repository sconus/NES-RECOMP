/* nesrecomp runtime: standard controllers. Writing 1 then 0 to $4016
   latches the buttons; each read then shifts out one button, A first.
   After all 8, an official controller returns 1s. */
#include "input.h"

uint8_t pad_buttons[2];
static uint8_t shift[2];
static uint8_t strobe;

static void latch(void) {
    shift[0] = pad_buttons[0];
    shift[1] = pad_buttons[1];
}

void input_write_strobe(uint8_t val) {
    strobe = val & 1;
    if (strobe) latch();
}

uint8_t input_read(int port) {
    if (strobe) latch();      /* while strobe is high, reads keep returning A */
    uint8_t bit = shift[port] & 1;
    shift[port] = (uint8_t)(shift[port] >> 1 | 0x80);
    /* Bits 5-7 aren't driven and keep the last byte on the CPU bus, which
       is the high byte of the address ($40) for a plain LDA $4016. */
    return 0x40 | bit;
}
