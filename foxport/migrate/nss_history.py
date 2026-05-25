"""Direct-write history migration — install a fresh places.sqlite straight
into a *closed* target Firefox profile, backing up the existing file first.

Same safety pattern as :mod:`nss_cookies`: refuse on locked profile,
back up the previous file with a timestamped name, then atomically copy
the new one in. Firefox rebuilds ``favicons.sqlite`` from the imported
visits on next launch, so we move the user's existing favicons aside
to a timestamped backup (NOT delete — accumulated favicon icons
represent months of browsing and shouldn't be unrecoverable on a
regret path).
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from foxport.browsers.detect import (
    ChromiumProfile,
    FirefoxProfile,
    is_firefox_profile_locked,
)
from foxport.fileops import replace_file_atomic, timestamped_backup_path
from foxport.migrate.history import HistoryResult, _get_host, _get_prefix, migrate_history
from foxport.migrate.nss_cookies import (
    ProfileLockedError,
    _clear_sqlite_sidecars,
    _copy_sqlite_with_sidecars,
    _table_columns,
)


@dataclass
class HistoryDirectWriteResult:
    target_path: Path
    backup_path: Path | None             # None when the target had nothing to back up
    favicons_backup_path: Path | None    # None when the target had no favicons.sqlite
    written: HistoryResult
    merged: bool = False
    places_inserted: int = 0
    visits_inserted: int = 0
    visits_skipped_existing: int = 0

    @property
    def favicons_deleted(self) -> bool:
        """Backward-compat shim — old callers asked whether favicons were
        "deleted". The new semantics is "moved aside to a backup", but
        the answer to the original question is True when the move ran."""
        return self.favicons_backup_path is not None


# Backward-compat alias for the helper that moved to foxport.fileops.
_backup_path_for = timestamped_backup_path


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _ensure_origin(conn: sqlite3.Connection, url: str) -> int | None:
    if not _table_exists(conn, "moz_origins"):
        return None
    prefix = _get_prefix(url)
    host = _get_host(url)
    if not prefix or not host:
        return None
    conn.execute(
        "INSERT OR IGNORE INTO moz_origins (prefix, host, frecency, recalc_frecency) "
        "VALUES (?, ?, -1, 1)",
        (prefix, host),
    )
    row = conn.execute(
        "SELECT id FROM moz_origins WHERE prefix = ? AND host = ?",
        (prefix, host),
    ).fetchone()
    return int(row[0]) if row else None


def _ensure_annotation_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
CREATE TABLE IF NOT EXISTS moz_anno_attributes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(32) UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS moz_annos (
    id INTEGER PRIMARY KEY,
    place_id INTEGER NOT NULL,
    anno_attribute_id INTEGER,
    content LONGVARCHAR,
    flags INTEGER DEFAULT 0,
    expiration INTEGER DEFAULT 0,
    type INTEGER DEFAULT 0,
    dateAdded INTEGER DEFAULT 0,
    lastModified INTEGER DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS moz_annos_placeattributeindex
    ON moz_annos (place_id, anno_attribute_id);
""")


def _annotation_attr_id(conn: sqlite3.Connection, name: str) -> int:
    conn.execute("INSERT OR IGNORE INTO moz_anno_attributes (name) VALUES (?)", (name,))
    row = conn.execute(
        "SELECT id FROM moz_anno_attributes WHERE name = ?",
        (name,),
    ).fetchone()
    return int(row[0])


def _copy_download_annotations(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    place_id_map: dict[int, int],
) -> None:
    if not (
        _table_exists(source_conn, "moz_annos")
        and _table_exists(source_conn, "moz_anno_attributes")
    ):
        return
    _ensure_annotation_tables(target_conn)
    rows = source_conn.execute(
        "SELECT a.place_id, aa.name, a.content, a.flags, a.expiration, "
        "a.type, a.dateAdded, a.lastModified "
        "FROM moz_annos a "
        "JOIN moz_anno_attributes aa ON aa.id = a.anno_attribute_id"
    ).fetchall()
    for source_place_id, name, content, flags, expiration, anno_type, added, modified in rows:
        target_place_id = place_id_map.get(int(source_place_id))
        if target_place_id is None:
            continue
        attr_id = _annotation_attr_id(target_conn, str(name))
        target_conn.execute(
            "INSERT OR REPLACE INTO moz_annos "
            "(place_id, anno_attribute_id, content, flags, expiration, type, "
            " dateAdded, lastModified) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                target_place_id,
                attr_id,
                content,
                flags,
                expiration,
                anno_type,
                added,
                modified,
            ),
        )


def _merge_history_rows(source_db: Path, target_db: Path) -> tuple[int, int, int]:
    """Insert source places/visits absent from target by URL + visit_date."""

    places_inserted = 0
    visits_inserted = 0
    visits_skipped = 0
    source_conn = sqlite3.connect(str(source_db))
    target_conn = sqlite3.connect(str(target_db))
    try:
        source_place_cols = _table_columns(source_conn, "moz_places")
        target_place_cols = _table_columns(target_conn, "moz_places")
        place_cols = [
            col for col in source_place_cols
            if col in target_place_cols and col != "id"
        ]
        if "url" not in place_cols:
            raise sqlite3.DatabaseError("moz_places is missing url column")
        source_visit_cols = _table_columns(source_conn, "moz_historyvisits")
        target_visit_cols = _table_columns(target_conn, "moz_historyvisits")
        visit_cols = [
            col for col in source_visit_cols
            if col in target_visit_cols and col != "id"
        ]
        if not {"place_id", "visit_date"}.issubset(visit_cols):
            raise sqlite3.DatabaseError("moz_historyvisits is missing place_id/visit_date")

        place_select = ", ".join(["id", *place_cols])
        place_insert = (
            f"INSERT INTO moz_places ({', '.join(place_cols)}) "
            f"VALUES ({', '.join('?' for _ in place_cols)})"
        )
        place_id_map: dict[int, int] = {}
        existing_target_places: set[int] = set()
        with target_conn:
            for values in source_conn.execute(f"SELECT {place_select} FROM moz_places"):
                source_place_id = int(values[0])
                row = dict(zip(place_cols, values[1:], strict=True))
                url = row.get("url") or ""
                target_row = target_conn.execute(
                    "SELECT id FROM moz_places WHERE url IS ? LIMIT 1",
                    (url,),
                ).fetchone()
                if target_row:
                    target_place_id = int(target_row[0])
                    existing_target_places.add(target_place_id)
                else:
                    if "origin_id" in row:
                        row["origin_id"] = _ensure_origin(target_conn, str(url))
                    try:
                        target_conn.execute(place_insert, [row[col] for col in place_cols])
                    except sqlite3.IntegrityError:
                        # url_hash collisions are rare but possible. Preserve target.
                        continue
                    target_place_id = int(target_conn.execute("SELECT last_insert_rowid()").fetchone()[0])
                    places_inserted += 1
                place_id_map[source_place_id] = target_place_id

            visit_select = ", ".join(visit_cols)
            visit_insert = (
                f"INSERT INTO moz_historyvisits ({visit_select}) "
                f"VALUES ({', '.join('?' for _ in visit_cols)})"
            )
            existing_visit_updates: dict[int, tuple[int, int]] = {}
            for values in source_conn.execute(f"SELECT {visit_select} FROM moz_historyvisits"):
                row = dict(zip(visit_cols, values, strict=True))
                source_place_id = int(row["place_id"])
                target_place_id = place_id_map.get(source_place_id)
                if target_place_id is None:
                    continue
                visit_date = row["visit_date"]
                exists = target_conn.execute(
                    "SELECT 1 FROM moz_historyvisits "
                    "WHERE place_id = ? AND visit_date IS ? LIMIT 1",
                    (target_place_id, visit_date),
                ).fetchone()
                if exists:
                    visits_skipped += 1
                    continue
                row["place_id"] = target_place_id
                if "from_visit" in row:
                    row["from_visit"] = 0
                target_conn.execute(visit_insert, [row[col] for col in visit_cols])
                visits_inserted += 1
                if target_place_id in existing_target_places:
                    count, max_visit = existing_visit_updates.get(target_place_id, (0, 0))
                    visit_int = int(visit_date or 0)
                    existing_visit_updates[target_place_id] = (
                        count + 1,
                        max(max_visit, visit_int),
                    )

            for target_place_id, (count, max_visit) in existing_visit_updates.items():
                target_conn.execute(
                    "UPDATE moz_places SET "
                    "visit_count = COALESCE(visit_count, 0) + ?, "
                    "last_visit_date = MAX(COALESCE(last_visit_date, 0), ?), "
                    "recalc_frecency = 1 "
                    "WHERE id = ?",
                    (count, max_visit, target_place_id),
                )

            _copy_download_annotations(source_conn, target_conn, place_id_map)
        target_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        source_conn.close()
        target_conn.close()
    return places_inserted, visits_inserted, visits_skipped


def write_history_into_target(
    source: ChromiumProfile,
    target: FirefoxProfile,
    staging_dir: Path,
    *,
    include_download_annotations: bool = False,
    merge: bool = False,
) -> HistoryDirectWriteResult:
    if is_firefox_profile_locked(target):
        raise ProfileLockedError(
            f"target profile {target.label} is locked — close Firefox before importing"
        )
    history_result = migrate_history(
        source,
        staging_dir,
        include_download_annotations=include_download_annotations,
    )
    target_path = target.profile_dir / "places.sqlite"

    merge_db = (
        _copy_sqlite_with_sidecars(target_path, prefix="foxport_history_merge_")
        if merge and target_path.is_file()
        else None
    )
    backup_path = timestamped_backup_path(target_path)
    if backup_path is not None:
        shutil.copy2(target_path, backup_path)
        # Clear WAL/SHM siblings so Firefox doesn't re-merge stale state into
        # the imported DB on next launch.
        _clear_sqlite_sidecars(target_path)
    places_inserted = 0
    visits_inserted = 0
    visits_skipped_existing = 0
    if merge_db is not None:
        try:
            places_inserted, visits_inserted, visits_skipped_existing = _merge_history_rows(
                history_result.sqlite_path,
                merge_db,
            )
            replace_file_atomic(merge_db, target_path)
        finally:
            shutil.rmtree(merge_db.parent, ignore_errors=True)
    else:
        replace_file_atomic(history_result.sqlite_path, target_path)
        places_inserted = history_result.urls
        visits_inserted = history_result.visits

    favicons = target.profile_dir / "favicons.sqlite"
    favicons_backup: Path | None = None
    if not merge and favicons.exists():
        try:
            mtime = int(favicons.stat().st_mtime)
            favicons_backup = favicons.with_name(
                f"favicons.foxport-backup-{mtime}.sqlite"
            )
            favicons.rename(favicons_backup)
        except OSError:
            favicons_backup = None

    return HistoryDirectWriteResult(
        target_path=target_path,
        backup_path=backup_path,
        favicons_backup_path=favicons_backup,
        written=history_result,
        merged=merge,
        places_inserted=places_inserted,
        visits_inserted=visits_inserted,
        visits_skipped_existing=visits_skipped_existing,
    )
