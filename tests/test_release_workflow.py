"""Regression tests for the release workflow YAML.

These tests pin the supply-chain wiring (SBOM generation + SLSA build
provenance attestation) in `.github/workflows/release.yml` so a future
edit that accidentally drops the steps or downgrades the permissions
trips a fast CI signal rather than silently shipping an un-attested
release.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "release.yml"
)


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_release_workflow_grants_oidc_and_attestations_permissions():
    """`actions/attest-build-provenance` needs id-token + attestations writes."""
    perms = _workflow()["permissions"]
    assert perms.get("id-token") == "write", (
        "OIDC token write permission is required for keyless Sigstore signing"
    )
    assert perms.get("attestations") == "write", (
        "attestations write permission is required to store the attestation"
    )
    assert perms.get("contents") == "write", (
        "release upload still needs contents:write"
    )


def test_release_workflow_generates_cyclonedx_sbom():
    """SBOM step must use cyclonedx-bom against requirements.txt."""
    steps = _workflow()["jobs"]["windows"]["steps"]
    sbom_steps = [s for s in steps if s.get("name", "").startswith("Generate CycloneDX SBOM")]
    assert len(sbom_steps) == 1, "expected exactly one SBOM generation step"
    body = sbom_steps[0]["run"]
    assert "cyclonedx-bom" in body, "SBOM step must install cyclonedx-bom"
    assert "cyclonedx-py" in body, "SBOM step must invoke cyclonedx-py"
    assert "requirements.txt" in body, "SBOM input is the pinned requirements.txt"
    assert "SBOM_NAME=" in body, "SBOM step must export SBOM_NAME for downstream steps"


def test_release_workflow_attests_build_provenance():
    """SLSA provenance step must cover both the ZIP and the SBOM."""
    steps = _workflow()["jobs"]["windows"]["steps"]
    attest = [s for s in steps if str(s.get("uses", "")).startswith("actions/attest-build-provenance@")]
    assert len(attest) == 1, "expected exactly one attest-build-provenance step"
    subjects = attest[0]["with"]["subject-path"]
    # multi-line YAML string of paths
    assert "ZIP_NAME" in subjects, "attestation must cover the release ZIP"
    assert "SBOM_NAME" in subjects, "attestation must cover the SBOM"


def test_release_workflow_uploads_sbom_as_release_asset():
    """SBOM ships next to the ZIP on the GitHub release."""
    steps = _workflow()["jobs"]["windows"]["steps"]
    create = [s for s in steps if s.get("name", "") == "Create GitHub release"]
    assert len(create) == 1
    body = create[0]["run"]
    assert "SBOM_NAME" in body, "release step must append the SBOM to its asset list"


def test_release_workflow_uploads_sbom_in_actions_artifact():
    """The actions/upload-artifact step also keeps the SBOM for CI runs."""
    steps = _workflow()["jobs"]["windows"]["steps"]
    upload = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert upload, "expected actions/upload-artifact step"
    paths = upload[0]["with"]["path"]
    assert "SBOM_NAME" in paths, "SBOM must be in the workflow artifact bundle"
