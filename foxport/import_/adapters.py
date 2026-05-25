"""Parsers for external bookmark export formats → flat ``BookmarkImport`` list.

Supports four common shapes:

* **Pocket** — ``ril_export.html`` is Netscape format with ``<h1>Unread/Read</h1>``
  group headers; the public Pocket export is also a JSON list.
* **Pinboard** — ``pinboard_export.json`` (list of objects with
  ``href, description, tags, time``).
* **Netscape HTML** — generic, what Chrome / Firefox / Safari emit.
* **OPML** — `<outline xmlUrl=... htmlUrl=...>` (Feedly / Inoreader feeds).

Each adapter returns a list of :class:`BookmarkImport` records. The
forward bookmarks emitter (:mod:`foxport.migrate.bookmarks`) doesn't
currently consume these; the manual-source tile uses them via a
dedicated path that emits a Chromium-shaped ``Bookmarks`` JSON file the
user can then re-run the full migration against.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BookmarkImport:
    """One bookmark from an external source."""

    url: str
    title: str
    tags: tuple[str, ...] = ()
    added_unix_secs: int = 0
    folder_path: tuple[str, ...] = ()


def detect_format(path: Path) -> str:
    """Return one of: ``"pocket-json"`` / ``"pinboard-json"`` / ``"netscape-html"``
    / ``"opml"`` / ``"unknown"``.

    Heuristic: peek at the first ~4 KB.
    """
    if not path.is_file():
        return "unknown"
    try:
        with path.open("rb") as fh:
            head = fh.read(4096)
    except OSError:
        return "unknown"
    if head[:5].lower().lstrip() == b"<?xml" and b"<opml" in head.lower():
        return "opml"
    if b"<!DOCTYPE NETSCAPE-Bookmark-file-1>" in head:
        return "netscape-html"
    # JSON shapes
    text_head = head.decode("utf-8", errors="ignore").lstrip()
    if text_head.startswith("["):
        # Could be Pinboard or Pocket — distinguish by keys.
        try:
            sample = json.loads(text_head[: 4 * 1024] + "]" if not text_head.endswith("]") else text_head)
        except ValueError:
            try:
                # Read the full file when the prefix isn't a complete array.
                sample = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return "unknown"
        if sample and isinstance(sample, list) and isinstance(sample[0], dict):
            keys = set(sample[0].keys())
            if {"href", "description"}.issubset(keys):
                return "pinboard-json"
            if {"item_id", "given_url"}.issubset(keys) or {"resolved_url"}.issubset(keys):
                return "pocket-json"
    return "unknown"


def parse_pinboard_json(path: Path) -> list[BookmarkImport]:
    import datetime as _dt
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[BookmarkImport] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        url = entry.get("href") or ""
        if not url:
            continue
        title = entry.get("description") or url
        tags_str = entry.get("tags") or ""
        tags = tuple(t for t in tags_str.split() if t) if isinstance(tags_str, str) else ()
        added = 0
        time_str = entry.get("time")
        if time_str:
            try:
                added = int(_dt.datetime.fromisoformat(time_str.replace("Z", "+00:00")).timestamp())
            except (TypeError, ValueError):
                added = 0
        out.append(BookmarkImport(
            url=url, title=title, tags=tags, added_unix_secs=added,
            folder_path=("Pinboard",),
        ))
    return out


def parse_pocket_json(path: Path) -> list[BookmarkImport]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[BookmarkImport] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        url = entry.get("resolved_url") or entry.get("given_url") or ""
        if not url:
            continue
        title = entry.get("resolved_title") or entry.get("given_title") or url
        tags = entry.get("tags") or {}
        if isinstance(tags, dict):
            tag_names = tuple(tags.keys())
        else:
            tag_names = ()
        added = 0
        time_str = entry.get("time_added")
        if time_str:
            try:
                added = int(time_str)
            except (TypeError, ValueError):
                added = 0
        out.append(BookmarkImport(
            url=url, title=title, tags=tag_names, added_unix_secs=added,
            folder_path=("Pocket",),
        ))
    return out


_NETSCAPE_HREF_RE = re.compile(
    r'<DT><A\s+HREF="([^"]+)"(?:[^>]*\sADD_DATE="(\d+)")?[^>]*>([^<]*)</A>',
    re.IGNORECASE,
)


def parse_netscape_html(path: Path) -> list[BookmarkImport]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    out: list[BookmarkImport] = []
    for match in _NETSCAPE_HREF_RE.finditer(text):
        url = match.group(1)
        added = int(match.group(2) or 0)
        title = match.group(3).strip() or url
        out.append(BookmarkImport(url=url, title=title, added_unix_secs=added,
                                   folder_path=("Imported",)))
    return out


def parse_opml(path: Path) -> list[BookmarkImport]:
    out: list[BookmarkImport] = []
    try:
        tree = ET.parse(str(path))
    except (OSError, ET.ParseError):
        return out
    root = tree.getroot()
    for outline in root.iter("outline"):
        url = outline.attrib.get("xmlUrl") or outline.attrib.get("htmlUrl") or ""
        if not url:
            continue
        title = outline.attrib.get("text") or outline.attrib.get("title") or url
        out.append(BookmarkImport(url=url, title=title, folder_path=("OPML feeds",)))
    return out


def parse_file(path: Path) -> tuple[str, list[BookmarkImport]]:
    """Detect format and parse. Returns ``(format_name, entries)``."""
    fmt = detect_format(path)
    if fmt == "pinboard-json":
        return fmt, parse_pinboard_json(path)
    if fmt == "pocket-json":
        return fmt, parse_pocket_json(path)
    if fmt == "netscape-html":
        return fmt, parse_netscape_html(path)
    if fmt == "opml":
        return fmt, parse_opml(path)
    return fmt, []


def write_netscape_html(entries: list[BookmarkImport], out_path: Path) -> None:
    """Emit a Firefox-importable Netscape HTML file from imported bookmarks.

    Groups by the first segment of ``folder_path`` (every adapter sets one —
    "Pocket" / "Pinboard" / "Imported" / "OPML feeds") so the user sees the
    origin in their Bookmarks Library after import. Atomic write so a
    crash mid-render can't leave a half-written HTML at the final path.
    """

    from html import escape

    from foxport.fileops import write_text_atomic

    groups: dict[str, list[BookmarkImport]] = {}
    for entry in entries:
        folder = entry.folder_path[0] if entry.folder_path else "Imported"
        groups.setdefault(folder, []).append(entry)

    buf: list[str] = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        "<TITLE>Bookmarks</TITLE>",
        "<H1>Bookmarks</H1>",
        "<DL><p>",
    ]
    for folder_name, items in groups.items():
        buf.append(f'    <DT><H3>{escape(folder_name)}</H3>')
        buf.append("    <DL><p>")
        for item in items:
            href = escape(item.url, quote=True)
            title = escape(item.title or item.url)
            date_attr = f' ADD_DATE="{item.added_unix_secs}"' if item.added_unix_secs else ""
            tag_attr = ""
            if item.tags:
                tag_attr = f' TAGS="{escape(",".join(item.tags), quote=True)}"'
            buf.append(f'        <DT><A HREF="{href}"{date_attr}{tag_attr}>{title}</A>')
        buf.append("    </DL><p>")
    buf.append("</DL><p>")
    write_text_atomic(out_path, "\n".join(buf) + "\n")
