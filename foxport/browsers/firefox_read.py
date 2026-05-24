"""Read Firefox-family profile artifacts: passwords (via NSS), bookmarks
(places.sqlite), and installed extensions (extensions.json).

The Windows-side reads still work cross-platform because Firefox uses the
same on-disk layout everywhere. Decryption uses :mod:`foxport.crypto.nss`
which already handles per-platform DLL/dylib/.so lookup.
"""

from __future__ import annotations

import base64
import json
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from foxport.browsers.detect import FirefoxProfile, is_firefox_profile_locked
from foxport.crypto.nss import NSSError, NSSSession, open_session


@dataclass(frozen=True)
class FirefoxLogin:
    """One decrypted entry from logins.json."""

    hostname: str
    form_submit_url: str
    http_realm: str | None
    username: str
    password: str
    guid: str
    time_created_ms: int
    time_last_used_ms: int
    time_password_changed_ms: int
    times_used: int


@dataclass(frozen=True)
class FirefoxBookmark:
    """Flattened bookmark — folder hierarchy walked into a path."""

    folder_path: tuple[str, ...]   # e.g. ("toolbar", "News")
    title: str
    url: str
    date_added_us: int             # microseconds since epoch
    date_modified_us: int


@dataclass(frozen=True)
class FirefoxExtension:
    """One installed Firefox extension as recorded in extensions.json."""

    guid: str                       # AMO GUID, e.g. "uBlock0@raymondhill.net"
    name: str
    version: str
    enabled: bool
    description: str
    homepage: str | None


def read_firefox_logins(profile: FirefoxProfile, master_password: str = "") -> Iterator[FirefoxLogin]:
    """Open an NSS session against the profile and decrypt every login.

    The profile must be closed (Firefox holds an exclusive NSS lock).
    Raises :class:`NSSError` on master-password mismatch or DLL load failure.
    """
    if is_firefox_profile_locked(profile):
        raise NSSError(
            f"profile {profile.label} is locked — close Firefox before reading logins"
        )
    logins_path = profile.profile_dir / "logins.json"
    if not logins_path.is_file():
        return
    try:
        data = json.loads(logins_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    session = open_session(profile, master_password=master_password)
    with session:
        from foxport.crypto.nss import (
            SECSuccess,
            _SECItem,
        )
        # We need decrypt direction here — NSS exposes PK11SDR_Decrypt.
        # The shared NSSLibrary doesn't bind it by default, so do it inline.
        dec = session._lib.handle.PK11SDR_Decrypt  # noqa: SLF001
        from ctypes import POINTER, byref, c_int, c_void_p
        dec.argtypes = [POINTER(_SECItem), POINTER(_SECItem), c_void_p]
        dec.restype = c_int

        def decrypt(encoded: str) -> str:
            blob = base64.b64decode(encoded)
            from ctypes import c_uint, cast, create_string_buffer
            buf = create_string_buffer(blob)
            data_item = _SECItem(type=0, data=cast(buf, c_void_p).value, len=c_uint(len(blob)).value)
            result = _SECItem(type=0, data=None, len=0)
            rv = dec(byref(data_item), byref(result), None)
            if rv != SECSuccess:
                raise NSSError(f"PK11SDR_Decrypt failed (rv={rv})")
            try:
                import ctypes
                plain = ctypes.string_at(result.data, result.len)
            finally:
                session._lib.handle.SECITEM_FreeItem(byref(result), 0)  # noqa: SLF001
            return plain.decode("utf-8", errors="replace")

        for login in data.get("logins", []) or []:
            try:
                yield FirefoxLogin(
                    hostname=login.get("hostname") or "",
                    form_submit_url=login.get("formSubmitURL") or "",
                    http_realm=login.get("httpRealm"),
                    username=decrypt(login.get("encryptedUsername") or ""),
                    password=decrypt(login.get("encryptedPassword") or ""),
                    guid=login.get("guid") or "",
                    time_created_ms=int(login.get("timeCreated") or 0),
                    time_last_used_ms=int(login.get("timeLastUsed") or 0),
                    time_password_changed_ms=int(login.get("timePasswordChanged") or 0),
                    times_used=int(login.get("timesUsed") or 0),
                )
            except NSSError:
                # Skip broken entries rather than aborting the whole import.
                continue


def _copy_for_read(src: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="foxport_ffread_"))
    dest = tmp / src.name
    shutil.copy2(src, dest)
    for suffix in ("-wal", "-shm"):
        sibling = src.with_name(src.name + suffix)
        if sibling.exists():
            shutil.copy2(sibling, dest.with_name(dest.name + suffix))
    return dest


# Firefox root bookmark GUIDs (12-char underscore-padded).
_ROOT_GUIDS = {
    "toolbar_____":  "toolbar",
    "menu________":  "menu",
    "unfiled_____":  "unfiled",
    "mobile______":  "mobile",
}


def read_firefox_bookmarks(profile: FirefoxProfile) -> list[FirefoxBookmark]:
    """Walk ``places.sqlite`` and return every bookmark with its folder path."""
    places = profile.profile_dir / "places.sqlite"
    if not places.is_file():
        return []
    copy = _copy_for_read(places)
    try:
        conn = sqlite3.connect(str(copy))
        try:
            # Build a map of bookmark.id -> (parent, title, type, fk, dateAdded, lastModified, guid).
            rows = conn.execute(
                "SELECT id, parent, title, type, fk, dateAdded, lastModified, guid "
                "FROM moz_bookmarks ORDER BY id"
            ).fetchall()
            by_id: dict[int, tuple] = {r[0]: r for r in rows}

            url_for_place: dict[int, str] = {
                p[0]: p[1] for p in conn.execute("SELECT id, url FROM moz_places").fetchall()
            }
        finally:
            conn.close()
    finally:
        shutil.rmtree(copy.parent, ignore_errors=True)

    # Build path-from-root for every folder id.
    def path_for(bookmark_id: int) -> tuple[str, ...]:
        path: list[str] = []
        cur = bookmark_id
        seen: set[int] = set()
        while cur and cur not in seen:
            seen.add(cur)
            row = by_id.get(cur)
            if not row:
                break
            _id, parent, title, _type, _fk, _da, _lm, guid = row
            if guid in _ROOT_GUIDS:
                path.insert(0, _ROOT_GUIDS[guid])
                break
            if title:
                path.insert(0, title)
            cur = parent or 0
        return tuple(path)

    out: list[FirefoxBookmark] = []
    for row in rows:
        _id, parent, title, kind, fk, date_added, last_modified, _guid = row
        if kind != 1 or not fk:    # 1 = URL leaf
            continue
        url = url_for_place.get(fk)
        if not url:
            continue
        out.append(FirefoxBookmark(
            folder_path=path_for(parent or 0),
            title=title or url,
            url=url,
            date_added_us=int(date_added or 0),
            date_modified_us=int(last_modified or 0),
        ))
    return out


def read_firefox_extensions(profile: FirefoxProfile) -> list[FirefoxExtension]:
    """Read ``extensions.json`` and return every entry (enabled or not)."""
    path = profile.profile_dir / "extensions.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: list[FirefoxExtension] = []
    for entry in data.get("addons", []) or []:
        if not isinstance(entry, dict):
            continue
        guid = entry.get("id") or ""
        if not isinstance(guid, str):
            continue
        # AMO listing GUIDs look like uBlock0@raymondhill.net or {curly-uuid};
        # system add-ons (telemetry, formautofill, ...) live under
        # *@mozilla.org, *@mozilla.com, and "system-default-engine" — skip them.
        if guid.endswith("@mozilla.org") or guid.endswith("@mozilla.com"):
            continue
        out.append(FirefoxExtension(
            guid=guid,
            name=str(entry.get("defaultLocale", {}).get("name") or entry.get("name") or guid),
            version=str(entry.get("version") or ""),
            enabled=bool(entry.get("active", True)),
            description=str(entry.get("defaultLocale", {}).get("description") or ""),
            homepage=entry.get("defaultLocale", {}).get("homepageURL"),
        ))
    return out
