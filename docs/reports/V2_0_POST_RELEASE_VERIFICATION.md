# V2.0.0 Post-Release Verification Receipt

Date: 2026-10-05 (UTC)
Author: autonomous release reconciliation run (advisor-directed, post-v2.0.0)

## Purpose

The tagged `V2_FREEZE_MANIFEST.json` at tag `v2.0.0` contains
`release_commit_pending: true`, because a freeze manifest created *before* the
release commit cannot, by construction, contain the hash of its own commit.
This receipt closes that pending binding **post-release**, without modifying
the immutable tag `v2.0.0`, the release commit, or any historical artifact.

This document supplements the freeze manifest; it does not supersede or
rewrite it.

## Immutable release identity

| Field | Value |
|---|---|
| Release | `v2.0.0` |
| Annotated tag object SHA | `8ca87588b00f5cc5d3dc116231b8bac88ba6d170` |
| Peeled tag commit SHA | `b3eaec340c3c446f3c61e109b25dc216dde7141d` |
| `origin/main` at verification | `b3eaec340c3c446f3c61e109b25dc216dde7141d` (identical to tag target) |
| SHA-256 of `V2_FREEZE_MANIFEST.json` (tag blob and working tree, verified identical) | `22bcdd8bff49c3790e17d429dd1481365ce678aca932812f33a9ff98e6686b0d` |
| GitHub Release URL | <https://github.com/SKZL-AI/paper-factory/releases/tag/v2.0.0> |
| CI run (main @ b3eaec3) | run id `37353010493` — conclusion: success |
| Release Attestation run (tag push) | run id `37353404390` — conclusion: success |

## Release asset verification (2026-10-05)

Both assets were downloaded fresh from the GitHub release and independently
verified against the GitHub Artifact Attestations (sigstore bundle issued by
`release-attestation.yml@refs/tags/v2.0.0`, source commit `b3eaec3...`):

| Asset | SHA-256 | `gh attestation verify` result |
|---|---|---|
| `paper_factory-2.0.0-py3-none-any.whl` | `f8459fa40af2adb07d00549744680de44646a49d2d5402b7dbcc129ef04ec53b` | PASS (exit 0) |
| `paper_factory-2.0.0.tar.gz` (sdist) | `430ccd5f7cf5ea323ddf2210c947dd1ef0dcd7248add39533b405d7b177049b2` | PASS (exit 0) |

Verification command per asset:

```bash
gh release download v2.0.0 --repo SKZL-AI/paper-factory
gh attestation verify <asset> --repo SKZL-AI/paper-factory
```

## Scope statement

- Tag `v2.0.0`, commit `b3eaec3`, and all historical release artifacts are
  unchanged; this receipt is a new post-release record only.
- Attestation proves the artifacts were produced by the release-attestation
  workflow on the tagged commit. It is **not** a SLSA-level claim and not a
  bit-reproducibility claim (payload equivalence only, as documented).
- P37 was not executed. No external submission occurred.

Machine-readable companion: `V2_0_POST_RELEASE_VERIFICATION.json`
(same directory).
