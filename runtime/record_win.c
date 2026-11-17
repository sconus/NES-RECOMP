/* nesrecomp runtime: recording gameplay on Windows (record.h,
   PLAN-windows.md step 3), with Microsoft's Media Foundation: the part of
   Windows that the Films & TV app and the Photos app's video editor use.

   One .mp4 file: the picture in H.264, the NES's 256x240 at 4x with
   sharp pixels (1024x960), at the NES's 60.0988 frames a second; the
   sound in AAC, 48 kHz mono. As on the Mac, the movie runs on game time:
   frame N at N * 655171 / 39375000 seconds, sample K at K / 48000.
   Media Foundation counts time in 100 ns steps, so each time is the
   nearest step to that.

   Media Foundation is loaded when a recording starts, not when the game
   does: a Windows without it (the "N" editions, until Microsoft's Media
   Feature Pack is added) still runs games, and says why it can't record.
   On the Mac this file is empty: record_mac.m records. */
typedef int record_win_c;               /* (so the file is never empty) */
#ifdef _WIN32
#define COBJMACROS
#include <windows.h>
#include <initguid.h>                   /* the GUIDs below are defined here */
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <mferror.h>
#include <stdio.h>
#include <string.h>
#include "palette.h"
#include "ppu.h"
#include "record.h"

#define SCALE 4
#define MOVIE_W (NES_WIDTH * SCALE)
#define MOVIE_H (NES_HEIGHT * SCALE)
#define FRAME_NUM 655171            /* a frame lasts 655171 / 39375000 s */
#define FRAME_DEN 39375000
#define RATE 48000

const char *record_ext(void) { return "mp4"; }

/* Media Foundation's functions, found when a recording starts. */
static HMODULE mfplat, mfreadwrite;
static HRESULT (WINAPI *p_MFStartup)(ULONG, DWORD);
static HRESULT (WINAPI *p_MFShutdown)(void);
static HRESULT (WINAPI *p_MFCreateAttributes)(IMFAttributes **, UINT32);
static HRESULT (WINAPI *p_MFCreateMediaType)(IMFMediaType **);
static HRESULT (WINAPI *p_MFCreateSample)(IMFSample **);
static HRESULT (WINAPI *p_MFCreateMemoryBuffer)(DWORD, IMFMediaBuffer **);
static HRESULT (WINAPI *p_MFCreateSinkWriterFromURL)(LPCWSTR, IMFByteStream *, IMFAttributes *,
                                                     IMFSinkWriter **);

static IMFSinkWriter *writer;
static DWORD video_stream, audio_stream;
static long long frames, samples;
static char movie_path[1024];
static int started_mf, com_ours;

/* The picture's colours as the encoder takes them (NV12: Y, then U and V
   at half the size), for each of the palette's 512 colours: BT.709,
   16-235, as on the Mac. */
static uint8_t pal_y[512], pal_u[512], pal_v[512];

int record_active(void) { return writer != NULL; }

static int load_mf(void) {
    if (p_MFCreateSinkWriterFromURL) return 0;
    /* Only from Windows' own folder (never a DLL of that name beside the
       game). */
    mfplat = LoadLibraryExA("mfplat.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
    mfreadwrite = LoadLibraryExA("mfreadwrite.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!mfplat || !mfreadwrite) return -1;
#define FIND(lib, f) if (!(*(FARPROC *)&p_##f = GetProcAddress(lib, #f))) return -1
    FIND(mfplat, MFStartup);
    FIND(mfplat, MFShutdown);
    FIND(mfplat, MFCreateAttributes);
    FIND(mfplat, MFCreateMediaType);
    FIND(mfplat, MFCreateSample);
    FIND(mfplat, MFCreateMemoryBuffer);
    FIND(mfreadwrite, MFCreateSinkWriterFromURL);
#undef FIND
    return 0;
}

static void make_colours(void) {
    for (int i = 0; i < 512; i++) {
        uint32_t c = nes_rgb[i];
        double r = (c >> 16 & 255) / 255.0, g = (c >> 8 & 255) / 255.0, b = (c & 255) / 255.0;
        double y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        pal_y[i] = (uint8_t)(16 + 219 * y + 0.5);
        pal_u[i] = (uint8_t)(128 + 224 * (b - y) / 1.8556 + 0.5);
        pal_v[i] = (uint8_t)(128 + 224 * (r - y) / 1.5748 + 0.5);
    }
}

static int fail(const char *what, HRESULT hr) {
    if (hr) fprintf(stderr, "can't record to %s: %s (error 0x%08lX)\n", movie_path, what,
                    (unsigned long)hr);
    else fprintf(stderr, "can't record to %s: %s\n", movie_path, what);
    return -1;
}

/* A size or a ratio, two numbers in one (Media Foundation's way). */
static HRESULT set_pair(IMFAttributes *a, REFGUID key, UINT32 hi, UINT32 lo) {
    return IMFAttributes_SetUINT64(a, key, (UINT64)hi << 32 | lo);
}

static void drop_writer(void) {
    if (writer) IMFSinkWriter_Release(writer);
    writer = NULL;
    if (started_mf) p_MFShutdown();
    started_mf = 0;
    if (com_ours) CoUninitialize();
    com_ours = 0;
}

/* The picture's type: H.264 in the file (encoded), or NV12 as handed in. */
static HRESULT video_type(IMFMediaType **out, int encoded) {
    IMFMediaType *t;
    HRESULT hr = p_MFCreateMediaType(&t);
    if (FAILED(hr)) return hr;
    IMFAttributes *a = (IMFAttributes *)t;
    IMFAttributes_SetGUID(a, &MF_MT_MAJOR_TYPE, &MFMediaType_Video);
    IMFAttributes_SetGUID(a, &MF_MT_SUBTYPE, encoded ? &MFVideoFormat_H264 : &MFVideoFormat_NV12);
    IMFAttributes_SetUINT32(a, &MF_MT_INTERLACE_MODE, MFVideoInterlace_Progressive);
    set_pair(a, &MF_MT_FRAME_SIZE, MOVIE_W, MOVIE_H);
    set_pair(a, &MF_MT_FRAME_RATE, FRAME_DEN, FRAME_NUM);
    set_pair(a, &MF_MT_PIXEL_ASPECT_RATIO, 1, 1);
    IMFAttributes_SetUINT32(a, &MF_MT_YUV_MATRIX, MFVideoTransferMatrix_BT709);
    IMFAttributes_SetUINT32(a, &MF_MT_VIDEO_PRIMARIES, MFVideoPrimaries_BT709);
    IMFAttributes_SetUINT32(a, &MF_MT_TRANSFER_FUNCTION, MFVideoTransFunc_709);
    IMFAttributes_SetUINT32(a, &MF_MT_VIDEO_NOMINAL_RANGE, MFNominalRange_16_235);
    if (encoded) {
        IMFAttributes_SetUINT32(a, &MF_MT_AVG_BITRATE, 20000000);
        /* H.264's Baseline profile: no frames shown out of order
           ("B-frames"). With them, Media Foundation's MP4 shifts every
           frame's showing by one frame, with nothing in the file to undo
           it, so the picture would play 17 ms behind the sound (found in
           step 3's checks). At 20 Mbit/s it looks the same. */
        IMFAttributes_SetUINT32(a, &MF_MT_MPEG2_PROFILE, 66);
    } else {
        IMFAttributes_SetUINT32(a, &MF_MT_DEFAULT_STRIDE, MOVIE_W);
    }
    *out = t;
    return S_OK;
}

/* The sound's type: AAC in the file, or 16-bit samples as handed in. */
static HRESULT audio_type(IMFMediaType **out, int encoded) {
    IMFMediaType *t;
    HRESULT hr = p_MFCreateMediaType(&t);
    if (FAILED(hr)) return hr;
    IMFAttributes *a = (IMFAttributes *)t;
    IMFAttributes_SetGUID(a, &MF_MT_MAJOR_TYPE, &MFMediaType_Audio);
    IMFAttributes_SetGUID(a, &MF_MT_SUBTYPE, encoded ? &MFAudioFormat_AAC : &MFAudioFormat_PCM);
    IMFAttributes_SetUINT32(a, &MF_MT_AUDIO_BITS_PER_SAMPLE, 16);
    IMFAttributes_SetUINT32(a, &MF_MT_AUDIO_SAMPLES_PER_SECOND, RATE);
    IMFAttributes_SetUINT32(a, &MF_MT_AUDIO_NUM_CHANNELS, 1);
    if (encoded) {
        IMFAttributes_SetUINT32(a, &MF_MT_AUDIO_AVG_BYTES_PER_SECOND, 24000);  /* 192 kbit/s */
    } else {
        IMFAttributes_SetUINT32(a, &MF_MT_AUDIO_BLOCK_ALIGNMENT, 2);
        IMFAttributes_SetUINT32(a, &MF_MT_AUDIO_AVG_BYTES_PER_SECOND, RATE * 2);
    }
    *out = t;
    return S_OK;
}

/* A missing encoder (Windows N, or a Windows Server without its media
   features) shows up as these. */
static int no_codec(HRESULT hr) {
    return hr == MF_E_TOPO_CODEC_NOT_FOUND || hr == MF_E_INVALIDMEDIATYPE ||
           hr == MF_E_UNSUPPORTED_D3D_TYPE || hr == REGDB_E_CLASSNOTREG;
}

static int add_stream(int video, DWORD *index) {
    IMFMediaType *out = NULL, *in = NULL;
    HRESULT hr = video ? video_type(&out, 1) : audio_type(&out, 1);
    if (SUCCEEDED(hr)) hr = IMFSinkWriter_AddStream(writer, out, index);
    if (SUCCEEDED(hr)) hr = video ? video_type(&in, 0) : audio_type(&in, 0);
    if (SUCCEEDED(hr)) hr = IMFSinkWriter_SetInputMediaType(writer, *index, in, NULL);
    if (out) IMFMediaType_Release(out);
    if (in) IMFMediaType_Release(in);
    if (FAILED(hr)) {
        if (no_codec(hr))
            return fail(video ? "this Windows has no H.264 video encoder (on a Windows \"N\" edition, "
                                "Microsoft's Media Feature Pack adds it)"
                              : "this Windows has no AAC sound encoder (on a Windows \"N\" edition, "
                                "Microsoft's Media Feature Pack adds it)", hr);
        return fail(video ? "the picture's format wasn't taken" : "the sound's format wasn't taken", hr);
    }
    return 0;
}

int record_start(const char *path) {
    if (writer) return 0;
    snprintf(movie_path, sizeof movie_path, "%s", path);
    if (load_mf())
        return fail("this Windows has no Media Foundation (on a Windows \"N\" edition, "
                    "Microsoft's Media Feature Pack adds it)", 0);
    HRESULT hr = CoInitializeEx(NULL, COINIT_MULTITHREADED);
    com_ours = SUCCEEDED(hr);           /* (already set up some other way: fine) */
    hr = p_MFStartup(MF_VERSION, MFSTARTUP_FULL);
    if (FAILED(hr)) { drop_writer(); return fail("Media Foundation didn't start", hr); }
    started_mf = 1;
    make_colours();

    wchar_t wpath[1024];
    if (!MultiByteToWideChar(CP_ACP, 0, path, -1, wpath, 1024)) {
        drop_writer();
        return fail("the file name is too long", 0);
    }
    DeleteFileW(wpath);                 /* an existing file is replaced */
    IMFAttributes *attrs = NULL;
    hr = p_MFCreateAttributes(&attrs, 2);
    if (SUCCEEDED(hr))
        /* An MP4, whatever the name ends with. */
        hr = IMFAttributes_SetGUID(attrs, &MF_TRANSCODE_CONTAINERTYPE, &MFTranscodeContainerType_MPEG4);
    if (SUCCEEDED(hr)) hr = p_MFCreateSinkWriterFromURL(wpath, NULL, attrs, &writer);
    if (attrs) IMFAttributes_Release(attrs);
    if (FAILED(hr)) { writer = NULL; drop_writer(); return fail("the file couldn't be made", hr); }
    if (add_stream(1, &video_stream) || add_stream(0, &audio_stream)) {
        drop_writer();
        DeleteFileW(wpath);
        return -1;
    }
    hr = IMFSinkWriter_BeginWriting(writer);
    if (FAILED(hr)) { drop_writer(); DeleteFileW(wpath); return fail("it couldn't start", hr); }
    frames = samples = 0;
    fprintf(stderr, "recording to %s\n", path);
    return 0;
}

static void lost(const char *what, HRESULT hr) {
    static int said;
    if (!said++) fprintf(stderr, "recording: a %s was lost (error 0x%08lX)\n", what, (unsigned long)hr);
}

/* Media Foundation's time (100 ns steps) of frame n, and of sample k. */
static LONGLONG frame_time(long long n) { return (n * 10482736 + 31) / 63; }   /* 655171e7/39375000 = 10482736/63 */
static LONGLONG sample_time(long long k) { return (k * 625 + 1) / 3; }         /* 1e7/48000 = 625/3 */

/* One sample (a frame, or a piece of sound) to the writer. */
static void put_sample(DWORD stream, const void *data, DWORD bytes, int is_frame, LONGLONG at, LONGLONG dur,
                  void (*fill)(uint8_t *, const void *)) {
    IMFMediaBuffer *buf = NULL;
    IMFSample *s = NULL;
    BYTE *p;
    HRESULT hr = p_MFCreateMemoryBuffer(bytes, &buf);
    if (SUCCEEDED(hr)) hr = IMFMediaBuffer_Lock(buf, &p, NULL, NULL);
    if (SUCCEEDED(hr)) {
        if (fill) fill(p, data); else memcpy(p, data, bytes);
        IMFMediaBuffer_Unlock(buf);
        hr = IMFMediaBuffer_SetCurrentLength(buf, bytes);
    }
    if (SUCCEEDED(hr)) hr = p_MFCreateSample(&s);
    if (SUCCEEDED(hr)) hr = IMFSample_AddBuffer(s, buf);
    if (SUCCEEDED(hr)) hr = IMFSample_SetSampleTime(s, at);
    if (SUCCEEDED(hr)) hr = IMFSample_SetSampleDuration(s, dur);
    if (SUCCEEDED(hr)) hr = IMFSinkWriter_WriteSample(writer, stream, s);
    if (FAILED(hr)) lost(is_frame ? "frame" : "piece of sound", hr);
    if (s) IMFSample_Release(s);
    if (buf) IMFMediaBuffer_Release(buf);
}

/* The NES's frame, 4x, as NV12. */
static void fill_frame(uint8_t *p, const void *data) {
    const uint16_t *fb = data;
    uint8_t *uv = p + MOVIE_W * MOVIE_H;
    for (int y = 0; y < NES_HEIGHT; y++) {
        uint8_t *row = p + (size_t)y * SCALE * MOVIE_W;
        uint8_t *crow = uv + (size_t)y * (SCALE / 2) * MOVIE_W;
        for (int x = 0; x < NES_WIDTH; x++) {
            int c = fb[y * NES_WIDTH + x] & 0x1FF;
            memset(row + x * SCALE, pal_y[c], SCALE);
            for (int k = 0; k < SCALE / 2; k++) {
                crow[x * SCALE + 2 * k] = pal_u[c];
                crow[x * SCALE + 2 * k + 1] = pal_v[c];
            }
        }
        for (int k = 1; k < SCALE; k++) memcpy(row + (size_t)k * MOVIE_W, row, MOVIE_W);
        memcpy(crow + MOVIE_W, crow, MOVIE_W);
    }
}

void record_frame(const uint16_t *fb) {
    if (!writer) return;
    long long n = frames++;
    put_sample(video_stream, fb, MOVIE_W * MOVIE_H * 3 / 2, 1, frame_time(n),
          frame_time(n + 1) - frame_time(n), fill_frame);
}

void record_audio(const int16_t *s, int n) {
    if (!writer || n <= 0) return;
    long long at = samples;
    samples += n;
    put_sample(audio_stream, s, (DWORD)n * 2, 0, sample_time(at), sample_time(at + n) - sample_time(at), NULL);
}

void record_stop(void) {
    if (!writer) return;
    HRESULT hr = IMFSinkWriter_Finalize(writer);
    if (SUCCEEDED(hr))
        fprintf(stderr, "recorded %lld frame(s) (%.1f s) to %s\n", frames,
                (double)frames * FRAME_NUM / FRAME_DEN, movie_path);
    else
        fprintf(stderr, "the recording to %s failed (error 0x%08lX)\n", movie_path, (unsigned long)hr);
    drop_writer();
}
#endif
