# WinSparkle appcast

FoxPort does not perform update checks yet. The release pipeline can now
publish a signed WinSparkle-compatible `appcast.xml` for a future opt-in
update checker.

## Signing key

Create an Ed25519 signing key with WinSparkle's `winsparkle-tool generate-key`
or another Ed25519-capable tool. Store the private key as the GitHub Actions
secret `WINSPARKLE_EDDSA_PRIVATE_KEY_BASE64`.

The secret may be either:

- base64 of a PEM-encoded Ed25519 private key
- base64 of the raw 32-byte Ed25519 private seed

The matching public key must be compiled into any future WinSparkle-enabled
FoxPort build, either through a Windows resource or the WinSparkle API.

## Release output

When the secret is present, `.github/workflows/release.yml` runs
`scripts/generate_winsparkle_appcast.py` after the Windows zip is created.
The generated appcast contains:

- release title and notes URL
- `sparkle:version`
- `sparkle:shortVersionString`
- `sparkle:os="windows"`
- zip `length`
- `sparkle:edSignature` over the exact zip bytes attached to the release

When the secret is absent, the workflow skips appcast generation and still
publishes the normal Windows zip and SHA-256 sidecar.
