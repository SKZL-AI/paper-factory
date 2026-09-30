# REAL PILOT 03 — MassInv Paper 1 (Draft-References-Brücke)

**Datum:** 2026-09-30 · **PF-HEAD:** `0d3cdac` · **Suite:** 421 PASS + 1 env-skip
**Run:** `complete-20260930T164840Z` (frisch, post-Fix) · vorheriger Lauf: `…T140203Z` (pre-Fix)
**Projekt:** MassInv Paper 1 — *Auditing Effective Training Configurations* (Draft v1.3.0)
**Input-Modus:** MIXED_EVIDENCE (DRAFT_ASSISTED: T4-Draft + 200 Evidence-Dateien, 4,2 MB)
**Quellen-Integrität:** 200/200 Dateien SHA-256 unverändert nach dem Lauf (Quellen read-only).

---

## 1. Was dieser Pilot testen sollte

Erster realer Lauf mit **Draft-Referenzliste statt .bib** (Markdown `## References`,
`\[N]`-Marker). Run 1 scheiterte an P32 `bib_exists` (FAIL) und P08 (0 Claims —
Paper-1-Stil „classifies/reports" matchte den Claim-Cue nicht). Beide Befunde
wurden als generische Core-Fixe gebaut (Commit `0d3cdac`, 5 adversariale
Review-Runden bis dual JA) und dieser Lauf ist ihre Feldverifikation.

## 2. Ergebnis Run 2 (post-Fix)

| Node | Run 1 (pre-Fix) | Run 2 (post-Fix) | Lesart |
|---|---|---|---|
| P08 Claims | DEGRADED (0 Claims) | DEGRADED (**10 Claims**, alle unbound) | Extraktion wirkt; Paper 1 macht Klassifikations-Claims ohne Metrik-Bindung — ehrlich |
| P15 References | — | PASS (21 kept) | Derived-Bib-Brücke trägt |
| P21 Citation Audit | DEGRADED (kein Audit) | DEGRADED (**21 Entries: 12 VERIFIED, 9 UNVERIFIABLE_T4**) | echte Verifikation via DOI + arXiv-DataCite-Synthese |
| P32 Venue | **FAIL bib_exists** | **PASS** | Befund geschlossen |
| P27 Remediation | DEGRADED | DEGRADED (10 RESOLVED / 9 UNRESOLVED / 2 deferred) | GAP-004-konform, finding-spezifisch |
| P31 Paperpal | HUMAN_REQUIRED | HUMAN_REQUIRED | manuelle Bridge, Outbox wartet |
| P33–P37 | SKIPPED | SKIPPED_DEPENDENCY | Release-Lane hinter Human-Gate (designed) |
| **overall** | FAILED | **HUMAN_REQUIRED** (exit 3) | ehrlicher Endzustand |

### Citation Audit im Detail

- 21 Draft-Referenzen geparsed (`literature/parsed_from_draft.bib`, T4-markiert).
- **12 VERIFIED** gegen Crossref/OpenAlex — davon der arXiv-Anteil über
  synthetisierte DataCite-DOIs (`10.48550/arXiv.<id>`, versionslos).
- **9 UNVERIFIABLE_T4 (MAJOR)**: weder DOI noch arXiv-ID → nicht maschinell
  verifizierbar. Remediation (`drop_unverifiable_citation`) bleibt ehrlich
  UNRESOLVED, weil der T4-Draft die Einträge bei jedem Rebuild erneut liefert —
  eine Autoren-Entscheidung (DOIs nachliefern oder Refs streichen), kein
  Automatismus.

### Claims / Remediation (GAP-004-Semantik)

- 10 Claims extrahiert (Mess-/Audit-Rhetorik: „classifies 766,771,200 …").
- Alle 10 ohne deterministische Metric-Bindung → UNSUPPORTED →
  finding-spezifisch retiriert (`retire_bound_claims`, alle RESOLVED).
- 2 deferred: Draft-Zahl `7.4` (number_mismatch) benötigt allowed writer —
  U15 verbietet Auto-Edit des T4-Drafts. Ehrlich offen.

### Integrity / Statistik

- P05 integrity_audit: 5 Findings (4× unverifiable_number MINOR, 1×
  number_mismatch) — unverändert zu Run 1, bekannte Draft-Prosa-Zahlen.
- P09: 146 Metriken aus 10 Quellen (GAP-012-Multi-Source-Discovery trägt).

## 3. HUMAN_REQUIRED (unverändert offen)

1. **Paperpal (P31):** `paperpal/outbox/main.tex` manuell in Paperpal Web
   prüfen, Ergebnis in `inbox/` legen, dann `paper-factory … complete --resume`.
2. **9 Draft-Referenzen:** DOIs/arXiv-IDs nachliefern oder aus dem Draft
   entfernen (Autoren-Entscheidung).
3. **Draft-Zahl 7.4:** redaktionelle Korrektur durch den Autor (U15).
4. **P36:** final sign-off — nicht erreicht (hinter P31).

## 4. Neue Beobachtungen (kein Core-Fix ohne Reproduktion)

- **GAP-P3-obs1 (A, projektspezifisch):** 9/21 Referenzen ohne verifizierbaren
  Identifier — Eigenschaft des Drafts, nicht des Systems.
- **GAP-P3-obs2 (A):** `drop_unverifiable_citation` ist gegen eine
  draft-regenerierte Bib strukturell wirkungslos — die Disposition UNRESOLVED
  ist das korrekte Endstadium; dokumentiert, kein Fix.
- **GAP-P3-obs3 (B, beobachtet):** number_mismatch an T4-Drafts kann ohne
  allowed-writer-Pfad nicht auto-remediiert werden (U15) — by design.

## 5. Verifikation dieses Berichts

- Run-Artefakte: `pilots/pilot-03-massinv-paper1/project/.paper-factory/`
  (runs.sqlite, reports/*, claims/claims.yaml).
- Suite: 421 passed + 1 ehrlicher env-SKIP (HoH-Receipt, umgebungsbedingt).
- Quellen-Hash-Check: 200/200 unverändert (`source_inventory.json`).
- Dashboard: Sektion 13 (REAL PILOT 03) in `dashboard/index.html`.

**Endzustand: ehrliches HUMAN_REQUIRED — das System unterscheidet sauber
zwischen verifiziert (12 Refs), unverifizierbar (9 Refs, MAJOR),
menschenpflichtig (Paperpal, Autoren-Entscheidungen) und blockiert die
Release-Lane genau dort.**
