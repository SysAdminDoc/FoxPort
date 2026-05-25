# Changelog

All notable changes to FoxPort are documented here. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/), versioning per
[SemVer](https://semver.org/).

## [1.3.0] — 2026-05-24

Trust + completeness pass — Phase A of the v1.3 roadmap. Atomic
fileops, ASCII-safe CLI help, generalized import instructions,
snapshot overwrite policy, open-tabs direct-write wiring. **97 tests
pass** (up from 89). No new user-facing features yet; this batch
hardens the surfaces that the v1.3 GUI and release work will land on.

### Added
- `foxport/fileops.py` — `write_bytes_atomic()` and
  `replace_file_atomic()` helpers. Sibling temp file + `fsync` +
  `Path.replace` so an interrupted write can't leave a half-finished
  file at the target name.
- `tests/test_fileops.py` — coverage for the atomic helpers,
  including the source-missing-on-replace case (target must remain
  intact, no orphan temp files).
- `tests/test_cli_help.py` — recursively walks every subparser and
  asserts the help text is ASCII-safe. Catches the cp1252 regression
  before it ships.
- `tests/test_import_instructions.py` — pins generated README
  coverage for every emitted artifact (passwords, HIBP, bookmarks,
  extensions, cookies, history, autofill, cards, search engines,
  open tabs, downloads) and the reverse-direction Chrome
  workflows.
- `snapshot restore --overwrite` flag — restore into a non-empty
  output directory only with explicit opt-in.

### Changed
- `foxport/cli.py` — top-level argparse description swapped the
  Unicode arrow for ` - ` so the help command runs cleanly under
  cp1252. Subcommand descriptions stay ASCII too.
- `foxport/browsers/firefox.py:import_instructions()` rewritten as a
  data-driven generator that covers every artifact key forward and
  reverse. Says favicons.sqlite is **moved aside** (the v1.2.1
  behavior), no longer "deleted".
- `foxport/snapshot.py:create_snapshot()` writes through
  `write_bytes_atomic()`; refuses an output path inside the input
  directory.
- `foxport/snapshot.py:restore_snapshot()` refuses non-empty output
  directories unless `overwrite=True`; the SHA-256 integrity check
  runs before the atomic write so a tampered manifest fails fast.
- `foxport/migrate/nss_cookies.py`, `nss_history.py`, `open_tabs.py`
  — direct-write paths use `replace_file_atomic()` so the target
  cookies.sqlite / places.sqlite / recovery.jsonlz4 file can never
  end up half-written after the backup is taken.
- `MigrationContext.direct_write_open_tabs` is now wired end-to-end:
  Items checkbox → MigrationContext → MigrationRequest → worker.
  The previously hidden flag is reachable from the GUI with locked-
  profile, reverse-mode, and category-dependency guards.

### Internal
- `foxport/__init__.py` bumped to `1.3.0`.
- ROADMAP.md reorganized as the single to-do file; historical
  milestones collapsed; v1.3 phases A–D promoted from
  RESEARCH_FEATURE_PLAN.md.

### Phase B — Done + Items parity (in progress)
- `RunPage` Done-screen action bar is now generated from
  `ARTIFACT_ACTIONS` instead of six hardcoded buttons. Every artifact
  the worker emits (passwords, HIBP report, bookmarks, extensions,
  cookies, history, autofill, cards, search engines, open tabs,
  downloads) gets an Open or Reveal button on completion. The page
  exposes a single signal `artifactActionRequested(key, action_kind)`;
  `MainWindow._on_artifact_action` routes it to `_open_path` /
  `_reveal_path`. Adding a new artifact only requires appending one
  row to `ARTIFACT_ACTIONS` and the worker's `exports` map.
- `ItemsPage.set_counts()` now takes `dict[str, int]` and updates
  every registered category badge (was: positional 5-arg signature
  that left autofill / cards / search-engines / open-tabs / downloads
  perpetually unbadged on back-nav).
- `MigrationContext.counts: dict[str, int]` replaces the five
  positional `*_count` attributes. `PreviewPage` populates it on
  every entry; `_start_migration` forwards it to the Items page.
- `.github/workflows/ci.yml` runs `python -m foxport.cli --help` as
  a regression guard against the v1.2.1 cp1252 crash, and sets
  `QT_QPA_PLATFORM=offscreen` so the new GUI smoke tests run on Linux.
- `tests/test_gui_run_actions.py` — 5 new tests covering
  `ItemsPage.set_counts(dict)`, unknown-key resilience, Done-screen
  button generation order, signal closure binding, reset cleanup,
  and failure-state action hiding.

### Regression tests for the gaps the v1.3 audit found
- `tests/migrate/test_downloads.py` — 4 tests for the CSV shape, the
  state-label mapping (0 = in_progress, 1 = complete, etc.),
  the no-History-DB branch, and dry-run.
- `tests/migrate/test_search_engines.py` — 5 tests covering the slug
  helper, Chrome `{google:*}` token stripping in OpenSearch XML, the
  no-Web-Data branch, full round-trip with multiple engines + skip
  for empty name / empty URL, and dry-run.
- `tests/test_diff.py` — 4 tests for the CLI `diff` subcommand's
  set-difference logic across passwords / bookmarks / extensions
  with all readers mocked (no real profile required). Includes the
  NSS-error-fail-open path and the gecko-id-vs-installed-guid check.
- `tests/migrate_reverse/test_bookmarks_reverse.py` — 3 tests
  pinning the Firefox-toolbar-first-and-tagged invariant (Chrome's
  Bookmarks Bar promotion rule), HTML/URL escape, and dry-run.
- Reverse passwords / bookmarks / extensions emitters now go through
  `write_text_atomic` for consistency with the forward direction.

### Documentation drift fixes
- README curated-map count corrected to 67 entries (was 63 pre-audit).
- README "Security notes" rewritten as a longer enumeration that
  describes both optional network endpoints (AMO + HIBP),
  manifest.json semantics, atomic direct-write behavior, the NSS
  version guard, and DPAPI scoping. Replaces the v1.2 paragraph that
  only mentioned AMO.
- `foxport/browsers/firefox.py` module docstring updated to
  acknowledge direct-write modules (the old version claimed FoxPort
  emits "import files" only).
- `CLAUDE.md` curated-map line synced to "67-entry" with the
  category-count framing.

### External bookmark adapters surfaced (Phase C)
- `import_/adapters.write_netscape_html()` — shared emitter consumed
  by the CLI subcommand and the GUI manual-drop branch. Groups by the
  first folder-path segment so the user sees "Pocket / Pinboard /
  OPML feeds / Imported" sections in their Library after import.
  HTML-escapes title and URL; surfaces tags as the optional `TAGS=`
  attribute. Goes through `write_text_atomic()` for safety.
- `python -m foxport.cli import-bookmarks --input <file>` converts a
  Pocket / Pinboard / OPML / Netscape export to a Firefox-importable
  `.firefox.html` sibling. Format is auto-detected by content; the
  `--format pocket|pinboard|opml|netscape` flag lets power users
  override the heuristic. Returns non-zero on missing input or zero
  parsed bookmarks.
- The GUI manual-drop tile (Source step) now tries the bookmark
  adapters before the Chromium-profile path. A dropped Pocket JSON,
  Pinboard JSON, OPML XML, or Netscape HTML file is converted in
  place to a `.firefox.html` sibling and the banner copy points the
  user at Firefox Library import.
- `tests/test_import_bookmarks_cli.py` — 5 tests covering grouping,
  HTML escape (XSS guard), Pinboard round-trip, format override, and
  missing-input error path.

### NSS version-skew guard (Phase C)
- `crypto/nss.py` binds `NSS_GetVersion()` and captures the reported
  version on `NSSLibrary.version`. `open_session()` takes a
  `require_compatible_version=True` keyword (default for direct-write
  paths) and raises `NSSVersionMismatchError` if the loaded major
  version is below 3. `FOXPORT_NSS_FORCE=1` overrides for portable
  Firefox builds whose stripped NSS doesn't expose the symbol.
- `migrate/nss_passwords.DirectWriteResult.nss_version` carries the
  captured version through to the GUI worker, which logs it next to
  the per-row write counts. The run manifest records it on the
  passwords artifact via the worker's normal recording path.
- `tests/crypto/test_nss_version.py` — 11 tests covering the
  parametrized version parser, the open-session refusal path, and
  the env-var override.

### Atomic-replace for staging emitters (Phase C)
- `foxport/fileops.py` grew `write_text_atomic(path, str)` — thin
  wrapper over `write_bytes_atomic` for emitters that build text in
  memory.
- Every non-`nss_*` writer routes through one of the atomic helpers
  now. CSV/HTML/JSON/mozLz40 emitters build their payload in
  `io.StringIO` (text) or memory (bytes) and call
  `write_text_atomic` / `write_bytes_atomic`. SQLite emitters build
  the DB in a private `tempfile.mkdtemp()` and `replace_file_atomic`
  it into the staging path on success. A torn write mid-run can no
  longer leave a corrupt `passwords.csv` / `cookies.sqlite` /
  `places.sqlite` / `formhistory.sqlite` / `recovery.jsonlz4` /
  `extensions.html` / `search-engines/*.xml` at the path the
  generated README and `manifest.json` point at.
- Migrators that previously called `.unlink()` on a stale output before
  reopening it no longer need that step — the atomic replace overwrites
  in one operation.

### Saved-cards CSV cleanup
- `migrate/cards.py` dropped the duplicate `Name` column. The shape is
  now `Type, Cardholder name, Number, Expiration, Notes`. Chrome's
  saved-card store only captures one human name (`name_on_card`); the
  v1.2 export emitted it twice and confused importers that key on
  column names.
- `migrate_cards()` refuses to emit a CSV when zero cards decrypted —
  the user no longer sees a header-only file that looks like a
  catastrophic data loss.
- `tests/migrate/test_cards.py` — 4 new tests covering the column
  shape invariant, the empty-blob no-CSV behavior, the no-Web-Data
  branch, and dry-run.

### Per-run manifest (Phase B)
- `foxport/manifest.py` — schema-versioned `RunManifest` /
  `RunArtifact` dataclasses, `build_artifact()` (hashes + sizes +
  sensitivity labels per artifact key), `write_manifest()`,
  `load_manifest()` (forward-compatible — unknown top-level and
  per-artifact keys drop instead of TypeError'ing).
- GUI worker + both CLI subcommands (`migrate`, `migrate-reverse`)
  now write `manifest.json` next to `README.txt`. Records source +
  target labels, direction, dry-run flag, requested items, allowed
  network endpoints (AMO + HIBP), and per-artifact path / size /
  SHA-256 / count / sensitivity / direct-write backup path.
- `tests/test_manifest.py` — 8 tests covering build, write/load
  round-trip, reveal-vs-open action mapping, direct-write backup
  recording, relative paths through subdirectories, forward-compat
  for unknown manifest keys, and a guard that plaintext password
  bodies never leak into the serialized manifest. **110 tests pass.**

## [1.2.1] — 2026-05-24

Extreme hardening pass — five batches of audit fixes across correctness,
resource safety, security, UX, and test coverage. No new user-facing
features; everything below is a quality / safety improvement on the
v1.2.0 surface area. **89 tests pass** (up from 69).

### Fixed (data-loss + correctness)
- `migrate/nss_passwords.py` — **stop silently overwriting unreadable
  `logins.json`.** The pre-audit code returned an empty store on any
  parse/IO failure, which then caused the migrator to clobber the
  user's real entries with an empty array on the first re-run. New
  `LoginsCorruptError` propagates so the caller aborts instead.
- `migrate/passwords.py` — HIBP scan no longer re-decrypts every row.
  Both the CSV writer and the HIBP scan now consume the same
  in-memory `(PasswordRow, plaintext)` list. Empty-blob and
  empty-plaintext rows count toward `skipped_empty` so
  `total == decrypted + skipped_empty + failed` holds. Broad-except
  guard on the cryptography call site (wrong-length keys raise
  `ValueError`, not `DecryptionError`) keeps one bad row from
  aborting the batch.
- `migrate/nss_passwords|nss_cookies|nss_history` — `backup_path`
  becomes `Path | None` so callers can distinguish "no previous
  file" from a real backup. Removes the fake `.no-backup-needed`
  sentinel path that leaked into user-facing log lines.
- `migrate/nss_history.py` — rename the misleading
  `favicons_deleted: bool` field to `favicons_backup_path: Path |
  None`; the file is moved aside to a timestamped backup, not
  deleted (the old name lied about the behavior).
- `migrate/search_engines.py` — `_copy_for_read` now pulls the
  `-wal` / `-shm` siblings; recently-added engines were being
  dropped from the read snapshot because the WAL hadn't been
  checkpointed yet.

### Fixed (resource safety + thread safety)
- `gui/pages.py` — consolidate Preview's per-DB count helpers behind
  a single `_safe_sqlite_count()` that copies the DB + WAL/SHM
  siblings, runs the queries, and always tears the tempdir down —
  even when `mkdtemp` / `copy2` / `connect` raise in between (the
  per-helper try/except left tempdirs leaked on early failure).
- `gui/main_window.py` — new `closeEvent()` blocks Alt-F4 during a
  live migration with a confirm prompt + bounded thread wait.
  Direct-write paths can leave a half-imported `logins.json` /
  `places.sqlite` if the worker is killed between the backup and
  the atomic replace.

### Security
- `snapshot.restore_snapshot()` — reject absolute paths and `..`
  segments in manifest entries up front. Replace the prefix-string
  check (which falsely accepted `/safe-evil/x` against `/safe`)
  with `Path.relative_to()`. Verify each file's manifest SHA-256
  digest before writing. Drop unknown manifest keys defensively so
  a tampered or forward-compatible bundle doesn't TypeError the
  `SnapshotManifest()` constructor.
- `migrate/extensions._amo_detail` — URL-quote the `gecko_id` path
  segment (`safe=""`) so an attacker-controlled extension manifest
  can't inject path or query traversal into the AMO URL.
- `crypto/hibp` — User-Agent now reflects the live
  `foxport.__version__` instead of a frozen `"1.2"` string.

### UX / Accessibility
- `gui/theme.py` — visible keyboard `:focus` indicators for `Tile`,
  `QCheckBox`, `QPushButton`. Tiles had `StrongFocus` but no visual
  focus state, so Tab navigation was effectively invisible.
- `gui/pages.py:RunPage` — persistent dry-run banner at the top of
  the Run page whenever `ctx.dry_run` is set. The Preview step
  showed DRY RUN in the summary tree, but the Run page used to look
  identical for real and dry-run executions until users noticed
  "No files were written" buried in the log.

### Tests (69 → 89)
- `test_passwords` — pin the `_decrypt_all` invariants
  (`total == decrypted + skipped_empty + failed`, isolated failure
  handling, unexpected-exception fallback path).
- `test_nss_passwords` — pin the LoginsCorruptError data-loss fix
  for corrupt JSON, missing `logins` key, and non-object roots.
- `test_autofill` — end-to-end Chrome `Web Data.autofill` →
  `formhistory.sqlite` test that asserts the Firefox v5 schema
  (presence of `moz_sources` + `moz_history_to_sources`,
  `PRAGMA user_version = 5`). A v4-looking output triggers
  Firefox's first-launch auto-migration and corrupts the DB.
- `test_snapshot` — 4 new regression tests covering the path-
  traversal rejection (absolute, `..`, prefix-bypass), sha256
  integrity verification, and the forward-compat unknown-key drop.

## [1.2.0] — 2026-05-23

Research-driven correctness + trust pass. Acts on every P0 and most P1/P2
items from `RESEARCH_FEATURE_PLAN.md`.

### Fixed (P0 correctness)
- `migrate/history.py` — `PRAGMA user_version` bumped 77 → 86 (Firefox
  tip). Added `block_until_ms` + `block_pages_until_ms` to `moz_origins`
  to match v78–v86 column additions. **`url_hash` algorithm replaced**:
  the previous MD5 + fabricated-scheme-int-table approach is gone. New
  `crypto/mozhash.py` is a faithful port of `mfbt::HashString`
  (`AddU32ToHash` mix; RotateLeft5 + 0x9E3779B9 golden ratio). Hashes now
  match what Firefox computes on first visit; AwesomeBar dedup works.
- `migrate/open_tabs.py` — rewrote the SNSS extractor. Walks SNSS
  commands with a proper uint16-size + uint8-id parser. Pulls URLs from
  `kCommandUpdateTabNavigation` (id 6 / 0x21) Pickle payloads with a
  UTF-8 regex fallback for schema drift. Reads both `Sessions/Session_*`
  **and** `Sessions/Tabs_*` files (the previous extractor only looked at
  Session_*, which on real Chrome data return 0 URLs). Live verification
  against this host: 0 → 12 URLs extracted from the same profile.
- New `tests/` tree with `pyproject.toml` pytest config and 56 round-trip
  tests across bookmarks, history, cookies, open_tabs, extensions,
  mozhash, HIBP, export-dir, and config. CI runs `pytest` cross-platform.

### Added
- `crypto/hibp.py` — HIBP Pwned Passwords k-anonymity client. SHA-1 hash
  each plaintext, request the 5-char prefix only, scan the returned
  suffix list for the rest. Per-prefix LRU cache; `Add-Padding: true`
  request header. Opt-in via Items-step checkbox or CLI `--hibp`.
  Produces `compromised-passwords.txt` with URL + username
  (NEVER the plaintext).
- `foxport/config.py` + `gui/dialogs.SettingsDialog` — persisted
  preferences (output dir, password masking, online AMO lookup, dry-run
  default, HIBP default, future telemetry / crash-reporting opt-ins).
  Per-platform: `%APPDATA%/FoxPort/`, `~/Library/Application Support/
  FoxPort/`, `$XDG_CONFIG_HOME/FoxPort/`.
- `gui/dialogs.HistoryFilterDialog` — time-range picker with presets
  (Last 7 / 30 / 90 days, Last 12 months, Custom range). Threaded
  through `MigrationContext.history_date_from_us` /
  `history_date_to_us` → `migrate_history(date_from_us=, date_to_us=)`.
- `crypto/nss.NSSSession.decrypt()` — public method binding
  `PK11SDR_Decrypt`. Replaces the previously-inline `_lib.handle.PK11SDR
  _Decrypt` access in `browsers/firefox_read.py`.
- `scripts/harvest_reverse_map.py` — walks the curated forward map and
  queries the AMO detail endpoint to populate
  `AMO_GUID_TO_CHROME` automatically. `--write` rewrites the module.
- `migrate/autofill.py` — `formhistory.sqlite` schema bumped v4 → v5
  with empty `moz_sources` + `moz_history_to_sources` tables (avoids
  Firefox's first-launch migration race).
- `browsers/firefox.make_export_dir` — slug-safe filename component
  scrubbing (`[A-Za-z0-9._-]`-only, 120 char cap, NULs stripped) plus
  resolved-path bounds check refusing any path that escapes the parent.

### Changed
- `gui/pages.SourcePage._on_drop` — was dead code. Now promotes the
  dropped folder into a synthetic `ChromiumProfile` (handles Login Data
  file / profile dir / User Data root) and appends it to the source
  tile list with auto-select.
- `gui/dialogs.PasswordPreviewDialog` — passwords masked by default
  (first/last char visible, middle dots). New "Show all passwords"
  toggle button.
- `migrate/extensions._build_html` — already-installed extensions fold
  into a collapsed `<details>` block so a one-click install pass
  doesn't re-tap them. Stat "Matched" renamed "To install" (matched
  minus already-installed) for accuracy.
- `migrate/cookies._FIREFOX_COOKIES_SCHEMA` — added missing
  `updateTime INTEGER` column (Firefox 138 expects it per v17).
- `migrate/nss_history.write_history_into_target` — `favicons.sqlite`
  is moved to `favicons.foxport-backup-<mtime>.sqlite` instead of
  unlinked. Field name `favicons_deleted` kept for API stability.
- `browsers/chromium.is_browser_internal_url` — new predicate covering
  `chrome://`, `chrome-extension://`, `chrome-search://`,
  `chrome-untrusted://`, `chrome-devtools://`, `devtools://`, `edge://`,
  `brave://`, `opera://`, `vivaldi://`, `yandex://`, `arc://`, `about:`.
  Applied in bookmarks + history + open_tabs by default. New
  `include_internal=True` kwarg for the opt-in case.
- `cli.AmbiguousProfileMatch` — raised when `--source`/`--target` matches
  more than one profile via substring. Exits 2 instead of silently
  picking the first.
- `gui/main_window._start_migration` — master-password prompt loops up
  to 3 attempts on reverse-mode NSS open; surfaces "attempt N of 3" in
  the title.
- `scripts/check_curated_map.py` — `--strict-stale` flag exits 2 when
  any entry is older than `--stale-months`.
- `migrate_reverse/extensions.AMO_GUID_TO_CHROME` — removed the
  `"{446900e4-…}": ""` placeholder and the wrong-mapping ClearURLs
  entry. 11 verified entries remain.

### Notes
- 56/56 tests pass. CI YAML installs pytest and runs the suite on
  Windows/macOS/Linux × Python 3.11/3.12.
- HIBP scan is OFF by default. When enabled, only the 5-char SHA-1
  prefix leaves the machine (HIBP k-anonymity guarantee).
- Settings dialog ships with telemetry + crash-reporting checkboxes
  disabled in the UI; they're persisted but the v1.3 Glean + Sentry
  wiring isn't yet present.

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
