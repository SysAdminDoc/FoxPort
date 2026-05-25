"""Saved-cards CSV export tests.

The cards migrator decrypts Chromium's ``Web Data.credit_cards`` blobs
with the DPAPI master key. The decryption path itself is exercised under
``test_passwords`` / ``test_cookies`` (same AES-GCM helper); here we
focus on:

* The CSV column shape stays in sync with ``_CSV_HEADER`` (which we
  pruned in v1.3 to drop the duplicate cardholder column).
* The migrator never writes a CSV when zero cards decrypt — there's no
  point in producing a header-only file the user would think contains
  real entries.
* dry-run mode produces no on-disk artifact.
* The output goes through the atomic writer (no leftover ``.foxport-*``
  tempfile after a successful run).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from foxport.migrate import cards
from foxport.migrate.cards import _CSV_HEADER, migrate_cards


def _seed_web_data(profile, with_cards: bool) -> None:
    """Drop a ``Web Data`` SQLite into the profile directory.

    Schema is the subset cards.py reads (the migrator uses ``SELECT *``
    with a fixed column list; extras would be ignored anyway). When
    ``with_cards=False`` we leave the table empty so decryption never
    runs.
    """

    db = profile.profile_dir / "Web Data"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE credit_cards ("
            "guid TEXT PRIMARY KEY, "
            "name_on_card TEXT, "
            "expiration_month TEXT, "
            "expiration_year TEXT, "
            "card_number_encrypted BLOB"
            ")"
        )
        if with_cards:
            # Encrypted blob is a placeholder — the test forces the migrator
            # down its empty-blob branch so we never call into DPAPI. That
            # branch counts as "empty plaintext" failure, so the CSV writer
            # produces no rows and (per the new behavior) no CSV file.
            conn.execute(
                "INSERT INTO credit_cards VALUES (?, ?, ?, ?, ?)",
                ("guid-1", "Test Holder", "07", "2030", b""),
            )
        conn.commit()
    finally:
        conn.close()


def test_csv_header_has_five_distinct_columns():
    # The v1.3 cleanup dropped the duplicate cardholder column. Guard the
    # invariant so a future PR doesn't quietly re-add it.
    assert _CSV_HEADER == [
        "Type", "Cardholder name", "Number", "Expiration", "Notes",
    ]
    assert len(set(_CSV_HEADER)) == len(_CSV_HEADER), "duplicate column!"


def test_migrate_cards_no_web_data_writes_nothing(tmp_path: Path, fake_chromium_profile, monkeypatch):
    # No Web Data file at all → returns an empty result with zero failures
    # (this is the "this browser never saved a card" branch).
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = migrate_cards(fake_chromium_profile, out_dir, dry_run=False)
    assert result.total == 0
    assert result.decrypted == 0
    assert not (out_dir / "saved-cards.csv").exists()


def test_migrate_cards_empty_plaintext_skips_csv_emit(
    tmp_path: Path,
    fake_chromium_profile,
    monkeypatch,
):
    # Master key loader must not raise (would short-circuit before reading
    # the table). Return a 32-byte stand-in.
    monkeypatch.setattr(cards, "load_master_key", lambda *a, **kw: b"\x00" * 32)
    # Decrypt path is bypassed by the empty-blob branch — assert it's never
    # called so a failing test would say so loudly.
    def _explode(*a, **kw):  # pragma: no cover - assertion-only path
        raise AssertionError("decrypt_value should not be called for empty blobs")
    monkeypatch.setattr(cards, "decrypt_value", _explode)
    _seed_web_data(fake_chromium_profile, with_cards=True)

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = migrate_cards(fake_chromium_profile, out_dir, dry_run=False)

    # Total rows seen was 1; we never decrypted any.
    assert result.total == 1
    assert result.decrypted == 0
    # The migrator now refuses to emit a header-only CSV when nothing
    # decrypted — the user shouldn't be tricked into importing an empty
    # file thinking they "lost" all their cards.
    assert not (out_dir / "saved-cards.csv").exists()
    # No orphaned tempfile from the atomic helper.
    assert not list(out_dir.glob(".saved-cards.csv.foxport-*"))


def test_migrate_cards_dry_run_writes_nothing(
    tmp_path: Path, fake_chromium_profile, monkeypatch,
):
    monkeypatch.setattr(cards, "load_master_key", lambda *a, **kw: b"\x00" * 32)
    _seed_web_data(fake_chromium_profile, with_cards=True)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = migrate_cards(fake_chromium_profile, out_dir, dry_run=True)

    assert result.csv_path.name == "saved-cards.csv"
    # Dry-run never writes anything on disk.
    assert not result.csv_path.exists()
