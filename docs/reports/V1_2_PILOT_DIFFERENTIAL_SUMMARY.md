# Pilot Differential — Summary (v1.2 WP7, Phase 12)

Generated: 2026-10-04T18:12:47.200026+00:00

Offline differential over stored pilot state only — no live HoH replays, no network, no LLM calls (plan §5 Abweichung 2, quota discipline). Per-pilot details: `V1_2_PILOT_DIFFERENTIAL_<pilot>.md`.

| Pilot | Run | Nodes | Native PASS | Native DEGRADED | Native FAIL/other | Stored HoH receipts | Shadow receipts | Mismatches | Outcome distribution |
|---|---|---|---|---|---|---|---|---|---|
| pilot-03-massinv-paper1 | complete-20261002T143931.928898Z | 38 | 33 | 4 | 1 | 0 | 0 | 0 | PROVIDER_UNAVAILABLE:38 |
| real-pilot-01-rerun | complete-20260925T162928Z | 38 | 31 | 5 | 2 | 0 | 0 | 0 | PROVIDER_UNAVAILABLE:38 |

## Headline Limitation

Differential computed from stored pilot state only (runs.sqlite + receipt tree), read-only. No live HoH replay was executed (plan §5 Abweichung 2, quota discipline); the VH side is therefore UNAVAILABLE/PROVIDER_UNAVAILABLE wherever no HoH receipt was persisted historically. Semantic equivalence is N/A in that case — it is a documented gap, not a PASS.

Cost was not measurable for any pilot (offline reconstruction from stored state; live cost evidence requires the explicit live path `scripts/run_live_hoh.py`).

## Reading Guide

- `PROVIDER_UNAVAILABLE` rows mean: the pilot ran without persisting any HoH result for that node, and this WP deliberately did not re-run HoH. It is a documented gap (Phase-12 acceptance under §5 Abweichung 2), not a PASS.
- `MATCH`/`SEMANTIC_MATCH`/`MISMATCH`/`INCOMPARABLE` rows would appear for nodes with stored `hoh_verdict` receipts and are produced by `verification.shadow.compare`.
