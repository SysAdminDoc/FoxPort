"""Read Chromium profile artifacts: passwords, bookmarks, extensions.

All reads are non-destructive — the source files are copied to a scratch
location before SQLite opens them, so they work even while the browser is
running and holds a write-lock.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


# Schemes that exist only inside one browser family. Migrating these to a
# different browser produces broken links — `chrome://gpu/` is not
# navigable from Firefox, etc. The bookmark / history / open-tabs migrators
# default to filtering these unless the user explicitly opts in.
BROWSER_INTERNAL_SCHEMES = (
    "chrome://",
    "chrome-extension://",
    "chrome-search://",
    "chrome-untrusted://",
    "chrome-devtools://",
    "devtools://",
    "edge://",
    "brave://",
    "opera://",
    "vivaldi://",
    "yandex://",
    "arc://",
    "about:",
)


def is_browser_internal_url(url: str) -> bool:
    """True if ``url`` uses a browser-specific scheme that won't load in Firefox."""
    if not url:
        return False
    lowered = url.lower()
    return any(lowered.startswith(prefix) for prefix in BROWSER_INTERNAL_SCHEMES)

from foxport.browsers.detect import ChromiumProfile


@dataclass(frozen=True)
class PasswordRow:
    """A single saved credential extracted from ``Login Data``."""

    origin_url: str
    action_url: str
    username: str
    password_blob: bytes
    date_created: int
    date_last_used: int
    date_password_modified: int


@dataclass(frozen=True)
class BookmarkNode:
    """One bookmark or folder. ``children`` is empty for URL leaves."""

    kind: str               # "folder" or "url"
    name: str
    url: str | None
    date_added: int
    date_modified: int
    children: list["BookmarkNode"]


@dataclass(frozen=True)
class ExtensionInfo:
    """A single Chromium extension installed in this profile."""

    extension_id: str
    name: str
    version: str
    description: str
    homepage: str | None
    gecko_id: str | None = None         # browser_specific_settings.gecko.id, if present
    chrome_permissions: tuple[str, ...] = ()
    chrome_host_permissions: tuple[str, ...] = ()


def _copy_for_read(src: Path) -> Path:
    """Copy a SQLite file (and its WAL/SHM siblings) to a temp dir for safe reading."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="foxport_"))
    dest = tmp_dir / src.name
    shutil.copy2(src, dest)
    for suffix in ("-wal", "-shm"):
        sibling = src.with_name(src.name + suffix)
        if sibling.exists():
            shutil.copy2(sibling, dest.with_name(dest.name + suffix))
    return dest


def read_password_rows(profile: ChromiumProfile) -> Iterator[PasswordRow]:
    """Yield every saved credential in this profile's ``Login Data`` DB."""
    if not profile.login_data.is_file():
        return
    copy = _copy_for_read(profile.login_data)
    try:
        conn = sqlite3.connect(str(copy))
        try:
            cur = conn.execute(
                "SELECT origin_url, action_url, username_value, password_value, "
                "date_created, date_last_used, date_password_modified "
                "FROM logins"
            )
            for row in cur:
                yield PasswordRow(
                    origin_url=row[0] or "",
                    action_url=row[1] or "",
                    username=row[2] or "",
                    password_blob=bytes(row[3]) if row[3] else b"",
                    date_created=row[4] or 0,
                    date_last_used=row[5] or 0,
                    date_password_modified=row[6] or 0,
                )
        finally:
            conn.close()
    finally:
        shutil.rmtree(copy.parent, ignore_errors=True)


def _walk_bookmark(node: dict) -> BookmarkNode:
    kind = node.get("type", "url")
    name = node.get("name", "")
    url = node.get("url") if kind == "url" else None
    date_added = int(node.get("date_added", 0) or 0)
    date_modified = int(node.get("date_modified", 0) or 0)
    children = [_walk_bookmark(c) for c in node.get("children", [])] if kind == "folder" else []
    return BookmarkNode(
        kind="folder" if kind == "folder" else "url",
        name=name,
        url=url,
        date_added=date_added,
        date_modified=date_modified,
        children=children,
    )


def read_bookmarks(profile: ChromiumProfile) -> list[BookmarkNode]:
    """Return the top-level Bookmark Bar / Other / Mobile roots as folders."""
    if not profile.bookmarks.is_file():
        return []
    data = json.loads(profile.bookmarks.read_text(encoding="utf-8", errors="ignore"))
    roots = data.get("roots", {})
    out: list[BookmarkNode] = []
    # Preserve the user-visible order Chrome uses in its menu.
    for key, display in (
        ("bookmark_bar", "Bookmarks Toolbar"),
        ("other", "Other Bookmarks"),
        ("synced", "Mobile Bookmarks"),
    ):
        root = roots.get(key)
        if not root:
            continue
        node = _walk_bookmark(root)
        # Override the generic Chrome label with the matching Firefox folder name
        # so that imports land in the same place users expect.
        out.append(BookmarkNode(
            kind="folder",
            name=display,
            url=None,
            date_added=node.date_added,
            date_modified=node.date_modified,
            children=node.children,
        ))
    return out


def read_extensions(profile: ChromiumProfile) -> list[ExtensionInfo]:
    """Enumerate installed extensions by reading each manifest.json on disk."""
    root = profile.extensions_dir
    if not root.is_dir():
        return []
    out: list[ExtensionInfo] = []
    for ext_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        ext_id = ext_dir.name
        if len(ext_id) != 32:
            continue  # Chromium extension IDs are always 32 lowercase letters
        # Each extension has one or more version subdirs; pick the highest.
        version_dirs = sorted((p for p in ext_dir.iterdir() if p.is_dir()), reverse=True)
        if not version_dirs:
            continue
        manifest_path = version_dirs[0] / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            raw = manifest_path.read_text(encoding="utf-8", errors="ignore")
            manifest = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            continue
        name = _resolve_locale_string(manifest.get("name", ""), version_dirs[0])
        desc = _resolve_locale_string(manifest.get("description", ""), version_dirs[0])
        bss = manifest.get("browser_specific_settings") or manifest.get("applications") or {}
        gecko = bss.get("gecko") if isinstance(bss, dict) else None
        gecko_id = gecko.get("id") if isinstance(gecko, dict) else None
        perms = tuple(p for p in (manifest.get("permissions") or []) if isinstance(p, str))
        host_perms = tuple(p for p in (manifest.get("host_permissions") or []) if isinstance(p, str))
        out.append(ExtensionInfo(
            extension_id=ext_id,
            name=name or ext_id,
            version=str(manifest.get("version", "")),
            description=desc or "",
            homepage=manifest.get("homepage_url"),
            gecko_id=gecko_id if isinstance(gecko_id, str) else None,
            chrome_permissions=perms,
            chrome_host_permissions=host_perms,
        ))
    return out


def _resolve_locale_string(value: str, ext_root: Path) -> str:
    """Translate ``__MSG_foo__`` placeholders against the extension's _locales dir."""
    if not isinstance(value, str) or not value.startswith("__MSG_"):
        return value
    msg_key = value[6:-2] if value.endswith("__") else value[6:]
    locales_dir = ext_root / "_locales"
    if not locales_dir.is_dir():
        return value
    # Prefer en/en_US, then default_locale from manifest, then anything we find.
    candidates = ["en", "en_US", "en_GB"]
    for candidate in candidates + [p.name for p in locales_dir.iterdir() if p.is_dir()]:
        messages = locales_dir / candidate / "messages.json"
        if not messages.is_file():
            continue
        try:
            data = json.loads(messages.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, json.JSONDecodeError):
            continue
        entry = data.get(msg_key) or data.get(msg_key.lower())
        if isinstance(entry, dict) and entry.get("message"):
            return str(entry["message"])
    return value
