/* Read a movie back for tests/check_record.py (PLAN-standalone.md step 6),
   with Apple's AVFoundation: the same library a video editor or QuickTime
   would use to open it.

       read_movie MOVIE OUT

   prints
       video W H FRAMES RATE FIRST LAST STEP_MIN STEP_MAX TIMESCALE
           the size, the number of frames, the nominal rate, the first and
           last frame's time and the shortest and longest step between two
           frames (in the track's time units, TIMESCALE a second)
       audio RATE CHANNELS BITS FORMAT SAMPLES FIRST
           FORMAT "lpcm" for uncompressed; FIRST: the first sample's time
           in samples
       duration SECONDS
   and writes OUT.frames (each frame as 256x240 RGB: the pixel at the
   centre of each 4x4 block) and OUT.pcm (the sound, 16-bit, as it was
   decoded). Exit status 1 if it can't be opened.
   Built by the check: cc -fobjc-arc -framework AVFoundation ... */
#import <AVFoundation/AVFoundation.h>
#include <stdio.h>

int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc != 3) { fprintf(stderr, "usage: read_movie MOVIE OUT\n"); return 2; }
        NSURL *url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[1]]];
        AVURLAsset *asset = [AVURLAsset URLAssetWithURL:url options:@{
            AVURLAssetPreferPreciseDurationAndTimingKey: @YES }];
        NSError *err = nil;
        AVAssetReader *reader = [[AVAssetReader alloc] initWithAsset:asset error:&err];
        if (!reader) {
            printf("error %s\n", [[err localizedDescription] UTF8String]);
            return 1;
        }
        NSArray *vt = [asset tracksWithMediaType:AVMediaTypeVideo];
        NSArray *at = [asset tracksWithMediaType:AVMediaTypeAudio];
        AVAssetReaderTrackOutput *vo = nil, *ao = nil;
        if (vt.count) {
            vo = [[AVAssetReaderTrackOutput alloc] initWithTrack:vt[0] outputSettings:@{
                (id)kCVPixelBufferPixelFormatTypeKey: @(kCVPixelFormatType_32BGRA) }];
            [reader addOutput:vo];
        }
        if (at.count) {
            ao = [[AVAssetReaderTrackOutput alloc] initWithTrack:at[0] outputSettings:@{
                AVFormatIDKey: @(kAudioFormatLinearPCM), AVLinearPCMBitDepthKey: @16,
                AVLinearPCMIsFloatKey: @NO, AVLinearPCMIsBigEndianKey: @NO,
                AVLinearPCMIsNonInterleaved: @NO }];
            [reader addOutput:ao];
        }
        if (![reader startReading]) {
            printf("error %s\n", [[reader.error localizedDescription] UTF8String]);
            return 1;
        }
        char path[2048];
        snprintf(path, sizeof path, "%s.frames", argv[2]);
        FILE *ff = fopen(path, "wb");
        snprintf(path, sizeof path, "%s.pcm", argv[2]);
        FILE *pf = fopen(path, "wb");
        if (!ff || !pf) { perror(path); return 2; }

        long frames = 0;
        int w = 0, h = 0;
        int64_t first = 0, last = 0, step_min = 0, step_max = 0;
        int32_t scale = 0;
        if (vo) {
            CMSampleBufferRef sb;
            static uint8_t rgb[256 * 240 * 3];
            while ((sb = [vo copyNextSampleBuffer])) {
                CVImageBufferRef img = CMSampleBufferGetImageBuffer(sb);
                if (!img) { CFRelease(sb); continue; }
                CMTime t = CMSampleBufferGetPresentationTimeStamp(sb);
                if (frames == 0) { first = t.value; scale = t.timescale; }
                else {
                    int64_t step = t.value - last;
                    if (frames == 1 || step < step_min) step_min = step;
                    if (frames == 1 || step > step_max) step_max = step;
                }
                last = t.value;
                CVPixelBufferLockBaseAddress(img, kCVPixelBufferLock_ReadOnly);
                w = (int)CVPixelBufferGetWidth(img);
                h = (int)CVPixelBufferGetHeight(img);
                const uint8_t *base = CVPixelBufferGetBaseAddress(img);
                size_t stride = CVPixelBufferGetBytesPerRow(img);
                for (int y = 0; y < 240; y++)
                    for (int x = 0; x < 256; x++) {
                        int sx = x * w / 256 + w / 512, sy = y * h / 240 + h / 480;
                        const uint8_t *p = base + (size_t)sy * stride + (size_t)sx * 4;
                        uint8_t *o = rgb + (y * 256 + x) * 3;
                        o[0] = p[2]; o[1] = p[1]; o[2] = p[0];
                    }
                CVPixelBufferUnlockBaseAddress(img, kCVPixelBufferLock_ReadOnly);
                fwrite(rgb, 1, sizeof rgb, ff);
                frames++;
                CFRelease(sb);
            }
            printf("video %d %d %ld %.6f %lld %lld %lld %lld %d\n", w, h, frames,
                   ((AVAssetTrack *)vt[0]).nominalFrameRate, (long long)first, (long long)last,
                   (long long)step_min, (long long)step_max, scale);
        } else printf("video none\n");
        if (ao) {
            AVAssetTrack *track = at[0];
            CMAudioFormatDescriptionRef fd = (__bridge CMAudioFormatDescriptionRef)track.formatDescriptions[0];
            const AudioStreamBasicDescription *d = CMAudioFormatDescriptionGetStreamBasicDescription(fd);
            uint32_t id = d->mFormatID;
            char fmt[5] = { (char)(id >> 24), (char)(id >> 16), (char)(id >> 8), (char)id, 0 };
            long count = 0;
            int64_t first_s = -1;
            CMSampleBufferRef sb;
            while ((sb = [ao copyNextSampleBuffer])) {
                if (first_s < 0) {
                    CMTime t = CMSampleBufferGetPresentationTimeStamp(sb);
                    first_s = (int64_t)llround(CMTimeGetSeconds(t) * d->mSampleRate);
                }
                CMBlockBufferRef bb = CMSampleBufferGetDataBuffer(sb);
                size_t len = CMBlockBufferGetDataLength(bb);
                char *data = malloc(len);
                CMBlockBufferCopyDataBytes(bb, 0, len, data);
                fwrite(data, 1, len, pf);
                free(data);
                count += (long)(len / 2);
                CFRelease(sb);
            }
            printf("audio %.0f %u %u %s %ld %lld\n", d->mSampleRate, d->mChannelsPerFrame,
                   d->mBitsPerChannel, fmt, count, (long long)(first_s < 0 ? 0 : first_s));
        } else printf("audio none\n");
        printf("duration %.6f\n", CMTimeGetSeconds(asset.duration));
        fclose(ff);
        fclose(pf);
        if (reader.status == AVAssetReaderStatusFailed) {
            printf("error %s\n", [[reader.error localizedDescription] UTF8String]);
            return 1;
        }
    }
    return 0;
}
