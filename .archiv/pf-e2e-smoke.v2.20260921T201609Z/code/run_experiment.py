#!/usr/bin/env python3
"""Deterministisches Experiment: FPR von Bloom- vs. Cuckoo-Filter unter Last.

Basis-Seed 42 (fix), drei Wiederholungen pro Konfiguration mit den Seeds
42, 43, 44. Fuer jede (filter, load, seed)-Kombination werden
int(load * DESIGN_CAPACITY) zufaellige 64-bit-Elemente eingefuegt und
anschliessend N_QUERIES garantiert nicht eingefuegte Elemente abgefragt;
die False-Positive-Rate (FPR) ist false_positives / N_QUERIES.

Schreibt results/experiment_runs.csv (eine Zeile pro Lauf).
Nur Python-Stdlib, keine Netzwerkzugriffe.
"""

import csv
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from filters import BloomFilter, CuckooFilter

DESIGN_CAPACITY = 10_000
LOADS = [0.50, 0.70, 0.80, 0.90, 0.95]
SEEDS = [42, 43, 44]
N_QUERIES = 10_000
RESULTS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "results", "experiment_runs.csv"
)

FIELDNAMES = [
    "run_id",
    "filter",
    "load",
    "seed",
    "n_inserted",
    "n_insert_failed",
    "n_queries",
    "false_positives",
    "fpr",
]


def make_filter(filter_name):
    if filter_name == "bloom":
        return BloomFilter(DESIGN_CAPACITY)
    if filter_name == "cuckoo":
        return CuckooFilter(DESIGN_CAPACITY)
    raise ValueError(f"unbekannter Filter: {filter_name}")


def run_single(filter_name, load, seed):
    rng = random.Random(seed)
    n_items = int(load * DESIGN_CAPACITY)

    items = set()
    while len(items) < n_items:
        items.add(rng.getrandbits(64))

    filt = make_filter(filter_name)
    n_inserted = 0
    n_failed = 0
    for item in items:
        if filt.add(item):
            n_inserted += 1
        else:
            n_failed += 1

    false_positives = 0
    asked = 0
    while asked < N_QUERIES:
        q = rng.getrandbits(64)
        if q in items:
            continue  # nur garantiert abwesende Elemente abfragen
        asked += 1
        if q in filt:
            false_positives += 1

    return {
        "run_id": f"{filter_name}-{load:.2f}-s{seed}",
        "filter": filter_name,
        "load": f"{load:.2f}",
        "seed": seed,
        "n_inserted": n_inserted,
        "n_insert_failed": n_failed,
        "n_queries": N_QUERIES,
        "false_positives": false_positives,
        "fpr": f"{false_positives / N_QUERIES:.6f}",
    }


def main():
    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    rows = []
    for filter_name in ("bloom", "cuckoo"):
        for load in LOADS:
            for seed in SEEDS:
                row = run_single(filter_name, load, seed)
                rows.append(row)
                print(
                    f"{row['run_id']:>22}  inserted={row['n_inserted']:>5}  "
                    f"fp={row['false_positives']:>4}  fpr={row['fpr']}"
                )
    with open(RESULTS_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n{len(rows)} Laeufe -> {os.path.relpath(RESULTS_PATH)}")


if __name__ == "__main__":
    main()
