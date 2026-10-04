"""Mirror the final deliverables to the Windows project folder (report target
only — never deletes, never overwrites existing files there).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGET_BASE_RAW = os.environ.get("PF_MIRROR_TARGET")
if not TARGET_BASE_RAW:
    raise SystemExit("set PF_MIRROR_TARGET (Windows mirror root) — no default")
TARGET_BASE = Path(TARGET_BASE_RAW)
STAMP = "RESULTS_2026-09-22"

ITEMS = [
    "README.md",
    "docs/reports/INSTALLATION_REPORT.md",
    "docs/reports/VERIHARNESS_GAP_REPORT.md",
    "AGENTS.md",
    "pyproject.toml",
    "docs",
    "dashboard",
    "frontends",
    "paper_factory/state",
]


def main() -> int:
    dest = TARGET_BASE / STAMP
    if dest.exists():
        print(f"Ziel existiert bereits — parke nichts zweimal: {dest}")
        return 1
    dest.mkdir(parents=True)
    copied = []
    for item in ITEMS:
        src = REPO / item
        if not src.exists():
            print(f"  skip (fehlt): {item}")
            continue
        d = dest / item
        if src.is_dir():
            shutil.copytree(src, d, ignore=shutil.ignore_patterns("__pycache__", "bootstrap_smoke"))
        else:
            shutil.copy2(src, d)
        copied.append(item)
    # dashboard screenshot for convenience
    shot = Path("/tmp/pf-dashboard2.png")
    if shot.exists():
        shutil.copy2(shot, dest / "dashboard" / "dashboard-preview.png")
    print(f"gespiegelt nach {dest}: {len(copied)} Einträge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
