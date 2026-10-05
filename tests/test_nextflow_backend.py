"""WP-B tests: Nextflow backend adapter — the second workflow consumer of
the Reproduction Capsule (v1.4). Covers main.nf generation (determinism,
quoting, cwd semantics), the UNAVAILABLE fail-visible case, run-directory
lifecycle, receipt mapping, job failure, staging and the local-vs-nextflow
differential gate.

Real end-to-end runs execute the deterministic synthetic pilot (or tiny
stdlib scripts) on local CPU via the actual nextflow binary — no network
(except the one-time nextflow install itself), no LLM, no HoH. They are
skipped honestly when nextflow is not installed (same convention as the
environment-gated snakemake skips)."""
from __future__ import annotations

import re
import shlex
import shutil
import sys
from pathlib import Path

import pytest

from paper_factory.reproduction import (
    CapsuleIntegrityError,
    FileRef,
    LocalReproductionRunner,
    NextflowBackend,
    NextflowUnavailableError,
    ReproClassification,
    ReproductionCapsule,
    UndeclaredOutputError,
    compare_executions,
    nextflow_backend,
    nextflow_binary,
    render_nextflow_script,
    sha256_file,
)

FIXTURE = Path(__file__).parent / "fixtures" / "repro_pilot"

requires_nextflow = pytest.mark.skipif(
    nextflow_binary() is None, reason="nextflow not installed (binary launcher)")


def pilot_capsule() -> ReproductionCapsule:
    """Load the pre-built pilot capsule; swap the interpreter for the test's
    own executable so the committed JSON stays free of absolute paths."""
    c = ReproductionCapsule.model_validate_json(
        (FIXTURE / "capsule.json").read_text(encoding="utf-8"))
    return c.model_copy(update={"command": [sys.executable, *c.command[1:]]})


def pilot_root(tmp_path: Path, name: str = "pilot") -> Path:
    root = tmp_path / name
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
# main.nf generation (pure, no nextflow needed)
# --------------------------------------------------------------------------- #

def test_main_nf_generation_is_deterministic(tmp_path):
    capsule = pilot_capsule()
    staged = tmp_path / "run" / "capsule"
    first = render_nextflow_script(capsule, staged)
    second = render_nextflow_script(capsule, staged)
    assert first == second
    assert first.endswith("\n")
    assert "process capsule_run {" in first
    assert "workflow {" in first


def test_main_nf_declares_no_outputs_and_cds_into_staged_workdir(tmp_path):
    capsule = pilot_capsule()
    staged = tmp_path / "run" / "capsule"
    text = render_nextflow_script(capsule, staged)
    # output evidence is PF's post-hoc collection, not the engine's
    assert "output:" not in text
    # one process, workflow entry, cwd semantics via cd into the staged root
    assert text.count("process capsule_run {") == 1
    assert "capsule_run()" in text
    assert f"cd {staged}" in text


def test_main_nf_shell_command_is_quoted(tmp_path):
    capsule, _ = _script_capsule(tmp_path, "pass\n", outputs=["o.txt"])
    capsule = capsule.model_copy(update={
        "command": [sys.executable, "case.py", 'arg with "quotes"']})
    text = render_nextflow_script(capsule, tmp_path / "stage")
    script_block = text.split('"""')[1]
    # shlex.quote wraps the dangerous arg in single quotes
    assert shlex.quote('arg with "quotes"') in script_block
    assert "case.py" in script_block


def _groovy_unescape(text: str) -> str:
    """What Nextflow's GString parse turns the source into (single pass:
    only `\\` and `$` can be escaped in a Groovy GString)."""
    out: list[str] = []
    i = 0
    while i < len(text):
        if (text[i] == "\\" and i + 1 < len(text)
                and text[i + 1] in "\\$"):
            out.append(text[i + 1])
            i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def test_main_nf_dollar_escaped(tmp_path):
    """Review MAJOR-1 B: the `script` block is a Groovy GString — Nextflow
    interpolates `$` itself, before bash ever sees the script (reproduced
    pre-fix: `price$100` arrived as `price00` with status completed). The
    `$` must be escaped at the Groovy layer only, so the bash-level command
    is unchanged and the job receives the capsule's exact argv."""
    capsule, _ = _script_capsule(tmp_path, "pass\n", outputs=["o.txt"])
    capsule = capsule.model_copy(update={
        "command": [sys.executable, "case.py", "price$100", "${HOME}"]})
    text = render_nextflow_script(capsule, tmp_path / "stage")
    script_block = text.split('"""')[1]
    # escaped in the Groovy source
    assert "price\\$100" in script_block
    assert "\\${HOME}" in script_block
    # no unescaped `$` may remain — Nextflow would interpolate it
    assert not re.search(r"(?<!\\)\$", script_block)
    # after the GString parse the bash text is the exact shlex-quoted argv
    assert shlex.quote("price$100") in _groovy_unescape(script_block)
    assert shlex.quote("${HOME}") in _groovy_unescape(script_block)


def test_main_nf_backslash_escaped(tmp_path):
    """`\\` starts a Groovy escape sequence too; a literal backslash in argv
    must survive the GString parse unchanged (same bug class as `$`)."""
    capsule, _ = _script_capsule(tmp_path, "pass\n", outputs=["o.txt"])
    capsule = capsule.model_copy(update={
        "command": [sys.executable, "case.py", "a\\b"]})
    text = render_nextflow_script(capsule, tmp_path / "stage")
    script_block = text.split('"""')[1]
    assert "a\\\\b" in script_block            # source: doubled backslash
    assert shlex.quote("a\\b") in _groovy_unescape(script_block)


def test_main_nf_rejects_triple_quote_arg(tmp_path):
    """An argv element containing `\"\"\"` would terminate the Groovy script
    block early and run a truncated command with a `completed` receipt —
    fail-visible rejection instead (review MAJOR-1 B)."""
    capsule, _ = _script_capsule(tmp_path, "pass\n", outputs=["o.txt"])
    capsule = capsule.model_copy(update={
        "command": [sys.executable, "case.py", 'say """hi"""']})
    with pytest.raises(ValueError, match='"""'):
        render_nextflow_script(capsule, tmp_path / "stage")


def test_main_nf_contains_no_caller_root_paths(tmp_path):
    """The generated script embeds only the staged workdir, never paths of
    the caller's capsule root."""
    capsule, root = _script_capsule(tmp_path, "pass\n", outputs=["o.txt"])
    text = render_nextflow_script(capsule, tmp_path / "run" / "capsule")
    assert str(root) not in text


# --------------------------------------------------------------------------- #
# Capability honesty (no nextflow needed)
# --------------------------------------------------------------------------- #

def test_unavailable_fails_visible_when_binary_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(nextflow_backend, "nextflow_binary", lambda: None)
    with pytest.raises(NextflowUnavailableError, match="nextflow"):
        NextflowBackend().run(pilot_capsule(), pilot_root(tmp_path),
                              run_dir=tmp_path / "run")


# --------------------------------------------------------------------------- #
# Run-directory lifecycle — fake nextflow, no binary needed
# --------------------------------------------------------------------------- #

_FAKE_NEXTFLOW = '''\
#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

args = sys.argv[1:]
if "-version" in args or "--version" in args:
    print("nextflow version 26.9.9", file=sys.stderr)
    sys.exit(0)
nf = Path(args[args.index("run") + 1])
text = nf.read_text(encoding="utf-8")
block = text.split('"""')[1]
sys.exit(subprocess.run(["bash", "-c", block]).returncode)
'''


def _fake_nextflow(tmp_path, monkeypatch):
    binary = tmp_path / "fake_nextflow.py"
    binary.write_text(_FAKE_NEXTFLOW, encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setattr(nextflow_backend, "nextflow_binary",
                        lambda: str(binary))


def test_default_run_dir_is_cleaned_up(tmp_path, monkeypatch):
    """Without run_dir the backend's private pf-nextflow-* directory must
    not leak. A caller-provided run_dir is audit evidence and must survive."""
    import tempfile

    _fake_nextflow(tmp_path, monkeypatch)
    leak_probe = Path(tempfile.gettempdir())
    before = {p.name for p in leak_probe.glob("pf-nextflow-*")}

    capsule, root = _script_capsule(tmp_path, "pass\n", outputs=["o.txt"])
    receipt = NextflowBackend().run(capsule, root)
    assert receipt.status == "completed"
    assert receipt.backend.name == "nextflow"
    assert receipt.backend.version == "26.9.9"

    leftover = {p.name for p in leak_probe.glob("pf-nextflow-*")} - before
    assert leftover == set(), f"leaked run directories: {leftover}"


def test_caller_run_dir_is_never_removed(tmp_path, monkeypatch):
    _fake_nextflow(tmp_path, monkeypatch)
    run_dir = tmp_path / "audit"
    capsule, root = _script_capsule(tmp_path, "pass\n", outputs=["o.txt"])
    receipt = NextflowBackend().run(capsule, root, run_dir=run_dir)
    assert receipt.status == "completed"
    assert (run_dir / "main.nf").is_file()
    assert (run_dir / "capsule").is_dir()


def test_default_run_dir_cleaned_even_on_undeclared_output(tmp_path,
                                                          monkeypatch):
    """Cleanup runs in finally: an UndeclaredOutputError must not leak the
    private run directory either."""
    import tempfile

    _fake_nextflow(tmp_path, monkeypatch)
    leak_probe = Path(tempfile.gettempdir())
    before = {p.name for p in leak_probe.glob("pf-nextflow-*")}
    capsule, root = _script_capsule(
        tmp_path,
        "from pathlib import Path\n"
        "Path('o.txt').write_text('x')\n"
        "Path('scratch.bin').write_text('undeclared')\n",
        outputs=["o.txt"])
    with pytest.raises(UndeclaredOutputError):
        NextflowBackend().run(capsule, root)
    leftover = {p.name for p in leak_probe.glob("pf-nextflow-*")} - before
    assert leftover == set(), f"leaked run directories: {leftover}"


# --------------------------------------------------------------------------- #
# Real executions via the actual nextflow binary (env-gated)
# --------------------------------------------------------------------------- #

@requires_nextflow
def test_pilot_runs_via_nextflow_and_maps_receipt(tmp_path):
    root = pilot_root(tmp_path)
    receipt = NextflowBackend().run(pilot_capsule(), root,
                                    run_dir=tmp_path / "run")

    assert receipt.status == "completed"
    assert receipt.exit_code == 0
    assert receipt.failure_reason is None
    assert receipt.backend.kind == "external"
    assert receipt.backend.name == "nextflow"
    assert receipt.backend.version and receipt.backend.version != "unknown"
    assert receipt.capsule_digest == pilot_capsule().capsule_digest
    by_path = {f.rel_path: f.sha256 for f in receipt.outputs}
    assert set(by_path) == {"summary.json", "table.txt"}
    assert all(len(h) == 64 for h in by_path.values())
    # local-runner reference hashes must match byte for byte
    ref = LocalReproductionRunner().run(pilot_capsule(),
                                        pilot_root(tmp_path, "ref"))
    ref_by_path = {f.rel_path: f.sha256 for f in ref.outputs}
    assert by_path == ref_by_path


@requires_nextflow
def test_backend_stages_and_never_touches_caller_root(tmp_path):
    root = pilot_root(tmp_path)
    receipt = NextflowBackend().run(pilot_capsule(), root,
                                    run_dir=tmp_path / "run")
    assert receipt.status == "completed"
    # caller's capsule root: no outputs, no nextflow metadata
    assert not (root / "summary.json").exists()
    assert not (root / "table.txt").exists()
    assert not (root / ".nextflow.log").exists()
    assert not (root / "work").exists()
    # the run directory holds the audit trail instead
    run_dir = tmp_path / "run"
    assert (run_dir / "main.nf").is_file()
    assert (run_dir / "capsule" / "summary.json").is_file()


@requires_nextflow
def test_differential_local_vs_nextflow_reproduced_exact(tmp_path):
    """The WP-B proof gate: same capsule → local runner and Nextflow backend
    → identical output hashes → REPRODUCED_EXACT."""
    capsule = pilot_capsule()
    local = LocalReproductionRunner().run(capsule, pilot_root(tmp_path, "a"))
    nxf = NextflowBackend().run(capsule, pilot_root(tmp_path, "b"),
                                run_dir=tmp_path / "run")
    assert local.backend.name != nxf.backend.name
    result = compare_executions(local, nxf, capsule)
    assert result.classification is ReproClassification.REPRODUCED_EXACT
    assert result.differing_outputs == ()
    assert result.missing_outputs == ()


@requires_nextflow
def test_failed_job_recorded_in_receipt_not_raised(tmp_path):
    capsule, root = _script_capsule(
        tmp_path,
        "import sys\nsys.stderr.write('boom\\n')\nsys.exit(3)\n",
        outputs=["summary.json"])
    (root / "summary.json").write_text("{}", encoding="utf-8")
    receipt = NextflowBackend().run(capsule, root, run_dir=tmp_path / "run")
    assert receipt.status == "failed"
    assert receipt.exit_code != 0
    assert receipt.failure_reason
    assert len(receipt.stderr_sha256) == 64


@requires_nextflow
def test_undeclared_output_fails_visible(tmp_path):
    capsule, root = _script_capsule(
        tmp_path,
        "from pathlib import Path\n"
        "Path('summary.json').write_text('{}')\n"
        "Path('scratch.bin').write_text('undeclared')\n",
        outputs=["summary.json"])
    with pytest.raises(UndeclaredOutputError, match="scratch.bin"):
        NextflowBackend().run(capsule, root, run_dir=tmp_path / "run")


@requires_nextflow
def test_declared_input_hash_mismatch_fails_before_nextflow(tmp_path):
    root = pilot_root(tmp_path)
    (root / "input.csv").write_text("name,value\nx,999\n", encoding="utf-8")
    with pytest.raises(CapsuleIntegrityError, match="hash mismatch"):
        NextflowBackend().run(pilot_capsule(), root, run_dir=tmp_path / "run")
    # pre-flight happens before the run directory is created
    assert not (tmp_path / "run").exists()


@requires_nextflow
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
    receipt = NextflowBackend().run(capsule, root, run_dir=tmp_path / "run")
    assert receipt.status == "completed"
    assert [f.rel_path for f in receipt.outputs] == ["sub/summary.json"]
    # cwd staging is private to the run directory
    assert not (root / "sub" / "summary.json").exists()


@requires_nextflow
def test_dollar_and_metachar_args_arrive_verbatim_e2e(tmp_path):
    """E2E proof for review MAJOR-1 B: a real `nextflow run` must deliver
    argv containing `$`, `${...}`, `$(...)`, quotes, backslashes and spaces
    byte-identically. Pre-fix, Groovy GString interpolation in the generated
    main.nf silently turned `price$100` into `price00` while the receipt
    claimed completed."""
    capsule, root = _script_capsule(
        tmp_path,
        "import sys\nfrom pathlib import Path\n"
        "Path('echo.txt').write_text(sys.argv[1])\n",
        outputs=["echo.txt"])
    token = 'price$100 ${x} $(y) "q" a\\b spa ce'
    capsule = capsule.model_copy(update={
        "command": [sys.executable, "case.py", token]})
    receipt = NextflowBackend().run(capsule, root, run_dir=tmp_path / "run")
    assert receipt.status == "completed"
    echo = tmp_path / "run" / "capsule" / "echo.txt"
    assert echo.read_text(encoding="utf-8") == token
