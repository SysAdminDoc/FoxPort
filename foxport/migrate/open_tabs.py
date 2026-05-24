"""Open-tabs migration — Chromium ``Sessions/Session_<num>`` → Firefox
``sessionstore-backups/recovery.jsonlz4``.

The Chromium SNSS format is well-documented but version-dependent: command
IDs and Pickle field layouts drift. Rather than maintain a per-Chrome-version
SNSS parser, this implementation uses the **URL-scanning fallback** the
xaitax/cookie_crimes community settled on:

1. Read the most recent ``Sessions/Session_<n>`` file in the source profile.
2. Scan the raw bytes for UTF-16LE strings beginning with ``http://``,
   ``https://``, or ``file://``. SNSS stores SerializedNavigationEntry URLs
   as UTF-16LE Pickle entries, so this finds them reliably even when the
   command structure shifts.
3. Dedupe (preserving order) and write a Firefox session-restore JSON.

Firefox's ``recovery.jsonlz4`` is:

    b"mozLz40\\0"  +  uint32_le(uncompressed_size)  +  lz4.block.compress(json)

The JSON shape is the minimum Firefox accepts: one window, one tab per URL,
``index=1`` so the first entry is selected.
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from foxport.browsers.detect import ChromiumProfile, FirefoxProfile


# Match UTF-16LE-encoded URLs in the SNSS binary. ``\x00`` between every char
# is what UTF-16LE looks like for ASCII URL bytes. The repeated char class is
# the RFC 3986 unreserved + reserved + percent-encoded set; using the full
# printable ASCII range would let one URL leak into the next when a Pickle
# field ends without a NUL gap.
_URL_UTF16_RE = re.compile(
    rb"(?:h\x00t\x00t\x00p\x00s?\x00|f\x00i\x00l\x00e\x00)"
    rb":\x00/\x00/\x00"
    rb"(?:[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]\x00){1,2048}"
)


@dataclass
class OpenTabsResult:
    out_path: Path
    tabs: int
    failures: list[str] = field(default_factory=list)


def _latest_session_file(profile: ChromiumProfile) -> Path | None:
    """Return the highest-numbered Session_<n> file in the profile's Sessions dir.

    Falls back to the legacy ``Current Session`` filename when present.
    """
    sessions_dir = profile.profile_dir / "Sessions"
    candidates: list[Path] = []
    if sessions_dir.is_dir():
        for p in sessions_dir.glob("Session_*"):
            candidates.append(p)
    legacy = profile.profile_dir / "Current Session"
    if legacy.is_file():
        candidates.append(legacy)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _extract_urls(session_bytes: bytes) -> list[str]:
    """Return open-tab URLs in original-order, deduped.

    URLs are stored as UTF-16LE Pickle fields. We strip the embedded NULs
    after match and dedupe via an order-preserving dict.
    """
    seen: dict[str, None] = {}
    for match in _URL_UTF16_RE.finditer(session_bytes):
        raw = match.group(0)
        # Strip every other byte (the UTF-16LE high byte for ASCII).
        url = raw.decode("utf-16-le", errors="ignore")
        # Many URLs trail with garbage characters from the next Pickle field;
        # cut at the first whitespace/control char.
        for i, ch in enumerate(url):
            if ord(ch) < 0x20 or ch in ('"', "<", ">", "\\"):
                url = url[:i]
                break
        if not url.startswith(("http://", "https://", "file://")):
            continue
        if len(url) < 8:
            continue
        seen.setdefault(url, None)
    return list(seen)


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
    """Walk the latest Chromium session file, extract every URL, and emit
    a Firefox-importable ``recovery.jsonlz4`` in ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "recovery.jsonlz4"
    failures: list[str] = []
    session = _latest_session_file(profile)
    if not session:
        failures.append("no Sessions/Session_* or Current Session file found")
        return OpenTabsResult(out_path=out_path, tabs=0, failures=failures)
    try:
        raw = session.read_bytes()
    except OSError as exc:
        failures.append(f"read {session}: {exc}")
        return OpenTabsResult(out_path=out_path, tabs=0, failures=failures)

    urls = _extract_urls(raw)

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
    shutil.copy2(result.out_path, target_path)
    return target_path
