"""Direct-write cookies migration — install a fresh cookies.sqlite straight
into a *closed* target Firefox profile, backing up the existing file first.

This is the cookies counterpart to :mod:`foxport.migrate.nss_passwords`. NSS
isn't involved (Firefox stores cookies unencrypted in this DB), but we
borrow the same safety pattern: refuse on locked profile, back up the
previous file with a timestamped name, then replace.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from foxport.browsers.detect import (
    ChromiumProfile,
    FirefoxProfile,
    is_firefox_profile_locked,
)
from foxport.fileops import replace_file_atomic, timestamped_backup_path
from foxport.migrate.cookies import CookieResult, migrate_cookies


class ProfileLockedError(RuntimeError):
    """Target profile is in use; bailing out."""


@dataclass
class CookieDirectWriteResult:
    target_path: Path
    backup_path: Path | None     # None when the target had nothing to back up
    written: CookieResult
    merged: bool = False
    inserted: int = 0
    skipped_existing: int = 0


# Backward-compat alias. Old name lived here before the helper moved into
# fileops to dedupe between nss_cookies/nss_history. Keep the symbol so
# any external caller (or pickled test fixture) still resolves.
_backup_path_for = timestamped_backup_path


def _copy_sqlite_with_sidecars(src: Path, *, prefix: str) -> Path:
    tmp_dir = Path(tempfile.mkdtemp(prefix=prefix))
    dest = tmp_dir / src.name
    shutil.copy2(src, dest)
    for suffix in ("-wal", "-shm"):
        sibling = src.with_name(src.name + suffix)
        if sibling.exists():
            shutil.copy2(sibling, dest.with_name(dest.name + suffix))
    return dest


def _clear_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sibling = path.with_name(path.name + suffix)
        if sibling.exists():
            try:
                sibling.unlink()
            except OSError:
                # WAL on a network share can be locked; non-fatal.
                pass


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _merge_cookie_rows(source_db: Path, target_db: Path) -> tuple[int, int]:
    """Insert source cookies absent from target by host/path/name.

    Firefox's physical uniqueness constraint also includes
    ``originAttributes`` for containers, but FoxPort's product-level merge
    key intentionally ignores containers: if any target container already
    has ``host + path + name``, keep the target value and skip the source.
    """

    inserted = 0
    skipped = 0
    source_conn = sqlite3.connect(str(source_db))
    target_conn = sqlite3.connect(str(target_db))
    try:
        source_cols = _table_columns(source_conn, "moz_cookies")
        target_cols = _table_columns(target_conn, "moz_cookies")
        common_cols = [
            col for col in source_cols
            if col in target_cols and col != "id"
        ]
        if not {"host", "path", "name"}.issubset(common_cols):
            raise sqlite3.DatabaseError("moz_cookies is missing host/path/name columns")
        select_sql = ", ".join(common_cols)
        insert_sql = (
            f"INSERT INTO moz_cookies ({select_sql}) "
            f"VALUES ({', '.join('?' for _ in common_cols)})"
        )
        with target_conn:
            for values in source_conn.execute(f"SELECT {select_sql} FROM moz_cookies"):
                row = dict(zip(common_cols, values, strict=True))
                exists = target_conn.execute(
                    "SELECT 1 FROM moz_cookies "
                    "WHERE host IS ? AND path IS ? AND name IS ? LIMIT 1",
                    (row["host"], row["path"], row["name"]),
                ).fetchone()
                if exists:
                    skipped += 1
                    continue
                target_conn.execute(insert_sql, values)
                inserted += 1
        target_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        source_conn.close()
        target_conn.close()
    return inserted, skipped


def write_cookies_into_target(
    source: ChromiumProfile,
    target: FirefoxProfile,
    staging_dir: Path,
    *,
    merge: bool = False,
) -> CookieDirectWriteResult:
    """Run the normal cookies migrator into ``staging_dir`` and then atomically
    swap the result into ``target/cookies.sqlite``, backing up the previous file.
    """
    if is_firefox_profile_locked(target):
        raise ProfileLockedError(
            f"target profile {target.label} is locked — close Firefox before importing"
        )
    cookies_result = migrate_cookies(source, staging_dir)
    target_path = target.profile_dir / "cookies.sqlite"

    merge_db = (
        _copy_sqlite_with_sidecars(target_path, prefix="foxport_cookie_merge_")
        if merge and target_path.is_file()
        else None
    )
    backup_path = timestamped_backup_path(target_path)
    if backup_path is not None:
        shutil.copy2(target_path, backup_path)
        # Clear WAL/SHM siblings so Firefox doesn't re-merge stale state into
        # the imported DB on next launch.
        _clear_sqlite_sidecars(target_path)
    inserted = 0
    skipped_existing = 0
    if merge_db is not None:
        try:
            inserted, skipped_existing = _merge_cookie_rows(
                cookies_result.sqlite_path,
                merge_db,
            )
            replace_file_atomic(merge_db, target_path)
        finally:
            shutil.rmtree(merge_db.parent, ignore_errors=True)
    else:
        replace_file_atomic(cookies_result.sqlite_path, target_path)
        inserted = cookies_result.decrypted
    return CookieDirectWriteResult(
        target_path=target_path,
        backup_path=backup_path,
        written=cookies_result,
        merged=merge,
        inserted=inserted,
        skipped_existing=skipped_existing,
    )
