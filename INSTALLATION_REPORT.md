# INSTALLATION REPORT — PAPER FACTORY

Datum: 2026-09-21/22 · Maschine: WSL2 (SAI-01) · Autor: Kimi (Captain-Session)

## SYSTEM STATUS

```
PAPER FACTORY CORE     PASS          (CLI, DAG P00–P37, 61/61 Tests grün)
VERIHARNESS            PASS          (v0.1.0 @5d576bd, editable-Install, echter Live-Run)
HERDR                  PASS          (0.8.0 läuft; Pane-Evidenz w6F)
OPENCODE               UNAVAILABLE   (nicht installiert; Wrapper-Template liegt bereit)
PI                     PASS          (0.85.1, Adapter + Wrapper)
KIMI                   PASS          (2.0.2; Subprocess-Invoke; Pane-Driving: siehe D1-Gap)
CODEX                  PASS          (0.153.4)
CLAUDE                 PASS          (2.1.278; unter Strict-Policy kein Finalprosa-Ursprung)
LITERATURE STACK       PASS          (Crossref + OpenAlex live verifiziert; PaperQA2 UNAVAILABLE)
LATEX                  DEGRADED      (pdflatex-Multipass ok; latexmk fehlt → HUMAN_REQUIRED sudo)
PAPERPAL               HUMAN_REQUIRED(manuelle Bridge outbox/inbox; kein API)
PROVENANCE             PASS          (Firewall + Origin-Receipts, U11–U14 grün)
SYNTHETIC E2E          PASS          (61/61 Tests, davon 18 Akzeptanztests)
GLOBAL CLOSURE         PASS          (U1–U16 am Referenzlauf, siehe Dashboard)
```

## IMPLEMENTED

- Separates Projekt `/home/sai/paper-factory` (git, venv, 10 CLI-Kommandos).
- DAG P00–P37 mit ehrlichen Zuständen; Audit→Review→Remediation→Closure-Semantik.
- 6 Harness-Adapter + Provider-Router (Harness≠Backend, Receipts, DEGRADED_INDEPENDENCE).
- VeriHarness-Adapter mit O177-Klon-Politik (eigener Klon, eigener runs-Root,
  PF-Run-ID-Prefix, Serialisierung, Pane-Cleanup, kein Push).
- Evidenz T0–T4, Claim-Graph, Literatur-Verifikation (Crossref/OpenAlex),
  gruppierte Statistik → LaTeX-Makros, Figuren (Okabe-Ito), booktabs-Tabellen,
  deterministische Manuskript-Komposition mit Provenance-Firewall,
  strukturierte Reviews, Remediation ohne Reviewer-Prosa-Transfer,
  Release mit Secret-Scan (fail-closed) + unabhängigem Rebuild + U1–U16-Closure.
- Frontend-Wrapper: `~/.agents/skills/complete-paper/`, `~/.claude/skills/complete-paper/`,
  Templates in `frontends/`.
- Echte HoH-Integration bewiesen: Run `PF-e05758a3-P05` CHECKPOINTED,
  10 VERIFIED Evidence-Items, 36 immutable Receipts, QA=codex (andere Familie).

## VERIHARNESS GAPS (nur empirisch belegte)

Siehe `VERIHARNESS_GAP_REPORT.md`: C1 (Launcher-Quota-Klassifikation),
D1 (herdr×kimi Pane-Stall), A1 (Namens-Truncation), A2 (Test-Orphans),
C2 (Trust-Dialog in frischen Dirs). Kein Upstream-Patch aus Bequemlichkeit;
C1 ist ein sauberer Kandidat für einen kleinen generischen Fix.

## OPTIONAL CREDENTIALS STILL NEEDED

- Paperpal-API (oder manuelle Bridge weiter nutzen — sie ist implementiert).
- `sudo apt install texlive-latex-extra graphviz qpdf poppler-utils` für
  latexmk/dot/qpdf/pdftotext (optional; Pipeline läuft ohne sie, DEGRADED).
- Weitere Provider-Keys (GLM/DeepSeek) für mehr Modell-Diversität — sonst
  wird DEGRADED_INDEPENDENCE ehrlich vermerkt.

## FIRST REAL PAPER COMMAND

```bash
cd <dein-forschungsprojekt>
paper-factory doctor
paper-factory complete            # bis P36 (Human Sign-off); Paperpal-Bridge beachten
paper-factory resume              # nach Human-Deliveries
```

## GIT STATE

- repo: /home/sai/paper-factory · branch: main
- commits: siehe `git log` (Scaffold → A3 → C+D → E+F → G)
- dirty files: nur `.archiv/` (bewusst ungetrackt, geparkte Alt-Zustände)
- kein Push, kein Publish, keine externe Submission.

## VERIFIKATION (nachvollziehbar)

- `.venv/bin/python -m pytest tests -q` → 61 passed
- `dashboard/index.html` (self-contained) — Generierung:
  `.venv/bin/python -c "from pathlib import Path; from paper_factory.report.dashboard import render_dashboard; render_dashboard(Path('examples/demo_project/.paper-factory/reports'))"`
- HoH-Evidenz: `paper_factory/state/e2e_hoh_evidence.json`, Receipts unter
  `/tmp/pf-hoh-live/.paper-factory/hoh-runs/PF-e05758a3-P05/receipts/`
