# Paper Factory — Project Completion Report

Date: 2026-10-06 (UTC)
Status: **PROJECT_COMPLETE** · Operating mode: **MAINTENANCE**

## Released product

| Field | Value |
|---|---|
| Released version | **v2.0.0** (published GitHub Release, not draft) |
| Release commit | `b3eaec340c3c446f3c61e109b25dc216dde7141d` |
| Annotated tag object | `8ca87588b00f5cc5d3dc116231b8bac88ba6d170` (immutable, never moved) |
| Post-release reconciliation | `461aec7` + `f5bd0f9` (freeze-binding receipt, PROV-JSON correction with correction-provenance) |
| Final project HEAD | `f5bd0f94652c9c8f79c4abab6a4d57281bddadb6` (== `origin/main`) |
| GitHub Release | <https://github.com/SKZL-AI/paper-factory/releases/tag/v2.0.0> |

## Evidence chain

| Gate | Result |
|---|---|
| CI on final HEAD `f5bd0f9` | **success** (run `37367561591`; an earlier failure was a GitHub hosted-runner acquisition flake on the py3.12 job, resolved by rerun — no code change) |
| Test suite | 1070 passed + 4 honest skips (2 environment, 2 local-only conformance) |
| Wheel attestation (`paper_factory-2.0.0-py3-none-any.whl`, sha256 `f8459fa4…04ec53b`) | **PASS** (`gh attestation verify`, sigstore bundle from `release-attestation.yml@refs/tags/v2.0.0`) |
| sdist attestation (`paper_factory-2.0.0.tar.gz`, sha256 `430ccd5f…177049b2`) | **PASS** |
| Freeze-binding receipt | `docs/reports/V2_0_POST_RELEASE_VERIFICATION.{md,json}` — closes the freeze manifest's `release_commit_pending` binding post-release without touching the immutable tag |
| Provenance correction | PROV-JSON correctly labelled W3C Working Group Note (NOTE-prov-json-20130430), not a Recommendation; old claim preserved via correction note |
| CWL | v1.2 CommandLineTool **export/interchange only — no CWL execution backend** (implemented: local, Snakemake, Nextflow reproduction backends) |
| Reviewer A/B (all release gates) | JA/JA |

## Scientific control integrity

- P00–P37 ownership: **Paper Factory** (control plane) — unchanged
- U1–U16 global closure: **Paper Factory** — unchanged
- VeriHarness = verification plane, Herdr = runtime plane; neither can set closure
- Provenance firewall, evidence authority: intact
- **P37: NOT EXECUTED. External paper submission: NO.**

## Findings

- OPEN CRITICAL: **0**
- OPEN MAJOR: **0**
- Deferred MINOR/NIT: tracked in `docs/reports/DEFERRED_HARDENING.md`

### Deferred-item classification (2026-10-06)

| Item | Classification |
|---|---|
| PaperQA2 literature provider (no real consumer) | VALID_DEFERRED_MAINTENANCE |
| ReproZip-style system capture | VALID_DEFERRED_MAINTENANCE |
| Herdr upstream 5 s dispatch-stall window + Claude folder-trust dialog | VALID_DEFERRED_MAINTENANCE (upstream) |
| CWL execution backend | REJECT_NO_CURRENT_NEED |
| `ExecutionReceipt` name collision (bound to schema_version=2 trigger) | VALID_DEFERRED_MAINTENANCE |
| Provider SDK without multiple real consumers | REJECT_NO_CURRENT_NEED |
| Flowcept / AI Scientist | REJECT_NO_CURRENT_NEED |
| Manubot / showyourwork | SUPERSEDED / no current need |
| System-wide inode pressure outside Paper Factory | OUTSIDE_PAPER_FACTORY_SCOPE |

No item blocks project completion: no reproducible defect exists in the
current Paper Factory state.

## Redundant backup (`/mnt/e/paper-factory/backups/`)

| Artifact | SHA-256 |
|---|---|
| `2026-10-05T204218Z_f5bd0f9_full.tar` (full repo incl. `.git`, 13,993 entries, verified: freeze-manifest sha256 `22bcdd8b…` matches tag) | `b04c937fc4bef0f7fa2e43d9714c0e0654887383eaddb8944c5e78b50bff1e00` |
| `2026-10-05T204218Z_v2-conformance-scratch.tar` (untracked migration-test scratch, archived before worktree removal) | `4b346bf888ee191a9bf86f06e9248910c5c05baef327fd8c2022987872e5c00a` |
| Final git-bundle snapshot + manifest | see `BACKUP_MANIFEST_2026-10-06_PROJECT_COMPLETE.md` |

The aborted partial rsync (`…incomplete-rsync-aborted`) is marked as such
and superseded by the verified tar.

## Maintenance policy

From this point Paper Factory receives only:

1. genuine bug fixes,
2. security / supply-chain fixes,
3. compatibility fixes,
4. evidenced scientific-integrity fixes,
5. explicitly authorized new development cycles.

No automatic revival of earlier wish lists or research roadmaps.

Machine-readable companion: `PROJECT_COMPLETION_2026-10-06.json`.
