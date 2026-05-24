"""Shared pytest fixtures for FoxPort tests."""

from __future__ import annotations

import json
import sqlite3
import struct
from pathlib import Path

import pytest


# Synthetic Chromium WebKit µs since 1601-01-01 UTC for the moment when
# Unix epoch began (1970-01-01 UTC). All test fixtures use this anchor.
CHROME_EPOCH_OFFSET_MICROS = 11_644_473_600 * 1_000_000


@pytest.fixture
def make_bookmarks_json(tmp_path: Path):
    """Build a Chromium ``Bookmarks`` JSON file with the bookmark tree
    supplied as a dict of `{root_key: [(folder_path_tuple, [(title, url), ...]) ...]}`.
    """

    def _maker(root_data: dict) -> Path:
        # Chrome's roots key shape.
        roots: dict[str, dict] = {}
        for root_key, items in root_data.items():
            children: list[dict] = []
            for url_tuple in items:
                title, url = url_tuple
                children.append({
                    "type": "url",
                    "name": title,
                    "url": url,
                    "date_added": str(CHROME_EPOCH_OFFSET_MICROS),
                })
            roots[root_key] = {
                "type": "folder",
                "name": root_key,
                "children": children,
                "date_added": str(CHROME_EPOCH_OFFSET_MICROS),
                "date_modified": str(CHROME_EPOCH_OFFSET_MICROS),
            }
        path = tmp_path / "Bookmarks"
        path.write_text(json.dumps({"roots": roots, "version": 1}), encoding="utf-8")
        return path

    return _maker


@pytest.fixture
def make_history_db(tmp_path: Path):
    """Build a minimal Chromium ``History`` SQLite with given URLs + visits."""

    def _maker(rows: list[tuple[str, str, int]]) -> Path:
        """rows: list of (url, title, visit_count)."""
        path = tmp_path / "History"
        conn = sqlite3.connect(str(path))
        try:
            conn.executescript("""
                CREATE TABLE urls (
                    id INTEGER PRIMARY KEY,
                    url LONGVARCHAR,
                    title LONGVARCHAR,
                    visit_count INTEGER DEFAULT 0,
                    typed_count INTEGER DEFAULT 0,
                    last_visit_time INTEGER NOT NULL,
                    hidden INTEGER DEFAULT 0
                );
                CREATE TABLE visits (
                    id INTEGER PRIMARY KEY,
                    url INTEGER NOT NULL,
                    visit_time INTEGER NOT NULL,
                    from_visit INTEGER,
                    transition INTEGER DEFAULT 0
                );
            """)
            for url, title, visits in rows:
                cur = conn.execute(
                    "INSERT INTO urls (url, title, visit_count, last_visit_time) "
                    "VALUES (?, ?, ?, ?)",
                    (url, title, visits, CHROME_EPOCH_OFFSET_MICROS),
                )
                url_id = cur.lastrowid
                for _ in range(visits):
                    conn.execute(
                        "INSERT INTO visits (url, visit_time) VALUES (?, ?)",
                        (url_id, CHROME_EPOCH_OFFSET_MICROS),
                    )
            conn.commit()
        finally:
            conn.close()
        return path

    return _maker


@pytest.fixture
def make_snss_tabs(tmp_path: Path):
    """Build a synthetic SNSS Tabs_ file with a single
    ``kCommandUpdateTabNavigation`` command per URL.

    Wire format per command:
        uint16_le size + uint8 command_id + payload
    Payload for nav (12-byte header + 4-byte url_len + url bytes + padding):
        4 bytes tab_id (any int)
        4 bytes pickle payload size (unused by parser)
        4 bytes navigation index
        4 bytes url length
        url bytes (UTF-8, padded to 4-byte multiple)
    """

    def _maker(urls: list[str], command_id: int = 6) -> Path:
        buf = bytearray()
        buf += b"SNSS"
        buf += struct.pack("<I", 3)  # version 3
        for i, url in enumerate(urls):
            url_bytes = url.encode("utf-8")
            url_len = len(url_bytes)
            padding = (-url_len) % 4
            payload = (
                struct.pack("<I", i + 1)        # tab_id
                + struct.pack("<I", 12 + 4 + url_len + padding)  # pickle size
                + struct.pack("<I", 0)          # nav index
                + struct.pack("<I", url_len)    # url length
                + url_bytes
                + b"\x00" * padding
            )
            size = 1 + len(payload)             # command_id + payload bytes
            buf += struct.pack("<H", size)
            buf += bytes([command_id])
            buf += payload
        path = tmp_path / "Tabs_1234567890"
        path.write_bytes(bytes(buf))
        return path

    return _maker


@pytest.fixture
def fake_chromium_profile(tmp_path: Path):
    """Construct a minimal ``ChromiumProfile`` rooted at ``tmp_path/profile``."""
    from foxport.browsers.detect import ChromiumProfile

    user_data = tmp_path / "User Data"
    profile_dir = user_data / "Default"
    profile_dir.mkdir(parents=True)
    (user_data / "Local State").write_text(
        json.dumps({"os_crypt": {"encrypted_key": ""}}), encoding="utf-8"
    )
    (profile_dir / "Preferences").write_text("{}", encoding="utf-8")
    return ChromiumProfile(
        browser="Test Browser",
        family="chromium",
        profile_name="Default",
        profile_dir=profile_dir,
        local_state=user_data / "Local State",
        user_data_dir=user_data,
    )
