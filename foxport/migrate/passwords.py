"""Decrypt Chromium logins and write a Firefox-importable CSV.

Firefox's ``about:logins`` "Import from a File" accepts CSVs with these
columns (case-sensitive header, double-quoted values, comma delimiter, RFC 4180
escaping):

    url, username, password, httpRealm, formActionOrigin, guid,
    timeCreated, timeLastUsed, timePasswordChanged

* ``url`` comes from Chromium's ``origin_url``.
* ``formActionOrigin`` comes from ``action_url`` (or empty for HTTP-Basic auth).
* ``httpRealm`` is left empty — Chromium doesn't preserve it.
* Times are converted from Chromium WebKit epoch (microseconds since
  1601-01-01 UTC) to Firefox milliseconds since 1970-01-01 UTC.
"""

from __future__ import annotations

import csv
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

# Stable namespace UUID for FoxPort-generated login GUIDs. Deterministic per
# (origin, username) so a second migration run produces the same GUID and
# Firefox's CSV import deduplicates instead of inserting duplicates.
_FOXPORT_LOGIN_NAMESPACE = uuid.UUID("8a8f3f4c-6a4b-4cab-9a26-1d9e1ce4d3a1")

from foxport.browsers.chromium import PasswordRow, read_password_rows
from foxport.browsers.detect import ChromiumProfile
from foxport.crypto.dpapi import (
    ChromiumKey,
    DecryptionError,
    decrypt_value,
    load_master_key,
)


_FIREFOX_CSV_HEADER = [
    "url",
    "username",
    "password",
    "httpRealm",
    "formActionOrigin",
    "guid",
    "timeCreated",
    "timeLastUsed",
    "timePasswordChanged",
]

# Chromium time = microseconds since 1601-01-01 UTC.
# Firefox time = milliseconds since 1970-01-01 UTC.
_CHROME_EPOCH_OFFSET_MICROS = 11644473600 * 1_000_000


@dataclass
class PasswordResult:
    """Outcome of a passwords migration run."""

    csv_path: Path
    total: int
    decrypted: int
    skipped_empty: int
    failed: int
    failures: list[str]
    hibp_report_path: Path | None = None
    hibp_hits: int = 0


def _chrome_micros_to_firefox_millis(chrome_us: int) -> int:
    if chrome_us <= 0:
        return 0
    unix_us = chrome_us - _CHROME_EPOCH_OFFSET_MICROS
    if unix_us < 0:
        return 0
    return unix_us // 1000


def _decrypt_rows(
    rows: Iterable[PasswordRow],
    key: ChromiumKey,
    failures: list[str],
) -> Iterable[tuple[PasswordRow, str]]:
    for row in rows:
        if not row.password_blob:
            continue
        try:
            plaintext = decrypt_value(row.password_blob, key)
        except DecryptionError as exc:
            failures.append(f"{row.origin_url} / {row.username}: {exc}")
            continue
        yield row, plaintext


PasswordPredicate = Callable[[PasswordRow], bool]


def migrate_passwords(
    profile: ChromiumProfile,
    out_dir: Path,
    *,
    dry_run: bool = False,
    row_filter: PasswordPredicate | None = None,
    hibp_scan: bool = False,
) -> PasswordResult:
    """Decrypt all logins in ``profile`` and write a Firefox-format CSV.

    When ``dry_run=True``, counts decrypt successes and failures without
    writing any CSV file to disk. ``row_filter`` is an optional predicate
    over each :class:`PasswordRow` (called before decryption) — return
    False to skip that row entirely.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "passwords.csv"
    failures: list[str] = []
    total = 0
    decrypted = 0
    skipped_empty = 0

    key = load_master_key(profile.local_state, browser_display=profile.browser)
    raw_rows = list(read_password_rows(profile))
    rows = [r for r in raw_rows if (row_filter is None or row_filter(r))]
    total = len(rows)

    if dry_run:
        for _row, plaintext in _decrypt_rows(rows, key, failures):
            if plaintext:
                decrypted += 1
            else:
                skipped_empty += 1
        return PasswordResult(
            csv_path=csv_path,
            total=total,
            decrypted=decrypted,
            skipped_empty=skipped_empty,
            failed=len(failures),
            failures=failures,
        )

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL)
        writer.writerow(_FIREFOX_CSV_HEADER)
        for row, plaintext in _decrypt_rows(rows, key, failures):
            if not plaintext:
                skipped_empty += 1
                continue
            decrypted += 1
            stable_guid = uuid.uuid5(
                _FOXPORT_LOGIN_NAMESPACE,
                f"{row.origin_url}\x00{row.username}",
            )
            writer.writerow([
                row.origin_url,
                row.username,
                plaintext,
                "",
                row.action_url or "",
                "{" + str(stable_guid) + "}",
                _chrome_micros_to_firefox_millis(row.date_created),
                _chrome_micros_to_firefox_millis(row.date_last_used),
                _chrome_micros_to_firefox_millis(row.date_password_modified),
            ])

    hibp_report_path: Path | None = None
    hibp_hits = 0
    if hibp_scan and decrypted > 0:
        from foxport.crypto.hibp import scan_passwords
        # Re-iterate decrypted rows. We don't keep a parallel list to avoid
        # holding plaintext in memory longer than necessary; just decrypt
        # again. Cheap because everything is already in the page cache.
        rows_for_scan = []
        for row, plaintext in _decrypt_rows(rows, key, []):
            if plaintext:
                rows_for_scan.append((row.origin_url, row.username, plaintext))
        pwned = scan_passwords(rows_for_scan)
        hibp_hits = len(pwned)
        if pwned:
            hibp_report_path = out_dir / "compromised-passwords.txt"
            lines = [
                "FoxPort HIBP scan — passwords that appear in known data breaches.",
                "Reset these in the affected accounts before importing.",
                "Passwords themselves are NOT printed (only URL/username).",
                "",
            ]
            for origin_url, username, count in pwned:
                lines.append(f"  {origin_url}  /  {username}  ({count:,} breach occurrences)")
            hibp_report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return PasswordResult(
        csv_path=csv_path,
        total=total,
        decrypted=decrypted,
        skipped_empty=skipped_empty,
        failed=len(failures),
        failures=failures,
        hibp_report_path=hibp_report_path,
        hibp_hits=hibp_hits,
    )
