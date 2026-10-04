"""Adversarial tests for the verification plane (Phase 11) — all offline/mocked.

Gaps closed on top of the existing contract/adapter/shadow suites:

- schema_version: missing key must default to 1 (honest backward path), a wrong
  version is already fail-visible elsewhere but is re-proven here at JSON level.
- corrupt receipts (truncated JSON, invalid enums) must raise ValidationError,
  never parse leniently.
- a provider claiming PASS while binding a DIFFERENT artifact must produce
  INCOMPARABLE end-to-end via run_shadow — never MATCH.
- stale receipts: documented Ist-Zustand (see test docstring + WP6 report).
- provider TimeoutError/ConnectionError → PROVIDER_UNAVAILABLE, native untouched.
- registry lookup of unknown backends; external identities never self-register.
- malformed capability status strings → ValidationError.
- pane cleanup provenance: documents the REAL behavior of _cleanup_panes when
  the run state lists foreign tab ids (BEFUND, not fixed here).
- flock serialization across TWO adapter instances on ONE workspace.
- SQLite crash/restart/resume against tmp_path only.
- paper_factory stays importable with paperqa blocked (works with or without
  the package installed).

No real hoh/herdr/network/LLM anywhere.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from paper_factory.adapters.veriharness import adapter as adapter_mod
from paper_factory.adapters.veriharness.adapter import VeriharnessAdapter
from paper_factory.core.results import Verdict
from paper_factory.state.store import Workspace
from paper_factory.verification import registry
from paper_factory.verification.capabilities import CapabilityDeclaration
from paper_factory.verification.contract import (
    ArtifactRef,
    BackendIdentity,
    ExecutionReceipt,
    VerificationResult,
    WorkPackage,
)
from paper_factory.verification.shadow import (
    DifferentialOutcome,
    DifferentialReceipt,
    compare,
    run_shadow,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 4, 12, 5, 0, tzinfo=UTC)


def native_backend() -> BackendIdentity:
    return BackendIdentity(kind="pf_native", name="pf_native:P05", version="1.2.0.dev0")


def make_result(
    verdict: Verdict,
    *,
    sha: str | None = None,
    backend: BackendIdentity | None = None,
    failure_reason: str | None = None,
    receipts: list[ExecutionReceipt] | None = None,
    package_id: str = "wp-p05-1",
) -> VerificationResult:
    return VerificationResult(
        package_id=package_id,
        backend=backend or BackendIdentity(kind="veriharness", name="hoh", version="0.1.0"),
        verdict=verdict,
        artifact_sha256=sha,
        started_at=NOW,
        finished_at=LATER,
        failure_reason=failure_reason,
        receipts=receipts or [],
    )


def native_result(verdict: Verdict, *, sha: str | None = None) -> VerificationResult:
    return make_result(verdict, sha=sha, backend=native_backend())


def make_package() -> WorkPackage:
    return WorkPackage(
        package_id="wp-p05-1",
        node_id="P05",
        spec_markdown="# Result Integrity\nReproduce the numbers.\n",
        artifacts=[ArtifactRef(rel_path="results/summary.json", sha256=SHA_A, kind="data")],
    )


# --------------------------------------------------------------------------- #
# 1. schema_version: fail-visible on mismatch, honest default on missing
# --------------------------------------------------------------------------- #


def test_missing_schema_version_defaults_to_one_and_loads():
    """Backward path is honest: omitting schema_version loads as v1, not as an
    error and not as a silent upgrade."""
    payload = WorkPackage(
        package_id="wp", node_id="P05", spec_markdown="s"
    ).model_dump(mode="json")
    del payload["schema_version"]
    wp = WorkPackage.model_validate(payload)
    assert wp.schema_version == 1

    res_payload = make_result(Verdict.PASS).model_dump(mode="json")
    del res_payload["schema_version"]
    assert VerificationResult.model_validate(res_payload).schema_version == 1

    receipt = compare(native_result(Verdict.PASS), make_result(Verdict.PASS), node_id="P05")
    d_payload = json.loads(receipt.model_dump_json())
    del d_payload["schema_version"]
    assert DifferentialReceipt.model_validate(d_payload).schema_version == 1


@pytest.mark.parametrize("model_obj", [
    WorkPackage(package_id="wp", node_id="P05", spec_markdown="s"),
    make_result(Verdict.PASS),
    compare(native_result(Verdict.PASS), make_result(Verdict.PASS), node_id="P05"),
])
def test_schema_version_two_rejected_at_json_boundary(model_obj):
    """schema_version=2 must fail visibly at the JSON boundary, never be ignored."""
    payload = json.loads(model_obj.model_dump_json())
    payload["schema_version"] = 2
    with pytest.raises(ValidationError):
        type(model_obj).model_validate(payload)


# --------------------------------------------------------------------------- #
# 2. corrupt receipts: fail-visible loading, no lenient parsing
# --------------------------------------------------------------------------- #


def test_truncated_differential_receipt_json_raises():
    good = compare(
        native_result(Verdict.PASS),
        make_result(Verdict.UNAVAILABLE, failure_reason="offline"),
        node_id="P05",
    )
    full = good.model_dump_json()
    truncated = full[: len(full) // 2]  # cut mid-content
    with pytest.raises(ValidationError):
        DifferentialReceipt.model_validate_json(truncated)


def test_invalid_outcome_enum_in_receipt_json_raises():
    payload = json.loads(
        compare(native_result(Verdict.PASS), make_result(Verdict.FAIL), node_id="P05")
            .model_dump_json()
    )
    payload["outcome"] = "TOTALLY_NOT_AN_OUTCOME"
    with pytest.raises(ValidationError):
        DifferentialReceipt.model_validate(payload)


def test_corrupt_execution_receipt_inside_result_raises():
    payload = make_result(Verdict.PASS, sha=SHA_A).model_dump(mode="json")
    payload["receipts"] = [
        {"receipt_id": "r1", "backend": {"kind": "veriharness", "name": "hoh", "version": "1"},
         "artifact_sha256": "not-a-sha", "sha256": SHA_B}
    ]
    with pytest.raises(ValidationError):
        VerificationResult.model_validate(payload)


def test_corrupt_artifact_sha_in_package_raises():
    payload = make_package().model_dump(mode="json")
    payload["artifacts"][0]["sha256"] = "z" * 64  # invalid hex char
    with pytest.raises(ValidationError):
        WorkPackage.model_validate(payload)


# --------------------------------------------------------------------------- #
# 3+4. provider claims PASS for a DIFFERENT artifact → never MATCH
# --------------------------------------------------------------------------- #


class _LyingBackend:
    """Reports PASS like the native side, but binds a foreign artifact."""

    def __init__(self, sha: str):
        self._sha = sha
        self.packages: list[WorkPackage] = []

    def identity(self):
        return BackendIdentity(kind="veriharness", name="hoh", version="0.1.0")

    def capabilities(self):
        return []

    def verify(self, package: WorkPackage) -> VerificationResult:
        self.packages.append(package)
        return make_result(Verdict.PASS, sha=self._sha)


def test_run_shadow_pass_with_differing_artifact_sha_is_incomparable():
    """Grenzfall: both sides PASS, artifact binding differs. The agreement is
    not artifact-provable — outcome must be INCOMPARABLE, never MATCH, and the
    native result is returned unchanged (identity, not a copy)."""
    native = native_result(Verdict.PASS, sha=SHA_A)
    returned, receipt = run_shadow(lambda p: native, _LyingBackend(SHA_B), make_package())
    assert returned is native
    assert receipt.outcome == DifferentialOutcome.INCOMPARABLE
    assert receipt.native_artifact_sha256 == SHA_A
    assert receipt.shadow_artifact_sha256 == SHA_B
    assert receipt.outcome != DifferentialOutcome.MATCH


def test_run_shadow_pass_with_unbound_shadow_is_incomparable():
    """Shadow PASS without any artifact binding cannot be promoted to MATCH."""
    native = native_result(Verdict.PASS, sha=SHA_A)
    _, receipt = run_shadow(lambda p: native, _LyingBackend(None), make_package())
    assert receipt.outcome == DifferentialOutcome.INCOMPARABLE


# --------------------------------------------------------------------------- #
# 5. stale receipts — Ist-Zustand-Dokumentation (BEFUND: kein Frische-Mechanismus)
# --------------------------------------------------------------------------- #


def test_stale_execution_receipt_loads_without_any_freshness_check():
    """BEFUND-Dokumentation (WP6): the contract has NO staleness derivation.
    A receipt created 400 days ago validates cleanly and is carried through a
    VerificationResult round-trip without complaint; compare() has no timestamp
    input at all. This test pins the honest Ist-Zustand so a future freshness
    check has a red test to turn green — it deliberately does NOT invent one."""
    ancient = datetime(2025, 8, 1, tzinfo=UTC)
    stale = ExecutionReceipt(
        receipt_id="r-stale",
        backend=BackendIdentity(kind="veriharness", name="hoh", version="0.1.0"),
        artifact_sha256=SHA_A,
        sha256=SHA_B,
        created_at=ancient,
    )
    res = make_result(Verdict.PASS, sha=SHA_A, receipts=[stale])
    restored = VerificationResult.model_validate_json(res.model_dump_json())
    assert restored.receipts[0].created_at == ancient  # stale, but accepted as-is
    # no consumer-side freshness hook exists today:
    assert not hasattr(ExecutionReceipt, "is_stale")
    assert not hasattr(VerificationResult, "check_receipt_freshness")


# --------------------------------------------------------------------------- #
# 6+7. provider timeout / network loss → PROVIDER_UNAVAILABLE, native untouched
# --------------------------------------------------------------------------- #


class _FailingBackend:
    def __init__(self, exc: Exception):
        self._exc = exc

    def identity(self):
        return BackendIdentity(kind="veriharness", name="hoh", version="0.1.0")

    def capabilities(self):
        return []

    def verify(self, package):
        raise self._exc


@pytest.mark.parametrize("exc", [
    TimeoutError("hoh run timed out after 7200s"),
    ConnectionError("herdr socket unreachable"),
    OSError("spawn hoh: No such file or directory"),
])
def test_provider_infrastructure_failures_are_provider_unavailable(exc):
    """Timeout, network loss, missing process: all become PROVIDER_UNAVAILABLE
    with the reason recorded — never a False-PASS, never NOT_FOUND, and the
    native result is returned byte-identical."""
    native = native_result(Verdict.PASS, sha=SHA_A)
    returned, receipt = run_shadow(lambda p: native, _FailingBackend(exc), make_package())
    assert returned is native
    assert receipt.outcome == DifferentialOutcome.PROVIDER_UNAVAILABLE
    assert receipt.shadow_verdict == Verdict.UNAVAILABLE
    assert type(exc).__name__ in receipt.provider_status
    assert "shadow backend raised" in receipt.provider_status


def test_native_fail_result_not_upgraded_when_provider_dies():
    """Asymmetry guard: a FAILing native result must not be softened just
    because the shadow provider is unreachable."""
    native = native_result(Verdict.FAIL)
    returned, receipt = run_shadow(
        lambda p: native, _FailingBackend(ConnectionError("down")), make_package()
    )
    assert returned is native and returned.verdict == Verdict.FAIL
    assert receipt.outcome == DifferentialOutcome.PROVIDER_UNAVAILABLE


# --------------------------------------------------------------------------- #
# 8. unknown backend identity: controlled lookup, no self-registration
# --------------------------------------------------------------------------- #


def test_registry_lookup_of_unknown_name_returns_none():
    """Real behavior of registry.get: silent None (no KeyError, no probing)."""
    assert registry.get("nichtexistent") is None
    assert "nichtexistent" not in registry.available()


def test_external_identity_serializable_but_never_self_registers():
    ident = BackendIdentity(kind="external", name="beliebig", version="9.9")
    before = registry.available()
    res = make_result(Verdict.PASS, backend=ident, sha=SHA_A)
    restored = VerificationResult.model_validate_json(res.model_dump_json())
    assert restored.backend.kind == "external" and restored.backend.name == "beliebig"
    # merely USING an external identity must not register it:
    assert registry.available() == before
    assert registry.get("beliebig") is None


# --------------------------------------------------------------------------- #
# 9. malformed capability declaration
# --------------------------------------------------------------------------- #


def test_capability_declaration_rejects_invalid_status_string():
    with pytest.raises(ValidationError):
        CapabilityDeclaration(
            backend={"kind": "external", "name": "x", "version": "1"},
            capability="verify",
            status="MAYBE_SOMETIMES",
        )


def test_capability_declaration_rejects_invalid_status_in_json():
    good = CapabilityDeclaration(
        backend={"kind": "veriharness", "name": "hoh", "version": "0.1.0"},
        capability="verify",
        status="SUPPORTED",
    )
    payload = json.loads(good.model_dump_json())
    payload["status"] = "WORKS_ON_MY_MACHINE"
    with pytest.raises(ValidationError):
        CapabilityDeclaration.model_validate(payload)


# --------------------------------------------------------------------------- #
# 10. pane cleanup vs foreign tabs — REAL behavior pinned (BEFUND)
# --------------------------------------------------------------------------- #


def test_cleanup_panes_documents_missing_provenance_guard(tmp_path, monkeypatch):
    """BEFUND-Dokumentation (WP6): _cleanup_panes closes EVERY herdr_tab_id
    listed in the run's own state.json — there is no per-task provenance check
    (no run_id/task-owner filter). If a foreign tab id ever lands in this run's
    active_tasks, it WOULD be closed. This test pins that real behavior so the
    gap stays visible; the guard itself is deliberately NOT added here."""
    ws = Workspace(tmp_path / "target")
    adapter = VeriharnessAdapter(ws, hoh_executable="/fake/bin/hoh")
    herdr_calls: list[list[str]] = []

    def fake_run(cmd, **kw):
        herdr_calls.append(list(cmd))
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(adapter_mod.shutil, "which", lambda name: "/fake/bin/herdr")
    monkeypatch.setattr(adapter_mod.subprocess, "run", fake_run)

    state = {
        "active_tasks": [
            {"task": "planner", "herdr_tab_id": "tab-own-1"},
            {"task": "qa", "herdr_tab_id": "tab-own-2"},
            {"task": "foreign-run-agent", "herdr_tab_id": "tab-foreign-9"},
        ]
    }
    adapter._cleanup_panes("PF-adv00001-P05", state)

    closed = [c[c.index("close") + 1] for c in herdr_calls]
    # Ist-Zustand: ALL listed tabs are closed, the foreign one included —
    # this assertion is the Befund, not the desired end state.
    assert closed == ["tab-foreign-9", "tab-own-1", "tab-own-2"]
    cleanup_file = adapter.runs_root / "PF-adv00001-P05.pane_cleanup.json"
    assert json.loads(cleanup_file.read_text(encoding="utf-8"))["closed"] == closed


def test_cleanup_panes_without_herdr_binary_is_noop(tmp_path, monkeypatch):
    ws = Workspace(tmp_path / "target")
    adapter = VeriharnessAdapter(ws, hoh_executable="/fake/bin/hoh")
    calls: list[list[str]] = []
    monkeypatch.setattr(adapter_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(adapter_mod.subprocess, "run",
                        lambda cmd, **kw: calls.append(list(cmd)))
    adapter._cleanup_panes("PF-adv00002-P05", {"active_tasks": [{"herdr_tab_id": "t1"}]})
    assert calls == []


# --------------------------------------------------------------------------- #
# 11. flock: two adapter instances on ONE workspace serialize
# --------------------------------------------------------------------------- #


class _FakeHohEnv:
    """Minimal mocked environment: doctor ok, one happy run flow."""

    def __init__(self, target: Path, monkeypatch: pytest.MonkeyPatch):
        self.target = target
        self.target.mkdir(parents=True, exist_ok=True)
        self.ws = Workspace(self.target)
        self.calls: list[list[str]] = []

        def fake_run(cmd, **kw):
            self.calls.append(list(cmd))
            exe = Path(cmd[0]).name
            if exe == "hoh":
                if "--help" in cmd or "--version" in cmd:
                    return type("P", (), {"returncode": 0, "stdout": "hoh 0.1.0\n",
                                          "stderr": ""})()
                if "start" in cmd:
                    return type("P", (), {"returncode": 0,
                                          "stdout": json.dumps({"started": True}),
                                          "stderr": ""})()
                if "run" in cmd:
                    root = Path(cmd[cmd.index("--root") + 1])
                    run_id = cmd[cmd.index("run") + 1]
                    rdir = root / run_id
                    (rdir / "receipts").mkdir(parents=True, exist_ok=True)
                    (rdir / "receipts" / "r.json").write_text("{}", encoding="utf-8")
                    (rdir / "state.json").write_text(json.dumps({
                        "stage": "qa", "condition": "ok", "blocked_kind": None,
                        "last_accepted_candidate": "cand-1", "active_tasks": [],
                    }), encoding="utf-8")
                    return type("P", (), {"returncode": 0,
                                          "stdout": json.dumps({"done": True}),
                                          "stderr": ""})()
            raise AssertionError(f"unexpected subprocess call: {cmd}")

        monkeypatch.setattr(adapter_mod.subprocess, "run", fake_run)
        monkeypatch.setattr(adapter_mod.shutil, "which",
                            lambda name: f"/fake/bin/{name}")
        monkeypatch.setenv("HERDR_ENV", "1")

        def fake_clone(self_):
            self_.clone_dir.mkdir(parents=True, exist_ok=True)
            return self_.clone_dir

        self._clone_patch = pytest.MonkeyPatch()
        self._clone_patch.setattr(VeriharnessAdapter, "ensure_clone", fake_clone)

    def close(self):
        self._clone_patch.undo()


def test_two_adapter_instances_serialize_on_same_lock_file(tmp_path, monkeypatch):
    import fcntl
    import threading
    import time

    env = _FakeHohEnv(tmp_path / "target", monkeypatch)
    try:
        adapter_a = VeriharnessAdapter(env.ws, hoh_executable="/fake/bin/hoh")
        adapter_b = VeriharnessAdapter(env.ws, hoh_executable="/fake/bin/hoh")
        # same workspace → same lock file (the serialization point)
        assert adapter_a._serial_lock_path == adapter_b._serial_lock_path

        done: list[Verdict] = []

        def run_b():
            done.append(adapter_b.verify(make_package()).verdict)

        with open(adapter_a._serial_lock_path, "a+") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            t = threading.Thread(target=run_b)
            t.start()
            time.sleep(0.4)
            assert done == []  # instance B blocks on the SAME lock file
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            t.join(timeout=10)
        assert not t.is_alive()
        assert done == [Verdict.PASS]
    finally:
        env.close()


# --------------------------------------------------------------------------- #
# 12. crash / restart / resume on SQLite (tmp_path only)
# --------------------------------------------------------------------------- #


def test_sqlite_state_survives_reopen_and_stays_consistent(tmp_path):
    target = tmp_path / "target"
    ws = Workspace(target)
    ws.create_run("run-1", config_hash="abc")
    ws.set_node_status("run-1", "P05", "FAIL", detail={"error": "numbers diverge"})
    ws.set_node_status("run-1", "P05", "FAIL", detail={"error": "still diverging"})
    ws.record_receipt("rcpt-1", "run-1", "P05", "shadow",
                      target / ".paper-factory" / "receipts" / "x.json", SHA_A)
    ws.event("run-1", "node_finished", "P05", {"verdict": "FAIL"})
    ws.event("run-1", "node_finished", "P05", {"verdict": "FAIL", "attempt": 2})
    # implicit "crash": all connections dropped, Workspace object discarded

    ws2 = Workspace(target)  # restart: brand-new handle on the SAME database
    assert ws2.node_status("run-1", "P05") == "FAIL"
    assert ws2.all_node_statuses("run-1") == {"P05": "FAIL"}
    ws2.create_run("run-1")  # idempotent: INSERT OR IGNORE, no PK violation
    assert ws2.latest_run_id() == "run-1"

    events = ws2.events_of_kind("node_finished")
    assert [e["payload"]["verdict"] for e in events] == ["FAIL", "FAIL"]  # append-only
    receipts = ws2.receipts_for("run-1", "P05")
    assert len(receipts) == 1 and receipts[0]["receipt_id"] == "rcpt-1"

    # attempts were bumped across updates (retry accounting survives restart)
    with ws2.connect() as c:
        row = c.execute("SELECT attempts FROM nodes WHERE run_id=? AND node_id=?",
                        ("run-1", "P05")).fetchone()
    assert row["attempts"] == 2


def test_sqlite_receipt_insert_or_replace_is_idempotent(tmp_path):
    ws = Workspace(tmp_path / "target")
    ws.create_run("run-1")
    path = tmp_path / "r.json"
    ws.record_receipt("rcpt-1", "run-1", None, "kind", path, SHA_A)
    ws.record_receipt("rcpt-1", "run-1", None, "kind", path, SHA_B)  # same PK
    rows = ws.receipts_for("run-1")
    assert len(rows) == 1  # replace, not duplicate
    assert rows[0]["sha256"] == SHA_B


# --------------------------------------------------------------------------- #
# 14. paperqa absent: paper_factory stays importable (green with or without)
# --------------------------------------------------------------------------- #


def test_paper_factory_importable_with_paperqa_blocked():
    """Green in both worlds: if paperqa is installed, sys.modules['paperqa']=None
    blocks it for this import; if it is not installed, the block is a no-op.
    Either way the verification plane and literature modules must import."""
    code = (
        "import sys; sys.modules['paperqa'] = None;"
        "import importlib.util;"
        "assert importlib.util.find_spec('paperqa') is None or 'paperqa' in sys.modules;"
        "import paper_factory.verification.contract;"
        "import paper_factory.verification.shadow;"
        "import paper_factory.verification.registry;"
        "import paper_factory.verification.capabilities;"
        "import paper_factory.verification.findings_map;"
        "import paper_factory.literature.discovery;"
        "import paper_factory.literature.verify;"
        "import paper_factory.literature.draft_refs;"
        "import paper_factory.literature.novelty;"
        "import paper_factory.literature.url_verify;"
        "import paper_factory.adapters.veriharness.adapter;"
        "print('OK')"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          timeout=120, check=False)
    assert proc.returncode == 0, f"import failed: {proc.stderr}"
    assert proc.stdout.strip() == "OK"
