"""Cookies migration — Chromium ``Cookies`` SQLite → Firefox ``cookies.sqlite``.

The DB lives at one of:
    %LOCALAPPDATA%\\<browser>\\User Data\\<profile>\\Network\\Cookies   (Chromium 96+)
    %LOCALAPPDATA%\\<browser>\\User Data\\<profile>\\Cookies            (legacy fallback)

Each ``encrypted_value`` blob is AES-256-GCM with the same master key used for
``Login Data`` (loaded from ``Local State.os_crypt.encrypted_key``). Chromium
130+ silently prepended the SHA-256 of the cookie's ``host_key`` to the
plaintext — we detect via ``meta.value`` for ``key='version'`` and strip 32
bytes when the DB version is ≥ 24.

Firefox's ``cookies.sqlite`` schema (v17) is recreated from scratch. We never
write into an existing file — the user gets a standalone DB to swap in (after
backing up the original) when Firefox is closed.

Times: Chromium stores ``creation_utc``, ``last_access_utc``, ``expires_utc``
as microseconds since 1601-01-01 UTC. Firefox stores ``creationTime``,
``lastAccessed`` as microseconds since 1970-01-01 UTC, but ``expiry`` as
**seconds** since 1970-01-01 UTC (despite the misleading inline comment in
``CookiePersistentStorage.cpp``).
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from foxport.browsers.detect import ChromiumProfile
from foxport.crypto.dpapi import (
    ChromiumKey,
    DecryptionError,
    decrypt_value,
    load_master_key,
)

# Chromium time = µs since 1601-01-01 UTC. Firefox time = µs (or s) since
# 1970-01-01 UTC.
_CHROME_TO_UNIX_MICROS = 11_644_473_600_000_000


def _chrome_micros_to_firefox_micros(chrome_us: int) -> int:
    if chrome_us <= 0:
        return 0
    return max(0, chrome_us - _CHROME_TO_UNIX_MICROS)


def _chrome_micros_to_unix_seconds(chrome_us: int) -> int:
    if chrome_us <= 0:
        return 0
    return max(0, (chrome_us - _CHROME_TO_UNIX_MICROS) // 1_000_000)


# Firefox cookies.sqlite schema (version 17). Faithful to mozilla-central's
# CookiePersistentStorage.cpp -- additional columns can land in future Firefox
# versions but new columns get sensible defaults so older schemas open cleanly.
_FIREFOX_COOKIES_SCHEMA = """
CREATE TABLE moz_cookies (
    id INTEGER PRIMARY KEY,
    originAttributes TEXT NOT NULL DEFAULT '',
    name TEXT,
    value TEXT,
    host TEXT,
    path TEXT,
    expiry INTEGER,
    lastAccessed INTEGER,
    creationTime INTEGER,
    isSecure INTEGER,
    isHttpOnly INTEGER,
    inBrowserElement INTEGER DEFAULT 0,
    sameSite INTEGER DEFAULT 0,
    rawSameSite INTEGER DEFAULT 0,
    schemeMap INTEGER DEFAULT 0,
    isPartitionedAttributeSet INTEGER DEFAULT 0,
    CONSTRAINT moz_uniqueid UNIQUE (name, host, path, originAttributes)
);
CREATE INDEX moz_basedomain ON moz_cookies (host);
PRAGMA user_version = 17;
"""


@dataclass
class CookieResult:
    """Outcome of a cookies migration run."""

    sqlite_path: Path
    total: int
    decrypted: int
    failed: int
    failures: list[str] = field(default_factory=list)


def _cookies_db_path(profile: ChromiumProfile) -> Path | None:
    """Locate the Cookies DB for this profile (Network/ subdir on Chromium 96+)."""
    candidates = (
        profile.profile_dir / "Network" / "Cookies",
        profile.profile_dir / "Cookies",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _copy_for_read(src: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="foxport_cookies_"))
    dest = tmp / src.name
    shutil.copy2(src, dest)
    for suffix in ("-wal", "-shm"):
        sibling = src.with_name(src.name + suffix)
        if sibling.exists():
            shutil.copy2(sibling, dest.with_name(dest.name + suffix))
    return dest


def _read_meta_version(conn: sqlite3.Connection) -> int:
    """Read meta.value where key='version'. Returns 0 if absent."""
    try:
        cur = conn.execute("SELECT value FROM meta WHERE key = 'version'")
        row = cur.fetchone()
    except sqlite3.DatabaseError:
        return 0
    if not row:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def _scheme_map_from_secure(is_secure: int) -> int:
    """schemeMap is a bitfield: 1=http, 2=https, 4=file. Default to https/http."""
    return 2 if is_secure else 1


def _ensure_host_format(host_key: str, is_host_only: bool) -> str:
    """Firefox uses leading '.' for domain cookies, bare host for host-only."""
    if not host_key:
        return ""
    if is_host_only:
        return host_key.lstrip(".")
    if not host_key.startswith("."):
        return "." + host_key
    return host_key


def _iter_decrypted_cookies(
    profile: ChromiumProfile,
    key: ChromiumKey,
    failures: list[str],
) -> Iterator[tuple[dict, str]]:
    """Yield (cookie_row_dict, plaintext_value) tuples for every cookie row."""
    src = _cookies_db_path(profile)
    if not src:
        return
    copy = _copy_for_read(src)
    try:
        conn = sqlite3.connect(str(copy))
        try:
            db_version = _read_meta_version(conn)
            strip_host_key_prefix = db_version >= 24
            cur = conn.execute(
                "SELECT creation_utc, host_key, name, value, encrypted_value, path, "
                "expires_utc, is_secure, is_httponly, last_access_utc, "
                "is_persistent, samesite "
                "FROM cookies"
            )
            for row in cur:
                (creation_utc, host_key, name, value, encrypted_value, path,
                 expires_utc, is_secure, is_httponly, last_access_utc,
                 is_persistent, samesite) = row
                blob = bytes(encrypted_value) if encrypted_value else b""
                plaintext = value or ""
                if blob:
                    try:
                        plaintext = decrypt_value(blob, key)
                    except DecryptionError as exc:
                        failures.append(f"{host_key} / {name}: {exc}")
                        continue
                    if strip_host_key_prefix and len(plaintext) >= 32:
                        plaintext = plaintext[32:]
                # Chromium's is_host_only is implied by leading dot in host_key.
                is_host_only = not (host_key or "").startswith(".")
                yield (
                    {
                        "host": _ensure_host_format(host_key or "", is_host_only),
                        "name": name or "",
                        "path": path or "/",
                        "creationTime": _chrome_micros_to_firefox_micros(creation_utc or 0),
                        "lastAccessed": _chrome_micros_to_firefox_micros(last_access_utc or 0),
                        "expiry": _chrome_micros_to_unix_seconds(expires_utc or 0),
                        "isSecure": 1 if is_secure else 0,
                        "isHttpOnly": 1 if is_httponly else 0,
                        "sameSite": int(samesite or 0) if samesite is not None else 0,
                        "schemeMap": _scheme_map_from_secure(is_secure),
                    },
                    plaintext,
                )
        finally:
            conn.close()
    finally:
        shutil.rmtree(copy.parent, ignore_errors=True)


def migrate_cookies(
    profile: ChromiumProfile,
    out_dir: Path,
    *,
    dry_run: bool = False,
) -> CookieResult:
    """Decrypt all cookies in ``profile`` and emit a Firefox-format
    ``cookies.sqlite`` in ``out_dir``. Dry-run reports counts only."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = out_dir / "cookies.sqlite"
    if sqlite_path.exists() and not dry_run:
        sqlite_path.unlink()

    failures: list[str] = []
    key = load_master_key(profile.local_state, browser_display=profile.browser)

    if dry_run:
        total = 0
        decrypted = 0
        for _row, _plain in _iter_decrypted_cookies(profile, key, failures):
            decrypted += 1
            total += 1
        # Failures-only cookies don't count toward total via the iterator;
        # add them in explicitly.
        total += len(failures)
        return CookieResult(
            sqlite_path=sqlite_path,
            total=total,
            decrypted=decrypted,
            failed=len(failures),
            failures=failures,
        )

    decrypted = 0
    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.executescript(_FIREFOX_COOKIES_SCHEMA)
        conn.commit()
        with conn:
            for row, plaintext in _iter_decrypted_cookies(profile, key, failures):
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO moz_cookies "
                        "(originAttributes, name, value, host, path, expiry, "
                        " lastAccessed, creationTime, isSecure, isHttpOnly, "
                        " inBrowserElement, sameSite, rawSameSite, schemeMap, "
                        " isPartitionedAttributeSet) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 0)",
                        (
                            "",
                            row["name"],
                            plaintext,
                            row["host"],
                            row["path"],
                            row["expiry"],
                            row["lastAccessed"],
                            row["creationTime"],
                            row["isSecure"],
                            row["isHttpOnly"],
                            row["sameSite"],
                            row["sameSite"],
                            row["schemeMap"],
                        ),
                    )
                    decrypted += 1
                except sqlite3.IntegrityError as exc:
                    # UNIQUE(name, host, path, originAttributes) — skip dupes.
                    failures.append(f"dup {row['host']} / {row['name']}: {exc}")
    finally:
        conn.close()

    return CookieResult(
        sqlite_path=sqlite_path,
        total=decrypted + len(failures),
        decrypted=decrypted,
        failed=len(failures),
        failures=failures,
    )
