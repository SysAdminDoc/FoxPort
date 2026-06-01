# FoxPort Research Report

This is the canonical research summary. The full pre-consolidation feature plan
is archived at `docs/archive/research/RESEARCH_FEATURE_PLAN.md`.

## Current Findings

- `ROADMAP.md` is the single actionable checklist; the prior research plan is
  historical and should not carry independent task state.
- v1.3.1 through v1.4 converted most trust, completeness, telemetry, crash,
  appcast, passkey inventory, direct-write merge, and release-provenance work
  into shipped behavior.
- Remaining distribution gates are largely external: Authenticode cert, signed
  ABE-sidecar verification after the first signed release, and macOS developer
  ID/notarization.
- Speculative items such as CDP fallback, curated-map auto-PR generation, and
  fresh screenshot capture should stay gated on real need or real telemetry.

## Archive Use

- `RESEARCH_FEATURE_PLAN.md` preserves the 2026-05-25 post-v1.3 research
  consolidation notes and shipped-plan context.
