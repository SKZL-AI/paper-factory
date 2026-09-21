# Methodik-Konsolidierung: LCMS-Leitplanken (L1–L17) → PAPER FACTORY

Quelle (read-only gelesen 2026-09-21): `~/LCMS_worktrees/self-evolving-llm-glm/rd_glm/HAUSREGELN.md`
+ `MASTER_LEITPLANKEN.csv` (kanonisch). Konfliktauflösung: globale Hausregeln
(`~/.agents/AGENTS.md`) schlagen Projektleitplanken — **L13's `nvidia-smi` ist seit dem
Treiber-Wedge 2026-08-03 verboten**; GPU-Zustand wird über `ps`/`fuser`/`/proc/<pid>/stat`
geprüft. Alles andere wird übernommen und verortet.

Verortung: **HOH** = deckt VeriHarness v0.1.0 bereits ab · **PF-CODE** = in Paper Factory
code-erzwungen · **PF-OPS** = Arbeitsweise dieser Session · **PF-DOC** = Richtlinie/Doku.

| Regel | Inhalt (Kurz) | Verortung |
|---|---|---|
| L1 | Worktree-Grenzen, fremde read-only | HOH (Developer einziger Schreiber) + PF-CODE: dedizierter Klon `.paper-factory/hoh-repo` (O177), Adapter schreibt nie ins Original |
| L2 | Guard-Validität: unguarded Variante | HOH: Acceptance verlangt ≥1 discriminates (rot auf Vorgänger); PF-CODE: E2E-Test 17 prüft `discriminating`-Flag in Receipts |
| L3 | Ehrliche Scorecard, volle Case-Zahl | PF-CODE: E2E führt ALLE 18 Tests, kein Subsetting; Verdicts runden nie auf |
| L4 | Kanonischer Korpus + Hash im Ledger | PF-CODE: P04 hashed jedes Evidenz-Artefakt (T0–T4), `evidence_index.json` |
| L5 | Pre-Run-Verifikation, Mini-Smoke, kein stiller Fallback | HOH (Receipts vom Runner) + PF-CODE: `complete` führt P00-Doctor + Adapter-Smoke VOR Quota-Ausgabe aus |
| L6 | Versioniert, kein Überschreiben | PF-CODE: Ledger-Rotation `.v1.<UTC>`, Immutable-Evidence |
| L7 | Korrektur-Provenance (alter Claim bleibt) | PF-CODE: Claim-Status RETIRED statt Löschen; Review-Dispositions historisiert; Audit-Updates als `updates[]`-Arrays |
| L8 | Lokal-only Logging | PF-CODE: Release-Export exkludiert Chats/interne Reviews; kein Sync |
| L9 | Parallelisierung, konfliktfreie Stränge | PF-OPS: Pair-Dispatch ≤2 Subagenten/Strang; PF-CODE: HoH-Serialisierungs-Lock pro Klon |
| L10 | Ehrliche Kontrollen, keine Strawmen, iso-config | PF-OPS/DOC: Adversarial-Reviewer in bester Config; E2E-Fixture mit echten Stärken |
| L11 | Kein Löschen | PF-CODE/OPS: überall (Hausregel) |
| L12 | Knob-Raum abdecken, Optima sweepen | PF-OPS: Provider-Routen getestet wo verfügbar; alte Artefakte vor Nutzung verifiziert |
| L13 | GPU-Courtesy | **ERSETZT durch globale Regel: kein nvidia-smi**; ps/fuser//proc; 1 Job/GPU; PF braucht aktuell keine GPU |
| L14 | Adversariales Dual-Review-Gate vor Verdikt-Commits | PF-OPS: 2 Reviewer-Subagenten (Auftrag: widerlegen) vor E2E-Verdikt, Gap-Report, Closure; dokumentiert pro Gate |
| L15 | Vollständige Issue-Adresse | PF-CODE: `core/issue_ledger.py` — jedes Issue sofort gefixt ODER getrackt mit Begründung+Priorität |
| L16 | Index/Wiki-Pflege im Commit-Rhythmus | PF-OPS: Dashboard/Docs/State-JSONs bei jedem Phasen-Commit aktualisiert |
| L17 | Double-Down ≥5 Sequential-Paar-Runden bei R&D-Negativen | PF-OPS+CODE: `core/double_down.py` Ledger; Treiber = Orchestrierung; Firewall: Mess-Verdikt unantastbar |

## Anwendung in DIESEM Projekt (verbindlich für die Session)

1. Jeder E2E-Fail wird nach L9/L17 behandelt: empirische Instrumentierung → Root-Cause →
   Harness-Bug (fixen, re-run bis grün) vs. realer Befund (ehrlich verbuchen) → ggf.
   Sequential-Paar-Double-Down mit Ledger-Einträgen.
2. Verdikt-Commits (E2E-PASS, Gap-Report, Global Closure) nur nach Dual-Review-Gate.
3. Issue-Ledger: `paper_factory/state/issue_ledger.jsonl`, gespiegelt ins Dashboard.
4. HoH-Nutzung immer über den Adapter mit Klon-Politik (L1 + O177).
