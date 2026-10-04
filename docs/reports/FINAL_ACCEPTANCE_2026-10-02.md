# FINAL ACCEPTANCE — Pilot 3 (MassInv Paper 1), 2026-10-02

Nach Word-Ownership-/Isolation-Fix, adversarialem Feldtest und finalem
Real-Run auf dem finalen HEAD. P36 NICHT signiert (Human-Gate), P37 nie
ausgeführt, kein Push.

## Pflichtfeld-Bericht

- **FINAL HEAD:** `61e7fc3` (+ `83c9fa5` Ownership, `4e8ba04` Härtung R2,
  `f900598` Content-Gate — alle vor dem finalen Real-Run)
- **git tree:** CLEAN (alle Arbeiten committed)
- **Tests:** 566 passed + 2 ehrliche env-Skips (Live-Netz opt-in, HoH-Receipt)
- **Reviewer A/B:** JA / JA (Ownership-R2: zwei Runden, danach MINORs gefixt
  und eingecheckt; P31/arXiv: JA nach 4 Runden)
- **unrelated Word document survived:** YES (geöffnet geblieben, eigene
  Instanz PID 10312)
- **foreign unsaved edit preserved:** YES (`Saved=False`, Marker-Text
  vorhanden, Disk-SHA256 unverändert `e72eab50…`)
- **PF document closed:** YES (scoped close, capture-only, nie gespeichert)
- **WINWORD ownership cleanup:** PASS (PF-Instanz sauber beendet, fremde
  Instanz nie angefasst; Feldtest zweimal: R1 + R2 final)
- **manuscript SHA:** `60960422…` (draft/paper1_v1_3_0.md, unverändert)
- **DOCX SHA:** `3a2f3575…` (paper-20261002T083441149732Z.docx)
- **Paperpal checked DOCX SHA:** `3a2f3575…` — **artifact chain MATCH** ✓
- **P21** PASS (19/21 Registry-upgraded, 2 authoritative-URL) · **P31** PASS
  (exact, capture-only) · **P32** PASS · **P33** PASS · **P34** PASS
  (scaffold + arXiv-Paket: Tarball ok, Sim-Rebuild OK, Fonts embedded)
  · **P35** PASS
- **U1–U16:** 16/16 PASS
- **Offene CRITICAL/MAJOR im Core:** keine

## Die 4 DEGRADED Nodes (transparent)

| Node | Status | Warum | Klassifikation |
|---|---|---|---|
| P00 | DEGRADED | latexmk fehlt (optional; pdflatex-Fallback aktiv) | Umgebung, optional — v1.1 könnte latexmk installieren |
| P02 | DEGRADED | Chat-Logs bewusst nicht importiert (Policy) | projektspezifisch, designed |
| P08 | DEGRADED | Paper 1 macht Klassifikations-Aussagen ohne metric-bound Claims | projektspezifisch, ehrlich |
| P10 | DEGRADED | „no reproduction commands discovered" — das Evidence-Pack enthält versiegelte read-only Artefakte, keine ausführbare Repro-Pipeline | projektspezifisch; v1.1-Thema (Repro-Runner), KEIN Core-Fehler |

**Warum U1–U16 trotzdem PASS:** DEGRADED ist ein ehrlich verbuchter
Teilzustand innerhalb der DAG-Semantik (nicht FAIL, nicht PASS-auf-Papier);
keine Invariante U1–U16 verlangt die P00/P02/P08/P10-Fähigkeit — U10
(Clean-Rebuild) läuft über P34/pdflatex, U6 über den Freeze-Hash. Nichts wird
grün geredet.

## Deliverables (identisch im Mirror)

- Anschau-PDF: `…/release/massinv_paper1/build_arxiv/main.pdf` (16 S.,
  arXiv-Look, TikZ-Vektorfiguren)
- arXiv-Upload: `…/release/massinv_paper1/arxiv-massinv_paper1.tar.gz`
- Mirror: `<MIRROR_ROOT>/PROJEKTE/Paper_factory/RESULTS_2026-10-02/`
  (Hinweis: das Mirror-Refresh hat die frühere gleichnamige PDF/tar.gz aus
  demselben Tages-Lauf überschrieben statt versioniert — Alt-Versionen sind
  im Repo-Release-Verzeichnis erhalten; künftig versionierte Mirror-Namen)

## Verbleibend (HUMAN_REQUIRED, projektspezifisch)

1. **P36 final sign-off** — das einzige Gate zwischen hier und P37.
2. 113 Paperpal-Vorschläge zur Autor-Review (27 SCIENTIFIC_OR_AMBIGUOUS —
   niemals auto-applizieren; SAFE_MECHANICAL-Auto-Apply ist Roadmap-Item
   hinter dem Semantic-Diff-Gate).

## Verdikt

**P36_READY = YES** · **READY_FOR_V1_FREEZE = YES** (nach deinem Sign-off)
