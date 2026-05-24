"""Firefox → Chromium passwords CSV.

Chrome's password import (Settings → Autofill and passwords → Passwords →
three-dot menu → Import) accepts a CSV with these columns:

    name,url,username,password,note

* ``name`` is a human label (Chrome derives one from the URL when blank).
* ``note`` is optional (Chrome 110+ supports per-entry notes; pre-110
  silently ignores).

The CSV is comma-delimited, RFC 4180 quoting. Chrome only deduplicates on
``(url, username)``, so we keep Firefox's deterministic GUID-derived
identifier in the ``note`` field for traceability.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from foxport.browsers.detect import FirefoxProfile
from foxport.browsers.firefox_read import read_firefox_logins
from foxport.crypto.nss import NSSError


_CHROME_CSV_HEADER = ["name", "url", "username", "password", "note"]


@dataclass
class ReversePasswordResult:
    csv_path: Path
    total: int
    written: int
    failures: list[str] = field(default_factory=list)


def migrate_passwords_reverse(
    source: FirefoxProfile,
    out_dir: Path,
    *,
    master_password: str = "",
    dry_run: bool = False,
) -> ReversePasswordResult:
    """Decrypt every login in ``source`` and write a Chrome-importable CSV."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "chrome-passwords.csv"
    failures: list[str] = []
    written = 0

    try:
        logins = list(read_firefox_logins(source, master_password=master_password))
    except NSSError as exc:
        return ReversePasswordResult(
            csv_path=csv_path,
            total=0,
            written=0,
            failures=[f"NSS: {exc}"],
        )

    if dry_run:
        return ReversePasswordResult(
            csv_path=csv_path,
            total=len(logins),
            written=0,
            failures=failures,
        )

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL)
        writer.writerow(_CHROME_CSV_HEADER)
        for login in logins:
            try:
                # Chrome wants the full URL (host + scheme). Firefox's
                # `hostname` field already contains that; passing it raw
                # is what Chrome's own export does.
                writer.writerow([
                    login.hostname,
                    login.hostname,
                    login.username,
                    login.password,
                    f"foxport guid={login.guid}",
                ])
                written += 1
            except (csv.Error, OSError) as exc:
                failures.append(f"{login.hostname} / {login.username}: {exc}")

    return ReversePasswordResult(
        csv_path=csv_path,
        total=len(logins),
        written=written,
        failures=failures,
    )
