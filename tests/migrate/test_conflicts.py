"""Pre-flight conflict-analysis tests for the direct-write paths."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from foxport.browsers.chromium import PasswordRow
from foxport.migrate import conflicts as conflicts_mod
from foxport.migrate.conflicts import (
    analyze_cookies,
    analyze_history,
    analyze_passwords,
)
from foxport.migrate.passwords import _FOXPORT_LOGIN_NAMESPACE


@pytest.fixture
def fake_firefox_profile(tmp_path: Path):
    from foxport.browsers.detect import FirefoxProfile
    d = tmp_path / "ff"
    d.mkdir()
    return FirefoxProfile(
        browser="Firefox", family="firefox", profile_name="default",
        profile_dir=d, is_default=True,
    )


def _det_guid(origin: str, username: str) -> str:
    return "{" + str(uuid.uuid5(
        _FOXPORT_LOGIN_NAMESPACE, f"{origin}\x00{username}",
    )) + "}"


def test_analyze_passwords_counts_overlap_via_deterministic_guid(
    fake_chromium_profile, fake_firefox_profile, monkeypatch,
):
    """Source rows whose deterministic GUID already exists in the target
    count as duplicates; the rest are new. Mirrors what the real merge
    path would actually do, so the user sees the same skip count."""

    source_rows = [
        PasswordRow(origin_url="https://a.example", action_url="", username="me",
                    password_blob=b"x", date_created=0, date_last_used=0,
                    date_password_modified=0),
        PasswordRow(origin_url="https://b.example", action_url="", username="me",
                    password_blob=b"x", date_created=0, date_last_used=0,
                    date_password_modified=0),
        PasswordRow(origin_url="https://c.example", action_url="", username="me",
                    password_blob=b"x", date_created=0, date_last_used=0,
                    date_password_modified=0),
    ]
    monkeypatch.setattr(conflicts_mod, "read_password_rows", lambda _p: source_rows)

    # Target already has the GUID for https://a.example.
    target_logins = {
        "logins": [
            {"guid": _det_guid("https://a.example", "me")},
            {"guid": "{some-unrelated-uuid}"},
        ],
    }
    (fake_firefox_profile.profile_dir / "logins.json").write_text(
        json.dumps(target_logins), encoding="utf-8",
    )

    result = analyze_passwords(fake_chromium_profile, fake_firefox_profile)
    assert result.source_total == 3
    assert result.duplicates == 1
    assert result.new == 2
    assert result.failures == []
    # Invariant restored: source_total == duplicates + new.
    assert result.source_total == result.duplicates + result.new


def test_analyze_passwords_missing_target_treats_all_as_new(
    fake_chromium_profile, fake_firefox_profile, monkeypatch,
):
    """No logins.json in the target -> every source row is new."""

    rows = [
        PasswordRow(origin_url="https://x.example", action_url="", username="me",
                    password_blob=b"y", date_created=0, date_last_used=0,
                    date_password_modified=0),
    ]
    monkeypatch.setattr(conflicts_mod, "read_password_rows", lambda _p: rows)
    result = analyze_passwords(fake_chromium_profile, fake_firefox_profile)
    assert result.source_total == 1
    assert result.duplicates == 0
    assert result.new == 1


def test_analyze_passwords_corrupt_target_reports_failure_not_crash(
    fake_chromium_profile, fake_firefox_profile, monkeypatch,
):
    rows = [
        PasswordRow(origin_url="https://x.example", action_url="", username="me",
                    password_blob=b"y", date_created=0, date_last_used=0,
                    date_password_modified=0),
    ]
    monkeypatch.setattr(conflicts_mod, "read_password_rows", lambda _p: rows)
    (fake_firefox_profile.profile_dir / "logins.json").write_text(
        "not json", encoding="utf-8",
    )
    result = analyze_passwords(fake_chromium_profile, fake_firefox_profile)
    # Failures are surfaced rather than raised so the GUI can keep running.
    assert len(result.failures) == 1
    # Source still counted; duplicates treated as zero because we couldn't
    # read the target — caller can decide whether to proceed.
    assert result.source_total == 1
    assert result.new == 1


def test_analyze_cookies_counts_source_and_target(
    fake_chromium_profile, fake_firefox_profile,
):
    # Build a source cookies DB with 3 entries.
    src = fake_chromium_profile.profile_dir / "Cookies"
    conn = sqlite3.connect(str(src))
    try:
        conn.execute("CREATE TABLE cookies (host_key TEXT)")
        for h in ("a", "b", "c"):
            conn.execute("INSERT INTO cookies VALUES (?)", (h,))
        conn.commit()
    finally:
        conn.close()
    # Target cookies.sqlite with 5 entries the direct-write would replace.
    tgt = fake_firefox_profile.profile_dir / "cookies.sqlite"
    conn = sqlite3.connect(str(tgt))
    try:
        conn.execute("CREATE TABLE moz_cookies (id INTEGER)")
        for i in range(5):
            conn.execute("INSERT INTO moz_cookies VALUES (?)", (i,))
        conn.commit()
    finally:
        conn.close()

    result = analyze_cookies(fake_chromium_profile, fake_firefox_profile)
    assert result.source_total == 3
    assert result.new == 3            # cookies direct-write replaces wholesale
    assert result.duplicates == 5      # what gets displaced
    assert result.failures == []


def test_analyze_history_counts_source_and_target(
    fake_chromium_profile, fake_firefox_profile, make_history_db,
):
    # Forge a source History DB with 2 URLs.
    history = make_history_db([("https://a.example", "A", 1),
                                ("https://b.example", "B", 1)])
    history.rename(fake_chromium_profile.profile_dir / "History")
    # Forge a target places.sqlite with 7 URLs.
    tgt = fake_firefox_profile.profile_dir / "places.sqlite"
    conn = sqlite3.connect(str(tgt))
    try:
        conn.execute("CREATE TABLE moz_places (id INTEGER)")
        for i in range(7):
            conn.execute("INSERT INTO moz_places VALUES (?)", (i,))
        conn.commit()
    finally:
        conn.close()

    result = analyze_history(fake_chromium_profile, fake_firefox_profile)
    assert result.source_total == 2
    assert result.duplicates == 7
    assert result.new == 2
