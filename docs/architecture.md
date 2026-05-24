# FoxPort Architecture

A one-page tour of how the codebase fits together. Skip the README if you
already know what FoxPort *does*; this file is about how it does it.

## Layers

```
foxport/
├── app.py / __main__.py        # entry points — wire QApplication + MainWindow
├── cli.py                      # argparse front-end (list/migrate/migrate-reverse/diff/snapshot/restore)
├── config.py                   # persistent Settings (JSON in %APPDATA%/FoxPort etc.)
├── diff.py                     # `diff` subcommand engine
├── snapshot.py                 # .fxport bundle create/restore + AES-256-GCM
│
├── browsers/                   # Detection + read paths
│   ├── detect.py               # per-platform _CHROMIUM_SPECS + _FIREFOX_PROFILES_ROOT
│   ├── chromium.py             # SQLite copy-to-temp reads; is_browser_internal_url filter
│   ├── firefox.py              # output dir creation + import_instructions text
│   └── firefox_read.py         # reverse direction reads (places.sqlite, logins.json via NSS)
│
├── crypto/                     # Master-key recovery + helpers
│   ├── dpapi.py                # Windows DPAPI + AES-GCM
│   ├── keychain.py             # macOS Keychain + Linux libsecret/kwallet + AES-128-CBC
│   ├── nss.py                  # ctypes wrapper around Firefox's nss3 (encrypt + decrypt)
│   ├── abe.py                  # App-Bound Encryption sidecar launcher
│   ├── mozhash.py              # Mozilla mfbt::HashString port (used by places url_hash)
│   └── hibp.py                 # Have-I-Been-Pwned k-anonymity client
│
├── migrate/                    # Forward (Chromium → Firefox) emitters
│   ├── passwords.py            # Firefox CSV
│   ├── bookmarks.py            # Netscape HTML
│   ├── extensions.py           # 4-stage AMO matcher → install-page HTML
│   ├── cookies.py              # writes cookies.sqlite (v17) from scratch
│   ├── history.py              # writes places.sqlite (v86) from scratch
│   ├── autofill.py             # writes formhistory.sqlite (v5) from scratch
│   ├── cards.py                # CSV (Firefox has no native card store)
│   ├── search_engines.py       # OpenSearch XML per engine
│   ├── open_tabs.py            # SNSS Pickle parser → recovery.jsonlz4
│   ├── downloads.py            # downloads.csv
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
│   └── adapters.py             # detect_format + parse_file
│
├── data/
│   └── curated_extension_map.json   # 63 Chrome ID → AMO slug pairs
│
└── gui/                        # PyQt6 wizard
    ├── main_window.py          # 5-step QStackedWidget shell
    ├── pages.py                # Source / Target / Items / Preview / Run pages
    ├── widgets.py              # StepRail, Tile (keyboard-focusable), Banner, FooterBar
    ├── workers.py              # QThread workers — DetectWorker, MigrationWorker
    ├── dialogs.py              # Settings, password preview, bookmark filter, history filter
    └── theme.py                # Catppuccin Mocha QSS
```

## Data flow — forward migration

1. `MainWindow` launches → `DetectWorker` runs `detect_chromium()` +
   `detect_firefox()` on a background thread.
2. User picks tiles on `SourcePage` + `TargetPage`; selections land in
   `MigrationContext`.
3. `ItemsPage` exposes the 10 category checkboxes + Customize…
   dialogs + direct-write toggles + HIBP toggle.
4. `PreviewPage` reads the source profile to compute counts; populates
   `ctx.password_count` etc.
5. User clicks Run → `MainWindow._start_migration` builds a
   `MigrationRequest`, kicks off `MigrationWorker` on a QThread.
6. `MigrationWorker.run` walks the checked categories. Each calls into
   `foxport/migrate/<category>.py:migrate_<category>` with `out_dir` +
   per-category options.
7. Each migrator opens its source file via `_copy_for_read` (copies to
   temp so the source profile stays untouched even while the browser
   runs), processes, writes its artifact to `out_dir`.
8. Optional direct-write paths run after the artifact is produced —
   they back up the existing target file and swap the new one in.
9. Worker emits `finished` → Done page shows "Open output folder" plus
   per-artifact buttons.

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

## Output layout

```
~/Documents/FoxPort/
└── YYYYMMDD-HHMMSS_<source>__to__<target>/
    ├── passwords.csv              # about:logins import
    ├── compromised-passwords.txt  # HIBP scan (opt-in)
    ├── bookmarks.html             # Library import
    ├── extensions.html            # one-click AMO install page
    ├── extensions.json            # machine-readable
    ├── cookies.sqlite             # swap in to closed profile
    ├── places.sqlite              # swap in to closed profile
    ├── formhistory.sqlite         # swap in to closed profile
    ├── recovery.jsonlz4           # sessionstore-backups/
    ├── saved_cards.csv            # 1Password import format
    ├── search-engines.json
    ├── search-engines/<slug>.xml  # one OpenSearch XML per engine
    ├── downloads.csv
    └── README.txt                 # per-run import instructions
```

## Where to add a new data type

1. New `foxport/migrate/<thing>.py` with a `migrate_<thing>(profile, out_dir, *, dry_run=False)` function returning a result dataclass.
2. Optional: a `foxport/migrate/nss_<thing>.py` direct-write path.
3. `MigrationRequest.do_<thing> = False` in `gui/workers.py`.
4. `MigrationContext.do_<thing> = False` in `gui/pages.py`.
5. New row + checkbox in `ItemsPage._make_row(...)` + `_sync()` line.
6. `MigrationWorker.run` branch for it.
7. `ALL_ITEMS` tuple in `cli.py` + the CLI loop.
8. Add to the import_instructions table in `browsers/firefox.py`.
9. Test: `tests/migrate/test_<thing>.py`.

## See also

* `docs/file-formats.md` — Firefox-side schemas FoxPort writes
* `docs/troubleshooting.md` — common failure modes
* `RESEARCH_FEATURE_PLAN.md` — historic deep-research pass; many P2/P3
  items in there have since been shipped.
