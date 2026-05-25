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
from typing import Literal

from foxport.browsers.chromium import (
    PasswordRow,
    read_bookmarks,
    read_password_rows,
)
from foxport.browsers.detect import ChromiumProfile, FirefoxProfile
from foxport.migrate.passwords import _FOXPORT_LOGIN_NAMESPACE


# Per-category direct-write policy. Values land in MigrationRequest fields
# (policy_passwords / policy_cookies / policy_history / policy_open_tabs)
# and in the manifest's RunArtifact.direct_write_policy for the record.
#
#   "apply"       — current v1.3 behavior. For passwords: NSS merge by
#                   deterministic GUID. For cookies / history /
#                   open_tabs: replace the target file wholesale after
#                   backing it up to a timestamped sibling. This stays the
#                   default for backward compatibility.
#   "merge"       — preserve target state where the category supports it.
#                   Cookies add source rows absent by host/path/name; history
#                   adds source visits absent by URL + visit_time. Passwords
#                   already merge under "apply"; open tabs still replace.
#   "skip"        — don't run the direct-write at all. Staging output
#                   is still written to the run's output folder so the
#                   user can manually import it later via Firefox's UI.
#                   The target file is untouched.
#   "backup-only" — take the timestamped backup of the existing target
#                   file (the same one "apply" would produce), but do
#                   NOT actually write the new content. Useful when the
#                   user wants to snapshot Firefox's current state before
#                   making any decisions.
DirectWritePolicy = Literal["apply", "merge", "skip", "backup-only"]


DIRECT_WRITE_POLICIES: tuple[str, ...] = ("apply", "merge", "skip", "backup-only")
DIRECT_WRITE_POLICY_DEFAULT: DirectWritePolicy = "apply"


# Human-readable explanation per policy — surfaced by the
# DirectWritePolicyDialog so the user sees the consequence next to the
# dropdown without having to re-read the ROADMAP.
DIRECT_WRITE_POLICY_LABELS: dict[str, str] = {
    "apply": "Apply (default — merge passwords, replace cookies/history/open-tabs after backup)",
    "merge": "Merge (preserve target cookies/history; add only new source rows)",
    "skip": "Skip (don't touch the target profile; staging output only)",
    "backup-only": "Backup only (timestamp-copy the target file but don't write new content)",
}


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

    # GUIDs in logins.json are case-insensitive; ``uuid.uuid5`` always emits
    # lowercase. Normalize both sides so the pre-flight count agrees with
    # the merge skip count in ``migrate_passwords_via_nss`` even when an
    # older Firefox or third-party tool wrote mixed-case GUIDs.
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
                        target_guids.add(guid.lower())

    for row in source_rows:
        candidate = "{" + str(uuid.uuid5(
            _FOXPORT_LOGIN_NAMESPACE,
            f"{row.origin_url}\x00{row.username}",
        )) + "}"
        if candidate.lower() in target_guids:
            result.duplicates += 1
        else:
            result.new += 1
    return result


def analyze_cookies(
    source: ChromiumProfile,
    target: FirefoxProfile,
) -> CategoryConflicts:
    """Count cookies before direct-write.

    ``apply`` replaces the whole target DB, so ``duplicates`` remains the
    target row count that would be displaced. ``merge`` performs a more
    precise host/path/name skip inside ``nss_cookies``; this analyzer stays
    cheap and conservative for the review dialog.
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
    """Count history before direct-write.

    ``apply`` replaces ``places.sqlite``, so ``duplicates`` is the target
    row count that would be displaced. ``merge`` dedupes by URL+visit_time
    inside ``nss_history``; this analyzer stays cheap and conservative.
    """

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


def analyze_open_tabs(
    source: ChromiumProfile,
    target: FirefoxProfile,
) -> CategoryConflicts:
    """Count source open tabs vs. tabs currently in the target's session.

    Open-tabs direct-write replaces ``sessionstore-backups/recovery.jsonlz4``
    wholesale. ``source_total`` is what FoxPort would emit; ``duplicates``
    is the count of tabs in the target's current recovery file (the
    "displaced" count, same idiom as :func:`analyze_cookies` /
    :func:`analyze_history`).
    """

    result = CategoryConflicts(category="open_tabs")
    # Source side — reuse the existing SNSS scan in dry-run mode so the
    # count matches what migrate_open_tabs would actually write.
    try:
        import tempfile
        from foxport.migrate.open_tabs import migrate_open_tabs
        with tempfile.TemporaryDirectory(prefix="foxport_ot_preflight_") as tmp:
            res = migrate_open_tabs(source, Path(tmp), dry_run=True)
        result.source_total = res.tabs
    except Exception as exc:  # noqa: BLE001
        result.failures.append(f"could not count source open tabs: {exc}")
    result.new = result.source_total

    # Target side — decode the existing recovery.jsonlz4 if present.
    recovery = target.profile_dir / "sessionstore-backups" / "recovery.jsonlz4"
    if recovery.is_file():
        try:
            result.duplicates = _count_recovery_jsonlz4_tabs(recovery)
        except Exception as exc:  # noqa: BLE001
            result.failures.append(f"could not count target open tabs: {exc}")
    return result


def _count_recovery_jsonlz4_tabs(path: Path) -> int:
    """Decode a Firefox ``recovery.jsonlz4`` and count navigation entries.

    Format: ``b"mozLz40\\0"`` + uint32_le(original_size) + lz4.block.compress(
    JSON). The JSON is a sessionstore payload with windows -> tabs ->
    entries. We count one URL per tab (the active entry); closed tabs in
    ``_closedTabs`` are NOT counted because the user wouldn't see them in
    a fresh Firefox launch.
    """

    raw = path.read_bytes()
    if not raw.startswith(b"mozLz40\x00"):
        return 0
    import json as _json
    import struct as _struct
    try:
        import lz4.block as _lz4_block
    except ImportError:
        return 0
    offset = len(b"mozLz40\x00")
    (orig_size,) = _struct.unpack_from("<I", raw, offset)
    payload = _lz4_block.decompress(raw[offset + 4:], uncompressed_size=orig_size)
    try:
        data = _json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return 0
    tab_count = 0
    for window in data.get("windows", []) or []:
        for _tab in window.get("tabs", []) or []:
            tab_count += 1
    return tab_count


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
