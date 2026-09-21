# Eingabedaten

Es gibt **keine externen Eingabedateien**. Alle Elemente werden synthetisch
und deterministisch zur Laufzeit erzeugt:

- `code/run_experiment.py` zieht pro Lauf mit `random.Random(seed)` zufällige
  64-Bit-Ganzzahlen.
- Eingefügt werden `int(load * 10000)` paarweise verschiedene Elemente.
- Für die FPR-Messung werden 10.000 weitere Zufallszahlen gezogen, von denen
  nachweislich keine in der eingefügten Menge liegt (Mengenprüfung vor der
  Filteranfrage); FPR-Messung zählt also ausschließlich echte False Positives.
- Seeds: 42, 43, 44 (Basis-Seed 42 fix).

Damit ist das Experiment offline lauffähig und bitidentisch reproduzierbar.
