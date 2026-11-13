/* nesrecomp runtime: NES colour number -> RGB. */
#ifndef NESRECOMP_PALETTE_H
#define NESRECOMP_PALETTE_H
#include <stdint.h>

/* 0xAARRGGBB for each colour number (bits 0-5) with each combination of
   the $2001 emphasis bits (bits 6-8: red, green, blue); filled by
   palette_init. */
extern uint32_t nes_rgb[512];
void palette_init(void);

#endif
