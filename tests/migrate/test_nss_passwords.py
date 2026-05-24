"""Tests for the NSS direct-write passwords safety contract.

We can't exercise the full migrate path without a real NSS shared lib
and a Firefox profile, but the data-loss-critical helper
``_read_existing_logins`` is pure I/O + JSON and worth pinning to
prevent the corrupt-file-silently-overwritten regression from sneaking
back in.
"""

from __future__ import annotations

import json

import pytest

from foxport.migrate.nss_passwords import (
    LoginsCorruptError,
    _EMPTY_LOGINS_STORE,
    _backup_target,
    _read_existing_logins,
)


def test_read_missing_file_returns_empty_store(tmp_path):
    """Brand-new target profile has no logins.json — we should return
    the empty-store skeleton, NOT raise."""
    data, guids = _read_existing_logins(tmp_path / "logins.json")
    assert data == _EMPTY_LOGINS_STORE
    assert guids == set()


def test_read_valid_file_returns_parsed(tmp_path):
    path = tmp_path / "logins.json"
    payload = {
        "nextId": 5,
        "logins": [
            {"id": 1, "guid": "{abc-123}", "hostname": "https://x"},
            {"id": 2, "guid": "{def-456}", "hostname": "https://y"},
        ],
        "potentiallyVulnerablePasswords": [],
        "dismissedBreachAlertsByLoginGUID": {},
        "version": 3,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    data, guids = _read_existing_logins(path)
    assert data["nextId"] == 5
    assert guids == {"{abc-123}", "{def-456}"}


def test_corrupt_json_refuses_to_overwrite(tmp_path):
    """The pre-audit code silently returned an empty store on parse failure,
    which then caused the migrator to OVERWRITE a real (but unreadable in
    that moment) logins.json with an empty one. We now raise so the caller
    aborts instead."""
    path = tmp_path / "logins.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(LoginsCorruptError, match="not valid JSON"):
        _read_existing_logins(path)


def test_missing_logins_key_refuses(tmp_path):
    path = tmp_path / "logins.json"
    path.write_text(json.dumps({"nextId": 1, "version": 3}), encoding="utf-8")
    with pytest.raises(LoginsCorruptError, match="missing the 'logins' key"):
        _read_existing_logins(path)


def test_non_object_root_refuses(tmp_path):
    """Top-level being a list / string is the same kind of bad shape — refuse."""
    path = tmp_path / "logins.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(LoginsCorruptError, match="missing the 'logins' key"):
        _read_existing_logins(path)


def test_backup_target_returns_none_when_missing(tmp_path):
    """The old code synthesized a fake ``.no-backup-needed`` path; we
    now return None so callers can render an honest message."""
    backup = _backup_target(tmp_path / "logins.json")
    assert backup is None


def test_backup_target_creates_timestamped_copy(tmp_path):
    src = tmp_path / "logins.json"
    src.write_text('{"logins": [], "version": 3}', encoding="utf-8")
    backup = _backup_target(src)
    assert backup is not None
    assert backup.exists()
    assert backup.name.startswith("logins.foxport-backup-")
    assert backup.name.endswith(".json")
    # Original should still be present (copy, not move).
    assert src.exists()
