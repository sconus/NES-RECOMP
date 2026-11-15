/* nesrecomp runtime: recording gameplay to a .mov with AVFoundation (see
   record.h). Objective-C without ARC: the few objects are released by
   record_stop.

   The writer is fed in game time, never the Mac's clock: each frame is
   stamped N * 655171 / 39375000 seconds (the NES's 39375000/655171
   frames a second), and each block of sound by how many samples came
   before it, at 48000 a second. What the writer isn't ready for waits in
   a queue (see pump), so no frame or sample is ever dropped. */
#import <AVFoundation/AVFoundation.h>
#import <CoreMedia/CoreMedia.h>
#import <CoreVideo/CoreVideo.h>
#include <stdio.h>
#include <unistd.h>
#include "palette.h"
#include "ppu.h"
#include "record.h"

#define SCALE 4
#define MOVIE_W (NES_WIDTH * SCALE)
#define MOVIE_H (NES_HEIGHT * SCALE)
#define FRAME_NUM 655171            /* a frame lasts 655171 / 39375000 s */
#define FRAME_DEN 39375000
#define RATE 48000

static AVAssetWriter *writer;
static AVAssetWriterInput *video_in, *audio_in;
static AVAssetWriterInputPixelBufferAdaptor *adaptor;
static CMAudioFormatDescriptionRef audio_fmt;
static long long frames, samples;
static char movie_path[1024];

int record_active(void) { return writer != nil; }

static int fail(const char *what, NSError *err) {
    fprintf(stderr, "can't record to %s: %s%s%s\n", movie_path, what, err ? ": " : "",
            err ? [[err localizedDescription] UTF8String] : "");
    return -1;
}

int record_start(const char *path) {
    if (writer) return 0;
    @autoreleasepool {
        snprintf(movie_path, sizeof movie_path, "%s", path);
        NSURL *url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:path]];
        [[NSFileManager defaultManager] removeItemAtURL:url error:nil];
        NSError *err = nil;
        writer = [[AVAssetWriter alloc] initWithURL:url fileType:AVFileTypeQuickTimeMovie error:&err];
        if (!writer) return fail("no writer", err);
        writer.movieTimeScale = FRAME_DEN;

        NSDictionary *colour = @{
            AVVideoColorPrimariesKey: AVVideoColorPrimaries_ITU_R_709_2,
            AVVideoTransferFunctionKey: AVVideoTransferFunction_ITU_R_709_2,
            AVVideoYCbCrMatrixKey: AVVideoYCbCrMatrix_ITU_R_709_2,
        };
        NSDictionary *vs = @{
            AVVideoCodecKey: AVVideoCodecTypeH264,
            AVVideoWidthKey: @(MOVIE_W),
            AVVideoHeightKey: @(MOVIE_H),
            AVVideoColorPropertiesKey: colour,
            AVVideoCompressionPropertiesKey: @{
                AVVideoAverageBitRateKey: @(20000000),
                AVVideoExpectedSourceFrameRateKey: @(60),
                AVVideoMaxKeyFrameIntervalKey: @(60),
                AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
            },
        };
        video_in = [[AVAssetWriterInput alloc] initWithMediaType:AVMediaTypeVideo outputSettings:vs];
        /* "Real time", as for a camera: frames come at the game's pace.
           With neither input in real time, the writer, after about a
           second of frames coming at 60 a second, stops taking any more
           (found in step 6's checks). What it isn't ready for waits in
           our queue. */
        video_in.expectsMediaDataInRealTime = YES;
        video_in.mediaTimeScale = FRAME_DEN;
        NSDictionary *pb = @{
            (id)kCVPixelBufferPixelFormatTypeKey: @(kCVPixelFormatType_32BGRA),
            (id)kCVPixelBufferWidthKey: @(MOVIE_W),
            (id)kCVPixelBufferHeightKey: @(MOVIE_H),
        };
        adaptor = [[AVAssetWriterInputPixelBufferAdaptor alloc]
                   initWithAssetWriterInput:video_in sourcePixelBufferAttributes:pb];

        AudioStreamBasicDescription asbd = { 0 };
        asbd.mSampleRate = RATE;
        asbd.mFormatID = kAudioFormatLinearPCM;
        asbd.mFormatFlags = kLinearPCMFormatFlagIsSignedInteger | kLinearPCMFormatFlagIsPacked;
        asbd.mBytesPerPacket = 2;
        asbd.mFramesPerPacket = 1;
        asbd.mBytesPerFrame = 2;
        asbd.mChannelsPerFrame = 1;
        asbd.mBitsPerChannel = 16;
        if (CMAudioFormatDescriptionCreate(kCFAllocatorDefault, &asbd, 0, NULL, 0, NULL, NULL,
                                           &audio_fmt) != noErr)
            return fail("no sound format", nil);
        NSDictionary *as = @{
            AVFormatIDKey: @(kAudioFormatLinearPCM),
            AVSampleRateKey: @(RATE),
            AVNumberOfChannelsKey: @1,
            AVLinearPCMBitDepthKey: @16,
            AVLinearPCMIsFloatKey: @NO,
            AVLinearPCMIsBigEndianKey: @NO,
            AVLinearPCMIsNonInterleaved: @NO,
        };
        audio_in = [[AVAssetWriterInput alloc] initWithMediaType:AVMediaTypeAudio outputSettings:as
                                                sourceFormatHint:audio_fmt];
        audio_in.expectsMediaDataInRealTime = YES;
        if (![writer canAddInput:video_in] || ![writer canAddInput:audio_in])
            return fail("can't add the picture and sound", nil);
        [writer addInput:video_in];
        [writer addInput:audio_in];
        if (![writer startWriting]) return fail("can't start", writer.error);
        [writer startSessionAtSourceTime:kCMTimeZero];
        frames = samples = 0;
        fprintf(stderr, "recording to %s\n", path);
    }
    return 0;
}

/* A millisecond's wait that keeps the main thread's run loop turning, in
   case the writer hands anything back through it. */
static void pause_a_moment(void) {
    if ([NSThread isMainThread]) CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.001, true);
    else usleep(1000);
}

static void lost(const char *what) {
    static int said;
    if (!said++) fprintf(stderr, "recording: a %s was lost (%s)\n", what,
                         writer.error ? [[writer.error localizedDescription] UTF8String] : "the writer stalled");
}

/* What is waiting to go to the writer. The writer takes the picture and
   the sound in turns (it interleaves them in the file), and may want
   more sound before it takes the next frame. That sound is only made by
   running the game on, so the game must never wait on the writer for
   one while it holds the other: frames and sound wait here instead, and
   go whenever their input is ready. Only a long line of frames (the
   encoder really behind, MAX_QUEUED of them) makes the game wait. */
#define MAX_QUEUED 600                  /* 10 seconds of frames, 70 MB */
struct item {
    struct item *next;
    long long at;                       /* the frame's number, or the first sample's */
    int n;                              /* samples */
    uint16_t *fb;                       /* a frame */
    int16_t *pcm;                       /* or sound */
};
static struct item *vq, *vq_end, *aq, *aq_end;
static int vq_len;

static void put(struct item **head, struct item **tail, struct item *it) {
    it->next = NULL;
    if (*tail) (*tail)->next = it; else *head = it;
    *tail = it;
}

static struct item *take(struct item **head, struct item **tail) {
    struct item *it = *head;
    if (it) { *head = it->next; if (!*head) *tail = NULL; }
    return it;
}

static void write_frame(struct item *it) {
    CVPixelBufferRef px = NULL;
    if (!adaptor.pixelBufferPool ||
        CVPixelBufferPoolCreatePixelBuffer(NULL, adaptor.pixelBufferPool, &px) != kCVReturnSuccess) {
        lost("frame");
        return;
    }
    CVPixelBufferLockBaseAddress(px, 0);
    uint8_t *base = CVPixelBufferGetBaseAddress(px);
    size_t stride = CVPixelBufferGetBytesPerRow(px);
    for (int y = 0; y < NES_HEIGHT; y++) {
        uint32_t *row = (uint32_t *)(base + (size_t)y * SCALE * stride);
        for (int x = 0; x < NES_WIDTH; x++) {
            uint32_t c = nes_rgb[it->fb[y * NES_WIDTH + x] & 0x1FF];   /* 0xAARRGGBB: BGRA bytes */
            for (int k = 0; k < SCALE; k++) row[x * SCALE + k] = c;
        }
        for (int k = 1; k < SCALE; k++)
            memcpy(base + ((size_t)y * SCALE + k) * stride, row, MOVIE_W * 4);
    }
    CVPixelBufferUnlockBaseAddress(px, 0);
    CMTime t = CMTimeMake(it->at * FRAME_NUM, FRAME_DEN);
    if (![adaptor appendPixelBuffer:px withPresentationTime:t]) lost("frame");
    CVPixelBufferRelease(px);
}

static void write_sound(struct item *it) {
    CMBlockBufferRef block = NULL;
    size_t bytes = (size_t)it->n * 2;
    if (CMBlockBufferCreateWithMemoryBlock(kCFAllocatorDefault, NULL, bytes, kCFAllocatorDefault,
                                           NULL, 0, bytes, kCMBlockBufferAssureMemoryNowFlag,
                                           &block) != noErr ||
        CMBlockBufferReplaceDataBytes(it->pcm, block, 0, bytes) != noErr) {
        if (block) CFRelease(block);
        lost("piece of sound");
        return;
    }
    CMSampleBufferRef sb = NULL;
    CMTime t = CMTimeMake(it->at, RATE);
    if (CMAudioSampleBufferCreateReadyWithPacketDescriptions(kCFAllocatorDefault, block, audio_fmt,
                                                             it->n, t, NULL, &sb) != noErr) {
        CFRelease(block);
        lost("piece of sound");
        return;
    }
    if (![audio_in appendSampleBuffer:sb]) lost("piece of sound");
    CFRelease(sb);
    CFRelease(block);
}

/* Hand over whatever the writer will take now. Returns how much went. */
static int pump(void) {
    int moved = 0;
    @autoreleasepool {
        for (;;) {
            int now = 0;
            if (writer.status == AVAssetWriterStatusFailed) break;
            if (vq && video_in.readyForMoreMediaData) {
                struct item *it = take(&vq, &vq_end);
                vq_len--;
                write_frame(it);
                free(it->fb);
                free(it);
                now = 1;
            }
            if (aq && audio_in.readyForMoreMediaData) {
                struct item *it = take(&aq, &aq_end);
                write_sound(it);
                free(it->pcm);
                free(it);
                now = 1;
            }
            if (!now) break;
            moved++;
        }
    }
    return moved;
}

/* Is the writer waiting for sound the game hasn't made yet? */
static int wants_sound(void) {
    return !aq && audio_in.readyForMoreMediaData;
}

void record_frame(const uint16_t *fb) {
    if (!writer) return;
    struct item *it = calloc(1, sizeof *it);
    it->at = frames++;
    it->fb = malloc(NES_WIDTH * NES_HEIGHT * sizeof *fb);
    memcpy(it->fb, fb, NES_WIDTH * NES_HEIGHT * sizeof *fb);
    put(&vq, &vq_end, it);
    vq_len++;
    pump();
    /* The encoder far behind: wait for it (the game slows, the movie
       doesn't lose a frame), unless it's waiting for sound. */
    for (int waited = 0; vq_len > MAX_QUEUED && !wants_sound() && waited < 10000; waited++) {
        pause_a_moment();
        if (pump()) waited = 0;
    }
}

void record_audio(const int16_t *s, int n) {
    if (!writer || n <= 0) return;
    struct item *it = calloc(1, sizeof *it);
    it->at = samples;
    it->n = n;
    it->pcm = malloc((size_t)n * sizeof *s);
    memcpy(it->pcm, s, (size_t)n * sizeof *s);
    samples += n;
    put(&aq, &aq_end, it);
    pump();
}

void record_stop(void) {
    if (!writer) return;
    @autoreleasepool {
        /* Everything still waiting goes first (giving up after 10 s with
           nothing taken, which only a broken writer would take). */
        for (int waited = 0; (vq || aq) && waited < 10000; waited++) {
            if (pump()) waited = 0;
            else pause_a_moment();
        }
        if (vq || aq) lost(vq ? "frame" : "piece of sound");
        while (vq) { struct item *it = take(&vq, &vq_end); free(it->fb); free(it); }
        while (aq) { struct item *it = take(&aq, &aq_end); free(it->pcm); free(it); }
        vq_len = 0;
        [video_in markAsFinished];
        [audio_in markAsFinished];
        __block volatile int finished = 0;
        [writer finishWritingWithCompletionHandler:^{ finished = 1; }];
        while (!finished) pause_a_moment();
        if (writer.status == AVAssetWriterStatusCompleted)
            fprintf(stderr, "recorded %lld frame(s) (%.1f s) to %s\n", frames,
                    (double)frames * FRAME_NUM / FRAME_DEN, movie_path);
        else
            fprintf(stderr, "the recording to %s failed: %s\n", movie_path,
                    writer.error ? [[writer.error localizedDescription] UTF8String] : "?");
        [adaptor release];
        [video_in release];
        [audio_in release];
        [writer release];
        CFRelease(audio_fmt);
        writer = nil;
        adaptor = nil;
        video_in = audio_in = nil;
        audio_fmt = NULL;
    }
}
