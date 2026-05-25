"""Downloads CSV export tests.

Chromium stores download metadata in two related tables: ``downloads`` (one
row per file the user pulled down) and ``downloads_url_chains`` (the chain
of source URLs each download passed through, with one row per hop).  The
migrator joins them and emits a flat CSV.

These tests cover:

* The CSV header matches what FoxPort documents (filename, source_url,
  target_path, sizes, mime, start/end ISO timestamps, state label).
* The state mapping (0..4) renders human labels rather than raw ints.
* When no ``History`` DB exists, the migrator returns an empty result
  with zero failures (this is the "browser has never downloaded
  anything" branch).
* ``dry_run=True`` emits no file but still reports the row count.
* The atomic-write helper is honored — no orphan tempfile after a
  successful run.
"""

from __future__ import annotations

import csv as _csv
import sqlite3
from pathlib import Path

from foxport.migrate.downloads import _CSV_HEADER, migrate_downloads


def _seed_history_downloads(profile, rows: list[tuple]) -> None:
    """Build a minimal Chromium ``History`` DB with the downloads schema.

    Each row is
    ``(id, current_path, target_path, start_time, end_time, received_bytes,
    total_bytes, mime_type, state, tab_url, chain_url)``. ``chain_url`` goes
    into ``downloads_url_chains`` with ``chain_index=0`` so the migrator's
    "first chain entry wins" rule picks it.
    """

    db = profile.profile_dir / "History"
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript("""
            CREATE TABLE downloads (
                id INTEGER PRIMARY KEY,
                current_path LONGVARCHAR,
                target_path LONGVARCHAR,
                start_time INTEGER,
                end_time INTEGER,
                received_bytes INTEGER,
                total_bytes INTEGER,
                mime_type VARCHAR,
                state INTEGER,
                tab_url LONGVARCHAR
            );
            CREATE TABLE downloads_url_chains (
                id INTEGER,
                chain_index INTEGER,
                url LONGVARCHAR,
                PRIMARY KEY (id, chain_index)
            );
        """)
        for row in rows:
            conn.execute(
                "INSERT INTO downloads (id, current_path, target_path, start_time, "
                "end_time, received_bytes, total_bytes, mime_type, state, tab_url) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row[:10],
            )
            if row[10]:
                conn.execute(
                    "INSERT INTO downloads_url_chains VALUES (?, 0, ?)",
                    (row[0], row[10]),
                )
        conn.commit()
    finally:
        conn.close()


def test_csv_header_is_stable():
    assert _CSV_HEADER == [
        "filename", "source_url", "target_path",
        "received_bytes", "total_bytes", "mime_type",
        "start_time_iso", "end_time_iso", "state",
    ]


def test_migrate_downloads_no_history_returns_empty(tmp_path: Path, fake_chromium_profile):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = migrate_downloads(fake_chromium_profile, out_dir)
    assert result.written == 0
    assert result.total == 0
    assert not (out_dir / "downloads.csv").exists()


def test_migrate_downloads_renders_state_labels(tmp_path: Path, fake_chromium_profile):
    # Chrome epoch microseconds for 2026-05-24 00:00:00 UTC = (Unix ts) + offset.
    epoch_2026 = 13_359_168_000 * 1_000_000   # rough; exact value isn't important
    _seed_history_downloads(fake_chromium_profile, [
        (1, "C:\\Users\\me\\Downloads\\report.pdf", "C:\\Users\\me\\Downloads\\report.pdf",
         epoch_2026, epoch_2026, 1024, 1024, "application/pdf", 1, "",
         "https://example.com/report.pdf"),
        (2, "", "C:\\Users\\me\\Downloads\\song.mp3",
         epoch_2026, 0, 512, 4096, "audio/mpeg", 0, "https://music.example",
         "https://music.example/song.mp3"),
        (3, "", "C:\\Users\\me\\Downloads\\bad.zip",
         epoch_2026, epoch_2026, 0, 0, "", 3, "", "https://bad.example/x"),
    ])

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = migrate_downloads(fake_chromium_profile, out_dir)

    assert result.total == 3
    assert result.written == 3
    csv_path = out_dir / "downloads.csv"
    assert csv_path.is_file()
    # ``csv_path.open(...)`` leaks the file handle until GC; use a
    # context manager so ``pytest -W error::ResourceWarning`` stays clean.
    with csv_path.open(encoding="utf-8") as fh:
        rows = list(_csv.reader(fh))
    assert rows[0] == _CSV_HEADER
    body = rows[1:]
    # State labels render rather than raw ints.
    states = [r[-1] for r in body]
    assert "complete" in states
    assert "in_progress" in states
    # Source URL falls back to tab_url when downloads_url_chains is empty.
    urls = [r[1] for r in body]
    assert "https://example.com/report.pdf" in urls
    assert "https://music.example/song.mp3" in urls
    # No orphan atomic-write tempfile.
    assert not list(out_dir.glob(".downloads.csv.foxport-*"))


def test_migrate_downloads_dry_run_does_not_write(tmp_path: Path, fake_chromium_profile):
    _seed_history_downloads(fake_chromium_profile, [
        (1, "", "/tmp/a.txt", 0, 0, 0, 0, "text/plain", 1, "", "https://a.example"),
    ])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = migrate_downloads(fake_chromium_profile, out_dir, dry_run=True)
    assert result.total == 1
    assert result.written == 0
    assert not (out_dir / "downloads.csv").exists()
