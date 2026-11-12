/* nesrecomp runtime: the 64 NES colours, worked out from the video signal.

   The NES has no RGB palette. Each colour number makes the PPU output a
   square wave on the composite video line: 4 bits pick one of 12 phases
   (the hue), 2 bits pick a pair of voltage levels (the brightness). A TV
   decodes that wave into luma (Y) and two colour signals (I, Q). We do the
   same: sample one colour cycle at 12 points, average to get Y, multiply
   by a cosine/sine at the colour carrier to get I and Q, then convert YIQ
   to RGB. The voltage levels are measured values from the nesdev wiki. */
#include <math.h>
#include "palette.h"

uint32_t nes_rgb[64];

void palette_init(void) {
    /* Low and high signal voltages for brightness levels 0-3. */
    static const float low[4]  = { 0.350f, 0.518f, 0.962f, 1.550f };
    static const float high[4] = { 1.094f, 1.506f, 1.962f, 1.962f };
    const float black = 0.518f, white = 1.962f;
    const float pi = 3.14159265f;
    const float saturation = 1.3f;     /* TVs usually run colour a bit hot */

    for (int c = 0; c < 64; c++) {
        int hue = c & 0x0F, level = (c >> 4) & 3;
        float lo = low[level], hi = high[level];
        if (hue == 0x00) lo = hi;                 /* greys: a flat high level */
        if (hue >= 0x0D) hi = lo;                 /* $xD-$xF: a flat low level */
        if (hue >= 0x0E) lo = hi = black;         /* $xE, $xF are black */

        float y = 0, i = 0, q = 0;
        for (int p = 0; p < 12; p++) {
            /* The wave is high for 6 of the 12 phases; the hue shifts it. */
            float s = ((hue + p) % 12 < 6) ? hi : lo;
            s = (s - black) / (white - black);
            /* Phase offset that lines hue 1 up with blue, as on a TV. */
            float angle = pi * (p + 4.0f) / 6.0f;
            y += s;
            i += s * cosf(angle);
            q += s * sinf(angle);
        }
        y /= 12;
        i = i / 12 * saturation;
        q = q / 12 * saturation;

        float rgb[3] = {
            y + 0.956f * i + 0.621f * q,
            y - 0.272f * i - 0.647f * q,
            y - 1.106f * i + 1.703f * q,
        };
        uint32_t out = 0xFF000000u;               /* ARGB, opaque */
        for (int k = 0; k < 3; k++) {
            float v = rgb[k] < 0 ? 0 : rgb[k] > 1 ? 1 : rgb[k];
            v = powf(v, 1.0f / 1.1f);             /* gentle gamma lift */
            out |= (uint32_t)(v * 255.0f + 0.5f) << (16 - 8 * k);
        }
        nes_rgb[c] = out;
    }
}
