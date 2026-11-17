/* Read a movie back for tests/check_record_win.py (PLAN-windows.md step
   3), with Windows' Media Foundation: the same library the Films & TV app
   uses to open it. The Windows twin of tests/read_movie.m.

       read_movie_win MOVIE OUT

   prints
       video W H FRAMES RATE FIRST LAST STEP_MIN STEP_MAX TIMESCALE
           the size, the number of frames, the rate the file gives, the
           first and last frame's time and the shortest and longest step
           between two frames (in Media Foundation's 100 ns steps,
           TIMESCALE = 10000000 a second)
       videoformat CODEC MATRIX
           CODEC "h264"; MATRIX the colours' matrix the file names ("709",
           "601" or "none")
       audio RATE CHANNELS BITS FORMAT SAMPLES FIRST GAPS
           FORMAT "aac" (or "pcm", "other"); SAMPLES as decoded; FIRST the
           first piece's time in samples; GAPS how many pieces didn't
           start where the one before ended
       duration SECONDS
   and writes OUT.frames (each frame as 256x240 RGB: the pixel at the
   centre of each 4x4 block, its colours worked out with the matrix the
   file names) and OUT.pcm (the sound, 16-bit, each piece placed at its
   time: sample i of the file is at (FIRST + i) / RATE seconds). Exit
   status 1 if it can't be opened.
   Built by the check: zig cc ... -lmfplat -lmfreadwrite -lole32 */
#define COBJMACROS
#include <windows.h>
#include <initguid.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint8_t clamp(double v) { return v < 0 ? 0 : v > 255 ? 255 : (uint8_t)(v + 0.5); }

static IMFSourceReader *open_reader(const wchar_t *path, DWORD only) {
    IMFSourceReader *r = NULL;
    if (FAILED(MFCreateSourceReaderFromURL(path, NULL, &r))) return NULL;
    IMFSourceReader_SetStreamSelection(r, MF_SOURCE_READER_ALL_STREAMS, FALSE);
    IMFSourceReader_SetStreamSelection(r, only, TRUE);
    return r;
}

static UINT32 get32(IMFMediaType *t, REFGUID key, UINT32 dflt) {
    UINT32 v;
    return SUCCEEDED(IMFAttributes_GetUINT32((IMFAttributes *)t, key, &v)) ? v : dflt;
}

static void get_pair(IMFMediaType *t, REFGUID key, UINT32 *hi, UINT32 *lo) {
    UINT64 v = 0;
    IMFAttributes_GetUINT64((IMFAttributes *)t, key, &v);
    *hi = (UINT32)(v >> 32);
    *lo = (UINT32)v;
}

int main(int argc, char **argv) {
    if (argc != 3) { fprintf(stderr, "usage: read_movie_win MOVIE OUT\n"); return 2; }
    CoInitializeEx(NULL, COINIT_MULTITHREADED);
    if (FAILED(MFStartup(MF_VERSION, MFSTARTUP_FULL))) { printf("error no Media Foundation\n"); return 1; }
    wchar_t path[1024];
    MultiByteToWideChar(CP_ACP, 0, argv[1], -1, path, 1024);
    char out[2048];
    snprintf(out, sizeof out, "%s.frames", argv[2]);
    FILE *ff = fopen(out, "wb");
    snprintf(out, sizeof out, "%s.pcm", argv[2]);
    FILE *pf = fopen(out, "wb");
    if (!ff || !pf) { perror(out); return 2; }
    int failed = 0;

    /* The picture. */
    IMFSourceReader *r = open_reader(path, MF_SOURCE_READER_FIRST_VIDEO_STREAM);
    if (!r) { printf("error can't open\n"); return 1; }
    IMFMediaType *native = NULL, *t = NULL;
    if (SUCCEEDED(IMFSourceReader_GetNativeMediaType(r, MF_SOURCE_READER_FIRST_VIDEO_STREAM, 0, &native))) {
        GUID sub;
        IMFAttributes_GetGUID((IMFAttributes *)native, &MF_MT_SUBTYPE, &sub);
        UINT32 rn, rd;
        get_pair(native, &MF_MT_FRAME_RATE, &rn, &rd);
        UINT32 m = get32(native, &MF_MT_YUV_MATRIX, 0);
        MFCreateMediaType(&t);
        IMFAttributes_SetGUID((IMFAttributes *)t, &MF_MT_MAJOR_TYPE, &MFMediaType_Video);
        IMFAttributes_SetGUID((IMFAttributes *)t, &MF_MT_SUBTYPE, &MFVideoFormat_NV12);
        HRESULT hr = IMFSourceReader_SetCurrentMediaType(r, MF_SOURCE_READER_FIRST_VIDEO_STREAM, NULL, t);
        IMFMediaType_Release(t);
        if (FAILED(hr)) { printf("error no decoder for the picture (0x%08lX)\n", (unsigned long)hr); return 1; }
        IMFSourceReader_GetCurrentMediaType(r, MF_SOURCE_READER_FIRST_VIDEO_STREAM, &t);
        if (!m) m = get32(t, &MF_MT_YUV_MATRIX, 0);
        int bt709 = m == MFVideoTransferMatrix_BT709;
        UINT32 w, h;
        get_pair(t, &MF_MT_FRAME_SIZE, &w, &h);
        long frames = 0;
        LONGLONG first = 0, last = 0, step_min = 0, step_max = 0;
        static uint8_t rgb[256 * 240 * 3];
        for (;;) {
            DWORD idx, flags = 0;
            LONGLONG ts = 0;
            IMFSample *s = NULL;
            HRESULT hr = IMFSourceReader_ReadSample(r, MF_SOURCE_READER_FIRST_VIDEO_STREAM, 0, &idx, &flags, &ts, &s);
            if (FAILED(hr)) { printf("error reading the picture (0x%08lX)\n", (unsigned long)hr); failed = 1; break; }
            if (flags & MF_SOURCE_READERF_CURRENTMEDIATYPECHANGED) {
                IMFMediaType_Release(t);
                IMFSourceReader_GetCurrentMediaType(r, MF_SOURCE_READER_FIRST_VIDEO_STREAM, &t);
                get_pair(t, &MF_MT_FRAME_SIZE, &w, &h);
            }
            if (s) {
                if (frames == 0) first = ts;
                else {
                    LONGLONG step = ts - last;
                    if (frames == 1 || step < step_min) step_min = step;
                    if (frames == 1 || step > step_max) step_max = step;
                }
                last = ts;
                IMFMediaBuffer *b = NULL;
                BYTE *p;
                DWORD len;
                IMFSample_ConvertToContiguousBuffer(s, &b);
                IMFMediaBuffer_Lock(b, &p, NULL, &len);
                DWORD stride = h ? len * 2 / (3 * h) : w;     /* (rows may be padded) */
                const BYTE *uv = p + (size_t)stride * h;
                for (int y = 0; y < 240; y++)
                    for (int x = 0; x < 256; x++) {
                        int sx = x * w / 256 + w / 512, sy = y * h / 240 + h / 480;
                        double Y = (p[(size_t)sy * stride + sx] - 16) * 255.0 / 219;
                        const BYTE *c = uv + (size_t)(sy / 2) * stride + (sx & ~1);
                        double U = (c[0] - 128) * 255.0 / 224, V = (c[1] - 128) * 255.0 / 224;
                        double kr = bt709 ? 0.2126 : 0.299, kb = bt709 ? 0.0722 : 0.114, kg = 1 - kr - kb;
                        double R = Y + 2 * (1 - kr) * V, B = Y + 2 * (1 - kb) * U;
                        double G = (Y - kr * R - kb * B) / kg;
                        uint8_t *o = rgb + (y * 256 + x) * 3;
                        o[0] = clamp(R); o[1] = clamp(G); o[2] = clamp(B);
                    }
                IMFMediaBuffer_Unlock(b);
                IMFMediaBuffer_Release(b);
                fwrite(rgb, 1, sizeof rgb, ff);
                frames++;
                IMFSample_Release(s);
            }
            if (flags & MF_SOURCE_READERF_ENDOFSTREAM) break;
        }
        printf("video %u %u %ld %.6f %lld %lld %lld %lld 10000000\n", w, h, frames,
               rd ? (double)rn / rd : 0, (long long)first, (long long)last,
               (long long)step_min, (long long)step_max);
        printf("videoformat %s %s\n", IsEqualGUID(&sub, &MFVideoFormat_H264) ? "h264" : "other",
               m == MFVideoTransferMatrix_BT709 ? "709" : m == MFVideoTransferMatrix_BT601 ? "601" : "none");
        IMFMediaType_Release(t);
        IMFMediaType_Release(native);
    } else printf("video none\n");
    PROPVARIANT d;
    PropVariantInit(&d);
    double duration = 0;
    if (SUCCEEDED(IMFSourceReader_GetPresentationAttribute(r, MF_SOURCE_READER_MEDIASOURCE, &MF_PD_DURATION, &d)))
        duration = d.uhVal.QuadPart / 1e7;
    IMFSourceReader_Release(r);

    /* The sound. */
    r = open_reader(path, MF_SOURCE_READER_FIRST_AUDIO_STREAM);
    native = NULL;
    if (r && SUCCEEDED(IMFSourceReader_GetNativeMediaType(r, MF_SOURCE_READER_FIRST_AUDIO_STREAM, 0, &native))) {
        GUID sub;
        IMFAttributes_GetGUID((IMFAttributes *)native, &MF_MT_SUBTYPE, &sub);
        MFCreateMediaType(&t);
        IMFAttributes_SetGUID((IMFAttributes *)t, &MF_MT_MAJOR_TYPE, &MFMediaType_Audio);
        IMFAttributes_SetGUID((IMFAttributes *)t, &MF_MT_SUBTYPE, &MFAudioFormat_PCM);
        IMFAttributes_SetUINT32((IMFAttributes *)t, &MF_MT_AUDIO_BITS_PER_SAMPLE, 16);
        HRESULT hr = IMFSourceReader_SetCurrentMediaType(r, MF_SOURCE_READER_FIRST_AUDIO_STREAM, NULL, t);
        IMFMediaType_Release(t);
        if (FAILED(hr)) { printf("error no decoder for the sound (0x%08lX)\n", (unsigned long)hr); return 1; }
        IMFSourceReader_GetCurrentMediaType(r, MF_SOURCE_READER_FIRST_AUDIO_STREAM, &t);
        UINT32 rate = get32(t, &MF_MT_AUDIO_SAMPLES_PER_SECOND, 0), ch = get32(t, &MF_MT_AUDIO_NUM_CHANNELS, 0);
        UINT32 bits = get32(t, &MF_MT_AUDIO_BITS_PER_SAMPLE, 0);
        long long count = 0, first = -1, gaps = 0;
        for (;;) {
            DWORD idx, flags = 0;
            LONGLONG ts = 0;
            IMFSample *s = NULL;
            hr = IMFSourceReader_ReadSample(r, MF_SOURCE_READER_FIRST_AUDIO_STREAM, 0, &idx, &flags, &ts, &s);
            if (FAILED(hr)) { printf("error reading the sound (0x%08lX)\n", (unsigned long)hr); failed = 1; break; }
            if (s) {
                long long at = (ts * rate + 5000000) / 10000000;     /* in samples */
                if (first < 0) first = at;
                long long want = first + count;          /* where the last piece ended */
                if (llabs(at - want) > 1) gaps++;
                /* Placed at its time: silence for a gap; an overlap
                   (earlier than where the last ended) drops its start. */
                static const int16_t zero[4096];
                for (long long k = want; k < at; ) {
                    long long n = at - k > 4096 ? 4096 : at - k;
                    fwrite(zero, 2 * ch, (size_t)n, pf);
                    k += n;
                    count += n;
                }
                IMFMediaBuffer *b = NULL;
                BYTE *p;
                DWORD len;
                IMFSample_ConvertToContiguousBuffer(s, &b);
                IMFMediaBuffer_Lock(b, &p, NULL, &len);
                long long n = len / (2 * ch), skip = at < want ? want - at : 0;
                if (skip > n) skip = n;
                fwrite(p + skip * 2 * ch, 2 * ch, (size_t)(n - skip), pf);
                count += n - skip;
                IMFMediaBuffer_Unlock(b);
                IMFMediaBuffer_Release(b);
                IMFSample_Release(s);
            }
            if (flags & MF_SOURCE_READERF_ENDOFSTREAM) break;
        }
        printf("audio %u %u %u %s %lld %lld %lld\n", rate, ch, bits,
               IsEqualGUID(&sub, &MFAudioFormat_AAC) ? "aac" : IsEqualGUID(&sub, &MFAudioFormat_PCM) ? "pcm" : "other",
               count, first < 0 ? 0 : first, gaps);
        IMFMediaType_Release(t);
        IMFMediaType_Release(native);
    } else printf("audio none\n");
    if (r) IMFSourceReader_Release(r);
    printf("duration %.6f\n", duration);
    fclose(ff);
    fclose(pf);
    MFShutdown();
    return failed;
}
