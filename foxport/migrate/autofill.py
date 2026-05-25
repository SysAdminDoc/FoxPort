"""Form-autofill migration — Chromium ``Web Data.autofill`` → Firefox
``formhistory.sqlite/moz_formhistory``.

Both stores hold the same conceptual data: which strings the user has
typed into which form field names, with usage stats. Firefox's table:

    CREATE TABLE moz_formhistory(
        id INTEGER PRIMARY KEY,
        fieldname TEXT NOT NULL,
        value TEXT NOT NULL,
        timesUsed INTEGER,
        firstUsed INTEGER,    -- microseconds since 1970-01-01 UTC
        lastUsed INTEGER,
        guid TEXT
    )

Chromium's ``autofill`` table is ``(name, value, value_lower, date_created,
date_last_used, count)`` — date columns are seconds since 1601-01-01 UTC
(different from passwords' microseconds!).
"""

from __future__ import annotations

import base64
import os
import secrets
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from foxport.browsers.detect import ChromiumProfile
from foxport.fileops import replace_file_atomic

# autofill table uses seconds since 1601-01-01 UTC (NOT microseconds).
_CHROME_EPOCH_OFFSET_SECS = 11_644_473_600


def _chrome_secs_to_firefox_micros(chrome_secs: int) -> int:
    if chrome_secs <= 0:
        return 0
    unix_secs = chrome_secs - _CHROME_EPOCH_OFFSET_SECS
    if unix_secs <= 0:
        return 0
    return unix_secs * 1_000_000


@dataclass
class AutofillResult:
    sqlite_path: Path
    written: int
    skipped: int
    failures: list[str] = field(default_factory=list)


# Firefox v5 schema added moz_sources (extension/app provenance per entry)
# and the moz_history_to_sources junction. We create both empty so Firefox's
# v4 → v5 migration doesn't fire on first launch.
_FIREFOX_FORMHISTORY_SCHEMA = """
CREATE TABLE moz_formhistory (
    id INTEGER PRIMARY KEY,
    fieldname TEXT NOT NULL,
    value TEXT NOT NULL,
    timesUsed INTEGER,
    firstUsed INTEGER,
    lastUsed INTEGER,
    guid TEXT
);
CREATE INDEX moz_formhistory_fieldname_index ON moz_formhistory (fieldname);
CREATE INDEX moz_formhistory_lastused_index ON moz_formhistory (lastUsed);
CREATE UNIQUE INDEX moz_formhistory_guid_index ON moz_formhistory (guid);

CREATE TABLE moz_deleted_formhistory (
    id INTEGER PRIMARY KEY,
    timeDeleted INTEGER,
    guid TEXT
);
CREATE UNIQUE INDEX moz_deleted_formhistory_guid_index ON moz_deleted_formhistory (guid);

CREATE TABLE moz_sources (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL UNIQUE
);

CREATE TABLE moz_history_to_sources (
    history_id INTEGER NOT NULL REFERENCES moz_formhistory(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES moz_sources(id) ON DELETE CASCADE,
    PRIMARY KEY (history_id, source_id)
);

PRAGMA user_version = 5;
"""


def _web_data_path(profile: ChromiumProfile) -> Path | None:
    candidate = profile.profile_dir / "Web Data"
    return candidate if candidate.is_file() else None


def _copy_for_read(src: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="foxport_webdata_"))
    dest = tmp / src.name
    shutil.copy2(src, dest)
    for suffix in ("-wal", "-shm"):
        sibling = src.with_name(src.name + suffix)
        if sibling.exists():
            shutil.copy2(sibling, dest.with_name(dest.name + suffix))
    return dest


def _firefox_guid() -> str:
    """Firefox uses a base64-encoded 9-byte token (~12 chars after b64)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(9)).decode("ascii").rstrip("=")


def migrate_autofill(
    profile: ChromiumProfile,
    out_dir: Path,
    *,
    dry_run: bool = False,
) -> AutofillResult:
    """Walk Chromium's ``Web Data.autofill`` and emit a Firefox-ready
    ``formhistory.sqlite`` in ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = out_dir / "formhistory.sqlite"

    src = _web_data_path(profile)
    failures: list[str] = []
    if not src:
        return AutofillResult(sqlite_path=sqlite_path, written=0, skipped=0, failures=failures)

    copy = _copy_for_read(src)
    try:
        conn = sqlite3.connect(str(copy))
        try:
            cur = conn.execute(
                "SELECT name, value, count, date_created, date_last_used FROM autofill"
            )
            rows = cur.fetchall()
        except sqlite3.DatabaseError as exc:
            failures.append(str(exc))
            rows = []
        finally:
            conn.close()
    finally:
        shutil.rmtree(copy.parent, ignore_errors=True)

    written = 0
    skipped = 0

    if dry_run:
        return AutofillResult(
            sqlite_path=sqlite_path,
            written=len(rows),
            skipped=0,
            failures=failures,
        )

    # Build into a tempdir then atomic-replace so a crash during inserts
    # can't leave a corrupt formhistory.sqlite at the staging output path.
    staging_dir = tempfile.mkdtemp(prefix="foxport_formhistory_build_")
    try:
        staged = Path(staging_dir) / "formhistory.sqlite"
        out_conn = sqlite3.connect(str(staged))
        try:
            out_conn.executescript(_FIREFOX_FORMHISTORY_SCHEMA)
            out_conn.commit()
            with out_conn:
                for name, value, count, date_created, date_last_used in rows:
                    if not name or value is None:
                        skipped += 1
                        continue
                    first = _chrome_secs_to_firefox_micros(date_created or 0)
                    last = _chrome_secs_to_firefox_micros(date_last_used or 0)
                    try:
                        out_conn.execute(
                            "INSERT INTO moz_formhistory "
                            "(fieldname, value, timesUsed, firstUsed, lastUsed, guid) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (str(name), str(value), int(count or 1), first, last, _firefox_guid()),
                        )
                        written += 1
                    except sqlite3.IntegrityError as exc:
                        failures.append(f"{name}={value}: {exc}")
        finally:
            out_conn.close()
        replace_file_atomic(staged, sqlite_path)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    return AutofillResult(
        sqlite_path=sqlite_path,
        written=written,
        skipped=skipped,
        failures=failures,
    )
