"""First unit tests for the VeriHarness adapter (plan §3, Phase 4) — all mocked.

No real hoh/herdr/subprocess effects anywhere: ``subprocess.run`` and
``shutil.which`` are faked per test, HERDR_ENV is controlled via monkeypatch,
and ``ensure_clone`` is stubbed for run-flow tests (the real clone logic is
exercised separately by the policy tests, which raise before any git call).
The flock test deliberately uses a REAL fcntl lock to document the actual
blocking behavior of the production code.
"""

from __future__ import annotations

import fcntl
import json
import re
import subprocess
import threading
import time
from pathlib import Path

import pytest

from paper_factory.adapters.veriharness import adapter as adapter_mod
from paper_factory.adapters.veriharness.adapter import (
    HohResult,
    VeriharnessAdapter,
    register_veriharness,
)
from paper_factory.core.results import Verdict
from paper_factory.provenance.firewall import PolicyViolation
from paper_factory.state.store import Workspace
from paper_factory.verification import registry
from paper_factory.verification.capabilities import CapabilityStatus
from paper_factory.verification.contract import ArtifactRef, WorkPackage

SHA = "a" * 64
RUN_ID_RE = re.compile(r"PF-[0-9a-f]{8}-P05")


class _Proc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeEnv:
    """Mocked execution environment for one adapter instance."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        hoh_present: bool = True,
        herdr: bool = True,
        bwrap: bool = True,
        version_ok: bool = True,
    ):
        self.target = tmp_path / "target"
        self.target.mkdir(parents=True)
        (self.target / "code").mkdir()
        self.target.joinpath("code", "analyze.py").write_text("print(1)\n", encoding="utf-8")
        self.ws = Workspace(self.target)
        self.adapter = VeriharnessAdapter(self.ws, hoh_executable="/fake/bin/hoh")
        self.calls: list[list[str]] = []
        self.scenario: dict = {
            "blocked_kind": None,
            "accepted": True,
            "stage": "qa",
            "condition": "ok",
        }
        self._hoh_present = hoh_present
        self._version_ok = version_ok

        def fake_run(cmd, **kw):
            self.calls.append(list(cmd))
            return self._route(list(cmd))

        def fake_which(name):
            if name == "herdr":
                return "/fake/bin/herdr" if herdr else None
            if name == "bwrap":
                return "/fake/bin/bwrap" if bwrap else None
            return None

        monkeypatch.setattr(adapter_mod.subprocess, "run", fake_run)
        monkeypatch.setattr(adapter_mod.shutil, "which", fake_which)
        if herdr:
            monkeypatch.setenv("HERDR_ENV", "1")
        else:
            monkeypatch.delenv("HERDR_ENV", raising=False)

    def _route(self, cmd: list[str]) -> _Proc:
        exe = Path(cmd[0]).name
        if exe == "hoh":
            if "--help" in cmd:
                return _Proc(0 if self._hoh_present else 2, "usage: hoh")
            if "--version" in cmd:
                return _Proc(0 if self._version_ok else 1, "hoh 0.1.0\n")
            if "start" in cmd:
                return _Proc(0, json.dumps({"started": cmd[cmd.index("--run-id") + 1]}))
            if "run" in cmd:
                root = Path(cmd[cmd.index("--root") + 1])
                run_id = cmd[cmd.index("run") + 1]
                self._write_run_state(root, run_id)
                return _Proc(0, json.dumps({"done": True}))
        if exe == "herdr":
            return _Proc(0, "")
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    def _write_run_state(self, root: Path, run_id: str) -> None:
        rdir = root / run_id
        (rdir / "receipts").mkdir(parents=True, exist_ok=True)
        (rdir / "receipts" / "receipt1.json").write_text('{"ok": true}\n', encoding="utf-8")
        state = {
            "stage": self.scenario.get("stage"),
            "condition": self.scenario.get("condition"),
            "blocked_kind": self.scenario["blocked_kind"],
            "last_accepted_candidate": ("cand-1" if self.scenario["accepted"] else None),
            "active_tasks": [],
        }
        (rdir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def hoh_calls(self, verb: str) -> list[list[str]]:
        return [c for c in self.calls if len(c) > 1 and c[0].endswith("hoh") and verb in c]


@pytest.fixture
def env(tmp_path, monkeypatch) -> FakeEnv:
    return FakeEnv(tmp_path, monkeypatch)


@pytest.fixture
def stub_clone(monkeypatch):
    """Bypass the real git snapshotting: materialize an empty clone dir."""

    def _ensure(self):
        self.clone_dir.mkdir(parents=True, exist_ok=True)
        return self.clone_dir

    monkeypatch.setattr(VeriharnessAdapter, "ensure_clone", _ensure)


def make_package(node_id: str = "P05", with_artifact: bool = True) -> WorkPackage:
    return WorkPackage(
        package_id="wp-p05-1",
        node_id=node_id,
        spec_markdown="# Result Integrity\nReproduce the numbers.\n",
        artifacts=[ArtifactRef(rel_path="results/summary.json", sha256=SHA, kind="data")]
        if with_artifact
        else [],
    )


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #


def test_registry_register_get_available():
    class Dummy:
        def identity(self): ...
        def capabilities(self): ...
        def verify(self, package): ...

    registry.register("dummy", Dummy())
    assert registry.get("dummy") is not None
    assert registry.get("nope") is None
    assert registry.available() == ["dummy"]
    registry.BACKENDS.pop("dummy", None)


def test_adapter_satisfies_backend_protocol(env):
    assert isinstance(env.adapter, registry.VerificationBackend)


def test_register_veriharness_is_lazy_and_external(env):
    reg: dict = {}
    adapter = register_veriharness(reg, env.ws)
    assert reg["veriharness"] is adapter
    assert registry.get("veriharness") is None  # global registry untouched
    registry.register("veriharness", adapter)
    assert registry.get("veriharness") is adapter
    registry.BACKENDS.pop("veriharness", None)


# --------------------------------------------------------------------------- #
# doctor-driven availability
# --------------------------------------------------------------------------- #


def test_verify_unavailable_when_hoh_missing(tmp_path, monkeypatch, stub_clone):
    e = FakeEnv(tmp_path, monkeypatch, hoh_present=False)
    res = e.adapter.verify(make_package())
    assert res.verdict == Verdict.UNAVAILABLE
    assert res.failure_reason == "hoh executable not found"
    # no clone, no spec write, no hoh start/run attempt
    assert not (e.ws.root / "hoh-repo").exists()
    assert e.hoh_calls("start") == [] and e.hoh_calls("run") == []


def test_verify_degraded_when_herdr_missing(tmp_path, monkeypatch, stub_clone):
    e = FakeEnv(tmp_path, monkeypatch, herdr=False)
    caps = e.adapter.capabilities()
    assert len(caps) == 1
    assert caps[0].status == CapabilityStatus.SUPPORTED_DEGRADED
    assert "herdr" in caps[0].detail
    res = e.adapter.verify(make_package())
    assert res.verdict == Verdict.DEGRADED
    assert "herdr" in res.failure_reason
    assert e.hoh_calls("start") == []  # HoH refused, no run attempted


def test_capabilities_supported_and_unavailable(tmp_path, monkeypatch):
    e_ok = FakeEnv(tmp_path / "a", monkeypatch)
    caps = e_ok.adapter.capabilities()
    assert caps[0].status == CapabilityStatus.SUPPORTED
    assert caps[0].backend.kind == "veriharness"
    assert caps[0].backend.name == "hoh"
    assert caps[0].backend.version == "0.1.0"
    e_missing = FakeEnv(tmp_path / "b", monkeypatch, hoh_present=False)
    assert e_missing.adapter.capabilities()[0].status == CapabilityStatus.UNAVAILABLE


def test_identity_version_falls_back_to_unknown(tmp_path, monkeypatch):
    e = FakeEnv(tmp_path, monkeypatch, version_ok=False)
    assert e.adapter.identity().version == "unknown"


# --------------------------------------------------------------------------- #
# verify(): run-flow verdict mapping
# --------------------------------------------------------------------------- #


def test_verify_happy_path_pass(env, stub_clone):
    res = env.adapter.verify(make_package())
    assert res.verdict == Verdict.PASS
    assert res.package_id == "wp-p05-1"
    assert res.artifact_sha256 == SHA  # bound to the first package artifact
    assert res.failure_reason is None
    assert res.started_at <= res.finished_at
    # receipt copied out of the run tree, path recorded
    assert len(res.raw_receipt_refs) == 1
    copied = Path(res.raw_receipt_refs[0])
    assert copied.exists() and copied.name == "receipt1.json"
    assert copied.parent.name == res.backend.detail["run_id"]
    # run-specific HoH details live in BackendIdentity.detail, not new fields
    assert RUN_ID_RE.fullmatch(res.backend.detail["run_id"])
    assert res.backend.detail["blocked_kind"] is None
    assert res.backend.detail["hoh_detail"]["stage"] == "qa"
    # spec was materialized inside the PF-owned clone
    run_id = res.backend.detail["run_id"]
    spec = env.adapter.clone_dir / ".pf-specs" / f"{run_id}.md"
    assert spec.read_text(encoding="utf-8").startswith("# Result Integrity")
    start = env.hoh_calls("start")[0]
    assert start[start.index("--spec") + 1] == str(spec)


def test_verify_blocked_usage_limit_is_degraded(env, stub_clone):
    env.scenario.update(blocked_kind="usage_limit", accepted=False)
    res = env.adapter.verify(make_package())
    assert res.verdict == Verdict.DEGRADED  # quota exhaustion is not a FAIL
    assert "usage_limit" in res.failure_reason
    assert res.backend.detail["blocked_kind"] == "usage_limit"


def test_verify_blocked_other_kind_is_fail(env, stub_clone):
    env.scenario.update(blocked_kind="policy_refusal", accepted=False)
    res = env.adapter.verify(make_package())
    assert res.verdict == Verdict.FAIL
    assert "policy_refusal" in res.failure_reason


def test_verify_rejected_candidate_is_fail(env, stub_clone):
    env.scenario.update(accepted=False, blocked_kind=None)
    res = env.adapter.verify(make_package())
    assert res.verdict == Verdict.FAIL


# --------------------------------------------------------------------------- #
# legacy shim: verify_work_package -> HohResult (handlers.py contract)
# --------------------------------------------------------------------------- #


def test_shim_returns_hoh_result_with_legacy_fields(env, stub_clone, tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("# PF verification node P05\nreproduce\n", encoding="utf-8")
    res = env.adapter.verify_work_package("P05", spec)
    assert isinstance(res, HohResult)
    assert RUN_ID_RE.fullmatch(res.run_id)
    assert res.verdict == Verdict.PASS
    assert res.accepted is True
    assert res.blocked_kind is None
    assert res.stage == "qa"
    assert res.detail["condition"] == "ok"
    assert len(res.receipts) == 1
    r = res.receipts[0]
    assert r["receipt_file"] == "receipt1.json"
    assert Path(r["copied_to"]).exists()
    assert len(r["sha256"]) == 64


def test_shim_blocked_mapping_roundtrip(env, stub_clone, tmp_path):
    env.scenario.update(blocked_kind="usage_limit", accepted=False)
    spec = tmp_path / "spec.md"
    spec.write_text("spec\n", encoding="utf-8")
    res = env.adapter.verify_work_package("P05", spec)
    assert res.verdict == Verdict.DEGRADED
    assert res.blocked_kind == "usage_limit"
    assert res.accepted is False
    assert res.detail["stage"] == "qa"


def test_shim_dry_run_makes_no_subprocess_calls(env, tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("spec\n", encoding="utf-8")
    res = env.adapter.verify_work_package("P05", spec, dry_run=True)
    assert res.verdict == Verdict.NOT_RUN
    assert res.accepted is None
    assert res.detail["dry_run"] is True
    assert env.calls == []  # not even doctor probes


def test_shim_degraded_runtime_mapping(tmp_path, monkeypatch, stub_clone):
    e = FakeEnv(tmp_path, monkeypatch, herdr=False)
    spec = tmp_path / "spec.md"
    spec.write_text("spec\n", encoding="utf-8")
    res = e.adapter.verify_work_package("P05", spec)
    assert res.verdict == Verdict.DEGRADED
    assert res.accepted is None
    assert res.blocked_kind is None
    assert res.detail["reason"].startswith("DEGRADED_RUNTIME")
    assert res.receipts == []


# --------------------------------------------------------------------------- #
# run-id format (herdr truncation discipline)
# --------------------------------------------------------------------------- #


def test_run_id_format_respects_truncation_limit(env, stub_clone):
    res = env.adapter.verify(make_package())
    run_id = res.backend.detail["run_id"]
    assert len(run_id) <= 24  # herdr agent-name truncation ~24 chars
    assert run_id.startswith("PF-")
    assert len(run_id.split("-")[1]) == 8  # random part BEFORE the node suffix


# --------------------------------------------------------------------------- #
# clone policy (O177) — real ensure_clone, raises before any git/subprocess
# --------------------------------------------------------------------------- #


def test_ensure_clone_rejects_symlink_escape(tmp_path, monkeypatch):
    e = FakeEnv(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    e.ws.root.mkdir(parents=True, exist_ok=True)
    e.adapter.clone_dir.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PolicyViolation):
        e.adapter.ensure_clone()
    assert list(outside.iterdir()) == []  # symlink never followed, nothing written


def test_ensure_clone_rejects_symlink_even_inside_workspace(tmp_path, monkeypatch):
    e = FakeEnv(tmp_path, monkeypatch)
    e.ws.root.mkdir(parents=True, exist_ok=True)
    inside = e.ws.root / "real-repo"
    inside.mkdir()
    e.adapter.clone_dir.symlink_to(inside, target_is_directory=True)
    with pytest.raises(PolicyViolation):
        e.adapter.ensure_clone()
    assert list(inside.iterdir()) == []


# --------------------------------------------------------------------------- #
# flock serialization — documents the REAL behavior: blocking wait, not error
# --------------------------------------------------------------------------- #


def test_second_verify_waits_on_held_lock(env, stub_clone):
    done: list[Verdict] = []

    def run_verify():
        done.append(env.adapter.verify(make_package()).verdict)

    with open(env.adapter._serial_lock_path, "a+") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)  # simulate a concurrent PF run
        t = threading.Thread(target=run_verify)
        t.start()
        time.sleep(0.4)
        assert done == []  # second run blocks on LOCK_EX (real behavior: it waits)
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)  # first run finishes
        t.join(timeout=10)
    assert not t.is_alive()
    assert done == [Verdict.PASS]  # second run proceeds normally after the wait


# --------------------------------------------------------------------------- #
# F3 (review B-1): an exception between `hoh start` and a finished `hoh run`
# must not leave orphans — best-effort cleanup (own panes only, provenance
# guard), a failure receipt, then the exception propagates (FAIL, no swallow).
# --------------------------------------------------------------------------- #


def test_run_phase_timeout_cleans_up_records_failure_and_propagates(
    env, stub_clone, tmp_path, monkeypatch
):
    import subprocess as sp

    adapter = env.adapter
    cleaned: list[str] = []
    monkeypatch.setattr(adapter, "_cleanup_panes", lambda run_id, state: cleaned.append(run_id))
    real_call = adapter._call

    def failing_call(*args, **kw):
        if "run" in args:
            raise sp.TimeoutExpired(cmd="hoh run", timeout=kw.get("timeout", 7200))
        return real_call(*args, **kw)

    monkeypatch.setattr(adapter, "_call", failing_call)
    with pytest.raises(sp.TimeoutExpired):
        adapter.verify(make_package())
    assert len(cleaned) == 1, "own panes must be cleaned even on run-phase failure"
    run_id = cleaned[0]
    assert run_id.startswith("PF-")
    # failure receipt persisted (in the run tree AND collected into the ws receipts)
    assert (adapter.runs_root / run_id / "receipts" / "pf_run_failure.json").exists()
    copied = env.ws.receipts_dir / "hoh" / run_id / "pf_run_failure.json"
    assert copied.exists()
    assert "TimeoutExpired" in copied.read_text(encoding="utf-8")
    # flock released: a fresh non-blocking exclusive lock must succeed
    import fcntl

    with open(adapter._serial_lock_path, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# --------------------------------------------------------------------------- #
# F4 (review B-3): clone fingerprint must be content-based (git HEAD +
# status digest), not mtime/size — and verify() must expose the clone
# identity separately from the caller-declared artifact_sha256.
# --------------------------------------------------------------------------- #


def _git_repo(path: Path) -> Path:
    """Fresh local git repo with one committed file (no network)."""
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    path.joinpath("code.py").write_text("print(1)\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=pf-test", "-c", "user.email=pf@test", "commit", "-q", "-m", "one"],
        cwd=path, check=True,
    )
    return path


def test_source_fingerprint_changes_on_new_commit(tmp_path):
    src = _git_repo(tmp_path / "repo")
    fp_before = VeriharnessAdapter._source_fingerprint(src)
    src.joinpath("code.py").write_text("print(2)\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=src, check=True)
    subprocess.run(
        ["git", "-c", "user.name=pf-test", "-c", "user.email=pf@test", "commit", "-q", "-m", "two"],
        cwd=src, check=True,
    )
    fp_after = VeriharnessAdapter._source_fingerprint(src)
    assert fp_before != fp_after, "a new commit must change the clone fingerprint"


def test_source_fingerprint_changes_on_uncommitted_change(tmp_path):
    src = _git_repo(tmp_path / "repo")
    fp_before = VeriharnessAdapter._source_fingerprint(src)
    src.joinpath("code.py").write_text("print(2)\n", encoding="utf-8")  # dirty, same length
    fp_after = VeriharnessAdapter._source_fingerprint(src)
    assert fp_before != fp_after, (
        "uncommitted working-tree changes must change the fingerprint "
        "(mtime/size alone is forgeable)"
    )
    # same-size in-place edit of the ALREADY dirty file: the diff CONTENT
    # changed, so the fingerprint must change too (review B-3a)
    src.joinpath("code.py").write_text("print(9)\n", encoding="utf-8")
    assert VeriharnessAdapter._source_fingerprint(src) != fp_after
    subprocess.run(["git", "checkout", "-q", "--", "code.py"], cwd=src, check=True)
    assert VeriharnessAdapter._source_fingerprint(src) == fp_before  # clean tree again


def test_source_fingerprint_tracks_dirty_to_dirtier_and_back(tmp_path):
    """Review B-3a: successive in-place edits of an already-dirty file must
    each change the fingerprint; restoring the clean file restores it."""
    src = _git_repo(tmp_path / "repo")
    fp_clean = VeriharnessAdapter._source_fingerprint(src)
    src.joinpath("code.py").write_text("v2 = True\n", encoding="utf-8")
    fp_dirty_v2 = VeriharnessAdapter._source_fingerprint(src)
    assert fp_dirty_v2 != fp_clean
    src.joinpath("code.py").write_text("v3 = True\n", encoding="utf-8")  # same length, still dirty
    fp_dirty_v3 = VeriharnessAdapter._source_fingerprint(src)
    assert fp_dirty_v3 != fp_dirty_v2 != fp_clean
    subprocess.run(["git", "checkout", "-q", "--", "code.py"], cwd=src, check=True)
    assert VeriharnessAdapter._source_fingerprint(src) == fp_clean


def test_source_fingerprint_covers_untracked_file_edits(tmp_path):
    """Untracked files are not in `git diff HEAD` — their content is hashed
    separately so editing one also changes the fingerprint."""
    src = _git_repo(tmp_path / "repo")
    fp_clean = VeriharnessAdapter._source_fingerprint(src)
    src.joinpath("notes.txt").write_text("draft one\n", encoding="utf-8")
    fp_untracked = VeriharnessAdapter._source_fingerprint(src)
    assert fp_untracked != fp_clean
    src.joinpath("notes.txt").write_text("draft two\n", encoding="utf-8")  # same length
    assert VeriharnessAdapter._source_fingerprint(src) != fp_untracked


def test_source_fingerprint_fallback_without_git(tmp_path):
    src = tmp_path / "plain"
    src.mkdir()
    src.joinpath("data.csv").write_text("x\n", encoding="utf-8")
    fp1 = VeriharnessAdapter._source_fingerprint(src)
    assert len(fp1) == 64
    # fallback is the documented weak proxy: a new file changes it
    src.joinpath("more.csv").write_text("y\n", encoding="utf-8")
    assert VeriharnessAdapter._source_fingerprint(src) != fp1


def test_verify_result_reports_clone_fingerprint_separately(env, stub_clone, tmp_path, monkeypatch):
    # manifest as ensure_clone would write it (stubbed clone, real marker)
    import json as _json

    env.adapter.runs_root.mkdir(parents=True, exist_ok=True)
    (env.adapter.runs_root / "clone-manifest.json").write_text(
        _json.dumps({"source_fingerprint": "f" * 64, "source": str(env.target)}),
        encoding="utf-8",
    )
    res = env.adapter.verify(make_package())
    assert res.backend.detail["clone_fingerprint"] == "f" * 64
    assert "clone-manifest" in res.backend.detail["clone_fingerprint_source"]
    # artifact_sha256 stays the caller-declared package binding, not the clone
    assert res.artifact_sha256 == SHA
    assert res.artifact_sha256 != res.backend.detail["clone_fingerprint"]


# --------------------------------------------------------------------------- #
# Re-Review B-2a: KeyboardInterrupt/SystemExit (BaseException) must also
# trigger the orphan cleanup — and ALWAYS propagate (Ctrl+C keeps working).
# --------------------------------------------------------------------------- #


def test_run_phase_keyboard_interrupt_cleans_up_records_and_propagates(
    env, stub_clone, tmp_path, monkeypatch
):
    adapter = env.adapter
    cleaned: list[str] = []
    monkeypatch.setattr(adapter, "_cleanup_panes", lambda run_id, state: cleaned.append(run_id))
    real_call = adapter._call

    def interrupting_call(*args, **kw):
        if "run" in args:
            raise KeyboardInterrupt()
        return real_call(*args, **kw)

    monkeypatch.setattr(adapter, "_call", interrupting_call)
    with pytest.raises(KeyboardInterrupt):
        adapter.verify(make_package())
    assert len(cleaned) == 1, "own panes must be cleaned even on KeyboardInterrupt"
    run_id = cleaned[0]
    copied = env.ws.receipts_dir / "hoh" / run_id / "pf_run_failure.json"
    assert copied.exists()
    receipt = json.loads(copied.read_text(encoding="utf-8"))
    assert receipt["error"].startswith("KeyboardInterrupt"), receipt["error"]
    import fcntl

    with open(adapter._serial_lock_path, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# --------------------------------------------------------------------------- #
# artifact_binding rule: verify() binds multi-artifact packages via the
# manifest digest (never silently element [0]).
# --------------------------------------------------------------------------- #


def test_verify_uses_manifest_digest_for_multiple_artifacts(env, stub_clone):
    from paper_factory.verification.contract import artifact_binding

    pkg = WorkPackage(
        package_id="wp-p05-multi",
        node_id="P05",
        spec_markdown="# spec\n",
        artifacts=[
            ArtifactRef(rel_path="results/a.json", sha256="a" * 64, kind="data"),
            ArtifactRef(rel_path="results/b.json", sha256="b" * 64, kind="data"),
        ],
    )
    res = env.adapter.verify(pkg)
    assert res.artifact_sha256 == artifact_binding(pkg.artifacts)
    assert res.artifact_sha256 != "a" * 64, "multi-artifact binding must not be artifacts[0]"
    # single-artifact behavior unchanged: the artifact's own sha256
    single = env.adapter.verify(make_package())
    assert single.artifact_sha256 == SHA


# --------------------------------------------------------------------------- #
# Live-field-test finding: the legacy shim silently dropped planner/developer/
# qa/iterations — verify() called _execute with defaults, so a caller choosing
# developer="codex" still got kimi. The options now pass through both layers.
# --------------------------------------------------------------------------- #


def _spy_execute(monkeypatch, adapter) -> dict:
    captured: dict = {}
    real_execute = adapter._execute

    def spy(run_id, spec_text, **kw):
        captured.update(kw)
        return real_execute(run_id, spec_text, **kw)

    monkeypatch.setattr(adapter, "_execute", spy)
    return captured


def test_shim_passes_role_parameters_through_to_execute(env, stub_clone, tmp_path, monkeypatch):
    captured = _spy_execute(monkeypatch, env.adapter)
    spec = tmp_path / "spec.md"
    spec.write_text("# spec\n", encoding="utf-8")
    env.adapter.verify_work_package("P05", spec, developer="codex", qa="kimi", iterations=3)
    assert captured["developer"] == "codex", "shim must not drop the developer role"
    assert captured["qa"] == "kimi"
    assert captured["planner"] == "claude"  # untouched default
    assert captured["iterations"] == 3


def test_verify_passes_options_through(env, stub_clone, monkeypatch):
    captured = _spy_execute(monkeypatch, env.adapter)
    env.adapter.verify(make_package(), qa="kimi")
    assert captured["qa"] == "kimi"
    assert captured["developer"] == "kimi"  # default untouched


def test_verify_role_defaults_unchanged(env, stub_clone, monkeypatch):
    captured = _spy_execute(monkeypatch, env.adapter)
    env.adapter.verify(make_package())
    assert captured == {"planner": "claude", "developer": "kimi", "qa": "codex",
                        "iterations": 1, "use_herdr": True}


# --------------------------------------------------------------------------- #
# Live-field-test finding (2026-10-05, runs PF-73ed7828/581db7b3/7aeb552c):
# Herdr dispatch stalls at the developer role with new CLI-TUI versions
# (5s stall window vs. kimi Welcome-Screen / codex empty pane). use_herdr=False
# routes `hoh run` through --no-herdr (Subprocess dispatcher) with an honest
# evidence note instead of a hard DEGRADED gate.
# --------------------------------------------------------------------------- #


def _hoh_run_argv(env) -> list:
    return [c for c in env.calls if c[0].endswith("hoh") and len(c) > 4 and c[3] == "run"]


def test_verify_no_herdr_appends_flag_and_skips_pane_cleanup(env, stub_clone, monkeypatch):
    cleaned: list = []
    monkeypatch.setattr(env.adapter, "_cleanup_panes", lambda run_id, state: cleaned.append(run_id))
    res = env.adapter.verify(make_package(), use_herdr=False)
    assert res.verdict == Verdict.PASS
    runs = _hoh_run_argv(env)
    assert len(runs) == 1
    assert "--no-herdr" in runs[0]
    assert cleaned == [], "--no-herdr spawns no panes; cleanup must not fake evidence"
    assert res.backend.detail["herdr"] is False
    assert "A01/A02/A12" in res.backend.detail["evidence_note"]


def test_verify_no_herdr_runs_without_herdr_runtime(tmp_path, monkeypatch, stub_clone):
    e = FakeEnv(tmp_path, monkeypatch, herdr=False)
    res = e.adapter.verify(make_package(), use_herdr=False)
    assert res.verdict == Verdict.PASS, "missing herdr must not block when use_herdr=False"
    assert res.backend.detail["herdr"] is False
    assert "Subprocess-Dispatch" in res.backend.detail["evidence_note"]
    assert len(_hoh_run_argv(e)) == 1


def test_verify_default_still_requires_herdr(tmp_path, monkeypatch, stub_clone):
    """Backward compatibility: use_herdr=True (default) keeps the DEGRADED gate."""
    e = FakeEnv(tmp_path, monkeypatch, herdr=False)
    res = e.adapter.verify(make_package())
    assert res.verdict == Verdict.DEGRADED
    assert _hoh_run_argv(e) == []


# --------------------------------------------------------------------------- #
# A-12 (proof review): the --no-herdr evidence_note must survive the legacy
# shim mapping into HohResult.detail — the DAG gate forwards it to the node.
# --------------------------------------------------------------------------- #


def test_shim_no_herdr_carries_evidence_note(env, stub_clone, tmp_path, monkeypatch):
    spec = tmp_path / "spec.md"
    spec.write_text("# spec\n", encoding="utf-8")
    res = env.adapter.verify_work_package("P05", spec, use_herdr=False)
    assert res.verdict == Verdict.PASS
    assert "A01/A02/A12" in res.detail["evidence_note"], (
        "shim must carry the backend evidence_note into HohResult.detail"
    )
    assert res.detail.get("herdr") is False
