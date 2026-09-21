# Bloom-Filter vs. Cuckoo-Filter: False-Positive-Rate unter wachsender Last

Kleines, vollständig reproduzierbares Vergleichsexperiment: Wie entwickelt
sich die False-Positive-Rate (FPR) eines klassischen Bloom-Filters und eines
Cuckoo-Filters, wenn die Anzahl eingefügter Elemente relativ zur
Designkapazität wächst?

Das Projekt ist bewusst minimal gehalten: nur Python-Standardbibliothek,
keine externen Abhängigkeiten, keine Netzwerkzugriffe, deterministisch
(Basis-Seed 42, drei Wiederholungen mit Seeds 42/43/44).

## Struktur

```
code/filters.py          Bloom- + Cuckoo-Filter-Implementierung (Stdlib)
code/run_experiment.py   führt 30 Läufe aus -> results/experiment_runs.csv
code/analyze.py          aggregiert die CSV -> results/summary.json
results/                 generierte Ergebnisse (CSV + JSON)
data/                    Beschreibung der synthetischen Eingabedaten
draft/                   Papier-Draft (Markdown)
history/                 Chat-Export und Recherche-Notizen zum Projektverlauf
literature/references.bib  Literaturverzeichnis
```

## Reproduktion

```bash
python3 code/run_experiment.py   # schreibt results/experiment_runs.csv
python3 code/analyze.py          # schreibt results/summary.json
```

Beide Skripte laufen mit jedem Python ≥ 3.8 und erzeugen bei gleichem
Code bitidentische Ergebnisse.

## Experiment-Setup

- Designkapazität N = 10.000 Elemente; beide Filter werden für N konfiguriert
  (Bloom: 8 Bit/Element, k = 6 Hashfunktionen; Cuckoo: 4096 Buckets à 4 Slots,
  12-Bit-Fingerprints, max. 500 Kicks).
- Laststufen: 50 %, 70 %, 80 %, 90 %, 95 % von N.
- Pro (Filter, Last)-Kombination drei Läufe mit den Seeds 42, 43, 44.
- Pro Lauf 10.000 Anfragen mit garantiert nicht eingefügten Elementen;
  FPR = False Positives / 10.000.
