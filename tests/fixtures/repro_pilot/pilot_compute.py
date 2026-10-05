"""Deterministic synthetic reproduction pilot (WP5, reusable for WP12/backend
conformance). Reads input.csv (columns: name,value), computes summary
statistics and writes summary.json + table.txt. No randomness, no clocks, no
environment dependence — the same capsule run twice must produce identical
output hashes. Pure stdlib; no network, no LLM."""

import csv
import json
from pathlib import Path

root = Path(__file__).resolve().parent

values = []
with open(root / "input.csv", newline="", encoding="utf-8") as fh:
    for row in csv.DictReader(fh):
        values.append(float(row["value"]))

values.sort()
n = len(values)
mean = sum(values) / n

summary = {
    "n": n,
    "mean": round(mean, 6),
    "min": values[0],
    "max": values[-1],
    "spread": round(values[-1] - values[0], 6),
}
(root / "summary.json").write_text(
    json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")

lines = ["metric\tvalue"]
for key in sorted(summary):
    lines.append(f"{key}\t{summary[key]}")
(root / "table.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
