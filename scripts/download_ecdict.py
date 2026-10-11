#!/usr/bin/env python3
"""Download and build the ECDICT local dictionary database.

ECDICT is a free English-Chinese dictionary with ~300k entries.
Source: https://github.com/skywind3000/ECDICT

This script:
  1. Downloads `stardict.7z` (~51 MB) from the ECDICT repository
  2. Extracts `stardict.csv` (~232 MB, ~770k entries)
  3. Builds a SQLite database at `config/ecdict.db` with table `ecdict`

Run once after installation:

    python3 scripts/download_ecdict.py

Requires the `7z` command-line tool:
    sudo apt install 7zip
"""
from __future__ import annotations

import csv
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/skywind3000/ECDICT/master/stardict.7z"
# Optional SHA-256 of stardict.7z for integrity verification. Set via the
# ECDICT_SHA256 environment variable (or hardcode once known). When empty,
# verification is skipped with a warning.
EXPECTED_SHA256 = os.environ.get("ECDICT_SHA256", "").strip().lower()
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DEST = CONFIG_DIR / "ecdict.db"
TMP_7Z = CONFIG_DIR / "stardict.7z"
CSV_PATH = CONFIG_DIR / "stardict.csv"

# Columns to import from the CSV (subset that we actually query).
COLUMNS = [
    "word", "phonetic", "definition", "translation",
    "pos", "collins", "oxford", "tag", "exchange",
]


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def verify_sha256(path: Path, expected: str) -> bool:
    """Return True if the file's SHA-256 matches `expected` (or if no
    expected value is configured, in which case a warning is logged)."""
    if not expected:
        print("WARNING: ECDICT_SHA256 not set; skipping integrity check")
        return True
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(128 * 1024), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != expected:
        print(f"ERROR: SHA-256 mismatch for {path}")
        print(f"  expected: {expected}")
        print(f"  actual:   {actual}")
        return False
    print(f"SHA-256 OK: {actual}")
    return True


def download(url: str, dest: Path) -> bool:
    print(f"Downloading from {url}")
    print(f"  -> {dest}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ubdict/0.1"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
            total = 0
            while True:
                chunk = resp.read(128 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
                print(f"\r  {human(total)} downloaded", end="", flush=True)
        print()
        return True
    except Exception as e:
        print(f"\nDownload failed: {e}")
        if dest.exists():
            dest.unlink()
        return False


def extract_7z(archive: Path, out_dir: Path) -> bool:
    if not shutil.which("7z"):
        print("ERROR: 7z not found. Install: sudo apt install 7zip")
        return False
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["7z", "x", "-y", f"-o{out_dir}", str(archive)],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Extraction failed: {e.stderr}")
        return False


def build_sqlite(csv_path: Path, db_path: Path) -> int:
    """Build SQLite database from CSV, return entry count."""
    print(f"Building SQLite from {csv_path.name}...")
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    # Create table.
    col_defs = ", ".join(f'"{c}" TEXT' for c in COLUMNS)
    conn.execute(f'CREATE TABLE ecdict ({col_defs})')
    conn.execute('CREATE INDEX idx_word ON ecdict(word COLLATE NOCASE)')

    count = 0
    batch: list[tuple] = []
    BATCH_SIZE = 5000

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Extract only the columns we need; strip surrounding quotes.
            values = []
            for col in COLUMNS:
                val = row.get(col, "") or ""
                # ECDICT CSV wraps some fields in single quotes.
                val = val.strip()
                if len(val) >= 2 and val[0] == "'" and val[-1] == "'":
                    val = val[1:-1]
                values.append(val)
            batch.append(tuple(values))
            if len(batch) >= BATCH_SIZE:
                placeholders = ", ".join("?" for _ in COLUMNS)
                conn.executemany(
                    f'INSERT INTO ecdict VALUES ({placeholders})', batch
                )
                count += len(batch)
                batch.clear()
                print(f"\r  {count:,} entries", end="", flush=True)

    if batch:
        placeholders = ", ".join("?" for _ in COLUMNS)
        conn.executemany(f'INSERT INTO ecdict VALUES ({placeholders})', batch)
        count += len(batch)

    conn.commit()
    # Vacuum to compact.
    conn.execute("VACUUM")
    conn.close()
    print(f"\r  {count:,} entries written")
    return count


def verify_db(path: Path) -> tuple[int, str] | None:
    try:
        conn = sqlite3.connect(str(path))
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        if not rows:
            conn.close()
            return None
        table = rows[0][0]
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        conn.close()
        return count, table
    except sqlite3.Error as e:
        print(f"Verify failed: {e}")
        return None


def main() -> int:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if DEST.exists():
        info = verify_db(DEST)
        if info and "--force" not in sys.argv:
            count, table = info
            print(f"ECDICT already exists: {DEST} ({human(DEST.stat().st_size)})")
            print(f"  table: {table}, entries: {count:,}")
            print("Use --force to re-download and rebuild.")
            return 0

    # Step 1: download stardict.7z (skip if already present)
    if not TMP_7Z.exists() or "--force" in sys.argv:
        if not download(URL, TMP_7Z):
            print_manual_instructions()
            return 1
        if not verify_sha256(TMP_7Z, EXPECTED_SHA256):
            print("Integrity verification failed; aborting")
            TMP_7Z.unlink(missing_ok=True)
            return 1
    print(f"Archive: {TMP_7Z} ({human(TMP_7Z.stat().st_size)})")

    # Step 2: extract (skip if CSV already present)
    if not CSV_PATH.exists() or "--force" in sys.argv:
        if not extract_7z(TMP_7Z, CONFIG_DIR):
            return 1
    if not CSV_PATH.exists():
        print(f"ERROR: {CSV_PATH} not found after extraction")
        return 1
    print(f"CSV: {CSV_PATH} ({human(CSV_PATH.stat().st_size)})")

    # Step 3: build SQLite
    count = build_sqlite(CSV_PATH, DEST)
    print(f"Built: {DEST} ({human(DEST.stat().st_size)})")

    # Step 4: verify
    info = verify_db(DEST)
    if not info:
        print("Verification failed")
        return 1
    vcount, vtable = info
    print(f"Verified: table={vtable}, {vcount:,} entries")

    # Clean up intermediate files.
    if TMP_7Z.exists():
        TMP_7Z.unlink()
        print(f"Removed: {TMP_7Z.name}")
    if CSV_PATH.exists():
        CSV_PATH.unlink()
        print(f"Removed: {CSV_PATH.name}")

    print()
    print(f"ECDICT ready: {DEST} ({human(DEST.stat().st_size)})")
    print(f"  table: {vtable}, entries: {vcount:,}")
    return 0


def print_manual_instructions() -> None:
    print()
    print("Manual download instructions:")
    print("  1. Visit https://github.com/skywind3000/ECDICT")
    print(f"  2. Download stardict.7z to: {TMP_7Z}")
    print("  3. Ensure 7z is installed: sudo apt install 7zip")
    print(f"  4. Re-run: python3 {Path(__file__).name}")


if __name__ == "__main__":
    raise SystemExit(main())
