# Supply-chain artifacts

Every FoxPort release publishes two integrity artifacts on top of the
Windows ZIP:

* a **CycloneDX SBOM** describing the pinned Python dependency tree, and
* a **SLSA build provenance attestation** signed via GitHub OIDC +
  Sigstore (Rekor).

These let you confirm two independent things before you run a downloaded
build: *what is inside* (SBOM) and *where it came from* (attestation).

## CycloneDX SBOM

The release workflow runs `cyclonedx-py` against `requirements.txt` and
attaches `FoxPort-<tag>-sbom.cdx.json` to the GitHub release. The SBOM
follows the [CycloneDX 1.6 spec](https://cyclonedx.org/specification/overview/)
and lists every direct dependency that ships inside the PyInstaller
bundle with its pinned version and PURL identifier.

To inspect the components:

```bash
jq '.components[] | {name,version,purl}' FoxPort-v1.4.0-sbom.cdx.json
```

To scan the SBOM against the public vulnerability databases, point any
CycloneDX-aware scanner at it, e.g.:

```bash
# OSV-Scanner — https://github.com/google/osv-scanner
osv-scanner sbom FoxPort-v1.4.0-sbom.cdx.json

# Grype — https://github.com/anchore/grype
grype sbom:FoxPort-v1.4.0-sbom.cdx.json
```

A failing scan does not necessarily mean the build is compromised; many
results are unreachable advisories. Treat it as an audit aid, not a
gate.

## Build provenance

The release workflow asks GitHub Actions for a short-lived OIDC token
and uses [`actions/attest-build-provenance`](https://github.com/actions/attest-build-provenance)
to mint a SLSA v1 build provenance statement covering both the Windows
ZIP and the SBOM. The signature is recorded in the public Rekor
transparency log; the attestation bundle is stored on the FoxPort
repository's attestations API.

To verify a downloaded ZIP:

```bash
gh attestation verify FoxPort-v1.4.0-windows-x64.zip \
    --owner SysAdminDoc \
    --repo SysAdminDoc/FoxPort
```

`gh` must be 2.49 or newer (earlier releases lack `attestation verify`).
The command fetches the matching attestation, checks the Sigstore
certificate chain back to Fulcio, confirms the Rekor entry, and asserts
that the artifact's SHA-256 matches what GitHub Actions signed.

A successful verification proves:

* the ZIP was built by `.github/workflows/release.yml` on this repo,
* the commit, workflow file, and runner identity at the time of build,
* the artifact has not been modified since the workflow signed it.

Verification does **not** prove the source tree is free of malice —
review the build commit and the workflow file before trusting an
attestation in production.

## Why this matters

FoxPort decrypts every password in your Chromium profile. A
compromised release could exfiltrate those secrets. SBOM + provenance
attestation lets a security-conscious user answer two questions
mechanically — without needing to trust GitHub's web UI or any
mirror — before running the binary:

1. Did this exact file come out of FoxPort's release pipeline?
2. What third-party code is sitting in the bundle?

The pair is cheap to publish and easy to verify; we strongly
encourage you to run both checks on any release before importing real
profile data.
