"""
sillok_core.py — Core encoder/decoder for the .sillok format.

Provides:
  - encode_text(text) -> bitstream
  - decode_bitstream(bitstream) -> text
  - write_sillok(filepath, bitstream)
  - read_sillok(filepath) -> bitstream
  - build_daily_record(date, sections) -> text in .sillok layout
"""

import heapq
import struct
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# Huffman builder
# ============================================================

@dataclass(order=True)
class HuffmanNode:
    freq: float
    symbol: Optional[str] = field(default=None, compare=False)
    left: Optional['HuffmanNode'] = field(default=None, compare=False)
    right: Optional['HuffmanNode'] = field(default=None, compare=False)


def build_huffman(freq_dict):
    if len(freq_dict) == 1:
        return {list(freq_dict.keys())[0]: '0'}
    heap = [HuffmanNode(freq=f, symbol=s) for s, f in freq_dict.items()]
    heapq.heapify(heap)
    while len(heap) > 1:
        left = heapq.heappop(heap)
        right = heapq.heappop(heap)
        heapq.heappush(heap, HuffmanNode(freq=left.freq + right.freq, left=left, right=right))
    codes = {}
    def traverse(node, prefix=''):
        if node.symbol is not None:
            codes[node.symbol] = prefix if prefix else '0'
            return
        if node.left: traverse(node.left, prefix + '0')
        if node.right: traverse(node.right, prefix + '1')
    traverse(heap[0])
    return codes


# ============================================================
# Korean character utilities
# ============================================================

ONSET_LIST = ['ㄱ','ㄲ','ㄴ','ㄷ','ㄸ','ㄹ','ㅁ','ㅂ','ㅃ','ㅅ','ㅆ','ㅇ','ㅈ','ㅉ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ']
VOWEL_LIST = ['ㅏ','ㅐ','ㅑ','ㅒ','ㅓ','ㅔ','ㅕ','ㅖ','ㅗ','ㅘ','ㅙ','ㅚ','ㅛ','ㅜ','ㅝ','ㅞ','ㅟ','ㅠ','ㅡ','ㅢ','ㅣ']
CODA_LIST = [None,'ㄱ','ㄲ','ㄳ','ㄴ','ㄵ','ㄶ','ㄷ','ㄹ','ㄺ','ㄻ','ㄼ','ㄽ','ㄾ','ㄿ','ㅀ','ㅁ','ㅂ','ㅄ','ㅅ','ㅆ','ㅇ','ㅈ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ']


def is_hangul(ch):
    return '\uAC00' <= ch <= '\uD7A3'


def decompose_hangul(ch):
    code = ord(ch) - 0xAC00
    return (ONSET_LIST[code // (21 * 28)],
            VOWEL_LIST[(code % (21 * 28)) // 28],
            CODA_LIST[code % 28])


def compose_hangul(onset, vowel, coda):
    oi = ONSET_LIST.index(onset)
    vi = VOWEL_LIST.index(vowel)
    ci = CODA_LIST.index(coda) if coda else 0
    return chr(0xAC00 + oi * 21 * 28 + vi * 28 + ci)


# ============================================================
# Huffman tables
# ============================================================

# Frequencies below are derived from the training split of a 15.1M-syllable
# Korean news corpus (Naver News, Apache-2.0). GLUE is a first-class symbol;
# rare symbols are floored to 0.01% so any Korean text remains encodable.
TABLE0_FREQ = {
    '3-syl': 22.32, '2-syl': 21.48, '4-syl': 13.52, 'GLUE': 10.04,
    '1-syl': 8.33, 'NUMBER': 5.79, 'ASCII_START': 5.14, '5-syl': 5.12,
    '.': 4.64, '6-syl': 1.73, '7+-syl': 1.30, '\u00b7': 0.58,
    'NEWLINE': 0.01, ',': 0.01, 'SECTION_SEP': 0.01,
}

ONSET_FREQ = {
    'ㅇ': 21.60, 'ㄱ': 12.57, 'ㅅ': 9.97, 'ㅈ': 9.74,
    'ㄷ': 8.57, 'ㅎ': 8.24, 'ㄹ': 6.51, 'ㄴ': 4.77,
    'ㅂ': 4.73, 'ㅁ': 4.04, 'ㅊ': 2.88, 'ㅌ': 2.32,
    'ㅍ': 1.97, 'ㅋ': 1.11, 'ㄸ': 0.38, 'ㄲ': 0.34,
    'ㅆ': 0.12, 'ㅉ': 0.07, 'ㅃ': 0.07,
}

VOWEL_FREQ = {
    'ㅏ': 19.96, 'ㅣ': 15.01, 'ㅡ': 12.00, 'ㅗ': 9.98,
    'ㅓ': 9.27, 'ㅜ': 7.29, 'ㅐ': 5.90, 'ㅕ': 4.95,
    'ㅔ': 4.80, 'ㅘ': 2.29, 'ㅚ': 1.37, 'ㅝ': 1.28,
    'ㅢ': 1.24, 'ㅛ': 1.21, 'ㅠ': 1.18, 'ㅑ': 0.76,
    'ㅖ': 0.69, 'ㅟ': 0.59, 'ㅙ': 0.16, 'ㅞ': 0.05,
    'ㅒ': 0.01,
}

CODA_FREQ = {
    '(none)': 51.88, 'ㄴ': 15.68, 'ㅇ': 9.77, 'ㄹ': 8.72,
    'ㄱ': 5.20, 'ㅁ': 2.79, 'ㅂ': 2.13, 'ㅆ': 1.99,
    'ㅅ': 0.70, 'ㅍ': 0.17, 'ㄶ': 0.15, 'ㄷ': 0.13,
    'ㅈ': 0.13, 'ㅊ': 0.11, 'ㄺ': 0.11, 'ㅌ': 0.10,
    'ㅄ': 0.10, 'ㅎ': 0.07, 'ㄲ': 0.03, 'ㄳ': 0.01,
    'ㄵ': 0.01, 'ㄻ': 0.01, 'ㄼ': 0.01, 'ㄽ': 0.01,
    'ㄾ': 0.01, 'ㄿ': 0.01, 'ㅀ': 0.01, 'ㅋ': 0.01,
}

# Build tables
CODES_T0 = build_huffman(TABLE0_FREQ)
CODES_T1 = build_huffman(ONSET_FREQ)
CODES_T2 = build_huffman(VOWEL_FREQ)
CODES_T3 = build_huffman(CODA_FREQ)

# GLUE is a first-class Table 0 symbol (~10% of dispatch events on the news
# corpus): it suppresses the space the decoder would otherwise insert before a
# token that continues an eojeol, e.g. the "1" and "의" in "제1의".

# Reverse tables for decoding
DEC_T0 = {v: k for k, v in CODES_T0.items()}
DEC_T1 = {v: k for k, v in CODES_T1.items()}
DEC_T2 = {v: k for k, v in CODES_T2.items()}
DEC_T3 = {v: k for k, v in CODES_T3.items()}


# ============================================================
# Tokenizer
# ============================================================

def tokenize(text):
    """Tokenize text into encoder events.

    Newlines are preserved exactly (one NEWLINE event per '\n', including blank
    lines and a trailing newline), matching the C reference implementation.
    Within an eojeol (whitespace-delimited token) the decoder must NOT insert a
    space between sub-pieces, so a ('glue',) event is emitted before every
    content sub-piece (word/number/ascii) after the first. The decoder inserts a
    space before each content piece by default; GLUE suppresses that space. Runs
    of intra-line whitespace are normalised to a single space.
    """
    events = []
    for li, line in enumerate(text.split('\n')):
        if li > 0:
            events.append(('newline',))
        for token in line.split():
            seen_content = False
            for ev in _subtokenize(token):
                if ev[0] in ('word', 'number', 'ascii', 'ascii_char'):
                    if seen_content:
                        events.append(('glue',))
                    seen_content = True
                events.append(ev)
    return events


def _subtokenize(token):
    result = []
    i = 0
    while i < len(token):
        ch = token[i]
        if is_hangul(ch):
            start = i
            while i < len(token) and is_hangul(token[i]):
                i += 1
            result.append(('word', token[start:i]))
        elif '0' <= ch <= '9':
            # ASCII digits only; non-ASCII digit characters (④, fullwidth, etc.)
            # fall through to the escape so the BCD path always sees 0-9. This
            # matches the C reference, which also tests the ASCII range.
            start = i
            while i < len(token):
                if '0' <= token[i] <= '9':
                    i += 1
                elif token[i] in '.,':
                    if i + 1 < len(token) and '0' <= token[i + 1] <= '9':
                        i += 1
                    else:
                        break
                else:
                    break
            result.append(('number', token[start:i]))
        elif ch in '.,\u00b7':
            result.append(('punct', ch))
            i += 1
        else:
            # Any other character (ASCII symbol, Latin letter, or non-ASCII
            # symbol such as % or an em dash) goes into an escape run, encoded
            # as raw UTF-8 bytes. Consecutive such characters share one run so
            # the marker/terminator overhead is amortised.
            start = i
            while i < len(token):
                c = token[i]
                if is_hangul(c) or '0' <= c <= '9' or c in '.,\u00b7':
                    break
                i += 1
            result.append(('ascii', token[start:i]))
    return result


# ============================================================
# Encoder
# ============================================================

def encode_text(text):
    """Encode Korean text into a .sillok bitstream string."""
    events = tokenize(text)
    bitstream = ""

    for event in events:
        etype = event[0]

        if etype == 'word':
            word = event[1]
            n = len(word)
            if n <= 6:
                bitstream += CODES_T0[f'{n}-syl']
            else:
                bitstream += CODES_T0['7+-syl'] + format(n - 7, '08b')

            for ch in word:
                onset, vowel, coda = decompose_hangul(ch)
                bitstream += CODES_T1[onset]
                bitstream += CODES_T2[vowel]
                coda_key = coda if coda else '(none)'
                bitstream += CODES_T3[coda_key]

        elif etype == 'punct':
            ch = event[1]
            if ch in CODES_T0:
                bitstream += CODES_T0[ch]
            else:
                bitstream += CODES_T0['ASCII_START']
                bitstream += format(ord(ch), '08b')
                bitstream += '00000000'

        elif etype == 'number':
            # Each character is one 4-bit nibble: digits 0-9 use their value;
            # the decimal separators '.' and ',' use the otherwise-unused nibble
            # values 10 and 11, so they survive the round trip. The length prefix
            # is 8 bits (up to 255 characters per number token).
            chars = event[1]
            bitstream += CODES_T0['NUMBER']
            bitstream += format(len(chars), '08b')
            for ch in chars:
                if ch == '.':
                    bitstream += format(10, '04b')
                elif ch == ',':
                    bitstream += format(11, '04b')
                else:
                    bitstream += format(int(ch), '04b')

        elif etype in ('ascii', 'ascii_char'):
            val = event[1]
            bitstream += CODES_T0['ASCII_START']
            for b in val.encode('utf-8'):
                bitstream += format(b, '08b')
            bitstream += '00000000'

        elif etype == 'newline':
            bitstream += CODES_T0['NEWLINE']

        elif etype == 'glue':
            bitstream += CODES_T0['GLUE']

    return bitstream


def encode_section_sep(section_name):
    """Encode a SECTION_SEP marker followed by the section name as a regular word."""
    bitstream = CODES_T0['SECTION_SEP']
    # Section name encoded as a word with word-length prefix
    bitstream += encode_text(section_name)
    # Followed by a NEWLINE
    bitstream += CODES_T0['NEWLINE']
    return bitstream


def encode_day_boundary(year, month, day):
    """Encode a 16-zero day boundary + 21-bit date."""
    bitstream = '0' * 16  # 16 zeros
    bitstream += format(year, '012b')   # 12-bit year
    bitstream += format(month, '04b')   # 4-bit month
    bitstream += format(day, '05b')     # 5-bit day
    return bitstream


# ============================================================
# Decoder
# ============================================================

def _read_huffman(bits, pos, table):
    buf = ""
    while pos < len(bits):
        buf += bits[pos]
        pos += 1
        if buf in table:
            return table[buf], pos
    return None, pos


def decode_day_boundary(bitstream, pos):
    """Try to read a day boundary at current position. Returns (year, month, day, new_pos) or None."""
    if pos + 37 > len(bitstream):
        return None
    # Check for 16 consecutive zeros
    if bitstream[pos:pos+16] != '0' * 16:
        return None
    # Read 21-bit date
    year = int(bitstream[pos+16:pos+28], 2)
    month = int(bitstream[pos+28:pos+32], 2)
    day = int(bitstream[pos+32:pos+37], 2)
    # Validate the date so a 16-zero run occurring inside content is not mistaken
    # for a boundary. The encoder only emits boundaries at record starts; this
    # check is defence in depth (see the archaeological-recoverability section).
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return year, month, day, pos + 37


def decode_bitstream(bitstream):
    """Decode a .sillok bitstream back to text."""
    pos = 0
    output = ""
    space_pending = False  # should a space precede the next content token?
    glue = False           # did a GLUE marker just suppress that space?

    while pos < len(bitstream):
        # Day boundary (16 zeros + 21-bit date) is tested before each Table 0 read
        day_result = decode_day_boundary(bitstream, pos)
        if day_result is not None:
            year, month, day, pos = day_result
            output += f"{year}년 {month}월 {day}일\n"
            space_pending = False
            glue = False
            continue

        sym, pos = _read_huffman(bitstream, pos, DEC_T0)
        if sym is None:
            break

        if sym == 'GLUE':
            glue = True
            continue

        if sym.endswith('-syl'):
            if sym == '7+-syl':
                ext = bitstream[pos:pos + 8]
                pos += 8
                n = int(ext, 2) + 7
            else:
                n = int(sym[0])
            if space_pending and not glue:
                output += " "
            for _ in range(n):
                onset, pos = _read_huffman(bitstream, pos, DEC_T1)
                vowel, pos = _read_huffman(bitstream, pos, DEC_T2)
                coda, pos = _read_huffman(bitstream, pos, DEC_T3)
                coda_val = None if coda == '(none)' else coda
                output += compose_hangul(onset, vowel, coda_val)
            space_pending = True
            glue = False

        elif sym == 'ASCII_START':
            # Bytes are raw UTF-8, terminated by a null byte (UTF-8 never
            # produces a 0x00 byte).
            if space_pending and not glue:
                output += " "
            byte_vals = bytearray()
            while pos < len(bitstream):
                byte_bits = bitstream[pos:pos + 8]
                pos += 8
                val = int(byte_bits, 2)
                if val == 0:
                    break
                byte_vals.append(val)
            output += byte_vals.decode('utf-8', errors='replace')
            space_pending = True
            glue = False

        elif sym == 'NUMBER':
            if space_pending and not glue:
                output += " "
            count_bits = bitstream[pos:pos + 8]
            pos += 8
            n_chars = int(count_bits, 2)
            for _ in range(n_chars):
                d_bits = bitstream[pos:pos + 4]
                pos += 4
                val = int(d_bits, 2)
                if val == 10:
                    output += '.'
                elif val == 11:
                    output += ','
                else:
                    output += str(val)
            space_pending = True
            glue = False

        elif sym == 'NEWLINE':
            output += "\n"
            space_pending = False
            glue = False

        elif sym == 'SECTION_SEP':
            # Section name follows as encoded text, terminated by NEWLINE.
            section_name = ""
            sec_space = False
            sec_glue = False
            while pos < len(bitstream):
                inner_sym, new_pos = _read_huffman(bitstream, pos, DEC_T0)
                if inner_sym is None or inner_sym == 'NEWLINE':
                    pos = new_pos
                    break
                elif inner_sym == 'GLUE':
                    pos = new_pos
                    sec_glue = True
                    continue
                elif inner_sym.endswith('-syl'):
                    pos = new_pos
                    if inner_sym == '7+-syl':
                        ext = bitstream[pos:pos + 8]
                        pos += 8
                        n = int(ext, 2) + 7
                    else:
                        n = int(inner_sym[0])
                    if sec_space and not sec_glue:
                        section_name += " "
                    sec_glue = False
                    sec_space = True
                    for _ in range(n):
                        onset, pos = _read_huffman(bitstream, pos, DEC_T1)
                        vowel, pos = _read_huffman(bitstream, pos, DEC_T2)
                        coda, pos = _read_huffman(bitstream, pos, DEC_T3)
                        coda_val = None if coda == '(none)' else coda
                        section_name += compose_hangul(onset, vowel, coda_val)
                else:
                    pos = new_pos
                    break
            output += f"\n{section_name}\n"
            space_pending = False
            glue = False

        elif sym in (',', '.', '\u00b7'):
            # No space before punctuation
            output += sym
            glue = False  # space_pending unchanged, so "안녕, 친구" keeps its space

    return output


# ============================================================
# File I/O
# ============================================================

MAGIC = b'SL'
VERSION = 0x01


def bits_to_bytes(bitstream):
    padded = bitstream + '0' * ((8 - len(bitstream) % 8) % 8)
    result = bytearray()
    for i in range(0, len(padded), 8):
        result.append(int(padded[i:i + 8], 2))
    return bytes(result)


def bytes_to_bits(data, bit_count):
    bits = ''.join(format(b, '08b') for b in data)
    return bits[:bit_count]


def write_sillok(filepath, bitstream):
    """Write a .sillok file. Returns file size in bytes."""
    bit_count = len(bitstream)
    payload = bits_to_bytes(bitstream)
    with open(filepath, 'wb') as f:
        f.write(MAGIC)
        f.write(struct.pack('B', VERSION))
        f.write(struct.pack('>I', bit_count))
        f.write(payload)
    return 7 + len(payload)


def read_sillok(filepath):
    """Read a .sillok file and return the bitstream."""
    with open(filepath, 'rb') as f:
        magic = f.read(2)
        if magic != MAGIC:
            raise ValueError(f"Not a .sillok file (magic: {magic!r})")
        version = struct.unpack('B', f.read(1))[0]
        if version != VERSION:
            raise ValueError(f"Unsupported version: {version}")
        bit_count = struct.unpack('>I', f.read(4))[0]
        payload = f.read()
    return bytes_to_bits(payload, bit_count)


# ============================================================
# Daily record builder
# ============================================================

SECTIONS = ['정치', '경제', '사회', '국제정세', '과학기술', '문화', '천재지변', '사신왈']


def build_daily_record(year, month, day, sections_content):
    """
    Build a complete .sillok bitstream for one day.

    Args:
        year, month, day: date
        sections_content: dict mapping section name -> text content
            e.g. {'정치': '...article text...', '경제': '...'}

    Returns:
        bitstream string
    """
    bitstream = ""

    # Day boundary
    bitstream += encode_day_boundary(year, month, day)

    # Each section
    for section_name in SECTIONS:
        content = sections_content.get(section_name, '')
        if not content:
            continue

        # Section separator
        bitstream += encode_section_sep(section_name)

        # Encode the section content
        bitstream += encode_text(content)

        # Newline after section
        bitstream += CODES_T0['NEWLINE']

    return bitstream


# ============================================================
# Quick test
# ============================================================

if __name__ == '__main__':
    # Test encode/decode roundtrip
    test = "안녕! 오랜만"
    bits = encode_text(test)
    decoded = decode_bitstream(bits)
    print(f"Input:   {test}")
    print(f"Decoded: {decoded}")
    print(f"Bits:    {len(bits)}")
    print(f"Match:   {test == decoded}")

    # Test daily record
    print("\n--- Daily Record Test ---")
    bits = build_daily_record(2026, 3, 25, {
        '정치': '이재명 대통령이 부동산 범죄 특별단속 성과를 발표했다.',
        '사신왈': '오늘은 바쁜 하루였다.',
    })
    size = write_sillok('test_daily.sillok', bits)
    print(f"Written test_daily.sillok: {size} bytes, {len(bits)} bits")
