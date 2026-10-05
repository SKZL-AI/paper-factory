"""WP7 tests: Snakemake backend adapter — the first workflow consumer of the
Reproduction Capsule. Covers Snakefile generation (determinism, quoting,
path semantics), the UNAVAILABLE fail-visible case, receipt mapping, job
failure, undeclared outputs and declared-input integrity.

Real end-to-end runs execute the deterministic synthetic pilot (or tiny
stdlib scripts) on local CPU via the actual snakemake binary — no network,
no LLM, no HoH. They are skipped honestly when snakemake is not installed
(same convention as the existing environment-gated skips)."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from paper_factory.reproduction import (
    CapsuleIntegrityError,
    FileRef,
    LocalReproductionRunner,
    ReproClassification,
    ReproductionCapsule,
    SnakemakeBackend,
    SnakemakeUnavailableError,
    UndeclaredOutputError,
    compare_executions,
    render_snakefile,
    sha256_file,
    snakemake_backend,
    snakemake_binary,
)

FIXTURE = Path(__file__).parent / "fixtures" / "repro_pilot"

requires_snakemake = pytest.mark.skipif(
    snakemake_binary() is None, reason="snakemake not installed (optional extra)")


def pilot_capsule() -> ReproductionCapsule:
    """Load the pre-built pilot capsule; swap the interpreter for the test's
    own executable so the committed JSON stays free of absolute paths."""
    c = ReproductionCapsule.model_validate_json(
        (FIXTURE / "capsule.json").read_text(encoding="utf-8"))
    return c.model_copy(update={"command": [sys.executable, *c.command[1:]]})


def pilot_root(tmp_path: Path) -> Path:
    root = tmp_path / "pilot"
    shutil.copytree(FIXTURE, root)
    return root


def _script_capsule(tmp_path, code: str, outputs):
    root = tmp_path / "case"
    root.mkdir()
    script = root / "case.py"
    script.write_text(code, encoding="utf-8")
    capsule = ReproductionCapsule(
        capsule_id="case-1",
        command=[sys.executable, "case.py"],
        code_refs=[FileRef(rel_path="case.py", sha256=sha256_file(script))],
        environment={"python_version": "3", "platform": "test"},
        expected_outputs=outputs,
        producer={"kind": "pf_native", "name": "test", "version": "0"},
    )
    return capsule, root


# --------------------------------------------------------------------------- #
# Snakefile generation (pure, no snakemake needed)
# --------------------------------------------------------------------------- #

def test_snakefile_generation_is_deterministic(tmp_path):
    capsule = pilot_capsule()
    first = render_snakefile(capsule)
    second = render_snakefile(capsule)
    assert first == second
    assert first.endswith("\n")
    assert "rule capsule_run:" in first


def test_snakefile_outputs_match_expected_sorted(tmp_path):
    capsule = pilot_capsule().model_copy(update={
        "expected_outputs": ["table.txt", "summary.json"]})
    text = render_snakefile(capsule)
    out_section = text.split("output:", 1)[1].split("shell:", 1)[0]
    # sorted, root-relative, quoted — no workflow semantics added
    assert out_section.index('"summary.json"') < out_section.index('"table.txt"')
    assert '"summary.json"' in out_section and '"table.txt"' in out_section


def test_snakefile_cwd_prepends_cd_but_outputs_stay_root_relative(tmp_path):
    """cwd changes the process working directory only; expected_outputs stay
    relative to the capsule root (same convention as the local runner)."""
    capsule, _ = _script_capsule(tmp_path, "pass\n", outputs=["sub/out.txt"])
    capsule = capsule.model_copy(update={"cwd": "sub"})
    text = render_snakefile(capsule)
    assert '"cd sub &&' in text
    assert '"sub/sub/out.txt"' not in text
    assert '"sub/out.txt"' in text


def test_snakefile_shell_command_is_quoted_and_escaped(tmp_path):
    capsule, _ = _script_capsule(tmp_path, "pass\n", outputs=["o.txt"])
    capsule = capsule.model_copy(update={
        "command": [sys.executable, "case.py", 'arg with "quotes"']})
    text = render_snakefile(capsule)
    shell_line = text.split("shell:", 1)[1].strip()
    assert shell_line.startswith('"') and shell_line.endswith('"')
    assert '\\"' in shell_line  # embedded double quotes escaped
    assert "arg with" in shell_line


def test_snakefile_contains_no_absolute_paths(tmp_path):
    # committed fixture capsule: command is ["python3", ...] — nothing absolute
    capsule = ReproductionCapsule.model_validate_json(
        (FIXTURE / "capsule.json").read_text(encoding="utf-8"))
    text = render_snakefile(capsule)
    assert str(tmp_path) not in text
    assert sys.executable not in text


# --------------------------------------------------------------------------- #
# Capability honesty (no snakemake needed)
# --------------------------------------------------------------------------- #

def test_unavailable_fails_visible_when_binary_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(snakemake_backend, "snakemake_binary", lambda: None)
    root = pilot_root(tmp_path)
    with pytest.raises(SnakemakeUnavailableError, match="snakemake"):
        SnakemakeBackend().run(pilot_capsule(), root, run_dir=tmp_path / "run")


def test_unavailable_error_mentions_install_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(snakemake_backend, "snakemake_binary", lambda: None)
    root = pilot_root(tmp_path)
    with pytest.raises(SnakemakeUnavailableError, match=r"\[snakemake\]"):
        SnakemakeBackend().run(pilot_capsule(), root, run_dir=tmp_path / "run")


# --------------------------------------------------------------------------- #
# Real executions via the actual snakemake binary (env-gated)
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Run-directory lifecycle (review B-MINOR-3) — fake snakemake, no binary needed
# --------------------------------------------------------------------------- #

_FAKE_SNAKEMAKE = """\
#!/usr/bin/env python3
import re, sys
from pathlib import Path

args = sys.argv[1:]
if "--version" in args:
    print("9.9.9")
    sys.exit(0)
snakefile = Path(args[args.index("--snakefile") + 1])
directory = Path(args[args.index("--directory") + 1])
text = snakefile.read_text(encoding="utf-8")
out_section = text.split("output:", 1)[1].split("shell:", 1)[0]
for pattern in re.findall(r'"((?:[^"\\\\]|\\\\.)*)"', out_section):
    pattern = pattern.replace('\\\\"', '"').replace("\\\\\\\\", "\\\\")
    target = directory / pattern
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("fake output\\n", encoding="utf-8")
# execute the capsule shell command like real snakemake would
shell_line = text.split("shell:", 1)[1].strip().strip('"')
import subprocess
sys.exit(subprocess.run(shell_line, shell=True, cwd=directory).returncode)
"""


def _fake_snakemake(tmp_path, monkeypatch):
    binary = tmp_path / "fake_snakemake.py"
    binary.write_text(_FAKE_SNAKEMAKE, encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setattr(snakemake_backend, "snakemake_binary",
                        lambda: str(binary))


def test_default_run_dir_is_cleaned_up(tmp_path, monkeypatch):
    """Without run_dir the backend's private pf-snakemake-* directory must
    not leak (review B-MINOR-3). A caller-provided run_dir is audit
    evidence and must survive."""
    import tempfile

    _fake_snakemake(tmp_path, monkeypatch)
    leak_probe = Path(tempfile.gettempdir())
    before = {p.name for p in leak_probe.glob("pf-snakemake-*")}

    capsule, root = _script_capsule(tmp_path, "pass\n", outputs=["o.txt"])
    receipt = SnakemakeBackend().run(capsule, root)
    assert receipt.status == "completed"

    leftover = {p.name for p in leak_probe.glob("pf-snakemake-*")} - before
    assert leftover == set(), f"leaked run directories: {leftover}"


def test_caller_run_dir_is_never_removed(tmp_path, monkeypatch):
    _fake_snakemake(tmp_path, monkeypatch)
    run_dir = tmp_path / "audit"
    capsule, root = _script_capsule(tmp_path, "pass\n", outputs=["o.txt"])
    receipt = SnakemakeBackend().run(capsule, root, run_dir=run_dir)
    assert receipt.status == "completed"
    assert (run_dir / "Snakefile").is_file()
    assert (run_dir / "capsule").is_dir()


def test_default_run_dir_cleaned_even_on_undeclared_output(tmp_path, monkeypatch):
    """Cleanup runs in finally: an UndeclaredOutputError must not leak the
    private run directory either."""
    import tempfile

    _fake_snakemake(tmp_path, monkeypatch)
    leak_probe = Path(tempfile.gettempdir())
    before = {p.name for p in leak_probe.glob("pf-snakemake-*")}
    capsule, root = _script_capsule(
        tmp_path,
        "from pathlib import Path\n"
        "Path('o.txt').write_text('x')\n"
        "Path('scratch.bin').write_text('undeclared')\n",
        outputs=["o.txt"])
    with pytest.raises(UndeclaredOutputError):
        SnakemakeBackend().run(capsule, root)
    leftover = {p.name for p in leak_probe.glob("pf-snakemake-*")} - before
    assert leftover == set(), f"leaked run directories: {leftover}"


@requires_snakemake
def test_pilot_runs_via_snakemake_and_maps_receipt(tmp_path):
    root = pilot_root(tmp_path)
    receipt = SnakemakeBackend().run(pilot_capsule(), root,
                                     run_dir=tmp_path / "run")

    assert receipt.status == "completed"
    assert receipt.exit_code == 0
    assert receipt.failure_reason is None
    assert receipt.backend.kind == "external"
    assert receipt.backend.name == "snakemake"
    assert receipt.backend.version and receipt.backend.version != "unknown"
    assert receipt.capsule_digest == pilot_capsule().capsule_digest
    by_path = {f.rel_path: f.sha256 for f in receipt.outputs}
    assert set(by_path) == {"summary.json", "table.txt"}
    assert all(len(h) == 64 for h in by_path.values())
    # local-runner reference hashes must match byte for byte
    ref = LocalReproductionRunner().run(pilot_capsule(),
                                        pilot_root(tmp_path / "ref"))
    ref_by_path = {f.rel_path: f.sha256 for f in ref.outputs}
    assert by_path == ref_by_path


@requires_snakemake
def test_backend_stages_and_never_touches_caller_root(tmp_path):
    root = pilot_root(tmp_path)
    receipt = SnakemakeBackend().run(pilot_capsule(), root,
                                     run_dir=tmp_path / "run")
    assert receipt.status == "completed"
    # caller's capsule root: no outputs, no .snakemake metadata
    assert not (root / "summary.json").exists()
    assert not (root / "table.txt").exists()
    assert not (root / ".snakemake").exists()
    # the run directory holds the audit trail instead
    run_dir = tmp_path / "run"
    assert (run_dir / "Snakefile").is_file()
    assert (run_dir / "capsule" / "summary.json").is_file()
    assert (run_dir / "capsule" / ".snakemake").is_dir()


@requires_snakemake
def test_differential_local_vs_snakemake_reproduced_exact(tmp_path):
    """The WP7 proof gate: same capsule → local runner and Snakemake backend
    → identical output hashes → REPRODUCED_EXACT."""
    capsule = pilot_capsule()
    local = LocalReproductionRunner().run(capsule, pilot_root(tmp_path / "a"))
    snake = SnakemakeBackend().run(capsule, pilot_root(tmp_path / "b"),
                                   run_dir=tmp_path / "run")
    assert local.backend.name != snake.backend.name
    result = compare_executions(local, snake, capsule)
    assert result.classification is ReproClassification.REPRODUCED_EXACT
    assert result.differing_outputs == ()
    assert result.missing_outputs == ()


@requires_snakemake
def test_failed_job_recorded_in_receipt_not_raised(tmp_path):
    capsule, root = _script_capsule(
        tmp_path,
        "import sys\nsys.stderr.write('boom\\n')\nsys.exit(3)\n",
        outputs=["summary.json"])
    (root / "summary.json").write_text("{}", encoding="utf-8")
    receipt = SnakemakeBackend().run(capsule, root, run_dir=tmp_path / "run")
    assert receipt.status == "failed"
    assert receipt.exit_code != 0
    assert receipt.failure_reason
    assert len(receipt.stderr_sha256) == 64
    assert len(receipt.stdout_sha256) == 64


@requires_snakemake
def test_timeout_recorded_not_raised(tmp_path):
    capsule, root = _script_capsule(
        tmp_path,
        "import time\ntime.sleep(10)\n"
        "from pathlib import Path\nPath('summary.json').write_text('{}')\n",
        outputs=["summary.json"])
    receipt = SnakemakeBackend().run(capsule, root, timeout=1.0,
                                     run_dir=tmp_path / "run")
    assert receipt.status == "timeout"
    assert receipt.exit_code is None
    assert "timeout" in receipt.failure_reason


@requires_snakemake
def test_undeclared_output_fails_visible(tmp_path):
    capsule, root = _script_capsule(
        tmp_path,
        "from pathlib import Path\n"
        "Path('summary.json').write_text('{}')\n"
        "Path('scratch.bin').write_text('undeclared')\n",
        outputs=["summary.json"])
    with pytest.raises(UndeclaredOutputError, match="scratch.bin"):
        SnakemakeBackend().run(capsule, root, run_dir=tmp_path / "run")


@requires_snakemake
def test_declared_input_hash_mismatch_fails_before_snakemake(tmp_path):
    root = pilot_root(tmp_path)
    (root / "input.csv").write_text("name,value\nx,999\n", encoding="utf-8")
    with pytest.raises(CapsuleIntegrityError, match="hash mismatch"):
        SnakemakeBackend().run(pilot_capsule(), root, run_dir=tmp_path / "run")
    # pre-flight happens before the run directory is created
    assert not (tmp_path / "run").exists()


@requires_snakemake
def test_cwd_capsule_runs_in_staged_workdir(tmp_path):
    capsule, root = _script_capsule(
        tmp_path,
        "from pathlib import Path\nPath('summary.json').write_text('{}')\n",
        outputs=["sub/summary.json"])
    sub = root / "sub"
    sub.mkdir()
    script = root / "case.py"
    script.rename(sub / "case.py")
    capsule = capsule.model_copy(update={
        "cwd": "sub",
        "command": [sys.executable, "case.py"],
        "code_refs": [FileRef(rel_path="sub/case.py",
                              sha256=sha256_file(sub / "case.py"))],
    })
    receipt = SnakemakeBackend().run(capsule, root, run_dir=tmp_path / "run")
    assert receipt.status == "completed"
    assert [f.rel_path for f in receipt.outputs] == ["sub/summary.json"]
    # cwd staging is private to the run directory
    assert not (root / "sub" / "summary.json").exists()
