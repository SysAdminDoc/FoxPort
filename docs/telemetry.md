# FoxPort telemetry

FoxPort telemetry is off by default. It is enabled only when the user checks
the GUI setting or passes `--telemetry` on a CLI migration command.

The implementation uses Mozilla Glean with a custom `migration` ping declared
in `foxport/data/glean_pings.yaml` and metrics declared in
`foxport/data/glean_metrics.yaml`. The ping is submitted to
`https://incoming.telemetry.mozilla.org`.

## What is sent

Only aggregate run metadata is recorded:

| Metric | Type | Values |
|--------|------|--------|
| `migration.direction` | string | `forward` or `reverse` |
| `migration.surface` | string | `cli` or `gui` |
| `migration.outcome` | string | `completed`, `dry_run`, or `failed` |
| `migration.dry_run` | boolean | Whether dry-run mode was enabled |
| `migration.direct_write` | boolean | Whether any direct-write option was selected |
| `migration.selected_items` | string list | Canonical item slugs such as `passwords` or `history` |
| `migration.item_counts` | labeled quantity | Aggregate count by item slug |

The custom ping sets `include_client_id: false`.

## What is never sent

Telemetry must not include:

- filesystem paths
- source or target profile labels
- URLs, hostnames, page titles, or download filenames
- usernames, passwords, cookies, form values, card values, or extension secrets
- exception text or traceback strings

If the Glean SDK is unavailable or fails, FoxPort logs the telemetry status
and continues the migration.
