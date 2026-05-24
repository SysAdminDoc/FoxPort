# Changelog

All notable changes to FoxPort are documented here. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/), versioning per
[SemVer](https://semver.org/).

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
