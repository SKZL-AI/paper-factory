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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...core.results import Verdict
from ...core.util import sha256_file, utcnow, write_json
from ...provenance.firewall import PolicyViolation
from ...verification.capabilities import CapabilityStatus, declare
from ...verification.contract import BackendIdentity, VerificationResult, WorkPackage
from ...verification.registry import VerificationBackend

RUN_PREFIX = "PF-"


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
        self._version: str | None = None

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
        out: dict[str, Any] = {
            "executable": self.hoh,
            "present": False,
            "herdr": False,
            "bwrap": bool(shutil.which("bwrap")),
        }
        try:
            proc = subprocess.run(
                [self.hoh, "--help"], capture_output=True, text=True, timeout=30, check=False
            )
            out["present"] = proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
        out["herdr"] = os.environ.get("HERDR_ENV") == "1" and bool(shutil.which("herdr"))
        if out["present"] and not out["herdr"]:
            out["note"] = "DEGRADED_RUNTIME: HoH requires HERDR_ENV=1 + herdr binary"
        return out

    # -- generic verification-plane façade (plan §4, Phase 4) --------------
    def identity(self) -> BackendIdentity:
        diag = self.doctor()
        return BackendIdentity(
            kind="veriharness",
            name="hoh",
            version=self._hoh_version(),
            detail={"herdr": bool(diag["herdr"]), "bwrap": bool(diag["bwrap"])},
        )

    def _hoh_version(self) -> str:
        if self._version is None:
            self._version = "unknown"
            try:
                proc = subprocess.run(
                    [self.hoh, "--version"], capture_output=True, text=True, timeout=30, check=False
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    self._version = proc.stdout.strip().splitlines()[0].split()[-1]
            except (OSError, subprocess.TimeoutExpired):
                pass
        return self._version

    def capabilities(self):
        """Derived from the existing doctor probe — no parallel discovery."""
        diag = self.doctor()
        backend = self.identity()
        if not diag["present"]:
            return [
                declare(backend, "verify", CapabilityStatus.UNAVAILABLE, "hoh executable not found")
            ]
        missing = []
        if not diag["herdr"]:
            missing.append("herdr runtime (HERDR_ENV=1 + herdr binary)")
        if not diag["bwrap"]:
            missing.append("bwrap sandbox")
        if missing:
            return [
                declare(backend, "verify", CapabilityStatus.SUPPORTED_DEGRADED, "; ".join(missing))
            ]
        return [declare(backend, "verify", CapabilityStatus.SUPPORTED)]

    def verify(self, package: WorkPackage) -> VerificationResult:
        """Generic façade: one HoH run per WorkPackage (module policy applies).

        HoH specifics (run_id, blocked_kind, stage/condition/rc summary) stay
        out of the core contract fields — they live in BackendIdentity.detail
        and failure_reason, never as new contract fields.
        """
        import uuid

        run_id = f"{RUN_PREFIX}{uuid.uuid4().hex[:8]}-{package.node_id}"
        backend = self.identity()
        started_at = datetime.now(UTC)

        def result(
            verdict: Verdict,
            *,
            failure_reason: str | None = None,
            hoh: HohResult | None = None,
            hoh_detail: dict[str, Any] | None = None,
        ) -> VerificationResult:
            detail = dict(backend.detail)
            detail["run_id"] = run_id
            if hoh is not None:
                detail["blocked_kind"] = hoh.blocked_kind
                detail["hoh_detail"] = hoh.detail
            elif hoh_detail is not None:
                detail["hoh_detail"] = hoh_detail
            res_backend = backend.model_copy(update={"detail": detail})
            return VerificationResult(
                package_id=package.package_id,
                backend=res_backend,
                verdict=verdict,
                artifact_sha256=package.artifacts[0].sha256 if package.artifacts else None,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                failure_reason=failure_reason,
                raw_receipt_refs=[r["copied_to"] for r in hoh.receipts] if hoh else [],
            )

        diag = self.doctor()
        if not diag["present"]:
            reason = "hoh executable not found"
            return result(Verdict.UNAVAILABLE, failure_reason=reason, hoh_detail={"reason": reason})
        if not diag["herdr"]:
            reason = "DEGRADED_RUNTIME: herdr unavailable, HoH refused"
            return result(Verdict.DEGRADED, failure_reason=reason, hoh_detail={"reason": reason})

        hoh = self._execute(run_id, package.spec_markdown)
        if hoh.verdict == Verdict.PASS:
            return result(Verdict.PASS, hoh=hoh)
        if hoh.blocked_kind:
            reason = f"HoH run blocked: {hoh.blocked_kind}"
            if hoh.stage:
                reason = f"{reason} (stage {hoh.stage})"
            return result(hoh.verdict, failure_reason=reason, hoh=hoh)
        return result(hoh.verdict, hoh=hoh)

    # -- dedicated clone (O177 policy) ------------------------------------
    def ensure_clone(self) -> Path:
        """Materialize a PF-owned git snapshot of the target project.

        Hard invariants (adversarial-review hardened):
        - the clone must be a REAL directory under the workspace root
          (symlinks are rejected — a symlinked clone would silently run HoH
          against the original, violating the O177 policy);
        - the clone is refreshed when the source changed since the snapshot
          (a stale clone would verify stale code while producing
          valid-looking receipts).
        """
        if self.clone_dir.is_symlink():
            raise PolicyViolation(f"hoh-repo clone must not be a symlink: {self.clone_dir}")
        if self.clone_dir.exists() and not self.clone_dir.resolve().is_relative_to(
            self.ws.root.resolve()
        ):
            raise PolicyViolation(f"hoh-repo clone escapes the workspace: {self.clone_dir}")

        src = self.ws.target_root
        src_fingerprint = self._source_fingerprint(src)
        marker = self.runs_root / "clone-manifest.json"
        if (self.clone_dir / ".git").exists():
            if marker.exists():
                import json as _json

                old = _json.loads(marker.read_text())
                if old.get("source_fingerprint") == src_fingerprint:
                    return self.clone_dir
                # stale clone: park it, snapshot fresh (never delete)
                parked = self.clone_dir.with_name(
                    self.clone_dir.name + f".v1.{utcnow().replace(':', '')}"
                )
                self.clone_dir.rename(parked)
            else:
                return self.clone_dir  # pre-manifest clone from an earlier version
        self.clone_dir.mkdir(parents=True, exist_ok=True)
        if (src / ".git").exists():
            subprocess.run(
                ["git", "clone", "--quiet", str(src), str(self.clone_dir)], check=True, timeout=600
            )
        else:
            exclude = {".paper-factory", ".git", "node_modules", "__pycache__", ".venv"}

            def ignore(d, names):
                return [n for n in names if n in exclude]

            tmp = self.clone_dir / ".incoming"
            if tmp.exists():
                tmp.rename(self.clone_dir / f".incoming.parked.{utcnow().replace(':', '')}")
            shutil.copytree(src, tmp, ignore=ignore)
            for item in tmp.iterdir():
                shutil.move(str(item), self.clone_dir)
            tmp.rmdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.clone_dir, check=True)
            subprocess.run(
                ["git", "-c", "user.name=paper-factory", "-c", "user.email=pf@local", "add", "-A"],
                cwd=self.clone_dir,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=paper-factory",
                    "-c",
                    "user.email=pf@local",
                    "commit",
                    "-q",
                    "-m",
                    "PF baseline snapshot",
                ],
                cwd=self.clone_dir,
                check=True,
            )
        self.runs_root.mkdir(parents=True, exist_ok=True)
        (self.runs_root / "clone-manifest.json").write_text(
            json.dumps(
                {"created_at": utcnow(), "source": str(src), "source_fingerprint": src_fingerprint}
            ),
            encoding="utf-8",
        )
        return self.clone_dir

    @staticmethod
    def _source_fingerprint(src: Path) -> str:
        """Content fingerprint of the target's tracked-relevant files (cheap:
        path + size + mtime). Detects 'source changed since snapshot'."""
        import hashlib

        h = hashlib.sha256()
        exclude = {".paper-factory", ".git", "node_modules", "__pycache__", ".venv"}
        for p in sorted(src.rglob("*")):
            if not p.is_file() or any(part in exclude for part in p.parts):
                continue
            st = p.stat()
            h.update(f"{p.relative_to(src)}|{st.st_size}|{int(st.st_mtime)}|".encode())
        return h.hexdigest()

    # -- run lifecycle ------------------------------------------------------
    def _call(self, *args: str, timeout: int = 300) -> tuple[int, dict[str, Any] | str]:
        env = dict(os.environ, HOH_RUNS=str(self.runs_root))
        proc = subprocess.run(
            [self.hoh, "--root", str(self.runs_root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        try:
            return proc.returncode, json.loads(proc.stdout)
        except json.JSONDecodeError:
            return proc.returncode, (proc.stdout.strip() or proc.stderr.strip())

    def verify_work_package(
        self,
        node_id: str,
        spec_path: Path,
        *,
        planner: str = "claude",
        developer: str = "kimi",
        qa: str = "codex",
        iterations: int = 1,
        dry_run: bool = False,
    ) -> HohResult:
        """Legacy façade for dag/handlers.py — one run flow, two façades.

        Builds a WorkPackage from the legacy parameters, delegates to the
        generic verify(), and maps VerificationResult back onto HohResult so
        existing consumers keep identical fields (run_id/verdict/accepted/
        blocked_kind/receipts/detail).
        """
        import uuid

        run_id = f"{RUN_PREFIX}{uuid.uuid4().hex[:8]}-{node_id}"
        if dry_run:
            return HohResult(
                run_id=run_id,
                verdict=Verdict.NOT_RUN,
                accepted=None,
                blocked_kind=None,
                stage=None,
                detail={"dry_run": True, "spec": str(spec_path)},
            )
        package = WorkPackage(
            package_id=f"wp-{node_id}-{uuid.uuid4().hex[:8]}",
            node_id=node_id,
            spec_markdown=spec_path.read_text(encoding="utf-8"),
        )
        res = self.verify(package)
        hoh_detail = dict(res.backend.detail.get("hoh_detail") or {})
        executed = "run_rc" in hoh_detail
        receipts = [
            {"receipt_file": Path(p).name, "copied_to": p, "sha256": sha256_file(Path(p))}
            for p in res.raw_receipt_refs
        ]
        return HohResult(
            run_id=res.backend.detail.get("run_id", run_id),
            verdict=res.verdict,
            accepted=True if res.verdict == Verdict.PASS else (False if executed else None),
            blocked_kind=res.backend.detail.get("blocked_kind"),
            stage=hoh_detail.get("stage"),
            receipts=receipts,
            detail=hoh_detail,
        )

    def _execute(
        self,
        run_id: str,
        spec_text: str,
        *,
        planner: str = "claude",
        developer: str = "kimi",
        qa: str = "codex",
        iterations: int = 1,
    ) -> HohResult:
        """Shared HoH run flow behind both façades. Serialized per workspace.

        run_id scheme: PF-<rand8>-<node> — the random part sits BEFORE the
        truncation point of herdr's agent-name derivation (observed truncation
        ~24 chars: 'hoh-pf-p05-20260-planner'), so names stay unique per run.
        """
        import fcntl

        self.ensure_clone()
        spec_in_clone = self.clone_dir / ".pf-specs" / f"{run_id}.md"
        spec_in_clone.parent.mkdir(parents=True, exist_ok=True)
        spec_in_clone.write_text(spec_text, encoding="utf-8")

        with open(self._serial_lock_path, "a+") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)  # one HoH run per workspace at a time
            try:
                rc, started = self._call(
                    "start",
                    "--repo",
                    str(self.clone_dir),
                    "--spec",
                    str(spec_in_clone),
                    "--run-id",
                    run_id,
                )
                if rc != 0:
                    return HohResult(
                        run_id, Verdict.FAIL, None, None, None, detail={"start_failed": started}
                    )
                rc, ran = self._call(
                    "run",
                    run_id,
                    "--iterations",
                    str(iterations),
                    "--planner",
                    planner,
                    "--developer",
                    developer,
                    "--qa",
                    qa,
                    timeout=7200,
                )
            finally:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)

        state = self._read_state(run_id)
        receipts = self._collect_receipts(run_id)
        self._cleanup_panes(run_id, state)
        blocked_kind = state.get("blocked_kind")  # read directly, not the launcher verdict
        accepted = bool(state.get("last_accepted_candidate"))
        if blocked_kind:
            verdict = Verdict.DEGRADED if blocked_kind == "usage_limit" else Verdict.FAIL
        elif accepted:
            verdict = Verdict.PASS
        else:
            verdict = Verdict.FAIL
        detail = {
            "run_rc": rc,
            "run_summary": ran,
            "stage": state.get("stage"),
            "condition": state.get("condition"),
        }
        return HohResult(
            run_id,
            verdict,
            accepted,
            blocked_kind,
            state.get("stage"),
            receipts=receipts,
            detail=detail,
        )

    def _read_state(self, run_id: str) -> dict[str, Any]:
        p = self.runs_root / run_id / "state.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {}

    def _cleanup_panes(self, run_id: str, state: dict[str, Any]) -> None:
        """Close Herdr tabs THIS run spawned. Provenance guard: a tab is
        closed only if its id contains this run's run_id (HoH embeds the run
        id in agent/tab names, e.g. 'hoh-pf-<rand8>-<node>-<role>'), matched
        case-insensitively. Tabs failing the guard are treated as foreign,
        NOT closed, and recorded as skipped_foreign — never silently dropped.
        Failure to clean is recorded, not fatal."""
        tabs = {
            t.get("herdr_tab_id") for t in state.get("active_tasks", []) if t.get("herdr_tab_id")
        }
        if not tabs or not shutil.which("herdr"):
            return
        own_run = run_id.lower()
        closed, failed, skipped_foreign = [], [], []
        for tab_id in sorted(tabs):
            if own_run not in tab_id.lower():
                skipped_foreign.append(
                    {"tab_id": tab_id, "reason": f"tab id does not contain run id {run_id}"}
                )
                continue
            proc = subprocess.run(
                ["herdr", "tab", "close", tab_id],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            (closed if proc.returncode == 0 else failed).append(tab_id)
        if closed or failed or skipped_foreign:
            write_json(
                self.runs_root / f"{run_id}.pane_cleanup.json",
                {
                    "at": utcnow(),
                    "closed": closed,
                    "failed": failed,
                    "skipped_foreign": skipped_foreign,
                },
            )

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
                out.append(
                    {"receipt_file": f.name, "copied_to": str(dest), "sha256": sha256_file(dest)}
                )
        return out


def register_veriharness(backends: dict[str, VerificationBackend], workspace) -> VeriharnessAdapter:
    """Register a VeriharnessAdapter under "veriharness" in a registry dict.

    Lives here (and is called from the outside) so verification/registry.py
    never imports this adapter — optional-dependency and circularity
    avoidance. A missing HoH installation is not an error at registration
    time; it surfaces honestly via identity()/capabilities()/verify().
    """
    adapter = VeriharnessAdapter(workspace)
    backends["veriharness"] = adapter
    return adapter
