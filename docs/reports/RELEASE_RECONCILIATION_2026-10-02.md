# RELEASE RECONCILIATION — Pilot 3 (MassInv Paper 1), 2026-10-02

Finaler Stand nach dem Post-Pilot-Integrity-Audit (Berater-Auftrag) + arXiv-Look-Ausbau.

## Artefakt-Kette (empirisch belegt, dieser Run)

```
draft/paper1_v1_3_0.md        60960422…  (manuscript, T4-Quelle, unverändert)
  └─ docx_outbox provenance   60960422…  (source sha match ✓)
  └─ paper-20261002T083441149732Z.docx
       file = recorded = P31 state = inbox binding
       3a2f3575… = 3a2f3575… = 3a2f3575… = 3a2f3575…  ✓ MATCH
  └─ Paperpal Word-Add-in (CDP, mausfrei, capture-only)
       Grammar: 145 Karten (Pane: 159 suggestions / 117 Sätze)
       Klassen: 110 SEMANTICALLY_GUARDED · 35 SCIENTIFIC_OR_AMBIGUOUS · 0 applied
       Consistency: clean ("No consistency issues found!")
```

## Node-Ergebnisse (run complete-20261002T085501.571637Z)

- P21 PASS — Zitations-Audit + danach Bib-Rebuild: **19/21 Einträge aus
  Registry-verifizierten Metadaten neu geschrieben** (Autoren/Jahr aus
  Crossref/OpenAlex/DataCite); 2 URL-Einträge (PyTorch, W3C) bleiben
  VERIFIED_AUTHORITATIVE_URL ohne Autoren-Rewrite
- P31 PASS — evidence_class external_paperpal_declared, artifact_binding **exact**
- P32 PASS (venue) · P33 PASS (clean export + secret scan)
- P34 PASS — scaffold-Rebuild + arXiv-Paket: `arxiv-massinv_paper1.tar.gz`
  (825 195 bytes, sha256 90c437f6…): Comment-Strip, 00README.XXX, .bbl,
  Dateinamen-/Abs-Pfad-Checks, **Untar-Rebuild-Simulation OK**,
  pdffonts: alle Fonts embedded
- P35 PASS — **U1–U16 16/16**
- P36 HUMAN_REQUIRED (einziger Human-Gate, designed) · P37 SKIPPED (nie automatisch)
- Summary: 32 PASS · 4 DEGRADED (P00 latexmk optional, P02 keine Chats by policy,
  P08 Paper-1 hat keine Metric-Claims, P10) · 0 FAIL

## Gefixte Release-Blocker heute

1. **P31 stale-evidence false-green** (empirisch bestätigt: Inbox bindet an
   a155…, aktuell war 8774…, P31 meldete PASS) → exact-artifact-Bindung +
   U9/U16-On-Disk-Revalidation + Render-Reuse + Ledger-Anker
2. **durable-decision false-close** (claim_refs-Kollision) → statement_hash-
   Diskriminator + fail-closed Legacy-Migration (kein Receipt-Shadowing)
3. **Bib-Qualität**: falsche Jahre (1911/1910/2012) + verstümmelte Autoren +
   interne Notiz im PDF → Registry-Upgrade + Note-Strip im Shipped-Bib +
   draft_refs-Jahrfix (URL-Zone ausgeschlossen, eprint-YYMM-Fallback)
4. **P21/P15-Reihenfolge**: Bib-Build las das Vor-Run-Audit → P21 = audit→build
5. **bibtex openout_any=p** (absoluter Pfad → keine .bbl) → cwd=build+BIBINPUTS
6. **NFC-Normalisierung** (kombinierende Unicode-Marks brachen pdflatex)
7. Stripper-/Packaging-Härtung (verbatim*/lstlisting, Single-Line, Kommentar-
   Marker-Falle, Symlink-Verbot, paper.id, URL-False-Positive, /tmp-Allowlist)

## Reviewer-Gates heute

- Phase 0 (Integrity): A JA (R3), B JA (R4) — 5 B-Runden, 4 A-Runden
- Phase 1/2 (arXiv): A JA (R2, Auflage: Bib-Rebuild vor Release — erledigt),
  B JA (R4; R3-MAJ-1 durch Empirie widerlegt)
- Suite: **556 passed + 2 ehrliche env-Skips** (Live-Netz opt-in, HoH-Receipt)

## Deliverables

- Anschau-PDF: `pilots/pilot-03-massinv-paper1/project/.paper-factory/release/massinv_paper1/build_arxiv/main.pdf` (16 S., arXiv-Look: Times, natbib num, TikZ-Vektorfiguren fig1/fig2)
- arXiv-Upload: `…/release/massinv_paper1/arxiv-massinv_paper1.tar.gz`
- Mirror: `<MIRROR_ROOT>/PROJEKTE/Paper_factory/RESULTS_2026-10-02/`

## Offen (HUMAN_REQUIRED, projektspezifisch — keine Core-Fehler)

1. **P36 final sign-off** — danach wäre P37 (externe Submission) möglich,
   niemals automatisch
2. 145 Paperpal-Vorschläge zur Autor-Review (35 SCIENTIFIC_OR_AMBIGUOUS —
   niemals auto-applizieren); SAFE_MECHANICAL-Auto-Apply ist Roadmap-Item 8
   (ROADMAP_AUTONOMY.md) hinter dem Semantic-Diff-Gate
3. Kosmetik: doppelte Figure-Caption im gerenderten PDF ("Figure 1: Figure 1:")
   — Draft trägt Caption im Alt-Text + Pandoc; kein Inhaltsfehler
