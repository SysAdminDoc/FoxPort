# FoxPort crash reporting

Crash reporting is off by default. It is enabled only when the user opts in
and a Sentry DSN is configured with `FOXPORT_SENTRY_DSN` or `SENTRY_DSN`.

The implementation uses `sentry-sdk` for unhandled Python exceptions. FoxPort
does not enable Sentry's default integrations; it installs its own
`sys.excepthook` and `threading.excepthook` after initialization so command
line arguments, logs, modules, and framework integrations are not collected by
default.

## Local scrubbing

Before an event can leave the machine, `foxport.crash_reporting.before_send`
removes:

- `user`
- `request`
- `server_name`
- `modules`
- device context
- stack frame locals
- source pre/post/context lines

It also replaces Windows, UNC, and common POSIX absolute paths with
`<path>/<filename>` placeholders. `include_local_variables` and
`include_source_context` are disabled at SDK initialization as a second guard.

## Runtime status

If the user opts in without a DSN or without `sentry-sdk` installed, startup
continues and reports the crash-reporting status as unavailable. Migration
manifests record the configured Sentry host under `network`.
