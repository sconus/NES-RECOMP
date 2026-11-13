/* nesrecomp runtime: the PPU (picture processing unit). */
#ifndef NESRECOMP_PPU_H
#define NESRECOMP_PPU_H
#include <stdint.h>

#define NES_WIDTH 256
#define NES_HEIGHT 240

struct ppu {
    uint8_t ctrl, mask, status;     /* $2000, $2001, $2002 */
    uint8_t oam_addr;               /* $2003 */
    uint8_t oam[256];               /* sprite memory */
    uint8_t nametables[0x1000];     /* 2 KB used, 4 KB for four-screen carts */
    uint8_t palette[32];
    /* The internal scroll/address registers, named as on the nesdev wiki:
       v = current VRAM address, t = temporary address, x = fine X scroll,
       w = the shared first/second write toggle for $2005 and $2006. */
    uint16_t v, t;
    uint8_t x, w;
    uint8_t read_buffer;            /* $2007 reads lag one byte behind */
    uint8_t prev_read_buffer;       /* the buffer before the last refill */
    uint64_t last_2007_read;        /* dot of the last $2007 read */
    uint8_t io_bus;                 /* last value on the PPU's data lines */
    uint64_t bus_refreshed[8];      /* dot each io_bus bit was last refreshed */

    /* Timing. A frame is 262 scanlines of 341 dots; 3 dots per CPU cycle.
       Lines 0-239 are visible, 241 starts vblank, 261 is the pre-render
       line. `dots` counts every dot since power-on. */
    int scanline, dot;
    int odd_frame;
    uint64_t dots;
    uint64_t frame;                 /* frames completed */
    int overflow_line, overflow_dot;    /* where the overflow flag gets set */
    int suppress_vbl;               /* $2002 read just before vblank began */
    uint64_t vblank_dot;            /* when the vblank flag was last set */

    /* Background tiles for the line being drawn, fetched at the dots the
       PPU fetches them: slots 0-1 at the end of the line before, 2-33
       during the line. 8 pixels each: two pattern bytes and a palette. */
    uint8_t bg_lo[34], bg_hi[34], bg_pal[34];
    uint8_t fetch_name;             /* nametable byte of the tile being fetched */
    /* Sprite pixels for the line being drawn: 0x10 | palette << 2 | pixel
       (0 = none), whether in front of the background, whether sprite 0. */
    uint8_t sp[NES_WIDTH], sp_front[NES_WIDTH], sp_zero[NES_WIDTH];
    /* Palette index of each pixel worked out on this line, waiting to
       leave the PPU (0xFF = none; see PIXEL_OUTPUT_DELAY). */
    uint8_t line_entry[NES_WIDTH];
    /* The same for the next line, filled during this one's dots 257-320:
       the OAM indices the search found, then each one's pattern fetched
       at its own dot. */
    uint8_t next_sp[NES_WIDTH], next_front[NES_WIDTH], next_zero[NES_WIDTH];
    uint8_t next_sprites[8];
    int next_count, next_line;

    /* One finished picture, 256 x 240. Per pixel: colour (bits 0-5) and the $2001 emphasis bits in effect
       (bits 6-8: red, green, blue). nes_rgb (palette.h) turns it into RGB. */
    uint16_t framebuffer[NES_WIDTH * NES_HEIGHT];
};

extern struct ppu ppu;

/* Called at the start of every vblank with the finished picture. */
extern void (*ppu_frame_done)(const uint16_t *framebuffer);

/* Run the PPU forward to the CPU's current cycle. Called before every CPU
   access that the PPU could see or affect, and from runtime_event. */
void ppu_catch_up(void);
/* The reset button: $2000 and $2001 cleared, the write toggle reset. */
void ppu_soft_reset(void);
/* Tell the event system when the PPU next needs to run on its own
   (the start of the next vblank, where NMI fires and a frame ends). */
void ppu_schedule(void);

/* CPU side: addr is $2000-$3FFF; only the low 3 bits matter. */
uint8_t ppu_reg_read(uint16_t addr);
void ppu_reg_write(uint16_t addr, uint8_t val);

/* PPU side: the 14-bit PPU address space. */
uint8_t ppu_mem_read(uint16_t addr);
void ppu_mem_write(uint16_t addr, uint8_t val);

#endif
