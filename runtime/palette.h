/* nesrecomp runtime: NES colour number -> RGB. */
#ifndef NESRECOMP_PALETTE_H
#define NESRECOMP_PALETTE_H
#include <stdint.h>

/* 0xAARRGGBB for each of the 64 colour numbers; filled by palette_init. */
extern uint32_t nes_rgb[64];
void palette_init(void);

#endif
