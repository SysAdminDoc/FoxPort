"""Tests for the Settings/config persistence layer."""

import json

from foxport.config import Settings, load_settings, save_settings, config_path


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
