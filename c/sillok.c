/*
 * sillok.c — C implementation of .sillok encoder/decoder
 *
 * Compile: gcc -O2 -o sillok_c sillok.c
 * Usage:   sillok_c encode <input.txt> <output.sillok>
 *          sillok_c decode <input.sillok>
 *          sillok_c bench  <input.txt> <iterations>
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#endif

/* ============================================================
 * Bit buffer for writing
 * ============================================================ */

typedef struct {
    uint8_t *data;
    int capacity;
    int byte_pos;
    int bit_pos;   /* 0-7, next bit position within current byte */
    int total_bits;
} BitWriter;

void bw_init(BitWriter *bw, int initial_capacity) {
    bw->data = (uint8_t *)calloc(initial_capacity, 1);
    bw->capacity = initial_capacity;
    bw->byte_pos = 0;
    bw->bit_pos = 0;
    bw->total_bits = 0;
}

void bw_write_bit(BitWriter *bw, int bit) {
    if (bw->byte_pos >= bw->capacity) {
        bw->capacity *= 2;
        bw->data = (uint8_t *)realloc(bw->data, bw->capacity);
        memset(bw->data + bw->byte_pos, 0, bw->capacity - bw->byte_pos);
    }
    if (bit) {
        bw->data[bw->byte_pos] |= (1 << (7 - bw->bit_pos));
    }
    bw->bit_pos++;
    bw->total_bits++;
    if (bw->bit_pos == 8) {
        bw->bit_pos = 0;
        bw->byte_pos++;
    }
}

void bw_write_bits(BitWriter *bw, const char *code) {
    while (*code) {
        bw_write_bit(bw, *code == '1');
        code++;
    }
}

void bw_write_int(BitWriter *bw, int value, int width) {
    for (int i = width - 1; i >= 0; i--) {
        bw_write_bit(bw, (value >> i) & 1);
    }
}

void bw_free(BitWriter *bw) {
    free(bw->data);
}

/* ============================================================
 * Bit reader for decoding
 * ============================================================ */

typedef struct {
    const uint8_t *data;
    int total_bits;
    int pos;
} BitReader;

void br_init(BitReader *br, const uint8_t *data, int total_bits) {
    br->data = data;
    br->total_bits = total_bits;
    br->pos = 0;
}

int br_read_bit(BitReader *br) {
    if (br->pos >= br->total_bits) return -1;
    int byte_idx = br->pos / 8;
    int bit_idx = 7 - (br->pos % 8);
    br->pos++;
    return (br->data[byte_idx] >> bit_idx) & 1;
}

int br_read_int(BitReader *br, int width) {
    int val = 0;
    for (int i = 0; i < width; i++) {
        int bit = br_read_bit(br);
        if (bit < 0) return -1;
        val = (val << 1) | bit;
    }
    return val;
}

int br_remaining(BitReader *br) {
    return br->total_bits - br->pos;
}

/* ============================================================
 * Hangul decomposition/composition
 * ============================================================ */

#define HANGUL_BASE 0xAC00
#define ONSET_COUNT 19
#define VOWEL_COUNT 21
#define CODA_COUNT  28

void decompose_hangul(uint32_t cp, int *onset, int *vowel, int *coda) {
    int code = cp - HANGUL_BASE;
    *onset = code / (VOWEL_COUNT * CODA_COUNT);
    *vowel = (code % (VOWEL_COUNT * CODA_COUNT)) / CODA_COUNT;
    *coda  = code % CODA_COUNT;
}

uint32_t compose_hangul(int onset, int vowel, int coda) {
    return HANGUL_BASE + onset * VOWEL_COUNT * CODA_COUNT + vowel * CODA_COUNT + coda;
}

int is_hangul(uint32_t cp) {
    return cp >= 0xAC00 && cp <= 0xD7A3;
}

/* ============================================================
 * UTF-8 helpers
 * ============================================================ */

/* Read one UTF-8 codepoint, return bytes consumed */
int utf8_decode(const uint8_t *s, uint32_t *cp) {
    if (s[0] < 0x80) { *cp = s[0]; return 1; }
    if ((s[0] & 0xE0) == 0xC0) { *cp = ((s[0]&0x1F)<<6)|(s[1]&0x3F); return 2; }
    if ((s[0] & 0xF0) == 0xE0) { *cp = ((s[0]&0x0F)<<12)|((s[1]&0x3F)<<6)|(s[2]&0x3F); return 3; }
    if ((s[0] & 0xF8) == 0xF0) { *cp = ((s[0]&0x07)<<18)|((s[1]&0x3F)<<12)|((s[2]&0x3F)<<6)|(s[3]&0x3F); return 4; }
    *cp = '?'; return 1;
}

/* Write one UTF-8 codepoint, return bytes written */
int utf8_encode(uint8_t *out, uint32_t cp) {
    if (cp < 0x80) { out[0] = cp; return 1; }
    if (cp < 0x800) { out[0] = 0xC0|(cp>>6); out[1] = 0x80|(cp&0x3F); return 2; }
    if (cp < 0x10000) { out[0] = 0xE0|(cp>>12); out[1] = 0x80|((cp>>6)&0x3F); out[2] = 0x80|(cp&0x3F); return 3; }
    out[0] = 0xF0|(cp>>18); out[1] = 0x80|((cp>>12)&0x3F); out[2] = 0x80|((cp>>6)&0x3F); out[3] = 0x80|(cp&0x3F); return 4;
}

/* ============================================================
 * Huffman tables — hardcoded to match Python/Haskell exactly
 * ============================================================ */

/* Table 0: Word-length & control */
/* Symbols: 0=1-syl, 1=2-syl, 2=3-syl, 3=4-syl, 4=5-syl, 5=6-syl,
            6=7+-syl, 7=comma, 8=period, 9=middledot,
            10=number, 11=newline, 12=ascii_start, 13=section_sep */
#define T0_1SYL    0
#define T0_2SYL    1
#define T0_3SYL    2
#define T0_4SYL    3
#define T0_5SYL    4
#define T0_6SYL    5
#define T0_7PLUS   6
#define T0_COMMA   7
#define T0_PERIOD  8
#define T0_MIDDOT  9
#define T0_NUMBER  10
#define T0_NEWLINE 11
#define T0_ASCII   12
#define T0_SECTION 13
#define T0_GLUE    14
#define T0_COUNT   15

/* Codes derived from the 15.1M-syllable Korean news training corpus. GLUE is a
 * first-class symbol. Must match build_huffman() over the same frequencies in
 * the Python reference (verified byte-identical). */
static const char *table0_codes[T0_COUNT] = {
    "1110",       /* 1-syl */
    "00",         /* 2-syl */
    "01",         /* 3-syl */
    "101",        /* 4-syl */
    "1000",       /* 5-syl */
    "110100",     /* 6-syl */
    "1101011",    /* 7+-syl */
    "1101010011", /* comma */
    "11011",      /* period */
    "11010101",   /* middle dot */
    "1100",       /* number */
    "110101000",  /* newline */
    "1001",       /* ascii_start */
    "1101010010", /* section_sep */
    "1111",       /* glue */
};

/* Table 1: Onset (19 symbols) — index matches Hangul onset index */
static const char *onset_codes[ONSET_COUNT] = {
    "101",         /* ㄱ 0 */
    "110011011",   /* ㄲ 1 */
    "11111",       /* ㄴ 2 */
    "1110",        /* ㄷ 3 */
    "11001100",    /* ㄸ 4 */
    "1001",        /* ㄹ 5 */
    "11000",       /* ㅁ 6 */
    "11110",       /* ㅂ 7 */
    "11001101010", /* ㅃ 8 */
    "001",         /* ㅅ 9 */
    "1100110100",  /* ㅆ 10 */
    "01",          /* ㅇ 11 */
    "000",         /* ㅈ 12 */
    "11001101011", /* ㅉ 13 */
    "10001",       /* ㅊ 14 */
    "1100111",     /* ㅋ 15 */
    "10000",       /* ㅌ 16 */
    "110010",      /* ㅍ 17 */
    "1101",        /* ㅎ 18 */
};

/* Table 2: Vowel (21 symbols) */
static const char *vowel_codes[VOWEL_COUNT] = {
    "00",          /* ㅏ 0 */
    "0111",        /* ㅐ 1 */
    "1010101",     /* ㅑ 2 */
    "1010110000",  /* ㅒ 3 */
    "1110",        /* ㅓ 4 */
    "11111",       /* ㅔ 5 */
    "0110",        /* ㅕ 6 */
    "1010100",     /* ㅖ 7 */
    "010",         /* ㅗ 8 */
    "111100",      /* ㅘ 9 */
    "101011001",   /* ㅙ 10 */
    "101001",      /* ㅚ 11 */
    "1111010",     /* ㅛ 12 */
    "1011",        /* ㅜ 13 */
    "101000",      /* ㅝ 14 */
    "1010110001",  /* ㅞ 15 */
    "10101101",    /* ㅟ 16 */
    "1010111",     /* ㅠ 17 */
    "100",         /* ㅡ 18 */
    "1111011",     /* ㅢ 19 */
    "110",         /* ㅣ 20 */
};

/* Table 3: Coda (28 symbols, 0 = no coda) */
static const char *coda_codes[CODA_COUNT] = {
    "1",                  /* none 0 */
    "0100",               /* ㄱ 1 */
    "00000100101",        /* ㄲ 2 */
    "00000010000",        /* ㄳ 3 */
    "011",                /* ㄴ 4 */
    "000001001001",       /* ㄵ 5 */
    "00000000",           /* ㄶ 6 */
    "000001011",          /* ㄷ 7 */
    "0101",               /* ㄹ 8 */
    "000000111",          /* ㄺ 9 */
    "000001001000",       /* ㄻ 10 */
    "000000100111",       /* ㄼ 11 */
    "000000100110",       /* ㄽ 12 */
    "000000100101",       /* ㄾ 13 */
    "000000100100",       /* ㄿ 14 */
    "000000100011",       /* ㅀ 15 */
    "00011",              /* ㅁ 16 */
    "00010",              /* ㅂ 17 */
    "000000101",          /* ㅄ 18 */
    "0000011",            /* ㅅ 19 */
    "00001",              /* ㅆ 20 */
    "001",                /* ㅇ 21 */
    "000001010",          /* ㅈ 22 */
    "000001000",          /* ㅊ 23 */
    "000000100010",       /* ㅋ 24 */
    "000000110",          /* ㅌ 25 */
    "00000001",           /* ㅍ 26 */
    "0000010011",         /* ㅎ 27 */
};

/* ============================================================
 * Decode trie for each table
 * ============================================================ */

#define TRIE_MAX 4096

typedef struct {
    int left[TRIE_MAX];   /* child on 0 */
    int right[TRIE_MAX];  /* child on 1 */
    int symbol[TRIE_MAX]; /* -1 = not a leaf */
    int count;
} Trie;

void trie_init(Trie *t) {
    memset(t->left, -1, sizeof(t->left));
    memset(t->right, -1, sizeof(t->right));
    memset(t->symbol, -1, sizeof(t->symbol));
    t->count = 1; /* node 0 is root */
}

void trie_insert(Trie *t, const char *code, int sym) {
    int node = 0;
    while (*code) {
        if (*code == '0') {
            if (t->left[node] == -1) { t->left[node] = t->count++; }
            node = t->left[node];
        } else {
            if (t->right[node] == -1) { t->right[node] = t->count++; }
            node = t->right[node];
        }
        code++;
    }
    t->symbol[node] = sym;
}

/* Returns symbol or -1 */
int trie_read(Trie *t, BitReader *br) {
    int node = 0;
    while (t->symbol[node] == -1) {
        int bit = br_read_bit(br);
        if (bit < 0) return -1;
        node = bit ? t->right[node] : t->left[node];
        if (node == -1) return -1;
    }
    return t->symbol[node];
}

/* Global decode tries */
static Trie trie_t0, trie_onset, trie_vowel, trie_coda;

void init_tries(void) {
    trie_init(&trie_t0);
    for (int i = 0; i < T0_COUNT; i++)
        trie_insert(&trie_t0, table0_codes[i], i);

    trie_init(&trie_onset);
    for (int i = 0; i < ONSET_COUNT; i++)
        trie_insert(&trie_onset, onset_codes[i], i);

    trie_init(&trie_vowel);
    for (int i = 0; i < VOWEL_COUNT; i++)
        trie_insert(&trie_vowel, vowel_codes[i], i);

    trie_init(&trie_coda);
    for (int i = 0; i < CODA_COUNT; i++)
        trie_insert(&trie_coda, coda_codes[i], i);
}

/* ============================================================
 * Encoder
 * ============================================================ */

void encode_syllable(BitWriter *bw, uint32_t cp) {
    int onset, vowel, coda;
    decompose_hangul(cp, &onset, &vowel, &coda);
    bw_write_bits(bw, onset_codes[onset]);
    bw_write_bits(bw, vowel_codes[vowel]);
    bw_write_bits(bw, coda_codes[coda]);
}

void encode_text(BitWriter *bw, const uint8_t *text, int len) {
    int i = 0;
    int seen_content = 0;  /* has a content token been emitted in this eojeol? */
    while (i < len) {
        uint32_t cp;
        int bytes = utf8_decode(text + i, &cp);

        if (cp == '\n') {
            bw_write_bits(bw, table0_codes[T0_NEWLINE]);
            seen_content = 0;
            i += bytes;
            continue;
        }
        if (cp == ' ' || cp == '\t' || cp == '\r') { seen_content = 0; i += bytes; continue; }

        /* Hangul word */
        if (is_hangul(cp)) {
            if (seen_content) bw_write_bits(bw, table0_codes[T0_GLUE]);
            seen_content = 1;
            /* Count syllables */
            int start = i;
            int syl_count = 0;
            int j = i;
            while (j < len) {
                uint32_t cp2;
                int b2 = utf8_decode(text + j, &cp2);
                if (!is_hangul(cp2)) break;
                syl_count++;
                j += b2;
            }
            /* Write word length */
            if (syl_count <= 6) {
                bw_write_bits(bw, table0_codes[syl_count - 1]); /* T0_1SYL=0 .. T0_6SYL=5 */
            } else {
                bw_write_bits(bw, table0_codes[T0_7PLUS]);
                bw_write_int(bw, syl_count - 7, 8);
            }
            /* Write syllables */
            j = i;
            while (j < len) {
                uint32_t cp2;
                int b2 = utf8_decode(text + j, &cp2);
                if (!is_hangul(cp2)) break;
                encode_syllable(bw, cp2);
                j += b2;
            }
            i = j;
            continue;
        }

        /* Number: digits with interior '.'/',' separators preserved.
         * Each char is a 4-bit nibble (0-9 digits, 10='.', 11=','); the
         * length prefix is 8 bits (up to 255 chars per number token). */
        if (cp >= '0' && cp <= '9') {
            if (seen_content) bw_write_bits(bw, table0_codes[T0_GLUE]);
            seen_content = 1;
            char chars[256];
            int nc = 0;
            int j = i;
            while (j < len && nc < 255) {
                uint32_t cp2;
                int b2 = utf8_decode(text + j, &cp2);
                if (cp2 >= '0' && cp2 <= '9') {
                    chars[nc++] = (char)cp2;
                    j += b2;
                } else if ((cp2 == '.' || cp2 == ',') && j + b2 < len) {
                    uint32_t cp3;
                    utf8_decode(text + j + b2, &cp3);
                    if (cp3 >= '0' && cp3 <= '9') {
                        chars[nc++] = (char)cp2; /* keep separator */
                        j += b2;
                    } else break;
                } else break;
            }
            bw_write_bits(bw, table0_codes[T0_NUMBER]);
            bw_write_int(bw, nc, 8);
            for (int k = 0; k < nc; k++) {
                int nib = (chars[k] == '.') ? 10 : (chars[k] == ',') ? 11 : (chars[k] - '0');
                bw_write_int(bw, nib, 4);
            }
            i = j;
            continue;
        }

        /* Punctuation */
        if (cp == ',') { bw_write_bits(bw, table0_codes[T0_COMMA]); i += bytes; continue; }
        if (cp == '.') { bw_write_bits(bw, table0_codes[T0_PERIOD]); i += bytes; continue; }
        if (cp == 0x00B7) { bw_write_bits(bw, table0_codes[T0_MIDDOT]); i += bytes; continue; }

        /* Everything else (ASCII symbols, Latin letters, and non-ASCII symbols
         * such as % or an em dash) → escape run, copied verbatim as UTF-8 bytes
         * and null-terminated. Consecutive such characters share one run. */
        {
            if (seen_content) bw_write_bits(bw, table0_codes[T0_GLUE]);
            seen_content = 1;
            bw_write_bits(bw, table0_codes[T0_ASCII]);
            int j = i;
            while (j < len) {
                uint32_t cp2;
                int b2 = utf8_decode(text + j, &cp2);
                if (is_hangul(cp2) || (cp2 >= '0' && cp2 <= '9') ||
                    cp2 == ',' || cp2 == '.' || cp2 == 0x00B7 ||
                    cp2 == ' ' || cp2 == '\t' || cp2 == '\r' || cp2 == '\n')
                    break;
                for (int k = 0; k < b2; k++)
                    bw_write_int(bw, (uint8_t)text[j + k], 8);
                j += b2;
            }
            bw_write_int(bw, 0, 8); /* null terminator */
            i = j;
            continue;
        }
    }
}

/* ============================================================
 * Decoder
 * ============================================================ */

void decode_stream(BitReader *br, uint8_t *out, int *out_len) {
    int pos = 0;
    int space_pending = 0;  /* should a space precede the next content token? */
    int glue = 0;           /* did a GLUE marker just suppress that space? */

    while (br_remaining(br) > 0) {
        /* Check day boundary */
        if (br_remaining(br) >= 37) {
            int save = br->pos;
            int all_zero = 1;
            for (int i = 0; i < 16 && all_zero; i++) {
                if (br_read_bit(br)) all_zero = 0;
            }
            if (all_zero) {
                int year = br_read_int(br, 12);
                int month = br_read_int(br, 4);
                int day = br_read_int(br, 5);
                /* Validate the date so a 16-zero run inside content is not
                 * mistaken for a boundary (matches the Python reference). */
                if (month >= 1 && month <= 12 && day >= 1 && day <= 31) {
                    pos += sprintf((char*)out + pos, "%d년 %d월 %d일\n", year, month, day);
                    space_pending = 0;
                    glue = 0;
                    continue;
                }
            }
            br->pos = save;
        }

        int sym = trie_read(&trie_t0, br);
        if (sym < 0) break;

        if (sym == T0_GLUE) { glue = 1; continue; }

        if (sym >= T0_1SYL && sym <= T0_7PLUS) {
            int n;
            if (sym == T0_7PLUS) {
                n = br_read_int(br, 8) + 7;
            } else {
                n = sym + 1; /* T0_1SYL=0 → 1, T0_2SYL=1 → 2, etc */
            }
            if (space_pending && !glue) out[pos++] = ' ';
            for (int s = 0; s < n; s++) {
                int onset = trie_read(&trie_onset, br);
                int vowel = trie_read(&trie_vowel, br);
                int coda  = trie_read(&trie_coda, br);
                if (onset < 0 || vowel < 0 || coda < 0) goto done;
                uint32_t cp = compose_hangul(onset, vowel, coda);
                pos += utf8_encode(out + pos, cp);
            }
            space_pending = 1;
            glue = 0;
        }
        else if (sym == T0_COMMA)  { out[pos++] = ','; glue = 0; }
        else if (sym == T0_PERIOD) { out[pos++] = '.'; glue = 0; }
        else if (sym == T0_MIDDOT) { pos += utf8_encode(out + pos, 0x00B7); glue = 0; }
        else if (sym == T0_NEWLINE) { out[pos++] = '\n'; space_pending = 0; glue = 0; }
        else if (sym == T0_NUMBER) {
            if (space_pending && !glue) out[pos++] = ' ';
            int nc = br_read_int(br, 8);
            for (int d = 0; d < nc; d++) {
                int nib = br_read_int(br, 4);
                if (nib == 10) out[pos++] = '.';
                else if (nib == 11) out[pos++] = ',';
                else out[pos++] = '0' + nib;
            }
            space_pending = 1;
            glue = 0;
        }

        else if (sym == T0_ASCII) {
            if (space_pending && !glue) out[pos++] = ' ';
            while (br_remaining(br) >= 8) {
                int val = br_read_int(br, 8);
                if (val == 0) break;
                out[pos++] = (uint8_t)val;
            }
            space_pending = 1;
            glue = 0;
        }
        else if (sym == T0_SECTION) {
            out[pos++] = '\n';
            space_pending = 0;
            glue = 0;
            /* Read section name words until newline */
            while (1) {
                int inner = trie_read(&trie_t0, br);
                if (inner < 0 || inner == T0_NEWLINE) {
                    out[pos++] = '\n';
                    break;
                }
                if (inner == T0_GLUE) continue;
                if (inner >= T0_1SYL && inner <= T0_6SYL) {
                    int nn = inner + 1;
                    for (int s = 0; s < nn; s++) {
                        int o = trie_read(&trie_onset, br);
                        int v = trie_read(&trie_vowel, br);
                        int c = trie_read(&trie_coda, br);
                        if (o < 0) goto done;
                        pos += utf8_encode(out + pos, compose_hangul(o, v, c));
                    }
                } else {
                    out[pos++] = '\n';
                    break;
                }
            }
            space_pending = 0;
            glue = 0;
        }
    }
done:
    *out_len = pos;
}

/* ============================================================
 * File I/O
 * ============================================================ */

void write_sillok(const char *path, BitWriter *bw) {
    FILE *f = fopen(path, "wb");
    /* Header: SL + version + bit count */
    fputc('S', f); fputc('L', f); fputc(0x01, f);
    uint32_t bits = bw->total_bits;
    fputc((bits >> 24) & 0xFF, f);
    fputc((bits >> 16) & 0xFF, f);
    fputc((bits >> 8) & 0xFF, f);
    fputc(bits & 0xFF, f);
    /* Payload */
    int payload_bytes = (bw->total_bits + 7) / 8;
    fwrite(bw->data, 1, payload_bytes, f);
    fclose(f);
}

int read_sillok(const char *path, uint8_t **out_data, int *out_bits) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    int magic1 = fgetc(f), magic2 = fgetc(f);
    if (magic1 != 'S' || magic2 != 'L') { fclose(f); return -1; }
    fgetc(f); /* version */
    uint32_t bits = 0;
    bits |= (fgetc(f) << 24);
    bits |= (fgetc(f) << 16);
    bits |= (fgetc(f) << 8);
    bits |= fgetc(f);
    int payload_bytes = (bits + 7) / 8;
    *out_data = (uint8_t *)malloc(payload_bytes);
    fread(*out_data, 1, payload_bytes, f);
    fclose(f);
    *out_bits = bits;
    return 0;
}

/* ============================================================
 * Main
 * ============================================================ */

int main(int argc, char **argv) {
    init_tries();

    if (argc < 2) {
        printf("Usage:\n");
        printf("  sillok_c encode <input.txt> <output.sillok>\n");
        printf("  sillok_c decode <input.sillok>\n");
        printf("  sillok_c bench  <input.txt> <iterations>\n");
        return 0;
    }

    if (strcmp(argv[1], "encode") == 0 && argc >= 4) {
        FILE *f = fopen(argv[2], "rb");
        fseek(f, 0, SEEK_END);
        int len = ftell(f);
        fseek(f, 0, SEEK_SET);
        uint8_t *text = (uint8_t *)malloc(len);
        fread(text, 1, len, f);
        fclose(f);

        BitWriter bw;
        bw_init(&bw, len * 2);
        encode_text(&bw, text, len);
        write_sillok(argv[3], &bw);
        printf("Encoded: %d bits (%d bytes)\n", bw.total_bits, (bw.total_bits+7)/8 + 7);
        bw_free(&bw);
        free(text);
    }
    else if (strcmp(argv[1], "decode") == 0 && argc >= 3) {
        uint8_t *data;
        int bits;
        if (read_sillok(argv[2], &data, &bits) < 0) {
            printf("Failed to read %s\n", argv[2]);
            return 1;
        }
        BitReader br;
        br_init(&br, data, bits);
        uint8_t *out = (uint8_t *)malloc(bits); /* generous buffer */
        int out_len;
        decode_stream(&br, out, &out_len);
#ifdef _WIN32
        _setmode(_fileno(stdout), _O_BINARY);  /* don't translate \n to \r\n */
#endif
        fwrite(out, 1, out_len, stdout);
        free(out);
        free(data);
    }
    else if (strcmp(argv[1], "bench") == 0 && argc >= 4) {
        FILE *f = fopen(argv[2], "rb");
        fseek(f, 0, SEEK_END);
        int len = ftell(f);
        fseek(f, 0, SEEK_SET);
        uint8_t *text = (uint8_t *)malloc(len);
        fread(text, 1, len, f);
        fclose(f);

        int iters = atoi(argv[3]);
        printf("Text: %d bytes, %d iterations\n\n", len, iters);

        /* Benchmark encode */
        clock_t start = clock();
        BitWriter bw;
        for (int i = 0; i < iters; i++) {
            bw_init(&bw, len * 2);
            encode_text(&bw, text, len);
            if (i < iters - 1) bw_free(&bw);
        }
        clock_t end = clock();
        double enc_ms = (double)(end - start) / CLOCKS_PER_SEC * 1000.0;
        printf("Encode: %.2f ms/run (total %.1fms)\n", enc_ms / iters, enc_ms);
        printf("  Bits: %d\n\n", bw.total_bits);

        /* Benchmark decode */
        BitReader br;
        br_init(&br, bw.data, bw.total_bits);
        uint8_t *out = (uint8_t *)malloc(bw.total_bits);
        int out_len;

        start = clock();
        for (int i = 0; i < iters; i++) {
            br.pos = 0;
            decode_stream(&br, out, &out_len);
        }
        end = clock();
        double dec_ms = (double)(end - start) / CLOCKS_PER_SEC * 1000.0;
        printf("Decode: %.2f ms/run (total %.1fms)\n", dec_ms / iters, dec_ms);
        printf("  Chars: %d bytes\n", out_len);

        bw_free(&bw);
        free(out);
        free(text);
    }

    return 0;
}
