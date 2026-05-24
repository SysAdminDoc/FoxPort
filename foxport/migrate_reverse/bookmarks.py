"""Firefox → Chromium bookmarks (Netscape HTML).

Chrome's Bookmark Manager → import-from-HTML accepts the same Netscape
format we emit for Firefox-as-target, with one twist: Chrome maps the
**first** `<H3 PERSONAL_TOOLBAR_FOLDER="true">` folder to its Bookmarks
Bar. We make sure the Firefox ``toolbar`` root lands first and gets that
tag.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path

from foxport.browsers.detect import FirefoxProfile
from foxport.browsers.firefox_read import (
    FirefoxBookmark,
    read_firefox_bookmarks,
)


@dataclass
class ReverseBookmarkResult:
    html_path: Path
    folders: int
    urls: int


_ROOT_LABEL = {
    "toolbar": "Bookmarks Bar",
    "menu": "Other bookmarks",
    "unfiled": "Other bookmarks",
    "mobile": "Mobile bookmarks",
}


def _group_by_root(bookmarks: list[FirefoxBookmark]) -> dict[str, list[FirefoxBookmark]]:
    out: dict[str, list[FirefoxBookmark]] = {}
    for bm in bookmarks:
        root = bm.folder_path[0] if bm.folder_path else "unfiled"
        out.setdefault(root, []).append(bm)
    return out


def _emit_root(
    root_key: str,
    items: list[FirefoxBookmark],
    buf: list[str],
    counter: list[int],
) -> None:
    label = _ROOT_LABEL.get(root_key, root_key.title())
    is_toolbar = root_key == "toolbar"
    toolbar_attr = ' PERSONAL_TOOLBAR_FOLDER="true"' if is_toolbar else ""
    buf.append(f'    <DT><H3 ADD_DATE="0" LAST_MODIFIED="0"{toolbar_attr}>{escape(label)}</H3>')
    buf.append("    <DL><p>")
    counter[0] += 1
    # Group inside the root by sub-folder path.
    by_path: dict[tuple[str, ...], list[FirefoxBookmark]] = {}
    for bm in items:
        sub = bm.folder_path[1:]
        by_path.setdefault(sub, []).append(bm)
    # Emit nested folders.
    _emit_sub(by_path, (), 2, buf, counter)
    buf.append("    </DL><p>")


def _emit_sub(
    by_path: dict[tuple[str, ...], list[FirefoxBookmark]],
    cur: tuple[str, ...],
    depth: int,
    buf: list[str],
    counter: list[int],
) -> None:
    pad = "    " * depth
    # Emit URLs directly in this folder.
    for bm in by_path.get(cur, []):
        # Firefox stores µs since 1970; Netscape HTML wants seconds.
        add_date = max(0, bm.date_added_us // 1_000_000)
        buf.append(
            f'{pad}<DT><A HREF="{escape(bm.url, quote=True)}" '
            f'ADD_DATE="{add_date}">{escape(bm.title)}</A>'
        )
        counter[1] += 1
    # Find immediate child folders of ``cur``.
    seen_children: set[str] = set()
    for path in by_path:
        if len(path) > len(cur) and path[: len(cur)] == cur:
            child = path[len(cur)]
            if child not in seen_children:
                seen_children.add(child)
                new_path = cur + (child,)
                buf.append(f'{pad}<DT><H3 ADD_DATE="0" LAST_MODIFIED="0">{escape(child)}</H3>')
                buf.append(f"{pad}<DL><p>")
                counter[0] += 1
                _emit_sub(by_path, new_path, depth + 1, buf, counter)
                buf.append(f"{pad}</DL><p>")


def migrate_bookmarks_reverse(
    source: FirefoxProfile,
    out_dir: Path,
    *,
    dry_run: bool = False,
) -> ReverseBookmarkResult:
    """Walk Firefox places.sqlite and emit a Chrome-importable HTML file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "chrome-bookmarks.html"
    bookmarks = read_firefox_bookmarks(source)
    grouped = _group_by_root(bookmarks)

    buf: list[str] = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        "<TITLE>Bookmarks</TITLE>",
        "<H1>Bookmarks</H1>",
        "<DL><p>",
    ]
    counter = [0, 0]
    # Emit toolbar first so Chrome promotes it to the Bookmarks Bar.
    for root_key in ("toolbar", "menu", "unfiled", "mobile"):
        if root_key in grouped:
            _emit_root(root_key, grouped[root_key], buf, counter)
    buf.append("</DL><p>")

    if not dry_run:
        html_path.write_text("\n".join(buf) + "\n", encoding="utf-8")
    return ReverseBookmarkResult(
        html_path=html_path,
        folders=counter[0],
        urls=counter[1],
    )
