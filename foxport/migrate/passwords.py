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
from typing import Iterable

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


def migrate_passwords(profile: ChromiumProfile, out_dir: Path) -> PasswordResult:
    """Decrypt all logins in ``profile`` and write a Firefox-format CSV."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "passwords.csv"
    failures: list[str] = []
    total = 0
    decrypted = 0
    skipped_empty = 0

    key = load_master_key(profile.local_state)
    rows = list(read_password_rows(profile))
    total = len(rows)

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL)
        writer.writerow(_FIREFOX_CSV_HEADER)
        for row, plaintext in _decrypt_rows(rows, key, failures):
            if not plaintext:
                skipped_empty += 1
                continue
            decrypted += 1
            writer.writerow([
                row.origin_url,
                row.username,
                plaintext,
                "",
                row.action_url or "",
                "{" + str(uuid.uuid4()) + "}",
                _chrome_micros_to_firefox_millis(row.date_created),
                _chrome_micros_to_firefox_millis(row.date_last_used),
                _chrome_micros_to_firefox_millis(row.date_password_modified),
            ])

    return PasswordResult(
        csv_path=csv_path,
        total=total,
        decrypted=decrypted,
        skipped_empty=skipped_empty,
        failed=len(failures),
        failures=failures,
    )
