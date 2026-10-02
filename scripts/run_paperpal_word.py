#!/usr/bin/env python3
"""Orchestrator entry for the Word/Paperpal P31 session (consultant brief B/C).

The orchestrating agent runs this stepwise; every step writes a receipt into
the pilot's paperpal receipts dir. Nothing here fakes a state: each command
either carries proof (COM state, UIA result, screenshot file) or fails.

Usage (from the repo root):
  .venv/bin/python scripts/run_paperpal_word.py --root <project> open
  .venv/bin/python scripts/run_paperpal_word.py --root <project> shot <name>
  .venv/bin/python scripts/run_paperpal_word.py --root <project> click X Y
  .venv/bin/python scripts/run_paperpal_word.py --root <project> uia-click "Open Paperpal"
  .venv/bin/python scripts/run_paperpal_word.py --root <project> uia-find Grammar
  .venv/bin/python scripts/run_paperpal_word.py --root <project> state
  .venv/bin/python scripts/run_paperpal_word.py --root <project> save-copy
  .venv/bin/python scripts/run_paperpal_word.py --root <project> close
  .venv/bin/python scripts/run_paperpal_word.py --root <project> report <extra-json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paper_factory.paperpal.word.driver import (  # noqa: E402
    StepFailed, WordPaperpalAdapter, stage_docx, win_to_wsl, WIN_EXCHANGE)


def main() -> int:
    args = sys.argv[1:]
    root = Path(args[args.index("--root") + 1])
    rest = [a for a in args[2:] if a != "--root"]
    cmd = rest[0]
    receipts = root / ".paper-factory" / "paperpal" / "receipts"
    ad = WordPaperpalAdapter(receipts_dir=receipts)
    try:
        if cmd == "open":
            outbox = root / ".paper-factory" / "paperpal" / "outbox"
            docx = sorted(outbox.glob("paper-*.docx"),
                          key=lambda p: p.stat().st_mtime)[-1]
            win = stage_docx(docx)
            ad.record("DOCX_READY", True, f"{docx.name} staged -> {win}")
            print(ad.open_word(win))
        elif cmd == "shot":
            print(ad.screenshot(rest[1]))
        elif cmd == "wshot":
            print(ad.shot_window(rest[1]))
        elif cmd == "click":
            print(ad.click(int(rest[1]), int(rest[2])))
        elif cmd == "bg-click":
            print(ad.bg_click(int(rest[1]), int(rest[2])))
        elif cmd == "si-click":
            print(ad._ps("si-click", "-Arg1", rest[1], "-Arg2", rest[2]))
        elif cmd == "uia-click":
            print(ad.uia_click(rest[1]))
        elif cmd == "uia-click-owned":
            print(ad._ps("uia-click-owned", "-Arg1", rest[1], "-Arg2", rest[2]))
        elif cmd == "uia-find-owned":
            print(ad._ps("uia-find-owned", "-Arg1", rest[1], "-Arg2", rest[2]))
        elif cmd == "uia-find":
            print(ad.uia_find(rest[1]))
        elif cmd == "uia-dump":
            print(ad.uia_dump(rest[1] if len(rest) > 1 else ""))
        elif cmd == "uia-dump-scope":
            print(ad._ps("uia-dump-scope", "-Arg1", rest[1],
                         "-Arg2", rest[2] if len(rest) > 2 else ""))
        elif cmd == "park":
            print(ad.park())
        elif cmd == "unpark":
            print(ad.unpark())
        elif cmd == "state":
            print(ad.word_state())
        elif cmd == "save-copy":
            print(ad.save_copy(WIN_EXCHANGE + "\\" + rest[1]))
        elif cmd == "close":
            # ownership-scoped only: never a global Word close — without an
            # ownership record this refuses to touch Word at all
            print(ad.close_word_robust())
        elif cmd == "report":
            extra = json.loads(rest[1]) if len(rest) > 1 else {}
            p = ad.write_report(receipts / "paperpal_word_session.json", extra)
            print(f"report={p}")
        elif cmd == "deliver":
            # deliver <captured-report.json> <staged.docx> — production writer
            # for the inbox provenance sidecar (binds the report to the EXACT
            # staged DOCX sha256; never hand-write the sidecar)
            inbox = root / ".paper-factory" / "paperpal" / "inbox"
            print(f"delivered={ad.deliver(inbox, Path(rest[1]), Path(rest[2]))}")
        elif cmd == "mark":
            # mark STATE "detail" [receipt] — a verified transition made by
            # the orchestrator (e.g. PAPERPAL_VISIBLE after a screenshot)
            receipt = None
            if len(rest) > 3:
                receipt = receipts / rest[3]
            ad.record(rest[1], True, rest[2] if len(rest) > 2 else "",
                      receipt)
            print(f"marked {rest[1]}")
        else:
            print(f"unknown command: {cmd}", file=sys.stderr)
            return 2
        return 0
    except StepFailed as e:
        ad.record(e.state, False, e.detail)
        ad.write_report(receipts / "paperpal_word_session.json",
                        {"aborted": True, "failure": e.detail})
        print(f"FAILED {e.state}: {e.detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
