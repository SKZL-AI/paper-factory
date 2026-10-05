"""WP-IV failure injection across plane boundaries (v2.0).

Genuine gaps on top of the existing adversarial / conformance / hardening
suites (checked first, no duplicates):

- receipt file tampered BETWEEN collection and gate: the collect-time digest
  on the gate receipt and the content hash recomputed at gate time must
  agree — a mismatch fails the run visibly (digest guard in
  ``dag/handlers._hoh_result_from_verify``), never registers tampered
  evidence under a fresh hash.
- capsule ``expected_outputs`` tampered: the semantic digest deliberately
  excludes comparison policy (pinned by test_reproduction_capsule), so the
  tamper does NOT change capsule identity — the consequence must surface
  where the declaration is consumed (runner/differential), and the export
  boundary must be pinned honestly instead of pretending the digest catches
  it.
- node receipt artifact refs read path: ``_node_artifact_refs`` takes
  sha256 from the DB row without re-hashing the file — a post-registration
  file tamper is not re-detected on THAT read path (the gate digest guard
  covers the hoh/shadow receipt path). Pinned as a documented limitation,
  not silently assumed away.
- concurrent store writers: two threads writing through separate
  connections serialize via SQLite locking (busy timeout) without
  corruption; a writer blocked longer than the busy timeout raises
  ``OperationalError("database is locked")`` — fail-visible, documented.

Real local subprocesses only for the capsule run (echo-class, no LLM/HoH/
network), consistent with tests/conformance.
"""
from __future__ import annotations

import json
import platform
import sqlite3
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from paper_factory.adapters.veriharness.adapter import ReceiptValidationError
from paper_factory.core.config import (
    MarkingRegistry,
    PaperFactoryConfig,
    ProviderPolicyConfig,
    ProvidersConfig,
)
from paper_factory.core.results import Verdict
from paper_factory.dag.executor import NodeContext
from paper_factory.dag.handlers import _hoh_result_from_verify, _node_artifact_refs
from paper_factory.export._shared import ExportBundle, ExportError
from paper_factory.export.cwl import build_cwl_tool
from paper_factory.reproduction import (
    EnvironmentIdentity,
    LocalReproductionRunner,
    ReproductionCapsule,
    compare_executions,
    sha256_file,
)
from paper_factory.state.store import Workspace
from paper_factory.verification.contract import (
    BackendIdentity,
    ExecutionReceipt,
    VerificationResult,
)

SHA_A = "a" * 64
NOW_TS = "2026-10-05T12:00:00Z"


def _gate_result(receipts: list[ExecutionReceipt], raw_refs: list[str],
                 hoh_run: str, sha: str = SHA_A) -> VerificationResult:
    res = VerificationResult(
        package_id="wp-fi-1",
        backend=BackendIdentity(kind="veriharness", name="hoh", version="0.1.0",
                                detail={"run_id": hoh_run}),
        verdict=Verdict.PASS,
        artifact_sha256=sha,
        started_at=datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 10, 5, 12, 1, 0, tzinfo=UTC),
        receipts=receipts,
        raw_receipt_refs=raw_refs,
    )
    return res


# --------------------------------------------------------------------------- #
# 1. receipt tampered between collection and gate
# --------------------------------------------------------------------------- #


def test_receipt_tampered_between_collect_and_gate_fails_visible(tmp_path):
    """Failure injection: das kopierte Receipt-File wird NACH der Collection
    (collect-Digest liegt am Gate-Receipt) aber VOR dem Gate manipuliert.
    Der Digest-Guard in _hoh_result_from_verify vergleicht collect-Zeit- und
    Gate-Zeit-Hash und bricht laut ab — das manipulierte Evidence wird nicht
    unter einem frischen Hash im Store registriert."""
    ws = Workspace(tmp_path / "target")
    ws.create_run("run-A")
    hoh_run = "PF-fi000001-P05"
    copied = ws.receipts_dir / "hoh" / hoh_run / "receipt1.json"
    copied.parent.mkdir(parents=True, exist_ok=True)
    copied.write_text(json.dumps({"run_id": hoh_run, "ok": True}), encoding="utf-8")
    collect_sha = sha256_file(copied)
    ws.record_receipt(f"{hoh_run}/receipt1.json", "run-A", "P05", "hoh",
                      copied, collect_sha)

    receipt = ExecutionReceipt(
        receipt_id="r-1",
        backend=BackendIdentity(kind="veriharness", name="hoh", version="0.1.0"),
        artifact_sha256=SHA_A,
        sha256=collect_sha,          # digest at collection time
        created_at=datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC),
    )
    res = _gate_result([receipt], [str(copied)], hoh_run)
    # honest path passes ...
    _hoh_result_from_verify("P05", res, None, ws, run_id="run-A")

    # ... tamper the file content between collect and gate ...
    copied.write_text(json.dumps({"run_id": hoh_run, "ok": True,
                                  "injected": "forged evidence"}),
                      encoding="utf-8")
    tampered = _gate_result([receipt], [str(copied)], hoh_run)
    with pytest.raises(ReceiptValidationError, match="digest changed"):
        _hoh_result_from_verify("P05", tampered, None, ws, run_id="run-A")


# --------------------------------------------------------------------------- #
# 2. capsule expected_outputs tampered — digest boundary honest by design,
#    consequence caught at execution/differential, export pinned
# --------------------------------------------------------------------------- #


def _capsule(root: Path, expected: list[str]) -> ReproductionCapsule:
    out_dir = root / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "out.txt").write_text("hello\n", encoding="utf-8")
    return ReproductionCapsule(
        capsule_id="fi-capsule-1",
        command=[sys.executable, "-c",
                 ("from pathlib import Path; "
                  "Path('results/out.txt').write_text('hello\\n')")],
        cwd=".",
        environment=EnvironmentIdentity(
            python_version=platform.python_version(),
            platform=f"{sys.platform}-{platform.machine()}"),
        expected_outputs=expected,
        producer=BackendIdentity(kind="pf_native", name="fi-test", version="0"),
    )


def test_capsule_expected_outputs_tamper_same_digest_export_guard_catches(tmp_path):
    """expected_outputs ist Comparison-Policy und steht bewusst NICHT im
    capsule_digest (Design, pinned in test_reproduction_capsule). Ein Tamper
    aendert also die Identitaet nicht. Folgekette ehrlich gepinnt:
    - der Differential vergleicht Receipt-gegen-Receipt — beide Laeufe
      lieferten denselben Output-Satz, also REPRODUCED_EXACT (die Deklaration
      selbst ist kein Vergleichsgegenstand);
    die ExportBundle-Validierung weist das halbe Ergebnis dagegen zurueck:
    completed, aber kein Output deckt das deklarierte 'stolen.txt' ab —
    ExportError statt halb-wahrer Exports."""
    root = tmp_path / "capsule"
    root.mkdir()
    honest = _capsule(root, ["results/out.txt"])
    runner = LocalReproductionRunner()
    receipt_a = runner.run(honest, root)

    tampered = honest.model_copy(update={"expected_outputs":
                                         ["results/out.txt", "stolen.txt"]})
    assert tampered.capsule_digest == honest.capsule_digest  # boundary, by design
    receipt_b = runner.run(tampered, root)
    assert "stolen.txt" not in {o.rel_path for o in receipt_b.outputs}

    cmp = compare_executions(receipt_a, receipt_b, capsule=tampered)
    assert cmp.classification.value == "REPRODUCED_EXACT"  # receipt-vs-receipt basis

    with pytest.raises(ExportError, match="stolen.txt"):
        ExportBundle.build(tampered, [receipt_b])
    # the honest capsule + honest receipt still exports clean
    ExportBundle.build(honest, [receipt_a])


def test_capsule_expected_outputs_tamper_visible_in_cwl_projection(tmp_path):
    """Nebenbefund der Failure Injection: die CWL-Projektion baut aus der
    Kapsel-Deklaration — die manipulierte expected_outputs erscheint als
    zusaetzlicher Glob-Output. Sichtbar, aber keine Verifikation; die
    Absicherung liegt im ExportBundle-Guard (Test oben)."""
    root = tmp_path / "capsule"
    root.mkdir()
    honest = _capsule(root, ["results/out.txt"])
    tampered = honest.model_copy(update={"expected_outputs":
                                         ["results/out.txt", "stolen.txt"]})
    def _globs(capsule: ReproductionCapsule) -> set[str]:
        return {o.get("outputBinding", {}).get("glob", "") for o in
                build_cwl_tool(capsule)["outputs"] if isinstance(o, dict)}

    assert any("stolen" in g for g in _globs(tampered))
    assert not any("stolen" in g for g in _globs(honest))


# --------------------------------------------------------------------------- #
# 3. node receipt artifact refs: DB-row trust pinned as documented limit
# --------------------------------------------------------------------------- #


def _ctx(ws: Workspace, run_id: str) -> NodeContext:
    return NodeContext(workspace=ws, run_id=run_id,
                       config=PaperFactoryConfig(), providers=ProvidersConfig(),
                       policy=ProviderPolicyConfig(), marking=MarkingRegistry(),
                       offline=True, strict=True)


def test_node_artifact_refs_trust_store_row_post_registration_tamper_pinned(tmp_path):
    """DOKUMENTIERTE Grenze (kein Regressionsspielraum): _node_artifact_refs
    nimmt sha256 aus der DB-Zeile und hashet die Datei NICHT neu — ein
    Tamper nach der Registrierung wird auf DIESEM Lesepfad nicht erneut
    erkannt. Gepinnt, damit die Annahme nie still zu einer "Verifikation"
    aufbläht; der hoh/shadow-Gate-Pfad ist durch den Digest-Guard abgedeckt."""
    ws = Workspace(tmp_path / "target")
    ws.create_run("run-fi")
    f = ws.receipts_dir / "evidence.json"
    f.write_text(json.dumps({"v": 1}), encoding="utf-8")
    recorded_sha = sha256_file(f)
    ws.record_receipt("evidence.json", "run-fi", "P02", "artifact", f,
                      recorded_sha)

    f.write_text(json.dumps({"v": 2, "injected": True}), encoding="utf-8")
    refs = _node_artifact_refs(_ctx(ws, "run-fi"), "P02")
    assert len(refs) == 1
    assert refs[0].sha256 == recorded_sha  # DB row, NOT the tampered content
    assert refs[0].sha256 != sha256_file(f)


# --------------------------------------------------------------------------- #
# 4. concurrent store writers — SQLite locking documented
# --------------------------------------------------------------------------- #


def test_concurrent_writers_serialize_without_corruption(tmp_path):
    """Zwei Writer-Threads ueber getrennte Connections: SQLite serialisiert
    ueber den Busy-Timeout (python-sqlite3 Default 5s), alle Writes landen,
    kein Korruption. Journal-Mode ist der SQLite-Default 'delete' (kein WAL)
    — die PF-Store-Disziplin bleibt Single-Writer-Prozess, Concurrent-Access
    serialisiert statt parallel."""
    ws = Workspace(tmp_path / "target")
    ws.create_run("run-conc")
    with ws.connect() as c:
        journal = c.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal == "delete"  # no WAL — documented, not assumed

    errors: list[BaseException] = []

    def writer(tag: str) -> None:
        try:
            for i in range(25):
                ws.set_node_status("run-conc", f"{tag}-{i}", "PASS",
                                   {"i": i})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(t,)) for t in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    statuses = ws.all_node_statuses("run-conc")
    assert len(statuses) == 50
    assert all(v == "PASS" for v in statuses.values())


def test_sqlite_writer_blocked_beyond_busy_timeout_fails_visible(tmp_path):
    """Locking-Verhalten dokumentiert: haelt Writer A eine EXCLUSIVE-
    Transaktion, wirft Writer B (Busy-Timeout 0.2s) OperationalError
    'database is locked' — fail-visible statt Warten bis ins Unendliche."""
    db = tmp_path / "locked.sqlite"
    conn_a = sqlite3.connect(db, timeout=30)
    conn_a.execute("CREATE TABLE t (k TEXT)")
    conn_a.execute("BEGIN EXCLUSIVE")
    conn_a.execute("INSERT INTO t VALUES ('held')")

    conn_b = sqlite3.connect(db, timeout=0.2)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        conn_b.execute("INSERT INTO t VALUES ('blocked')")
    conn_a.rollback()
    conn_a.close()
    conn_b.close()
