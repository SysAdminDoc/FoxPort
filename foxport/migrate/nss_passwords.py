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
from foxport.fileops import write_text_atomic
from foxport.migrate.passwords import (
    _FOXPORT_LOGIN_NAMESPACE,
    _chrome_micros_to_firefox_millis,
)


@dataclass
class DirectWriteResult:
    """Outcome of an NSS direct-write migration.

    Invariant: ``total >= written + skipped_existing + failed`` (rows with
    empty plaintext are excluded from ``total`` upstream of this struct).
    """

    target_logins_json: Path
    backup_file: Path | None             # None when target had nothing to back up
    total: int
    written: int
    skipped_existing: int
    failed: int
    failures: list[str] = field(default_factory=list)
    # NSS reports its own version string via NSS_GetVersion(); we record it
    # so the run manifest + Done UI can show "encrypted via NSS 3.95 from
    # C:\Program Files\Mozilla Firefox\nss3.dll" instead of the user having
    # to guess which install actually serviced the call.
    nss_version: str = ""


class ProfileLockedError(RuntimeError):
    """The target profile is in use; bailing out before NSS gets confused."""


class LoginsCorruptError(RuntimeError):
    """The target's existing logins.json is unreadable / malformed.

    We refuse to proceed because overwriting it would destroy real login
    data the user has accumulated. The user should investigate the
    profile (typically a previous Firefox crash mid-write) before re-running.
    """


_EMPTY_LOGINS_STORE = {
    "nextId": 1,
    "logins": [],
    "potentiallyVulnerablePasswords": [],
    "dismissedBreachAlertsByLoginGUID": {},
    "version": 3,
}


def _read_existing_logins(logins_json: Path) -> tuple[dict, set[str]]:
    """Read existing ``logins.json`` and return ``(parsed_dict, guid_set)``.

    * File doesn't exist → return the empty-store skeleton.
    * File exists but I/O fails or JSON is malformed → raise
      :class:`LoginsCorruptError`. We deliberately do NOT treat this as
      "start from empty" because the previous code path silently
      overwrote real user data when the target was momentarily unreadable.
    """
    if not logins_json.is_file():
        return dict(_EMPTY_LOGINS_STORE), set()
    try:
        raw = logins_json.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoginsCorruptError(
            f"could not read existing {logins_json}: {exc}. "
            "Refusing to overwrite — investigate the profile before re-running."
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LoginsCorruptError(
            f"existing {logins_json} is not valid JSON ({exc}). "
            "Refusing to overwrite — investigate the profile before re-running."
        ) from exc
    if not isinstance(data, dict) or "logins" not in data:
        raise LoginsCorruptError(
            f"existing {logins_json} is missing the 'logins' key — refusing to overwrite."
        )
    # GUIDs are case-insensitive UUIDs surrounded by braces. Firefox itself
    # normalizes to lowercase, but logins.json can legitimately contain
    # mixed-case strings imported from older Firefox builds or third-party
    # tools. ``uuid.uuid5()`` always emits lowercase, so we lower both sides
    # at compare time to keep idempotent re-runs idempotent.
    guids: set[str] = set()
    for login in data.get("logins", []) or []:
        if isinstance(login, dict):
            guid = login.get("guid")
            if isinstance(guid, str):
                guids.add(guid.lower())
    return data, guids


def _backup_target(logins_json: Path) -> Path | None:
    """Copy the existing logins.json to a timestamped sibling.

    Returns the backup path, or ``None`` when the target didn't exist
    (nothing to back up).
    """
    if not logins_json.is_file():
        return None
    mtime = int(logins_json.stat().st_mtime)
    backup = logins_json.with_name(f"logins.foxport-backup-{mtime}.json")
    shutil.copy2(logins_json, backup)
    return backup


def _atomic_write(path: Path, content: str) -> None:
    """Write file atomically through the canonical fileops helper.

    Pre-v1.3.2 this was a local re-implementation that lacked
    ``fh.flush()`` + ``os.fsync(fh.fileno())`` before the rename — on a
    crash between the write and the rename, the temp file's bytes may
    not have hit the disk and the replaced ``logins.json`` would have
    pointed at zero-filled blocks. The canonical helper
    :func:`foxport.fileops.write_text_atomic` adds the missing fsync
    and shares the same ``.{name}.foxport-*`` tmpfile naming as every
    other atomic emitter, so a torn write leaves no orphans.
    """

    write_text_atomic(path, content)


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
            backup_file=None,
            total=total,
            written=0,
            skipped_existing=0,
            failed=len(failures),
            failures=failures,
        )

    # Read first — raises LoginsCorruptError if the existing logins.json
    # exists but is unparseable. Catching that and "starting from empty"
    # would silently destroy user data, so we let it propagate.
    existing, existing_guids = _read_existing_logins(logins_json)
    backup_path = _backup_target(logins_json)

    written = 0
    skipped_existing = 0
    next_id = int(existing.get("nextId", 1) or 1)
    logins_array: list[dict] = list(existing.get("logins", []) or [])

    # The version-skew guard inside open_session() will refuse if the loaded
    # nss3 reports a wildly out-of-step major. Once we're past it, capture
    # the version for the manifest record.
    session: NSSSession = open_session(target, master_password=master_password)
    nss_version = session._lib.version  # NSSLibrary is frozen; safe to read.
    with session:
        for row, plaintext in decrypted:
            stable_guid = "{" + str(uuid.uuid5(
                _FOXPORT_LOGIN_NAMESPACE,
                f"{row.origin_url}\x00{row.username}",
            )) + "}"
            # ``existing_guids`` is already lowercased; ``stable_guid`` is
            # lowercase by construction, but the explicit .lower() keeps the
            # invariant obvious for the next reader.
            if stable_guid.lower() in existing_guids:
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
        nss_version=nss_version,
    )
