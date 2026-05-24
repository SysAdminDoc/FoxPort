"""End-to-end test for the autofill (Chromium → Firefox formhistory) path.

Verifies that the produced ``formhistory.sqlite`` actually conforms to
Firefox v5 schema: the v4 → v5 migration on Firefox's side requires
``moz_sources`` and ``moz_history_to_sources`` to already exist (or
Firefox refuses to load the DB).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from foxport.migrate.autofill import migrate_autofill


@pytest.fixture
def fake_web_data(fake_chromium_profile):
    """Drop a synthetic Web Data SQLite into the chromium profile."""
    def _make(entries: list[tuple[str, str, int, int, int]]) -> Path:
        # entries: list of (name, value, count, date_created_secs_1601, date_last_used_secs_1601)
        web_data = fake_chromium_profile.profile_dir / "Web Data"
        conn = sqlite3.connect(str(web_data))
        try:
            conn.executescript("""
                CREATE TABLE autofill (
                    name VARCHAR,
                    value VARCHAR,
                    value_lower VARCHAR,
                    date_created INTEGER NOT NULL DEFAULT 0,
                    date_last_used INTEGER NOT NULL DEFAULT 0,
                    count INTEGER NOT NULL DEFAULT 1
                );
            """)
            for name, value, count, dc, dlu in entries:
                conn.execute(
                    "INSERT INTO autofill (name, value, value_lower, date_created, "
                    "date_last_used, count) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, value, value.lower(), dc, dlu, count),
                )
            conn.commit()
        finally:
            conn.close()
        return fake_chromium_profile
    return _make


def test_emits_v5_schema_with_required_tables(tmp_path, fake_web_data):
    """Firefox v5 needs moz_sources + moz_history_to_sources; the v4
    layout (which omitted them) makes Firefox try to run an auto-migration
    on first launch and corrupt the DB."""
    profile = fake_web_data([
        ("email", "alice@example.com", 5, 11_644_473_600 + 100, 11_644_473_600 + 200),
    ])
    out_dir = tmp_path / "out"
    result = migrate_autofill(profile, out_dir)
    assert result.written == 1
    db = sqlite3.connect(str(result.sqlite_path))
    try:
        tables = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "moz_formhistory" in tables
        assert "moz_deleted_formhistory" in tables
        assert "moz_sources" in tables
        assert "moz_history_to_sources" in tables
        user_version = db.execute("PRAGMA user_version").fetchone()[0]
        assert user_version == 5
    finally:
        db.close()


def test_writes_one_row_per_autofill_entry(tmp_path, fake_web_data):
    profile = fake_web_data([
        ("email", "alice@example.com", 5, 11_644_473_600 + 100, 11_644_473_600 + 200),
        ("name", "Alice", 3, 11_644_473_600 + 50, 11_644_473_600 + 150),
    ])
    out_dir = tmp_path / "out"
    result = migrate_autofill(profile, out_dir)
    assert result.written == 2
    db = sqlite3.connect(str(result.sqlite_path))
    try:
        rows = db.execute(
            "SELECT fieldname, value, timesUsed FROM moz_formhistory ORDER BY fieldname"
        ).fetchall()
    finally:
        db.close()
    assert rows == [("email", "alice@example.com", 5), ("name", "Alice", 3)]


def test_skips_empty_name_or_value(tmp_path, fake_web_data):
    profile = fake_web_data([
        ("", "no name", 1, 11_644_473_600, 11_644_473_600),
        ("real", "value", 1, 11_644_473_600, 11_644_473_600),
    ])
    out_dir = tmp_path / "out"
    result = migrate_autofill(profile, out_dir)
    assert result.written == 1
    assert result.skipped == 1


def test_dry_run_writes_no_file(tmp_path, fake_web_data):
    profile = fake_web_data([
        ("email", "alice@example.com", 1, 11_644_473_600, 11_644_473_600),
    ])
    out_dir = tmp_path / "out"
    result = migrate_autofill(profile, out_dir, dry_run=True)
    assert result.written == 1   # counts the row
    assert not result.sqlite_path.exists()
