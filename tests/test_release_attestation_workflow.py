"""WP-IV: structural guard for .github/workflows/release-attestation.yml.

The attestation workflow is release-critical infrastructure: it builds the
sdist/wheel for every v* tag and signs them via actions/attest. A silently
manipulated workflow (broadened permissions, added publish step, widened
triggers) must be caught by the SUITE, not by review luck. This guard pins
the security-relevant structure; a simulated tamper proves the guard
actually fires (no vacuous green).

The guard function takes the parsed YAML, so the same checks run against
the real file and against mutated copies — no network, no git, no LLM.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW_PATH = (Path(__file__).resolve().parent.parent
                 / ".github" / "workflows" / "release-attestation.yml")

FORBIDDEN_STEP_SNIPPETS = (
    "pypa/gh-action-pypi-publish",
    "twine upload",
    "gh release create",
    "softprops/action-gh-release",
)


class AttestationWorkflowStructureError(AssertionError):
    """The release-attestation workflow deviates from its guarded structure."""


def _guard(doc: Any) -> None:
    """Structural checks, fail-visible with a reason each."""
    if not isinstance(doc, dict):
        raise AttestationWorkflowStructureError(
            f"workflow is a {type(doc).__name__}, not a mapping")
    if "name" not in doc:
        raise AttestationWorkflowStructureError("workflow has no name")

    on = doc.get("on") or doc.get(True)  # YAML 1.1 parses 'on' as bool key
    if not isinstance(on, dict):
        raise AttestationWorkflowStructureError(f"'on' trigger is not a mapping: {on!r}")
    push = on.get("push")
    if not isinstance(push, dict) or push.get("tags") != ["v*"]:
        raise AttestationWorkflowStructureError(
            f"push trigger must be tags-only ['v*'], got {push!r}")
    if "branches" in push:
        raise AttestationWorkflowStructureError(
            "push trigger must not fire on branches — tags only")

    # permissions: empty at top level, job-scoped and minimal
    if doc.get("permissions") not in ({}, None):
        raise AttestationWorkflowStructureError(
            f"top-level permissions must be empty, got {doc.get('permissions')!r}")
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or len(jobs) != 1:
        raise AttestationWorkflowStructureError(
            f"exactly one job expected, got {list(jobs) if isinstance(jobs, dict) else jobs!r}")
    job = next(iter(jobs.values()))
    perms = job.get("permissions") or {}
    allowed = {"contents": "read", "id-token": "write", "attestations": "write"}
    if any(str(v) == "write-all" for v in perms.values()) or perms == "write-all":
        raise AttestationWorkflowStructureError("write-all permissions are forbidden")
    for scope, level in perms.items():
        if allowed.get(scope) != level:
            raise AttestationWorkflowStructureError(
                f"job permission {scope!r}: {level!r} — only {allowed!r} permitted")

    steps = job.get("steps") or []
    rendered = yaml.safe_dump(steps)
    if "actions/attest" not in rendered:
        raise AttestationWorkflowStructureError(
            "no actions/attest step — the attestation step must not be removed")
    for snippet in FORBIDDEN_STEP_SNIPPETS:
        if snippet in rendered:
            raise AttestationWorkflowStructureError(
                f"forbidden step content present: {snippet!r} "
                "(attestation workflow must not publish or release)")


def _load() -> Any:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _on(doc: dict) -> dict:
    """YAML 1.1 parses the key 'on' as boolean True — handle both."""
    return doc.get("on") or doc[True]


def _job(doc: dict) -> dict:
    return next(iter(doc["jobs"].values()))


def test_release_attestation_workflow_structure_guarded():
    """Der reale Workflow erfuellt den Guard."""
    _guard(_load())


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda d: _on(d)["push"].update({"branches": ["main"]}),
                 id="branches-trigger-added"),
    pytest.param(lambda d: _job(d)["steps"].append(
        {"name": "Publish to PyPI", "uses": "pypa/gh-action-pypi-publish@release/v1"}),
        id="pypi-publish-step-added"),
    pytest.param(lambda d: _job(d).update(
        {"permissions": {"contents": "write-all"}}),
        id="write-all-permissions"),
    pytest.param(lambda d: _job(d)["steps"].append(
        {"name": "Release", "run": "gh release create ${TAG} dist/*"}),
        id="gh-release-step-added"),
    pytest.param(lambda d: _job(d)["steps"].remove(
        next(s for s in _job(d)["steps"]
             if isinstance(s, dict) and "actions/attest" in str(s.get("uses", "")))),
        id="attest-step-removed"),
])
def test_attestation_workflow_guard_fires_on_tamper(mutate):
    """Der Guard ist nicht vakuum-gruen: jede relevante Manipulationsklasse
    (Trigger-Verbreiterung, Publish-Step, Permissions-Aufweitung, Wegnahme
    des Attest-Schritts) wird nachweislich erwischt."""
    doc = _load()
    mutate(doc)
    with pytest.raises(AttestationWorkflowStructureError):
        _guard(doc)
