from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from foxport.browsers.detect import ChromiumProfile, FirefoxProfile
from foxport.passkeys import (
    inventory_chromium_passkeys,
    inventory_firefox_passkeys,
)


def _chromium_profile(tmp_path: Path) -> ChromiumProfile:
    profile_dir = tmp_path / "Default"
    profile_dir.mkdir(parents=True)
    return ChromiumProfile(
        browser="Chrome",
        family="chromium",
        profile_name="Default",
        profile_dir=profile_dir,
        local_state=tmp_path / "Local State",
        user_data_dir=tmp_path,
    )


def _firefox_profile(tmp_path: Path) -> FirefoxProfile:
    profile_dir = tmp_path / "abcd.default-release"
    profile_dir.mkdir(parents=True)
    return FirefoxProfile(
        browser="Firefox",
        family="firefox",
        profile_name="default-release",
        profile_dir=profile_dir,
        is_default=True,
    )


def test_chromium_inventory_counts_webauthn_sqlite_table(tmp_path: Path):
    profile = _chromium_profile(tmp_path)
    conn = sqlite3.connect(profile.profile_dir / "Login Data")
    try:
        conn.execute("CREATE TABLE webauthn_credentials (id INTEGER PRIMARY KEY, secret BLOB)")
        conn.executemany("INSERT INTO webauthn_credentials(secret) VALUES (?)", [(b"a",), (b"b",)])
        conn.execute("CREATE TABLE logins (origin_url TEXT)")
        conn.commit()
    finally:
        conn.close()

    result = inventory_chromium_passkeys(profile)

    assert result.count == 2
    assert result.stores[0].store == "Login Data:webauthn_credentials"
    assert result.stores[0].confidence == "table"


def test_chromium_inventory_counts_sync_leveldb_markers(tmp_path: Path):
    profile = _chromium_profile(tmp_path)
    leveldb = profile.profile_dir / "Sync Data" / "LevelDB"
    leveldb.mkdir(parents=True)
    (leveldb / "000003.log").write_bytes(
        b"...WebauthnCredentialSpecifics...WebauthnCredentialSpecifics..."
    )

    result = inventory_chromium_passkeys(profile)

    assert result.count == 2
    assert result.stores[0].store == "Sync Data/LevelDB"
    assert result.stores[0].confidence == "heuristic"
    assert result.notes


def test_firefox_inventory_counts_generic_passkey_table(tmp_path: Path):
    profile = _firefox_profile(tmp_path)
    conn = sqlite3.connect(profile.profile_dir / "webauthn.sqlite")
    try:
        conn.execute("CREATE TABLE passkey_credentials (id INTEGER PRIMARY KEY)")
        conn.executemany("INSERT INTO passkey_credentials DEFAULT VALUES", [(), (), ()])
        conn.commit()
    finally:
        conn.close()

    result = inventory_firefox_passkeys(profile)

    assert result.count == 3
    assert result.stores[0].store == "webauthn.sqlite:passkey_credentials"


def test_passkeys_inventory_cli_json(capsys, monkeypatch, tmp_path: Path):
    from foxport.cli import main

    chromium = _chromium_profile(tmp_path / "chrome")
    conn = sqlite3.connect(chromium.profile_dir / "Login Data")
    try:
        conn.execute("CREATE TABLE webauthn_credentials (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO webauthn_credentials DEFAULT VALUES")
        conn.commit()
    finally:
        conn.close()
    firefox = _firefox_profile(tmp_path / "firefox")

    monkeypatch.setattr("foxport.cli.detect_chromium", lambda: [chromium])
    monkeypatch.setattr("foxport.cli.detect_firefox", lambda: [firefox])

    rc = main(["passkeys", "inventory", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert rc == 0
    assert payload["schema_version"] == 1
    assert payload["command"] == "passkeys inventory"
    assert payload["export_supported"] is False
    assert payload["totals"]["profiles"] == 2
    assert payload["totals"]["profiles_with_passkeys"] == 1
    assert payload["totals"]["known_or_possible_passkeys"] == 1
    assert payload["profiles"][0]["has_passkeys"] is True
