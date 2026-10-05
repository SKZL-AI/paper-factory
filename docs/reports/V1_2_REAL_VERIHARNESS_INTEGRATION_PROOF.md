# V1.2 REAL VeriHarness Integration Proof

Datum: 2026-10-05 · Status: **MATCH (echter provider-backed Differential-Fall)**
Maschinen-Evidenz: `docs/reports/v1_2_integration_proof.json`
Reproduzierbarer Entry Point: `scripts/run_integration_proof_v12.py`
(expliziter Live-Pfad, analog `scripts/run_live_hoh.py`; nie in pytest)

## Identitäten

| Feld | Wert |
|---|---|
| PF HEAD | `58b3a80` (Branch `v1.2/integration-proof`) |
| VeriHarness | hoh 0.1.0, Commit `5d576bd` (Repo read-only, kein Byte geändert) |
| WorkPackage | `v12-integration-proof-P05` (schema_version=1, Node P05) |
| HoH Run ID | `PF-938286ae-P05` |
| Backend Identity | kind=veriharness, name=hoh, dispatch=HarnessDispatcher (`--no-herdr`) |
| Artifact Binding | `705fb76e4310d21fddf208cf5a8ca939185d6adfd6c7e48df20c823ffcf9d801` (Manifest-Digest über `code/analyze.py` + `results/summary.json` der Synthetic-Fixture, `artifact_binding()`) |
| Clone-Fingerprint | `hoh-repo/clone-manifest.json` (git-inhaltsbasiert, im Result unter `backend.detail.clone_fingerprint`) |
| Accepted Candidate | `PF-938286ae-P05-i1`, Commit `ddb19d6`, Stage CHECKPOINTED |

## Ergebnis

| Seite | Verdict | artifact_sha256 |
|---|---|---|
| PF-native (K1: `analyze.py` reproduziert, K2: Result-Artefakt vorhanden) | PASS | `705fb76e…` |
| VeriHarness/HoH (K1–K4, 8 Receipts kopiert, SHA-registriert) | PASS | `705fb76e…` |
| **Differential** | **MATCH** | identisch |

Rationale (vom Receipt, wörtlich): identische Verdicts + identische Bindung;
die Bindung ist das caller-deklarierte Package-Manifest und per Konstruktion
identisch — **kein unabhängiges Re-Hash durch das Backend** (A-8-Ehrlichkeit:
Agreement über eine geteilte Deklaration, kein unabhängiges Artefakt-Audit).

Erwünschtes Nebenprodukt: Der Developer schrieb real `VERIFICATION.md` im
PF-owned Clone; QA akzeptierte gegen Runner-Receipts (K1–K4, jeweils
befehls- und ergebnisgebunden). Die 8 kopierten Receipts sind im
Evidence-JSON mit SHA-256 registriert (`receipts[]`):

| Receipt | SHA-256 (Präfix) |
|---|---|
| PF-938286ae-P05-i1-a1-K1-basis.json | `d6f5b5a545677055` |
| PF-938286ae-P05-i1-a1-K1.json | `1498ee09c10d2c65` |
| PF-938286ae-P05-i1-a1-K2-basis.json | `4a45d7dc1705f5b6` |
| PF-938286ae-P05-i1-a1-K2.json | `6f8ccd793aabc27a` |
| PF-938286ae-P05-i1-a1-K3-basis.json | `88caa1576b1057d4` |
| PF-938286ae-P05-i1-a1-K3.json | `d9bf3d52656f4cb2` |
| PF-938286ae-P05-i1-a1-K4-basis.json | `c351bbfd2eb65c93` |
| PF-938286ae-P05-i1-a1-K4.json | `b0761b95cf8bd0cf` |

## Runtime / Kosten

- Wall Clock: 06:08:55 → 06:15:43 UTC (~6:48 min)
- Netzwerk: nur LLM-CLI-Dispatches (Subscriptions); keine sonstigen externen Calls
- LLM: planner=codex, developer=codex, qa=codex, iterations=1, `--no-herdr`
- Kosten: Subscription-Quota, pro Run nicht messbar (Dokumentierte Limitation)
- Cleanup: 0 eigene Panes offen (`herdr_tabs_after: []`); keine fremden
  Ressourcen berührt; fremdes Pilot-/VeriHarness-Repo unverändert

## Fehlerkaskade bis zum MATCH (vollständig, nichts kaschiert)

| Versuch | Run-ID | Ausgang | Root Cause (bewiesen) | Konsequenz |
|---|---|---|---|---|
| 1 | PF-73ed7828-P05 | FAIL/MISMATCH | Claude Session-Quota erschöpft (Planner-Pane idle auf Quota-Meldung) | Reset abgewartet; Evidenz `…attempt1-claude-quota…json` |
| 2 | PF-581db7b3-P05 | FAIL/MISMATCH | kimi-TUI: Session-Start > herdr 5s-Stall-Fenster → `agent_prompt_stalled` | herdr-Limitation dokumentiert; Evidenz `…attempt2-kimi-stall…json` |
| 3 | PF-7aeb552c-P05 | FAIL/MISMATCH | codex im herdr-Pane: leeres Pane, selbes 5s-Stall-Fenster | Adapter-Option `use_herdr` gebaut (58b3a80); Evidenz rekonstruiert: `v1_2_integration_proof.attempt3-herdr-stall-codex.2026-10-05T062737.116892Z.json` (aus dem archivierten Run-Tree, Provenance im JSON) |
| 4 | PF-c6fa5b94-P05 | FAIL/MISMATCH | claude-Planner verletzt DevelopmentPlan-Contract (`description` statt `command`, Repair-Budget erschöpft) | Planner→codex + Contract-Beispiel in Spec |
| 5 | PF-773ec39c-P05 | FAIL/MISMATCH | codex Developer las stdin (Exit 1) | Reproduktion: Prompt-Form unschuldig → transient (Capacity) vermutet |
| 6 | PF-42fe1242-P05 | FAIL/MISMATCH | identisch zu 5 | argv-Shim-Instrumentierung gebaut |
| 7 | **PF-938286ae-P05** | **PASS/PASS → MATCH** | — | Shim-Log beweist korrekte argv-Zustellung; Versuche 5/6 damit als transientes codex-Capacity-/Startup-Verhalten klassifiziert |

Zusätzlicher echter Defekt, den die Feldtests enttarnten: der Shim
`verify_work_package` droppte die Parameter planner/developer/qa/iterations
still (Fix `65a49fb`, mit Regressionstests).

## Bekannte Limitierungen (ehrlich)

1. `--no-herdr`: keine A01/A02/A12-Pane-Evidenz (HoH-eigene Klassifikation).
   Die Receipt-Evidenz (Runner, Exit-Codes, Digests) ist vollständig; die
   Pane-Provenienz der Rollenausführung fehlt. Grund: herdr-seitiges,
   nicht konfigurierbares 5s-Stall-Fenster vs. neue CLI-TUI-Versionen
   (Empfehlung an herdr/veriharness in `DEFERRED_HARDENING.md`).
2. developer == qa == codex: keine Harness-Diversität in diesem Proof; der
   Proof zielt auf die Integrationskette, nicht auf Review-Unabhängigkeit.
3. MATCH-Bindung ist per Konstruktion identisch (beide Seiten lesen dasselbe
   Package) — siehe A-8-Rationale oben. INCOMPARABLE/MISMATCH-Pfade sind
   unit-/adversarial-getestet, nicht live provoziert (wie im Auftrag erlaubt).
4. Kosten nicht messbar; Quota-Verbrauch der CLIs ist real, aber klein
   (~7 Live-Dispatches gesamt über alle Versuche).

## Foreign-Resource Safety

- PF-owned Clone unter `pilots/integration-proof-v12/project/.paper-factory/hoh-repo`
- eigener Runs-Root, PF-Präfix-Run-IDs, flock-Serialisierung
- lokaler VeriHarness-Klon unter `~/veriharness` (read-only; belegt: nur `git rev-parse` gelesen; Pfad via `PF_VERIHARNESS_REPO` übersteuerbar)
- keine fremden Panes/Runs angefasst (0 eigene Panes offen nach Cleanup)
- kein Push, kein Tag, kein Release
