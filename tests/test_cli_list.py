"""``list`` subcommand: JSON and detail-counts paths.

These tests verify the v1.3 CLI additions without needing a real browser
profile on disk — we stub out `detect_chromium` / `detect_firefox`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from foxport import cli as cli_mod
from foxport.cli import main


def _stub_detect(monkeypatch, chromium_profiles, firefox_profiles):
    monkeypatch.setattr(cli_mod, "detect_chromium", lambda: chromium_profiles)
    monkeypatch.setattr(cli_mod, "detect_firefox", lambda: firefox_profiles)
    monkeypatch.setattr(cli_mod, "is_chromium_running", lambda _p: False)
    monkeypatch.setattr(cli_mod, "is_firefox_profile_locked", lambda _p: False)


def test_list_json_shape_is_stable(capsys, monkeypatch, fake_chromium_profile):
    # Reuse the conftest Chromium profile; tests don't read its files.
    _stub_detect(monkeypatch, [fake_chromium_profile], [])

    rc = main(["list", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    # Schema is versioned so a future shape change can be detected by parsers.
    assert payload["schema_version"] == 1
    assert payload["foxport_version"]
    assert len(payload["chromium_sources"]) == 1
    src = payload["chromium_sources"][0]
    # The four documented fields are always present.
    assert set(src.keys()) == {"browser", "profile_name", "profile_dir", "running"}
    assert payload["firefox_targets"] == []


def test_list_json_never_includes_plaintext_secrets(capsys, monkeypatch, fake_chromium_profile):
    """Sanity guard: machine output must only carry path + status metadata."""

    _stub_detect(monkeypatch, [fake_chromium_profile], [])
    rc = main(["list", "--json"])
    assert rc == 0
    raw = capsys.readouterr().out
    # No password, no plaintext-looking strings beyond what we set in fixtures.
    for forbidden in ("password=", "encrypted_key", "hunter2"):
        assert forbidden not in raw


def test_list_detail_prints_per_category_counts(capsys, monkeypatch, fake_chromium_profile):
    # Stub the count helper so we don't need real SQLite files on disk.
    monkeypatch.setattr(cli_mod, "_profile_detail_counts",
                        lambda _p: [("logins", 12), ("urls", 999)])
    _stub_detect(monkeypatch, [fake_chromium_profile], [])

    rc = main(["list", "--detail"])
    out = capsys.readouterr().out
    assert rc == 0
    # The "logins:" / "urls:" lines appear indented under the profile dir.
    assert "logins: 12" in out
    assert "urls: 999" in out


def test_list_without_detail_omits_counts(capsys, monkeypatch, fake_chromium_profile):
    monkeypatch.setattr(cli_mod, "_profile_detail_counts",
                        lambda _p: [("logins", 12)])
    _stub_detect(monkeypatch, [fake_chromium_profile], [])
    rc = main(["list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "logins:" not in out
