"""Firefox-side helpers - discover import targets and prepare staging files.

FoxPort emits browser-native import artifacts by default (CSV / HTML / JSON /
OpenSearch XML / mozLz40) so the user always has a portable copy in the
output folder. It also offers opt-in *direct-write* paths for the Firefox
files where the official import dialog is missing or fragile —
``logins.json`` (via NSS), ``cookies.sqlite``, ``places.sqlite``, and
session ``recovery.jsonlz4``. Direct-write only runs when the target
profile is closed and goes through ``foxport.fileops.replace_file_atomic``
so an interrupted write can never leave a half-written file in the user's
profile.

Outputs land in a dated export folder alongside a generated ``README.txt``
and a machine-readable ``manifest.json`` so the artifacts are easy to find,
review, snapshot, restore, or import manually later.
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


def import_instructions(profile, exports: dict[str, Path | str]) -> str:
    """Build a human-readable instruction sheet for the produced exports.

    ``profile`` may be a :class:`FirefoxProfile` (forward direction) or a
    :class:`ChromiumProfile` (reverse direction). Reverse artifacts are detected
    by their Chrome-prefixed filenames so CLI and GUI exports get accurate copy
    without needing a target profile object.
    """

    def p(key: str) -> Path:
        return Path(exports[key])

    def is_chrome_artifact(key: str) -> bool:
        return p(key).name.startswith("chrome-")

    target = profile.label if profile else "your destination browser"
    lines: list[str] = [
        f"FoxPort migration files ready for {target}",
        "=" * 64,
        "",
    ]
    if "passwords" in exports:
        if is_chrome_artifact("passwords"):
            lines.extend([
                "Passwords:",
                f"  File: {p('passwords')}",
                "  Open Chrome, go to Settings -> Autofill and passwords -> Password Manager.",
                "  Use the three-dot menu to import the CSV. Chrome deduplicates by URL and username.",
                "  Delete the CSV after you verify the import; it contains plaintext passwords.",
                "",
            ])
        else:
            lines.extend([
                "Passwords:",
                f"  File: {p('passwords')}",
                "  Open Firefox or a Firefox-family browser, go to about:logins.",
                "  Use the three-dot menu -> Import from a File, then pick this CSV.",
                "  Firefox deduplicates by URL and username. Delete the CSV after verification.",
                "",
            ])
    if "hibp" in exports:
        lines.extend([
            "Compromised-password review:",
            f"  File: {p('hibp')}",
            "  Review these accounts before or immediately after import. The file lists",
            "  site and username only, not plaintext passwords.",
            "",
        ])
    if "bookmarks" in exports:
        if is_chrome_artifact("bookmarks"):
            lines.extend([
                "Bookmarks:",
                f"  File: {p('bookmarks')}",
                "  Open Chrome Bookmark Manager (Ctrl+Shift+O), then use Import bookmarks.",
                "  The Bookmarks Toolbar is emitted first so Chrome can promote it to the bar.",
                "",
            ])
        else:
            lines.extend([
                "Bookmarks:",
                f"  File: {p('bookmarks')}",
                "  Open Firefox Library (Ctrl+Shift+O).",
                "  Use Import and Backup -> Import Bookmarks from HTML, then pick this file.",
                "  Firefox's user import path may place toolbar items under",
                "  Other Bookmarks > Bookmarks Toolbar; drag those contents to Bookmarks Toolbar",
                "  in the Library tree if needed.",
                "",
            ])
    if "extensions" in exports:
        marketplace = "Chrome Web Store" if is_chrome_artifact("extensions") else "Firefox Add-ons"
        lines.extend([
            "Extensions:",
            f"  File: {p('extensions')}",
            f"  Open the HTML in the target browser and install each mapped {marketplace} item.",
            "  Unmatched rows are preserved so you can decide whether to skip or search manually.",
            "",
        ])
    if "cookies" in exports:
        lines.extend([
            "Cookies (advanced):",
            f"  File: {p('cookies')}",
            "  If FoxPort direct-write was enabled, this file was already installed after",
            "  backing up the existing cookies.sqlite.",
            "  For manual import, close Firefox completely, back up cookies.sqlite, copy this",
            "  file into the profile, and remove cookies.sqlite-wal / cookies.sqlite-shm if present.",
            "",
        ])
    if "history" in exports:
        lines.extend([
            "Browsing history (advanced):",
            f"  File: {p('history')}",
            "  If FoxPort direct-write was enabled, this file was already installed after",
            "  backing up places.sqlite and moving favicons.sqlite to a timestamped backup.",
            "  For manual import, close Firefox completely, back up places.sqlite, copy this",
            "  file into the profile, and move favicons.sqlite aside so Firefox can rebuild it.",
            "",
        ])
    if "autofill" in exports:
        lines.extend([
            "Form autofill:",
            f"  File: {p('autofill')}",
            "  Close Firefox completely, back up formhistory.sqlite in the profile, then",
            "  copy this file into its place. Reopen Firefox and verify common form entries.",
            "",
        ])
    if "cards" in exports:
        lines.extend([
            "Saved payment cards:",
            f"  File: {p('cards')}",
            "  Firefox has no equivalent local card store for direct import. Use this CSV as",
            "  a review/export artifact and delete it after moving data to your password manager.",
            "",
        ])
    if "search_engines" in exports:
        lines.extend([
            "Search engines:",
            f"  Inventory: {p('search_engines')}",
            "  OpenSearch XML files are in the search-engines folder next to this inventory.",
            "  Add the engines you want from Firefox Settings -> Search or via the browser's",
            "  OpenSearch install prompt where available.",
            "",
        ])
    if "open_tabs" in exports:
        lines.extend([
            "Open tabs / session restore:",
            f"  File: {p('open_tabs')}",
            "  If FoxPort direct-write was enabled, recovery.jsonlz4 was already installed",
            "  after backing up any existing recovery file.",
            "  For manual import, close Firefox, copy this file to",
            "  sessionstore-backups/recovery.jsonlz4 in the profile, then reopen Firefox.",
            "",
        ])
    if "downloads" in exports:
        lines.extend([
            "Downloads:",
            f"  File: {p('downloads')}",
            "  Firefox does not expose a stable native download-history import. Keep this CSV",
            "  as a portable reference for file names, source URLs, target paths, and timestamps.",
            "  When Downloads are selected with history direct-write, matching rows are also",
            "  annotated in the installed places.sqlite for Firefox's history/download views.",
            "",
        ])
    lines.append("Keep this folder until you have verified the import. FoxPort does not modify")
    lines.append("the source browser profile. Files containing secrets should be deleted once")
    lines.append("they are safely imported or moved to your password manager.")
    return "\n".join(lines)
