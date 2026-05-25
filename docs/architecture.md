# FoxPort Architecture

A one-page tour of how the codebase fits together. Skip the README if you
already know what FoxPort *does*; this file is about how it does it.

## Layers

```
foxport/
├── app.py / __main__.py        # entry points — wire QApplication + MainWindow
├── cli.py                      # argparse front-end (list/migrate/migrate-reverse/
│                               #   diff/snapshot/restore/import-bookmarks).
│                               #   Every action subcommand supports `--json`.
├── config.py                   # persistent Settings (JSON in %APPDATA%/FoxPort etc.)
├── diff.py                     # `diff` subcommand engine
├── fileops.py                  # atomic file helpers — write_bytes_atomic,
│                               #   write_text_atomic, replace_file_atomic,
│                               #   timestamped_backup_path
├── manifest.py                 # per-run manifest.json (RunManifest + RunArtifact +
│                               #   build_artifact + write_manifest + load_manifest).
│                               #   Sensitivity labels + action_kind defaults per key.
├── snapshot.py                 # .fxport bundle create/restore + AES-256-GCM with
│                               #   InvalidTag → friendly ValueError translation
├── telemetry.py                # opt-in Glean wrapper; aggregate run metrics only
├── crash_reporting.py          # opt-in Sentry wrapper; path-stripped events only
│
├── browsers/                   # Detection + read paths
│   ├── detect.py               # per-platform _CHROMIUM_SPECS + _FIREFOX_PROFILES_ROOT
│   ├── chromium.py             # SQLite copy-to-temp reads; is_browser_internal_url filter
│   ├── firefox.py              # output dir creation + import_instructions text
│   └── firefox_read.py         # reverse direction reads (places.sqlite, logins.json via NSS)
│
├── crypto/                     # Master-key recovery + helpers
│   ├── dpapi.py                # Windows DPAPI + AES-GCM (decrypt_value + decrypt_value_bytes).
│   │                           #   decrypt_value_bytes returns raw plaintext so cookies can
│   │                           #   strip the Chrome 130+ SHA-256 host_key prefix in bytes-
│   │                           #   space before UTF-8 decoding.
│   ├── keychain.py             # macOS Keychain + Linux libsecret/kwallet + AES-128-CBC
│   │                           #   (decrypt_value_v10 + decrypt_value_v10_bytes)
│   ├── nss.py                  # ctypes wrapper around Firefox's nss3 with
│   │                           #   NSS_GetVersion() probe + version-skew refusal
│   ├── abe.py                  # App-Bound Encryption sidecar launcher
│   ├── mozhash.py              # Mozilla mfbt::HashString port (used by places url_hash)
│   └── hibp.py                 # Have-I-Been-Pwned k-anonymity client with HibpScanResult
│                               #   tri-state (checked-clean / checked-hits / network-error
│                               #   / disabled)
│
├── migrate/                    # Forward (Chromium → Firefox) emitters
│   ├── passwords.py            # Firefox CSV; PasswordResult carries hibp_status tri-state
│   ├── bookmarks.py            # Netscape HTML
│   ├── extensions.py           # 4-stage AMO matcher → install-page HTML; User-Agent
│   │                           #   tracks __version__
│   ├── extension_settings.py   # opt-in allowlisted uBO/Stylus/Bitwarden settings
│   ├── cookies.py              # writes cookies.sqlite (v17) from scratch; Chrome 130+
│   │                           #   HOST_KEY prefix stripped in bytes-space
│   ├── history.py              # writes places.sqlite (v86) from scratch; can add
│   │                           #   download moz_annos when history direct-write applies
│   ├── autofill.py             # writes formhistory.sqlite (v5) from scratch
│   ├── cards.py                # saved-cards.csv (Firefox has no native card store)
│   ├── search_engines.py       # OpenSearch XML per engine
│   ├── open_tabs.py            # SNSS Pickle parser → recovery.jsonlz4; direct-write
│   │                           #   returns OpenTabsDirectWriteResult(target, backup)
│   ├── downloads.py            # downloads.csv reference artifact
│   ├── conflicts.py            # NON-mutating pre-flight analyzers for the four
│   │                           #   direct-write categories (passwords/cookies/history/
│   │                           #   open_tabs). Counts source vs. target rows so the
│   │                           #   worker can log "N of M already in target" before
│   │                           #   mutation. GUID compare is case-insensitive.
│   ├── nss_passwords.py        # direct-write into target logins.json via NSS
│   ├── nss_cookies.py          # direct-write target cookies.sqlite
│   └── nss_history.py          # direct-write target places.sqlite
│
├── migrate_reverse/            # Reverse (Firefox → Chromium) emitters
│   ├── passwords.py            # Chrome import CSV
│   ├── bookmarks.py            # Netscape HTML with Bookmarks-Bar promotion
│   └── extensions.py           # inverted curated + AMO_GUID_TO_CHROME → CWS links
│
├── import_/                    # External bookmark sources (Pinboard/Pocket/OPML/Netscape)
│   └── adapters.py             # detect_format + parse_file + write_netscape_html
│
├── data/
│   ├── curated_extension_map.json   # 56 Chrome ID → AMO slug pairs across 14 categories;
│   │                                #   _meta.entry_count asserted by the auditor
│   ├── glean_metrics.yaml           # declared Glean metrics for opt-in telemetry
│   └── glean_pings.yaml             # custom migration ping declaration
│
└── gui/                        # PyQt6 wizard
    ├── main_window.py          # 5-step QStackedWidget shell; first-run trust dialog
    │                           #   gated by Settings.first_run_acked_iso
    ├── pages.py                # Source / Target / Items / Preview / Run pages.
    │                           #   RunPage.ARTIFACT_ACTIONS drives the Done-screen
    │                           #   button bar (per-artifact Open/Reveal + per-
    │                           #   direct-write Reveal-backup + Save-as-snapshot)
    ├── widgets.py              # StepRail, Tile (keyboard-focusable), Banner, FooterBar
    ├── workers.py              # QThread workers — DetectWorker, MigrationWorker.
    │                           #   MigrationWorker emits directWriteBackups before
    │                           #   finished so the Done page renders Reveal-backup
    │                           #   buttons in lockstep with set_done.
    ├── dialogs.py              # Settings, password preview, bookmark filter, history
    │                           #   filter, FirstRunDialog (trust + AMO/HIBP defaults),
    │                           #   RestoreInspectDialog (reads inner per-run manifest
    │                           #   and labels artifact sensitivity)
    └── theme.py                # Catppuccin Mocha QSS
```

## Data flow — forward migration

1. `MainWindow` launches → `DetectWorker` runs `detect_chromium()` +
   `detect_firefox()` on a background thread. On the very first launch
   (`Settings.first_run_acked_iso` empty), the `FirstRunDialog` opens
   on a 0-ms timer so it lands above the main window.
2. User picks tiles on `SourcePage` + `TargetPage`; selections land in
   `MigrationContext`.
3. `ItemsPage` exposes the 10 category checkboxes + Customize…
   dialogs + direct-write toggles + HIBP toggle.
4. `PreviewPage` reads the source profile to compute per-category counts
   (`ctx.counts: dict[str, int]`) and renders the
   network-activity sub-tree (AMO + HIBP + telemetry + crash reporting
   ENABLED / disabled).
5. User clicks Run → `MainWindow._start_migration` builds a
   `MigrationRequest`, kicks off `MigrationWorker` on a QThread.
6. For each direct-write category, the worker calls
   `foxport/migrate/conflicts.analyze_<thing>(source, target)` BEFORE
   mutation and logs "N of M already in target".
7. `MigrationWorker.run` walks the checked categories. Each calls into
   `foxport/migrate/<category>.py:migrate_<category>` with `out_dir` +
   per-category options.
8. Each migrator opens its source file via `_copy_for_read` (copies to
   temp so the source profile stays untouched even while the browser
   runs), processes, writes its artifact to `out_dir` through
   `foxport.fileops.write_text_atomic` / `write_bytes_atomic` so a
   torn write can't leave a half-finished artifact at the README-
   referenced path.
9. Optional direct-write paths run after the artifact is produced —
    they capture `timestamped_backup_path(target)` (via the shared
    `foxport.fileops` helper), copy the existing file aside, and swap
    the new one in atomically. When Downloads and history direct-write
    are both selected with `apply`, `migrate_history(...,
    include_download_annotations=True)` also writes Firefox's
    `downloads/destinationFileURI` + `downloads/metaData` annotations
    into the generated `places.sqlite`.
10. If crash reporting is enabled in Settings and a Sentry DSN is
    configured, app startup initializes `foxport.crash_reporting` with
    locals/source context disabled and path-stripping `before_send` hooks.
    No Sentry default argument/log/module integrations are enabled.
11. If the persistent telemetry opt-in is enabled, `MigrationWorker`
    records the Glean `migration` ping using only direction, surface,
    outcome, dry-run/direct-write booleans, selected item slugs, and
    aggregate counts. Paths, profile labels, URLs, exception text, and
    secrets are never passed to `foxport.telemetry`.
12. `MigrationWorker._write_run_manifest` writes `manifest.json` next
    to `README.txt`. Schema-versioned (`schema_version: 1`), records
    per-artifact path/size/sha256/sensitivity/count/direct_write/
    backup_path + the live HIBP / telemetry / crash-reporting status under
    `network`.
13. Worker emits `directWriteBackups` then `finished` → Done page shows
    "Open output folder" plus per-artifact Open/Reveal buttons + a
    Reveal-backup button per direct-write category that produced one
    + a trailing "Save as snapshot…" button.

## Master key dispatch (`crypto/dpapi.load_master_key`)

```
platform == "win32"        → DPAPI v10/v11 (CryptUnprotectData)
                              → fallback: foxport_abe.exe sidecar (UAC)
platform == "darwin"       → Keychain via `security` CLI → PBKDF2 → AES-128
platform.startswith("linux") → secret-tool → kwallet → "peanuts" → PBKDF2 → AES-128
```

`decrypt_value(blob, master)` branches on key length:
* 32-byte key (Windows) → AES-256-GCM
* 16-byte key (mac/Linux) → AES-128-CBC

`decrypt_value_bytes(blob, master)` returns raw plaintext bytes; cookies
use this so they can strip Chrome 130+'s 32-byte SHA-256 host_key prefix
BEFORE UTF-8 decoding.

## Output layout

```
~/Documents/FoxPort/
└── YYYYMMDD-HHMMSS_<source>__to__<target>/
    ├── passwords.csv              # about:logins import
    ├── compromised-passwords.txt  # HIBP scan (opt-in, only when hits found)
    ├── bookmarks.html             # Library import
    ├── extensions.html            # one-click AMO install page
    ├── extensions.json            # machine-readable
    ├── extension-settings.json    # opt-in allowlisted extension settings
    ├── cookies.sqlite             # swap in to closed profile
    ├── places.sqlite              # swap in to closed profile; may include download moz_annos
    ├── formhistory.sqlite         # swap in to closed profile
    ├── recovery.jsonlz4           # sessionstore-backups/
    ├── saved-cards.csv            # 1Password / Bitwarden import format
    ├── search-engines.json
    ├── search-engines/<slug>.xml  # one OpenSearch XML per engine
    ├── downloads.csv              # portable download-history reference
    ├── README.txt                 # per-run import instructions
    └── manifest.json              # schema-versioned per-run registry
```

## .fxport snapshot bundle

```
foxport.snapshot.create_snapshot(input_dir, out_path,
                                  source_label, target_label,
                                  passphrase=None)
foxport.snapshot.restore_snapshot(bundle_path, out_dir,
                                   passphrase=None, overwrite=False)
```

A `.fxport` is either a plain ZIP of `input_dir` (default) or
`FXP\0enc\0v1\0 || iters(4) || salt(16) || nonce(12) || AES-256-GCM(zip)`
when a passphrase is given. PBKDF2-HMAC-SHA256(200 000 iter, 16-byte
salt). Restore verifies SHA-256 per file before writing through
`write_bytes_atomic`, refuses paths that resolve outside `out_dir`,
and refuses non-empty target dirs unless `overwrite=True`. Wrong-
passphrase / truncated-bundle failures surface as plain `ValueError`
so CLI consumers catch them cleanly.

## Where to add a new data type

1. New `foxport/migrate/<thing>.py` with a
   `migrate_<thing>(profile, out_dir, *, dry_run=False)` function
   returning a result dataclass.
2. Optional: a `foxport/migrate/nss_<thing>.py` direct-write path that
   returns a small `<Thing>DirectWriteResult(target_path, backup_path)`
   dataclass so the worker can surface a Reveal-backup button.
3. Optional: an `analyze_<thing>` pre-flight in
   `foxport/migrate/conflicts.py` matching the existing four.
4. `MigrationRequest.do_<thing> = False` in `gui/workers.py`.
5. `MigrationContext.do_<thing> = False` in `gui/pages.py`.
6. New row + checkbox in `ItemsPage._make_row(...)` + `_sync()` line.
7. `MigrationWorker.run` branch for it (call `_log("\n[<thing>]")` for
   parity with existing categories so `--json` mode silences cleanly).
8. `ALL_ITEMS` tuple in `cli.py` + the CLI loop + the `--json` count.
9. Add to the import_instructions table in `browsers/firefox.py`.
10. Add to `manifest._SENSITIVITY` and `manifest._DEFAULT_ACTION` so the
    Done screen / restore-inspect dialog render the right labels.
11. Add to `RunPage.ARTIFACT_ACTIONS` in `gui/pages.py`.
12. Test: `tests/migrate/test_<thing>.py`.

## See also

* `docs/file-formats.md` — Firefox-side schemas FoxPort writes
* `docs/troubleshooting.md` — common failure modes
* `RESEARCH_FEATURE_PLAN.md` — historic deep-research pass; many P2/P3
  items in there have since been shipped.
