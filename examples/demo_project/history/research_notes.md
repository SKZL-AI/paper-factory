# Research Notes — Bloom vs. Cuckoo unter Last

Stand: 2026-09-18

## Was wir wissen

- FPR-Kurve reproduzierbar (Seeds 42/43/44), Cuckoo liegt bei 0.90/0.95 Last
  grob eine Größenordnung unter Bloom. Passt zur Theorie.
- Erster Messversuch war kaputt (Queries nicht gegen eingefügte Menge
  geprüft → FPR ~1.0). Fix sitzt, siehe Chat-Export 2026-09-15.
- Terminologie fixiert: durchgehend "false-positive rate (FPR)", "load"
  immer relativ zur Designkapazität N = 10.000.

## Offene Fragen

- **Offen:** Wie verhalten sich beide Filter jenseits der Designkapazität
  (load > 1.0)? Beim Cuckoo steigen dann Insert-Failures — Messreihe nötig,
  bevor wir dazu etwas behaupten können.
- **Offen:** Lookup-Latenz. Wäre für die Discussion schön (Read-Path-Argument),
  wurde aber **bislang nicht gemessen** — aktuell keine Timing-Infrastruktur
  im Code. Falls es rein soll: eigene Messreihe mit time.perf_counter,
  sonst nichts dazu behaupten.
- Statistik: nur n = 3 Seeds. Für belastbare Signifikanzaussagen bräuchten
  wir mehr Wiederholungen und einen echten Test — im Draft vorsichtig
  formulieren.

## Literatur-Merkposten

- Schmidt & Weber 2024 (hybride Adaptive Filter) ist im Draft zitiert —
  Quelle stammt aus einer früheren Literaturliste, DOI noch nicht
  händisch gegen das Original geprüft.
