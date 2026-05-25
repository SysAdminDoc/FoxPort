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
from foxport.crash_reporting import (
    SENTRY_ENABLE_ENV,
    crash_reporting_env_enabled,
    crash_reporting_network_host,
    current_crash_reporting_status,
    initialize_crash_reporting,
)
from foxport.manifest import (
    RunManifest,
    build_artifact,
    now_iso,
    write_manifest,
)
from foxport.passkeys import inventory_profiles
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
from foxport.migrate.downloads import migrate_downloads
from foxport.migrate.extensions import migrate_extensions
from foxport.migrate.extension_settings import (
    migrate_extension_settings,
    parse_extension_settings_selection,
)
from foxport.migrate.history import migrate_history
from foxport.migrate.open_tabs import migrate_open_tabs
from foxport.migrate.passwords import migrate_passwords
from foxport.migrate.search_engines import migrate_search_engines
from foxport.migrate_reverse.bookmarks import migrate_bookmarks_reverse
from foxport.migrate_reverse.extensions import migrate_extensions_reverse
from foxport.migrate_reverse.passwords import migrate_passwords_reverse
from foxport.telemetry import (
    TELEMETRY_HOST,
    MigrationTelemetryPayload,
    record_migration,
)


ALL_ITEMS = (
    "passwords", "bookmarks", "extensions", "cookies", "history",
    "autofill", "cards", "search_engines", "open_tabs", "downloads",
)

REVERSE_ITEMS = ("passwords", "bookmarks", "extensions")


# Stable JSON schema versions per command. Bump additively — readers
# pin schema_version, so a new optional field is safe to add but a
# rename or removal is not. List used by the docs + tests so a stray
# bump shows up in CI.
_JSON_SCHEMA_VERSIONS = {
    "list": 1,
    "migrate": 1,
    "migrate-reverse": 1,
    "diff": 1,
    "snapshot": 1,
    "restore": 1,
    "import-bookmarks": 1,
    "restore-backup": 1,
    "passkeys-inventory": 1,
}


def _emit_json(payload: dict) -> None:
    """Print ``payload`` to stdout as JSON. Single shared shape:
    ``schema_version`` + ``foxport_version`` keys at the root, command-
    specific fields alongside. Never includes plaintext secrets — that's
    the caller's invariant (mirrored in ``test_cli_json_no_secrets`` for
    migrate, and the per-command schema snapshots).
    """

    import json as _json
    payload.setdefault("foxport_version", __version__)
    print(_json.dumps(payload, indent=2, default=str))


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
    chromium = detect_chromium()
    firefox = detect_firefox()
    if getattr(args, "json", False):
        # JSON output is the contract for IT/support automation. Schema is
        # versioned via "schema_version" so downstream parsers can refuse
        # an unknown shape rather than silently misinterpret it.
        import json as _json
        payload = {
            "schema_version": 1,
            "foxport_version": __version__,
            "chromium_sources": [
                {
                    "browser": p.browser,
                    "profile_name": p.profile_name,
                    "profile_dir": str(p.profile_dir),
                    "running": is_chromium_running(p),
                }
                for p in chromium
            ],
            "firefox_targets": [
                {
                    "browser": p.browser,
                    "profile_name": p.profile_name,
                    "profile_dir": str(p.profile_dir),
                    "is_default": p.is_default,
                    "locked": is_firefox_profile_locked(p),
                }
                for p in firefox
            ],
        }
        print(_json.dumps(payload, indent=2))
        return 0
    print(f"{__app_name__} v{__version__}")
    print("\nChromium sources:")
    if not chromium:
        print("  (none detected)")
    for p in chromium:
        marker = " [running]" if is_chromium_running(p) else ""
        print(f"  {p.browser}/{p.profile_name}{marker}")
        print(f"    {p.profile_dir}")
        if getattr(args, "detail", False):
            for label, count in _profile_detail_counts(p):
                print(f"      {label}: {count}")
    print("\nFirefox targets:")
    if not firefox:
        print("  (none detected)")
    for p in firefox:
        default = " [default]" if p.is_default else ""
        locked = " [locked]" if is_firefox_profile_locked(p) else ""
        print(f"  {p.browser}/{p.profile_name}{default}{locked}")
        print(f"    {p.profile_dir}")
    return 0


def _profile_detail_counts(profile: ChromiumProfile) -> list[tuple[str, int]]:
    """Cheap per-category counts that don't require decryption.

    Used by ``list --detail`` so support workflows can see "this profile
    has 1,245 logins / 8,901 history visits" without doing a real
    migration. SQLite reads run against a temp copy via the same helper
    the Preview page uses; any error returns 0 silently.
    """

    from foxport.gui.pages import _safe_sqlite_count
    counts: list[tuple[str, int]] = []
    login_data = profile.profile_dir / "Login Data"
    if login_data.is_file():
        rows = _safe_sqlite_count(login_data, ("SELECT COUNT(*) FROM logins",))
        if rows:
            counts.append(("logins", rows[0]))
    history_db = profile.profile_dir / "History"
    if history_db.is_file():
        rows = _safe_sqlite_count(
            history_db,
            ("SELECT COUNT(*) FROM urls", "SELECT COUNT(*) FROM downloads"),
        )
        if rows:
            counts.append(("urls", rows[0]))
            counts.append(("downloads", rows[1] if len(rows) > 1 else 0))
    web_data = profile.profile_dir / "Web Data"
    if web_data.is_file():
        rows = _safe_sqlite_count(web_data, (
            "SELECT COUNT(*) FROM autofill WHERE name <> '' AND value <> ''",
            "SELECT COUNT(*) FROM credit_cards",
            "SELECT COUNT(*) FROM keywords WHERE keyword IS NOT NULL AND keyword <> ''",
        ))
        if rows and len(rows) >= 3:
            counts.append(("autofill", rows[0]))
            counts.append(("cards", rows[1]))
            counts.append(("search_engines", rows[2]))
    cookies_db = profile.profile_dir / "Network" / "Cookies"
    if not cookies_db.is_file():
        cookies_db = profile.profile_dir / "Cookies"
    if cookies_db.is_file():
        rows = _safe_sqlite_count(cookies_db, ("SELECT COUNT(*) FROM cookies",))
        if rows:
            counts.append(("cookies", rows[0]))
    return counts


def _cmd_migrate(args: argparse.Namespace) -> int:
    # --json mode silences all per-category text output so callers can
    # pipe stdout straight into a JSON parser. Errors still go to
    # stderr (text), preserving the typical "stdout is the contract,
    # stderr is the chatter" CLI shape.
    json_mode = getattr(args, "json", False)

    def _log(msg: str) -> None:
        if not json_mode:
            print(msg)

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
    try:
        extension_settings = parse_extension_settings_selection(
            getattr(args, "extension_settings", None)
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if extension_settings:
        items.add("extensions")
    out_root = Path(args.out) if args.out else Path.home() / "Documents" / "FoxPort"
    target_label = target.label if target else "firefox"
    if args.dry_run:
        target_label += "_dryrun"
    out_dir = make_export_dir(out_root, source.label, target_label)
    _log(f"Source: {source.label}")
    _log(f"Target: {target.label if target else '(none - files only)'}")
    _log(f"Items:  {', '.join(sorted(items))}")
    _log(f"Output: {out_dir}")
    if args.dry_run:
        _log("Mode:   DRY RUN")

    already_installed: set[str] = set()
    if target and not args.dry_run:
        already_installed = read_installed_firefox_extensions(target)

    exports: dict[str, Path] = {}
    # Per-category counts surfaced in the --json payload so callers
    # don't have to parse the human-readable lines. Stays an empty dict
    # in text mode (zero overhead).
    json_counts: dict[str, int] = {}
    hibp_status_for_network = "enabled" if args.hibp else "disabled"

    if "passwords" in items:
        _log("\n[passwords]")
        try:
            r = migrate_passwords(source, out_dir, dry_run=args.dry_run, hibp_scan=args.hibp)
        except DecryptionError as exc:
            _log(f"  FAILED: {exc}")
        else:
            _log(f"  {r.decrypted} decrypted, {r.skipped_empty} empty, "
                 f"{r.failed} failed of {r.total} total")
            json_counts["passwords"] = r.decrypted
            if args.hibp:
                _log(f"  HIBP: {r.hibp_hits} compromised passwords"
                     + (f" - see {r.hibp_report_path.name}" if r.hibp_report_path else ""))
                if r.hibp_report_path and not args.dry_run:
                    exports["hibp"] = r.hibp_report_path
                json_counts["hibp"] = r.hibp_hits
                hibp_status_for_network = getattr(r, "hibp_status", "enabled")
            if not args.dry_run:
                exports["passwords"] = r.csv_path

    if "bookmarks" in items:
        _log("\n[bookmarks]")
        r = migrate_bookmarks(source, out_dir, dry_run=args.dry_run)
        _log(f"  {r.urls} URLs across {r.folders} folders")
        json_counts["bookmarks"] = r.urls
        if not args.dry_run:
            exports["bookmarks"] = r.html_path

    if "extensions" in items:
        _log("\n[extensions]")
        r = migrate_extensions(
            source, out_dir,
            online=not args.no_online,
            already_installed_guids=already_installed,
            dry_run=args.dry_run,
        )
        _log(f"  {r.matched} matched ({r.already_installed} already installed), "
             f"{r.unmatched} unmatched of {len(r.matches)} installed")
        for warning in r.warnings:
            _log(f"  ⚠ {warning}")
        json_counts["extensions"] = len(r.matches)
        if not args.dry_run:
            exports["extensions"] = r.html_path
        if extension_settings:
            selected = ", ".join(sorted(extension_settings))
            _log(f"  Exporting allowlisted extension settings ({selected})")
            sr = migrate_extension_settings(
                source,
                out_dir,
                selected=extension_settings,
                dry_run=args.dry_run,
            )
            json_counts["extension_settings"] = sr.count
            if not args.dry_run and sr.json_path.exists():
                exports["extension_settings"] = sr.json_path
            if sr.exported:
                _log("  Settings exported for: " + ", ".join(i.label for i in sr.exported))
            for line in sr.skipped[:5]:
                _log(f"    - {line}")
            for line in sr.failures[:5]:
                _log(f"    ! {line}")

    if "cookies" in items:
        _log("\n[cookies]")
        try:
            r = migrate_cookies(source, out_dir, dry_run=args.dry_run)
        except DecryptionError as exc:
            _log(f"  FAILED: {exc}")
        else:
            _log(f"  {r.decrypted} decrypted, {r.failed} failed of {r.total} total")
            json_counts["cookies"] = r.decrypted
            if not args.dry_run:
                exports["cookies"] = r.sqlite_path

    if "history" in items:
        _log("\n[history]")
        r = migrate_history(source, out_dir, dry_run=args.dry_run)
        _log(f"  {r.urls} URLs / {r.visits} visits ({len(r.failures)} failed)")
        json_counts["history"] = r.visits
        if not args.dry_run:
            exports["history"] = r.sqlite_path

    if "autofill" in items:
        _log("\n[autofill]")
        r = migrate_autofill(source, out_dir, dry_run=args.dry_run)
        _log(f"  {r.written} field/value pairs ({r.skipped} skipped, {len(r.failures)} failed)")
        json_counts["autofill"] = r.written
        if not args.dry_run:
            exports["autofill"] = r.sqlite_path

    if "cards" in items:
        _log("\n[cards]")
        try:
            r = migrate_cards(source, out_dir, dry_run=args.dry_run)
        except DecryptionError as exc:
            _log(f"  FAILED: {exc}")
        else:
            _log(f"  {r.decrypted} decrypted, {r.failed} failed of {r.total} total")
            json_counts["cards"] = r.decrypted
            if not args.dry_run and r.decrypted > 0:
                exports["cards"] = r.csv_path

    if "search_engines" in items:
        _log("\n[search_engines]")
        r = migrate_search_engines(source, out_dir, dry_run=args.dry_run)
        _log(f"  {r.written} OpenSearch XML files written ({r.total} total entries)")
        json_counts["search_engines"] = r.total
        if not args.dry_run:
            exports["search_engines"] = r.json_path

    if "open_tabs" in items:
        _log("\n[open_tabs]")
        r = migrate_open_tabs(source, out_dir, dry_run=args.dry_run)
        _log(f"  {r.tabs} URL(s) recovered ({len(r.failures)} failure(s))")
        json_counts["open_tabs"] = r.tabs
        if not args.dry_run and r.tabs > 0:
            exports["open_tabs"] = r.out_path

    if "downloads" in items:
        _log("\n[downloads]")
        r = migrate_downloads(source, out_dir, dry_run=args.dry_run)
        _log(f"  {r.written} of {r.total} download(s) exported")
        json_counts["downloads"] = r.written
        if not args.dry_run and r.written > 0:
            exports["downloads"] = r.csv_path

    telemetry_status = _record_cli_telemetry(
        enabled=getattr(args, "telemetry", False),
        direction="forward",
        outcome="dry_run" if args.dry_run else "completed",
        dry_run=bool(args.dry_run),
        items=sorted(items),
        counts=json_counts,
        direct_write=False,
    )
    if getattr(args, "telemetry", False):
        _log(_telemetry_status_line(telemetry_status))

    network = {
        "addons.mozilla.org": "disabled" if args.no_online else "enabled",
        "api.pwnedpasswords.com": hibp_status_for_network,
        TELEMETRY_HOST: telemetry_status,
        crash_reporting_network_host(): current_crash_reporting_status(
            _crash_reporting_requested(args)
        ),
    }

    manifest_path: Path | None = None
    if exports:
        instructions_path = out_dir / "README.txt"
        instructions_path.write_text(
            import_instructions(target, exports), encoding="utf-8"
        )
        _log(f"\nInstructions: {instructions_path}")
        manifest_path = _write_cli_manifest(
            out_dir=out_dir,
            source_label=source.label,
            target_label=target.label if target else "",
            direction="forward",
            dry_run=args.dry_run,
            items=sorted(items),
            exports=exports,
            network=network,
            privacy_redact=getattr(args, "privacy_redact", False),
        )
        _log(f"Manifest:     {manifest_path}")
    if json_mode:
        # Mirror the on-disk manifest into stdout — same shape as
        # `RunManifest`, plus an `out_dir` pointer so callers can find
        # the artifacts. Never includes plaintext (manifest layer
        # already enforces that — see foxport/manifest.py).
        payload = {
            "schema_version": _JSON_SCHEMA_VERSIONS["migrate"],
            "command": "migrate",
            "out_dir": str(out_dir),
            "source": source.label,
            "target": target.label if target else "",
            "direction": "forward",
            "dry_run": bool(args.dry_run),
            "items_requested": sorted(items),
            "counts": json_counts,
            "exports": {k: str(v) for k, v in exports.items()},
            "manifest_path": str(manifest_path) if manifest_path else "",
            "network": network,
            "telemetry": {"status": telemetry_status},
        }
        _emit_json(payload)
    return 0


def _write_cli_manifest(
    *,
    out_dir: Path,
    source_label: str,
    target_label: str,
    direction: str,
    dry_run: bool,
    items: list[str],
    exports: dict[str, Path],
    network: dict[str, str],
    privacy_redact: bool = False,
) -> Path:
    """CLI-side helper that mirrors the worker's manifest emission.

    Lives next to README.txt; consumed by the snapshot bundler, the
    ``--json`` CLI, and support diagnostics. When ``privacy_redact`` is
    set, the on-disk manifest's backup_path / label fields have the
    current user's home-dir prefix scrubbed (see
    :func:`foxport.manifest.redact_manifest`).
    """

    artifacts = []
    for key, path in exports.items():
        try:
            artifacts.append(build_artifact(key, Path(path), out_dir))
        except (OSError, ValueError):
            continue
    manifest = RunManifest(
        created_iso=now_iso(),
        source_label=source_label,
        target_label=target_label,
        direction=direction,
        dry_run=dry_run,
        items_requested=items,
        network=network,
        artifacts=artifacts,
    )
    return write_manifest(manifest, out_dir, privacy_redact=privacy_redact)


def _record_cli_telemetry(
    *,
    enabled: bool,
    direction: str,
    outcome: str,
    dry_run: bool,
    items: list[str],
    counts: dict[str, int],
    direct_write: bool,
) -> str:
    result = record_migration(
        MigrationTelemetryPayload(
            direction=direction,
            surface="cli",
            outcome=outcome,
            dry_run=dry_run,
            direct_write=direct_write,
            items=items,
            counts=counts,
        ),
        enabled=enabled,
    )
    return result.status


def _telemetry_status_line(status: str) -> str:
    if status == "submitted":
        return "\nTelemetry: submitted aggregate migration metrics."
    if status == "unavailable":
        return "\nTelemetry: Glean SDK unavailable; migration metrics were not sent."
    if status == "failed":
        return "\nTelemetry: failed to submit migration metrics."
    return "\nTelemetry: disabled."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="foxport",
        description=f"{__app_name__} v{__version__} - Chromium to Firefox migration",
    )
    parser.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")
    parser.add_argument("--crash-reporting", action="store_true",
                        help=f"Opt in to path-stripped Sentry crash reporting for this "
                             f"CLI invocation. Requires FOXPORT_SENTRY_DSN or SENTRY_DSN; "
                             f"{SENTRY_ENABLE_ENV}=1 also enables this without the flag.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list", help="List detected source and target profiles")
    list_p.add_argument("--detail", action="store_true",
                         help="Also print cheap per-category counts (logins, history, autofill, ...) "
                              "for every Chromium source. No decryption runs.")
    list_p.add_argument("--json", action="store_true",
                         help="Emit a schema-versioned machine-readable JSON payload instead of text")

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
    mig.add_argument("--extension-settings", default=None,
                     help="Opt-in allowlisted extension settings export. Comma-separated "
                          "keys: ublock,stylus,bitwarden, or all. Emits "
                          "extension-settings.json when supported settings are found.")
    mig.add_argument("--hibp", action="store_true",
                     help="Check decrypted passwords against haveibeenpwned.com (k-anonymity API)")
    mig.add_argument("--json", action="store_true",
                     help="Suppress per-category text output and emit a schema-versioned "
                          "JSON payload on stdout instead (same shape as the on-disk "
                          "manifest.json plus an out_dir pointer). Errors still print to stderr.")
    mig.add_argument("--privacy-redact", action="store_true",
                     help="Strip the current user's home-dir prefix (e.g. C:/Users/<name>) "
                          "from backup_path / labels in the on-disk manifest.json. "
                          "Use this when uploading the manifest for support so the "
                          "username doesn't leak. Backups themselves stay where they are.")
    mig.add_argument("--telemetry", action="store_true",
                     help="Opt in to Glean migration telemetry for this run. Sends only "
                          "aggregate item counts, selected item slugs, direction, "
                          "dry-run/direct-write flags, and outcome; never paths, "
                          "profile labels, URLs, usernames, or secrets.")
    mig.add_argument("--direct-write-policy", default="apply",
                     choices=("apply", "skip", "backup-only"),
                     help="Per-category direct-write disposition applied to every "
                          "enabled direct_write_* category: 'apply' (v1.3 default - "
                          "merge passwords / replace cookies+history+open-tabs after "
                          "backup), 'skip' (don't touch the target; staging only), "
                          "or 'backup-only' (copy target file aside but don't write).")
    mig.add_argument("--yes", action="store_true",
                     help="Non-interactive mode: skip any future confirmation prompts "
                          "for destructive direct-write paths. The CLI doesn't prompt "
                          "today; this flag reserves the contract so a future addition "
                          "doesn't surprise existing scripts.")

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
    snap.add_argument("--json", action="store_true",
                     help="Emit a schema-versioned JSON payload instead of human text")

    restore = sub.add_parser("restore",
                              help="Unpack a .fxport bundle back into a folder")
    restore.add_argument("--snapshot", required=True, help="Path to the .fxport file")
    restore.add_argument("--out-dir", required=True, help="Folder to write the unpacked artifacts to")
    restore.add_argument("--passphrase", default="",
                         help="Passphrase for encrypted bundles (omit for plain ones)")
    restore.add_argument("--overwrite", action="store_true",
                         help="Allow restore into a non-empty output directory")
    restore.add_argument("--json", action="store_true",
                         help="Emit a schema-versioned JSON payload instead of human text")

    diff = sub.add_parser("diff",
                           help="Show what's in the source that the target doesn't have yet")
    diff.add_argument("--source", required=True, help="Chromium source profile")
    diff.add_argument("--target", required=True, help="Firefox target profile")
    diff.add_argument("--master-password", default="",
                       help="Master password for the target Firefox profile, if set")
    diff.add_argument("--json", action="store_true",
                       help="Emit a schema-versioned JSON payload instead of human text")

    imp = sub.add_parser("import-bookmarks",
                          help="Convert a Pocket / Pinboard / OPML / Netscape bookmark export to Firefox-importable HTML")
    imp.add_argument("--input", required=True,
                     help="Path to the source bookmark file (auto-detected by content)")
    imp.add_argument("--out", default=None,
                     help="Path to write the Firefox-importable HTML "
                          "(default: <input>.firefox.html alongside the input)")
    imp.add_argument("--format", default="auto",
                     choices=("auto", "pocket", "pinboard", "opml", "netscape"),
                     help="Force a specific input format if auto-detection misclassifies the file")
    imp.add_argument("--json", action="store_true",
                     help="Emit a schema-versioned JSON payload instead of human text")

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
    rev.add_argument("--json", action="store_true",
                     help="Emit a schema-versioned JSON payload instead of human text")
    rev.add_argument("--privacy-redact", action="store_true",
                     help="Strip user-dir prefixes from manifest backup_path / labels")
    rev.add_argument("--telemetry", action="store_true",
                     help="Opt in to Glean migration telemetry for this reverse run "
                          "(aggregate counts and run flags only)")

    rbk = sub.add_parser("restore-backup",
                         help="Restore a *.foxport-backup-<mtime>.* file over its original target "
                              "(regret-undo for a direct-write run)")
    rbk.add_argument("--backup", required=True,
                     help="Path to the timestamped backup produced by a direct-write run")
    rbk.add_argument("--target", default=None,
                     help="Optional explicit target path; defaults to the backup's "
                          "resolved original (e.g. logins.foxport-backup-1.json -> logins.json)")
    rbk.add_argument("--yes", action="store_true",
                     help="Skip the confirmation prompt (the CLI doesn't prompt today; "
                          "flag reserved for future interactive use)")
    rbk.add_argument("--json", action="store_true",
                     help="Emit a schema-versioned JSON payload instead of human text")

    passkeys = sub.add_parser("passkeys", help="Passkey/WebAuthn helper commands")
    passkeys_sub = passkeys.add_subparsers(dest="passkeys_command", required=True)
    inv = passkeys_sub.add_parser(
        "inventory",
        help="Count known/likely local passkey stores without exporting credentials",
    )
    inv.add_argument("--json", action="store_true",
                     help="Emit schema-versioned JSON instead of text")
    return parser


def _cmd_migrate_reverse(args: argparse.Namespace) -> int:
    json_mode = getattr(args, "json", False)

    def _log(msg: str) -> None:
        if not json_mode:
            print(msg)

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
    _log(f"Source: {source.label}")
    _log(f"Items:  {', '.join(sorted(items))}")
    _log(f"Output: {out_dir}")
    exports: dict[str, Path] = {}
    json_counts: dict[str, int] = {}

    if "passwords" in items:
        _log("\n[passwords]")
        r = migrate_passwords_reverse(source, out_dir,
                                       master_password=args.master_password,
                                       dry_run=args.dry_run)
        _log(f"  {r.written} written, {len(r.failures)} failed of {r.total} total")
        json_counts["passwords"] = r.written
        if not args.dry_run and r.written > 0:
            exports["passwords"] = r.csv_path
    if "bookmarks" in items:
        _log("\n[bookmarks]")
        r = migrate_bookmarks_reverse(source, out_dir, dry_run=args.dry_run)
        _log(f"  {r.urls} URLs across {r.folders} folders")
        json_counts["bookmarks"] = r.urls
        if not args.dry_run and r.urls > 0:
            exports["bookmarks"] = r.html_path
    if "extensions" in items:
        _log("\n[extensions]")
        r = migrate_extensions_reverse(source, out_dir, dry_run=args.dry_run)
        _log(f"  {r.matched} matched, {r.unmatched} unmatched of {len(r.matches)} installed")
        json_counts["extensions"] = len(r.matches)
        if not args.dry_run and r.matches:
            exports["extensions"] = r.html_path
    telemetry_status = _record_cli_telemetry(
        enabled=getattr(args, "telemetry", False),
        direction="reverse",
        outcome="dry_run" if args.dry_run else "completed",
        dry_run=bool(args.dry_run),
        items=sorted(items),
        counts=json_counts,
        direct_write=False,
    )
    if getattr(args, "telemetry", False):
        _log(_telemetry_status_line(telemetry_status))

    network = {
        "addons.mozilla.org": "disabled",
        "api.pwnedpasswords.com": "disabled",
        TELEMETRY_HOST: telemetry_status,
        crash_reporting_network_host(): current_crash_reporting_status(
            _crash_reporting_requested(args)
        ),
    }

    manifest_path: Path | None = None
    if exports:
        instructions_path = out_dir / "README.txt"
        instructions_path.write_text(
            import_instructions(None, exports), encoding="utf-8"
        )
        _log(f"\nInstructions: {instructions_path}")
        manifest_path = _write_cli_manifest(
            out_dir=out_dir,
            source_label=source.label,
            target_label="",
            direction="reverse",
            dry_run=args.dry_run,
            items=sorted(items),
            exports=exports,
            network=network,
            privacy_redact=getattr(args, "privacy_redact", False),
        )
        _log(f"Manifest:     {manifest_path}")
    if json_mode:
        _emit_json({
            "schema_version": _JSON_SCHEMA_VERSIONS["migrate-reverse"],
            "command": "migrate-reverse",
            "out_dir": str(out_dir),
            "source": source.label,
            "direction": "reverse",
            "dry_run": bool(args.dry_run),
            "items_requested": sorted(items),
            "counts": json_counts,
            "exports": {k: str(v) for k, v in exports.items()},
            "manifest_path": str(manifest_path) if manifest_path else "",
            "network": network,
            "telemetry": {"status": telemetry_status},
        })
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    json_mode = getattr(args, "json", False)
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
    if json_mode:
        _emit_json({
            "schema_version": _JSON_SCHEMA_VERSIONS["diff"],
            "command": "diff",
            "source": source.label,
            "target": target.label,
            "passwords": {
                "only_in_source": d.passwords_only_in_source,
                "in_both": d.passwords_in_both,
                # Sample URL + username only — never any plaintext.
                "samples": d.samples.get("passwords", []),
            },
            "bookmarks": {
                "only_in_source": d.bookmark_urls_only_in_source,
                "in_both": d.bookmark_urls_in_both,
                "samples": d.samples.get("bookmarks", []),
            },
            "extensions": {
                "only_in_source": d.extensions_only_in_source,
                "in_both": d.extensions_in_both,
                "samples": d.samples.get("extensions", []),
            },
        })
        return 0
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
    json_mode = getattr(args, "json", False)
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
    if json_mode:
        _emit_json({
            "schema_version": _JSON_SCHEMA_VERSIONS["snapshot"],
            "command": "snapshot",
            "out_path": str(out_path),
            "source": manifest.source_label,
            "target": manifest.target_label,
            "encrypted": manifest.encrypted,
            "created_iso": manifest.created_iso,
            "files_count": len(manifest.files),
        })
        return 0
    print(f"Bundled {len(manifest.files)} file(s) into {out_path}")
    print(f"  Source: {manifest.source_label}")
    print(f"  Target: {manifest.target_label}")
    print(f"  Encrypted: {manifest.encrypted}")
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    from foxport.snapshot import restore_snapshot
    json_mode = getattr(args, "json", False)
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
    if json_mode:
        _emit_json({
            "schema_version": _JSON_SCHEMA_VERSIONS["restore"],
            "command": "restore",
            "out_dir": str(out_dir),
            "bundle": str(bundle),
            "source": manifest.source_label,
            "target": manifest.target_label,
            "encrypted": manifest.encrypted,
            "created_iso": manifest.created_iso,
            "files_count": len(manifest.files),
            "overwrite": bool(args.overwrite),
        })
        return 0
    print(f"Restored {len(manifest.files)} file(s) into {out_dir}")
    print(f"  Source: {manifest.source_label}")
    print(f"  Target: {manifest.target_label}")
    print(f"  Created: {manifest.created_iso}")
    return 0


def _cmd_import_bookmarks(args: argparse.Namespace) -> int:
    """Convert an external bookmark export to Firefox-importable HTML.

    Auto-detects the input format from content. Power users can force one
    via ``--format`` if the heuristic misclassifies the file (e.g. a
    custom Pinboard export with non-standard keys).
    """

    from foxport.import_.adapters import (
        BookmarkImport,
        detect_format,
        parse_file,
        parse_netscape_html,
        parse_opml,
        parse_pinboard_json,
        parse_pocket_json,
        write_netscape_html,
    )

    in_path = Path(args.input)
    if not in_path.is_file():
        print(f"error: {in_path} is not a file", file=sys.stderr)
        return 2

    fmt = args.format
    if fmt == "auto":
        fmt, entries = parse_file(in_path)
        if fmt == "unknown":
            print(
                f"error: could not auto-detect bookmark format for {in_path}.\n"
                "Try --format pocket|pinboard|opml|netscape.",
                file=sys.stderr,
            )
            return 2
    else:
        parser_for = {
            "pocket": parse_pocket_json,
            "pinboard": parse_pinboard_json,
            "opml": parse_opml,
            "netscape": parse_netscape_html,
        }[fmt]
        entries = parser_for(in_path)

    if not entries:
        print(f"error: parsed 0 bookmarks from {in_path}", file=sys.stderr)
        return 2

    out_path = Path(args.out) if args.out else in_path.with_suffix(in_path.suffix + ".firefox.html")
    write_netscape_html(entries, out_path)
    if getattr(args, "json", False):
        _emit_json({
            "schema_version": _JSON_SCHEMA_VERSIONS["import-bookmarks"],
            "command": "import-bookmarks",
            "input_path": str(in_path),
            "input_format": fmt,
            "parsed_count": len(entries),
            "out_path": str(out_path),
        })
        return 0
    print(f"Detected format: {fmt}")
    print(f"Parsed:  {len(entries)} bookmark(s)")
    print(f"Wrote:   {out_path}")
    print("Import:  Open Firefox Library (Ctrl+Shift+O) -> Import and Backup ->")
    print("         Import Bookmarks from HTML, then pick the file above.")
    return 0


def _cmd_restore_backup(args: argparse.Namespace) -> int:
    """Regret-undo a direct-write run.

    Copies the named ``*.foxport-backup-<mtime>.*`` file over its
    original target via the same atomic-replace helper a real
    direct-write step uses. Resolves the target automatically from
    the backup name when ``--target`` isn't given.
    """

    from foxport.fileops import original_from_backup, restore_from_backup

    json_mode = getattr(args, "json", False)
    backup = Path(args.backup)
    if not backup.is_file():
        print(f"error: backup file not found: {backup}", file=sys.stderr)
        return 2

    explicit_target = Path(args.target) if args.target else None
    resolved_target = explicit_target or original_from_backup(backup)
    if resolved_target is None:
        print(
            f"error: {backup.name} does not match the foxport-backup naming "
            "convention; pass --target to point at the file to overwrite.",
            file=sys.stderr,
        )
        return 2

    try:
        restored = restore_from_backup(backup, target_path=resolved_target)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # Permission denied / target dir gone / disk full mid-copy.
        print(f"error: could not restore: {exc}", file=sys.stderr)
        return 1

    if json_mode:
        _emit_json({
            "schema_version": _JSON_SCHEMA_VERSIONS["restore-backup"],
            "command": "restore-backup",
            "backup": str(backup),
            "target": str(restored),
            "explicit_target": explicit_target is not None,
        })
        return 0
    print(f"Restored {backup.name} -> {restored}")
    if explicit_target is None:
        print("(target was resolved automatically from the backup name; "
              "pass --target to override)")
    return 0


def _cmd_passkeys_inventory(args: argparse.Namespace) -> int:
    chromium = detect_chromium()
    firefox = detect_firefox()
    profiles = inventory_profiles(chromium, firefox)
    total = sum(profile.count for profile in profiles)
    with_passkeys = sum(1 for profile in profiles if profile.count > 0)
    if getattr(args, "json", False):
        _emit_json({
            "schema_version": _JSON_SCHEMA_VERSIONS["passkeys-inventory"],
            "command": "passkeys inventory",
            "totals": {
                "profiles": len(profiles),
                "profiles_with_passkeys": with_passkeys,
                "known_or_possible_passkeys": total,
            },
            "profiles": [profile.to_json() for profile in profiles],
            "export_supported": False,
        })
        return 0

    print("Passkey inventory (presence/count only; no export)")
    print(f"Profiles scanned: {len(profiles)}")
    print(f"Profiles with known/possible passkeys: {with_passkeys}")
    print(f"Known/possible passkey rows or markers: {total}")
    for profile in profiles:
        label = f"{profile.browser}/{profile.profile_name}"
        marker = f"{profile.count}" if profile.count else "none found"
        print(f"\n{label} ({profile.family}): {marker}")
        for store in profile.stores:
            print(f"  - {store.store}: {store.count} ({store.confidence})")
        for note in profile.notes[:2]:
            print(f"    note: {note}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    crash_status = initialize_crash_reporting(enabled=_crash_reporting_requested(args))
    if getattr(args, "crash_reporting", False) and crash_status.status not in {"initialized", "disabled"}:
        print(f"warning: crash reporting {crash_status.status}: {crash_status.message}", file=sys.stderr)
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
    if args.command == "import-bookmarks":
        return _cmd_import_bookmarks(args)
    if args.command == "restore-backup":
        return _cmd_restore_backup(args)
    if args.command == "passkeys":
        if args.passkeys_command == "inventory":
            return _cmd_passkeys_inventory(args)
    parser.error("no command")
    return 2


def _crash_reporting_requested(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "crash_reporting", False) or crash_reporting_env_enabled())


if __name__ == "__main__":
    raise SystemExit(main())
