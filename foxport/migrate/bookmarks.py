"""Convert Chromium Bookmarks JSON to Netscape Bookmark HTML.

Firefox's Library -> Import Bookmarks from HTML accepts the legacy Netscape
format that Chrome, Safari, IE, and Firefox have all read/written for two
decades. The format:

    <!DOCTYPE NETSCAPE-Bookmark-file-1>
    <META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
    <TITLE>Bookmarks</TITLE>
    <H1>Bookmarks</H1>
    <DL><p>
        <DT><H3 ADD_DATE="..." LAST_MODIFIED="..." PERSONAL_TOOLBAR_FOLDER="true">Bookmarks Toolbar</H3>
        <DL><p>
            <DT><A HREF="https://..." ADD_DATE="...">Title</A>
        </DL><p>
    </DL><p>

Date attributes are Unix epoch *seconds*. Chrome stores its dates as WebKit
microseconds since 1601, so we convert.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Callable

from foxport.browsers.chromium import BookmarkNode, read_bookmarks
from foxport.browsers.detect import ChromiumProfile


_CHROME_EPOCH_OFFSET_SECS = 11644473600


@dataclass
class BookmarkResult:
    """Outcome of a bookmarks migration run."""

    html_path: Path
    folders: int
    urls: int


# A folder-path predicate. Receives the list of folder names from root to the
# folder being considered. Return True to include, False to skip.
FolderFilter = Callable[[list[str]], bool]


def _filter_node(node: BookmarkNode, path: list[str], keep: FolderFilter) -> BookmarkNode | None:
    """Return a deep-copy of ``node`` with folders filtered out, or None to drop."""
    if node.kind != "folder":
        return node
    here = path + [node.name]
    if not keep(here):
        return None
    new_children: list[BookmarkNode] = []
    for child in node.children:
        if child.kind == "folder":
            filtered = _filter_node(child, here, keep)
            if filtered is not None:
                new_children.append(filtered)
        else:
            new_children.append(child)
    return BookmarkNode(
        kind="folder",
        name=node.name,
        url=None,
        date_added=node.date_added,
        date_modified=node.date_modified,
        children=new_children,
    )


def _chrome_to_unix_seconds(chrome_us: int) -> int:
    if chrome_us <= 0:
        return 0
    secs = (chrome_us // 1_000_000) - _CHROME_EPOCH_OFFSET_SECS
    return secs if secs > 0 else 0


def _emit_folder(
    node: BookmarkNode,
    depth: int,
    buf: list[str],
    counter: list[int],
    *,
    is_toolbar: bool = False,
) -> None:
    pad = "    " * depth
    add_date = _chrome_to_unix_seconds(node.date_added)
    last_mod = _chrome_to_unix_seconds(node.date_modified)
    toolbar_attr = ' PERSONAL_TOOLBAR_FOLDER="true"' if is_toolbar else ""
    name = escape(node.name or "")
    buf.append(
        f'{pad}<DT><H3 ADD_DATE="{add_date}" LAST_MODIFIED="{last_mod}"{toolbar_attr}>{name}</H3>'
    )
    buf.append(f"{pad}<DL><p>")
    counter[0] += 1
    for child in node.children:
        if child.kind == "folder":
            _emit_folder(child, depth + 1, buf, counter)
        else:
            _emit_url(child, depth + 1, buf, counter)
    buf.append(f"{pad}</DL><p>")


def _emit_url(node: BookmarkNode, depth: int, buf: list[str], counter: list[int]) -> None:
    if not node.url:
        return
    pad = "    " * depth
    add_date = _chrome_to_unix_seconds(node.date_added)
    href = escape(node.url, quote=True)
    name = escape(node.name or node.url)
    buf.append(f'{pad}<DT><A HREF="{href}" ADD_DATE="{add_date}">{name}</A>')
    counter[1] += 1


def migrate_bookmarks(
    profile: ChromiumProfile,
    out_dir: Path,
    *,
    dry_run: bool = False,
    folder_filter: FolderFilter | None = None,
) -> BookmarkResult:
    """Walk ``profile``'s Bookmarks file and emit ``bookmarks.html``.

    When ``dry_run=True``, returns the counts without writing the HTML file.
    ``folder_filter`` is an optional predicate over the folder name path
    (root → leaf) returning False to skip a folder. The top-level roots
    (Bookmarks Toolbar / Other Bookmarks / Mobile Bookmarks) are never
    skipped — only their children can be filtered.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "bookmarks.html"
    roots = read_bookmarks(profile)
    if folder_filter:
        filtered_roots: list[BookmarkNode] = []
        for root in roots:
            kept = _filter_node(root, [], lambda path: True if not path else folder_filter(path))
            if kept is not None:
                filtered_roots.append(kept)
        roots = filtered_roots

    buf: list[str] = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        "<TITLE>Bookmarks</TITLE>",
        "<H1>Bookmarks</H1>",
        "<DL><p>",
    ]
    counter = [0, 0]  # [folders, urls]
    for root in roots:
        is_toolbar = root.name == "Bookmarks Toolbar"
        _emit_folder(root, 1, buf, counter, is_toolbar=is_toolbar)
    buf.append("</DL><p>")

    if not dry_run:
        html_path.write_text("\n".join(buf) + "\n", encoding="utf-8")
    return BookmarkResult(html_path=html_path, folders=counter[0], urls=counter[1])
