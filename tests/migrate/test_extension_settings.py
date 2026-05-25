"""Allowlisted extension settings export tests."""

from __future__ import annotations

import json

import pytest

from foxport.migrate.extension_settings import (
    SUPPORTED_EXTENSION_SETTINGS,
    installed_supported_settings,
    migrate_extension_settings,
    parse_extension_settings_selection,
)


UBLOCK_ID = "cjpalhdlnbpafiamejdnhcphjbkeiagm"
STYLUS_ID = "clngdbkpkpeebahjckkjfobafhncgmne"
BITWARDEN_ID = "nngceckbapebfimnlniiiahkandclblb"


def _install_extension(profile, ext_id: str, name: str) -> None:
    root = profile.profile_dir / "Extensions" / ext_id / "1.0.0"
    root.mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps({
            "name": name,
            "version": "1.0.0",
            "description": "",
            "permissions": ["storage"],
        }),
        encoding="utf-8",
    )


def test_parse_extension_settings_selection():
    assert parse_extension_settings_selection("ublock, bitwarden") == {
        "ublock",
        "bitwarden",
    }
    assert parse_extension_settings_selection("all") == set(SUPPORTED_EXTENSION_SETTINGS)
    with pytest.raises(ValueError):
        parse_extension_settings_selection("unknown")


def test_installed_supported_settings_detects_known_extension(fake_chromium_profile):
    _install_extension(fake_chromium_profile, UBLOCK_ID, "uBlock Origin")
    from foxport.browsers.chromium import read_extensions

    installed = installed_supported_settings(read_extensions(fake_chromium_profile))
    assert set(installed) == {"ublock"}
    assert installed["ublock"].extension_id == UBLOCK_ID


def test_migrate_extension_settings_exports_allowlisted_fields(
    fake_chromium_profile,
    tmp_path,
):
    _install_extension(fake_chromium_profile, UBLOCK_ID, "uBlock Origin")
    _install_extension(fake_chromium_profile, STYLUS_ID, "Stylus")
    _install_extension(fake_chromium_profile, BITWARDEN_ID, "Bitwarden")

    ubo_dir = fake_chromium_profile.profile_dir / "Local Extension Settings" / UBLOCK_ID
    ubo_dir.mkdir(parents=True)
    (ubo_dir / "000001.log").write_text(
        json.dumps({
            "selectedFilterLists": ["easylist", "ublock-filters"],
            "userFilters": "||ads.example^\n@@||allowed.example^",
            "netWhitelist": "trusted.example",
            "unrelatedSecret": "do not export",
        }),
        encoding="utf-8",
    )

    stylus_dir = (
        fake_chromium_profile.profile_dir
        / "IndexedDB"
        / f"chrome-extension_{STYLUS_ID}_0.indexeddb.leveldb"
    )
    stylus_dir.mkdir(parents=True)
    (stylus_dir / "000003.log").write_text(
        json.dumps({
            "styles": [
                {
                    "id": 7,
                    "name": "Example dark",
                    "enabled": True,
                    "sections": [{"code": "body { color: white; }"}],
                    "privateField": "do not export",
                },
            ],
        }),
        encoding="utf-8",
    )

    bw_dir = fake_chromium_profile.profile_dir / "Local Extension Settings" / BITWARDEN_ID
    bw_dir.mkdir(parents=True)
    (bw_dir / "LOG").write_text(
        json.dumps({
            "environmentUrls": {
                "base": "https://vault.example.com",
                "api": "https://api.example.com",
            },
            "accessToken": "do not export",
        }),
        encoding="utf-8",
    )

    result = migrate_extension_settings(
        fake_chromium_profile,
        tmp_path / "out",
        selected={"ublock", "stylus", "bitwarden"},
    )

    assert result.count == 3
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    exported = {item["key"]: item for item in payload["exported"]}

    assert exported["ublock"]["data"]["selectedFilterLists"] == [
        "easylist",
        "ublock-filters",
    ]
    assert "unrelatedSecret" not in json.dumps(exported["ublock"])
    assert exported["stylus"]["data"]["styles"][0]["name"] == "Example dark"
    assert "privateField" not in json.dumps(exported["stylus"])
    assert exported["bitwarden"]["data"]["environment_urls"]["base"] == (
        "https://vault.example.com"
    )
    assert "accessToken" not in json.dumps(exported["bitwarden"])


def test_migrate_extension_settings_dry_run_writes_nothing(
    fake_chromium_profile,
    tmp_path,
):
    _install_extension(fake_chromium_profile, UBLOCK_ID, "uBlock Origin")
    storage_dir = fake_chromium_profile.profile_dir / "Local Extension Settings" / UBLOCK_ID
    storage_dir.mkdir(parents=True)
    (storage_dir / "000001.log").write_text(
        json.dumps({"selectedFilterLists": ["easylist"]}),
        encoding="utf-8",
    )

    result = migrate_extension_settings(
        fake_chromium_profile,
        tmp_path / "out",
        selected={"ublock"},
        dry_run=True,
    )

    assert result.count == 1
    assert not result.json_path.exists()
