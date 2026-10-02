# Paperpal-Automatisierung via Word-Add-in (P31) — Konzept und Recon

Status: **IMPLEMENTIERT und feldverifiziert (2026-10-01)** — der erste reale
Lauf auf Pilot 3 ist dokumentiert unten. Ersetzt die manuelle P31-Bridge
nicht semantisch — sie automatisiert nur den menschlichen Mittelteil
(Dokument in Paperpal prüfen lassen, Ergebnis zurücklegen).

## Warum kein API/MCP

Paperpal bietet kein dokumentiertes API und keinen offiziellen MCP-Server.
Die auffindbaren „paperpal"-Einträge auf GitHub/MCP-Marketplace sind
inoffizielle Drittprojekte ohne Verifikationswert. Die sauberste externe
Prüfinstanz bleibt Paperpal selbst — als Word-Add-in (installiert, mit dem
Microsoft-Konto des Nutzers verbunden, **Prime Classic Annual Plan aktiv**).

## Recon-Befunde 2026-10-01 (Belege: `recon/paperpal-shot1.png`, `recon/paperpal-shot2.png`)

| Fähigkeit | Status | Beweis |
|---|---|---|
| pandoc md→docx in WSL | ✓ | `/usr/bin/pandoc` |
| Word COM aus WSL via `powershell.exe` | ✓ | Word 16.0, `WORD_COM_OK` |
| Word sichtbar öffnen + maximieren | ✓ | shot1 |
| Screenshot aus WSL (System.Drawing) | ✓ | shot1/2, 2048×1152 |
| Mausklick via `SetCursorPos`/`mouse_event` | ✓ | Popup per Klick geschlossen (shot1→shot2) |
| Paperpal Ribbon-Tab vorhanden | ✓ | shot2 (Tab „Paperpal", Button „Open Paperpal") |
| Paperpal-Pane, eingeloggt | ✓ | shot2: Account + Prime-Plan sichtbar |
| Pane-Struktur | ✓ | Tabs „Grammar"/„Consistency", Seitenmenü Edit/Agents/Rewrite/Write |
| Word schließen ohne Speichern | ✓ | `WORD_CLOSED_NO_SAVE` |

Damit ist die gesamte Kette **ohne neue Installationen** machbar:
PowerShell-COM für Word, PowerShell+GDI für Screenshots, user32 für Maus,
Vision durch den orchestrierenden Agenten (Screenshots werden gelesen).

## Ziel-Architektur: Adapter `paper_factory/adapters/paperpal_word/`

```
P30 outbox/main.tex
      │  (1) pandoc → outbox/paper.docx          [deterministisch, testbar]
      ▼
(2) Word COM: öffnen, maximieren, Paperpal-Pane sicherstellen
      │  Ribbon „Paperpal" → „Open Paperpal"
      ▼
(3) Computer-use-Treiber (Screenshot-Loop):
      Grammar-Tab → Analyse abwarten → Vorschläge erfassen
      Consistency-Tab → Analyse abwarten → erfassen
      Screenshots als Receipts (vorher/nachher je Stufe)
      │  optional: „Accept all" für Sprachkorrekturen
      ▼
(4) Speichern als NEUE Datei paperpal/inbox/paper-paperpal.docx
    (Outbox wird nie überschrieben; Word wird sauber geschlossen)
      ▼
(5) Inbox-Auslieferung NUR über den Production-Writer
    (`run_paperpal_word.py deliver <report> <staged.docx>` →
    `WordPaperpalAdapter.deliver`): der Sidecar `<name>.provenance.json`
    wird dabei mit `docx_sha256_staged` = SHA-256 des EXAKT gestageden
    DOCX geschrieben — der Wert wird aus dem Artefakt gerechnet, nie
    handgesetzt:
      {"source": "paperpal", "docx_sha256_staged": ..., "staged_docx": ...,
       "delivered_at": ..., "delivered_by": "WordPaperpalAdapter/v1"}
      ▼
P31 PASS (echte externe Prüfung, exact-artifact-gebunden) → P32 Semantic
Diff → P33+ entblockt
```

Der bestehende Semantik-Vertrag bleibt unangetastet: nur ein Artefakt mit
`"source": "paperpal"`-Provenienz zählt als Paperpal-Ergebnis; ein interner
Operator-Check bleibt DEGRADED. Die Semantic-Diff-Prüfung (P32/U16) arbeitet
auf demselben Inbox-Pfad wie bei der manuellen Bridge.

### Exact-Artifact-Bindung (Release-Audit 2026-10-02)

Im `word_auto`-Modus muss die Inbox-Evidenz per `docx_sha256_staged` an das
AKTUELL gestagede DOCX gebunden sein (`artifact_binding: exact`), sonst
P31/U9/U16 = HUMAN_REQUIRED (stale | unbound | unverifiable). U9/U16
revalidieren die Kette on disk neu (DOCX-Hash + Sidecar-Bindung), statt dem
State-File zu trauen.

**Threat-Model-Ehrlichkeit (Reviewer B B2):** die Bindung ist ein
Konsistenz-Nachweis, kein Authentizitätsbeweis — Inbox und Sidecar liegen im
selben beschreibbaren Trust-Domain. Wer bewusst fälschen will, kann den Hash
aus `paperpal_state.json` kopieren. Die Bindung schützt gegen *veraltete*
Evidenz (der reale Pilot-3-Fall), nicht gegen *fabrizierte*. Zwei Anker
erhöhen den Aufwand: (1) der Production-Writer `deliver()` rechnet
`docx_sha256_staged` aus dem Artefakt; (2) jeder echte Render schreibt ein
append-only Event `paperpal_docx_rendered` in den Workspace-Ledger
(`runs.sqlite`), und der Reuse-Pfad verlangt das exakte Tripel
(name, docx_sha256, source_sha256) daraus — ein getauschtes DOCX mit
handaktualisiertem Sidecar (Reviewer B R4 N-B2) wird nicht als Render
anerkannt. Der Ledger liegt in derselben Trust-Domain; er macht Tausch
tamper-evident, nicht unmöglich. Die Deliver-Receipts
(`transitions.jsonl`, Screenshots) sind beratend und werden von P31/U9/U16
**nicht maschinell geprüft**. Ein kryptographisch externer Anker ist bewusst
v1.1+.

## Ehrlichkeits- und Fehlerregeln

- Kein simuliertes Ergebnis: jeder Schritt legt Screenshot-Receipts ab; der
  Sidecar verweist auf sie. Ohne belegte Paperpal-Session → P31 bleibt
  HUMAN_REQUIRED.
- UI-Drift (Paperpal ändert sein Pane-Layout) → Abbruch mit Screenshots +
  HUMAN_REQUIRED, niemals Raten.
- Word läuft sichtbar in der Windows-Session des Nutzers; der Treiber fasst
  nur das Outbox-DOCX an, speichert ausschließlich in die Inbox.
- Keine Credential-Speicherung: die Paperpal-Session nutzt die bestehende
  Word-Anmeldung des Nutzers.
- Tests: pandoc-Konvertierung, Sidecar-Schema, Inbox-Ingestion,
  Diff-Verdrahtung sind unit-testbar (kein Word nötig); die UI-Strecke ist
  Integrationstooling und wird mit echten Screenshots verifiziert, nicht im
  pytest (kein Word in CI — ehrlich als solches markiert).

## Verworfene Alternativen

- **Paperpal Web + Browser-Automation:** bräuchte separates Login-Management;
  die Word-Strecke ist bereits authentifiziert und näher am Manuskript.
- **pywinauto/UIA auf Windows:** zusätzliche Installation; Pane ist WebView2,
  UIA-Baum fragil — Screenshot-Loop ist genereller und belegbarer.
- **Reines COM:** reicht nicht ins Add-in-Pane (Web-Add-ins sind kein COM).
- **Dritt-MCP-Server:** unoffiziell, unverifiziert — kommt nicht in Frage.

## Rollout

1. Adapter-Modul + PowerShell-Assets (Screenshot, Click, Word-Steuerung).
2. Unit-Tests für die deterministischen Teile.
3. Echter Lauf auf `pilots/pilot-03-massinv-paper1` Outbox → P31 PASS →
   P33–P37 erstmals durchlaufen → Global Closure U1–U16.
4. Dashboard/Report aktualisieren.

Verbleibend bewusst menschlich: P36 Sign-off (hartes Gate, designed).

---

# Nachtrag 2026-10-01 — Implementierung und erster realer Lauf

## Was tatsächlich gebaut wurde

- `paper_factory/paperpal/docx_outbox.py` — versionierte DOCX-Outbox
  (pandoc + generiertes arXiv-Stil-Referenzdokument; Figuren-Einbettung via
  `![]()`-Umschreibung; Provenienz-Sidecar mit Source-/DOCX-Hashes).
- `paper_factory/paperpal/word/` — `pfword.ps1` (open/save-copy/close/shot/
  click/uia-click/uia-find/uia-dump/uia-dump-scope/park/unpark/bg-click/
  si-click), `driver.py` (State-Machine + append-only `transitions.jsonl`),
  `classify.py` (SAFE_MECHANICAL / SEMANTICALLY_GUARDED /
  SCIENTIFIC_OR_AMBIGUOUS), `cdp.py` (stdlib CDP-Client).
- `scripts/run_paperpal_word.py` — Orchestrierungs-Einstieg.

## Gelernte Implementation Reality (wichtig für spätere Läufe)

1. **Synthetic input in der Pane funktioniert NICHT.** PostMessage,
   mouse_event und SendInput werden vom WebView2-Chromium der Office-Pane
   still ignoriert. UIA-Invoke funktioniert nur für Word-Chrome (Ribbon).
2. **Der funktionierende Pfad ist CDP:** Word mit
   `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=0`
   starten, Pane öffnen, Port aus
   `%LOCALAPPDATA%\Microsoft\Office\16.0\Wef\webview2\*\EBWebView\DevToolsActivePort`
   lesen, dann DOM-Zugriff auf `office-addin.paperpal.com/taskpane`.
   Tab-Klicks, Kartenextraktion (virtueller Scroller `div.scroller`),
   alles deterministisch — ohne Maus, ohne Fokus, Word kann dabei sogar
   verdeckt sein.
3. **PrintWindow auf Office liefert schwarze Bilder** (GPU-Rendering) —
   Fenster-Screenshots nur über kurze Fokus-Borrows mit Rücksprung.
4. **"Download edits with track changes" ist im Word-Add-in NICHT
   verfügbar** — die Pane sagt selbst: "This is currently a Web-only
   feature." Ehrlich dokumentiert; keine Behauptung dieser Funktion.
5. **Checks-Sektion** (Plagiarism, AI Detector, Reference Checker,
   Journal Fit, AI Review, Human Expert) sind externe Links in die
   Paperpal-Web-App, keine In-Add-in-Checks.
6. Pane-Inhalt ist NICHT im Word-UIA-Baum (nur Pane-Chrome).

## Erster realer Lauf (Pilot 3, 2026-10-01)

- DOCX: `paper-20261001T183040341506Z.docx` (20 Seiten, 2 Figuren, 5
  Tabellen), SHA-seitig belegt, aus Draft v1.3.1 gerendert.
- **Grammar: 210 suggestions in 148 sentences; alle 148 Karten via CDP
  extrahiert**, Kategorien-Verteilung erfasst, alle klassifiziert:
  14 SAFE_MECHANICAL / 107 SEMANTICALLY_GUARDED / 27 SCIENTIFIC_OR_AMBIGUOUS.
- **Consistency: "No consistency issues found!"**
- Track-changes-Export: web-only (nicht erzeugt, ehrlich verbucht).
- Word-Session ohne Speichern geschlossen (capture-only, Brief F).
- Inbox: `paperpal_report.json` + `.provenance.json` (`source: paperpal`).
- Receipts: `receipts/p31-*.png` + `paperpal_word_session.json`
  (State-Machine DOCX_READY → INBOX_READY).
