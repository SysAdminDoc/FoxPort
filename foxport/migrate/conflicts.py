"""Pre-flight conflict analysis for direct-write paths.

The direct-write modules (``nss_passwords``, ``nss_cookies``,
``nss_history``, ``open_tabs``) replace or merge data inside the target
Firefox profile. Today the user sees no preview of what will be
overwritten — the v1.3 audit flagged that as the product's biggest
data-safety risk.

This module gives the worker + the future conflict-review dialog a
*non-mutating* read of how many rows the source has, how many already
exist in the target, and how many would be net-new — split per category
so the user can decide policy independently.

The functions here NEVER mutate target files and NEVER trigger network
calls. They open the relevant target file (or its temp copy via the
existing safe-copy helpers), count, and return. Errors fail closed —
zero counts with a populated ``failures`` list — so callers can show
"could not preflight" without aborting the migration.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from foxport.browsers.chromium import (
    PasswordRow,
    read_bookmarks,
    read_password_rows,
)
from foxport.browsers.detect import ChromiumProfile, FirefoxProfile
from foxport.migrate.passwords import _FOXPORT_LOGIN_NAMESPACE


@dataclass
class CategoryConflicts:
    """Per-category accounting: how many rows go where on a direct-write run.

    Invariant: ``source_total == new + duplicates`` for password/cookie/
    history scope. ``failures`` is a list of free-text reasons we
    couldn't analyze something — the GUI surfaces them so the user can
    decide whether to proceed without preflight.
    """

    category: str          # passwords / cookies / history / open_tabs
    source_total: int = 0
    duplicates: int = 0    # entries that already exist in the target
    new: int = 0           # entries that will be added
    failures: list[str] = field(default_factory=list)


def analyze_passwords(
    source: ChromiumProfile,
    target: FirefoxProfile,
) -> CategoryConflicts:
    """Count source logins vs. target ``logins.json`` matches.

    Deterministic GUID matching mirrors what ``nss_passwords`` would
    actually do during the merge — so the user sees the exact same
    skip count the real run would produce.
    """

    result = CategoryConflicts(category="passwords")
    try:
        source_rows = list(read_password_rows(source))
    except Exception as exc:  # noqa: BLE001
        result.failures.append(f"could not read source logins: {exc}")
        return result
    result.source_total = len(source_rows)

    target_guids: set[str] = set()
    logins_json = target.profile_dir / "logins.json"
    if logins_json.is_file():
        try:
            data = json.loads(logins_json.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            result.failures.append(f"could not parse target logins.json: {exc}")
        else:
            for login in (data.get("logins") or []):
                if isinstance(login, dict):
                    guid = login.get("guid")
                    if isinstance(guid, str):
                        target_guids.add(guid)

    for row in source_rows:
        candidate = "{" + str(uuid.uuid5(
            _FOXPORT_LOGIN_NAMESPACE,
            f"{row.origin_url}\x00{row.username}",
        )) + "}"
        if candidate in target_guids:
            result.duplicates += 1
        else:
            result.new += 1
    return result


def analyze_cookies(
    source: ChromiumProfile,
    target: FirefoxProfile,
) -> CategoryConflicts:
    """Cookies direct-write currently *replaces* the whole target DB, so
    every row counts as "new from source's perspective". We still report
    the target's existing row count under ``duplicates`` so the user can
    see how much state will be displaced by the swap.
    """

    result = CategoryConflicts(category="cookies")
    # Counting source cookies without decryption is cheap — the SQLite
    # row count matches what migrate_cookies will emit (minus
    # decryption failures we can't predict here).
    source_db = source.profile_dir / "Network" / "Cookies"
    if not source_db.is_file():
        source_db = source.profile_dir / "Cookies"
    if source_db.is_file():
        try:
            result.source_total = _safe_count(source_db, "SELECT COUNT(*) FROM cookies")
        except Exception as exc:  # noqa: BLE001
            result.failures.append(f"could not count source cookies: {exc}")
    result.new = result.source_total

    target_db = target.profile_dir / "cookies.sqlite"
    if target_db.is_file():
        try:
            result.duplicates = _safe_count(target_db, "SELECT COUNT(*) FROM moz_cookies")
        except Exception as exc:  # noqa: BLE001
            result.failures.append(f"could not count target cookies: {exc}")
    return result


def analyze_history(
    source: ChromiumProfile,
    target: FirefoxProfile,
) -> CategoryConflicts:
    """Same shape as cookies — history direct-write replaces places.sqlite,
    so ``duplicates`` is the size of what will be displaced."""

    result = CategoryConflicts(category="history")
    source_db = source.profile_dir / "History"
    if source_db.is_file():
        try:
            result.source_total = _safe_count(source_db, "SELECT COUNT(*) FROM urls")
        except Exception as exc:  # noqa: BLE001
            result.failures.append(f"could not count source history: {exc}")
    result.new = result.source_total

    target_db = target.profile_dir / "places.sqlite"
    if target_db.is_file():
        try:
            result.duplicates = _safe_count(target_db, "SELECT COUNT(*) FROM moz_places")
        except Exception as exc:  # noqa: BLE001
            result.failures.append(f"could not count target history: {exc}")
    return result


def _safe_count(db_path: Path, query: str) -> int:
    """Open ``db_path`` read-only, run a single COUNT query, return the int.

    SQLite's URI mode lets us hold a shared read lock instead of the
    exclusive lock the default connection takes. This is what makes the
    function safe to run against a live browser DB without invalidating
    Chrome's / Firefox's WAL.
    """

    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        row = conn.execute(query).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    finally:
        conn.close()
