# REAL PILOT 01 — Kandidatenbewertung

Scouting: 2026-09-22, read-only, kein Schreibzugriff auf irgendeine Quelle.
Bewertung ausschließlich nach: Evidence completeness · Scope · Input diversity ·
Reproducibility · Usefulness als PF-Stress-Test. Keine wissenschaftliche
Qualitätsrangliste.

## Kandidat 1: MassInv Paper A (arXiv-Submission-Bundle) — GEWÄHLT

- Root: `/home/sai/sai/wt-massinv/paper_arxiv/ARXIV_SUBMISSION_PAPER_A_v1.2.5/` (~1,3 MB)
  + Evidenz-Overlay `/home/sai/sai/wt-massinv/r_analysis_013/` (~26 MB)
- Inventar (verifiziert): komplette LaTeX-Quelle (`main.tex`, sections),
  `references.bib`, Figuren (PDF+PNG) **mit Generierungs-Code**, kompiliertes PDF,
  `AI_USE_DISCLOSURE.md`; daneben im Worktree: `CLAIM_INVENTORY_v1.csv`
  (Claims mit VERIFIED/REPLICATED/FAILED/CONFOUNDED/retrahiert — Ground Truth!),
  `evidence_v2/`, sha256-Provenienz-Manifeste, Peer-Review-Simulationen,
  ~60 Handoff-/Status-Dokumente, Git-Worktree mit 138 Commits.
- Evidence completeness: hoch (Analyse-Ebene; rohe GPU-Trainingsläufe nicht im Repo)
- Scope: begrenzbar (ein Paper, eine gepinnte Version)
- Input diversity: sehr hoch (tex/bib/py/csv/json/Reviews/Handoffs)
- Reproducibility: partiell (Analyse + Figuren reproduzierbar, Training nicht)
- PF-Stress-Test: **exzellent** — einziger Kandidat mit benotbarem Ground Truth
  inkl. retrahierter Falschclaims und hash-gepinnter Evidenzkette
- Input-Modus: MIXED_EVIDENCE (DRAFT_ASSISTED + Code + Daten)
- Risiken: Paper ist submission-poliert (PF verifiziert eher als konstruiert);
  Scope-Disziplin nötig (viele Versionen im selben Archiv)

## Kandidat 2: VeriHarness/HoH Positionspapier

- Root: `/home/sai/hoh/paper/POSITION_PAPER.md` (+ CLAIMS.json, runs/-Receipts 8,7 GB)
- Stärken: CLAIMS.json + eigener Checker, sehr hohe Evidence completeness
- Schwächen als Pilot 1: **Befangenheit** (VeriHarness ist PF-Laufzeit-Infra,
  Gap-Report existiert schon), kein LaTeX/.bib (Paper-Teilpfade ungetestet),
  Positionspapier statt empirischem Experiment
- Input-Modus: MIXED_EVIDENCE mit CODE_ONLY-Einschlag — als **Pilot 2** sinnvoll

## Kandidat 3: MassInv-Reopening GK-Programm (SOURCE_PACKAGES)

- Root: `/home/sai/sai/wt-massinv/massinv_reopening/`
- Stärken: Preregs, Gate-Artefakte mit Selftests/Pins, Ledger mit Errata
- Schwächen: **kein Paper-Draft, keine .bib** — Produkt sind Gate-Verdikte,
  kein Manuskript; testet nicht das volle PF-Profil
- Input-Modus: DATA_ONLY — eher Evidenz-Anhang zu Kandidat 1

## Entscheidung (autonom, eindeutig)

**Kandidat 1 — MassInv Paper A v1.2.5** mit Evidenz-Overlay r_analysis_013.

Begründung: einziger Kandidat mit extern benotbarem Ground Truth (retrahierte
Claims EX-05/EX-06/EX-13 müssen von PF erkannt werden), vollständiger
Paper-Form (tex/bib/Figuren/PDF) und hash-gepinnter Evidenz. Kein
Scope-/IP-Konflikt, daher keine HUMAN_REQUIRED-Eskalation.

**Blind-Test-Design:** `CLAIM_INVENTORY_v1.csv` (Ground Truth) wird NICHT in
den PF-Input kopiert — PF rekonstruiert claims blind aus Draft + Evidenz;
der Abgleich erfolgt extern im Pilot-Report. PF-interne Config: `hoh_nodes: []`
(HoH-Live-Beweis existiert bereits, PF-e05758a3-P05; Pilot 1 bleibt
deterministisch und quota-schonend). Literaturprüfung läuft ONLINE
(Crossref/OpenAlex), Netzfehler werden ehrlich klassifiziert.
