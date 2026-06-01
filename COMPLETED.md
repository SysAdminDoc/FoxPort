# FoxPort Completed Work

This file summarizes shipped roadmap history. Active work lives in `ROADMAP.md`;
release-level details live in `CHANGELOG.md`.

## v1.4.0

- Opt-in telemetry and crash reporting.
- Signed WinSparkle appcast generation.
- SLSA build provenance and CycloneDX SBOM.
- Raster branding.
- Cookies/history direct-write merge mode.
- Passkey inventory CLI.
- Restore-from-backup regret-undo wizard.
- Extension settings allowlist.
- Downloads annotations in `places.sqlite.moz_annos`.
- Curated-map hot-reload and AMO cache.

## v1.3.1 Through v1.3.3

- Audit-batch regressions and curated-map cleanup.
- Deep-audit hardening across cookies, NSS, snapshots, CLI JSON, parser
  tolerance, fileops, and GUI state.
- Trust/completeness closeout covering direct-write policy, snapshot inspect,
  HIBP tri-state, open-tabs preflight, manifest privacy redaction, and restore
  from backup.

## v1.0.0 Through v1.2.1

- Reverse Firefox-to-Chromium migration surfaces.
- Correct Firefox `places.sqlite` handling, SNSS extraction, HIBP scan, settings,
  time-range filters, path hardening, and test suite expansion.
- Cross-platform profile detection and migration for Windows, macOS, and Linux.
- CLI mode, direct NSS write, cookies/history/form autofill/search engine/card
  migration, and the five-step wizard UI.
