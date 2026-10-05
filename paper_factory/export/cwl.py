"""CWL v1.2 CommandLineTool export (v1.4 WP-C): ReproductionCapsule → CWL.

EXPORT ONLY — this module never feeds back into PF semantics and is not a
runtime backend (no third runner; see the package docstring). Grounded in the
CWL v1.2 / v1.2.1 CommandLineTool specification (commonwl.org/v1.2/
CommandLineTool.html, read 2026-10-05).

Decision (docs/reports/V1_4_CWL_DECISION.md): JA — a meaningful subset of the
capsule exports to CWL v1.2 with the computational content preserved
natively and the contract identity preserved as extension metadata. CWL is a
tool-description language, not a frozen reproduction contract; the capsule
remains canonical and authoritative.

Mapping (PF capsule → CWL CommandLineTool):

| PF evidence | CWL representation |
|---|---|
| command (plain argv) | baseCommand (argv[0]) + arguments (argv[1:], literal) — CWL passes arguments without a shell unless ShellCommandRequirement is declared, which matches the capsule's argv semantics exactly |
| declared files (input/config/code/dependency-lock refs) | File inputs + InitialWorkDirRequirement listing staging each file at its capsule rel_path |
| file sha256 | pf:sha256 extension metadata on the input (CWL has no content-hash binding for inputs) |
| parameters (deterministic) | string inputs with default = declared value |
| parameters (nondeterministic) | string inputs without default, doc marks them runtime-injected |
| expected_outputs | File outputs, outputBinding.glob = exact rel_path |
| nondeterministic_outputs (fnmatch globs) | array-of-File outputs, glob = pattern, doc carries the declared reason |
| environment.container_image | hint DockerRequirement dockerPull |
| environment identity (python/platform/tool versions/lock) | pf:environment extension metadata on the document |
| capsule_id / capsule_digest / cwd / provenance_refs | pf:* extension metadata on the document |
| comparison policy (semantic_rules, nondeterminism reasons) | pf:comparison_policy extension metadata on the document |

Honest limitations (documented, not hidden):

- Content hashes are carried, never enforced: CWL has no mechanism to bind an
  input's content to a digest, so pf:sha256 is metadata only. Digest
  enforcement stays PF-side; capsule_digest remains the authoritative identity.
- cwd: the capsule runs in capsule_root/cwd; CWL tools run in runtime.outdir
  with staged files. cwd "." is equivalent; any other cwd is recorded in
  pf:cwd but its directory semantics are only approximated by staging.
- Execution evidence (receipts) has no home in a CommandLineTool description;
  run-level provenance exports via RO-Crate / PROV instead.
- Round-trip is not a goal; exported invariants are pinned by
  tests/test_export_cwl.py (every declared file hash, parameter and output
  path of the capsule appears in the CWL document).

The document is serialized as JSON, which is a valid YAML 1.2 document and
therefore a valid CWL document; tests parse the written file with both json
and PyYAML to pin that.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..reproduction.capsule import ReproductionCapsule
from ._shared import ExportBundle, ExportError

CWL_VERSION = "v1.2"
CWL_CLASS = "CommandLineTool"
PF_CWL_NAMESPACE = "https://github.com/SKZL-AI/paper-factory/cwl/v1#"

_ROLE_DOC = {
    "input": "declared input",
    "config": "declared configuration",
    "code": "declared code",
    "dependency_lock": "declared dependency lock",
}


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_") or "x"


def _input_id(rel_path: str) -> str:
    return f"file_{_slug(rel_path.replace('/', '__'))}"


def build_cwl_tool(capsule: ReproductionCapsule) -> dict[str, Any]:
    """Project a validated capsule into a CWL v1.2 CommandLineTool document.

    Receipts are intentionally out of scope (execution evidence exports via
    RO-Crate/PROV). Raises ExportError on identifier collisions — a fail-
    visible export, never a silently renamed input."""
    bundle = ExportBundle.build(capsule)
    return _ToolBuilder(bundle).build()


def write_cwl_tool(
    capsule: ReproductionCapsule,
    target_path: str | Path,
) -> Path:
    """Write the CWL document (JSON, valid YAML 1.2) to `target_path`."""
    doc = build_cwl_tool(capsule)
    path = Path(target_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return path


class _ToolBuilder:
    def __init__(self, bundle: ExportBundle) -> None:
        self.capsule = bundle.capsule
        self._seen_input_ids: set[str] = set()

    def build(self) -> dict[str, Any]:
        capsule = self.capsule
        env = capsule.environment
        doc: dict[str, Any] = {
            "cwlVersion": CWL_VERSION,
            "class": CWL_CLASS,
            "id": f"cwl-{_slug(capsule.capsule_id)}",
            "label": f"Paper Factory reproduction capsule {capsule.capsule_id}",
            "doc": (
                "EXPORT ONLY: tool-signature projection of a Paper Factory "
                "ReproductionCapsule. The capsule (capsule_digest) remains "
                "the authoritative reproduction identity; pf:* extension "
                "fields carry the contract facts CWL cannot express natively."
            ),
            "baseCommand": capsule.command[0],
            "arguments": list(capsule.command[1:]),
            "$namespaces": {"pf": PF_CWL_NAMESPACE},
            "pf:capsule_id": capsule.capsule_id,
            "pf:capsule_digest": capsule.capsule_digest,
            "pf:cwd": capsule.cwd,
            "pf:provenance_refs": list(capsule.provenance_refs),
            "pf:environment": self._environment_metadata(),
            "pf:comparison_policy": {
                "semantic_rules": [
                    r.model_dump(mode="json") for r in capsule.semantic_rules
                ],
                "nondeterministic_outputs": [
                    d.model_dump(mode="json") for d in capsule.nondeterministic_outputs
                ],
            },
            "inputs": self._inputs(),
            "outputs": self._outputs(),
            "requirements": [self._staging_requirement()],
        }
        if env.container_image:
            # A hint, not a requirement: the image is part of the declared
            # environment identity, but the tool description stays runnable
            # without a container engine.
            doc["hints"] = [
                {"class": "DockerRequirement", "dockerPull": env.container_image}
            ]
        return doc

    # -- document metadata --------------------------------------------------- #

    def _environment_metadata(self) -> dict[str, Any]:
        env = self.capsule.environment
        meta: dict[str, Any] = {
            "python_version": env.python_version,
            "platform": env.platform,
            "tool_versions": dict(env.tool_versions),
        }
        if env.dependency_lock_ref is not None:
            meta["dependency_lock_ref"] = env.dependency_lock_ref.model_dump(
                mode="json")
        if env.container_image is not None:
            meta["container_image"] = env.container_image
        return meta

    # -- inputs & staging ---------------------------------------------------- #

    def _register_input_id(self, input_id: str, rel_path: str) -> None:
        if input_id in self._seen_input_ids:
            raise ExportError(
                f"CWL input identifier collision: {input_id!r} (from "
                f"{rel_path!r}) — refusing to export with a silently "
                "renamed or merged input")
        self._seen_input_ids.add(input_id)

    def _file_input(self, rel_path: str, sha256: str, role: str) -> dict[str, Any]:
        input_id = _input_id(rel_path)
        self._register_input_id(input_id, rel_path)
        return {
            "id": input_id,
            "type": "File",
            "label": rel_path,
            "doc": (f"{_ROLE_DOC[role]} — content hash bound in the capsule "
                    "digest; carried here as pf:sha256 metadata (CWL does "
                    "not enforce input content hashes)"),
            "pf:rel_path": rel_path,
            "pf:sha256": sha256,
            "pf:role": role,
        }

    def _parameter_input(self, param) -> dict[str, Any]:
        input_id = f"param_{_slug(param.name)}"
        self._register_input_id(input_id, f"parameter {param.name!r}")
        entry: dict[str, Any] = {
            "id": input_id,
            "type": "string",
            "label": param.name,
        }
        if param.deterministic:
            entry["default"] = param.value
            entry["doc"] = ("deterministic capsule parameter — bound in "
                            "capsule_digest")
            entry["pf:deterministic"] = True
        else:
            entry["doc"] = ("nondeterministic capsule parameter — excluded "
                            "from capsule_digest, injected per run by the "
                            "caller")
            entry["pf:deterministic"] = False
        return entry

    def _inputs(self) -> list[dict[str, Any]]:
        capsule = self.capsule
        inputs: list[dict[str, Any]] = []
        for ref, role in (
            *[(r, "input") for r in capsule.input_refs],
            *[(r, "config") for r in capsule.config_refs],
            *[(r, "code") for r in capsule.code_refs],
        ):
            inputs.append(self._file_input(ref.rel_path, ref.sha256, role))
        lock = capsule.environment.dependency_lock_ref
        if lock is not None:
            inputs.append(
                self._file_input(lock.rel_path, lock.sha256, "dependency_lock"))
        inputs.extend(self._parameter_input(p) for p in capsule.parameters)
        return inputs

    def _staging_requirement(self) -> dict[str, Any]:
        listing = [
            {"entry": f"$(inputs.{_input_id(ref.rel_path)})",
             "entryname": ref.rel_path}
            for ref in (*self.capsule.input_refs,
                        *self.capsule.config_refs,
                        *self.capsule.code_refs)
        ]
        lock = self.capsule.environment.dependency_lock_ref
        if lock is not None:
            listing.append({
                "entry": f"$(inputs.{_input_id(lock.rel_path)})",
                "entryname": lock.rel_path,
            })
        return {"class": "InitialWorkDirRequirement", "listing": listing}

    # -- outputs ------------------------------------------------------------- #

    def _outputs(self) -> list[dict[str, Any]]:
        capsule = self.capsule
        outputs: list[dict[str, Any]] = []
        for rel_path in capsule.expected_outputs:
            outputs.append({
                "id": f"out_{_slug(rel_path.replace('/', '__'))}",
                "type": "File",
                "label": rel_path,
                "doc": "declared expected output (exact path)",
                "pf:rel_path": rel_path,
                "outputBinding": {"glob": rel_path},
            })
        for decl in capsule.nondeterministic_outputs:
            if decl.pattern in capsule.expected_outputs:
                continue  # already exported as an exact-path output
            outputs.append({
                "id": f"out_nd_{_slug(decl.pattern.replace('/', '__'))}",
                # An fnmatch pattern may match zero or many files; an array
                # output is the only CWL type that admits both.
                "type": {"type": "array", "items": "File"},
                "doc": (f"declared nondeterministic output — {decl.reason}"),
                "pf:nondeterministic_reason": decl.reason,
                "outputBinding": {"glob": decl.pattern},
            })
        return outputs
