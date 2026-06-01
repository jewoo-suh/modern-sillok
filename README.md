# `.sillok` — A Korean-Specific Lossless Text Encoding Format

`.sillok` is a lossless encoding for Korean text, designed for **long-term
archival**. It decomposes each Hangul syllable into its onset, vowel, and coda
and codes each position with a static, published Huffman table, encoding a
syllable in **9.46 bits** on average against UTF-8's 24. Numbers, embedded
non-Hangul text, word spacing, and document structure all have dedicated,
lossless representations.

Unlike a general-purpose compressor, a `.sillok` bitstream is meant to be
**recoverable from the bits alone** — through knowledge of Korean phonology and
frequency analysis, with no software decoder — much as the *Joseon Wangjo
Sillok* (조선왕조실록), the daily annals it is named after, remain readable
centuries later.

## Paper

A full write-up (format spec, optimisation analysis, evaluation, and the
recoverability argument) is in [`paper/sillok_paper.tex`](paper/sillok_paper.tex).

**📄 Read it online:** https://jewoo-suh.github.io/modern-sillok/sillok_paper.pdf

## Results (held-out Korean news, train/test split)

| | `.sillok` | gzip | zstd | Brotli | lzma |
|---|---|---|---|---|---|
| **Per-record reduction vs UTF-8** | **56.4%** | 52.6% | 52.9% | 56.6% | 49.1% |

Per record — the way the format is actually used — `.sillok` is competitive with
the strongest general-purpose compressors (it matches Brotli, beats the rest)
while being the only one **reconstructible from the bitstream alone**. The
Python and C implementations are verified to produce **byte-identical** output;
C decodes ~52× faster than Python.

## Layout

```
src/sillok_core.py   reference encoder/decoder (Python)
src/rss_scraper.py   Korean news RSS scraper
src/daily_sillok.py  daily scrape -> encode -> archive pipeline
c/sillok.c           fast C implementation (byte-identical to Python)
paper/               LaTeX source of the paper
```

## Usage

```python
from src.sillok_core import encode_text, decode_bitstream, write_sillok, read_sillok

bits = encode_text("한국 2026년 경제 성장률은 3.1% 입니다")
write_sillok("record.sillok", bits)
print(decode_bitstream(read_sillok("record.sillok")))
```

The C build: `gcc -O2 -o sillok_c c/sillok.c`, then
`./sillok_c encode in.txt out.sillok` / `./sillok_c decode out.sillok`.

## A daily record (kept private)

`src/daily_sillok.py` scrapes Korean news, builds a sectioned daily digest, and
encodes it to a single `.sillok` record — a small, modern echo of the daily
annals the format is named after. I run this for myself each day, but I keep the
resulting archive **private**: the records contain third-party news content, so I
do not republish them here, out of respect for the outlets' copyright and terms
of use. The pipeline is included so the capability is fully reproducible on your
own text. Questions about it are welcome by email (`jewoosuh0111 [at] gmail.com`).

## Licence

- **Code** (`src/`, `c/`): MIT — see [`LICENSE`](LICENSE).
- **Paper** (`paper/`, `docs/sillok_paper.pdf`): CC BY 4.0.

## Citation

```bibtex
@misc{suh_sillok,
  author = {Suh, Jewoo},
  title  = {{.sillok}: A Korean-Specific Lossless Text Encoding Format},
  year   = {2026},
  month  = {6},
  note   = {Version 1.0},
  howpublished = {\url{https://github.com/jewoo-suh/modern-sillok}}
}
```
