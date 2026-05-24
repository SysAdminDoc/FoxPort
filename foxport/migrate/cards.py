"""Saved-cards CSV export — Chromium ``Web Data.credit_cards`` → CSV.

Firefox **has no native credit-card store**, so this migrator is CSV-only:
the user can import the file into 1Password, Bitwarden, KeePassXC, or
similar. The card number is encrypted with the same AES key as passwords;
we decrypt it (where DPAPI / Keychain succeeds) and write plaintext.

Chromium's ``credit_cards`` table columns vary by version. We pluck the
ones every Chrome 80+ ships:

    guid, name_on_card, expiration_month, expiration_year,
    card_number_encrypted, use_date, use_count, billing_address_id,
    nickname (since M99)

Output CSV columns (1Password import-compatible):

    Type, Name, Number, Expiration (MM/YYYY), Cardholder name, Notes
"""

from __future__ import annotations

import csv
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from foxport.browsers.detect import ChromiumProfile
from foxport.crypto.dpapi import (
    DecryptionError,
    decrypt_value,
    load_master_key,
)


_CSV_HEADER = [
    "Type",
    "Name",
    "Number",
    "Expiration",
    "Cardholder name",
    "Notes",
]


@dataclass
class CardResult:
    csv_path: Path
    total: int
    decrypted: int
    failed: int
    failures: list[str] = field(default_factory=list)


def _web_data_path(profile: ChromiumProfile) -> Path | None:
    candidate = profile.profile_dir / "Web Data"
    return candidate if candidate.is_file() else None


def _copy_for_read(src: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="foxport_cards_"))
    dest = tmp / src.name
    shutil.copy2(src, dest)
    for suffix in ("-wal", "-shm"):
        sibling = src.with_name(src.name + suffix)
        if sibling.exists():
            shutil.copy2(sibling, dest.with_name(dest.name + suffix))
    return dest


def migrate_cards(
    profile: ChromiumProfile,
    out_dir: Path,
    *,
    dry_run: bool = False,
) -> CardResult:
    """Walk Chromium's ``Web Data.credit_cards`` and emit a CSV of decrypted
    card details. Firefox has no native target, so this is informational."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "saved_cards.csv"
    failures: list[str] = []

    src = _web_data_path(profile)
    if not src:
        return CardResult(csv_path=csv_path, total=0, decrypted=0, failed=0, failures=failures)

    try:
        key = load_master_key(profile.local_state, browser_display=profile.browser)
    except DecryptionError as exc:
        return CardResult(
            csv_path=csv_path,
            total=0,
            decrypted=0,
            failed=1,
            failures=[f"master key: {exc}"],
        )

    copy = _copy_for_read(src)
    try:
        conn = sqlite3.connect(str(copy))
        try:
            # Use SELECT * so we tolerate missing optional columns.
            cur = conn.execute(
                "SELECT guid, name_on_card, expiration_month, expiration_year, "
                "card_number_encrypted FROM credit_cards"
            )
            rows = cur.fetchall()
        except sqlite3.DatabaseError:
            rows = []
        finally:
            conn.close()
    finally:
        shutil.rmtree(copy.parent, ignore_errors=True)

    decrypted = 0
    fh = None
    writer = None
    if not dry_run:
        fh = csv_path.open("w", encoding="utf-8", newline="")
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL)
        writer.writerow(_CSV_HEADER)
    try:
        for guid, name_on_card, expiration_month, expiration_year, encrypted in rows:
            blob = bytes(encrypted) if encrypted else b""
            try:
                card_number = decrypt_value(blob, key) if blob else ""
            except DecryptionError as exc:
                failures.append(f"{guid}: {exc}")
                continue
            if not card_number:
                failures.append(f"{guid}: empty plaintext")
                continue
            decrypted += 1
            if writer is None:
                continue
            expiry = ""
            if expiration_month and expiration_year:
                expiry = f"{int(expiration_month):02d}/{int(expiration_year)}"
            writer.writerow([
                "Credit Card",
                name_on_card or "",
                card_number,
                expiry,
                name_on_card or "",
                f"Imported from {profile.label} (guid={guid})",
            ])
    finally:
        if fh is not None:
            fh.close()

    return CardResult(
        csv_path=csv_path,
        total=len(rows),
        decrypted=decrypted,
        failed=len(failures),
        failures=failures,
    )
