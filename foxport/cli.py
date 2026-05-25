"""Command-line interface for FoxPort.

Useful for automation, scripted batch migrations, and dry-run sanity checks
without launching the GUI.

Examples:
    # List everything FoxPort can see
    python -m foxport.cli list

    # Migrate Brave Default -> Firefox default, everything except cookies
    python -m foxport.cli migrate \\
        --source "Brave/Default" --target "Firefox/default-release" \\
        --items passwords,bookmarks,extensions

    # Dry run to count things and exercise decryption
    python -m foxport.cli migrate --source "Google Chrome/Default" --all --dry-run

The ``--source`` and ``--target`` arguments use the ``"<browser>/<profile>"``
shape printed by ``list``; case-insensitive substring match also works
(``brave/default`` finds ``Brave - Default``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from foxport import __app_name__, __version__
from foxport.browsers.detect import (
    ChromiumProfile,
    FirefoxProfile,
    detect_chromium,
    detect_firefox,
    is_chromium_running,
    is_firefox_profile_locked,
    read_installed_firefox_extensions,
)
from foxport.browsers.firefox import import_instructions, make_export_dir
from foxport.crypto.dpapi import DecryptionError
from foxport.migrate.autofill import migrate_autofill
from foxport.migrate.bookmarks import migrate_bookmarks
from foxport.migrate.cards import migrate_cards
from foxport.migrate.cookies import migrate_cookies
from foxport.migrate.extensions import migrate_extensions
from foxport.migrate.downloads import migrate_downloads
from foxport.migrate.history import migrate_history
from foxport.migrate.open_tabs import migrate_open_tabs
from foxport.migrate.passwords import migrate_passwords
from foxport.migrate.search_engines import migrate_search_engines
from foxport.migrate_reverse.bookmarks import migrate_bookmarks_reverse
from foxport.migrate_reverse.extensions import migrate_extensions_reverse
from foxport.migrate_reverse.passwords import migrate_passwords_reverse


ALL_ITEMS = (
    "passwords", "bookmarks", "extensions", "cookies", "history",
    "autofill", "cards", "search_engines", "open_tabs", "downloads",
)

REVERSE_ITEMS = ("passwords", "bookmarks", "extensions")


class AmbiguousProfileMatch(SystemExit):
    """Raised when a CLI ``--source``/``--target`` substring matches >1 profile.

    We exit non-zero rather than silently picking one; silent wrong-profile
    selection produced the diff-CLI bug logged in RESEARCH_FEATURE_PLAN.md.
    """

    def __init__(self, spec: str, matches: list[str]) -> None:
        msg = (
            f"error: '{spec}' matched {len(matches)} profiles; please be more specific:\n"
            + "\n".join(f"  {m}" for m in matches)
        )
        print(msg, file=sys.stderr)
        super().__init__(2)


def _find_chromium(spec: str, profiles: list[ChromiumProfile]) -> ChromiumProfile | None:
    spec_lower = spec.lower()
    # 1. Exact "Browser/Profile" or full label match wins outright.
    for p in profiles:
        if f"{p.browser}/{p.profile_name}".lower() == spec_lower:
            return p
        if p.label.lower() == spec_lower:
            return p
    # 2. Substring match must be UNIQUE; refuse ambiguous matches loudly.
    substring_hits = [
        p for p in profiles
        if spec_lower in f"{p.browser}/{p.profile_name}".lower()
        or spec_lower in p.label.lower()
    ]
    if len(substring_hits) > 1:
        raise AmbiguousProfileMatch(spec, [f"{p.browser}/{p.profile_name}" for p in substring_hits])
    if len(substring_hits) == 1:
        return substring_hits[0]
    return None


def _find_firefox(spec: str, profiles: list[FirefoxProfile]) -> FirefoxProfile | None:
    spec_lower = spec.lower()
    for p in profiles:
        if f"{p.browser}/{p.profile_name}".lower() == spec_lower:
            return p
        if p.label.lower() == spec_lower:
            return p
    substring_hits = [
        p for p in profiles
        if spec_lower in f"{p.browser}/{p.profile_name}".lower()
        or spec_lower in p.label.lower()
    ]
    if len(substring_hits) > 1:
        raise AmbiguousProfileMatch(spec, [f"{p.browser}/{p.profile_name}" for p in substring_hits])
    if len(substring_hits) == 1:
        return substring_hits[0]
    return None


def _parse_items(value: str | None, all_flag: bool) -> set[str]:
    if all_flag:
        return set(ALL_ITEMS)
    if not value:
        return {"passwords", "bookmarks", "extensions"}
    items: set[str] = set()
    for token in value.split(","):
        token = token.strip().lower()
        if token not in ALL_ITEMS:
            raise SystemExit(
                f"unknown item '{token}'; pick from {', '.join(ALL_ITEMS)}"
            )
        items.add(token)
    return items


def _cmd_list(args: argparse.Namespace) -> int:
    print(f"{__app_name__} v{__version__}")
    chromium = detect_chromium()
    firefox = detect_firefox()
    print("\nChromium sources:")
    if not chromium:
        print("  (none detected)")
    for p in chromium:
        marker = " [running]" if is_chromium_running(p) else ""
        print(f"  {p.browser}/{p.profile_name}{marker}")
        print(f"    {p.profile_dir}")
    print("\nFirefox targets:")
    if not firefox:
        print("  (none detected)")
    for p in firefox:
        default = " [default]" if p.is_default else ""
        locked = " [locked]" if is_firefox_profile_locked(p) else ""
        print(f"  {p.browser}/{p.profile_name}{default}{locked}")
        print(f"    {p.profile_dir}")
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    chromium = detect_chromium()
    firefox = detect_firefox()
    source = _find_chromium(args.source, chromium)
    if not source:
        print(f"error: no Chromium source matched '{args.source}'", file=sys.stderr)
        print("\nAvailable sources:", file=sys.stderr)
        for p in chromium:
            print(f"  {p.browser}/{p.profile_name}", file=sys.stderr)
        return 2

    target: FirefoxProfile | None = None
    if args.target:
        target = _find_firefox(args.target, firefox)
        if not target:
            print(f"error: no Firefox target matched '{args.target}'", file=sys.stderr)
            return 2

    items = _parse_items(args.items, args.all)
    out_root = Path(args.out) if args.out else Path.home() / "Documents" / "FoxPort"
    target_label = target.label if target else "firefox"
    if args.dry_run:
        target_label += "_dryrun"
    out_dir = make_export_dir(out_root, source.label, target_label)
    print(f"Source: {source.label}")
    print(f"Target: {target.label if target else '(none - files only)'}")
    print(f"Items:  {', '.join(sorted(items))}")
    print(f"Output: {out_dir}")
    if args.dry_run:
        print("Mode:   DRY RUN")

    already_installed: set[str] = set()
    if target and not args.dry_run:
        already_installed = read_installed_firefox_extensions(target)

    exports: dict[str, Path] = {}

    if "passwords" in items:
        print("\n[passwords]")
        try:
            r = migrate_passwords(source, out_dir, dry_run=args.dry_run, hibp_scan=args.hibp)
        except DecryptionError as exc:
            print(f"  FAILED: {exc}")
        else:
            print(f"  {r.decrypted} decrypted, {r.skipped_empty} empty, "
                  f"{r.failed} failed of {r.total} total")
            if args.hibp:
                print(f"  HIBP: {r.hibp_hits} compromised passwords"
                      + (f" - see {r.hibp_report_path.name}" if r.hibp_report_path else ""))
                if r.hibp_report_path and not args.dry_run:
                    exports["hibp"] = r.hibp_report_path
            if not args.dry_run:
                exports["passwords"] = r.csv_path

    if "bookmarks" in items:
        print("\n[bookmarks]")
        r = migrate_bookmarks(source, out_dir, dry_run=args.dry_run)
        print(f"  {r.urls} URLs across {r.folders} folders")
        if not args.dry_run:
            exports["bookmarks"] = r.html_path

    if "extensions" in items:
        print("\n[extensions]")
        r = migrate_extensions(
            source, out_dir,
            online=not args.no_online,
            already_installed_guids=already_installed,
            dry_run=args.dry_run,
        )
        print(f"  {r.matched} matched ({r.already_installed} already installed), "
              f"{r.unmatched} unmatched of {len(r.matches)} installed")
        if not args.dry_run:
            exports["extensions"] = r.html_path

    if "cookies" in items:
        print("\n[cookies]")
        try:
            r = migrate_cookies(source, out_dir, dry_run=args.dry_run)
        except DecryptionError as exc:
            print(f"  FAILED: {exc}")
        else:
            print(f"  {r.decrypted} decrypted, {r.failed} failed of {r.total} total")
            if not args.dry_run:
                exports["cookies"] = r.sqlite_path

    if "history" in items:
        print("\n[history]")
        r = migrate_history(source, out_dir, dry_run=args.dry_run)
        print(f"  {r.urls} URLs / {r.visits} visits ({len(r.failures)} failed)")
        if not args.dry_run:
            exports["history"] = r.sqlite_path

    if "autofill" in items:
        print("\n[autofill]")
        r = migrate_autofill(source, out_dir, dry_run=args.dry_run)
        print(f"  {r.written} field/value pairs ({r.skipped} skipped, {len(r.failures)} failed)")
        if not args.dry_run:
            exports["autofill"] = r.sqlite_path

    if "cards" in items:
        print("\n[cards]")
        try:
            r = migrate_cards(source, out_dir, dry_run=args.dry_run)
        except DecryptionError as exc:
            print(f"  FAILED: {exc}")
        else:
            print(f"  {r.decrypted} decrypted, {r.failed} failed of {r.total} total")
            if not args.dry_run and r.decrypted > 0:
                exports["cards"] = r.csv_path

    if "search_engines" in items:
        print("\n[search_engines]")
        r = migrate_search_engines(source, out_dir, dry_run=args.dry_run)
        print(f"  {r.written} OpenSearch XML files written ({r.total} total entries)")
        if not args.dry_run:
            exports["search_engines"] = r.json_path

    if "open_tabs" in items:
        print("\n[open_tabs]")
        r = migrate_open_tabs(source, out_dir, dry_run=args.dry_run)
        print(f"  {r.tabs} URL(s) recovered ({len(r.failures)} failure(s))")
        if not args.dry_run and r.tabs > 0:
            exports["open_tabs"] = r.out_path

    if "downloads" in items:
        print("\n[downloads]")
        r = migrate_downloads(source, out_dir, dry_run=args.dry_run)
        print(f"  {r.written} of {r.total} download(s) exported")
        if not args.dry_run and r.written > 0:
            exports["downloads"] = r.csv_path

    if exports:
        instructions_path = out_dir / "README.txt"
        instructions_path.write_text(
            import_instructions(target, exports), encoding="utf-8"
        )
        print(f"\nInstructions: {instructions_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="foxport",
        description=f"{__app_name__} v{__version__} - Chromium to Firefox migration",
    )
    parser.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List detected source and target profiles")

    mig = sub.add_parser("migrate", help="Run a one-shot migration")
    mig.add_argument("--source", required=True,
                     help="Source profile (e.g. 'Brave/Default'; case-insensitive substring match works)")
    mig.add_argument("--target", default=None,
                     help="Target Firefox profile (optional; files-only mode if omitted)")
    mig.add_argument("--items", default=None,
                     help=f"Comma-separated subset of {','.join(ALL_ITEMS)} (default: passwords,bookmarks,extensions)")
    mig.add_argument("--all", action="store_true",
                     help="Equivalent to --items " + ",".join(ALL_ITEMS))
    mig.add_argument("--dry-run", action="store_true",
                     help="Count items + exercise decryption, write nothing")
    mig.add_argument("--out", default=None,
                     help="Output root directory (default: ~/Documents/FoxPort)")
    mig.add_argument("--no-online", action="store_true",
                     help="Skip AMO online lookup for unknown extensions")
    mig.add_argument("--hibp", action="store_true",
                     help="Check decrypted passwords against haveibeenpwned.com (k-anonymity API)")

    snap = sub.add_parser("snapshot",
                          help="Bundle a previous output folder into a portable .fxport archive")
    snap.add_argument("--input-dir", required=True,
                     help="Output folder produced by a previous `migrate` run")
    snap.add_argument("--out", required=True, help="Path to write the .fxport file")
    snap.add_argument("--source-label", default="(unknown)",
                     help="Human label for the source profile (recorded in the manifest)")
    snap.add_argument("--target-label", default="(unknown)",
                     help="Human label for the target profile")
    snap.add_argument("--passphrase", default="",
                     help="If set, encrypt the bundle with PBKDF2 + AES-256-GCM")

    restore = sub.add_parser("restore",
                              help="Unpack a .fxport bundle back into a folder")
    restore.add_argument("--snapshot", required=True, help="Path to the .fxport file")
    restore.add_argument("--out-dir", required=True, help="Folder to write the unpacked artifacts to")
    restore.add_argument("--passphrase", default="",
                         help="Passphrase for encrypted bundles (omit for plain ones)")
    restore.add_argument("--overwrite", action="store_true",
                         help="Allow restore into a non-empty output directory")

    diff = sub.add_parser("diff",
                           help="Show what's in the source that the target doesn't have yet")
    diff.add_argument("--source", required=True, help="Chromium source profile")
    diff.add_argument("--target", required=True, help="Firefox target profile")
    diff.add_argument("--master-password", default="",
                       help="Master password for the target Firefox profile, if set")

    rev = sub.add_parser("migrate-reverse",
                          help="Reverse direction: Firefox profile to Chromium-importable bundle")
    rev.add_argument("--source", required=True,
                     help="Firefox-family source profile (e.g. 'Firefox/default-release')")
    rev.add_argument("--items", default=None,
                     help=f"Comma-separated subset of {','.join(REVERSE_ITEMS)} (default: all three)")
    rev.add_argument("--master-password", default="",
                     help="Master password for the source Firefox profile, if set")
    rev.add_argument("--dry-run", action="store_true",
                     help="Decrypt and count, write nothing")
    rev.add_argument("--out", default=None,
                     help="Output root directory (default: ~/Documents/FoxPort)")
    return parser


def _cmd_migrate_reverse(args: argparse.Namespace) -> int:
    firefox = detect_firefox()
    source = _find_firefox(args.source, firefox)
    if not source:
        print(f"error: no Firefox source matched '{args.source}'", file=sys.stderr)
        print("\nAvailable Firefox profiles:", file=sys.stderr)
        for p in firefox:
            print(f"  {p.browser}/{p.profile_name}", file=sys.stderr)
        return 2
    items = set((args.items or ",".join(REVERSE_ITEMS)).split(","))
    items = {i.strip().lower() for i in items if i.strip()}
    unknown = items - set(REVERSE_ITEMS)
    if unknown:
        print(f"error: unknown reverse items {unknown}", file=sys.stderr)
        return 2
    out_root = Path(args.out) if args.out else Path.home() / "Documents" / "FoxPort"
    label = f"{source.label}_reverse" + ("_dryrun" if args.dry_run else "")
    out_dir = make_export_dir(out_root, label, "chrome")
    print(f"Source: {source.label}")
    print(f"Items:  {', '.join(sorted(items))}")
    print(f"Output: {out_dir}")
    exports: dict[str, Path] = {}

    if "passwords" in items:
        print("\n[passwords]")
        r = migrate_passwords_reverse(source, out_dir,
                                       master_password=args.master_password,
                                       dry_run=args.dry_run)
        print(f"  {r.written} written, {len(r.failures)} failed of {r.total} total")
        if not args.dry_run and r.written > 0:
            exports["passwords"] = r.csv_path
    if "bookmarks" in items:
        print("\n[bookmarks]")
        r = migrate_bookmarks_reverse(source, out_dir, dry_run=args.dry_run)
        print(f"  {r.urls} URLs across {r.folders} folders")
        if not args.dry_run and r.urls > 0:
            exports["bookmarks"] = r.html_path
    if "extensions" in items:
        print("\n[extensions]")
        r = migrate_extensions_reverse(source, out_dir, dry_run=args.dry_run)
        print(f"  {r.matched} matched, {r.unmatched} unmatched of {len(r.matches)} installed")
        if not args.dry_run and r.matches:
            exports["extensions"] = r.html_path
    if exports:
        instructions_path = out_dir / "README.txt"
        instructions_path.write_text(
            import_instructions(None, exports), encoding="utf-8"
        )
        print(f"\nInstructions: {instructions_path}")
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    chromium = detect_chromium()
    firefox = detect_firefox()
    source = _find_chromium(args.source, chromium)
    target = _find_firefox(args.target, firefox)
    if not source or not target:
        if not source:
            print(f"error: no Chromium source matched '{args.source}'", file=sys.stderr)
        if not target:
            print(f"error: no Firefox target matched '{args.target}'", file=sys.stderr)
        return 2
    from foxport.diff import diff_profiles
    d = diff_profiles(source, target, master_password=args.master_password)
    print(f"Diff: {source.label} -> {target.label}")
    print()
    print(f"Passwords:  +{d.passwords_only_in_source} new, "
          f"{d.passwords_in_both} already in target")
    for s in d.samples.get("passwords", []):
        print(f"    +  {s}")
    print(f"Bookmarks:  +{d.bookmark_urls_only_in_source} new, "
          f"{d.bookmark_urls_in_both} already in target")
    for s in d.samples.get("bookmarks", []):
        print(f"    +  {s}")
    print(f"Extensions: +{d.extensions_only_in_source} new, "
          f"{d.extensions_in_both} already in target")
    for s in d.samples.get("extensions", []):
        print(f"    +  {s}")
    return 0


def _cmd_snapshot(args: argparse.Namespace) -> int:
    from foxport.snapshot import create_snapshot
    in_dir = Path(args.input_dir)
    out_path = Path(args.out)
    if not in_dir.is_dir():
        print(f"error: {in_dir} is not a directory", file=sys.stderr)
        return 2
    try:
        manifest = create_snapshot(
            in_dir, out_path,
            source_label=args.source_label,
            target_label=args.target_label,
            passphrase=args.passphrase or None,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Bundled {len(manifest.files)} file(s) into {out_path}")
    print(f"  Source: {manifest.source_label}")
    print(f"  Target: {manifest.target_label}")
    print(f"  Encrypted: {manifest.encrypted}")
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    from foxport.snapshot import restore_snapshot
    bundle = Path(args.snapshot)
    out_dir = Path(args.out_dir)
    if not bundle.is_file():
        print(f"error: {bundle} not found", file=sys.stderr)
        return 2
    try:
        manifest = restore_snapshot(
            bundle,
            out_dir,
            passphrase=args.passphrase or None,
            overwrite=args.overwrite,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Restored {len(manifest.files)} file(s) into {out_dir}")
    print(f"  Source: {manifest.source_label}")
    print(f"  Target: {manifest.target_label}")
    print(f"  Created: {manifest.created_iso}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "list":
        return _cmd_list(args)
    if args.command == "migrate":
        return _cmd_migrate(args)
    if args.command == "migrate-reverse":
        return _cmd_migrate_reverse(args)
    if args.command == "diff":
        return _cmd_diff(args)
    if args.command == "snapshot":
        return _cmd_snapshot(args)
    if args.command == "restore":
        return _cmd_restore(args)
    parser.error("no command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
