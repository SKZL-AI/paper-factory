"""P31 Word/Paperpal session driver — state machine with per-transition
receipts (consultant brief C).

Design (docs/PAPERPAL_AUTOMATION.md): Paper Factory orchestrates from WSL.
PowerShell/Word-COM covers deterministic document operations; UIA covers
ribbon/pane controls where reachable; screenshot+mouse is the verified
fallback. The orchestrating agent performs the vision loop between gated
steps — every transition is recorded with timestamp, status, UI identity,
receipt and optional screenshot, so the run is auditable and UI drift fails
loudly (HUMAN_REQUIRED), never silently.

    DOCX_READY → WORD_OPEN → PAPERPAL_VISIBLE → CHECK_CONFIGURED
      → CHECK_RUNNING → CHECK_COMPLETE → RESULT_CAPTURED → OUTPUT_SAVED
      → PROVENANCE_WRITTEN → INBOX_READY

v1 is deliberately CAPTURE-ONLY (consultant brief F): no 'accept all', the
checked document is not mutated. Suggestions are captured as classified
proposals; SCIENTIFIC_OR_AMBIGUOUS items are surfaced to U16/P36.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ...core.util import sha256_file, utcnow, write_json

PS1 = Path(__file__).with_name("pfword.ps1")

# Windows-side exchange directory (Word needs a local/UNC path it trusts;
# the WSL home is reachable but UNC-fragile — the hop through %USERPROFILE%
# is the robust lane). Only PF-owned files live there.
WIN_EXCHANGE = r"C:\Users\SAI\paperfactory-p31"

STATES = ["DOCX_READY", "WORD_OPEN", "PAPERPAL_VISIBLE", "CHECK_CONFIGURED",
          "CHECK_RUNNING", "CHECK_COMPLETE", "RESULT_CAPTURED",
          "OUTPUT_SAVED", "PROVENANCE_WRITTEN", "INBOX_READY"]


class StepFailed(RuntimeError):
    def __init__(self, state: str, detail: str):
        super().__init__(f"{state}: {detail}")
        self.state = state
        self.detail = detail


class PaperpalAdapter(Protocol):
    """Adapter interface — a computer-use worker (Hermes-style) can be added
    later behind the same contract; it is NOT a v1 dependency."""
    def run_check(self, docx: Path, inbox: Path) -> dict[str, Any]: ...


def wsl_to_win(p: Path) -> str:
    s = str(p)
    if s.startswith("/mnt/") and len(s) > 7 and s[6] == "/":
        drive = s[5].upper()
        return drive + ":" + s[6:].replace("/", "\\")
    raise ValueError(f"not a /mnt/<drive>/ path: {s}")


def win_to_wsl(p: str) -> Path:
    p = p.strip()
    return Path("/mnt/" + p[0].lower() + p[2:].replace("\\", "/"))


@dataclass
class Transition:
    state: str
    at: str
    ok: bool
    detail: str = ""
    receipt: str | None = None


@dataclass
class WordPaperpalAdapter:
    """The concrete v1 adapter. Drive it stepwise; each public method records
    its transition. The caller (agent or later worker) verifies screenshots
    between gated steps."""
    receipts_dir: Path
    transitions: list[Transition] = field(default_factory=list)

    def _ps(self, *args: str, timeout: int = 180) -> str:
        cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", wsl_to_win_ps1(), "-Verb", args[0], *args[1:]]
        out = subprocess.run(cmd, capture_output=True, timeout=timeout)
        # PowerShell 5.1 writes the console codepage, not UTF-8 — decode
        # leniently so a stray byte in a pane dump never kills the driver
        stdout = out.stdout.decode("utf-8", errors="replace")
        stderr = out.stderr.decode("utf-8", errors="replace")
        line = stdout.strip().splitlines()
        line = line[0].strip() if line else ""
        if not line.startswith("PFWORD OK"):
            raise StepFailed(args[0],
                             (line or stderr.strip() or "no output"))
        return line[len("PFWORD OK "):]

    def _ps_raw(self, command: str, timeout: int = 180) -> str:
        """Raw PowerShell -Command (no pfword.ps1 verb protocol). For COM
        operations that must not raise StepFailed (modal-dialog handling)."""
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True, timeout=timeout)
        return (out.stdout.decode("utf-8", errors="replace")
                + out.stderr.decode("utf-8", errors="replace")).strip()

    def record(self, state: str, ok: bool, detail: str = "",
               receipt: Path | None = None) -> None:
        self.receipts_dir.mkdir(parents=True, exist_ok=True)
        t = Transition(state=state, at=utcnow(), ok=ok, detail=detail,
                       receipt=str(receipt) if receipt else None)
        self.transitions.append(t)
        # append-only receipt log: each CLI step survives the process end
        with (self.receipts_dir / "transitions.jsonl").open("a",
                                                            encoding="utf-8") as fh:
            fh.write(json.dumps(t.__dict__) + "\n")

    # -- gated primitives ------------------------------------------------
    def open_word(self, win_docx: str) -> str:
        detail = self._ps("open", "-Arg1", win_docx)
        self.record("WORD_OPEN", True, detail)
        return detail

    def open_word_owned(self, win_docx: str, docx_sha256: str, run_id: str
                        ) -> dict[str, Any]:
        """Open the staged DOCX and persist the OWNERSHIP record:
        Word PID, exact document FullName, docx sha, run_id, whether Word
        pre-existed and which foreign documents were open. Every later
        cleanup action is scoped to this record — Paper Factory never
        touches a Word instance or document it cannot prove ownership of."""
        detail = self._ps("open-owned", "-Arg1", win_docx)
        m = re.match(r"pid=(\d+) hwnd=(\S+) doc=(.*?) runningBefore=(\S+) "
                     r"startedByPF=(\S+) foreign=(.*)$", detail)
        if not m:
            raise StepFailed("WORD_OPEN", f"unparseable open-owned: {detail[:200]}")
        ownership = {
            "word_pid": int(m.group(1)),
            "hwnd": m.group(2),
            "docx_fullname_win": m.group(3),
            "docx_sha256": docx_sha256,
            "run_id": run_id,
            # multi-process Word: ownership is per-PID — quitting OUR pid is
            # safe even when other WINWORD processes host foreign documents
            "word_running_before": m.group(4) == "True",
            "started_by_pf": m.group(5) == "True",
            "foreign_docs_at_open": [x for x in m.group(6).split(";") if x],
            "opened_at": utcnow(),
        }
        path = self.receipts_dir / "word_ownership.json"
        write_json(path, ownership)
        self.record("WORD_OPEN", True,
                    f"owned pid={ownership['word_pid']} doc={Path(m.group(3)).name} "
                    f"running_before={ownership['word_running_before']} "
                    f"foreign={len(ownership['foreign_docs_at_open'])}")
        return ownership

    def word_state(self) -> str:
        return self._ps("word-state")

    def word_docs(self) -> dict[str, Any]:
        """Read-only: open document FullNames across ALL Word processes (ROT
        enumeration — per-process COM would hide foreign documents)."""
        detail = self._ps("word-docs")
        m = re.match(r"docs=(.*)$", detail)
        docs = [x for x in m.group(1).split(";") if x] if m else []
        return {"docs": docs}

    def doc_open(self, fullname_win: str) -> bool:
        """True IFF this exact document is open in any Word process."""
        return "open=true" in self._ps("doc-open", "-Arg1", fullname_win)


    def screenshot(self, name: str) -> Path:
        win_path = WIN_EXCHANGE + "\\" + name
        self._ps("shot", "-Arg1", win_path)
        src = win_to_wsl(win_path)
        dst = self.receipts_dir / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        return dst

    def click(self, x: int, y: int) -> str:
        """LAST RESORT: moves the physical cursor. Prefer uia_click/bg_click —
        the operator may be using the machine (user requirement 2026-10-01)."""
        return self._ps("click", "-Arg1", str(x), "-Arg2", str(y))

    def bg_click(self, x: int, y: int) -> str:
        """PostMessage click — physical cursor never moves, no focus needed."""
        return self._ps("bg-click", "-Arg1", str(x), "-Arg2", str(y))

    def shot_window(self, name: str) -> Path:
        """PrintWindow capture of the Word window only — works even when
        another window covers it."""
        win_path = WIN_EXCHANGE + "\\" + name
        self._ps("shot-window", "-Arg1", win_path)
        src = win_to_wsl(win_path)
        dst = self.receipts_dir / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        return dst

    def uia_click(self, name: str) -> str:
        return self._ps("uia-click", "-Arg1", name)

    def uia_find(self, needle: str) -> str:
        return self._ps("uia-find", "-Arg1", needle)

    def uia_dump(self, needle: str = "") -> str:
        """Pixel-free pane verification (works parked/off-screen)."""
        return self._ps("uia-dump", "-Arg1", needle)

    def park(self) -> str:
        return self._ps("park")

    def unpark(self) -> str:
        return self._ps("unpark")

    def save_copy(self, win_target: str) -> str:
        return self._ps("saveas-copy", "-Arg1", win_target)

    def close_word(self) -> str:
        return self._ps("close")

    def close_word_robust(self, ownership: dict[str, Any] | None = None) -> str:
        """Close the OWNED staged DOCX without saving — scoped, never global.

        Ownership contract (release audit 2026-10-02): the record identifies
        the exact document (FullName + sha256), the Word PID and whether Word
        pre-existed with foreign documents. Cleanup rules:
          - close ONLY the document whose FullName matches the record
            (SaveChanges=0 — capture-only is never negotiable)
          - Quit the Word instance ONLY when Paper Factory opened Word itself
            (not word_running_before) AND no foreign documents remain
          - the modal-save-dialog fallback (UIA, cursor-free) is scoped to
            windows OWNED by the recorded PID — a global 'Nicht speichern'
            search could dismiss somebody else's dialog
          - if our document is not open or ownership is missing/unclear:
            fail closed, touch nothing
        """
        if ownership is None:
            o_path = self.receipts_dir / "word_ownership.json"
            ownership = json.loads(o_path.read_text(encoding="utf-8")) \
                if o_path.exists() else None
        if not ownership or not ownership.get("docx_fullname_win"):
            self.record("WORD_CLOSED", False, "no ownership record — nothing touched")
            return "FAILED: no ownership record — refusing to touch Word"
        fullname = ownership["docx_fullname_win"]
        pid = int(ownership.get("word_pid") or 0)
        # quit only a process PF itself started; an adopted/foreign instance
        # (or an ambiguous record) is never quit
        may_quit = "1" if ownership.get("started_by_pf") else "0"

        def _close_once() -> str:
            return self._ps("close-owned", "-Arg1", fullname, "-Arg2", may_quit)

        for attempt in range(3):
            try:
                rc = _close_once()
            except StepFailed as e:
                # modal dialog up → Word rejects COM (RPC_E_CALL_REJECTED);
                # dismiss ONLY dialogs owned by OUR pid
                if "our-doc-not-open" in str(e.detail):
                    self.record("WORD_CLOSED", False,
                                f"owned document not open: {e.detail}")
                    return f"FAILED: {e.detail}"
                dismissed = False
                for label in ("Nicht speichern", "Don't Save", "Don't save"):
                    try:
                        found = self._ps("uia-find-owned", "-Arg1", label,
                                         "-Arg2", str(pid))
                        if found.startswith("matches=") and len(found) > 9:
                            self._ps("uia-click-owned", "-Arg1", label,
                                     "-Arg2", str(pid))
                            dismissed = True
                            break
                    except StepFailed:
                        continue
                if not dismissed:
                    self.record("WORD_CLOSED", False,
                                "modal dialog present but none scoped to our pid")
                    return ("FAILED: modal save dialog not attributable to our "
                            "Word pid — left untouched")
                continue
            break
        else:
            self.record("WORD_CLOSED", False, "close attempts exhausted")
            return "FAILED: close attempts exhausted"

        # verify: our document must be gone; foreign documents must be intact
        state = self.word_docs()
        if fullname in state["docs"]:
            self.record("WORD_CLOSED", False, "owned document still open")
            return "FAILED: owned document still open"
        foreign_left = [d for d in ownership.get("foreign_docs_at_open", [])
                        if d in state["docs"]]
        if len(foreign_left) != len(ownership.get("foreign_docs_at_open", [])):
            self.record("WORD_CLOSED", False,
                        f"foreign documents changed: {ownership.get('foreign_docs_at_open')} "
                        f"→ now {state['docs']}")
            return "FAILED: foreign document set changed — incident"
        self.record("WORD_CLOSED", True,
                    f"owned doc closed; foreign docs intact ({len(foreign_left)}); "
                    f"word {'quit (owned instance)' if not state['docs'] else 'left running'}")
        return "closed"

    # -- report ------------------------------------------------------------
    def write_report(self, path: Path, extra: dict[str, Any]) -> Path:
        log = self.receipts_dir / "transitions.jsonl"
        all_t = ([json.loads(x) for x in log.read_text().splitlines() if x.strip()]
                 if log.exists() else [])
        report = {
            "generated_at": utcnow(),
            "adapter": "WordPaperpalAdapter/v1 (capture-only)",
            "states_reached": [t["state"] for t in all_t if t.get("ok")],
            "transitions": all_t,
            **extra,
        }
        write_json(path, report)
        return path

    def deliver(self, inbox: Path, report: Path, staged_docx: Path) -> Path:
        """Production writer for the exact-artifact binding (reviewer B3):
        copy the captured Paperpal report into the bridge inbox and write the
        provenance sidecar bound to the EXACT staged DOCX sha256 — never let
        a human/agent hand-write `docx_sha256_staged` (the value must come
        from the artifact that actually went through Word)."""
        import shutil

        inbox.mkdir(parents=True, exist_ok=True)
        target = inbox / report.name
        shutil.copy2(report, target)
        sha = sha256_file(staged_docx)
        write_json(target.with_name(target.name + ".provenance.json"), {
            "source": "paperpal",
            "docx_sha256_staged": sha,
            "staged_docx": staged_docx.name,
            "delivered_at": utcnow(),
            "delivered_by": "WordPaperpalAdapter/v1",
        })
        self.record("INBOX_READY", True,
                    f"{target.name} bound to {staged_docx.name} ({sha[:12]}…)")
        return target


def wsl_to_win_ps1() -> str:
    """The ps1 asset lives in the WSL repo; copy it to the Windows exchange
    dir (powershell.exe can also read UNC paths, but local is robust) and
    return its Windows path."""
    dst = win_to_wsl(WIN_EXCHANGE)
    dst.mkdir(parents=True, exist_ok=True)
    target = dst / "pfword.ps1"
    target.write_bytes(PS1.read_bytes())
    return WIN_EXCHANGE + "\\pfword.ps1"


def stage_docx(docx: Path) -> str:
    """Copy the versioned outbox DOCX to the Windows exchange dir; return the
    Windows path. The pilot file itself is never touched by Word."""
    dst = win_to_wsl(WIN_EXCHANGE)
    dst.mkdir(parents=True, exist_ok=True)
    target = dst / docx.name
    target.write_bytes(docx.read_bytes())
    return WIN_EXCHANGE + "\\" + docx.name
