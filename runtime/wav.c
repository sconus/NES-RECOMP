/* nesrecomp runtime: write the sound to a WAV file (16-bit mono 48 kHz).
   The header's size fields are filled in when the file is closed. */
#include <stdio.h>
#include <stdlib.h>
#include "wav.h"

static FILE *wav;
static uint32_t data_bytes;

static void put16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = v >> 8; }
static void put32(uint8_t *p, uint32_t v) {
    put16(p, (uint16_t)v);
    put16(p + 2, (uint16_t)(v >> 16));
}

static void write_header(void) {
    uint8_t h[44] = "RIFF....WAVEfmt ";
    put32(h + 4, 36 + data_bytes);
    put32(h + 16, 16);                  /* format chunk size */
    put16(h + 20, 1);                   /* PCM */
    put16(h + 22, 1);                   /* mono */
    put32(h + 24, 48000);
    put32(h + 28, 48000 * 2);           /* bytes per second */
    put16(h + 32, 2);                   /* bytes per sample frame */
    put16(h + 34, 16);                  /* bits per sample */
    h[36] = 'd'; h[37] = 'a'; h[38] = 't'; h[39] = 'a';
    put32(h + 40, data_bytes);
    fseek(wav, 0, SEEK_SET);
    fwrite(h, 1, sizeof h, wav);
    fseek(wav, 0, SEEK_END);
}

void wav_open(const char *path) {
    wav = fopen(path, "wb");
    if (!wav) { perror(path); exit(1); }
    write_header();
}

void wav_write(const int16_t *samples, int n) {
    if (!wav) return;
    for (int i = 0; i < n; i++) {
        uint8_t b[2];
        put16(b, (uint16_t)samples[i]);
        fwrite(b, 1, 2, wav);
    }
    data_bytes += (uint32_t)n * 2;
}

void wav_close(void) {
    if (!wav) return;
    write_header();
    fclose(wav);
    wav = NULL;
}
