# V1 FREEZE REPORT — PAPER FACTORY (2026-10-02)

Freeze-Stand nach vollständigem Pilot-3-Zyklus inkl. Paperpal-Resolution,
P36-Sign-off (konditional-autorisiert, auditiert) und 16/16-Closure.

## Entscheidung zum Tag

**Kein `v1.0.0`-Tag erzeugt.** Begründung: `pyproject.toml` trägt
`version = "0.1.0"` — das Repository sieht v1.0.0 nicht eindeutig vor.
Statt Namen erfinden: Freeze-Commit + dieser Report. TODO für v1.0.0:
Maintainer-Entscheidung zur Versionserhebung, dann annotierter Tag auf den
Freeze-Commit.

## Freeze-Inhalt

- `V1_FREEZE_MANIFEST.json` — vollständige Provenance-Kette
  (manuscript/DOCX/PDF/arXiv-Tarball-SHA, U1–U16, Dispositionen, HEAD)
- `P36_SIGNOFF_RECEIPT.json` — konditional-autorisierter Sign-off
- `SHA256SUMS` im Release-Bundle (61/61 verifiziert durch Reviewer B)

## Finaler Stand (empirisch)

| Signal | Wert |
|---|---|
| Finaler Run | `complete-20261002T140940.395591Z` + Resume |
| Pipeline | 33 PASS · 4 DEGRADED · 0 FAIL · 0 HUMAN_REQUIRED · P37 NOT_RUN |
| U1–U16 | 16/16 PASS |
| Hash-Kette | manuscript→DOCX→staged→inbox→PDF→tarball: MATCH |
| Tests | 574 passed + 2 ehrliche env-Skips |
| Reviewer A/B | JA / JA (finale Runde, beide Perspektiven) |
| Paperpal | 139 v1.3.0-Vorschläge + 119 v1.3.1-Vorschläge — ALLE dispositioniert |

## Paperpal-Resolution (finale Counts, suggestions.jsonl)

| Disposition | Anzahl |
|---|---|
| APPLIED_SAFE | 6 |
| APPLIED_SEMANTICALLY_VERIFIED | 69 |
| REJECTED_NO_IMPROVEMENT | 0 |
| REJECTED_SCIENTIFIC_RISK | 38 |
| REJECTED_STYLE_ONLY | 86 |
| REJECTED_EVIDENCE_CONFLICT | 0 |
| NOT_APPLICABLE | 46 |
| **ohne Disposition** | **0** |

## Deferred MINOR/NIT (kein Blocker, getrackt in DEFERRED_HARDENING.md)

- Paperpal-Pane analysiert progressiv (Satz-Count wächst) — Capture braucht
  Stabilisierungs-Warte (im Session-Skript eingebaut)
- semantic_diff.json ist ein Marker-Artefakt (Assertion, keine Evidenz)
- pane-Aggregation schwankt (113/119/145 Karten je Lauf) — Dispositionen sind
  inhaltsbasiert dedupliziert
- UNC/`/var/`-Pfade entgehen der Abs-Path-Allowlist (Residual)
- 00README.XXX gegen arXiv-Spec nicht extern verifizierbar (offline)

## Nicht autorisiert / nicht ausgeführt

- P37 externe Submission: NICHT ausgeführt, niemals automatisch
- Push: nicht ausgeführt
