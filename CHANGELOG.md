# Changelog

All notable changes to FoxPort are documented here. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/), versioning per
[SemVer](https://semver.org/).

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
