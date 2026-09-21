"""VeriHarness/HoH adapter.

A Paper Factory node maps to one HoH run: planner → developer → independent
QA → receipts → accept/reject. Scientific meaning lives in the work-package
specification, not in HoH.

Hard policies (code-enforced, see state/concurrency_audit.json, O177):
- HoH NEVER runs against the caller's repository directly. PF materializes a
  dedicated, PF-owned git snapshot ("the clone") under
  <target>/.paper-factory/hoh-repo/ and runs HoH against that.
- Own runs root: <target>/.paper-factory/hoh-runs/ (never the shared default).
- run_ids carry the prefix PF-; PF serializes its own HoH runs with a lock.
- PF never pushes anywhere.
- blocked_kind is read from state.json directly (launcher verdict has the
  known usage_quota/usage_limit classification gap — launcher.py:48 vs
  stages.py:213).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...core.results import Verdict
from ...core.util import sha256_file, utcnow, write_json

RUN_PREFIX = "PF-"
_hoh_lock = threading.Lock()  # process-local; file lock below covers cross-process


@dataclass
class HohResult:
    run_id: str
    verdict: Verdict
    accepted: bool | None
    blocked_kind: str | None
    stage: str | None
    receipts: list[dict[str, Any]] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


class VeriharnessAdapter:
    def __init__(self, workspace, hoh_executable: str | None = None):
        self.ws = workspace
        self.hoh = hoh_executable or os.environ.get("HOH_EXECUTABLE") or self._find_hoh()
        self.runs_root = self.ws.sub("hoh-runs")
        self.clone_dir = self.ws.root / "hoh-repo"
        self._serial_lock_path = self.runs_root / ".pf-serial.lock"

    @staticmethod
    def _find_hoh() -> str:
        exe = shutil.which("hoh")
        if exe:
            return exe
        # paper-factory venv fallback
        cand = Path(__file__).resolve().parents[3] / ".venv" / "bin" / "hoh"
        return str(cand) if cand.exists() else "hoh"

    # -- environment ------------------------------------------------------
    def doctor(self) -> dict[str, Any]:
        out: dict[str, Any] = {"executable": self.hoh, "present": False, "herdr": False,
                               "bwrap": bool(shutil.which("bwrap"))}
        try:
            proc = subprocess.run([self.hoh, "--help"], capture_output=True, text=True, timeout=30)
            out["present"] = proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
        out["herdr"] = os.environ.get("HERDR_ENV") == "1" and bool(shutil.which("herdr"))
        if out["present"] and not out["herdr"]:
            out["note"] = "DEGRADED_RUNTIME: HoH requires HERDR_ENV=1 + herdr binary"
        return out

    # -- dedicated clone (O177 policy) ------------------------------------
    def ensure_clone(self) -> Path:
        """Materialize a PF-owned git snapshot of the target project.

        Never touches the original repo. If the target is a git repo we clone
        it; otherwise we create a fresh snapshot repo of the working files.
        """
        import fcntl

        if (self.clone_dir / ".git").exists():
            return self.clone_dir
        src = self.ws.target_root
        self.clone_dir.mkdir(parents=True, exist_ok=True)
        if (src / ".git").exists():
            subprocess.run(["git", "clone", "--quiet", str(src), str(self.clone_dir)],
                           check=True, timeout=600)
        else:
            exclude = {".paper-factory", ".git", "node_modules", "__pycache__", ".venv"}

            def ignore(d, names):
                return [n for n in names if n in exclude]

            tmp = self.clone_dir / ".incoming"
            if tmp.exists():
                shutil.rmtree(tmp)  # PF-owned scratch only
            shutil.copytree(src, tmp, ignore=ignore)
            for item in tmp.iterdir():
                shutil.move(str(item), self.clone_dir)
            tmp.rmdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.clone_dir, check=True)
            subprocess.run(["git", "-c", "user.name=paper-factory", "-c",
                            "user.email=pf@local", "add", "-A"], cwd=self.clone_dir, check=True)
            subprocess.run(["git", "-c", "user.name=paper-factory", "-c",
                            "user.email=pf@local", "commit", "-q", "-m",
                            "PF baseline snapshot"], cwd=self.clone_dir, check=True)
        return self.clone_dir

    # -- run lifecycle ------------------------------------------------------
    def _call(self, *args: str, timeout: int = 300) -> tuple[int, dict[str, Any] | str]:
        env = dict(os.environ, HOH_RUNS=str(self.runs_root))
        proc = subprocess.run([self.hoh, "--root", str(self.runs_root), *args],
                              capture_output=True, text=True, timeout=timeout, env=env)
        try:
            return proc.returncode, json.loads(proc.stdout)
        except json.JSONDecodeError:
            return proc.returncode, (proc.stdout.strip() or proc.stderr.strip())

    def verify_work_package(self, node_id: str, spec_path: Path, *,
                            planner: str = "claude", developer: str = "kimi",
                            qa: str = "codex", iterations: int = 1,
                            dry_run: bool = False) -> HohResult:
        """Map one PF node to one HoH run. Serialized per workspace."""
        run_id = f"{RUN_PREFIX}{node_id}-{utcnow().replace(':', '').replace('-', '')}"
        if dry_run:
            return HohResult(run_id=run_id, verdict=Verdict.NOT_RUN, accepted=None,
                             blocked_kind=None, stage=None,
                             detail={"dry_run": True, "spec": str(spec_path)})
        diag = self.doctor()
        if not diag["present"]:
            return HohResult(run_id, Verdict.UNAVAILABLE, None, None, None,
                             detail={"reason": "hoh executable not found"})
        if not diag["herdr"]:
            return HohResult(run_id, Verdict.DEGRADED, None, None, None,
                             detail={"reason": "DEGRADED_RUNTIME: herdr unavailable, HoH refused"})

        import fcntl

        self.ensure_clone()
        spec_in_clone = self.clone_dir / ".pf-specs" / f"{run_id}.md"
        spec_in_clone.parent.mkdir(parents=True, exist_ok=True)
        spec_in_clone.write_text(spec_path.read_text(encoding="utf-8"), encoding="utf-8")

        with open(self._serial_lock_path, "a+") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)  # one HoH run per workspace at a time
            try:
                rc, started = self._call("start", "--repo", str(self.clone_dir),
                                         "--spec", str(spec_in_clone), "--run-id", run_id)
                if rc != 0:
                    return HohResult(run_id, Verdict.FAIL, None, None, None,
                                     detail={"start_failed": started})
                rc, ran = self._call("run", run_id, "--iterations", str(iterations),
                                     "--planner", planner, "--developer", developer,
                                     "--qa", qa, timeout=7200)
            finally:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)

        state = self._read_state(run_id)
        receipts = self._collect_receipts(run_id)
        blocked_kind = state.get("blocked_kind")  # read directly, not the launcher verdict
        accepted = bool(state.get("last_accepted_candidate"))
        if blocked_kind:
            verdict = Verdict.DEGRADED if blocked_kind == "usage_limit" else Verdict.FAIL
        elif accepted:
            verdict = Verdict.PASS
        else:
            verdict = Verdict.FAIL
        detail = {"run_rc": rc, "run_summary": ran, "stage": state.get("stage"),
                  "condition": state.get("condition")}
        return HohResult(run_id, verdict, accepted, blocked_kind, state.get("stage"),
                         receipts=receipts, detail=detail)

    def _read_state(self, run_id: str) -> dict[str, Any]:
        p = self.runs_root / run_id / "state.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {}

    def _collect_receipts(self, run_id: str) -> list[dict[str, Any]]:
        out = []
        rdir = self.runs_root / run_id / "receipts"
        dest_dir = self.ws.receipts_dir / "hoh" / run_id
        if rdir.is_dir():
            for f in sorted(rdir.glob("*.json")):
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / f.name
                if not dest.exists():
                    shutil.copy2(f, dest)
                out.append({"receipt_file": f.name,
                            "copied_to": str(dest),
                            "sha256": sha256_file(dest)})
        return out
