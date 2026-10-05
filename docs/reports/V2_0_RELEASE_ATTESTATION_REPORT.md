# V2 Release Attestation Report

Date: 2026-10-05

- `.github/workflows/release-attestation.yml`: on every `v*` tag, sdist+wheel
  are built in GitHub Actions and attested via `actions/attest` (minimal
  job-scoped permissions; `workflow_dispatch` runs are marked NON-RELEASE).
- First live proof: tag `v1.4.0` (2026-10-05) — workflow run succeeded, both
  artifacts verified locally with `gh attestation verify -R SKZL-AI/paper-factory`
  (Sigstore bundle, exit 0) before being attached to the GitHub release.
- Honest limits: builds are payload-identical but not bit-reproducible
  (zip/tar timestamps, measured in v1.4 WP-E); no SLSA level is claimed —
  `SLSA_BUILD_REPRODUCED` requires ≥2 independently operated build platforms.
- Historical tags v1.0.0–v1.3.0 are annotated but unsigned and stay untouched.
- The workflow is guarded by structure tests
  (tests/test_release_attestation_workflow.py) that fail on trigger,
  permission or publish tampering.
