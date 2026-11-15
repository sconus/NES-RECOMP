/* nesrecomp's recompiler, in C (PLAN-standalone.md step 2): the same
   program as recomp.py, which stays as the reference it is checked
   against (tests/check_recomp.py).

       nesrecomp-recomp game.nes -o build/game.c [--entry C000 ...]
                        [--missed game.nes.missed ...]

   Step 2a reads the file and finds the entry points; --dump-rom prints
   what it read, as recomp.py --dump-rom does. Translating comes in
   step 2b. */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>
#include "rom.h"

#define MAX_ENTRIES 65536

static const char *prog = "recomp.py";

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
           "                     they become entry points for native translation\n", prog);
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
    printf("prg %zu %08lX\n", r->prg_len, crc32(0, r->prg, (uInt)r->prg_len));
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
                       crc32(0, r->files[t].data, (uInt)r->files[t].len));
        printf("boot_ram %08lX boot_owner %08lX\n", crc32(0, r->boot_ram, sizeof r->boot_ram),
               crc32(0, r->boot_owner, sizeof r->boot_owner));
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
    const char *rom_path = NULL, *out = NULL;
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
            static const char *names[] = { "--out", "--entry", "--missed", "--dump-rom", "--help" };
            int which = -1;
            for (int k = 0; k < 5; k++)
                if (n <= strlen(names[k]) && !strncmp(a, names[k], n)) which = k;
            if (which < 0 || (which >= 3 && eq)) {
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
    fprintf(stderr, "translating comes in step 2b: only --dump-rom for now\n");
    return 1;
}
