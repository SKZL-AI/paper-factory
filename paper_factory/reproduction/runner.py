"""Native local runner for Reproduction Capsules (WP5).

Executes a capsule with a plain subprocess in `capsule_root / cwd`, verifies
declared input/code/config hashes before launch, hashes produced outputs
afterwards and emits an honest ExecutionReceipt.

Declared vs. discovered access — what this runner does and does NOT detect:

- DECLARED INPUT: every code/config/input ref in the capsule is verified
  (exists + sha256 matches) *before* the process starts. A mismatch raises
  CapsuleIntegrityError; nothing runs against silently wrong inputs.
- DISCOVERED/UNDECLARED OUTPUT (best-effort, fail-visible): the runner
  snapshots (path, mtime_ns, size) of the cwd subtree before the run and
  compares afterwards. Files that are new or modified and match no
  expected_outputs pattern raise UndeclaredOutputError — including declared
  refs: a computation that rewrites its own inputs/config/code is exactly
  what must not pass silently. DELETIONS are detected the same way (review
  B-MINOR-1, 2026-10-05): a file present before and gone afterwards is an
  undeclared output event (the process consumed/destroyed evidence), unless
  it matches an expected_outputs pattern — an output the process wrote and
  then removed again is the differential's missing-output problem, not a
  hidden side effect. A process that deletes a declared input raises.
- HARD LIMITS (documented, not hidden): this is NOT a sandbox. A process that
  writes outside the cwd subtree, mutates a file while preserving
  (mtime_ns, size), touches the network, or reads undeclared inputs elsewhere
  on the filesystem is NOT detected. The capsule is a declaration of intent
  with pre-flight binding and post-hoc output evidence — not an isolation
  boundary. System-level capture (ReproZip-class tooling) is a v1.4+ decision
  gate per docs/ROADMAP.md and must never be retro-implied from this runner.
"""
from __future__ import annotations

import fnmatch
import hashlib
import subprocess
import uuid
from pathlib import Path

from ..verification.contract import BackendIdentity
from .capsule import (
    ExecutionReceipt,
    FileRef,
    ReproductionCapsule,
    sha256_file,
    utcnow,
)


class CapsuleIntegrityError(RuntimeError):
    """A declared code/config/input ref is missing or its sha256 mismatches."""


class UndeclaredOutputError(RuntimeError):
    """The process created, modified or deleted files outside expected_outputs."""


def _native_backend() -> BackendIdentity:
    return BackendIdentity(kind="pf_native", name="local-reproduction-runner",
                           version="0.1.0")


class LocalReproductionRunner:
    """Runs a ReproductionCapsule locally and produces an ExecutionReceipt."""

    def __init__(self, backend: BackendIdentity | None = None) -> None:
        self._backend = backend or _native_backend()

    # -- pre-flight -------------------------------------------------------- #

    def _verify_declared_refs(self, capsule: ReproductionCapsule,
                              root: Path) -> None:
        for group_name, refs in (
            ("code", capsule.code_refs),
            ("config", capsule.config_refs),
            ("input", capsule.input_refs),
        ):
            for ref in refs:
                path = root / ref.rel_path
                if not path.is_file():
                    raise CapsuleIntegrityError(
                        f"declared {group_name} ref missing: {ref.rel_path}")
                actual = sha256_file(path)
                if actual != ref.sha256:
                    raise CapsuleIntegrityError(
                        f"declared {group_name} ref hash mismatch: {ref.rel_path} "
                        f"(capsule {ref.sha256}, on-disk {actual})")

    @staticmethod
    def _snapshot_subtree(workdir: Path) -> dict[str, tuple[int, int]]:
        """rel_path -> (mtime_ns, size) for every file under workdir."""
        snap: dict[str, tuple[int, int]] = {}
        for path in sorted(workdir.rglob("*")):
            if path.is_file():
                st = path.stat()
                snap[path.relative_to(workdir).as_posix()] = (st.st_mtime_ns, st.st_size)
        return snap

    # -- main entry -------------------------------------------------------- #

    def run(self, capsule: ReproductionCapsule, capsule_root,
            timeout: float = 120.0) -> ExecutionReceipt:
        """Execute `capsule` with root directory `capsule_root`. Raises
        CapsuleIntegrityError / UndeclaredOutputError (fail-visible); a
        process-side failure (nonzero exit, timeout) is recorded in the
        receipt with status failed/timeout instead of raising."""
        root = Path(capsule_root).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"capsule_root is not a directory: {root}")
        workdir = (root / capsule.cwd).resolve()
        if not workdir.is_dir():
            raise FileNotFoundError(f"capsule cwd is not a directory: {workdir}")
        self._verify_declared_refs(capsule, root)
        before = self._snapshot_subtree(workdir)

        started = utcnow()
        try:
            proc = subprocess.run(
                list(capsule.command), cwd=workdir,
                capture_output=True, timeout=timeout, check=False,
            )
            status = "completed" if proc.returncode == 0 else "failed"
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
            failure_reason = None if proc.returncode == 0 else (
                f"command exited with code {proc.returncode}")
        except subprocess.TimeoutExpired as exc:
            status, exit_code = "timeout", None
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            failure_reason = f"timeout after {timeout}s"
        finished = utcnow()

        outputs = self._collect_outputs(capsule, root)
        self._check_undeclared(capsule, root, workdir, before)

        return ExecutionReceipt(
            receipt_id=f"rcpt-{uuid.uuid4().hex}",
            execution_id=f"exec-{uuid.uuid4().hex}",
            capsule_id=capsule.capsule_id,
            capsule_digest=capsule.capsule_digest,
            status=status,
            exit_code=exit_code,
            outputs=outputs,
            stdout_sha256=hashlib.sha256(stdout).hexdigest(),
            stderr_sha256=hashlib.sha256(stderr).hexdigest(),
            backend=self._backend,
            started_at=started,
            finished_at=finished,
            failure_reason=failure_reason,
        )

    # -- post-hoc ---------------------------------------------------------- #

    def _collect_outputs(self, capsule: ReproductionCapsule,
                         root: Path) -> list[FileRef]:
        """Hash every file matching an expected_outputs pattern (patterns are
        relative to the capsule root, fnmatch/glob syntax)."""
        found: dict[str, FileRef] = {}
        for pattern in capsule.expected_outputs:
            for path in sorted(root.glob(pattern)):
                if path.is_file():
                    found[path.relative_to(root).as_posix()] = FileRef(
                        rel_path=path.relative_to(root).as_posix(),
                        sha256=sha256_file(path))
        return sorted(found.values(), key=lambda f: f.rel_path)

    def _check_undeclared(self, capsule: ReproductionCapsule, root: Path,
                          workdir: Path,
                          before: dict[str, tuple[int, int]]) -> None:
        after = self._snapshot_subtree(workdir)
        expected_prefix = "" if capsule.cwd == "." else \
            workdir.relative_to(root).as_posix() + "/"

        def is_expected(rel_to_workdir: str) -> bool:
            rel_to_root = expected_prefix + rel_to_workdir
            return any(fnmatch.fnmatch(rel_to_root, p)
                       for p in capsule.expected_outputs)

        undeclared = sorted(
            rel for rel, stat in after.items()
            if before.get(rel) != stat and not is_expected(rel)
        )
        # deletions: present before, gone after. Expected-output removals
        # are tolerated (a removed expected output surfaces honestly as a
        # missing output in the differential); anything else the process
        # destroyed (e.g. a declared input) is an undeclared output event.
        undeclared += sorted(
            rel for rel in before
            if rel not in after and not is_expected(rel)
        )
        if undeclared:
            raise UndeclaredOutputError(
                "process created, modified or deleted files outside "
                f"expected_outputs (undeclared outputs): {undeclared}. Declare "
                "them in the capsule or remove the side effect.")
