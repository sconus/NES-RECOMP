/* nesrecomp runtime: the Famicom Disk System.

   ---- Its sound (nesdev wiki "FDS audio") ----
   One wavetable channel with frequency modulation:
     $4040-$407F  64 samples, 6 bits each; written only while $4089 bit
                  7 is set; read back with bits 7-6 = 01 (with $4089 bit 7
                  clear, any of them reads the sample being played)
     $4080        volume envelope: bit 7 off (bits 5-0 are then the gain),
                  bit 6 up (else down), bits 5-0 speed
     $4082/3      12-bit frequency; $4083 bit 7 stops the wave (and resets
                  its position to 0), bit 6 stops both envelopes (and
                  resets their timers)
     $4084        modulation envelope, laid out as $4080
     $4085        the modulation counter, 7-bit signed
     $4086/7      12-bit modulation frequency; $4087 bit 7 stops the
                  modulation table (and opens $4088), bit 6 steps it every
                  tick
     $4088        modulation table write: 3 bits at the table position,
                  which then moves on one entry (only while $4087 bit 7)
     $4089        bit 7 wavetable write (the output holds its level, the
                  wave keeps moving), bits 1-0 master volume: 1, 2/3,
                  2/4, 2/5
     $408A        envelope speed multiplier (0 stops both envelopes)
     $4090/$4092  the volume / modulation gain; $4091 the wave
                  accumulator's bits 12-19; $4097 the modulation counter
   The wave and the modulation table move every 16 CPU cycles:
   - The modulation table (32 entries, each used twice, so 64 positions)
     is a position plus a 12-bit accumulator. Each tick adds the
     modulation frequency; a carry out of the accumulator (or $4087 bit
     6) applies the entry at the position to the counter and moves on.
     Entries: 0, +1, +2, +4, reset to 0, -4, -2, -1.
   - The wave's step is the frequency scaled by the counter times the
     modulation gain, rounded as the wiki gives it. A 24-bit accumulator
     adds it each tick, and its top 6 bits are the wave position.
   An envelope ticks every 8 * (speed + 1) * ($408A + 1) CPU cycles,
   moving its gain one step towards 0 or 32. A new volume gain is heard
   from the next time the wave passes position 0. The output is sample
   * min(volume gain, 32) * master volume, through a one-pole low-pass
   near 2 kHz. Full scale is 2.4 times an APU square's.
   Where the wiki's sources disagree, this follows the wiki:
   - with $4083 bit 7 set, the output is sample 0 (not silence), and the
     envelopes run 4 times as fast;
   - $4089 bit 7 holds the output level (rather than silencing it);
   - the counter keeps changing the pitch while the table is stopped. */
#include <math.h>
#include <string.h>
#include "fds.h"
#include "rt.h"

#define CPU_HZ 1789772.727
#define LOWPASS_HZ 2000.0
/* 63 * 32 at full master volume = 2.4 APU squares (0.1494 each). */
#define FDS_UNIT (2.4f * 0.1494f / 2016.0f)

static struct {
    uint8_t wave[64], mod_table[32];
    uint8_t vol_ctrl, mod_ctrl;     /* $4080, $4084 */
    uint8_t vol_gain, mod_gain;
    int vol_timer, mod_timer;       /* CPU cycles to the next envelope tick */
    uint16_t freq, mod_freq;        /* 12 bits each */
    uint8_t wave_flags, mod_flags;  /* $4083, $4087 bits 7-6 */
    int counter;                    /* -64..63 */
    uint32_t wave_acc;              /* 24 bits; bits 23-18 the position */
    uint32_t mod_acc;               /* 12 bits */
    int mod_pos;                    /* 0-63; entry mod_pos / 2 */
    uint8_t write_mode, master, env_speed;
    uint8_t vol_out;                /* the gain heard, at most 32 */
    int tick;                       /* CPU cycles to the next 16-cycle tick */
    int held;                       /* the level while $4089 bit 7 is set */
    float filtered;
    uint64_t now;                   /* the CPU cycle the state is at */
} fs;

int fds_sound_on = 1;

static int env_period(uint8_t ctrl) {
    int p = 8 * ((ctrl & 0x3F) + 1) * (fs.env_speed + 1);
    return (fs.wave_flags & 0x80) ? p / 4 : p;
}

void fds_sound_reset(void) {
    memset(&fs, 0, sizeof fs);
    /* As the BIOS leaves them: envelope off, speed multiplier $E8. */
    fs.vol_ctrl = fs.mod_ctrl = 0x80;
    fs.env_speed = 0xE8;
    fs.vol_timer = env_period(fs.vol_ctrl);
    fs.mod_timer = env_period(fs.mod_ctrl);
    fs.tick = 16;
    fs.now = cycles;
}

static void envelope(uint8_t ctrl, uint8_t *gain, int *timer) {
    if ((ctrl & 0x80) || (fs.wave_flags & 0x40) || fs.env_speed == 0) return;
    if (--*timer > 0) return;
    *timer = env_period(ctrl);
    if (ctrl & 0x40) { if (*gain < 32) ++*gain; }
    else if (*gain > 0) --*gain;
}

/* The wave's step for one tick: the frequency scaled by the
   modulation (nesdev wiki "FDS audio", the pitch computation). */
static uint32_t wave_step(void) {
    int temp = fs.counter * fs.mod_gain;
    if ((temp & 0x0F) && !(temp & 0x800)) temp += 0x20;
    temp += 0x400;
    temp = (temp >> 4) & 0xFF;
    return ((uint32_t)fs.freq * (uint32_t)temp) & 0xFFFFF;
}

static void tick16(void) {
    /* The modulation table. */
    if (!(fs.mod_flags & 0x80) && !(fs.wave_flags & 0x80)) {
        fs.mod_acc += fs.mod_freq;
        int step = (fs.mod_acc >> 12) != 0 || (fs.mod_flags & 0x40);
        fs.mod_acc &= 0xFFF;
        if (step) {
            static const int8_t delta[8] = { 0, 1, 2, 4, 0, -4, -2, -1 };
            uint8_t e = fs.mod_table[fs.mod_pos >> 1];
            int c = e == 4 ? 0 : fs.counter + delta[e];
            c &= 0x7F;
            fs.counter = c >= 64 ? c - 128 : c;
            fs.mod_pos = (fs.mod_pos + 1) & 63;
        }
    }
    /* The wave. */
    if (fs.wave_flags & 0x80) {
        fs.wave_acc = 0;
        fs.vol_out = fs.vol_gain < 32 ? fs.vol_gain : 32;
    } else {
        uint32_t old = fs.wave_acc;
        fs.wave_acc = (fs.wave_acc + wave_step()) & 0xFFFFFF;
        if (fs.wave_acc < old)          /* passed position 0 */
            fs.vol_out = fs.vol_gain < 32 ? fs.vol_gain : 32;
    }
}

/* Bring the envelopes, the modulation and the wave up to CPU cycle
   `upto`. They run whether or not sound is being made, since the CPU can
   read them back. */
static void run(uint64_t upto) {
    while (fs.now < upto) {
        fs.now++;
        if (!fds_sound_on) continue;
        envelope(fs.vol_ctrl, &fs.vol_gain, &fs.vol_timer);
        envelope(fs.mod_ctrl, &fs.mod_gain, &fs.mod_timer);
        if (--fs.tick <= 0) { fs.tick = 16; tick16(); }
    }
}

float fds_audio_step(uint64_t cycle) {
    run(cycle + 1);
    if (!fds_sound_on) return 0;
    if (!fs.write_mode) fs.held = fs.wave[fs.wave_acc >> 18] * fs.vol_out;
    static const float master[4] = { 1.0f, 2.0f / 3, 2.0f / 4, 2.0f / 5 };
    float x = (float)fs.held * master[fs.master];
    static float k = 0;
    if (k == 0) k = (float)(1 - exp(-2 * M_PI * LOWPASS_HZ / CPU_HZ));
    fs.filtered += (x - fs.filtered) * k;
    return fs.filtered * FDS_UNIT;
}

void fds_sound_write(uint16_t addr, uint8_t val) {
    run(cycles);
    if (addr >= 0x4040 && addr < 0x4080) {
        if (fs.write_mode) fs.wave[addr - 0x4040] = val & 0x3F;
        return;
    }
    switch (addr) {
    case 0x4080:
        fs.vol_ctrl = val;
        if (val & 0x80) fs.vol_gain = val & 0x3F;
        fs.vol_timer = env_period(val);
        break;
    case 0x4082: fs.freq = (uint16_t)((fs.freq & 0xF00) | val); break;
    case 0x4083:
        fs.freq = (uint16_t)((fs.freq & 0xFF) | (val & 0x0F) << 8);
        fs.wave_flags = val & 0xC0;
        if (val & 0x80) fs.wave_acc = 0;
        if (val & 0x40) {
            fs.vol_timer = env_period(fs.vol_ctrl);
            fs.mod_timer = env_period(fs.mod_ctrl);
        }
        break;
    case 0x4084:
        fs.mod_ctrl = val;
        if (val & 0x80) fs.mod_gain = val & 0x3F;
        fs.mod_timer = env_period(val);
        break;
    case 0x4085: fs.counter = (val & 0x40) ? (val & 0x7F) - 128 : val & 0x3F; break;
    case 0x4086: fs.mod_freq = (uint16_t)((fs.mod_freq & 0xF00) | val); break;
    case 0x4087:
        fs.mod_freq = (uint16_t)((fs.mod_freq & 0xFF) | (val & 0x0F) << 8);
        fs.mod_flags = val & 0xC0;
        if (val & 0x80) { fs.mod_acc = 0; fs.mod_pos &= ~1; }
        break;
    case 0x4088:
        if (fs.mod_flags & 0x80) {
            fs.mod_table[fs.mod_pos >> 1] = val & 7;
            fs.mod_pos = (fs.mod_pos + 2) & 63;
        }
        break;
    case 0x4089: fs.write_mode = val >> 7; fs.master = val & 3; break;
    case 0x408A: fs.env_speed = val; break;
    }
}

int fds_sound_read(uint16_t addr) {
    run(cycles);
    if (addr >= 0x4040 && addr < 0x4080)
        return 0x40 | fs.wave[fs.write_mode ? addr - 0x4040 : fs.wave_acc >> 18];
    switch (addr) {
    case 0x4090: return 0x40 | fs.vol_gain;
    case 0x4091: return (int)((fs.wave_acc >> 12) & 0xFF);
    case 0x4092: return 0x40 | fs.mod_gain;
    case 0x4097: return fs.counter & 0x7F;
    }
    return -1;
}
