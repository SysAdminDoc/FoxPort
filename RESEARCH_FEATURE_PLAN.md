# Research Feature Plan

Consolidated: 2026-05-25.

`ROADMAP.md` is the single source of truth for actionable work. This file no
longer carries an independent checklist because the previous research snapshot
was stale relative to the v1.3.1, v1.3.2, v1.3.3, and early v1.4 commits.

Completed research findings have been moved into `CHANGELOG.md` and the
historical sections of `ROADMAP.md`. New research should either update the
active checklist in `ROADMAP.md` or add historical notes to `CHANGELOG.md`
when the work ships.

## Consolidation Notes

- v1.3.1 audit regressions, curated-map cleanup, and version/documentation
  drift are shipped and documented in `CHANGELOG.md`.
- v1.3.2 deep-audit hardening is shipped and documented in `CHANGELOG.md`.
- v1.3.3 trust and completeness work is shipped and documented in
  `CHANGELOG.md`.
- The stale Phase A/B/C/D research checklist has been removed from this file
  to prevent duplicate task state.
- v1.4 Downloads to `places.sqlite.moz_annos` direct-write is now shipped:
  when Downloads are selected with history direct-write `apply`, matching
  `moz_places` rows receive Firefox-compatible
  `downloads/destinationFileURI` and `downloads/metaData` annotations while
  `downloads.csv` remains the portable reference artifact.
- v1.4 Extension settings allowlist is now shipped: uBlock Origin,
  Stylus, and Bitwarden settings are exported only through explicit opt-in
  and only as allowlisted fields in `extension-settings.json`.
- v1.4 opt-in Glean telemetry is now shipped: declared metrics/pings live
  under `foxport/data/`, the GUI/CLI opt-in sends only aggregate run
  metadata, and `docs/telemetry.md` documents the never-send boundary.
- v1.4 opt-in Sentry crash reporting is now shipped: no DSN is committed;
  users must configure `FOXPORT_SENTRY_DSN`/`SENTRY_DSN`, and the wrapper
  disables locals/source context plus strips local paths before send.

## Current Process

1. Read `ROADMAP.md`.
2. Pick the next unchecked, unblocked item.
3. Implement and verify it.
4. Mark it complete in `ROADMAP.md`.
5. Record shipped behavior in `CHANGELOG.md`.
