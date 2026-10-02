# ROADMAP_AUTONOMY — Potentialanalyse Paper Factory (2026-10-02)

Basis: Recherche-Subagent (State of the Art: AI Scientist v1/v2, Agent
Laboratory, PaperQA2/FutureHouse, AI-Researcher, ResearchAgent, SciAgents,
AgentRxiv, Reviewer-Simulation GAR/DeepReview/LLM-REVal) + Pilot-1..3-Befunde.

**Positionierung:** Alle autonomen Systeme brechen an Literatur-Synthese,
Fairness und numerischer Genauigkeit — Paper Factorys evidence-first-Core
(U1–U16, VeriHarness, T0–T4-Tiers) ist der differenzierende Vorteil.
Autonomie-Ausbau darf diese Garantien nie verwässern.

## Priorisierte Hebel (Nutzen / Aufwand / Risiko)

1. **Citation-Graph-Expansion (OpenAlex/Semantic Scholar)** — sehr hoch /
   gering-mittel / niedrig. Rückwärts-/Vorwärts-Zitationen, cited-by-Monitoring,
   Novelty gegen den echten Graphen statt Keyword-Suche. Gegen False Novelty,
   den am häufigsten konstatierten Defekt der Konkurrenz. (Anknüpfung:
   literature/verify.py hat bereits Registry-Zugriffe.)
2. **Claim-Versionierung + Claim-Drift-Detection** — sehr hoch / mittel /
   niedrig. Persistente Claim-Graph-History über Manuskript-Versionen; Semantic
   Diff auf Claims statt nur Prosa. Baut direkt auf claims/graph + U15 auf.
3. **LaTeX-Build-Repair-Loop** — hoch / gering / sehr niedrig. P34 hat bereits
   Pass-Looping + Missing-Package-Klassifikation + unresolved-Gate
   (2026-10-02). Nächster Schritt: bekannte Fehlermuster → gezielte Fixes.
4. **Reviewer-Simulation gegen echte Venue-Guidelines** — hoch / mittel /
   mittel. OpenReview-Rubriken (NeurIPS/ICLR), 3 unabhängige Sim-Reviewer +
   Meta-Reviewer. NUR als Gate, nie als Freigabe (Auto-Reviewer korrelieren
   moderat mit Human-Scores).
5. **Automatische Figuren-/Tabellen-Ideen aus dem Evidence Inventory** — hoch /
   mittel / mittel. Claims → Chart-Typ-Vorschlag → Rendering → Number-Audit-
   Rückkopplung. Synergie mit figures/tikz_diagrams.py + paper.mplstyle.
6. **Kontinuierliches Literatur-Monitoring** — hoch / mittel / niedrig.
   arXiv-Matches gegen den Claim-Graph → "bedroht Novelty?"-Alerts.
7. **RO-Crate/CFF/codemeta-Export** — hoch für Vertrauen / mittel / sehr
   niedrig. FAIR-Artefakt-Bundle; ACM/IEEE Reproducibility Badges als Ziel.
8. **Paperpal SAFE_MECHANICAL Auto-Apply** — mittel / mittel / mittel.
   Klassifizierte mechanische Korrekturen automatisch anwenden, aber NUR hinter
   dem Semantic-Diff-Gate (Zahlen/Claims/Citation-IDs unverändert). Derzeit
   capture-only (bewusst).
9. **Rebuttal-/Response-Generator** — mittel-hoch / mittel / HOCH (ethisch).
   Nur nach menschlicher Freigabe der Review-Annahme; nie Versand.
10. **arXiv-Submission-Halbautomatik** — niedrig / gering / mittel.
    Tarball+Metadaten vorbereiten (existiert seit 2026-10-02: P34-Paket),
    Submit bleibt menschlich (P37). Vollautomatik = TOS-Risiko.

## Explizite Nicht-Ziele (niemals automatisieren)

- Eigentliche Submission/Freigabe (arXiv-Submit, Konferenz) — P36/P37 bleiben
  Human-Gates. Endorsement-Pflicht, Verantwortlichkeit.
- Auto-Reviewer als Freigabe-Instanz.
- Rebuttal-Versand ohne menschliche Freigabe.
- Endlos-Self-Improvement ohne harte Budget-/Abbruch-Gates
  (AI-Scientist-Manipulationsfälle dokumentiert).
- Massen-Produktion ohne Novelty-Gate.

## Quellen (Auswahl)

arXiv 2408.06292 (AI Scientist v1) · 2504.08066 (v2) · 2502.14297 (kritische
Eval) · 2501.04227 (Agent Laboratory) · 2409.13740 (PaperQA2) · 2505.18705
(AI-Researcher) · 2503.18102 (AgentRxiv) · researchobject.org RO-Crate
