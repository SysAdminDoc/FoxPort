# Changelog

All notable changes to FoxPort are documented here. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/), versioning per
[SemVer](https://semver.org/).

## [0.4.0] — 2026-05-23

CLI mode, per-row filtering, and NSS direct-write password import.

### Added
- **CLI** (`foxport/cli.py`) — `python -m foxport.cli {list,migrate}` with
  `--source / --target / --items / --all / --dry-run / --out / --no-online`.
  Profile names support substring matching (`brave/default` finds
  `Brave — Default`).
- **Per-folder bookmark filter** (`migrate/bookmarks.py:FolderFilter`) — A
  `folder_filter` predicate callable trims branches before HTML emission.
  Surfaced in the GUI as a "Customize…" button on the Items step that opens
  a `BookmarkFilterDialog` with a tickable tree of folders.
- **Per-row password filter** (`migrate/passwords.py:PasswordPredicate`) —
  A `row_filter` predicate trims rows before encryption. Surfaced in the
  GUI as a "Customize…" button that opens a `PasswordPreviewDialog` showing
  a searchable, plaintext table of all logins with per-row checkboxes.
- **NSS direct-write** (`crypto/nss.py` + `migrate/nss_passwords.py`) —
  Loads target Firefox install's `nss3.dll` (search order:
  `%ProgramFiles%\Mozilla Firefox\`, LibreWolf, Waterfox, Floorp, Mullvad,
  Zen, or `FOXPORT_NSS_PATH`); calls `PK11SDR_Encrypt` per login and writes
  directly into `logins.json` + `logins-backup.json`. Backup of any
  pre-existing `logins.json` lands at `logins.foxport-backup-<mtime>.json`.
  Refuses to run when `parent.lock` is present. Opt-in via Items-step
  checkbox.
- Conflict-safe direct write: existing entries matching FoxPort's
  deterministic GUID (`uuid5(NS, origin+username)`) are skipped.
- New `MigrationRequest` fields: `password_include_keys`,
  `bookmark_excluded_paths`, `direct_write_passwords`.
- New `MigrationContext` fields mirror the above plus runtime flags.

### Changed
- AMO User-Agent bumped to `FoxPort/0.4.0`.
- `migrate_passwords` accepts an optional `row_filter`.
- `migrate_bookmarks` accepts an optional `folder_filter`.

### Notes
- NSS direct-write fails fast with a clear error if a master password is
  set on the target — pass `master_password=` to `migrate_passwords_via_nss`
  or remove it before importing.
- NSS direct-write is **always paired** with a CSV export to the output
  folder so you have a safety net if `logins.json` ends up unreadable.

## [0.3.0] — 2026-05-23

Cookies + history + dry-run + App-Bound Encryption sidecar.

### Added
- **Cookies migration** (`migrate/cookies.py`) — decrypt all entries in
  Chromium's `Network/Cookies` (or legacy `Cookies`) SQLite using the same
  AES-GCM key as passwords, strip the 32-byte SHA-256 `HOST_KEY` prefix on
  Chrome 130+ (`meta.value WHERE key='version' >= 24`), and write a fresh
  Firefox v17-schema `cookies.sqlite` from scratch. Timestamps converted
  from Chromium WebKit µs/1601 to Firefox µs/1970 (creationTime,
  lastAccessed) or s/1970 (expiry). Default `schemeMap=2` for HTTPS,
  domain-vs-host-only inferred from leading dot in `host_key`.
- **History migration** (`migrate/history.py`) — walk Chromium's `History`
  database (`urls` + `visits` tables) and write a fresh Firefox v77-schema
  `places.sqlite` populating `moz_origins`, `moz_places`
  (`frecency=-1`, `recalc_frecency=1`, scheme-tagged `url_hash` per
  `toolkit/components/places/Helpers.cpp`), and `moz_historyvisits`. Chrome
  PageTransition LSB mapped to Firefox `visit_type`. Bookmarks tree left
  empty so the HTML import flow handles them.
- **Dry-run mode** — A `dry_run` flag on `MigrationRequest` and a checkbox
  on the Items step. All migrators count items and exercise decryption
  without writing artifacts; output folder is suffixed `_dryrun`.
- **App-Bound Encryption sidecar source** (`tools/abe_sidecar/`) — Tiny
  Windows-only C++ EXE that calls per-browser `IElevator` COM interfaces
  (Chrome/Brave/Edge IIDs hard-coded from xaitax research) to recover the
  AES master key on Chrome 127+ / Brave 1.86+ profiles. CMakeLists.txt +
  embedded `requireAdministrator` manifest + Python launcher
  (`crypto/abe.py`) that locates the bundled `foxport_abe.exe`, invokes it
  with UAC, parses the `KEY_HEX:<hex>\nOK\n` response.
- `load_master_key()` now accepts `browser_display` and `try_abe` parameters
  and automatically falls back to the ABE sidecar when the classic key is
  absent. Surfaces `AbeSidecarMissingError` cleanly when the EXE hasn't been
  built yet.
- Two new Done-screen action buttons — "Reveal cookies.sqlite" /
  "Reveal places.sqlite" (Explorer `/select,`).
- Preview tree now shows cookies count and history `(URLs / visits)`.
- `firefox.import_instructions` documents the "close Firefox, back up,
  swap" flow for cookies.sqlite and places.sqlite.

### Changed
- `migrate_passwords`, `migrate_bookmarks`, `migrate_extensions` all accept
  a `dry_run` kwarg. Existing callers stay binary-compatible.
- `MigrationRequest` gained `do_cookies`, `do_history`, `dry_run` fields
  (defaulting to off so existing automation isn't affected).
- AMO User-Agent bumped to `FoxPort/0.3.0`.

### Notes
- `foxport_abe.exe` ships as source. The compiled + signed Windows binary
  is on the v0.3.1 roadmap (release pipeline work, not a code issue).
  FoxPort works fine without it for classic-key profiles; ABE-only
  profiles will see an `AppBoundEncryptionError` with a clear "build
  the sidecar" message.

## [0.2.0] — 2026-05-23

Research-driven UX + matching rewrite. No source-browser format changes.

### Added
- **Five-step wizard GUI** (`gui/widgets.py`, `gui/pages.py`) — `QStackedWidget`-based
  flow (Source → Target → Items → Preview → Run/Done) with a left-rail step
  indicator, tile-based pickers, drag-and-drop on the source step, count badges
  on the items step, and a sample-rich preview tree before commit.
- **Curated extension map externalized to JSON**
  (`foxport/data/curated_extension_map.json`) — 63 verified entries across 14
  categories, loaded at import time. Community-contributable without touching code.
- **Gecko ID probe** — When a Chromium extension's manifest declares
  `browser_specific_settings.gecko.id`, FoxPort hits AMO's detail endpoint with
  that GUID for a 100%-confidence match before falling back to name search.
- **Permission-overlap confidence scoring** — Non-curated matches are tagged
  `amo-exact`, `amo-search`, `amo-search-medium`, or `amo-search-low` based on
  Jaccard similarity between Chrome and AMO permission sets.
- **Already-installed detection** — Reads target Firefox profile's
  `extensions.json` and strikes through matched-but-already-installed entries
  in the report.
- **App-Bound Encryption awareness** (`crypto/dpapi.py`) — Detects
  `app_bound_encrypted_key` in `Local State` and surfaces a clear warning;
  classic-key migrations proceed normally.
- **Opera Stable / Opera GX flat-profile layout** — `_BrowserSpec` registry now
  encodes per-browser layout quirks; Opera's single-flat-profile case is handled.
- **Browser-running detection** — `tasklist`-based probe plus SingletonLock
  check; surfaces an amber banner on the source page when a browser is open.
- **Firefox profile lock detection** — `parent.lock` check on the target page.
- **Deterministic password GUIDs** — `uuid5(origin+username)` makes re-runs
  idempotent on Firefox's CSV dedup.
- **Richer extensions.html report** — Summary stats row, per-row permissions
  preview, user count, AMO rating, already-installed strikethrough.

### Changed
- AMO User-Agent bumped to `FoxPort/0.2.0`, `Accept-Encoding: gzip` added.
- `ExtensionInfo` gained `gecko_id`, `chrome_permissions`, `chrome_host_permissions`.
- `MigrationWorker.finished` now emits `(ok, payload, exports_map)` so the Done
  screen can wire per-file open buttons.

### Documentation
- README rewritten to cover the new wizard, the four-stage extension matching,
  and the ABE caveat.
- ROADMAP refreshed: v0.3.0 promoted to cookies + history + direct NSS write
  + ABE bypass via side-car EXE.

## [0.1.0] — 2026-05-23

Initial release.

### Added
- Detect installed Chromium-family browsers: Chrome (stable / Beta / Canary),
  Chromium, Brave (stable / Beta / Nightly), Edge (stable / Beta / Dev),
  Vivaldi, Opera, Opera GX, Yandex, Arc, Thorium.
- Detect installed Firefox-family browsers via `profiles.ini`: Firefox
  (stable / Nightly / ESR), LibreWolf, Waterfox, Floorp, Mullvad Browser,
  Tor Browser, Zen Browser.
- Per-profile enumeration for both source and target browsers.
- Password migration: DPAPI-unwrap of `Local State` master key,
  AES-256-GCM decryption of `Login Data` entries, export as Firefox-format
  CSV consumable by `about:logins`.
- Bookmark migration: walk `Bookmarks` JSON, emit Netscape HTML with
  `PERSONAL_TOOLBAR_FOLDER` tagging for the toolbar root.
- Extension migration: curated Chrome → AMO map for the most-used add-ons,
  plus optional AMO search API lookup for everything else. Output is an
  HTML page with one-click Install links plus a `extensions.json` map.
- PyQt6 GUI with Catppuccin Mocha dark theme, threaded detection +
  migration workers, log panel, progress bar, output-folder picker.
- README import instructions written into every export folder.
