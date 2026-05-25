"""Tests for the Settings/config persistence layer."""

import json

from foxport.config import (
    Settings,
    config_path,
    load_settings,
    reset_to_defaults,
    save_settings,
)


def test_defaults_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr("foxport.config.config_dir", lambda: tmp_path)
    s = Settings()
    save_settings(s)
    loaded = load_settings()
    assert loaded == s


def test_changed_values_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr("foxport.config.config_dir", lambda: tmp_path)
    s = Settings(
        output_dir="/tmp/foxport-test",
        mask_passwords_in_preview=False,
        allow_online_amo_lookup=False,
        default_dry_run=True,
        hibp_scan_default=True,
    )
    save_settings(s)
    loaded = load_settings()
    assert loaded == s


def test_missing_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("foxport.config.config_dir", lambda: tmp_path)
    loaded = load_settings()
    assert loaded == Settings()


def test_partial_json_file_returns_defaults_for_missing_keys(tmp_path, monkeypatch):
    monkeypatch.setattr("foxport.config.config_dir", lambda: tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"hibp_scan_default": True}))
    loaded = load_settings()
    assert loaded.hibp_scan_default is True
    assert loaded.allow_online_amo_lookup is True  # default


def test_corrupt_json_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("foxport.config.config_dir", lambda: tmp_path)
    (tmp_path / "config.json").write_text("not json at all {")
    assert load_settings() == Settings()


def test_unknown_keys_are_ignored(tmp_path, monkeypatch):
    """Forward-compat: old/new schema keys we don't recognize must not crash."""
    monkeypatch.setattr("foxport.config.config_dir", lambda: tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps({"hibp_scan_default": True, "future_unknown_key": "x"})
    )
    loaded = load_settings()
    assert loaded.hibp_scan_default is True


def test_nss_path_override_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr("foxport.config.config_dir", lambda: tmp_path)
    s = Settings(nss_path_override="C:/Portable Firefox/nss3.dll")
    save_settings(s)
    loaded = load_settings()
    assert loaded.nss_path_override == "C:/Portable Firefox/nss3.dll"


def test_reset_to_defaults_overwrites_persisted_values(tmp_path, monkeypatch):
    monkeypatch.setattr("foxport.config.config_dir", lambda: tmp_path)
    custom = Settings(
        output_dir="/tmp/custom",
        hibp_scan_default=True,
        nss_path_override="/opt/firefox/libnss3.so",
    )
    save_settings(custom)
    assert load_settings() == custom

    reset = reset_to_defaults()
    # Returned settings are the v1.3 defaults.
    assert reset == Settings()
    # And were persisted — a subsequent load gets the same defaults, not the
    # custom values we just clobbered.
    assert load_settings() == Settings()
