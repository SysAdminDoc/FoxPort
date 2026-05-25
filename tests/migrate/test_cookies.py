"""Tests for the cookies.sqlite emitter."""

import sqlite3
from types import SimpleNamespace

from foxport.crypto.dpapi import ChromiumKey
from foxport.migrate.cookies import _FIREFOX_COOKIES_SCHEMA
from foxport.migrate.nss_cookies import write_cookies_into_target


def test_schema_pragma_version():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_FIREFOX_COOKIES_SCHEMA)
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    assert ver == 17


def test_schema_includes_updateTime_column():
    """v17 added updateTime — Firefox 138 silently triggers re-create otherwise."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(_FIREFOX_COOKIES_SCHEMA)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(moz_cookies)").fetchall()]
    assert "updateTime" in cols, cols


def test_chrome_130_host_key_prefix_is_stripped_in_bytes_space(tmp_path, monkeypatch):
    """Chrome 130+ prepends raw SHA-256(host_key) (32 bytes) to the cookie
    plaintext. Pre-v1.3.2 the migrator stripped 32 *characters* AFTER a
    UTF-8 decode-replace — which chewed the wrong amount because
    arbitrary SHA-256 bytes don't map 1:1 to chars. Pin the bytes-space
    strip so the recovered cookie value matches the original.

    We exercise the path by monkeypatching ``decrypt_value_bytes`` so the
    test doesn't need a real AES key + DPAPI flow on Linux/macOS.
    """

    import sys
    from foxport.migrate import cookies as cookies_mod

    real_value = b"session-token-payload-content"  # what Chrome stored
    # 16 × (0xC3 0xA9) — the UTF-8 encoding of 'é' — gives a 32-byte SHA-256
    # prefix that decodes to only 16 characters. The old character-slice
    # bug would chew 32 *chars* from a 16+N-char string, losing the first
    # 16 chars of real plaintext. The bytes-space strip leaves real_value
    # untouched.
    sha256_prefix = b"\xc3\xa9" * 16
    decoded_chars = (sha256_prefix + real_value).decode("utf-8", errors="replace")
    assert len(decoded_chars) == 16 + len(real_value), (
        "fixture should decode to fewer chars than bytes to exercise the bug class"
    )

    monkeypatch.setattr(cookies_mod, "decrypt_value_bytes",
                        lambda blob, key: sha256_prefix + real_value)
    monkeypatch.setattr(cookies_mod, "load_master_key", lambda *a, **kw: ChromiumKey(key=b"x" * 32))

    # Stand up the minimum profile + Cookies DB. We only need ONE row + a
    # meta.value=24 to trigger the Chrome 130 strip branch.
    profile_dir = tmp_path / "Default"
    profile_dir.mkdir()
    db = profile_dir / "Cookies"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE meta (key TEXT, value TEXT)"
        )
        conn.execute("INSERT INTO meta VALUES ('version', '24')")
        conn.execute(
            "CREATE TABLE cookies ("
            " creation_utc INTEGER, host_key TEXT, name TEXT, value TEXT,"
            " encrypted_value BLOB, path TEXT, expires_utc INTEGER,"
            " is_secure INTEGER, is_httponly INTEGER, last_access_utc INTEGER,"
            " is_persistent INTEGER, samesite INTEGER"
            ")"
        )
        conn.execute(
            "INSERT INTO cookies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (0, "example.com", "sid", "", b"v10nonce-and-blob", "/", 0, 0, 0, 0, 1, 0),
        )
        conn.commit()
    finally:
        conn.close()

    from foxport.browsers.detect import ChromiumProfile
    profile = ChromiumProfile(
        browser="Chrome", family="chromium", profile_name="Default",
        profile_dir=profile_dir, local_state=tmp_path / "Local State",
        user_data_dir=tmp_path,
    )

    # Force the Windows strip-path. (Skip on non-win32 — the strip is
    # gated on sys.platform; the test still pins the logic by faking it.)
    monkeypatch.setattr(cookies_mod.sys, "platform", "win32")

    rows = list(cookies_mod._iter_decrypted_cookies(profile, ChromiumKey(key=b"x" * 32), []))
    assert len(rows) == 1
    _row, plaintext = rows[0]
    assert plaintext == real_value.decode("utf-8"), (
        f"prefix not stripped correctly: got {plaintext!r}"
    )


def test_schema_unique_constraint():
    """UNIQUE (name, host, path, originAttributes) must exist or imports dupe."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(_FIREFOX_COOKIES_SCHEMA)
    # sqlite enforces the constraint via an auto-generated index; check the
    # behavior directly by inserting a duplicate row and expecting IntegrityError.
    conn.execute(
        "INSERT INTO moz_cookies (originAttributes, name, host, path) "
        "VALUES ('', 'sid', 'example.com', '/')"
    )
    try:
        conn.execute(
            "INSERT INTO moz_cookies (originAttributes, name, host, path) "
            "VALUES ('', 'sid', 'example.com', '/')"
        )
    except sqlite3.IntegrityError:
        return  # constraint fires
    raise AssertionError("Duplicate insert succeeded — UNIQUE constraint missing")


def test_write_cookies_into_target_merge_preserves_existing_rows(
    fake_chromium_profile, tmp_path, monkeypatch,
):
    """Merge mode adds source cookies absent by host/path/name only."""

    from foxport.migrate import cookies as cookies_mod

    monkeypatch.setattr(
        cookies_mod,
        "load_master_key",
        lambda *a, **kw: ChromiumKey(key=b"x" * 32),
    )

    source_db = fake_chromium_profile.profile_dir / "Cookies"
    conn = sqlite3.connect(str(source_db))
    try:
        conn.execute(
            "CREATE TABLE cookies ("
            " creation_utc INTEGER, host_key TEXT, name TEXT, value TEXT,"
            " encrypted_value BLOB, path TEXT, expires_utc INTEGER,"
            " is_secure INTEGER, is_httponly INTEGER, last_access_utc INTEGER,"
            " is_persistent INTEGER, samesite INTEGER"
            ")"
        )
        conn.execute(
            "INSERT INTO cookies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (0, "example.com", "sid", "source", b"", "/", 0, 0, 0, 0, 1, 0),
        )
        conn.execute(
            "INSERT INTO cookies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (0, "new.example", "fresh", "fresh-value", b"", "/", 0, 1, 0, 0, 1, 0),
        )
        conn.commit()
    finally:
        conn.close()

    target_dir = tmp_path / "target"
    target_dir.mkdir()
    target_db = target_dir / "cookies.sqlite"
    conn = sqlite3.connect(str(target_db))
    try:
        conn.executescript(_FIREFOX_COOKIES_SCHEMA)
        conn.execute(
            "INSERT INTO moz_cookies (originAttributes, name, value, host, path) "
            "VALUES ('', 'sid', 'target-kept', 'example.com', '/')"
        )
        conn.execute(
            "INSERT INTO moz_cookies (originAttributes, name, value, host, path) "
            "VALUES ('', 'target-only', 'target-only', 'target.example', '/')"
        )
        conn.commit()
    finally:
        conn.close()

    target = SimpleNamespace(
        label="Target",
        profile_dir=target_dir,
        lock_file=target_dir / "parent.lock",
    )
    result = write_cookies_into_target(
        fake_chromium_profile,
        target,
        tmp_path / "staging",
        merge=True,
    )

    assert result.merged is True
    assert result.inserted == 1
    assert result.skipped_existing == 1
    assert result.backup_path is not None and result.backup_path.exists()

    conn = sqlite3.connect(str(target_db))
    try:
        rows = conn.execute(
            "SELECT host, name, value FROM moz_cookies ORDER BY host, name"
        ).fetchall()
    finally:
        conn.close()

    assert rows == [
        ("example.com", "sid", "target-kept"),
        ("new.example", "fresh", "fresh-value"),
        ("target.example", "target-only", "target-only"),
    ]
