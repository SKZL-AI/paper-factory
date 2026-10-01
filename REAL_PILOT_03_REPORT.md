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

---

# ADDENDUM 2026-10-01 — Citation-Remediation + Identity-Rerun (Commit 6ce6bbf)

Ersetzt die obigen Abschnitte nicht; korrigiert/ergänzt sie (Korrektur-Provenance).

## Auslöser

Der Nutzer hat die 3 offenen Autoren-Aufgaben (Referenzen, 7.4-Entscheidung,
Pipeline-Lauf) explizit an die Maschine delegiert: „solltest du nicht schritt 1
selber machen — und ich ueberpruefe dann zum schluss redundant". Ausführung mit
Beweispflicht.

## Was geschah

1. **7 Referenzen feldverifiziert und mit arXiv-IDs versehen.** Jede ID wurde
   VOR dem Edit live gegen die DataCite-API (`10.48550/arXiv.<id>`) aufgelöst;
   Registry-Titel + Erstautoren stimmten exakt mit der Draft-Referenz
   überein: [1]→2103.03098, [3]→2110.02861, [4]→1911.11134, [5]→2101.03961,
   [12]→1711.05101, [16]→2003.12206, [20]→1706.03762. Venue-URLs bleiben als
   „Published version:" erhalten. Changelog: `draft/CHANGELOG_PAPER1_v1.3.1.txt`.
2. **Draft-Zahl 7.4 gegen Rohdaten bewiesen, Draft unverändert.** Sealed
   T0-Artefakt `evidence/r_analysis_013/next_blocks/V13_D2048_SELFTEST.json`
   (sha256 `a757067e98d4cef2d38581ece008ca19e05e8f6501d1148c4afd1fdfa740b18b`,
   green, 16/16 Checks) enthält exakt die Draft-Werte: p_nogmix=40960,
   p_gmix_layer=303104, p_gmix_extra=262144, p_ref=163840, ratio=**7.4**,
   frac=5/13. Arithmetik: 303104/40960 = 7.39843750 ≈ 7.4 — der Draft-Wert ist
   der gerundete Wert des Artefakts selbst. Der number_mismatch war ein
   Metric-Bindungs-False-Positive (Ratio liegt in sealed JSON, nicht in den
   CSV/SQLite-Metrikquellen). Disposition: AUTHOR_DECISION mit Beweiskette,
   GAP-010-Dedupe auf die P24/P25-Duplikate propagiert. U15 eingehalten
   (kein Auto-Edit des Manuskripts).
3. **Core-Gap gefunden und gefixt (GAP-P3-obs4, Klasse B).** Der
   Identity-Check (151f8f5) war nach dem Pilot-3-Lauf entstanden und mit dem
   Parser-Junk der Draft-Referenz-Brücke nicht komponiert: ein frischer Lauf
   hätte ALLE 12 bereits verifizierten Referenzen als CRITICAL
   identity_mismatch geflaggt (direkte Probe: 12/12 False). Fix:
   `_clean_title()` in `draft_refs.py` + `x-pf-title-cut`-Flag +
   Prefix-Downgrade-Regel in `verify.py`. Dual adversarial review: A NEIN
   (B1–B5) → Härtung → A JA, B JA. Tests 458 → 475 (+17).
4. **Frischer complete-Lauf** (`complete-20261001T141031.192588Z`):
   **19/21 Referenzen VERIFIED mit identity_check=match** (darunter alle 12
   zuvor verifizierten, exakte Normalform-Gleichheit — kein Prefix-Match).
   Verbleibend UNVERIFIABLE_T4 (MAJOR): PyTorch-Adam-Doku [17] und W3C
   PROV-DM [21] — für beide existiert kein DOI; sie bleiben legitime
   URL-Zitate und offene Autoren-Entscheidung (behalten/streichen).
   P-Status unverändert: 26 PASS / 6 DEGRADED / 1 HUMAN_REQUIRED (P31
   Paperpal) / 5 SKIPPED (Release-Lane hinter P31, designed).

## Verbleibende HUMAN_REQUIRED (projektspezifisch, keine Core-Fehler)

- P31 Paperpal (Automatisierung via Word-Add-in in Umsetzung — Recon
  2026-10-01: Word 16.0 COM aus WSL ✓, Paperpal-Ribbon-Tab ✓, Pane mit
  Prime-Login ✓)
- 2 DOI-lose Referenzen: Autor entscheidet behalten/streichen
- P36 Sign-off

## Verifikation dieses Addendums

- Suite: 475 passed + 1 ehrlicher env-SKIP.
- citation_audit_final.json (2026-10-01T14:12Z): 19× VERIFIED/match,
  2× UNVERIFIABLE_T4, 0 CRITICAL.
- Dashboard: Sektion 13 aktualisiert (run_id, headline, gaps).
