"""Mirror the final deliverables to the Windows project folder (report target
only — never deletes, never overwrites existing files there).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path("/home/sai/paper-factory")
TARGET_BASE = Path("/mnt/c/SAI_AI_MAIN_LAB/PROJEKTE/Paper_factory")
STAMP = "RESULTS_2026-09-22"

ITEMS = [
    "README.md",
    "INSTALLATION_REPORT.md",
    "VERIHARNESS_GAP_REPORT.md",
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
