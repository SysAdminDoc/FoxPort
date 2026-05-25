"""Passkey/WebAuthn inventory helpers.

This is intentionally presence/count only. The code never decodes credential
IDs, user IDs, public keys, or private-key material; it reports aggregate
counts from known/likely local stores so users know whether passkeys need
manual attention before moving profiles.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from foxport.browsers.detect import ChromiumProfile, FirefoxProfile


PASSKEY_TABLE_TOKENS = ("webauthn", "passkey")
PASSKEY_LEVELDB_PRIMARY_MARKERS = (b"WebauthnCredentialSpecifics", b"webauthn_credential")
PASSKEY_LEVELDB_FALLBACK_MARKERS = (b"webauthn", b"passkey")
MAX_LEVELDB_FILE_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class PasskeyStoreInventory:
    store: str
    count: int
    confidence: str


@dataclass(frozen=True)
class PasskeyProfileInventory:
    browser: str
    family: str
    profile_name: str
    count: int
    stores: list[PasskeyStoreInventory]
    notes: list[str]

    def to_json(self) -> dict:
        payload = asdict(self)
        payload["has_passkeys"] = self.count > 0
        return payload


def inventory_chromium_passkeys(profile: ChromiumProfile) -> PasskeyProfileInventory:
    stores: list[PasskeyStoreInventory] = []
    notes: list[str] = []

    for db_path, label in (
        (profile.profile_dir / "Login Data", "Login Data"),
        (profile.profile_dir / "Web Data", "Web Data"),
    ):
        stores.extend(_sqlite_passkey_tables(db_path, label))

    leveldb_roots = [
        profile.profile_dir / "Sync Data" / "LevelDB",
        profile.user_data_dir / "Sync Data" / "LevelDB",
    ]
    seen: set[Path] = set()
    for root in leveldb_roots:
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        if resolved in seen:
            continue
        seen.add(resolved)
        marker_count = _leveldb_marker_count(root)
        if marker_count > 0:
            stores.append(PasskeyStoreInventory(
                store="Sync Data/LevelDB",
                count=marker_count,
                confidence="heuristic",
            ))
            notes.append(
                "Sync Data/LevelDB marker count is heuristic; Chrome stores "
                "Google Password Manager passkey metadata as protobuf sync records."
            )

    count = sum(store.count for store in stores)
    return PasskeyProfileInventory(
        browser=profile.browser,
        family=profile.family,
        profile_name=profile.profile_name,
        count=count,
        stores=stores,
        notes=notes,
    )


def inventory_firefox_passkeys(profile: FirefoxProfile) -> PasskeyProfileInventory:
    stores: list[PasskeyStoreInventory] = []
    notes: list[str] = []
    for db_path in profile.profile_dir.glob("*.sqlite"):
        stores.extend(_sqlite_passkey_tables(db_path, db_path.name))
    if not stores:
        notes.append(
            "No known local Firefox passkey table was found. Firefox may use "
            "platform authenticators or external password managers that do "
            "not expose browser-profile passkey rows."
        )
    count = sum(store.count for store in stores)
    return PasskeyProfileInventory(
        browser=profile.browser,
        family=profile.family,
        profile_name=profile.profile_name,
        count=count,
        stores=stores,
        notes=notes,
    )


def inventory_profiles(
    chromium_profiles: Iterable[ChromiumProfile],
    firefox_profiles: Iterable[FirefoxProfile],
) -> list[PasskeyProfileInventory]:
    out: list[PasskeyProfileInventory] = []
    out.extend(inventory_chromium_passkeys(profile) for profile in chromium_profiles)
    out.extend(inventory_firefox_passkeys(profile) for profile in firefox_profiles)
    return out


def _sqlite_passkey_tables(src: Path, label: str) -> list[PasskeyStoreInventory]:
    if not src.is_file():
        return []
    copy = _copy_sqlite_for_read(src)
    try:
        conn = sqlite3.connect(str(copy))
        try:
            names = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
                if isinstance(row[0], str)
            ]
            stores: list[PasskeyStoreInventory] = []
            for table in names:
                lowered = table.lower()
                if not any(token in lowered for token in PASSKEY_TABLE_TOKENS):
                    continue
                quoted = table.replace('"', '""')
                try:
                    count = int(conn.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0])
                except sqlite3.DatabaseError:
                    continue
                stores.append(PasskeyStoreInventory(
                    store=f"{label}:{table}",
                    count=count,
                    confidence="table",
                ))
            return stores
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return []
    finally:
        shutil.rmtree(copy.parent, ignore_errors=True)


def _copy_sqlite_for_read(src: Path) -> Path:
    tmp_dir = Path(tempfile.mkdtemp(prefix="foxport_passkeys_"))
    dest = tmp_dir / src.name
    shutil.copy2(src, dest)
    for suffix in ("-wal", "-shm"):
        sibling = src.with_name(src.name + suffix)
        if sibling.exists():
            try:
                shutil.copy2(sibling, dest.with_name(dest.name + suffix))
            except OSError:
                pass
    return dest


def _leveldb_marker_count(root: Path) -> int:
    if not root.is_dir():
        return 0
    total = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > MAX_LEVELDB_FILE_BYTES:
                continue
            data = path.read_bytes().lower()
        except OSError:
            continue
        primary = sum(data.count(marker.lower()) for marker in PASSKEY_LEVELDB_PRIMARY_MARKERS)
        if primary:
            total += primary
        else:
            total += sum(data.count(marker.lower()) for marker in PASSKEY_LEVELDB_FALLBACK_MARKERS)
    return total
