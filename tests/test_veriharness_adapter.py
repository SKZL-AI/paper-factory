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
