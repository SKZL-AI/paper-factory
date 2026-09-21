# PF-P05: Result integrity of the synthetic filter benchmark

Work package: add a `VERIFICATION.md` to this repository that documents
exactly how the experiment results are reproduced (commands, expected
artifacts). Keep it factual and short.

## Acceptance criteria
- K1: `python3 code/analyze.py` exits 0 (analysis reproduces)
- K2: `test -s results/summary.json` (result artifact exists)
- K3: `test -s VERIFICATION.md` (documentation written)
- K4: `grep -q analyze VERIFICATION.md` (docs name the analysis)
