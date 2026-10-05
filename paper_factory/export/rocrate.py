"""RO-Crate export (WP9): ReproductionCapsule + ExecutionReceipts → RO-Crate 1.3
conforming to the Process Run Crate profile 0.6 (Workflow Run RO-Crate family).

EXPORT ONLY — this module never feeds back into PF semantics; see the package
docstring. Mapping (PF → RO-Crate), grounded in the profile requirements
(researchobject.org/workflow-run-crate/profiles/process_run_crate, read
2026-10-05):

| PF evidence | RO-Crate entity |
|---|---|
| capsule (as a whole) | root Dataset (`./`), `identifier` = capsule_id, digest as PropertyValue in `mentions` |
| profile conformance | root `conformsTo` → `https://w3id.org/ro/wfrun/process/0.6` (+ CreativeWork) |
| execution receipt | `CreateAction` (`#<execution_id>`), `instrument` = SoftwareApplication for the backend |
| backend identity | `SoftwareApplication` (`#tool-<kind>-<name>`), `softwareVersion` = version |
| input_refs / config_refs | `File` entities in root `hasPart` + `object` of the action |
| code_refs | `File` entities typed `["File", "SoftwareSourceCode"]` |
| receipt.outputs | `File` entities with `sha256`, `result` of the action |
| EnvironmentIdentity | `PropertyValue` entities attached via the workflow-run `environment` term |
| container_image | `ContainerImage` entity via the workflow-run `containerImage` term |
| status / failure_reason | `actionStatus` (CompletedActionStatus / FailedActionStatus) + `error` |
| command + cwd | action `description` (informational only, per profile) |

Required-by-profile properties asserted by tests: root Dataset `conformsTo`,
CreateAction `@type`/`@id`/`instrument`/`endTime`, SoftwareApplication
`@type`/`@id`, `sha256` on every File entity. At least one receipt is
mandatory — the profile requires a CreateAction; a capsule without any
execution evidence is exported via the Workflow Card, not as a run crate.

Conscious simplifications (documented, not hidden):

- Multiple content variants of one output path (declared nondeterminism) are
  exported under `variants/<hash16>/<path>` with `alternateName` set — the
  profile permits renaming with `alternateName` when ids would otherwise clash.
- `containerImage` omits `additionalType`/`registry`: EnvironmentIdentity
  records the image only as an opaque reference string, so the image format
  and registry are not assertable.
- Round-trip is not a goal; exported invariants are tested instead
  (tests/test_export_rocrate.py).
"""
from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..reproduction.capsule import ExecutionReceipt, ReproductionCapsule
from ._shared import ExportBundle, ExportError

RO_CRATE_CONTEXT = "https://w3id.org/ro/crate/1.3/context"
WORKFLOW_RUN_CONTEXT = "https://w3id.org/ro/terms/workflow-run/context"
RO_CRATE_SPEC_ID = "https://w3id.org/ro/crate/1.3"
PROCESS_RUN_PROFILE_ID = "https://w3id.org/ro/wfrun/process/0.6"
METADATA_FILENAME = "ro-crate-metadata.json"


def _data_id(rel_path: str) -> str:
    """Percent-encoded RO-Crate data-entity @id for a capsule-root rel_path."""
    return quote(rel_path, safe="/") or "."


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-") or "x"


def build_rocrate(
    capsule: ReproductionCapsule,
    receipts: list[ExecutionReceipt] | tuple[ExecutionReceipt, ...],
) -> dict[str, Any]:
    """Project a validated bundle into an RO-Crate JSON-LD document.
    Raises ExportError on missing/mandatory-data violations (see _shared)."""
    bundle = ExportBundle.build(capsule, receipts)
    if not bundle.receipts:
        raise ExportError(
            "RO-Crate export requires at least one ExecutionReceipt — the "
            "Process Run Crate profile mandates a CreateAction per crate")
    return _CrateBuilder(bundle).build()


def write_rocrate(
    capsule: ReproductionCapsule,
    receipts: list[ExecutionReceipt] | tuple[ExecutionReceipt, ...],
    target_dir: str | Path,
) -> Path:
    """Write `ro-crate-metadata.json` into `target_dir` (created if needed)."""
    crate = build_rocrate(capsule, receipts)
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / METADATA_FILENAME
    path.write_text(
        json.dumps(crate, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return path


class _CrateBuilder:
    def __init__(self, bundle: ExportBundle) -> None:
        self.bundle = bundle
        self.capsule = bundle.capsule
        # (rel_path, sha256) -> @id, filled by _data_entities().
        self._output_ids: dict[tuple[str, str], str] = {}

    def build(self) -> dict[str, Any]:
        data_entities = self._data_entities()
        tools = self._tool_entities()
        actions, env_entities, container_entities = self._action_entities()
        graph: list[dict[str, Any]] = [
            {
                "@id": METADATA_FILENAME,
                "@type": "CreativeWork",
                "conformsTo": {"@id": RO_CRATE_SPEC_ID},
                "about": {"@id": "./"},
            },
            self._root_dataset(),
            {
                "@id": PROCESS_RUN_PROFILE_ID,
                "@type": "CreativeWork",
                "name": "Process Run Crate",
                "version": "0.6",
            },
            {
                "@id": "#paper-factory",
                "@type": "Organization",
                "name": "Paper Factory",
                "url": "https://github.com/SKZL-AI/paper-factory",
            },
        ]
        graph.extend(data_entities)
        graph.extend(env_entities)
        graph.extend(container_entities)
        graph.extend(tools.values())
        graph.extend(actions)
        return {
            "@context": [RO_CRATE_CONTEXT, WORKFLOW_RUN_CONTEXT],
            "@graph": graph,
        }

    # -- root & data entities ------------------------------------------------ #

    def _root_dataset(self) -> dict[str, Any]:
        has_part = sorted({
            self._data_id_for(ref.rel_path) for ref in self.bundle.declared_refs()
        } | set(self._output_ids.values()))
        return {
            "@id": "./",
            "@type": "Dataset",
            "name": (f"Paper Factory reproduction capsule "
                     f"{self.capsule.capsule_id}"),
            "description": (
                "Research object exported from Paper Factory canonical "
                "evidence (EXPORT ONLY). capsule_digest="
                f"{self.capsule.capsule_digest}"),
            "identifier": self.capsule.capsule_id,
            "conformsTo": {"@id": PROCESS_RUN_PROFILE_ID},
            "hasPart": [{"@id": pid} for pid in has_part],
            "mentions": [
                {"@id": f"#{r.execution_id}"} for r in self.bundle.receipts
            ] + [{"@id": "#capsule-digest"}],
        }

    def _data_id_for(self, rel_path: str) -> str:
        return _data_id(rel_path)

    def _data_entities(self) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = [
            {
                "@id": "#capsule-digest",
                "@type": "PropertyValue",
                "name": "capsule_digest",
                "value": self.capsule.capsule_digest,
            }
        ]
        seen: set[str] = set()

        def add(entity: dict[str, Any]) -> None:
            if entity["@id"] not in seen:
                seen.add(entity["@id"])
                entities.append(entity)

        for ref, description, extra in (
            *[(r, "declared input", {}) for r in self.bundle.inputs],
            *[(r, "declared configuration", {}) for r in self.bundle.configs],
            *[(r, "declared code", {"@type": ["File", "SoftwareSourceCode"]})
              for r in self.bundle.code],
        ):
            entity = {
                "@id": self._data_id_for(ref.rel_path),
                "@type": "File",
                "name": ref.rel_path,
                "sha256": ref.sha256,
                "description": description,
            }
            entity.update(extra)
            add(entity)

        declared_ids = set(seen)
        declared_ids.discard("#capsule-digest")
        lock = self.bundle.dependency_lock
        if lock is not None:
            add({"@id": self._data_id_for(lock.rel_path),
                 "@type": "File", "name": lock.rel_path,
                 "sha256": lock.sha256,
                 "description": "declared dependency lock"})

        output_variants = self.bundle.output_variants()
        for rel_path, variants in output_variants.items():
            # One decision per path, applied to ALL variants of that path:
            # either every variant keeps the plain path (unique content) or
            # every variant moves to a content-addressed variants/ path —
            # never a mixed state.
            ambiguous = (len(variants) > 1
                         or _data_id(rel_path) in declared_ids)
            for ref in variants:
                at_id = (f"variants/{ref.sha256[:16]}/{_data_id(rel_path)}"
                         if ambiguous else _data_id(rel_path))
                entity = {
                    "@id": at_id,
                    "@type": "File",
                    "name": rel_path,
                    "sha256": ref.sha256,
                    "description": "produced output",
                }
                if ambiguous:
                    entity["alternateName"] = rel_path
                add(entity)
                self._output_ids[(rel_path, ref.sha256)] = at_id
        return entities

    # -- tools & actions ----------------------------------------------------- #

    def _tool_entities(self) -> dict[str, dict[str, Any]]:
        tools: dict[str, dict[str, Any]] = {}
        for receipt in self.bundle.receipts:
            backend = receipt.backend
            key = (backend.kind, backend.name)
            if key not in tools:
                tool_id = f"#tool-{_slug(backend.kind)}-{_slug(backend.name)}"
                tools[key] = {
                    "@id": tool_id,
                    "@type": "SoftwareApplication",
                    "name": backend.name,
                    "softwareVersion": backend.version,
                }
        return tools

    def _tool_id(self, receipt: ExecutionReceipt) -> str:
        backend = receipt.backend
        return f"#tool-{_slug(backend.kind)}-{_slug(backend.name)}"

    def _action_entities(self) -> tuple[list[dict[str, Any]],
                                        list[dict[str, Any]],
                                        list[dict[str, Any]]]:
        actions: list[dict[str, Any]] = []
        env_entities: dict[str, dict[str, Any]] = {}
        container_entities: list[dict[str, Any]] = []

        def env_pv(pid: str, name: str, value: str) -> dict[str, str]:
            env_entities[pid] = {
                "@id": pid, "@type": "PropertyValue",
                "name": name, "value": value,
            }
            return {"@id": pid}

        env = self.capsule.environment
        base_env = [
            env_pv("#env-python-version", "python_version", env.python_version),
            env_pv("#env-platform", "platform", env.platform),
        ]
        for tool_name in sorted(env.tool_versions):
            pid = f"#env-tool-{_slug(tool_name)}"
            base_env.append(env_pv(pid, f"tool:{tool_name}",
                                   env.tool_versions[tool_name]))
        if env.dependency_lock_ref is not None:
            base_env.append(env_pv("#env-dependency-lock", "dependency_lock_ref",
                                   env.dependency_lock_ref.rel_path))

        for receipt in self.bundle.receipts:
            environment = list(base_env)
            if env.container_image:
                cid = f"#container-{_slug(env.container_image)}"
                if cid not in {c["@id"] for c in container_entities}:
                    container_entities.append({
                        "@id": cid,
                        "@type": "ContainerImage",
                        "name": env.container_image,
                    })
                action_container = {"@id": cid}
            else:
                action_container = None

            action: dict[str, Any] = {
                "@id": f"#{receipt.execution_id}",
                "@type": "CreateAction",
                "name": (f"Run {receipt.execution_id} of capsule "
                         f"{self.capsule.capsule_id}"),
                "description": (
                    f"{shlex.join(self.capsule.command)} (cwd: "
                    f"{self.capsule.cwd}; backend: {receipt.backend.kind}/"
                    f"{receipt.backend.name} {receipt.backend.version})"),
                "startTime": receipt.started_at.isoformat(),
                "endTime": receipt.finished_at.isoformat(),
                "instrument": {"@id": self._tool_id(receipt)},
                "agent": {"@id": "#paper-factory"},
                "object": [
                    {"@id": self._data_id_for(ref.rel_path)}
                    for ref in (*self.bundle.inputs, *self.bundle.configs)
                ],
                "result": [
                    {"@id": self._output_ids[(f.rel_path, f.sha256)]}
                    for f in receipt.outputs
                ],
                "environment": environment,
            }
            if action_container is not None:
                action["containerImage"] = action_container
            if receipt.status == "completed" and receipt.exit_code == 0:
                action["actionStatus"] = \
                    "http://schema.org/CompletedActionStatus"
            else:
                action["actionStatus"] = \
                    "http://schema.org/FailedActionStatus"
                reason = receipt.failure_reason or (
                    f"status={receipt.status}, exit_code={receipt.exit_code}")
                action["error"] = reason
            actions.append(action)
        return actions, list(env_entities.values()), container_entities
