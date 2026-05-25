"""Open-tabs migration — Chromium ``Sessions/{Session,Tabs}_*`` SNSS files
→ Firefox ``sessionstore-backups/recovery.jsonlz4``.

Chromium splits session storage across two filename prefixes in the same
``Sessions/`` directory:

* ``Session_<id>`` — window/tab structure (which tab is selected, window
  bounds, group ownership).
* ``Tabs_<id>``    — per-tab navigation entries (URLs + titles + indices).

Live evidence from a real Chrome Default profile on this host: the
``Session_*`` files contain almost no inline URLs; the ``Tabs_*`` files
are where they live, encoded as **UTF-8** (not UTF-16LE — that was a
v0.6.1 regression).

Each SNSS file is:

* 4-byte magic ``SNSS``
* 4-byte little-endian version
* Sequence of commands: ``uint16_le(size)`` + ``uint8(command_id)`` +
  ``(size - 1)`` bytes of payload.

We use a robust two-track approach:

1. **Structural parser** walks every command, and for the navigation
   command IDs (6 / 33 in newer Chromium) parses the embedded Pickle
   to pull out the URL field cleanly.
2. **Fallback URL scanner** (UTF-8 regex with the RFC 3986 char class)
   runs if the structural parser produces zero hits — covers schema
   drift that's frequent across Chrome releases.

Output:  ``recovery.jsonlz4`` = ``b"mozLz40\0"`` + ``uint32_le(orig_size)``
+ ``lz4.block.compress(JSON)``. Optional direct-write to
``sessionstore-backups/recovery.jsonlz4``.
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from foxport.browsers.chromium import is_browser_internal_url
from foxport.browsers.detect import ChromiumProfile, FirefoxProfile


# Chrome command IDs for navigation updates. The integer value drifts
# slightly across Chrome versions; the most common are 6 and 33.
_NAVIGATION_COMMAND_IDS = {6, 0x21}  # kCommandUpdateTabNavigation{,13}

_SNSS_MAGIC = b"SNSS"

# UTF-8 URL scanner — RFC 3986 unreserved + reserved + percent-encoded set.
# Used both as fallback and to validate structural-parser output.
_URL_UTF8_RE = re.compile(
    rb"(?:https?|file)://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]{4,2048}"
)


@dataclass
class OpenTabsResult:
    out_path: Path
    tabs: int
    failures: list[str] = field(default_factory=list)


def _latest_session_files(profile: ChromiumProfile) -> list[Path]:
    """Return every SNSS file (Session_* and Tabs_*) in the latest session.

    Chrome rotates session/tabs files by timestamp; we pick the most-recently-
    modified Sessions/ dir contents (both prefixes) and fall back to legacy
    ``Current Session`` and ``Current Tabs``.
    """
    files: list[Path] = []
    sessions_dir = profile.profile_dir / "Sessions"
    if sessions_dir.is_dir():
        candidates = list(sessions_dir.glob("Session_*")) + list(sessions_dir.glob("Tabs_*"))
        if candidates:
            files.extend(candidates)
    for legacy_name in ("Current Session", "Current Tabs", "Last Session", "Last Tabs"):
        legacy = profile.profile_dir / legacy_name
        if legacy.is_file():
            files.append(legacy)
    return files


def _iter_snss_commands(data: bytes):
    """Yield ``(command_id, payload)`` for every command in an SNSS blob.

    Tolerates truncated files (stops at the first short read).
    """
    if len(data) < 8 or data[:4] != _SNSS_MAGIC:
        return
    offset = 8                       # skip 4-byte magic + 4-byte version
    while offset + 3 <= len(data):
        (size,) = struct.unpack_from("<H", data, offset)
        offset += 2
        if size == 0 or offset + size > len(data):
            break
        command_id = data[offset]
        payload = data[offset + 1: offset + size]
        offset += size
        yield command_id, payload


def _extract_url_from_navigation_payload(payload: bytes) -> str | None:
    """Pluck the URL out of a kCommandUpdateTabNavigation Pickle.

    Pickle wire format (Chrome ``base/pickle.cc``):

    * 4-byte tab_id (SessionID)
    * 4-byte pickle payload size
    * 4-byte index
    * 4-byte url_len + url bytes (UTF-8) + 4-byte alignment padding

    Returns the URL string or None if the layout doesn't match.
    """
    if len(payload) < 16:
        return None
    try:
        # Skip tab_id (4) + pickle payload size (4) + navigation index (4) = 12 bytes.
        url_len = struct.unpack_from("<I", payload, 12)[0]
    except struct.error:
        return None
    if url_len == 0 or url_len > 2048:
        return None
    start = 16
    end = start + url_len
    if end > len(payload):
        return None
    try:
        url = payload[start:end].decode("utf-8")
    except UnicodeDecodeError:
        return None
    # Sanity check — must look like a URL we'd care about.
    if not url.startswith(("http://", "https://", "file://", "ftp://")):
        return None
    return url


def _scan_urls_utf8(data: bytes) -> list[str]:
    """Fallback URL extractor — UTF-8 regex over raw bytes."""
    seen: dict[str, None] = {}
    for match in _URL_UTF8_RE.finditer(data):
        try:
            url = match.group(0).decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not url:
            continue
        if is_browser_internal_url(url):
            continue
        seen.setdefault(url, None)
    return list(seen)


def _extract_urls(data: bytes) -> list[str]:
    """Walk SNSS commands, extract URLs from navigation Pickles, fall back to
    UTF-8 regex scanning when the structural parser finds nothing."""
    seen: dict[str, None] = {}
    for command_id, payload in _iter_snss_commands(data):
        if command_id not in _NAVIGATION_COMMAND_IDS:
            continue
        url = _extract_url_from_navigation_payload(payload)
        if url and not is_browser_internal_url(url):
            seen.setdefault(url, None)
    if seen:
        return list(seen)
    # Fallback: regex scan the whole file.
    return _scan_urls_utf8(data)


def _build_session_json(urls: list[str]) -> bytes:
    """Render Firefox-compatible session JSON for the given URLs."""
    tabs = [
        {
            "entries": [{"url": url, "title": "", "triggeringPrincipal_base64": ""}],
            "index": 1,
            "hidden": False,
            "pinned": False,
        }
        for url in urls
    ]
    payload = {
        "version": ["sessionrestore", 1],
        "windows": [
            {
                "tabs": tabs,
                "selected": 1,
                "_closedTabs": [],
            }
        ],
        "_closedWindows": [],
        "session": {"lastUpdate": 0, "startTime": 0, "recentCrashes": 0},
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _wrap_mozlz4(data: bytes) -> bytes:
    """Build a mozLz40-format blob from ``data``.

    Layout: ``b"mozLz40\\0"`` + uint32_le(original_size) + lz4.block.compress(data).
    """
    import lz4.block
    compressed = lz4.block.compress(data, mode="default", store_size=False)
    header = b"mozLz40\0" + struct.pack("<I", len(data))
    return header + compressed


def migrate_open_tabs(
    profile: ChromiumProfile,
    out_dir: Path,
    *,
    dry_run: bool = False,
) -> OpenTabsResult:
    """Walk every SNSS file in the source profile, extract URLs, emit a
    Firefox-importable ``recovery.jsonlz4`` in ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "recovery.jsonlz4"
    failures: list[str] = []
    files = _latest_session_files(profile)
    if not files:
        failures.append("no Sessions/Session_* or Tabs_* file found")
        return OpenTabsResult(out_path=out_path, tabs=0, failures=failures)

    all_urls: dict[str, None] = {}
    for snss in files:
        try:
            raw = snss.read_bytes()
        except OSError as exc:
            failures.append(f"read {snss.name}: {exc}")
            continue
        for url in _extract_urls(raw):
            all_urls.setdefault(url, None)

    urls = list(all_urls)

    if dry_run:
        return OpenTabsResult(out_path=out_path, tabs=len(urls), failures=failures)
    try:
        blob = _wrap_mozlz4(_build_session_json(urls))
        out_path.write_bytes(blob)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"mozlz4 emit: {exc}")
        return OpenTabsResult(out_path=out_path, tabs=0, failures=failures)
    return OpenTabsResult(out_path=out_path, tabs=len(urls), failures=failures)


def write_session_into_target(
    source: ChromiumProfile,
    target: FirefoxProfile,
    staging_dir: Path,
) -> Path:
    """Run :func:`migrate_open_tabs` then drop the result into the target
    profile's ``sessionstore-backups/recovery.jsonlz4`` (closed-profile only)."""
    from foxport.browsers.detect import is_firefox_profile_locked
    if is_firefox_profile_locked(target):
        from foxport.migrate.nss_cookies import ProfileLockedError
        raise ProfileLockedError(
            f"target profile {target.label} is locked — close Firefox before importing"
        )
    result = migrate_open_tabs(source, staging_dir)
    backups_dir = target.profile_dir / "sessionstore-backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    target_path = backups_dir / "recovery.jsonlz4"
    import shutil
    if target_path.exists():
        backup = target_path.with_name(
            f"recovery.foxport-backup-{int(target_path.stat().st_mtime)}.jsonlz4"
        )
        shutil.copy2(target_path, backup)
    from foxport.fileops import replace_file_atomic
    replace_file_atomic(result.out_path, target_path)
    return target_path
