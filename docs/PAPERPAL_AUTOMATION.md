# Paperpal-Automatisierung via Word-Add-in (P31) — Konzept und Recon

Status: **Konzept bestätigt durch Recon 2026-10-01**, Implementierung als
nächster Block. Ersetzt die manuelle P31-Bridge nicht semantisch — sie
automatisiert nur den menschlichen Mittelteil (Dokument in Paperpal prüfen
lassen, Ergebnis zurücklegen).

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
(5) inbox docx → pandoc → Text; SHA-256 beider Artefakte;
    Sidecar <name>.provenance.json:
      {"source": "paperpal", "method": "word-addin-computer-use",
       "captured_at": ..., "screenshots": [...], "sha256": ...}
      ▼
P31 PASS (echte externe Prüfung) → P32 Semantic Diff → P33+ entblockt
```

Der bestehende Semantik-Vertrag bleibt unangetastet: nur ein Artefakt mit
`"source": "paperpal"`-Provenienz zählt als Paperpal-Ergebnis; ein interner
Operator-Check bleibt DEGRADED. Die Semantic-Diff-Prüfung (P32/U16) arbeitet
auf demselben Inbox-Pfad wie bei der manuellen Bridge.

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
