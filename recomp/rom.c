/* nesrecomp's recompiler, in C: reading a ROM (see rom.h). Each part
   follows recomp.py's of the same name; the comments there say why. */
#include "rom.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../runtime/fds_bios.h"     /* the project's FDS BIOS, 8 KB */

#define NOT_FIXED 99                 /* a slot that switches (not in "fixed") */

/* recomp.py's MAPPERS, in number order (the order its message lists
   them in). unit 0 is None: program ROM never moves. */
static const struct mapper {
    int number;
    const char *name;
    int unit;
    int fixed[4];                    /* slot -> bank, negative from the end */
    int power_on[4];
    int low_lo, low_hi;
} mappers[] = {
    { 0, "NROM", 0, { 0 }, { 0 }, -1, -1 },
    { 1, "MMC1", 2, { NOT_FIXED, NOT_FIXED, NOT_FIXED, NOT_FIXED }, { 0, 1, -2, -1 }, -1, -1 },
    { 2, "UxROM", 2, { NOT_FIXED, NOT_FIXED, -2, -1 }, { 0, 1, -2, -1 }, -1, -1 },
    { 3, "CNROM", 0, { 0 }, { 0 }, -1, -1 },
    { 4, "MMC3", 1, { NOT_FIXED, NOT_FIXED, NOT_FIXED, -1 }, { 0, 1, -2, -1 }, -1, -1 },
    { 5, "MMC5", 1, { NOT_FIXED, NOT_FIXED, NOT_FIXED, NOT_FIXED }, { -1, -1, -1, -1 },
      0x5100, 0x5117 },
    { 7, "AxROM", 4, { NOT_FIXED, NOT_FIXED, NOT_FIXED, NOT_FIXED }, { 0, 1, 2, 3 }, -1, -1 },
    { 9, "MMC2", 1, { NOT_FIXED, -3, -2, -1 }, { 0, -3, -2, -1 }, -1, -1 },
    { 10, "MMC4", 2, { NOT_FIXED, NOT_FIXED, -2, -1 }, { 0, 1, -2, -1 }, -1, -1 },
    { 11, "Color Dreams", 4, { NOT_FIXED, NOT_FIXED, NOT_FIXED, NOT_FIXED }, { 0, 1, 2, 3 }, -1, -1 },
    { 19, "Namco 163", 1, { NOT_FIXED, NOT_FIXED, NOT_FIXED, -1 }, { 0, 1, 2, -1 }, -1, -1 },
    { 21, "VRC4", 1, { NOT_FIXED, NOT_FIXED, NOT_FIXED, -1 }, { 0, 1, -2, -1 }, -1, -1 },
    { 22, "VRC2", 1, { NOT_FIXED, NOT_FIXED, NOT_FIXED, -1 }, { 0, 1, -2, -1 }, -1, -1 },
    { 23, "VRC4", 1, { NOT_FIXED, NOT_FIXED, NOT_FIXED, -1 }, { 0, 1, -2, -1 }, -1, -1 },
    { 24, "VRC6", 1, { NOT_FIXED, NOT_FIXED, NOT_FIXED, -1 }, { 0, 1, -2, -1 }, -1, -1 },
    { 25, "VRC4", 1, { NOT_FIXED, NOT_FIXED, NOT_FIXED, -1 }, { 0, 1, -2, -1 }, -1, -1 },
    { 26, "VRC6", 1, { NOT_FIXED, NOT_FIXED, NOT_FIXED, -1 }, { 0, 1, -2, -1 }, -1, -1 },
    { 28, "Action 53", 2, { NOT_FIXED, NOT_FIXED, NOT_FIXED, NOT_FIXED }, { -4, -3, -2, -1 }, -1, -1 },
    { 34, "BNROM", 4, { NOT_FIXED, NOT_FIXED, NOT_FIXED, NOT_FIXED }, { 0, 1, 2, 3 }, -1, -1 },
    { 41, "Caltron 6-in-1", 4, { NOT_FIXED, NOT_FIXED, NOT_FIXED, NOT_FIXED }, { 0, 1, 2, 3 },
      0x6000, 0x67FF },
    { 66, "GxROM", 4, { NOT_FIXED, NOT_FIXED, NOT_FIXED, NOT_FIXED }, { 0, 1, 2, 3 }, -1, -1 },
    { 69, "FME-7", 1, { NOT_FIXED, NOT_FIXED, NOT_FIXED, -1 }, { 0, 1, 2, -1 }, -1, -1 },
    { 71, "Camerica", 2, { NOT_FIXED, NOT_FIXED, -2, -1 }, { 0, 1, -2, -1 }, -1, -1 },
    { 79, "NINA-03/06", 4, { NOT_FIXED, NOT_FIXED, NOT_FIXED, NOT_FIXED }, { 0, 1, 2, 3 },
      0x4100, 0x5FFF },
    { 85, "VRC7", 1, { NOT_FIXED, NOT_FIXED, NOT_FIXED, -1 }, { 0, 1, 2, -1 }, -1, -1 },
    { 172, "TXC 172", 0, { 0 }, { 0 }, -1, -1 },
    { 228, "Active Enterprises", 2, { NOT_FIXED, NOT_FIXED, NOT_FIXED, NOT_FIXED }, { 0, 1, 2, 3 },
      -1, -1 },
    { NSF_MAPPER, "NSF", 0, { 0 }, { 0 }, -1, -1 },
    { FDS_MAPPER, "FDS", 0, { 0 }, { 0 }, -1, -1 },
};
#define N_MAPPERS (int)(sizeof mappers / sizeof mappers[0])

/* FDS BIOS routines that take pointers after the JSR: recomp.py's
   FDS_INLINE_POINTERS (-1: None, it never returns there). */
static const int fds_inline[][2] = {
    { 0xE1F8, 2 }, { 0xE237, 2 }, { 0xE239, 2 }, { 0xE2B7, 1 }, { 0xE2BB, 1 },
    { 0xE301, 1 }, { 0xE305, 1 }, { 0xE32A, 1 },
    { 0xE7BB, 1 }, { 0xE8D2, 1 }, { 0xE8E1, 1 }, { 0xEAFD, -1 },
};

/* Python's a % n, which is never negative for a positive n. */
static long pymod(long a, long n) {
    long m = a % n;
    return m < 0 ? m + n : m;
}

static void die(const char *fmt, ...) __attribute__((format(printf, 1, 2), noreturn));
#include <stdarg.h>
static void die(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    exit(1);
}

/* An NES 2.0 ROM size: LSB and 4-bit MSB in units, or the exponent form.
   Returns -1 with *why set when too large. */
static int64_t rom_size(int lsb, int msb, int64_t unit, char *why, size_t n) {
    if (msb == 0xF) {
        int e = lsb >> 2, mm = lsb & 3;
        if (e > 30) { snprintf(why, n, "ROM size 2^%d bytes is too large", e); return -1; }
        return ((int64_t)1 << e) * (mm * 2 + 1);
    }
    return (int64_t)(msb << 8 | lsb) * unit;
}

static int64_t ram_size(int shift) { return shift ? (int64_t)64 << shift : 0; }

/* recomp.py's read_header. Returns 0, or 1 with the reason in why. */
static int read_header(const uint8_t *data, size_t len, struct header *f, char *why, size_t n) {
    uint8_t h[16];
    if (len < 16) {
        snprintf(why, n, "truncated: the file is shorter than its header says");
        return 1;
    }
    memcpy(h, data, 16);
    memset(f, 0, sizeof *f);
    f->battery = (h[6] & 2) != 0;
    f->trainer = (h[6] & 4) != 0;
    int64_t head = 16 + (f->trainer ? 512 : 0), prg = 0, chr = 0;
    int nes2 = (h[7] & 0x0C) == 0x08;
    if (nes2) {
        prg = rom_size(h[4], h[9] & 0x0F, 0x4000, why, n);
        if (prg < 0) return 1;
        chr = rom_size(h[5], h[9] >> 4, 0x2000, why, n);
        if (chr < 0) return 1;
        if (head + prg + chr > (int64_t)len) nes2 = 0;
    }
    int clean = nes2 || !(h[12] | h[13] | h[14] | h[15]);
    f->nes2 = nes2;
    f->mapper = (h[6] >> 4) | (h[7] & 0xF0);
    f->console = clean ? h[7] & 3 : 0;
    if (nes2) {
        f->mapper |= (h[8] & 0x0F) << 8;
        f->submapper = h[8] >> 4;
        f->prg_size = prg;
        f->chr_size = chr;
        f->prg_ram = ram_size(h[10] & 0x0F);
        f->prg_nvram = ram_size(h[10] >> 4);
        f->chr_ram = ram_size(h[11] & 0x0F);
        f->chr_nvram = ram_size(h[11] >> 4);
        f->timing = h[12] & 3;
        f->misc_roms = h[14] & 3;
        f->exp_device = h[15] & 0x7F;
        f->console_ext = (f->console == 1 || f->console == 3) ? h[13] : 0;
    } else {
        if (!clean) f->mapper &= 0x0F;
        f->prg_size = h[4] * 0x4000;
        f->chr_size = h[5] * 0x2000;
        f->prg_ram = f->battery ? 0 : 0x2000;
        f->prg_nvram = f->battery ? 0x2000 : 0;
        f->chr_ram = h[5] == 0 ? 0x2000 : 0;
        f->chr_nvram = 0;
    }
    if (head + f->prg_size + f->chr_size > (int64_t)len) {
        snprintf(why, n, "truncated: the file is shorter than its header says");
        return 1;
    }
    if (f->prg_size == 0) { snprintf(why, n, "header lists no PRG ROM"); return 1; }
    if (f->prg_size % 0x2000) {
        snprintf(why, n, "PRG ROM of %lld bytes is not a whole number of 8 KB banks",
                 (long long)f->prg_size);
        return 1;
    }
    if (f->chr_size % 0x400) {
        snprintf(why, n, "CHR ROM of %lld bytes is not a whole number of 1 KB banks",
                 (long long)f->chr_size);
        return 1;
    }
    return 0;
}

static void nrom_layout(struct rom *r) {
    r->nslots = 4;
    for (int s = 0; s < 4; s++) r->power_on[s] = r->fixed[s] = (int)pymod(s, r->banks);
}

static void load_nsf(struct rom *r) {
    const uint8_t *h = r->data;
    if (r->size < 0x80) die("NSF header is cut short");
    r->is_nsf = 1;
    r->nsf_load = h[8] | h[9] << 8;
    r->nsf_init = h[10] | h[11] << 8;
    r->nsf_play = h[12] | h[13] << 8;
    r->nsf_chips = h[0x7B] & 0x3F;
    r->mapper = NSF_MAPPER;
    r->mapper_name = "NSF";
    int chips = r->nsf_chips, any = 0;
    for (int i = 0; i < 8; i++) any |= h[0x70 + i];
    const uint8_t *body = r->data + 0x80;
    size_t blen = r->size - 0x80;
    if (any) {
        size_t off = r->nsf_load & 0xFFF;
        size_t size = (off + blen + 0xFFF) & ~(size_t)0xFFF;
        if (size == 0) die("NSF has no program");
        r->prg = calloc(size, 1);
        memcpy(r->prg + off, body, blen);
        r->prg_len = size;
        r->slot_bits = 12;
        r->banks = (int)(size / 0x1000);
        r->unit = 1;
        r->nslots = 8;
        for (int s = 0; s < 8; s++) {
            r->fixed[s] = NO_BANK;
            r->power_on[s] = (int)pymod(h[0x70 + s], r->banks);
        }
        r->low_lo = 0x5FF8;
        r->low_hi = 0x5FFF;
        r->high_writes = 1;
        return;
    }
    long load = r->nsf_load, floor = chips & 4 ? 0x6000 : 0x8000;
    if (load < floor) die("NSF loads below $%04lX", floor);
    if (load < 0x8000) {
        size_t skip = (size_t)(0x8000 - load);
        if (skip > blen) skip = blen;
        body += skip;
        blen -= skip;
        load = 0x8000;
    }
    r->prg = calloc(0x8000, 1);
    if (blen > (size_t)(0x10000 - load)) blen = (size_t)(0x10000 - load);
    memcpy(r->prg + (load - 0x8000), body, blen);
    r->prg_len = 0x8000;
    r->slot_bits = 13;
    r->banks = 4;
    r->unit = 0;
    r->low_lo = r->low_hi = -1;
    r->high_writes = chips != 0;
    r->nslots = 4;
    for (int s = 0; s < 4; s++) r->power_on[s] = r->fixed[s] = s;
}

static void load_fds(struct rom *r, int has_header) {
    r->is_fds = 1;
    r->mapper = FDS_MAPPER;
    r->mapper_name = "FDS";
    r->prg = calloc(0x8000, 1);
    memcpy(r->prg + 0x6000, fds_bios, 0x2000);
    r->prg_len = 0x8000;
    r->slot_bits = 13;
    r->unit = 0;
    r->low_lo = r->low_hi = -1;
    r->high_writes = 0;
    r->nslots = 4;
    for (int s = 0; s < 4; s++) r->power_on[s] = r->fixed[s] = s;
    r->ram_top = 0xE000;
    r->n_inline = (int)(sizeof fds_inline / sizeof fds_inline[0]);
    for (int i = 0; i < r->n_inline; i++) {
        r->inline_addr[i] = fds_inline[i][0];
        r->inline_count[i] = fds_inline[i][1];
    }
    const uint8_t *body = r->data + (has_header ? 16 : 0);
    size_t blen = r->size - (has_header ? 16 : 0);
    int tag = FDS_FIRST_TAG;
    for (size_t n = 0; blen >= FDS_SIDE && n <= (blen - FDS_SIDE) / FDS_SIDE; n++) {
        const uint8_t *side = body + n * FDS_SIDE;
        /* fds_side_files */
        if (side[56] != 2) continue;
        int count = side[57], at = 58, got = 0;
        while (got < count && got < 256 && at + 17 <= FDS_SIDE && side[at] == 3) {
            const uint8_t *fh = side + at;
            int number = fh[1], id = fh[2], addr = fh[11] | fh[12] << 8;
            int size = fh[13] | fh[14] << 8, type = fh[15];
            (void)number;
            at += 16;
            if (side[at] != 4 || at + 1 + size > FDS_SIDE) break;
            const uint8_t *fdata = side + at + 1;
            at += 1 + size;
            got++;
            /* load_fds, for this file */
            int t = tag <= 255 ? tag : 0;
            tag++;
            if (type != 0) continue;
            int lo = addr > 0x6000 ? addr : 0x6000;
            int hi = addr + size < 0xE000 ? addr + size : 0xE000;
            if (t && lo < hi) {
                r->has_file[t] = 1;
                r->files[t].lo = lo;
                r->files[t].len = hi - lo;
                r->files[t].data = fdata + (lo - addr);
            }
            if (n == 0 && id <= side[0x19]) {
                for (int i = 0; i < size; i++) {
                    int a = (addr + i) & 0xFFFF;
                    if (a >= 0x6000 && a < 0xE000) {
                        r->boot_ram[a - 0x6000] = fdata[i];
                        r->boot_owner[a - 0x6000] = (uint8_t)t;
                    }
                }
            }
        }
    }
    r->banks = 256;
    r->files_count = tag - FDS_FIRST_TAG;
}

void rom_load(struct rom *r, const char *path) {
    memset(r, 0, sizeof *r);
    FILE *f = fopen(path, "rb");
    if (!f) die("%s: can't open the file", path);
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    r->data = malloc(len > 0 ? (size_t)len : 1);
    r->size = len > 0 && fread(r->data, 1, (size_t)len, f) == (size_t)len ? (size_t)len : 0;
    fclose(f);
    r->ram_top = 0x8000;
    r->low_lo = r->low_hi = -1;
    const uint8_t *d = r->data;
    if (r->size >= 5 && !memcmp(d, "NESM\x1a", 5)) { load_nsf(r); return; }
    if (r->size >= 4 && !memcmp(d, "FDS\x1a", 4)) { load_fds(r, 1); return; }
    if (r->size >= 15 && !memcmp(d, "\x01*NINTENDO-HVC*", 15)) { load_fds(r, 0); return; }
    if (r->size < 4 || memcmp(d, "NES\x1a", 4)) die("not an iNES, NSF or FDS file");
    char why[160];
    if (read_header(d, r->size, &r->header, why, sizeof why)) die("%s: %s", path, why);
    r->mapper = r->header.mapper;
    size_t start = 16 + (r->header.trainer ? 512 : 0);
    r->prg_len = (size_t)r->header.prg_size;
    r->prg = malloc(r->prg_len);
    memcpy(r->prg, d + start, r->prg_len);
    r->slot_bits = 13;
    r->banks = (int)(r->prg_len / 0x2000);
    const struct mapper *m = NULL;
    for (int i = 0; i < N_MAPPERS; i++)
        if (mappers[i].number == r->mapper) m = &mappers[i];
    if (!m) {
        char list[1024] = "";
        for (int i = 0; i < N_MAPPERS; i++) {
            char one[48];
            snprintf(one, sizeof one, "%s%d %s", i ? ", " : "", mappers[i].number, mappers[i].name);
            strncat(list, one, sizeof list - strlen(list) - 1);
        }
        die("mapper %d is not supported (supported: %s)", r->mapper, list);
    }
    r->mapper_name = m->name;
    r->unit = m->unit;
    int sub = r->header.submapper;
    if (r->mapper == 34 && sub == 1) die("mapper 34 submapper 1 (NINA-001) is not supported");
    r->high_writes = r->unit != 0;
    if (r->mapper == 1 && sub == 5) r->unit = 0;
    r->low_lo = m->low_lo;
    r->low_hi = m->low_hi;
    if (r->unit == 0) {
        nrom_layout(r);
    } else {
        r->nslots = 4;
        for (int s = 0; s < 4; s++) {
            r->power_on[s] = (int)pymod(m->power_on[s], r->banks);
            r->fixed[s] = m->fixed[s] == NOT_FIXED ? NO_BANK : (int)pymod(m->fixed[s], r->banks);
        }
        if (r->mapper == 1 && r->banks > 32) { r->power_on[2] = 30; r->power_on[3] = 31; }
    }
}

int rom_slot(const struct rom *r, long addr) {
    return (int)((addr >> r->slot_bits) & ((0x8000 >> r->slot_bits) - 1));
}

int rom_read(const struct rom *r, int bank, long addr) {
    if (r->is_fds && bank >= 0 && bank < 256 && r->has_file[bank])
        return r->files[bank].data[addr - r->files[bank].lo];
    long size = 1L << r->slot_bits;
    long at = (long)bank * size + (addr & (size - 1));
    if (at < 0 || (size_t)at >= r->prg_len) {
        fprintf(stderr, "internal error: read outside the program ROM (bank %d, $%04lX)\n",
                bank, addr);
        exit(1);
    }
    return r->prg[at];
}

int rom_read16(const struct rom *r, long addr) {
    int b = r->power_on[rom_slot(r, addr)];
    return rom_read(r, b, addr) | rom_read(r, b, addr + 1) << 8;
}

static int in_file(const struct rom *r, int tag, long addr) {
    return addr >= r->files[tag].lo && addr < r->files[tag].lo + r->files[tag].len;
}

static int is_fixed(const struct rom *r, int slot) { return r->fixed[slot] != NO_BANK; }

int rom_resolve(const struct rom *r, int fbank, long faddr, long addr) {
    if (r->is_fds) {
        if (addr >= 0xE000) return 3;
        if (fbank >= 0 && fbank < 256 && r->has_file[fbank] && in_file(r, fbank, addr)) return fbank;
        return NO_BANK;
    }
    if (addr < r->ram_top) return NO_BANK;
    int s_from = rom_slot(r, faddr), s_to = rom_slot(r, addr);
    if (is_fixed(r, s_to)) return r->fixed[s_to];
    if (s_from == s_to) return fbank;
    if (r->unit && !is_fixed(r, s_from) && s_from / r->unit == s_to / r->unit)
        return (int)pymod(fbank + s_to - s_from, r->banks);
    return NO_BANK;
}

int rom_translatable(const struct rom *r, int bank, long addr) {
    if (r->is_fds) {
        if (bank >= 0 && bank < 256 && r->has_file[bank]) return in_file(r, bank, addr);
        return bank == 3 && addr >= 0xE000;
    }
    return addr >= r->ram_top;
}

int rom_guard_tag(const struct rom *r, int bank, long addr) {
    if (r->is_fds) return addr >= 0x6000 && addr < 0xE000 ? bank : -1;
    if (r->is_nsf && (r->nsf_chips & 4) && addr >= 0x8000 && addr < 0xE000) return 1;
    return -1;
}

int rom_guarded(const struct rom *r) { return r->is_fds || (r->is_nsf && (r->nsf_chips & 4)); }

int rom_switches(const struct rom *r, long addr) {
    return r->unit != 0 && !is_fixed(r, rom_slot(r, addr));
}

int rom_power_on_bank(const struct rom *r, long addr) { return r->power_on[rom_slot(r, addr)]; }

int rom_fds_entries(const struct rom *r, int *banks, long *addrs) {
    int n = 0;
    for (int v = 0xDFF6; v < 0xE000; v += 2) {
        int t = r->boot_ram[v - 0x6000] | r->boot_ram[v + 1 - 0x6000] << 8;
        if (t >= 0xE000) { banks[n] = 3; addrs[n++] = t; }
        else if (t >= 0x6000 && t < 0xE000 && r->boot_owner[t - 0x6000]) {
            banks[n] = r->boot_owner[t - 0x6000];
            addrs[n++] = t;
        }
    }
    return n;
}
