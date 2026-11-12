/* nesrecomp runtime: sound to a WAV file, for tests and listening. */
#ifndef NESRECOMP_WAV_H
#define NESRECOMP_WAV_H
#include <stdint.h>

void wav_open(const char *path);
void wav_write(const int16_t *samples, int n);
void wav_close(void);

#endif
