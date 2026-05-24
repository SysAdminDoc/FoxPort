"""Tests for the Chromium → Firefox places.sqlite migrator."""

import sqlite3

from foxport.crypto.mozhash import places_url_hash
from foxport.migrate.history import migrate_history


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
