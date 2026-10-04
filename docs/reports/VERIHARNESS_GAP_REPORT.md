# VERIHARNESS GAP REPORT

Datum: 2026-09-21/22 · Gegenstand: VeriHarness/hoh v0.1.0 (Clone @ 5d576bd) ·
Erstellt NACH dem synthetischen E2E-Lauf von PAPER FACTORY. Kategorien:
A = PF-Adapter · B = PF-Core · C = VeriHarness generisch · D = Herdr ·
E = Provider-spezifisch · F = optionale Optimierung.

Jeder Befund ist empirisch belegt (Artefakt/Repro benannt). Kein Eintrag wurde
aus Bequemlichkeit erfunden; keine HoH-Änderung wurde vorgenommen.

---

## C1 — Launcher-Quota-Klassifikation mismatcht Run-State (generisch, echter Bug)

- **Befund**: `launcher.py:48` `PROVIDER_BLOCKED = {"usage_quota","quota","rate_limit","provider"}`
  matched per Substring gegen `blocked_kind.lower()`; `stages.py:213` schreibt
  `usage_limit`. `"quota" in "usage_limit"` ist False → quota-geblockte Runs
  werden projektseitig als `UNDETERMINED` statt `PROVIDER_UNAVAILABLE` gelesen.
  Tests parametrisieren nur die nie geschriebenen Werte
  (`tests/test_launcher_verdicts.py:91`).
- **Beleg**: Code gelesen + stichprobenartig gegengeprüft 2026-09-21
  (sed-Zeilen oben im Audit-Log); Explore-Report Punkt 11.
- **Einordnung**: generisch ja; jeder HoH-Konsument der Projekt-Ebene profitiert.
  Adapter-Lösung existiert (PF liest `blocked_kind` aus `state.json` direkt).
- **Empfehlung für Upstream**: `"usage_limit"` in PROVIDER_BLOCKED aufnehmen +
  Test um den real geschriebenen Wert erweitern. Kleiner Patch, testbar,
  schwächt keine Garantie.

## D1 — herdr 0.8.0 × kimi 2.0.2: `agent prompt` stalled auf frischem Pane

- **Befund**: `herdr agent start --kind kimi` meldet `interactive_ready: true`,
  aber `herdr agent prompt <pane> … --wait` liefert `agent_prompt_stalled`
  ("no observed state change within 5000 ms; status idle"). Pane zeigt die
  Kimi-2.0.2-Startansicht ("No session yet — one will be created on your first
  message"). Minimalrepro außerhalb von HoH: identisches Verhalten
  (Probe-Tab w6B:tE, 2026-09-21). Claude-Panes funktionieren im selben Setup
  (Planner-Rolle lief erfolgreich).
- **Beleg**: HoH-Telemetry (`developer failed / UNKNOWN / agent_prompt_stalled`)
  + eigenständige Probe. Nicht quota-bezogen.
- **Einordnung**: Herdr-Treiber für kimi 2.0.2 (TUI-State-Erkennung /
  Session-Initialisierung > 5 s Stall-Fenster). Workaround in PF:
  Developer-Rolle auf claude/codex; kimi bleibt als PF-Harness-Adapter
  (Subprocess-Invoke) voll nutzbar.

## A1 — Herdr-Agentennamen truncieren bei ~24 Zeichen → Kollisionsgefahr

- **Befund**: Name `hoh-pf-p05-20260-planner` kollidierte über zwei
  verschiedene Runs hinweg (Zeitstempel abgeschnitten); HoH verweigerte den
  Start korrekt (fail-safe), der Lauf blockte.
- **Einordnung**: in PF gelöst (Run-ID `PF-<rand8>-<NODE>`, Zufall vor dem
  Truncation-Punkt). Generische HoH-Verbesserung wäre: Run-Hash in den
  Agentennamen. Optional, nicht blockierend.

## A2 — pytest-Tempdirs + Herdr-Panes → verwaiste Agenten

- **Befund**: Ein aus Versehen quota-auslösender Test (E2E-Config ohne
  `hoh_nodes: []`) startete einen HoH-Run in einem pytest-Tmpdir; pytest
  löschte das Verzeichnis laufenden Agenten unter den Füßen weg; der
  Agentname blockierte danach Folge-Runs (Verweis auf gelöschtes cwd).
- **Einordnung**: PF-Policy-Fehler, behoben (Tests nie mit HoH; Pane-Cleanup
  im Adapter; `.archiv/` statt Löschen). Hausregeln-Nachtrag erfolgt.
  Kein VeriHarness-Defekt — HoH hat korrekt fail-safe reagiert.

## C2 — Claude-Ordner-Trust-Dialog blockiert Developer-Dispatch in frischen Dirs

- **Befund**: `claude` zeigt in einem nie benutzten Arbeitsverzeichnis den
  Trust-Dialog; HoH meldet sauber `WaitingForApproval` und hält den Tab offen
  (gewollt: nie auto-beantworten).
- **Einordnung**: korrekt designtes HoH-Verhalten; operativ gelöst durch
  gezieltes Vor-Trauen PF-eigener Klon-Pfade (`hasTrustDialogAccepted` für
  `<target>/.paper-factory/…`). Dokumentationshinweis für HoH-OPERATIONS
  wäre hilfreich (F).

## Nicht-Befunde (explizit geprüft, kein Gap)

- Receipt-Unveränderbarkeit, flock-Pro-Run, Stale-Writer-Erkennung,
  ImmutableViolation-Pfade: wie dokumentiert (store.py).
- Parallelbetrieb zweier Sessions ist bei eigener Klon-Politik sicher
  (O177-Konsequenz ist in PF code-erzwungen, nicht HoHs Schuld).

## Optional (F)

- HoH-Spec-Templates je PF-Knotentyp; Kostenfeld in Telemetry mit echten
  Zahlen füllen, sobald Provider das hergeben.
