"""
daily_sillok.py — Main automation script.

Scrapes today's news, encodes to .sillok, saves to archive.
Designed to be called by GitHub Actions or Task Scheduler.

Usage:
  python daily_sillok.py [YYYY-MM-DD] [--archive-dir DIR]
"""

import sys
import os
import json
from datetime import date

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rss_scraper import scrape_all_sections
from sillok_core import build_daily_record, write_sillok, read_sillok, decode_bitstream


def main():
    # Parse arguments
    target_date = date.today()
    archive_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'archive')

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == '--archive-dir' and i + 1 < len(sys.argv):
            archive_dir = sys.argv[i + 1]
        elif not arg.startswith('--'):
            try:
                target_date = date.fromisoformat(arg)
            except ValueError:
                pass

    os.makedirs(archive_dir, exist_ok=True)

    print("=" * 60)
    print(f"  .sillok Daily Record Generator")
    print(f"  Date: {target_date.isoformat()}")
    print("=" * 60)

    # Step 1: Scrape
    print("\n[1/4] Scraping news...")
    sections = scrape_all_sections(target_date)

    # Step 2: Save JSON (for reference)
    json_path = os.path.join(archive_dir, f"sections_{target_date.isoformat()}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(sections, f, ensure_ascii=False, indent=2)
    print(f"\n[2/4] Saved sections JSON: {json_path}")

    # Step 3: Encode
    print("\n[3/4] Encoding .sillok...")
    total_chars = sum(len(v) for v in sections.values() if v)
    filled = [k for k, v in sections.items() if v]

    if total_chars == 0:
        print("  No content scraped. Skipping encoding.")
        return

    print(f"  Sections with content: {len(filled)}")
    for name in filled:
        print(f"    {name}: {len(sections[name])} chars")

    bitstream = build_daily_record(
        target_date.year, target_date.month, target_date.day, sections
    )

    # Step 4: Write .sillok file
    sillok_path = os.path.join(archive_dir, f"{target_date.isoformat()}.sillok")
    file_size = write_sillok(sillok_path, bitstream)

    utf8_estimate = total_chars * 3
    print(f"\n[4/4] Written: {sillok_path}")
    print(f"  Total characters: {total_chars}")
    print(f"  Bitstream: {len(bitstream)} bits")
    print(f"  File size: {file_size} bytes")
    print(f"  UTF-8 estimate: ~{utf8_estimate} bytes")
    if utf8_estimate > 0:
        print(f"  Compression: {(1 - file_size / utf8_estimate) * 100:.1f}%")

    # Verify
    print("\n  Verifying decode...")
    read_bits = read_sillok(sillok_path)
    decoded = decode_bitstream(read_bits)
    print(f"  Decoded length: {len(decoded)} chars")
    print(f"  First 200 chars: {decoded[:200]}...")

    print(f"\nDone! Archive: {sillok_path}")


if __name__ == '__main__':
    main()
