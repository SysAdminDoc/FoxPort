"""Firefox-side helpers — discover import targets and prepare staging files.

FoxPort never writes directly into ``logins.json`` / ``places.sqlite`` — that
would corrupt active profiles and bypass Firefox's NSS encryption. Instead we
emit Firefox-native import formats:

* Passwords → CSV consumable by ``about:logins`` → "Import from a File"
  (Firefox 88+, LibreWolf, Waterfox).
* Bookmarks → Netscape Bookmark HTML consumable by the Library → Import.
* Extensions → an AMO install page list the user clicks through.

Outputs land in a single dated export folder so they're easy to find later.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from foxport.browsers.detect import FirefoxProfile


_UNSAFE_SLUG_RE = __import__("re").compile(r"[^A-Za-z0-9._\-]+")


def _safe_slug(value: str) -> str:
    """Collapse anything outside ``[A-Za-z0-9._-]`` to underscores and trim.

    Used on parts that flow into directory names — defangs path-traversal
    attempts (``..``, leading slash, NULs) and Unicode whitespace tricks.
    """
    cleaned = _UNSAFE_SLUG_RE.sub("_", value).strip("._-") or "profile"
    return cleaned[:120]                  # cap to keep total path under MAX_PATH


def make_export_dir(parent: Path, source_label: str, target_label: str) -> Path:
    """Create a timestamped subdir under ``parent`` to hold a single migration's output.

    Slug components are sanitized against path-traversal — `source_label`
    and `target_label` flow into a filesystem name, so we strip everything
    outside ``[A-Za-z0-9._-]`` first. The final path is asserted to live
    under ``parent.resolve()`` before creation.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = f"{_safe_slug(source_label)}__to__{_safe_slug(target_label)}"
    out = parent / f"{stamp}_{slug}"
    # Belt-and-suspenders: refuse any path that escapes the parent.
    parent_resolved = parent.expanduser().resolve()
    out_resolved = out.expanduser().resolve()
    try:
        out_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(
            f"refusing export path {out_resolved} (escapes parent {parent_resolved})"
        ) from exc
    out.mkdir(parents=True, exist_ok=True)
    return out


def import_instructions(profile, exports: dict[str, Path]) -> str:
    """Build a human-readable instruction sheet for the produced exports.

    ``profile`` may be a :class:`FirefoxProfile` (forward direction) or a
    :class:`ChromiumProfile` (reverse direction). The text is identical in
    structure; the destination-tool wording is generic enough to apply to
    both Firefox-family and Chromium-family targets.
    """
    target = profile.label if profile else "your destination browser"
    lines: list[str] = [
        f"FoxPort — migration files ready for {target}",
        "=" * 64,
        "",
    ]
    if "passwords" in exports:
        lines.extend([
            "Passwords:",
            f"  File: {exports['passwords']}",
            "  Open the target browser, go to about:logins.",
            "  Click the three-dot menu (top-right) -> Import from a File...",
            "  Pick the CSV above. Firefox will dedupe by URL+username.",
            "",
        ])
    if "bookmarks" in exports:
        lines.extend([
            "Bookmarks:",
            f"  File: {exports['bookmarks']}",
            "  Open the target browser, press Ctrl+Shift+O to open the Library.",
            "  Import and Backup -> Import Bookmarks from HTML... -> pick the file.",
            "  NOTE: Firefox's user-import path does NOT honor the bookmark-bar",
            "        toolbar tag. After import, the toolbar bookmarks will land",
            "        under 'Other Bookmarks > Bookmarks Toolbar'. Drag the",
            "        contents of that folder up to 'Bookmarks Toolbar' in the",
            "        Library tree to restore the original layout.",
            "",
        ])
    if "extensions" in exports:
        lines.extend([
            "Extensions:",
            f"  File: {exports['extensions']}",
            "  Open the HTML in the target browser and click each Install link.",
            "  Items marked NO MATCH have no known Firefox equivalent on AMO.",
            "",
        ])
    if "cookies" in exports:
        lines.extend([
            "Cookies (advanced):",
            f"  File: {exports['cookies']}",
            "  CLOSE Firefox completely, back up the existing cookies.sqlite in your",
            "  profile folder, then copy this file in its place. Delete cookies.sqlite-wal",
            "  and cookies.sqlite-shm if present.",
            "",
        ])
    if "history" in exports:
        lines.extend([
            "Browsing history (advanced):",
            f"  File: {exports['history']}",
            "  CLOSE Firefox completely, back up the existing places.sqlite in your",
            "  profile folder, then copy this file in its place. Delete favicons.sqlite",
            "  so Firefox rebuilds it from the new history. Bookmarks remain unaffected.",
            "",
        ])
    lines.append("Keep this folder until you've verified the import — the source")
    lines.append("browser was NOT modified.")
    return "\n".join(lines)
