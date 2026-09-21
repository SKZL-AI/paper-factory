#!/usr/bin/env python3
"""Aggregiert results/experiment_runs.csv zu results/summary.json.

Pro (filter, load)-Gruppe: n (Anzahl Laeufe), Mittelwert und
Stichproben-Standardabweichung der FPR. Nur Python-Stdlib.
"""

import csv
import json
import os
import statistics

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "..", "results", "experiment_runs.csv")
OUT_PATH = os.path.join(BASE_DIR, "..", "results", "summary.json")


def main():
    groups = {}
    with open(CSV_PATH, newline="") as f:
        for row in csv.DictReader(f):
            key = (row["filter"], float(row["load"]))
            groups.setdefault(key, []).append(float(row["fpr"]))

    records = []
    for (filter_name, load), fprs in sorted(groups.items()):
        records.append(
            {
                "filter": filter_name,
                "load": load,
                "n": len(fprs),
                "mean_fpr": statistics.fmean(fprs),
                "std_fpr": statistics.stdev(fprs) if len(fprs) > 1 else 0.0,
            }
        )

    summary = {
        "experiment": "bloom_vs_cuckoo_fpr_under_load",
        "source": "results/experiment_runs.csv",
        "grouping": "filter x load",
        "records": records,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")
    print(f"{len(records)} Gruppen -> {os.path.relpath(OUT_PATH)}")
    for r in records:
        print(
            f"  {r['filter']:>6} load={r['load']:.2f}  "
            f"mean_fpr={r['mean_fpr']:.6f}  std={r['std_fpr']:.6f}  n={r['n']}"
        )


if __name__ == "__main__":
    main()
