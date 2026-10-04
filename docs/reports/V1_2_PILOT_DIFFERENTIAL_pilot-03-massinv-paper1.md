# Pilot Differential — pilot-03-massinv-paper1 (v1.2 WP7, Phase 12)

- Workspace: `pilots/pilot-03-massinv-paper1/project/.paper-factory` (read-only, sqlite mode=ro)
- Run: `complete-20261002T143931.928898Z` of 16 recorded run(s), created 2026-10-02T14:39:31.934745Z
- Generated: 2026-10-04T18:38:47.247764+00:00

## Method & Limitation

Differential computed from stored pilot state only (runs.sqlite + receipt tree), read-only. No live HoH replay was executed (plan §5 Abweichung 2, quota discipline); the VH side is therefore UNAVAILABLE/PROVIDER_UNAVAILABLE wherever no HoH receipt was persisted historically. Semantic equivalence is N/A in that case — it is a documented gap, not a PASS.

Cost: not measurable offline — no live HoH replay was run (quota discipline); live cost evidence remains reserved for scripts/run_live_hoh.py.

## Node Differential

| Node | Native verdict | VH verdict | Semantic equivalence | Outcome | Mismatches | Timing (s) |
|---|---|---|---|---|---|---|
| P00 | DEGRADED | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P01 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P02 | DEGRADED | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P03 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P04 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P05 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P06 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P07 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P08 | DEGRADED | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P09 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P10 | DEGRADED | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P11 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P12 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P13 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P14 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P15 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P16 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P17 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P18 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P19 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P20 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P21 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P22 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P23 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P24 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P25 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P26 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P27 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P28 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P29 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P30 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P31 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P32 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P33 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P34 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P35 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P36 | PASS | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |
| P37 | NOT_RUN | UNAVAILABLE (no stored receipt) | N/A | PROVIDER_UNAVAILABLE | — | 0.0 |

## Verdict Distribution (native)

- DEGRADED: 4
- NOT_RUN: 1
- PASS: 33

## Degraded States (native DEGRADED)

P00, P02, P08, P10

## Mismatches

none — with the honest caveat that the VH side is UNAVAILABLE for every node without a stored HoH receipt (see Limitation), so no native↔VH mismatch can exist in this dataset by construction.

## Notes

- Resolution policy for historical data: documented, never resolved post-hoc.
- Live HoH replay (with real cost/timing evidence) is reserved for the explicit live path `scripts/run_live_hoh.py` and is not part of this acceptance gate.
