/* nesrecomp runtime: the APU (sound).

   Like the PPU, the APU catches up to the CPU's cycle count when the CPU
   touches it or an event is due. Here that means three things:

   - Length counters (pulse 1, pulse 2, triangle, noise): a note's
     remaining duration, loaded from a table when the program writes the
     channel's 4th register, counted down by the frame counter, and
     visible in $4015.
   - The frame counter: a sequencer that clocks the length counters (and,
     later, envelopes and sweeps) a few times a frame, and in its 4-step
     mode raises an IRQ once per sequence.
   - The DMC: plays a sample from ROM. Its "bytes remaining" shows in
     $4015, and it can raise an IRQ when a sample ends.

   When sound output is on (a window or --wav), it also runs the five
   channels cycle by cycle, mixes them like the console's DACs, and
   turns the result into 48 kHz samples. Headless test runs skip that
   part, since nothing the CPU can see depends on it.

   All times are in CPU cycles. */
#include <string.h>
#include "apu.h"
#include "event.h"
#include "cycles.h"
#include "rt.h"

/* Note lengths, indexed by the top 5 bits of the 4th channel register. */
static const uint8_t length_table[32] = {
    10, 254, 20, 2, 40, 4, 80, 6, 160, 8, 60, 10, 14, 12, 26, 14,
    12, 16, 24, 18, 48, 20, 96, 22, 192, 24, 72, 26, 16, 28, 32, 30,
};

/* CPU cycles per noise step, for the 16 period settings (NTSC). */
static const uint16_t noise_periods[16] = {
    4, 8, 16, 32, 64, 96, 128, 160, 202, 254, 380, 508, 762, 1016, 2034, 4068,
};

/* Pulse wave shapes: 12.5%, 25%, 50%, 75% (negated 25%). */
static const uint8_t duty_table[4][8] = {
    { 0, 1, 0, 0, 0, 0, 0, 0 }, { 0, 1, 1, 0, 0, 0, 0, 0 },
    { 0, 1, 1, 1, 1, 0, 0, 0 }, { 1, 0, 0, 1, 1, 1, 1, 1 },
};

/* The triangle's 32-step staircase. */
static const uint8_t triangle_table[32] = {
    15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0,
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
};

/* CPU cycles per DMC output bit, for the 16 rate settings (NTSC). */
static const uint16_t dmc_rates[16] = {
    428, 380, 340, 320, 286, 254, 226, 214, 190, 160, 142, 128, 106, 84, 72, 54,
};

struct length {
    uint8_t counter, halt, enabled;
    uint64_t clocked_at;            /* last half-frame clock that counted it */
};

/* Volume envelope (pulses and noise): either a constant volume or a
   decay from 15 to 0, one step per `period + 1` quarter frames. */
struct envelope {
    uint8_t start, divider, decay, period, constant, loop;
};

struct pulse {
    uint8_t duty, step;
    uint16_t period;                /* 11-bit timer period */
    uint32_t timer;                 /* CPU cycles to the next step */
    struct envelope env;
    uint8_t sweep_enabled, sweep_period, sweep_negate, sweep_shift;
    uint8_t sweep_reload, sweep_divider;
};

static struct {
    struct length len[4];           /* pulse 1, pulse 2, triangle, noise */

    struct pulse pulse[2];
    struct {
        uint16_t period;
        uint32_t timer;
        uint8_t step, linear, linear_period, linear_reload, control;
    } tri;
    struct {
        uint16_t period, shift;
        uint32_t timer;
        uint8_t mode;
        struct envelope env;
    } noise;

    /* Frame counter */
    int five_step, irq_inhibit, frame_irq;
    uint64_t frame_start;           /* cycle the current sequence began */
    int frame_step;                 /* index of the next step to run */
    uint64_t pending_reset_at;      /* a $4017 write takes effect later */
    uint8_t pending_mode;
    int reset_pending;

    /* DMC */
    int dmc_irq_enabled, dmc_loop, dmc_irq;
    uint16_t dmc_rate;
    uint16_t dmc_start_addr, dmc_start_len;
    uint16_t dmc_addr, dmc_remaining;
    int dmc_buffer_full, dmc_bits_left;
    uint8_t dmc_buffer, dmc_shift, dmc_silence, dmc_level;
    uint64_t dmc_next_bit;          /* cycle of the output unit's next tick */

    uint64_t now;                   /* cycles the APU has caught up to */
} apu;

/* ---- the frame counter ------------------------------------------------

   Steps, in CPU cycles after the sequence starts (nesdev wiki):
     4-step: 7457 Q, 14913 Q+H, 22371 Q, 29828 irq, 29829 Q+H+irq,
             29830 irq and restart
     5-step: 7457 Q, 14913 Q+H, 22371 Q, 37281 Q+H, 37282 restart
   Q = quarter frame (envelopes, triangle linear counter: later),
   H = half frame (length counters, sweeps). */
enum { Q = 1, H = 2, IRQ = 4, RESTART = 8 };
static const struct { uint32_t at; int what; } seq4[] = {
    { 7457, Q }, { 14913, Q | H }, { 22371, Q }, { 29828, IRQ },
    { 29829, Q | H | IRQ }, { 29830, IRQ | RESTART },
};
static const struct { uint32_t at; int what; } seq5[] = {
    { 7457, Q }, { 14913, Q | H }, { 22371, Q }, { 37281, Q | H },
    { 37282, RESTART },
};

static uint64_t clock_now;          /* the APU's own time while catching up */
static uint8_t last_4017;           /* rewritten by the reset button */

static void update_irq_line(void) {
    cpu_set_irq_at(IRQ_APU, apu.frame_irq || apu.dmc_irq, clock_now * 3);
}

static void envelope_clock(struct envelope *e) {
    if (e->start) {
        e->start = 0;
        e->decay = 15;
        e->divider = e->period;
    } else if (e->divider == 0) {
        e->divider = e->period;
        if (e->decay) e->decay--;
        else if (e->loop) e->decay = 15;
    } else {
        e->divider--;
    }
}

static int envelope_volume(const struct envelope *e) {
    return e->constant ? e->period : e->decay;
}

/* The sweep unit's target period. Pulse 1 subtracts one more when going
   down (it negates with one's complement, pulse 2 with two's). */
static int sweep_target(int i) {
    const struct pulse *p = &apu.pulse[i];
    int change = p->period >> p->sweep_shift;
    if (!p->sweep_negate) return p->period + change;
    int t = p->period - change - (i == 0);
    return t < 0 ? 0 : t;
}

static int pulse_muted(int i) {
    return apu.pulse[i].period < 8 || sweep_target(i) > 0x7FF;
}

static void sweep_clock(int i) {
    struct pulse *p = &apu.pulse[i];
    if (p->sweep_divider == 0 && p->sweep_enabled && p->sweep_shift &&
        !pulse_muted(i))
        p->period = (uint16_t)sweep_target(i);
    if (p->sweep_divider == 0 || p->sweep_reload) {
        p->sweep_divider = p->sweep_period;
        p->sweep_reload = 0;
    } else {
        p->sweep_divider--;
    }
}

static void half_frame(uint64_t when) {
    for (int i = 0; i < 4; i++)
        if (apu.len[i].counter && !apu.len[i].halt) {
            apu.len[i].counter--;
            apu.len[i].clocked_at = when;
        }
    sweep_clock(0);
    sweep_clock(1);
}

static void quarter_frame(void) {
    envelope_clock(&apu.pulse[0].env);
    envelope_clock(&apu.pulse[1].env);
    envelope_clock(&apu.noise.env);
    if (apu.tri.linear_reload) apu.tri.linear = apu.tri.linear_period;
    else if (apu.tri.linear) apu.tri.linear--;
    if (!apu.tri.control) apu.tri.linear_reload = 0;
}

static uint64_t next_frame_event(void) {
    uint32_t at = apu.five_step ? seq5[apu.frame_step].at
                                : seq4[apu.frame_step].at;
    return apu.frame_start + at;
}

static void run_frame_step(void) {
    int what = apu.five_step ? seq5[apu.frame_step].what
                             : seq4[apu.frame_step].what;
    if (what & Q) quarter_frame();
    if (what & H) half_frame(next_frame_event());
    if ((what & IRQ) && !apu.irq_inhibit) {
        apu.frame_irq = 1;
        update_irq_line();
    }
    if (what & RESTART) {
        apu.frame_start = next_frame_event();
        apu.frame_step = 0;
    } else {
        apu.frame_step++;
    }
}

/* A $4017 write: the new mode starts a few cycles later. Writing the
   5-step mode also clocks everything once, straight away. */
static void frame_counter_reset(void) {
    apu.five_step = (apu.pending_mode & 0x80) != 0;
    apu.frame_start = apu.pending_reset_at;
    apu.frame_step = 0;
    apu.reset_pending = 0;
    if (apu.five_step) { quarter_frame(); half_frame(apu.frame_start); }
}

/* ---- the DMC's sample reader and its DMA ---------------------------------

   The DMC reads sample bytes from ROM by pausing the CPU (DMA). When the
   output unit takes the buffered byte, the reader asks for the next one;
   the CPU then halts on its next read cycle, waits for an aligned cycle,
   and the byte is fetched. While halted the CPU keeps its read address
   on the bus, so a read of $2007 or $4016 that the pause lands on
   happens more than once: the side effect games know as "DMC conflicts".

   dmc_dma_due is the cycle at or after which the next DMA happens: a
   pending request, or (with a full buffer) the predicted moment the
   output unit takes it. The CPU bus checks it on every read of
   $2000-$401F; elsewhere the DMA happens at the next instruction
   boundary (an event). */
uint64_t dmc_dma_due = UINT64_MAX;
static int dmc_dma_requested;
static uint64_t dmc_dma_request_at;
/* A "load" (a $4015 write starting a sample into an empty buffer) or a
   "reload" (the output unit took the buffered byte). They first try to
   halt the CPU on different kinds of cycle, below. */
static int dmc_dma_load;

/* CPU cycles alternate between "get" and "put", following the APU's clock.
   This says which are gets: (cycles & 1) == GET_PARITY. On hardware it's
   one of two at random from power-on; tests that care accept either. */
#define GET_PARITY 0
/* A $4015 write that starts a sample asks for its first byte this many
   cycles later. Tuned with apu_test 7 and 8 (1 and 2 both pass). */
#define DMA_START_DELAY 2
/* A CPU read made at `cycles` happens, in APU time, at the end of that bus
   cycle (as with writes, see WRITE_DELAY): a DMA requested by then halts
   on it. Tuned with dmc_dma_during_read4. */
#define DMA_READ_AT 1

static void dmc_restart(void) {
    apu.dmc_addr = apu.dmc_start_addr;
    apu.dmc_remaining = apu.dmc_start_len;
}

static void dmc_update_due(void) {
    if (dmc_dma_requested)
        dmc_dma_due = dmc_dma_request_at;
    else if (apu.dmc_buffer_full && apu.dmc_remaining)
        dmc_dma_due = apu.dmc_next_bit + (uint64_t)apu.dmc_rate * apu.dmc_bits_left;
    else
        dmc_dma_due = UINT64_MAX;
    /* Wake the CPU then, even if it's in a loop that touches no hardware. */
    if (dmc_dma_due != UINT64_MAX) schedule_event(dmc_dma_due);
}

static void dmc_request(uint64_t at, int load) {
    if (apu.dmc_buffer_full || !apu.dmc_remaining || dmc_dma_requested) return;
    dmc_dma_requested = 1;
    dmc_dma_load = load;
    dmc_dma_request_at = at;
    dmc_update_due();
}

static void dmc_fetch(void) {
    if (apu.dmc_buffer_full || !apu.dmc_remaining) return;
    apu.dmc_buffer = rd(apu.dmc_addr);
    apu.dmc_addr = apu.dmc_addr == 0xFFFF ? 0x8000 : apu.dmc_addr + 1;
    apu.dmc_buffer_full = 1;
    if (--apu.dmc_remaining == 0) {
        if (apu.dmc_loop) dmc_restart();
        else if (apu.dmc_irq_enabled) { apu.dmc_irq = 1; update_irq_line(); }
    }
}

/* The output unit plays 8 bits per sample byte, one every dmc_rate
   cycles: each 1 bit raises the 7-bit level by 2, each 0 lowers it.
   When it starts a new byte it takes the one in the buffer (or stays
   silent if there is none), and the reader refills the buffer. */
static void dmc_tick(void) {
    if (apu.dmc_bits_left == 0) {
        apu.dmc_bits_left = 8;
        if (apu.dmc_buffer_full) {
            apu.dmc_silence = 0;
            apu.dmc_shift = apu.dmc_buffer;
            apu.dmc_buffer_full = 0;
            dmc_request(apu.dmc_next_bit, 0);
        } else {
            apu.dmc_silence = 1;
        }
    }
    if (!apu.dmc_silence) {
        if (apu.dmc_shift & 1) { if (apu.dmc_level <= 125) apu.dmc_level += 2; }
        else if (apu.dmc_level >= 2) apu.dmc_level -= 2;
    }
    apu.dmc_shift >>= 1;
    apu.dmc_bits_left--;
    apu.dmc_next_bit += apu.dmc_rate;
    dmc_update_due();
}

/* ---- sound output ----------------------------------------------------

   Each CPU cycle the channel timers step, the five outputs are mixed,
   and the mix is added to a running sum. Every 1789773 / 48000 (about
   37.3) cycles the average of that sum becomes one 48 kHz sample: a box
   filter that keeps the decimation from aliasing too badly. The result
   then goes through the same gentle filters as the console's output
   stage: two high-passes (90 Hz, 440 Hz) and a low-pass (14 kHz). */
#define CPU_HZ 1789773.0
#define SAMPLE_RATE 48000
#define SAMPLE_BUFFER 16384

static struct {
    int enabled;
    uint64_t at;                    /* cycles generated so far */
    double cycles_per_sample, next_sample;
    double sum;
    int count;
    float pulse_table[31];
    float tnd_table[16][16][128];   /* [triangle][noise][dmc] */
    float hp90_prev_in, hp90_out, hp440_prev_in, hp440_out, lp_out;
    float hp90_a, hp440_a, lp_b;
    int16_t buf[SAMPLE_BUFFER];
    int len;
} snd;

/* The console mixes the channels through resistor DACs, which isn't
   linear: these are the formulas from the nesdev wiki. The triangle,
   noise and DMC share one DAC, so their table is indexed by all three
   (the common 3t + 2n + d shortcut is audibly off in apu_mixer's
   triangle test). */
static void build_mixer_tables(void) {
    snd.pulse_table[0] = 0;
    for (int n = 1; n < 31; n++)
        snd.pulse_table[n] = (float)(95.88 / (8128.0 / n + 100.0));
    for (int t = 0; t < 16; t++)
        for (int n = 0; n < 16; n++)
            for (int d = 0; d < 128; d++) {
                double sum = t / 8227.0 + n / 12241.0 + d / 22638.0;
                snd.tnd_table[t][n][d] =
                    sum ? (float)(159.79 / (1.0 / sum + 100.0)) : 0.0f;
            }
}

static float one_pole(double cutoff) {      /* RC filter coefficient */
    double rc = 1.0 / (2 * 3.14159265358979 * cutoff), dt = 1.0 / SAMPLE_RATE;
    return (float)(rc / (rc + dt));
}

void apu_enable_sound(void) {
    snd.enabled = 1;
    snd.at = apu.now;
    snd.cycles_per_sample = CPU_HZ / SAMPLE_RATE;
    snd.next_sample = (double)snd.at + snd.cycles_per_sample;
    build_mixer_tables();
    snd.hp90_a = one_pole(90);
    snd.hp440_a = one_pole(440);
    snd.lp_b = 1.0f - one_pole(14000);
}

void apu_set_sample_rate_trim(double factor) {
    snd.cycles_per_sample = CPU_HZ / SAMPLE_RATE * factor;
}

int apu_take_samples(int16_t *out, int max) {
    int n = snd.len < max ? snd.len : max;
    memcpy(out, snd.buf, (size_t)n * sizeof *out);
    memmove(snd.buf, snd.buf + n, (size_t)(snd.len - n) * sizeof *out);
    snd.len -= n;
    return n;
}

static void emit_sample(float x) {
    static int primed;
    if (!primed) {      /* start the filters at rest, without a power-on click */
        snd.hp90_prev_in = x;
        snd.hp440_prev_in = 0;
        primed = 1;
    }
    /* high-pass: y = a * (y_prev + x - x_prev); low-pass: y += b * (x - y) */
    float h1 = snd.hp90_a * (snd.hp90_out + x - snd.hp90_prev_in);
    snd.hp90_prev_in = x; snd.hp90_out = h1;
    float h2 = snd.hp440_a * (snd.hp440_out + h1 - snd.hp440_prev_in);
    snd.hp440_prev_in = h1; snd.hp440_out = h2;
    snd.lp_out += snd.lp_b * (h2 - snd.lp_out);
    float v = snd.lp_out * 40000.0f;
    if (v > 32767) v = 32767;
    if (v < -32768) v = -32768;
    if (snd.len < SAMPLE_BUFFER) snd.buf[snd.len++] = (int16_t)v;
}

static int pulse_output(int i) {
    const struct pulse *p = &apu.pulse[i];
    if (!apu.len[i].counter || pulse_muted(i) || !duty_table[p->duty][p->step])
        return 0;
    return envelope_volume(&p->env);
}

/* Run the channel timers and the sampler up to `to` (exclusive). */
static void generate(uint64_t to) {
    for (; snd.at < to; snd.at++) {
        for (int i = 0; i < 2; i++) {        /* pulses: every 2 cycles */
            struct pulse *p = &apu.pulse[i];
            if (p->timer == 0) {
                p->timer = (uint32_t)(p->period + 1) * 2 - 1;
                p->step = (p->step + 1) & 7;
            } else {
                p->timer--;
            }
        }
        if (apu.tri.timer == 0) {            /* triangle: every cycle */
            apu.tri.timer = apu.tri.period;
            if (apu.tri.linear && apu.len[2].counter)
                apu.tri.step = (apu.tri.step + 1) & 31;
        } else {
            apu.tri.timer--;
        }
        if (apu.noise.timer == 0) {          /* noise: 15-bit shift register */
            apu.noise.timer = apu.noise.period - 1u;
            uint16_t r = apu.noise.shift;
            int fb = (r ^ (r >> (apu.noise.mode ? 6 : 1))) & 1;
            apu.noise.shift = (uint16_t)(r >> 1 | fb << 14);
        } else {
            apu.noise.timer--;
        }

        int p = pulse_output(0) + pulse_output(1);
        int t = triangle_table[apu.tri.step];
        int n = (apu.noise.shift & 1) || !apu.len[3].counter
                ? 0 : envelope_volume(&apu.noise.env);
        snd.sum += snd.pulse_table[p] + snd.tnd_table[t][n][apu.dmc_level];
        snd.count++;
        if ((double)snd.at + 1 >= snd.next_sample) {
            emit_sample((float)(snd.sum / snd.count));
            snd.sum = 0;
            snd.count = 0;
            snd.next_sample += snd.cycles_per_sample;
        }
    }
}

/* ---- catching up ------------------------------------------------------ */

static void run_until(uint64_t target) {
    for (;;) {
        uint64_t frame_at = next_frame_event();
        uint64_t reset_at = apu.reset_pending ? apu.pending_reset_at : UINT64_MAX;
        uint64_t dmc_at = apu.dmc_next_bit;
        uint64_t t = frame_at;
        if (reset_at < t) t = reset_at;
        if (dmc_at < t) t = dmc_at;
        if (t > target) break;
        if (snd.enabled) generate(t);
        clock_now = t;
        if (t == reset_at) frame_counter_reset();
        else if (t == frame_at) run_frame_step();
        else dmc_tick();
    }
    if (snd.enabled) generate(target);
    apu.now = target;
}

void apu_catch_up(void) {
    if (cycles > apu.now) run_until(cycles);
}

/* A CPU write reaches the APU this many cycles after `cycles` (the start
   of the write's bus cycle). Tuned with blargg_apu_2005 10 and 11. */
#define WRITE_DELAY 1
/* $4017 takes effect this many cycles after the write, plus one more if
   the write lands on an odd cycle. Tuned with blargg_apu_2005 04 and 09. */
#define FRAME_RESET_DELAY 2

void apu_schedule(void) {
    uint64_t t = UINT64_MAX;
    if (!apu.five_step && !apu.irq_inhibit && !apu.frame_irq) {
        /* the next IRQ step of the 4-step sequence */
        for (int s = apu.frame_step; s < 6; s++)
            if (seq4[s].what & IRQ) { t = apu.frame_start + seq4[s].at; break; }
    }
    if (apu.reset_pending && apu.pending_reset_at < t) t = apu.pending_reset_at;
    if (apu.dmc_remaining && apu.dmc_irq_enabled && apu.dmc_next_bit < t)
        t = apu.dmc_next_bit;
    if (dmc_dma_due < t) t = dmc_dma_due;
    if (t != UINT64_MAX) schedule_event(t);
}

/* ---- registers -------------------------------------------------------- */

void apu_write(uint16_t addr, uint8_t val) {
    uint64_t when = cycles + WRITE_DELAY;
    if (when > apu.now) run_until(when);
    clock_now = when;
    int ch = (addr - 0x4000) >> 2;          /* 0-3 for the four channels */
    switch (addr) {
    case 0x4000: case 0x4004: case 0x400C: {
        apu.len[ch].halt = (val >> 5) & 1;
        struct envelope *e = ch == 3 ? &apu.noise.env : &apu.pulse[ch].env;
        e->loop = (val >> 5) & 1;
        e->constant = (val >> 4) & 1;
        e->period = val & 15;
        if (ch < 2) apu.pulse[ch].duty = val >> 6;
        break;
    }
    case 0x4001: case 0x4005: {
        struct pulse *p = &apu.pulse[ch];
        p->sweep_enabled = val >> 7;
        p->sweep_period = (val >> 4) & 7;
        p->sweep_negate = (val >> 3) & 1;
        p->sweep_shift = val & 7;
        p->sweep_reload = 1;
        break;
    }
    case 0x4002: case 0x4006:
        apu.pulse[ch].period = (uint16_t)((apu.pulse[ch].period & 0x700) | val);
        break;
    case 0x4008:
        apu.len[2].halt = val >> 7;
        apu.tri.control = val >> 7;
        apu.tri.linear_period = val & 0x7F;
        break;
    case 0x400A:
        apu.tri.period = (uint16_t)((apu.tri.period & 0x700) | val);
        break;
    case 0x400E:
        apu.noise.mode = val >> 7;
        apu.noise.period = noise_periods[val & 15];
        break;
    case 0x4011:
        apu.dmc_level = val & 0x7F;
        break;
    case 0x4003: case 0x4007: case 0x400B: case 0x400F:
        /* A reload on the very cycle the counter was clocked down from a
           non-zero value is lost. */
        if (apu.len[ch].enabled && apu.len[ch].clocked_at != when)
            apu.len[ch].counter = length_table[val >> 3];
        if (ch < 2) {
            struct pulse *p = &apu.pulse[ch];
            p->period = (uint16_t)((p->period & 0xFF) | (val & 7) << 8);
            p->step = 0;
            p->env.start = 1;
        } else if (ch == 2) {
            apu.tri.period = (uint16_t)((apu.tri.period & 0xFF) | (val & 7) << 8);
            apu.tri.linear_reload = 1;
        } else {
            apu.noise.env.start = 1;
        }
        break;
    case 0x4010:
        apu.dmc_irq_enabled = (val >> 7) & 1;
        apu.dmc_loop = (val >> 6) & 1;
        apu.dmc_rate = dmc_rates[val & 15];
        dmc_update_due();
        if (!apu.dmc_irq_enabled) { apu.dmc_irq = 0; update_irq_line(); }
        break;
    case 0x4012: apu.dmc_start_addr = (uint16_t)(0xC000 | val << 6); break;
    case 0x4013: apu.dmc_start_len = (uint16_t)(val << 4 | 1); break;
    case 0x4015:
        for (int i = 0; i < 4; i++) {
            apu.len[i].enabled = (val >> i) & 1;
            if (!apu.len[i].enabled) apu.len[i].counter = 0;
        }
        apu.dmc_irq = 0;            /* cleared first: a restart may set it */
        if (!(val & 0x10)) { apu.dmc_remaining = 0; dmc_dma_requested = 0; }
        else if (!apu.dmc_remaining) {
            dmc_restart();
            dmc_request(when + DMA_START_DELAY, 1);
        }
        update_irq_line();
        break;
    case 0x4017:
        /* Takes effect a few CPU cycles later, one more on odd cycles
           (the APU runs at half the CPU's rate). */
        apu.pending_mode = val;
        last_4017 = val;
        apu.pending_reset_at = when + FRAME_RESET_DELAY + (when & 1);
        apu.reset_pending = 1;
        apu.irq_inhibit = (val >> 6) & 1;
        if (apu.irq_inhibit) { apu.frame_irq = 0; update_irq_line(); }
        break;
    }
    dmc_update_due();               /* a restart may make a DMA due */
    apu_schedule();
}

/* The first cycle at or after c that is a get (parity GET_PARITY) or a
   put (the other). */
static uint64_t at_parity(uint64_t c, int parity) {
    return c + ((int)(c & 1) != parity);
}

/* The first cycle at or after `from` where the pending DMA tries to halt
   the CPU: a put cycle for a reload, a get cycle for a load. */
static uint64_t dmc_first_halt(uint64_t from) {
    uint64_t first = dmc_dma_request_at - DMA_READ_AT;  /* as a CPU cycle */
    if (first < from) first = from;
    return at_parity(first, dmc_dma_load ? GET_PARITY : !GET_PARITY);
}

/* The sample fetch itself, on cycle `at`. */
static void dmc_do_fetch(uint64_t at) {
    if (at > apu.now) run_until(at);
    dmc_dma_requested = 0;
    clock_now = at;
    dmc_fetch();
    dmc_update_due();
}

/* Called on every CPU read of $2000-$401F at or after dmc_dma_due (with
   the address), and at instruction boundaries (with 0). The DMA follows
   the hardware's rules:
   - It first tries to halt the CPU on a put cycle (reload) or a get
     cycle (load), at or after the request.
   - The CPU can only be halted on a read cycle; on a write cycle it tries
     again on the next cycle. Which cycles of the instruction are writes
     comes from its cycle map (cycles.c).
   - Then: the halt cycle, a dummy cycle, an alignment cycle if needed,
     and the fetch on a get cycle. 3 or 4 cycles in all.
   - The halted CPU keeps repeating its read, which a register sees. */
void apu_dma_point(uint16_t read_addr) {
    uint64_t now = cycles + DMA_READ_AT;
    if (now > apu.now) run_until(now);  /* the output unit may only now ask */
    if (!dmc_dma_requested || dmc_dma_request_at > now) {
        dmc_update_due();
        return;
    }
    /* Not before this instruction: a boundary event can't come earlier
       than its start. */
    uint64_t halt = dmc_first_halt(insn_start);
    /* At a boundary the instruction is over, so its write cycles are
       known; during a register read, every earlier cycle was a read. */
    while (!read_addr && halt < cycles && insn_writes_at(halt, cycles)) halt++;
    if (read_addr && halt > cycles) {
        dmc_update_due();                   /* lands after this read */
        return;
    }
    int repeat = read_addr && halt == cycles;
    uint64_t stall = at_parity(halt + 2, GET_PARITY) - halt + 1;
    /* Halting the instruction's last cycle (a register read that ends a
       load, or at a boundary the last cycle or the next opcode fetch)
       comes after its interrupt decision. */
    const char *m = cycle_map[peek(insn_pc)];
    if (read_addr ? (repeat && m && m[strlen(m) - 1] == 'r') : halt + 1 >= cycles)
        cpu_late_stall(stall);
    dmc_dma_requested = 0;
    dmc_dma_due = UINT64_MAX;       /* no DMA inside the extra reads below */
    if (repeat) {
        /* The halted CPU keeps reading its address, until the fetch. A
           controller only shifts once for back-to-back reads; $2007 sees
           each one. */
        int extra = (read_addr == 0x4016 || read_addr == 0x4017) ? 1 : (int)stall - 1;
        for (int i = 0; i < extra; i++) (void)rd(read_addr);
    }
    cycles += stall;
    clock_now = cycles;
    dmc_fetch();
    dmc_update_due();
    apu_schedule();
}

/* Sprite DMA: a write to $4014 at `cycles` (the write's own cycle).
   Returns the cycle the CPU carries on from. Cycle by cycle:
   - The CPU halts on the cycle after the write, waits for a get cycle,
     then 256 times reads a byte (get) and writes it to OAM (put): 513
     or 514 cycles in all.
   - A DMC fetch whose halt would land on an earlier read cycle of the
     same instruction happens first, as a normal DMC DMA (3 or 4 cycles).
   - Otherwise the CPU is already halted, so the DMC only needs its fetch
     on a get cycle at least two cycles after it tries to halt. Inside the
     copy it takes over one of the copy's gets, which then waits for the
     next one: 2 more cycles. Right at the end it adds 1 or 3.
   blargg's sprdma_and_dmc_dma tests check each case; the copy itself is
   done by the caller. */
uint64_t apu_oam_dma(void) {
    uint64_t w = cycles;
    uint64_t now = w + DMA_READ_AT;
    if (now > apu.now) run_until(now);
    if (dmc_dma_requested && dmc_dma_request_at <= now) {
        uint64_t halt = dmc_first_halt(insn_start);
        if (halt < w) {                     /* a read before the write */
            uint64_t stall = at_parity(halt + 2, GET_PARITY) - halt + 1;
            w += stall;
            dmc_do_fetch(halt + stall - 1);
        }
    }
    uint64_t end = at_parity(w + 2, GET_PARITY) + 512;  /* first cycle after */
    for (;;) {
        if (!dmc_dma_requested) {
            /* The output unit may ask for a byte during the copy. */
            if (dmc_dma_due >= end + DMA_READ_AT) break;
            if (dmc_dma_due > apu.now) run_until(dmc_dma_due);
            if (!dmc_dma_requested) break;
        }
        uint64_t halt = dmc_first_halt(w + 1);
        if (halt >= end) break;             /* after the copy: the CPU's again */
        uint64_t get = at_parity(halt + 2, GET_PARITY);
        if (get < end) end += 2;            /* takes one of the copy's gets */
        else end = get + 1;                 /* runs past the end */
        dmc_do_fetch(get);
    }
    cpu_late_stall(end - (w + 1));          /* all of it after the write */
    clock_now = end;
    dmc_update_due();
    apu_schedule();
    return end;
}

/* The reset button. $4015 is cleared (silencing everything and stopping
   the DMC), the frame IRQ flag is cleared, and the last value written to
   $4017 is written again a few cycles before the program restarts.
   Tuned with the apu_reset tests. */
#define RESET_4017_LEAD 2

void apu_soft_reset(void) {
    apu_catch_up();
    clock_now = cycles;
    for (int i = 0; i < 4; i++) { apu.len[i].enabled = 0; apu.len[i].counter = 0; }
    /* "Length counters enabled, triangle unaffected": the pulse and noise
       halt flags are cleared, the triangle's isn't. */
    apu.len[0].halt = apu.len[1].halt = apu.len[3].halt = 0;
    apu.dmc_remaining = 0;
    dmc_dma_requested = 0;
    apu.dmc_irq = 0;
    apu.frame_irq = 0;
    apu.pending_mode = last_4017;
    apu.irq_inhibit = (last_4017 >> 6) & 1;
    apu.pending_reset_at = cycles + RESET_4017_LEAD;
    apu.reset_pending = 1;
    update_irq_line();
    dmc_update_due();
}

uint8_t apu_read_status(void) {
    apu_catch_up();
    clock_now = cycles;
    uint8_t s = 0;
    for (int i = 0; i < 4; i++)
        if (apu.len[i].counter) s |= (uint8_t)(1 << i);
    if (apu.dmc_remaining) s |= 0x10;
    if (apu.frame_irq) s |= 0x40;
    if (apu.dmc_irq) s |= 0x80;
    apu.frame_irq = 0;                      /* reading clears the frame IRQ */
    update_irq_line();
    apu_schedule();                         /* so the next one isn't missed */
    return s;
}

void apu_reset(void) {
    apu.noise.shift = 1;
    apu.noise.period = noise_periods[0];
    apu.dmc_rate = dmc_rates[0];
    apu.dmc_next_bit = apu.dmc_rate;
    apu.dmc_start_len = 1;
    apu.now = 0;
    /* At power the frame counter behaves as if $4017 = 0 was written just
       before the program starts. */
    apu.pending_mode = 0;
    apu.pending_reset_at = 0;
    apu.reset_pending = 1;
    apu.frame_start = 0;
}
