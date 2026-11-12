/* nesrecomp runtime: the PPU.

   The PPU doesn't run alongside the CPU. It sleeps until the CPU touches
   one of its registers (or vblank comes due), then catches up dot by dot
   to the CPU's cycle count. Each visible scanline is drawn in one go at
   its first dot, from the scroll position the PPU holds at that moment,
   so scroll changes made mid-line show up on the next line. That is the
   classic "scanline renderer" trade-off; most games and tests are happy
   with it. */
#include "ppu.h"
#include "cart.h"
#include "mapper.h"
#include "event.h"
#include "rt.h"

struct ppu ppu = { .sprite0_line = -1, .overflow_line = -1 };
void (*ppu_frame_done)(const uint8_t *framebuffer);

#define DOTS_PER_LINE 341
#define LINES_PER_FRAME 262
#define VBLANK_LINE 241
#define PRERENDER_LINE 261

#define STATUS_VBLANK   0x80
#define STATUS_SPRITE0  0x40
#define STATUS_OVERFLOW 0x20

/* ---------------------------------------------------------------------
   Memory map
   --------------------------------------------------------------------- */

/* Map a nametable address ($2000-$2FFF, or its $3000 mirror) to an
   offset in ppu.nametables, following the cartridge's mirroring. */
static uint16_t nt_offset(uint16_t addr) {
    uint16_t a = addr & 0x0FFF;
    uint16_t table = a >> 10, within = a & 0x3FF;
    switch (cart.mirroring) {
    case MIRROR_VERTICAL:   table &= 1; break;          /* 0 1 0 1 */
    case MIRROR_HORIZONTAL: table >>= 1; break;         /* 0 0 1 1 */
    case MIRROR_FOUR_SCREEN: break;
    case MIRROR_SINGLE_LOW:  table = 0; break;
    case MIRROR_SINGLE_HIGH: table = 1; break;
    }
    return (uint16_t)(table << 10 | within);
}

/* $3F10/$3F14/$3F18/$3F1C are mirrors of $3F00/$3F04/$3F08/$3F0C. */
static uint8_t pal_offset(uint16_t addr) {
    uint8_t i = addr & 0x1F;
    return (i & 0x13) == 0x10 ? i & 0x0F : i;
}

uint8_t ppu_mem_read(uint16_t addr) {
    addr &= 0x3FFF;
    if (addr < 0x2000) return chr_read(addr);
    if (addr < 0x3F00) return ppu.nametables[nt_offset(addr)];
    return ppu.palette[pal_offset(addr)];
}

void ppu_mem_write(uint16_t addr, uint8_t val) {
    addr &= 0x3FFF;
    if (addr < 0x2000) {
        if (cart.chr_is_ram) mapper.chr[addr >> 10][addr & 0x3FF] = val;
    }
    else if (addr < 0x3F00) ppu.nametables[nt_offset(addr)] = val;
    else ppu.palette[pal_offset(addr)] = val & 0x3F;
}

/* ---------------------------------------------------------------------
   Scroll register updates done by the rendering hardware
   --------------------------------------------------------------------- */

static int rendering_enabled(void) { return (ppu.mask & 0x18) != 0; }

/* Move v down one pixel row, wrapping into the next nametable below. */
static void increment_y(void) {
    if ((ppu.v & 0x7000) != 0x7000) { ppu.v += 0x1000; return; }
    ppu.v &= ~0x7000;
    int y = (ppu.v & 0x03E0) >> 5;
    if (y == 29) { y = 0; ppu.v ^= 0x0800; }   /* row 29 is the last row */
    else if (y == 31) y = 0;                    /* attribute rows: no flip */
    else y++;
    ppu.v = (uint16_t)((ppu.v & ~0x03E0) | y << 5);
}

static void copy_horizontal(void) {
    ppu.v = (ppu.v & ~0x041F) | (ppu.t & 0x041F);
}

static void copy_vertical(void) {
    ppu.v = (ppu.v & ~0x7BE0) | (ppu.t & 0x7BE0);
}

/* ---------------------------------------------------------------------
   Drawing one scanline
   --------------------------------------------------------------------- */

static void draw_background(uint8_t bg[NES_WIDTH]) {
    uint16_t v = ppu.v;                  /* a copy: real v moves at dot 257 */
    uint16_t table = (ppu.ctrl & 0x10) ? 0x1000 : 0;
    int fine_y = (v >> 12) & 7;
    for (int tile = 0; tile < 33; tile++) {
        uint8_t name = ppu_mem_read(0x2000 | (v & 0x0FFF));
        uint8_t attr = ppu_mem_read(0x23C0 | (v & 0x0C00) |
                                    ((v >> 4) & 0x38) | ((v >> 2) & 0x07));
        int shift = ((v >> 4) & 4) | (v & 2);
        uint8_t pal = (attr >> shift) & 3;
        uint16_t addr = table + name * 16 + fine_y;
        uint8_t lo = ppu_mem_read(addr), hi = ppu_mem_read(addr + 8);
        for (int b = 0; b < 8; b++) {
            int px = tile * 8 + b - ppu.x;
            if (px < 0 || px >= NES_WIDTH) continue;
            int p = ((lo >> (7 - b)) & 1) | ((hi >> (7 - b)) & 1) << 1;
            bg[px] = p ? (uint8_t)(pal << 2 | p) : 0;
        }
        if ((v & 0x001F) == 31) { v &= ~0x001F; v ^= 0x0400; }
        else v++;
    }
    if (!(ppu.mask & 0x02))              /* hide the leftmost 8 pixels */
        for (int px = 0; px < 8; px++) bg[px] = 0;
}

/* sp[px] = 0x10 | palette << 2 | pixel, or 0 for no sprite pixel.
   Sprites drawn on this line were found by the search on the line above,
   hence the "- 1". */
static void draw_sprites(int line, uint8_t sp[NES_WIDTH],
                         uint8_t front[NES_WIDTH], uint8_t zero[NES_WIDTH]) {
    int height = (ppu.ctrl & 0x20) ? 16 : 8;
    int found = 0;
    for (int i = 0; i < 64; i++) {
        const uint8_t *s = &ppu.oam[i * 4];
        int row = line - 1 - s[0];       /* OAM Y is the line above the top */
        if (row < 0 || row >= height) continue;
        if (++found > 8) break;          /* only 8 per line are drawn */

        uint8_t tile = s[1], attr = s[2];
        if (attr & 0x80) row = height - 1 - row;      /* vertical flip */
        uint16_t addr;
        if (height == 16) {
            addr = (uint16_t)((tile & 1) * 0x1000 + (tile & 0xFE) * 16);
            if (row >= 8) { addr += 16; row -= 8; }
        } else {
            addr = (uint16_t)(((ppu.ctrl & 0x08) ? 0x1000 : 0) + tile * 16);
        }
        uint8_t lo = ppu_mem_read(addr + row), hi = ppu_mem_read(addr + row + 8);
        for (int b = 0; b < 8; b++) {
            int px = s[3] + b;
            if (px >= NES_WIDTH) break;
            int bit = (attr & 0x40) ? b : 7 - b;      /* horizontal flip */
            int p = ((lo >> bit) & 1) | ((hi >> bit) & 1) << 1;
            if (!p || sp[px]) continue;  /* lower OAM index wins */
            sp[px] = (uint8_t)(0x10 | (attr & 3) << 2 | p);
            front[px] = !(attr & 0x20);
            zero[px] = i == 0;
        }
    }
    if (!(ppu.mask & 0x04))
        for (int px = 0; px < 8; px++) sp[px] = zero[px] = 0;
}

/* During dots 65-256 of each visible line the PPU searches OAM for
   sprites on the NEXT line: 2 dots per sprite, 8 for one that is in range
   (its 4 bytes get copied). Once 8 are found it keeps looking for a 9th
   to set the overflow flag, but with a hardware bug: each time a sprite
   is out of range it moves to the next sprite AND the next byte, so it
   compares a diagonal of tile/attribute/X bytes as if they were Y. Games
   don't rely on the bug, but the overflow tests check it. */
#define OVERFLOW_DELAY 1   /* 0-2 pass sprite_overflow_tests/3.Timing */

static void evaluate_overflow(int line) {
    int height = (ppu.ctrl & 0x20) ? 16 : 8, found = 0, dot = 65, m = 0;
    for (int n = 0; n < 64; n++) {
        int y = ppu.oam[n * 4 + (found < 8 ? 0 : m)];
        int in_range = line - y >= 0 && line - y < height;
        if (found < 8) {
            if (in_range) found++;
            dot += in_range ? 8 : 2;
        } else if (in_range) {
            ppu.overflow_line = line;
            ppu.overflow_dot = dot + OVERFLOW_DELAY;
            return;
        } else {
            m = (m + 1) & 3;            /* the bug */
            dot += 2;
        }
    }
}

static void draw_line(int line) {
    uint8_t *out = &ppu.framebuffer[line * NES_WIDTH];
    uint8_t grey = (ppu.mask & 0x01) ? 0x30 : 0x3F;

    if (!rendering_enabled()) return;   /* drawn dot by dot in step_dot */

    uint8_t bg[NES_WIDTH] = {0}, sp[NES_WIDTH] = {0};
    uint8_t front[NES_WIDTH] = {0}, zero[NES_WIDTH] = {0};
    if (ppu.mask & 0x08) draw_background(bg);
    if (ppu.mask & 0x10) draw_sprites(line, sp, front, zero);

    for (int px = 0; px < NES_WIDTH; px++) {
        int bg_opaque = bg[px] & 3;
        /* Sprite 0 hit: an opaque sprite 0 pixel over an opaque background
           pixel, never at x = 255. Flagged when the PPU reaches that dot. */
        if (zero[px] && bg_opaque && px != 255 && ppu.sprite0_line < 0 &&
            !(ppu.status & STATUS_SPRITE0)) {
            ppu.sprite0_line = line;
            ppu.sprite0_dot = px + 1;
        }
        uint8_t entry;
        if (sp[px] && (front[px] || !bg_opaque)) entry = sp[px];
        else if (bg_opaque) entry = bg[px];
        else entry = 0;
        out[px] = ppu.palette[pal_offset(0x3F00 | entry)] & grey;
    }
}

/* ---------------------------------------------------------------------
   Timing
   --------------------------------------------------------------------- */

/* ---------------------------------------------------------------------
   The A12 address line, for mappers that count scanlines with it (MMC3)
   --------------------------------------------------------------------- */

/* While rendering, every 8 dots the PPU reads a nametable byte, an
   attribute byte (both below $1000, so A12 low) and two pattern bytes
   (A12 = which pattern table). Dots 1-256 and 321-336 fetch background
   tiles, 257-320 sprite tiles. The short lows between pattern fetches
   are too brief for the mapper to notice, so only the switches between
   the background and sprite phases matter: at dots 257 and 321 A12 drops
   for a nametable read, at 261 and 325 the first pattern read of each
   phase puts that phase's table on A12. Nothing is fetched during
   vblank, so A12 is low until the pre-render line's first background
   pattern fetch at dot 5, which is a rise when backgrounds use $1000
   (mmc3_test_2/4-scanline_timing expects exactly this: 256 dots before
   the dot-261 sprite clock). */
#define A12_SPRITES_DOT 261
#define A12_BACKGROUND_DOT 325
#define A12_FIRST_FETCH_DOT 5

static int sprite_table_high(void) {
    /* 8x16 sprites pick a table per sprite; unused slots fetch tile $FF,
       which is in the $1000 table, so treat 8x16 as high. */
    return (ppu.ctrl & 0x20) || (ppu.ctrl & 0x08);
}

static void a12_while_rendering(int line, int dot) {
    if (line == PRERENDER_LINE && dot == A12_FIRST_FETCH_DOT)
        mapper.a12((ppu.ctrl & 0x10) != 0, ppu.dots);
    else if (dot == 257 || dot == 321) mapper.a12(0, ppu.dots);
    else if (dot == A12_SPRITES_DOT) mapper.a12(sprite_table_high(), ppu.dots);
    else if (dot == A12_BACKGROUND_DOT) mapper.a12((ppu.ctrl & 0x10) != 0, ppu.dots);
}

/* With rendering off, the PPU's address bus shows v whenever the CPU
   sets it or reads/writes through $2007. */
static void a12_from_v(void) {
    if (mapper.a12 && !rendering_enabled())
        mapper.a12((ppu.v & 0x1000) != 0, ppu.dots);
}

static void step_dot(void) {
    int line = ppu.scanline, dot = ppu.dot;
    int rendering = rendering_enabled();

    if (mapper.a12 && rendering) {
        if (line < NES_HEIGHT || line == PRERENDER_LINE)
            a12_while_rendering(line, dot);
        else if (line == NES_HEIGHT && dot == 1)
            mapper.a12(0, ppu.dots);        /* no fetches during vblank */
    }

    if (line < NES_HEIGHT) {
        if (dot == 1) draw_line(line);
        if (!rendering && dot >= 1 && dot <= NES_WIDTH) {
            /* Rendering off: the PPU outputs the backdrop colour, or the
               palette entry v points at when v is inside the palette.
               Done per dot, so mid-line palette writes show up (some
               demos draw this way). */
            uint16_t a = (ppu.v & 0x3FFF) >= 0x3F00 ? ppu.v : 0x3F00;
            uint8_t grey = (ppu.mask & 0x01) ? 0x30 : 0x3F;
            ppu.framebuffer[line * NES_WIDTH + dot - 1] =
                ppu.palette[pal_offset(a)] & grey;
        }
        if (line == ppu.sprite0_line && dot == ppu.sprite0_dot) {
            ppu.status |= STATUS_SPRITE0;
            ppu.sprite0_line = -1;
        }
        if (rendering) {
            if (dot == 65) evaluate_overflow(line);  /* the search starts here */
            if (line == ppu.overflow_line && dot == ppu.overflow_dot) {
                ppu.status |= STATUS_OVERFLOW;
                ppu.overflow_line = -1;
            }
            if (dot == 256) increment_y();
            else if (dot == 257) copy_horizontal();
        }
    } else if (line == VBLANK_LINE && dot == 1) {
        if (!ppu.suppress_vbl) {
            ppu.status |= STATUS_VBLANK;
            ppu.vblank_dot = ppu.dots;
            if (ppu.ctrl & 0x80) cpu_request_nmi(ppu.dots);
        }
        ppu.suppress_vbl = 0;
        ppu.frame++;
        if (ppu_frame_done) ppu_frame_done(ppu.framebuffer);
    } else if (line == PRERENDER_LINE) {
        if (dot == 1) {
            ppu.status &= ~(STATUS_VBLANK | STATUS_SPRITE0 | STATUS_OVERFLOW);
            ppu.sprite0_line = -1;
        }
        if (rendering) {
            if (dot == 256) increment_y();
            else if (dot == 257) copy_horizontal();
            else if (dot >= 280 && dot <= 304) copy_vertical();
            /* Odd frames with rendering on skip the last dot. */
            if (dot == 339 && ppu.odd_frame) dot = 340;
        }
    }

    if (++dot >= DOTS_PER_LINE) {
        dot = 0;
        if (++line >= LINES_PER_FRAME) { line = 0; ppu.odd_frame ^= 1; }
    }
    ppu.scanline = line;
    ppu.dot = dot;
    ppu.dots++;
}

void ppu_soft_reset(void) {
    ppu_catch_up();
    ppu.ctrl = 0;
    ppu.mask = 0;
    ppu.w = 0;
    ppu.read_buffer = 0;
}

void ppu_catch_up(void) {
    uint64_t target = cycles * 3;
    while (ppu.dots < target) step_dot();
}

void ppu_schedule(void) {
    long pos = (long)ppu.scanline * DOTS_PER_LINE + ppu.dot;
    long vbl = (long)VBLANK_LINE * DOTS_PER_LINE + 1;
    /* Dots until the vblank dot is next to run. Past it, go round to next
       frame's, assuming the odd-frame skip: at worst one dot early, and an
       early event just catches up and schedules again. */
    long d = pos <= vbl ? vbl - pos
                        : (long)LINES_PER_FRAME * DOTS_PER_LINE - pos - 1 + vbl;
    uint64_t dots_needed = ppu.dots + (uint64_t)d + 1;
    schedule_event((dots_needed + 2) / 3);

    /* A mapper with its scanline IRQ on wants the CPU woken at the next
       dot where A12 might rise, so the IRQ arrives on time. */
    if (mapper.watch_lines && rendering_enabled()) {
        long best = -1;
        for (int i = 0; i < 2 && best < 0; i++) {
            long line = ppu.scanline + i;
            for (int k = 0; k < 2; k++) {
                long dot = k ? A12_BACKGROUND_DOT : A12_SPRITES_DOT;
                long at = line * DOTS_PER_LINE + dot;
                int rendered = (line % LINES_PER_FRAME) < NES_HEIGHT ||
                               (line % LINES_PER_FRAME) == PRERENDER_LINE;
                if (at >= pos && rendered) { best = at; break; }
            }
        }
        long first = (long)PRERENDER_LINE * DOTS_PER_LINE + A12_FIRST_FETCH_DOT;
        if (first >= pos && (best < 0 || first < best)) best = first;
        if (best < 0) {             /* in vblank: next is the pre-render line */
            long next = first;
            best = next >= pos ? next : next + LINES_PER_FRAME * DOTS_PER_LINE;
        }
        dots_needed = ppu.dots + (uint64_t)(best - pos) + 1;
        schedule_event((dots_needed + 2) / 3);
    }
}

/* ---------------------------------------------------------------------
   CPU-visible registers
   --------------------------------------------------------------------- */

static void advance_v(void) {
    ppu.v = (ppu.v + ((ppu.ctrl & 0x04) ? 32 : 1)) & 0x7FFF;
}

uint8_t ppu_reg_read(uint16_t addr) {
    ppu_catch_up();
    switch (addr & 7) {
    case 2:   /* status: top 3 bits are flags, the rest is stale bus */
        /* The race with vblank starting (line 241, dot 1). Here dot is
           the next dot the PPU will run. Reading one dot early sees the
           flag clear and stops it being set this frame; reading on that
           dot or the one after sees it set but cancels the NMI. */
        if (ppu.scanline == VBLANK_LINE) {
            if (ppu.dot == 1) ppu.suppress_vbl = 1;
            else if (ppu.dot == 2 || ppu.dot == 3) cpu_cancel_nmi();
        }
        ppu.io_bus = (ppu.status & 0xE0) | (ppu.io_bus & 0x1F);
        ppu.status &= ~STATUS_VBLANK;     /* reading clears the vblank flag */
        ppu.w = 0;
        break;
    case 4:
        ppu.io_bus = ppu.oam[ppu.oam_addr];
        break;
    case 7:
        if ((ppu.v & 0x3FFF) >= 0x3F00) {
            /* Palette reads come straight back; the buffer is filled
               from the nametable "underneath" the palette. */
            ppu.io_bus = (ppu_mem_read(ppu.v) & 0x3F) | (ppu.io_bus & 0xC0);
            ppu.read_buffer = ppu_mem_read(ppu.v - 0x1000);
        } else {
            ppu.io_bus = ppu.read_buffer;
            ppu.read_buffer = ppu_mem_read(ppu.v);
        }
        advance_v();
        a12_from_v();
        break;
    default:  /* write-only registers read back the stale bus */
        break;
    }
    return ppu.io_bus;
}

/* A CPU write reaches the PPU a little later in the CPU cycle than a
   read does, which shows up as one PPU dot. Tuned with 07-nmi_on_timing. */
#define WRITE_SKEW 1

/* Turning NMI off within this many dots of it being raised stops it:
   the CPU hasn't latched it yet. Tuned with 08-nmi_off_timing. */
#define NMI_CANCEL_WINDOW 3

void ppu_reg_write(uint16_t addr, uint8_t val) {
    uint64_t target = cycles * 3 + WRITE_SKEW;
    while (ppu.dots < target) step_dot();
    ppu.io_bus = val;
    switch (addr & 7) {
    case 0: {
        uint8_t was = ppu.ctrl;
        ppu.ctrl = val;
        ppu.t = (ppu.t & 0x73FF) | (uint16_t)(val & 3) << 10;
        /* Turning NMI on during vblank fires one straight away. */
        if (!(was & 0x80) && (val & 0x80) && (ppu.status & STATUS_VBLANK))
            cpu_request_nmi(ppu.dots);
        if ((was & 0x80) && !(val & 0x80) &&
            ppu.dots - ppu.vblank_dot <= NMI_CANCEL_WINDOW)
            cpu_cancel_nmi();
        break;
    }
    case 1: ppu.mask = val; break;
    case 2: break;
    case 3: ppu.oam_addr = val; break;
    case 4: ppu.oam[ppu.oam_addr++] = val; break;
    case 5:
        if (!ppu.w) {
            ppu.t = (ppu.t & 0x7FE0) | val >> 3;
            ppu.x = val & 7;
        } else {
            ppu.t = (ppu.t & 0x0C1F) | (uint16_t)(val & 7) << 12
                                     | (uint16_t)(val & 0xF8) << 2;
        }
        ppu.w ^= 1;
        break;
    case 6:
        if (!ppu.w) ppu.t = (ppu.t & 0x00FF) | (uint16_t)(val & 0x3F) << 8;
        else { ppu.t = (ppu.t & 0x7F00) | val; ppu.v = ppu.t; a12_from_v(); }
        ppu.w ^= 1;
        break;
    case 7:
        ppu_mem_write(ppu.v, val);
        advance_v();
        a12_from_v();
        break;
    }
    ppu_schedule();             /* rendering or tables may have changed */
}
