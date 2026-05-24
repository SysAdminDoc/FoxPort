# ROADMAP

Items here are concrete units of work. Check them off as shipped; promote rough
ideas from the bottom of the file as scope firms up.

## v0.2.0 — Cookies + History
- [ ] Cookie migration (Chromium `Cookies` SQLite → Firefox `cookies.sqlite` via SQL)
- [ ] Browsing history (Chromium `History.urls` → Firefox `places.sqlite.moz_places` SQL import)
- [ ] Open-tabs migration (Chrome `Session Storage` → Firefox session-restore JSON)
- [ ] Dry-run mode — count items, decrypt-test, no file writes

## v0.3.0 — Quality of life
- [ ] CLI mode (`python -m foxport --source "Brave/Default" --target "Firefox/default-release" --all`)
- [ ] Per-folder bookmark filter (skip / rename folders before export)
- [ ] Password search/filter in a preview table before export
- [ ] Auto-detect when source browser is running and warn (data may be stale)

## v0.4.0 — Direct write mode
- [ ] Optional direct-write to a *new, empty* Firefox profile (still no clobbering existing profiles)
- [ ] Native NSS encryption of `logins.json` via `libnss3.dll` lookup or bundled wheel
- [ ] places.sqlite direct write under transaction with safety backup

## v0.5.0 — Cross-platform
- [ ] macOS Chromium support (Keychain unwrap of master key)
- [ ] Linux Chromium support (gnome-keyring / kwallet / plain text fallback)

## Reverse direction (maybe — v1.x)
- [ ] Firefox → Chromium port (passwords via Firefox CSV export → encrypt with target's DPAPI key)
- [ ] AMO → Chrome Web Store mapping table (the inverse of the current curated map)

## Distribution
- [ ] PyInstaller --onedir bundle, signed Windows release artifact
- [ ] GitHub Actions release workflow (workflow_dispatch, builds + uploads .zip)
- [ ] Logo / banner art
- [ ] Screenshots in README (DPI-aware capture)

## Reach goals
- [ ] Browser-profile diff viewer (what'll be migrated vs. what already exists in target)
- [ ] Extension-settings best-effort (only for the small set of cross-browser extensions that share storage shape, e.g. Stylus userstyles, Bitwarden vault URL)
- [ ] Saved-card migration (Chromium `Web Data` table + DPAPI) — Firefox doesn't have a native card store, so output would be CSV only
