/* nesrecomp's recompiler, in C (PLAN-standalone.md step 2): the same
   program as recomp.py, which stays as the reference it is checked
   against (tests/check_recomp.py).

       nesrecomp-recomp game.nes -o build/game.c [--entry C000 ...]
                        [--missed game.nes.missed ...]

   rom.c reads the file, this finds the entry points, gen.c follows the
   code from them and writes the C (ops.c has the opcodes). --dump-rom
   prints what was read, as recomp.py --dump-rom does. */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "gen.h"
#include "ops.h"
#include "rom.h"

#define MAX_ENTRIES 65536

/* Where a path's last folder ends: its last '/', and on Windows its last
   '\\' too (a Mac file name may hold a '\\', as recomp.py takes it).
   NULL if neither. */
static const char *last_sep(const char *path) {
    const char *s = strrchr(path, '/');
#ifdef _WIN32
    const char *b = strrchr(path, '\\');
    if (b && (!s || b > s)) s = b;
#endif
    return s;
}

/* The CRC-32 zlib's crc32 (and Python's zlib.crc32) computes, for
   --dump-rom's checksums: the recompiler's own, so it needs no zlib (which
   Windows doesn't have; PLAN-windows.md step 1). */
static unsigned long crc32_of(const void *data, size_t n) {
    static uint32_t table[256];
    if (!table[1])
        for (uint32_t i = 0; i < 256; i++) {
            uint32_t c = i;
            for (int k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            table[i] = c;
        }
    uint32_t c = 0xFFFFFFFFu;
    const unsigned char *p = data;
    for (size_t i = 0; i < n; i++) c = table[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return (unsigned long)(c ^ 0xFFFFFFFFu);
}

static const char *prog = "nesrecomp-recomp";

static void usage_error(const char *msg) {
    fprintf(stderr, "usage: %s [-h] [-o OUT] [--entry ENTRY] [--missed MISSED] rom\n", prog);
    fprintf(stderr, "%s: error: %s\n", prog, msg);
    exit(2);
}

static void help(void) {
    printf("usage: %s [-h] [-o OUT] [--entry ENTRY] [--missed MISSED] rom\n\n"
           "nesrecomp - a static recompiler for NES (6502) programs (the C version\n"
           "of recomp.py).\n\n"
           "  -o, --out OUT      the C file to write\n"
           "  --entry ENTRY      extra entry point in hex (e.g. C000)\n"
           "  --missed MISSED    file of addresses a previous run had to interpret;\n"
           "                     they become entry points for native translation\n"
           "  --listing FILE     also write each instruction's 6502 text and the lines\n"
           "                     of the C it became (the C itself is the same)\n", prog);
    exit(0);
}

/* A hex number as Python's int(s, 16) takes it: spaces around, a sign,
   an optional 0x. Returns 0 if it isn't one. */
static int parse_hex(const char *s, long *out) {
    while (*s == ' ' || *s == '\t' || *s == '\r' || *s == '\n') s++;
    if (!*s) return 0;
    errno = 0;
    char *end;
    long v = strtol(s, &end, 16);
    if (end == s || errno) return 0;
    while (*end == ' ' || *end == '\t' || *end == '\r' || *end == '\n') end++;
    if (*end) return 0;
    *out = v;
    return 1;
}

static long pymod(long a, long n) {
    long m = a % n;
    return m < 0 ? m + n : m;
}

static int ent_bank[MAX_ENTRIES];
static long ent_addr[MAX_ENTRIES];
static int n_ent;

static void add_entry(int bank, long addr) {
    if (n_ent >= MAX_ENTRIES) { fprintf(stderr, "too many entry points\n"); exit(1); }
    ent_bank[n_ent] = bank;
    ent_addr[n_ent++] = addr;
}

static void slots(const char *name, const struct rom *r, const int *v) {
    printf("%s", name);
    int first = 1;
    for (int s = 0; s < r->nslots; s++)
        if (v[s] != NO_BANK) { printf("%s%d:%d", first ? " " : " ", s, v[s]); first = 0; }
    if (first) printf(" ");
    printf("\n");
}

static void dump_rom(const struct rom *r) {
    if (!r->is_nsf && !r->is_fds) {
        const struct header *h = &r->header;
        printf("header battery=%d chr_nvram=%lld chr_ram=%lld chr_size=%lld console=%d "
               "console_ext=%d exp_device=%d mapper=%d misc_roms=%d nes2=%d prg_nvram=%lld "
               "prg_ram=%lld prg_size=%lld submapper=%d timing=%d trainer=%d\n",
               h->battery, (long long)h->chr_nvram, (long long)h->chr_ram,
               (long long)h->chr_size, h->console, h->console_ext, h->exp_device, h->mapper,
               h->misc_roms, h->nes2, (long long)h->prg_nvram, (long long)h->prg_ram,
               (long long)h->prg_size, h->submapper, h->timing, h->trainer);
    }
    printf("mapper %d %s\n", r->mapper, r->mapper_name);
    if (r->unit) printf("unit %d\n", r->unit); else printf("unit none\n");
    printf("slot_bits %d banks %d ram_top %04X high_writes %d\n", r->slot_bits, r->banks,
           r->ram_top, r->high_writes);
    if (r->low_lo >= 0) printf("low_regs %04X-%04X\n", r->low_lo, r->low_hi);
    else printf("low_regs none\n");
    slots("power_on", r, r->power_on);
    slots("fixed", r, r->fixed);
    printf("prg %zu %08lX\n", r->prg_len, crc32_of(r->prg, r->prg_len));
    if (r->is_nsf)
        printf("nsf load=%04X init=%04X play=%04X chips=%d\n", r->nsf_load, r->nsf_init,
               r->nsf_play, r->nsf_chips);
    else printf("nsf none\n");
    printf("inline ");
    for (int i = 0; i < r->n_inline; i++) {
        if (r->inline_count[i] < 0) printf("%s%04X:none", i ? " " : "", r->inline_addr[i]);
        else printf("%s%04X:%d", i ? " " : "", r->inline_addr[i], r->inline_count[i]);
    }
    printf("\n");
    printf("guarded %d\n", rom_guarded(r));
    if (r->is_fds) {
        printf("files_count %d\n", r->files_count);
        for (int t = 0; t < 256; t++)
            if (r->has_file[t])
                printf("file %d %04X %d %08lX\n", t, r->files[t].lo, r->files[t].len,
                       crc32_of(r->files[t].data, (size_t)r->files[t].len));
        printf("boot_ram %08lX boot_owner %08lX\n", crc32_of(r->boot_ram, sizeof r->boot_ram),
               crc32_of(r->boot_owner, sizeof r->boot_owner));
    }
    printf("entries ");
    for (int i = 0; i < n_ent; i++) printf("%s%02X:%04lX", i ? " " : "", ent_bank[i], ent_addr[i]);
    printf("\n");
}

/* The value of an option: after '=', the rest of "-oFILE", or the next
   argument. */
static const char *value(int argc, char **argv, int *i, const char *inline_val,
                         const char *label) {
    if (inline_val) return inline_val;
    if (*i + 1 >= argc) {
        char msg[96];
        snprintf(msg, sizeof msg, "argument %s: expected one argument", label);
        usage_error(msg);
    }
    return argv[++*i];
}

int main(int argc, char **argv) {
    const char *rom_path = NULL, *out = NULL, *listing = NULL;
    const char *entries[256], *missed[256];
    int n_entries = 0, n_missed = 0, dump = 0;
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        char msg[300];
        if (!strcmp(a, "-h")) help();
        if (!strncmp(a, "--", 2) && a[2]) {
            /* A long option, or an abbreviation of one as argparse allows
               (--ent for --entry), with its value after '=' or next. */
            size_t n = strcspn(a, "=");
            const char *eq = a[n] == '=' ? a + n + 1 : NULL;
            static const char *names[] = { "--out", "--entry", "--missed", "--dump-rom", "--help",
                                           "--listing" };
            int which = -1;
            for (int k = 0; k < 6; k++)
                if (n <= strlen(names[k]) && !strncmp(a, names[k], n)) which = k;
            if (which < 0 || ((which == 3 || which == 4) && eq)) {
                snprintf(msg, sizeof msg, "unrecognized arguments: %s", a);
                usage_error(msg);
            }
            if (which == 0) out = value(argc, argv, &i, eq, "-o/--out");
            else if (which == 1) {
                const char *v = value(argc, argv, &i, eq, "--entry");
                if (n_entries < 256) entries[n_entries++] = v;
            } else if (which == 2) {
                const char *v = value(argc, argv, &i, eq, "--missed");
                if (n_missed < 256) missed[n_missed++] = v;
            } else if (which == 3) dump = 1;
            else if (which == 5) listing = value(argc, argv, &i, eq, "--listing");
            else help();
            continue;
        }
        if (!strncmp(a, "-o", 2)) { out = value(argc, argv, &i, a[2] ? a + 2 : NULL, "-o/--out"); continue; }
        if (a[0] == '-' && a[1]) {
            snprintf(msg, sizeof msg, "unrecognized arguments: %s", a);
            usage_error(msg);
        }
        if (rom_path) {
            snprintf(msg, sizeof msg, "unrecognized arguments: %s", a);
            usage_error(msg);
        }
        rom_path = a;
    }
    if (!rom_path) usage_error("the following arguments are required: rom");
    if (!out && !dump) usage_error("the following arguments are required: -o/--out");

    ops_init();
    static struct rom rom;
    struct rom *r = &rom;
    rom_load(r, rom_path);

    /* The entry points, in recomp.py's order. */
    long vectors[3] = { rom_read16(r, 0xFFFA), rom_read16(r, 0xFFFC), rom_read16(r, 0xFFFE) };
    for (int i = 0; i < 3; i++) add_entry(rom_power_on_bank(r, vectors[i]), vectors[i]);
    if (r->is_nsf) {
        if (r->nsf_init >= 0x8000) add_entry(rom_power_on_bank(r, r->nsf_init), r->nsf_init);
        if (r->nsf_play >= 0x8000) add_entry(rom_power_on_bank(r, r->nsf_play), r->nsf_play);
    }
    if (r->is_fds) {
        int b[5];
        long ad[5];
        int n = rom_fds_entries(r, b, ad);
        for (int i = 0; i < n; i++) add_entry(b[i], ad[i]);
    }
    for (int i = 0; i < n_entries; i++) {
        long v;
        if (!parse_hex(entries[i], &v)) {
            fprintf(stderr, "invalid entry point: %s\n", entries[i]);
            return 1;
        }
        add_entry(rom_power_on_bank(r, v), v);
    }
    for (int i = 0; i < n_missed; i++) {
        FILE *f = fopen(missed[i], "r");
        if (!f) { fprintf(stderr, "%s: can't open the file\n", missed[i]); return 1; }
        char line[256];
        while (fgets(line, sizeof line, f)) {
            char *p = line, *e = line + strlen(line);
            while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
            while (e > p && (e[-1] == ' ' || e[-1] == '\t' || e[-1] == '\r' || e[-1] == '\n')) *--e = 0;
            if (!*p) continue;
            char *colon = strchr(p, ':');
            long b, a;
            if (colon) {                       /* BB:AAAA */
                *colon = 0;
                if (strchr(colon + 1, ':') || !parse_hex(p, &b) || !parse_hex(colon + 1, &a)) {
                    fprintf(stderr, "%s: a line that isn't BB:AAAA\n", missed[i]);
                    return 1;
                }
                add_entry((int)pymod(b, r->banks), a);
            } else {                           /* old format: AAAA */
                if (!parse_hex(p, &a)) {
                    fprintf(stderr, "%s: a line that isn't AAAA\n", missed[i]);
                    return 1;
                }
                add_entry(rom_power_on_bank(r, a), a);
            }
        }
        fclose(f);
    }
    int kept = 0;
    for (int i = 0; i < n_ent; i++)
        if (rom_translatable(r, ent_bank[i], ent_addr[i])) {
            ent_bank[kept] = ent_bank[i];
            ent_addr[kept++] = ent_addr[i];
        }
    n_ent = kept;

    if (dump) {
        dump_rom(r);
        return 0;
    }
    struct traced t;
    trace(r, ent_bank, ent_addr, n_ent, &t);
    /* As bytes: on Windows, a text file would get \r\n line ends, and the
       C must be the same on every system. */
    FILE *f = fopen(out, "wb");
    if (!f) { fprintf(stderr, "%s: can't write the file\n", out); return 1; }
    const char *src_name = last_sep(rom_path);
    FILE *lf = NULL;
    if (listing) {
        lf = fopen(listing, "wb");
        if (!lf) { fprintf(stderr, "%s: can't write the file\n", listing); return 1; }
        /* Its header: what it lists, and where the program starts. */
        /* The file names alone, not their folders: a listing is the same
           on every machine, and names no folder of the one it was made on. */
        const char *out_name = last_sep(out);
        fprintf(lf, "# nesrecomp listing of %s: each instruction's 6502 and the lines of %s\n"
                    "# it became: BB:AAAA, first line, last line, bytes, 6502\n",
                src_name ? src_name + 1 : rom_path, out_name ? out_name + 1 : out);
        static const char *const vname[3] = { "nmi", "reset", "irq" };
        if (!r->is_nsf && !r->is_fds)
            for (int i = 0; i < 3; i++)
                fprintf(lf, "# %s %02X:%04lX\n", vname[i], rom_power_on_bank(r, vectors[i]), vectors[i]);
        if (r->is_nsf)
            fprintf(lf, "# init %02X:%04X\n# play %02X:%04X\n", rom_power_on_bank(r, r->nsf_init),
                    r->nsf_init, rom_power_on_bank(r, r->nsf_play), r->nsf_play);
        for (int i = 0; i < n_ent; i++) fprintf(lf, "# entry %02X:%04lX\n", ent_bank[i], ent_addr[i]);
    }
    generate(f, r, &t, src_name ? src_name + 1 : rom_path, lf);
    if (fclose(f)) { fprintf(stderr, "%s: can't write the file\n", out); return 1; }
    if (lf && fclose(lf)) { fprintf(stderr, "%s: can't write the file\n", listing); return 1; }

    if (r->is_fds) {
        int nfiles = 0;
        for (int i = 0; i < 256; i++) nfiles += r->has_file[i];
        printf("FDS disk image, %d file(s): the BIOS and %d PRG file(s) in RAM can be translated\n",
               r->files_count, nfiles);
    } else if (!r->is_nsf) {
        printf("mapper %d (%s), %zu KB program ROM\n", r->mapper, r->mapper_name, r->prg_len / 1024);
    }
    if (r->is_nsf)
        printf("NSF: load=%04X init=%04X play=%04X\n", r->nsf_load, r->nsf_init, r->nsf_play);
    else
        printf("vectors: NMI=%04lX RESET=%04lX IRQ=%04lX\n", vectors[0], vectors[1], vectors[2]);
    long banks = 0;
    for (long i = 0; i < t.n_insns; i++)        /* sorted by bank: count the changes */
        if (i == 0 || t.insns[i].bank != t.insns[i - 1].bank) banks++;
    printf("translated %ld instructions in %ld bank(s) -> %s\n", t.n_insns, banks, out);
    if (t.n_unknown) {
        printf("stopped at %ld untranslatable spot(s):", t.n_unknown);
        for (long i = 0; i < t.n_unknown; i++)
            printf(" %02X:%04lX", t.unknown_bank[i], t.unknown_addr[i]);
        printf("\n");
    }
    return 0;
}
