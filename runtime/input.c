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
                                        button; controllers stay on bit 0

   Four players (nesdev wiki, "Four player adapters"), all latched by the
   one strobe:
     Four Score (NES):     $4016 bit 0 sends controller 1, controller 3,
                           then the signature 0,0,0,1,0,0,0,0; $4017 bit 0
                           controller 2, controller 4, then 0,0,1,0,0,0,0,0;
                           1s after the 24th read
     Famicom 3 and 4:      controller 3 on $4016 bit 1, controller 4 on
                           $4017 bit 1, 8 buttons each then 1s, beside 1
                           and 2 on bit 0
     Hori 4 Players:       the Four Score's sequence on bit 1, with the two
                           signatures swapped; 1 and 2 stay on bit 0

   The Zapper (nesdev wiki, "Zapper"): no shift register; every read of
   its port shows bit 3 = 0 while the sensor sees light and bit 4 = 1
   while the trigger is pulled (the simpler guns' trigger, which the
   wiki says games accept; the official one's half pull isn't copied).
   The Famicom Zapper reads like one in port 2. The sensor sees the TV:
   it lights up as the beam draws a bright pixel under the aim and stays
   lit for about 26 scanlines for white, 24 for light grey and 19 for
   dark grey. The wiki gives no area or brightness threshold, so here:
   the 5 x 5 pixels around the aim, and the colour's brightness (from
   the RGB palette) sorted against the greys: at least $30's and $10's
   midway point 26 lines, $10's and $00's 24, a little under $00's 19,
   darker nothing (the colours of rows $01-$0C and $11-$1C). */
#include "input.h"
#include "state.h"
#include "palette.h"
#include "ppu.h"

uint8_t pad_buttons[4];
int port_device[2];             /* DEV_PAD or DEV_VAUS */
int famicom_vaus;
int four_players;               /* FOUR_NONE, FOUR_SCORE, ... */
struct vaus vaus[2];
int famicom_zapper;
struct zapper zapper = { -1, -1, 0 };

#define ZAPPER_RADIUS 2                 /* pixels each side of the aim */

/* Scanlines a pixel of this colour keeps the sensor lit for. */
static int light_lines(uint16_t colour) {
    uint32_t c = nes_rgb[colour & 0x1FF];
    int luma = (int)(((c >> 16 & 255) * 299 + (c >> 8 & 255) * 587 +
                      (c & 255) * 114) / 1000);
    return luma >= 218 ? 26 : luma >= 146 ? 24 : luma >= 105 ? 19 : 0;
}

static int zapper_sees_light(void) {
    if (zapper.x < 0) return 0;
    ppu_catch_up();
    for (int dy = -ZAPPER_RADIUS; dy <= ZAPPER_RADIUS; dy++)
        for (int dx = -ZAPPER_RADIUS; dx <= ZAPPER_RADIUS; dx++) {
            int x = zapper.x + dx, y = zapper.y + dy;
            if (x < 0 || x >= NES_WIDTH || y < 0 || y >= NES_HEIGHT) continue;
            long since = ppu_dots_since_pixel(x, y);
            if (since < 0) continue;
            if (since < light_lines(ppu.framebuffer[y * NES_WIDTH + x]) * 341L)
                return 1;
        }
    return 0;
}

static uint8_t zapper_bits(void) {
    return (uint8_t)((zapper.trigger ? 0x10 : 0) | (zapper_sees_light() ? 0 : 0x08));
}

/* What each port sends next on bit 0 and on bit 1, lowest bit first.
   Every read shifts in a 1 from the top, so the reads after a sequence
   return 1s. */
static uint32_t shift[2], shift1[2];
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

/* A Four Score style sequence: two controllers, then a signature. */
static uint32_t sequence(uint8_t first, uint8_t second, uint8_t signature) {
    return first | (uint32_t)second << 8 | (uint32_t)signature << 16 | 0xFF000000u;
}

static void latch(void) {
    for (int p = 0; p < 2; p++) {
        shift[p] = 0xFFFFFF00u | pad_buttons[p];
        shift1[p] = 0xFFFFFFFFu;
    }
    if (four_players == FOUR_SCORE) {
        shift[0] = sequence(pad_buttons[0], pad_buttons[2], 0x08);
        shift[1] = sequence(pad_buttons[1], pad_buttons[3], 0x04);
    } else if (four_players == FOUR_FAMICOM) {
        shift1[0] = 0xFFFFFF00u | pad_buttons[2];
        shift1[1] = 0xFFFFFF00u | pad_buttons[3];
    } else if (four_players == FOUR_HORI) {
        shift1[0] = sequence(pad_buttons[0], pad_buttons[2], 0x04);
        shift1[1] = sequence(pad_buttons[1], pad_buttons[3], 0x08);
    }
}

static uint8_t next_bit(uint32_t *reg) {
    uint8_t bit = *reg & 1;
    *reg = *reg >> 1 | 0x80000000u;
    return bit;
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
    else if (port_device[port] == DEV_PAD)
        v |= next_bit(&shift[port]);
    else if (port_device[port] == DEV_ZAPPER)
        v |= zapper_bits();
    if (port == 1 && famicom_zapper) v |= zapper_bits();
    int f = vaus_index(2);
    if (f >= 0)
        v |= (uint8_t)((port ? vaus_bit(f) : vaus[f].fire) << 1);
    else if (four_players == FOUR_FAMICOM || four_players == FOUR_HORI)
        v |= (uint8_t)(next_bit(&shift1[port]) << 1);
    return v;
}

/* What a state holds from here: the buttons and paddle and Zapper
   readings the game sees now (the next frame's input replaces them), and
   the shift registers mid-read. What is plugged in is a setting, not
   state. */
void input_state(struct state_io *s) {
    state_part(s, "pad_buttons", pad_buttons, sizeof pad_buttons);
    state_part(s, "vaus", vaus, sizeof vaus);
    state_part(s, "zapper", &zapper, sizeof zapper);
    state_part(s, "input.shift", shift, sizeof shift);
    state_part(s, "input.shift1", shift1, sizeof shift1);
    state_part(s, "input.strobe", &strobe, sizeof strobe);
    state_part(s, "input.vaus_shift", vaus_shift, sizeof vaus_shift);
}
