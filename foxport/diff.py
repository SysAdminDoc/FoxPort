"""Browser-profile diff viewer — show what's in the source that the target
doesn't already have, before committing a migration.

Useful for answering "what will actually change?" without running a full
migration first. Covers passwords (by URL+username key), bookmarks (by
URL), and extensions (by GUID).

Used by the CLI ``diff`` subcommand:

    python -m foxport.cli diff --source "Brave/Default" --target "Firefox/default-release"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from foxport.browsers.chromium import (
    BookmarkNode,
    PasswordRow,
    read_bookmarks,
    read_extensions,
    read_password_rows,
)
from foxport.browsers.detect import (
    ChromiumProfile,
    FirefoxProfile,
    read_installed_firefox_extensions,
)
from foxport.browsers.firefox_read import (
    read_firefox_bookmarks,
    read_firefox_logins,
)
from foxport.crypto.nss import NSSError
from foxport.migrate.extensions import CURATED_MAP
from foxport.migrate_reverse.extensions import AMO_GUID_TO_CHROME


@dataclass
class ProfileDiff:
    """Per-category diff counts + samples."""

    passwords_only_in_source: int = 0
    passwords_in_both: int = 0
    bookmark_urls_only_in_source: int = 0
    bookmark_urls_in_both: int = 0
    extensions_only_in_source: int = 0
    extensions_in_both: int = 0
    samples: dict[str, list[str]] = field(default_factory=dict)


def _flatten_bookmark_urls(roots: Iterable[BookmarkNode]) -> set[str]:
    urls: set[str] = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node.kind == "url" and node.url:
            urls.add(node.url)
        else:
            stack.extend(node.children)
    return urls


def diff_profiles(
    source: ChromiumProfile,
    target: FirefoxProfile,
    *,
    master_password: str = "",
) -> ProfileDiff:
    """Return a populated :class:`ProfileDiff` for source→target."""
    diff = ProfileDiff()

    # --- Passwords ---
    target_login_keys: set[str] = set()
    try:
        for fl in read_firefox_logins(target, master_password=master_password):
            target_login_keys.add(f"{fl.hostname}\x00{fl.username}")
    except NSSError:
        # Couldn't read the target's NSS (locked, no master pass) — treat as empty.
        target_login_keys = set()
    sample_pw: list[str] = []
    for row in read_password_rows(source):
        key = f"{row.origin_url}\x00{row.username}"
        if key in target_login_keys:
            diff.passwords_in_both += 1
        else:
            diff.passwords_only_in_source += 1
            if len(sample_pw) < 5:
                sample_pw.append(f"{row.origin_url} / {row.username}")
    diff.samples["passwords"] = sample_pw

    # --- Bookmarks ---
    target_urls = {bm.url for bm in read_firefox_bookmarks(target) if bm.url}
    source_urls = _flatten_bookmark_urls(read_bookmarks(source))
    only_in_source = source_urls - target_urls
    diff.bookmark_urls_only_in_source = len(only_in_source)
    diff.bookmark_urls_in_both = len(source_urls & target_urls)
    diff.samples["bookmarks"] = sorted(only_in_source)[:5]

    # --- Extensions ---
    installed_guids = read_installed_firefox_extensions(target)
    source_exts = read_extensions(source)
    sample_ext: list[str] = []
    inverted_guid_to_chrome = {v: k for k, v in AMO_GUID_TO_CHROME.items()}
    for ext in source_exts:
        slug = CURATED_MAP.get(ext.extension_id)
        # Try to figure out the AMO GUID for the source extension so we can
        # check it against the target's installed_guids set.
        amo_guid: str | None = ext.gecko_id
        if not amo_guid and slug:
            # Look up the GUID for this slug via the AMO-GUID-to-Chrome table
            # (inverted: slug -> chrome_id wins, but if we already have a
            # gecko id from the manifest we prefer that).
            amo_guid = inverted_guid_to_chrome.get(ext.extension_id)
        if amo_guid and amo_guid in installed_guids:
            diff.extensions_in_both += 1
        else:
            diff.extensions_only_in_source += 1
            if len(sample_ext) < 5:
                sample_ext.append(f"{ext.name} ({ext.extension_id})")
    diff.samples["extensions"] = sample_ext

    return diff
