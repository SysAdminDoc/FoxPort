"""Direct-write password migration via NSS (PK11SDR_Encrypt) → ``logins.json``.

Unlike the default CSV path (``foxport/migrate/passwords.py``), this module
writes Firefox's authoritative password store directly. The target profile
must be **closed**; we hold an NSS session that takes the same locks
Firefox itself does.

Layout of ``logins.json`` we produce:

    {
      "nextId": <int>,
      "logins": [
        {
          "id": <int>,
          "hostname": "<origin>",
          "httpRealm": null,
          "formSubmitURL": "<action>",
          "usernameField": "",
          "passwordField": "",
          "encryptedUsername": "<base64 NSS blob>",
          "encryptedPassword": "<base64 NSS blob>",
          "guid": "{<uuid>}",
          "encType": 1,
          "timeCreated": <ms>,
          "timeLastUsed": <ms>,
          "timePasswordChanged": <ms>,
          "timesUsed": 0
        },
        …
      ],
      "potentiallyVulnerablePasswords": [],
      "dismissedBreachAlertsByLoginGUID": {},
      "version": 3
    }

Firefox re-reads ``logins-backup.json`` on next launch if it differs from
``logins.json``, so we write **both** with identical content (atomic
swap then mirror).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from foxport.browsers.chromium import PasswordRow, read_password_rows
from foxport.browsers.detect import (
    ChromiumProfile,
    FirefoxProfile,
    is_firefox_profile_locked,
)
from foxport.crypto.dpapi import (
    ChromiumKey,
    DecryptionError,
    decrypt_value,
    load_master_key,
)
from foxport.crypto.nss import NSSError, NSSSession, open_session
from foxport.migrate.passwords import (
    _FOXPORT_LOGIN_NAMESPACE,
    _chrome_micros_to_firefox_millis,
)


@dataclass
class DirectWriteResult:
    """Outcome of an NSS direct-write migration."""

    target_logins_json: Path
    backup_file: Path
    total: int
    written: int
    skipped_existing: int
    failed: int
    failures: list[str] = field(default_factory=list)


class ProfileLockedError(RuntimeError):
    """The target profile is in use; bailing out before NSS gets confused."""


def _existing_guids(logins_json: Path) -> tuple[dict, set[str]]:
    """Read existing logins.json (if any) and return (parsed_dict, guid_set)."""
    if not logins_json.is_file():
        return {
            "nextId": 1,
            "logins": [],
            "potentiallyVulnerablePasswords": [],
            "dismissedBreachAlertsByLoginGUID": {},
            "version": 3,
        }, set()
    try:
        data = json.loads(logins_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "nextId": 1,
            "logins": [],
            "potentiallyVulnerablePasswords": [],
            "dismissedBreachAlertsByLoginGUID": {},
            "version": 3,
        }, set()
    guids: set[str] = set()
    for login in data.get("logins", []) or []:
        if isinstance(login, dict):
            guid = login.get("guid")
            if isinstance(guid, str):
                guids.add(guid)
    return data, guids


def _backup_target(logins_json: Path) -> Path:
    """Copy the existing logins.json to a timestamped sibling. Returns the backup path."""
    if not logins_json.is_file():
        return logins_json.with_suffix(".json.no-backup-needed")
    backup = logins_json.with_name(f"logins.foxport-backup-{int(Path(logins_json).stat().st_mtime)}.json")
    shutil.copy2(logins_json, backup)
    return backup


def _atomic_write(path: Path, content: str) -> None:
    """Write file atomically: temp file + os.replace."""
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with open(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        Path(tmp_name).replace(path)
    except Exception:
        try:
            Path(tmp_name).unlink()
        except OSError:
            pass
        raise


def _decrypt_chromium_rows(
    profile: ChromiumProfile,
    failures: list[str],
) -> list[tuple[PasswordRow, str]]:
    key = load_master_key(profile.local_state, browser_display=profile.browser)
    out: list[tuple[PasswordRow, str]] = []
    for row in read_password_rows(profile):
        if not row.password_blob:
            continue
        try:
            plaintext = decrypt_value(row.password_blob, key)
        except DecryptionError as exc:
            failures.append(f"{row.origin_url} / {row.username}: {exc}")
            continue
        if plaintext:
            out.append((row, plaintext))
    return out


def migrate_passwords_via_nss(
    source: ChromiumProfile,
    target: FirefoxProfile,
    *,
    master_password: str = "",
    dry_run: bool = False,
) -> DirectWriteResult:
    """Encrypt source logins with the target profile's NSS key and merge
    them into ``logins.json``. Refuses to run if the target is locked.

    Existing entries (matched by deterministic GUID) are skipped so re-runs
    are idempotent.
    """
    if is_firefox_profile_locked(target):
        raise ProfileLockedError(
            f"target profile {target.label} is locked — close Firefox before importing"
        )
    failures: list[str] = []
    decrypted = _decrypt_chromium_rows(source, failures)
    total = len(decrypted)
    logins_json = target.profile_dir / "logins.json"
    backup_json = target.profile_dir / "logins-backup.json"

    if dry_run:
        return DirectWriteResult(
            target_logins_json=logins_json,
            backup_file=logins_json.with_suffix(".json.dry-run"),
            total=total,
            written=0,
            skipped_existing=0,
            failed=len(failures),
            failures=failures,
        )

    existing, existing_guids = _existing_guids(logins_json)
    backup_path = _backup_target(logins_json)

    written = 0
    skipped_existing = 0
    next_id = int(existing.get("nextId", 1) or 1)
    logins_array: list[dict] = list(existing.get("logins", []) or [])

    try:
        session: NSSSession = open_session(target, master_password=master_password)
    except NSSError as exc:
        # Restore the backup pointer if we created one (we haven't written anything yet).
        raise

    with session:
        for row, plaintext in decrypted:
            stable_guid = "{" + str(uuid.uuid5(
                _FOXPORT_LOGIN_NAMESPACE,
                f"{row.origin_url}\x00{row.username}",
            )) + "}"
            if stable_guid in existing_guids:
                skipped_existing += 1
                continue
            try:
                enc_user = session.encrypt(row.username)
                enc_pass = session.encrypt(plaintext)
            except NSSError as exc:
                failures.append(f"{row.origin_url} / {row.username}: NSS encrypt failed: {exc}")
                continue
            logins_array.append({
                "id": next_id,
                "hostname": row.origin_url,
                "httpRealm": None,
                "formSubmitURL": row.action_url or "",
                "usernameField": "",
                "passwordField": "",
                "encryptedUsername": enc_user,
                "encryptedPassword": enc_pass,
                "guid": stable_guid,
                "encType": 1,
                "timeCreated": _chrome_micros_to_firefox_millis(row.date_created),
                "timeLastUsed": _chrome_micros_to_firefox_millis(row.date_last_used),
                "timePasswordChanged": _chrome_micros_to_firefox_millis(row.date_password_modified),
                "timesUsed": 0,
            })
            next_id += 1
            written += 1

    payload = dict(existing)
    payload["nextId"] = next_id
    payload["logins"] = logins_array
    payload.setdefault("potentiallyVulnerablePasswords", [])
    payload.setdefault("dismissedBreachAlertsByLoginGUID", {})
    payload["version"] = 3
    rendered = json.dumps(payload, indent=2)
    _atomic_write(logins_json, rendered)
    _atomic_write(backup_json, rendered)
    return DirectWriteResult(
        target_logins_json=logins_json,
        backup_file=backup_path,
        total=total,
        written=written,
        skipped_existing=skipped_existing,
        failed=len(failures),
        failures=failures,
    )
