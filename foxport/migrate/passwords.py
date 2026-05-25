"""Decrypt Chromium logins and write a Firefox-importable CSV.

Firefox's ``about:logins`` "Import from a File" accepts CSVs with these
columns (case-insensitive header, double-quoted values, comma delimiter,
RFC 4180 escaping):

    url, username, password, httpRealm, formActionOrigin, guid,
    timeCreated, timeLastUsed, timePasswordChanged

* ``url`` comes from Chromium's ``origin_url``.
* ``formActionOrigin`` comes from ``action_url`` (or empty for HTTP-Basic auth).
* ``httpRealm`` is left empty — Chromium doesn't preserve it; Firefox
  normalizes empty string to null at import time.
* Times are converted from Chromium WebKit epoch (microseconds since
  1601-01-01 UTC) to Firefox milliseconds since 1970-01-01 UTC.
"""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from foxport.browsers.chromium import PasswordRow, read_password_rows
from foxport.browsers.detect import ChromiumProfile
from foxport.crypto.dpapi import (
    ChromiumKey,
    DecryptionError,
    decrypt_value,
    load_master_key,
)
from foxport.fileops import write_text_atomic


# Stable namespace UUID for FoxPort-generated login GUIDs. Deterministic per
# (origin, username) so a second migration run produces the same GUID and
# Firefox's CSV import deduplicates instead of inserting duplicates.
_FOXPORT_LOGIN_NAMESPACE = uuid.UUID("8a8f3f4c-6a4b-4cab-9a26-1d9e1ce4d3a1")


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
    """Outcome of a passwords migration run.

    Invariant: ``total == decrypted + skipped_empty + failed`` for any
    completed (non-exception) run. Empty-blob rows are counted in
    ``skipped_empty`` so the math always balances.

    ``hibp_status`` is the tri-state from :mod:`foxport.crypto.hibp`:

    * ``"disabled"`` — the user didn't opt in.
    * ``"checked-clean"`` — scan ran successfully, no breaches.
    * ``"checked-hits"`` — scan ran successfully, found at least one breach.
    * ``"network-error"`` — scan was requested but one or more API calls
      failed. ``hibp_hits`` may still be > 0 if some prefixes did succeed,
      but the user should treat "no hits" as "we don't actually know".

    Before v1.3.1 the worker treated ``hibp_hits == 0`` as success even
    when every API call had failed; the tri-state distinguishes those.
    """

    csv_path: Path
    total: int
    decrypted: int
    skipped_empty: int
    failed: int
    failures: list[str] = field(default_factory=list)
    hibp_report_path: Path | None = None
    hibp_hits: int = 0
    hibp_status: str = "disabled"


PasswordPredicate = Callable[[PasswordRow], bool]


def _chrome_micros_to_firefox_millis(chrome_us: int) -> int:
    if chrome_us <= 0:
        return 0
    unix_us = chrome_us - _CHROME_EPOCH_OFFSET_MICROS
    if unix_us < 0:
        return 0
    return unix_us // 1000


def _decrypt_all(
    rows: Iterable[PasswordRow],
    key: ChromiumKey,
) -> tuple[list[tuple[PasswordRow, str]], int, list[str]]:
    """Decrypt every row exactly once.

    Returns ``(decrypted_pairs, skipped_empty_count, failure_messages)``.

    * ``decrypted_pairs`` — rows whose blob decoded to a non-empty string.
    * ``skipped_empty`` — rows with no blob OR a blob that decoded to empty.
      Both shapes are legitimately "no password stored" (Chromium creates
      placeholder rows when the user picks "Never save for this site").
    * ``failure_messages`` — per-row diagnostics for decryption failures.

    Catches the full ``Exception`` for the cryptography call site — a
    wrong-length master key raises ``ValueError`` rather than
    ``DecryptionError``, and we don't want one bad row to abort the
    entire migration.
    """
    decrypted: list[tuple[PasswordRow, str]] = []
    skipped_empty = 0
    failures: list[str] = []
    for row in rows:
        if not row.password_blob:
            skipped_empty += 1
            continue
        try:
            plaintext = decrypt_value(row.password_blob, key)
        except DecryptionError as exc:
            failures.append(f"{row.origin_url} / {row.username}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 — keep one bad row from aborting
            failures.append(
                f"{row.origin_url} / {row.username}: unexpected {type(exc).__name__}: {exc}"
            )
            continue
        if not plaintext:
            skipped_empty += 1
            continue
        decrypted.append((row, plaintext))
    return decrypted, skipped_empty, failures


def _write_csv(decrypted: list[tuple[PasswordRow, str]], csv_path: Path) -> None:
    # Build the entire CSV in memory and write through the atomic helper so
    # a crash mid-write can't leave a half-finished CSV at the final name
    # (the README.txt and manifest.json would otherwise reference a corrupt
    # file that the user might try to import).
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
    writer.writerow(_FIREFOX_CSV_HEADER)
    for row, plaintext in decrypted:
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
    write_text_atomic(csv_path, buf.getvalue())


def _write_hibp_report(
    pwned: list[tuple[str, str, int]],
    out_path: Path,
) -> None:
    lines = [
        "FoxPort HIBP scan - passwords that appear in known data breaches.",
        "Reset these in the affected accounts before importing.",
        "Passwords themselves are NOT printed (only URL/username).",
        "",
    ]
    for origin_url, username, count in pwned:
        lines.append(f"  {origin_url}  /  {username}  ({count:,} breach occurrences)")
    write_text_atomic(out_path, "\n".join(lines) + "\n")


def migrate_passwords(
    profile: ChromiumProfile,
    out_dir: Path,
    *,
    dry_run: bool = False,
    row_filter: PasswordPredicate | None = None,
    hibp_scan: bool = False,
) -> PasswordResult:
    """Decrypt all logins in ``profile`` and write a Firefox-format CSV.

    Decryption runs once. The CSV writer and the optional HIBP scan both
    consume the same in-memory list of ``(PasswordRow, plaintext)`` tuples
    so we never pay the AES cost twice.

    Parameters
    ----------
    dry_run
        Counts items and exercises decryption but writes no files.
    row_filter
        Optional predicate run on each :class:`PasswordRow` BEFORE
        decryption. Return False to skip a row entirely (counts toward
        neither decrypted nor failed totals; it's as if the row didn't
        exist in the source).
    hibp_scan
        Opt-in. Runs each cleartext through
        :func:`foxport.crypto.hibp.scan_passwords` and writes
        ``compromised-passwords.txt`` listing hits (URL + username only —
        plaintext is never written to the report).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "passwords.csv"

    key = load_master_key(profile.local_state, browser_display=profile.browser)
    raw_rows = list(read_password_rows(profile))
    rows = [r for r in raw_rows if (row_filter is None or row_filter(r))]

    decrypted, skipped_empty, failures = _decrypt_all(rows, key)
    total = len(rows)

    hibp_report_path: Path | None = None
    hibp_hits = 0
    # Default to "disabled" — the user didn't opt in, or the dry-run
    # branch skipped the scan entirely.
    hibp_status = "disabled"

    if not dry_run:
        _write_csv(decrypted, csv_path)

        if hibp_scan and decrypted:
            from foxport.crypto.hibp import (
                HIBP_STATUS_NETWORK_ERROR,
                scan_passwords,
            )
            # Reuse the already-decrypted list — no second decrypt pass.
            scan_input = [(row.origin_url, row.username, plain)
                          for row, plain in decrypted]
            try:
                scan = scan_passwords(scan_input)
            except Exception as exc:  # noqa: BLE001 — network failure must not abort
                failures.append(f"hibp scan: {exc}")
                hibp_status = HIBP_STATUS_NETWORK_ERROR
            else:
                hibp_status = scan.status
                hibp_hits = len(scan.hits)
                if scan.network_errors:
                    failures.append(
                        f"hibp scan: {scan.network_errors} prefix lookup(s) "
                        "failed — some passwords were NOT checked"
                    )
                if scan.hits:
                    hibp_report_path = out_dir / "compromised-passwords.txt"
                    _write_hibp_report(scan.hits, hibp_report_path)

    return PasswordResult(
        csv_path=csv_path,
        total=total,
        decrypted=len(decrypted),
        skipped_empty=skipped_empty,
        failed=len(failures),
        failures=failures,
        hibp_report_path=hibp_report_path,
        hibp_hits=hibp_hits,
        hibp_status=hibp_status,
    )
