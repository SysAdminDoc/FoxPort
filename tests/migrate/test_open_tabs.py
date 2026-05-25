"""Tests for the SNSS open-tabs URL extractor."""

import struct
from pathlib import Path
from types import SimpleNamespace

from foxport.migrate.open_tabs import (
    OpenTabsDirectWriteResult,
    _extract_url_from_navigation_payload,
    _extract_urls,
    _iter_snss_commands,
    _scan_urls_utf8,
    write_session_into_target,
)


def _build_command(command_id: int, payload: bytes) -> bytes:
    size = 1 + len(payload)
    return struct.pack("<H", size) + bytes([command_id]) + payload


def _build_nav_payload(url: str, index: int = 0) -> bytes:
    url_bytes = url.encode("utf-8")
    padding = (-len(url_bytes)) % 4
    return (
        struct.pack("<I", 1)                          # tab_id
        + struct.pack("<I", 12 + 4 + len(url_bytes) + padding)  # pickle size
        + struct.pack("<I", index)                    # nav index
        + struct.pack("<I", len(url_bytes))           # url length
        + url_bytes
        + b"\x00" * padding
    )


def _build_snss(commands: list[tuple[int, bytes]]) -> bytes:
    out = b"SNSS" + struct.pack("<I", 3)
    for cmd_id, payload in commands:
        out += _build_command(cmd_id, payload)
    return out


def test_iter_snss_commands_walks_clean_stream():
    blob = _build_snss([(6, b"hello"), (33, b"world!!!")])
    cmds = list(_iter_snss_commands(blob))
    assert cmds == [(6, b"hello"), (33, b"world!!!")]


def test_iter_snss_commands_rejects_bad_magic():
    blob = b"BLOB" + b"\x00" * 16
    assert list(_iter_snss_commands(blob)) == []


def test_iter_snss_commands_tolerates_truncation():
    blob = _build_snss([(6, b"complete")]) + b"\x10\x00"  # truncated header
    cmds = list(_iter_snss_commands(blob))
    assert cmds == [(6, b"complete")]


def test_extract_url_from_navigation_payload_happy_path():
    payload = _build_nav_payload("https://example.com/foo")
    assert _extract_url_from_navigation_payload(payload) == "https://example.com/foo"


def test_extract_url_from_navigation_payload_rejects_short():
    assert _extract_url_from_navigation_payload(b"") is None
    assert _extract_url_from_navigation_payload(b"\x00" * 8) is None


def test_extract_url_from_navigation_payload_rejects_non_http():
    """data://, javascript://, chrome://, ftp://"""
    bad_payload = _build_nav_payload("data:text/html,<h1>x</h1>")
    assert _extract_url_from_navigation_payload(bad_payload) is None


def test_extract_urls_structural_parser_wins():
    """When the structural parser finds URLs, the fallback isn't used."""
    blob = _build_snss([
        (6, _build_nav_payload("https://example.com/a")),
        (33, _build_nav_payload("https://example.com/b")),
        (9, b"some other command"),
    ])
    urls = _extract_urls(blob)
    assert urls == ["https://example.com/a", "https://example.com/b"]


def test_extract_urls_fallback_to_utf8_scan():
    """When no navigation commands, the UTF-8 regex fallback finds URLs."""
    blob = _build_snss([
        (9, b"prefix\x00\x00https://fallback.example/path more stuff"),
    ])
    urls = _extract_urls(blob)
    assert "https://fallback.example/path" in urls


def test_extract_urls_filters_internal_schemes():
    blob = _build_snss([
        (6, _build_nav_payload("https://kept.example/")),
        (9, b"junk chrome://gpu/ junk"),
    ])
    urls = _extract_urls(blob)
    assert "chrome://gpu/" not in urls
    assert "https://kept.example/" in urls


def test_scan_urls_utf8_dedupes():
    data = b"a https://x.com b https://x.com c"
    assert _scan_urls_utf8(data) == ["https://x.com"]


def test_write_session_into_target_returns_backup_path(tmp_path, monkeypatch):
    """write_session_into_target must return both target and backup paths so
    the worker can surface a "Reveal open_tabs backup" button on the Done
    screen — the v1.3.0 shape returned only the target path and the
    affordance silently disappeared even when a backup existed.
    """

    # Synthetic source profile dir with a single Tabs_ file containing one URL.
    source_dir = tmp_path / "source"
    sessions = source_dir / "Sessions"
    sessions.mkdir(parents=True)
    blob = _build_snss([(6, _build_nav_payload("https://kept.example/x"))])
    (sessions / "Tabs_1").write_bytes(blob)
    source = SimpleNamespace(
        label="Source",
        profile_dir=source_dir,
    )

    # Target profile dir with a pre-existing recovery.jsonlz4 so the backup
    # branch runs.
    target_dir = tmp_path / "target"
    backups_dir = target_dir / "sessionstore-backups"
    backups_dir.mkdir(parents=True)
    existing = backups_dir / "recovery.jsonlz4"
    existing.write_bytes(b"pre-existing session")
    target = SimpleNamespace(label="Target", profile_dir=target_dir)

    # Bypass the lock check — the synthetic profile has no parent.lock so
    # the helper would short-circuit on a real call.
    monkeypatch.setattr(
        "foxport.browsers.detect.is_firefox_profile_locked",
        lambda _profile: False,
    )

    staging = tmp_path / "staging"
    staging.mkdir()
    result = write_session_into_target(source, target, staging)

    assert isinstance(result, OpenTabsDirectWriteResult)
    assert result.target_path == backups_dir / "recovery.jsonlz4"
    assert result.backup_path is not None
    assert result.backup_path.exists(), \
        "backup file should have been copied next to the target"
    assert result.backup_path.name.startswith("recovery.foxport-backup-")
    assert result.backup_path.name.endswith(".jsonlz4")
