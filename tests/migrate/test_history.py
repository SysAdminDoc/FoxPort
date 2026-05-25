"""Tests for the Chromium → Firefox places.sqlite migrator."""

import json
import sqlite3
from types import SimpleNamespace

from foxport.crypto.mozhash import places_url_hash
from foxport.migrate.history import migrate_history
from foxport.migrate.nss_history import write_history_into_target


CHROME_EPOCH_OFFSET_MICROS = 11_644_473_600 * 1_000_000


def _add_download_rows(history_path, rows):
    """Add Chromium downloads tables to an existing synthetic History DB."""

    conn = sqlite3.connect(str(history_path))
    try:
        conn.executescript("""
            CREATE TABLE downloads (
                id INTEGER PRIMARY KEY,
                current_path LONGVARCHAR,
                target_path LONGVARCHAR,
                end_time INTEGER,
                received_bytes INTEGER,
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
                "INSERT INTO downloads (id, current_path, target_path, end_time, "
                "received_bytes, state, tab_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
                row[:7],
            )
            if row[7]:
                conn.execute(
                    "INSERT INTO downloads_url_chains VALUES (?, 0, ?)",
                    (row[0], row[7]),
                )
        conn.commit()
    finally:
        conn.close()


def test_history_round_trip(fake_chromium_profile, make_history_db, tmp_path):
    history_path = make_history_db([
        ("https://github.com/", "GitHub", 5),
        ("https://mozilla.org/", "Mozilla", 2),
    ])
    history_path.rename(fake_chromium_profile.profile_dir / "History")

    out = tmp_path / "out"
    result = migrate_history(fake_chromium_profile, out)
    assert result.urls == 2
    assert result.visits == 7

    conn = sqlite3.connect(str(result.sqlite_path))
    try:
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        assert ver == 86, f"places.sqlite should declare schema 86, got {ver}"
        places = conn.execute("SELECT url, url_hash, frecency FROM moz_places").fetchall()
        urls_by_url = {row[0]: row for row in places}
        # url_hash MUST match the HashString algorithm.
        for url, url_hash, frecency in places:
            assert url_hash == places_url_hash(url), f"url_hash mismatch for {url}"
            assert frecency == -1, "frecency must be -1 so Firefox recomputes"
        assert "https://github.com/" in urls_by_url
        assert "https://mozilla.org/" in urls_by_url
    finally:
        conn.close()


def test_history_filters_internal_urls(fake_chromium_profile, make_history_db, tmp_path):
    history_path = make_history_db([
        ("https://example.com/", "Ex", 1),
        ("chrome://settings/", "Settings", 1),
        ("about:blank", "Blank", 1),
    ])
    history_path.rename(fake_chromium_profile.profile_dir / "History")

    out = tmp_path / "out"
    result = migrate_history(fake_chromium_profile, out)
    assert result.urls == 1  # only the https URL


def test_history_moz_origins_block_columns(fake_chromium_profile, make_history_db, tmp_path):
    """moz_origins must have block_until_ms + block_pages_until_ms (v86)."""
    history_path = make_history_db([("https://example.com/", "Ex", 1)])
    history_path.rename(fake_chromium_profile.profile_dir / "History")

    out = tmp_path / "out"
    result = migrate_history(fake_chromium_profile, out)
    conn = sqlite3.connect(str(result.sqlite_path))
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(moz_origins)").fetchall()]
        assert "block_until_ms" in cols
        assert "block_pages_until_ms" in cols
    finally:
        conn.close()


def test_history_dry_run(fake_chromium_profile, make_history_db, tmp_path):
    history_path = make_history_db([("https://example.com/", "Ex", 3)])
    history_path.rename(fake_chromium_profile.profile_dir / "History")
    out = tmp_path / "out"
    result = migrate_history(fake_chromium_profile, out, dry_run=True)
    assert result.urls == 1
    assert result.visits == 3
    assert not result.sqlite_path.exists()


def test_history_can_annotate_downloads_in_moz_annos(
    fake_chromium_profile, make_history_db, tmp_path,
):
    history_path = make_history_db([
        ("https://example.com/file.zip", "File", 1),
        ("https://example.com/page", "Page", 1),
    ])
    _add_download_rows(history_path, [
        (
            1,
            r"C:\Users\me\Downloads\file name.zip",
            r"C:\Users\me\Downloads\file name.zip",
            CHROME_EPOCH_OFFSET_MICROS + 42_000_000,
            2048,
            1,
            "",
            "https://example.com/file.zip",
        ),
        (
            2,
            "",
            r"C:\Users\me\Downloads\missing.zip",
            CHROME_EPOCH_OFFSET_MICROS + 99_000_000,
            1024,
            3,
            "",
            "https://not-in-history.example/missing.zip",
        ),
    ])
    history_path.rename(fake_chromium_profile.profile_dir / "History")

    result = migrate_history(
        fake_chromium_profile,
        tmp_path / "out",
        include_download_annotations=True,
    )
    assert result.downloads_annotated == 1

    conn = sqlite3.connect(str(result.sqlite_path))
    try:
        rows = conn.execute(
            "SELECT aa.name, a.content, a.type, a.expiration "
            "FROM moz_annos a "
            "JOIN moz_anno_attributes aa ON aa.id = a.anno_attribute_id "
            "ORDER BY aa.name"
        ).fetchall()
    finally:
        conn.close()

    assert rows == [
        (
            "downloads/destinationFileURI",
            "file:///C:/Users/me/Downloads/file%20name.zip",
            3,
            0,
        ),
        (
            "downloads/metaData",
            '{"state":1,"endTime":42000,"fileSize":2048}',
            3,
            0,
        ),
    ]
    assert json.loads(rows[1][1]) == {
        "state": 1,
        "endTime": 42000,
        "fileSize": 2048,
    }


def test_history_leaves_download_annos_empty_by_default(
    fake_chromium_profile, make_history_db, tmp_path,
):
    history_path = make_history_db([("https://example.com/file.zip", "File", 1)])
    _add_download_rows(history_path, [
        (
            1,
            "/home/me/file.zip",
            "/home/me/file.zip",
            CHROME_EPOCH_OFFSET_MICROS,
            10,
            1,
            "",
            "https://example.com/file.zip",
        ),
    ])
    history_path.rename(fake_chromium_profile.profile_dir / "History")

    result = migrate_history(fake_chromium_profile, tmp_path / "out")
    assert result.downloads_annotated == 0

    conn = sqlite3.connect(str(result.sqlite_path))
    try:
        annos = conn.execute("SELECT COUNT(*) FROM moz_annos").fetchone()[0]
    finally:
        conn.close()
    assert annos == 0


def test_write_history_into_target_can_include_download_annotations(
    fake_chromium_profile, make_history_db, tmp_path,
):
    history_path = make_history_db([("https://example.com/file.zip", "File", 1)])
    _add_download_rows(history_path, [
        (
            1,
            "/home/me/file.zip",
            "/home/me/file.zip",
            CHROME_EPOCH_OFFSET_MICROS,
            10,
            1,
            "",
            "https://example.com/file.zip",
        ),
    ])
    history_path.rename(fake_chromium_profile.profile_dir / "History")

    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / "places.sqlite").write_bytes(b"old db")
    target = SimpleNamespace(
        label="Target",
        profile_dir=target_dir,
        lock_file=target_dir / "parent.lock",
    )

    result = write_history_into_target(
        fake_chromium_profile,
        target,
        tmp_path / "staging",
        include_download_annotations=True,
    )

    assert result.backup_path is not None
    assert result.backup_path.exists()
    assert result.written.downloads_annotated == 1

    conn = sqlite3.connect(str(result.target_path))
    try:
        annos = conn.execute("SELECT COUNT(*) FROM moz_annos").fetchone()[0]
    finally:
        conn.close()
    assert annos == 2
