/* nesrecomp runtime: write a frame as a PNG, using zlib (part of macOS)
   for the compressed image data. */
#include <stdio.h>
#include <string.h>
#include <zlib.h>
#include "palette.h"
#include "ppu.h"
#include "video.h"

static void put32(uint8_t *p, uint32_t v) {
    p[0] = v >> 24; p[1] = v >> 16; p[2] = v >> 8; p[3] = (uint8_t)v;
}

/* A PNG chunk: length, 4-letter type, data, CRC of type + data. */
static void chunk(FILE *f, const char *type, const uint8_t *data, uint32_t len) {
    uint8_t b[4];
    put32(b, len);
    fwrite(b, 1, 4, f);
    fwrite(type, 1, 4, f);
    if (len) fwrite(data, 1, len, f);
    uLong crc = crc32(0, (const Bytef *)type, 4);
    if (len) crc = crc32(crc, data, len);
    put32(b, (uint32_t)crc);
    fwrite(b, 1, 4, f);
}

int video_save_png(const uint8_t *fb, const char *path) {
    /* Raw image: each row starts with filter byte 0, then RGB pixels. */
    enum { ROW = 1 + NES_WIDTH * 3 };
    static uint8_t raw[ROW * NES_HEIGHT];
    for (int y = 0; y < NES_HEIGHT; y++) {
        uint8_t *r = &raw[y * ROW];
        r[0] = 0;
        for (int x = 0; x < NES_WIDTH; x++) {
            uint32_t c = nes_rgb[fb[y * NES_WIDTH + x] & 0x3F];
            r[1 + x * 3] = c >> 16;
            r[2 + x * 3] = c >> 8;
            r[3 + x * 3] = (uint8_t)c;
        }
    }
    static uint8_t packed[ROW * NES_HEIGHT + 1024];
    uLongf packed_len = sizeof packed;
    if (compress(packed, &packed_len, raw, sizeof raw) != Z_OK) return -1;

    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); return -1; }
    fwrite("\x89PNG\r\n\x1a\n", 1, 8, f);
    uint8_t ihdr[13];
    put32(ihdr, NES_WIDTH);
    put32(ihdr + 4, NES_HEIGHT);
    ihdr[8] = 8;        /* bits per channel */
    ihdr[9] = 2;        /* colour type: RGB */
    ihdr[10] = ihdr[11] = ihdr[12] = 0;
    chunk(f, "IHDR", ihdr, 13);
    chunk(f, "IDAT", packed, (uint32_t)packed_len);
    chunk(f, "IEND", NULL, 0);
    return fclose(f) == 0 ? 0 : -1;
}
