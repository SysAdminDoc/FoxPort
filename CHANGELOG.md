# Changelog

All notable changes to FoxPort are documented here. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/), versioning per
[SemVer](https://semver.org/).

## [1.1.0] — 2026-05-23

GUI direction toggle, direct-write cookies/history, open tabs migration,
profile diff CLI, curated-map auditor.

### Added
- **Source step direction toggle** — Segmented Chromium → Firefox /
  Firefox → Chromium selector wired through `MigrationContext.direction`.
  Both `SourcePage` and `TargetPage` swap their tile lists on flip; the
  Items step disables categories not yet supported in reverse mode and
  the Preview step short-circuits to a placeholder for reverse.
- **Master-password prompt** (`gui/dialogs.py:prompt_master_password`) —
  Qt password dialog auto-shown when reverse-mode NSS open fails with a
  master-password error. Re-tries with the entered string; cancel aborts.
- **Cookies direct-write** (`migrate/nss_cookies.py`) — Backs up the
  target's existing `cookies.sqlite` to a timestamped sibling, drops the
  new one in place, and clears `-wal`/`-shm` siblings so Firefox doesn't
  re-merge stale state on next launch. Refuses on locked profile.
- **History direct-write** (`migrate/nss_history.py`) — Same shape as
  cookies; additionally deletes `favicons.sqlite` so Firefox rebuilds
  favicons from the imported visits.
- **Open tabs migration** (`migrate/open_tabs.py`) — URL-scanning SNSS
  parser (RFC 3986 char class on a UTF-16LE regex to prevent field
  bleed) plus an `mozLz40\0` writer that produces Firefox-compatible
  `recovery.jsonlz4`. Optional direct-write to
  `sessionstore-backups/recovery.jsonlz4`.
- **Profile diff** (`foxport/diff.py` + CLI `diff` subcommand) — Reports
  passwords (by URL+username), bookmarks (by URL), and extensions (by
  AMO GUID) that exist in source but not in target, with up to 5
  samples per category.
- **Curated-map auditor** (`scripts/check_curated_map.py`) — Hits AMO's
  detail endpoint for every slug; flags 404, `is_disabled=True`, and
  entries with `last_updated` older than `--stale-months`. Exits 1 on
  any broken result.

### Changed
- `MigrationRequest` gained `direct_write_cookies`, `direct_write_history`,
  `direct_write_open_tabs`, `do_open_tabs`, `direction`, `master_password`.
- `requirements.txt` adds `lz4==4.3.3` (for the recovery.jsonlz4 writer).
- AMO User-Agent bumped to `FoxPort/1.1.0`.

### Notes
- Direct-write cookies/history/open-tabs are forward-only (Chromium →
  Firefox). Reverse-mode direct-write to Chromium's profile DBs is on
  the v1.2 roadmap.
- SNSS URL extraction is intentionally lossy — it gets the URL list
  reliably but not per-tab metadata (window placement, scroll position,
  tab order). A full SNSS Pickle parser is a v1.2 candidate when needed.

## [1.0.0] — 2026-05-23

Reverse direction shipped — FoxPort now flows both ways.

### Added
- **Firefox source readers** (`browsers/firefox_read.py`):
  - `read_firefox_logins` opens an NSS session against a Firefox profile,
    binds `PK11SDR_Decrypt`, and yields `FirefoxLogin` records with
    fully-decrypted username/password fields. Refuses to run on a locked
    profile, propagates master-password failures as `NSSError`.
  - `read_firefox_bookmarks` walks `places.sqlite` (`moz_bookmarks` +
    `moz_places`) and returns `FirefoxBookmark` records flattened with
    their folder path (`toolbar`/`menu`/`unfiled`/`mobile`).
  - `read_firefox_extensions` parses `extensions.json` and filters out
    system add-ons (`*@mozilla.org`, `*@mozilla.com`).
- **Reverse migrators** (`foxport/migrate_reverse/`):
  - `passwords.py` decrypts Firefox logins and writes Chrome's
    import-format CSV (`name, url, username, password, note`). The
    `note` column carries the Firefox GUID for traceability.
  - `bookmarks.py` emits a Netscape HTML grouped so the Firefox
    `toolbar` root lands first and gets `PERSONAL_TOOLBAR_FOLDER="true"`,
    which Chrome maps to its Bookmarks Bar on import. ADD_DATE values
    converted from Firefox µs/1970 to seconds/1970.
  - `extensions.py` inverts `CURATED_MAP` (slug → Chrome ID) and adds an
    `AMO_GUID_TO_CHROME` table for well-known AMO GUIDs like
    `uBlock0@raymondhill.net`. Unmapped extensions fall back to a Chrome
    Web Store text-search URL the user can click.
- **CLI**: new `migrate-reverse` subcommand mirroring `migrate`'s shape
  with `--source / --items / --master-password / --dry-run / --out`.

### Changed
- AMO User-Agent bumped to `FoxPort/1.0.0`.
- Direction is no longer implicit — the README and ROADMAP now describe
  FoxPort as bidirectional.

### Notes
- GUI integration of the reverse direction (a "Direction" toggle on the
  Source step) is queued for v1.1.0; the CLI is the supported surface
  for reverse migrations in v1.0.
- Chrome Web Store has no public search API equivalent to AMO's, so
  unmapped Firefox extensions surface a CWS-search-URL link rather than
  a direct install link.

## [0.6.0] — 2026-05-23

Additional data types — form autofill, saved cards, search engines.

### Added
- **Form autofill migration** (`migrate/autofill.py`) — Walk Chromium's
  `Web Data.autofill` SQLite (fieldname, value, count, date_created,
  date_last_used) and write a Firefox v4-schema `formhistory.sqlite` from
  scratch. Time conversion is seconds-since-1601 (NOT microseconds, unlike
  passwords) → microseconds-since-1970. GUIDs are base64-encoded 9-byte
  tokens matching Firefox's `PlacesUtils.history.makeGuid()` shape.
- **Saved cards CSV** (`migrate/cards.py`) — Decrypt `Web Data.credit_cards`
  with the AES master key (Windows DPAPI / macOS Keychain / Linux secret
  store all work) and write a CSV with the 1Password import shape:
  `Type, Name, Number, Expiration (MM/YYYY), Cardholder name, Notes`.
  Firefox has no native card store, so this is opt-in and informational.
- **Search engines** (`migrate/search_engines.py`) — Read `Web Data.keywords`
  and emit `search-engines.json` plus one OpenSearch XML file per engine
  under `search-engines/<slug>.xml`. Chromium-specific URL tokens
  (`{google:baseURL}`, `{yahoo:...}`, etc.) are stripped during render
  so the resulting templates work in Firefox. User opens each XML in
  Firefox → Settings → Search → Add.
- Items wizard step gains three new checkboxes (Form autofill, Saved
  credit cards, Search engines) all defaulting to off.
- CLI `--items` and `--all` accept `autofill`, `cards`, `search_engines`.

### Notes
- Open tabs (Chromium `Sessions/Session_*` SNSS binary → Firefox
  `recovery.jsonlz4`) is genuinely complex (SNSS protobuf-ish format
  requires its own parser) — deferred to v0.6.1 / v0.7.
- Search engines fall short of writing `search.json.mozlz4` directly
  because that file is hash-validated and the schema flips with each
  Firefox release; the OpenSearch-per-engine approach is robust.

## [0.5.0] — 2026-05-23

Cross-platform — macOS and Linux support across detection, decryption,
and NSS write-back.

### Added
- **macOS browser detection** — `_CHROMIUM_SPECS_MAC` covers Chrome stable
  / Beta / Canary, Chromium, Brave (3 channels), Edge (3 channels),
  Vivaldi, Opera + GX (flat layout under `com.operasoftware.*`), Yandex,
  Arc, Thorium. Firefox-family detection uses `~/Library/Application
  Support/<vendor>/profiles.ini`.
- **Linux browser detection** — `_CHROMIUM_SPECS_LINUX` covers the same
  set under `$XDG_CONFIG_HOME` (or `~/.config`). Firefox-family detection
  walks per-vendor dotfiles (`~/.mozilla/firefox`, `~/.librewolf`,
  `~/.waterfox`, `~/.floorp`, `~/.zen`, etc.).
- **Cross-platform master-key recovery** (`crypto/keychain.py`) —
  - macOS: `security find-generic-password -w -s "<Browser> Safe Storage"`
    → PBKDF2-SHA1 with `salt="saltysalt"`, 1003 iterations, 16-byte key.
  - Linux: `secret-tool` → `kwallet-query` / `kwallet5-query` →
    `"peanuts"` plaintext fallback → PBKDF2-SHA1 with 1 iteration.
  - All paths return an AES-128 key; cookies/passwords on these platforms
    use AES-128-CBC of `v10`-prefixed blobs (PKCS7-padded, IV = sixteen
    spaces). `decrypt_value()` branches on key length.
- **NSS auto-detection on macOS/Linux** (`crypto/nss.py`) — covers
  `/Applications/<Browser>.app/Contents/MacOS/libnss3.dylib` and
  `/usr/lib*/libnss3.so` plus Flatpak/Snap paths.
- **Cross-platform process detection** (`is_chromium_running`) — uses
  `ps -axo comm=` on Linux/macOS, `tasklist /FO CSV /NH` on Windows.

### Changed
- `ChromiumKey` now accepts 16-byte (AES-128, macOS/Linux v10) or 32-byte
  (AES-256, Windows v10/v11/v20) keys.
- `migrate_cookies` only strips the 32-byte HOST_KEY prefix on Windows
  (the Chrome 130+ behavior only applies to the GCM path).
- `_chromium_base()` and `_firefox_base()` consolidate per-platform root
  selection so the rest of the detection code stays platform-agnostic.
- Platform badge in README updated to Windows | macOS | Linux.

### Notes
- The ABE sidecar remains Windows-only (it's a COM consumer of the per-
  browser `IElevator` interface). macOS and Linux Chrome don't currently
  ship an equivalent ABE layer for the cookie/password store.
- LibreWolf is the same shape as Firefox on every platform — no special
  cases needed.

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
