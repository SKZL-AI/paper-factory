"""P35 Global closure: cross-artifact invariants U1–U16.

Every invariant reads real artifacts and reports PASS / FAIL / NOT_RUN /
UNSUPPORTED_ENVIRONMENT. A per-run HoH PASS is necessary for verification
nodes but never sufficient here — closure is Paper Factory's own.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..claims.graph import load_claims
from ..core.results import Verdict
from ..core.util import read_jsonl, sha256_file, utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome
from ..provenance.firewall import is_protected
from ..provenance.origin import origin_receipts, protected_files
from ..reviews.framework import load_reviews, unresolved_blocking

Check = Callable[[NodeContext], tuple[str, str]]  # → (state, note)


def _u1(ctx: NodeContext) -> tuple[str, str]:
    graph_path = ctx.workspace.claims_dir / "claims.yaml"
    if not graph_path.exists():
        return "NOT_RUN", "no claim graph"
    graph = load_claims(graph_path)
    bad = [c.claim_id for c in graph.claims if c.type == "empirical" and not c.evidence
           and c.status.value == "VERIFIED"]
    if bad:
        return "FAIL", f"verified empirical claims without evidence: {bad}"
    unsupported = [c.claim_id for c in graph.unsupported_final_claims()]
    if unsupported:
        return "FAIL", f"final empirical claims unsupported/contradicted/proposed: {unsupported}"
    return "PASS", f"{len(graph.claims)} claims linked"


def _u2(ctx: NodeContext) -> tuple[str, str]:
    # Manuscript-level: numbers in the PAPER must derive from generated macros.
    audit = ctx.workspace.reports_dir / "numbers_units_audit.json"
    if not audit.exists():
        return "NOT_RUN", "no numbers/units audit of the manuscript"
    findings = json.loads(audit.read_text()).get("findings", [])
    if findings:
        return "FAIL", f"{len(findings)} raw hand-typed numbers in manuscript"
    return "PASS", "manuscript numbers derive from generated macros"


def _u3(ctx: NodeContext) -> tuple[str, str]:
    ws = ctx.workspace
    for name in ("figures_manifest.json", "tables_manifest.json"):
        p = ws.reports_dir / name
        if not p.exists():
            return "NOT_RUN", f"{name} missing"
        manifest = json.loads(p.read_text())
        entries = manifest.get("figures") or manifest.get("tables") or []
        for e in entries:
            out = e.get("output") or e.get("outputs") or {}
            paths = list(out.values()) if isinstance(out, dict) else ([e["path"]] if e.get("path") else [])
            for rel in paths:
                if not Path(rel).exists() and not (ws.root / rel).exists():
                    return "FAIL", f"manifest entry missing artifact: {rel}"
    return "PASS", "figures/tables match manifests"


def _u4(ctx: NodeContext) -> tuple[str, str]:
    # Post-remediation audit wins; otherwise the P21 audit of the manuscript bib.
    ws = ctx.workspace
    final = ws.reports_dir / "citation_audit_final.json"
    audit = final if final.exists() else ws.reports_dir / "citation_audit.json"
    if not audit.exists():
        return "NOT_RUN", "no citation audit"
    data = json.loads(audit.read_text())
    crit = [f for f in data.get("findings", []) if f.get("kind") == "false_citation"]
    if crit:
        return "FAIL", f"false citations: {[f.get('key') for f in crit]}"
    if data.get("offline"):
        return "NOT_RUN", "citation audit ran offline — verification pending"
    src = "post-remediation" if audit.name.endswith("final.json") else "P21"
    return "PASS", f"all citations resolve ({src} audit)"


def _u5(ctx: NodeContext) -> tuple[str, str]:
    reviews, invalid = load_reviews(ctx.workspace.reviews_dir)
    if invalid:
        # fail closed: a corrupt review artifact could hide CRITICAL/MAJOR
        findings = [f"{i['path']} ({i['error'].splitlines()[0] if i['error'] else '?'})"
                    for i in invalid]
        return "FAIL", f"REVIEW_ARTIFACT_INVALID: {findings}"
    if not reviews:
        return "NOT_RUN", "no reviews recorded"
    blocking = unresolved_blocking(reviews)
    if blocking:
        return "FAIL", f"{len(blocking)} unresolved CRITICAL/MAJOR findings"
    return "PASS", f"{len(reviews)} reviews, none blocking"


def _validated_rel(ws, rel: str) -> Path | None:
    """Resolve a pointer-supplied workspace-relative path; None when it is
    empty, degenerate, absolute, escaping, or resolving outside the workspace
    (e.g. through a symlinked bundle directory)."""
    p = Path(rel)
    if not rel or p.is_absolute() or not p.parts or ".." in p.parts:
        return None
    resolved = (ws.root / p).resolve()
    try:
        resolved.relative_to(ws.root.resolve())
    except ValueError:
        return None
    return resolved


def _u6(ctx: NodeContext) -> tuple[str, str]:
    # reviewed protected manuscript set == frozen set == release set: the full
    # canonical freeze manifest is compared, not just main.tex
    from ..reviews.remediation import compute_freeze_manifest, compute_freeze_symlinks

    ws = ctx.workspace
    freeze = ws.reports_dir / "scientific_freeze.json"
    if not freeze.exists():
        return "NOT_RUN", "no freeze record"
    frozen = json.loads(freeze.read_text())
    files = frozen.get("files")
    if not isinstance(files, dict) or not files:
        return "FAIL", "freeze record has no file manifest"
    unsafe = [k for k in files if Path(k).is_absolute() or ".." in Path(k).parts]
    if unsafe:
        return "FAIL", f"unsafe paths in freeze manifest: {unsafe[:3]}"
    paper = ws.paper_dir
    if not paper.exists():
        return "NOT_RUN", "no manuscript"
    current = compute_freeze_manifest(paper)
    problems = []
    missing = sorted(k for k in files if k not in current)
    changed = sorted(k for k in files if k in current and current[k] != files[k])
    added = sorted(k for k in current if k not in files)
    if missing:
        problems.append(f"frozen files deleted: {missing[:5]}")
    if changed:
        problems.append(f"frozen files mutated: {changed[:5]}")
    if added:
        problems.append(f"files added after freeze: {added[:5]}")
    frozen_links = frozen.get("symlinks", {})
    frozen_link_hashes = frozen.get("symlink_hashes", {})
    current_links, current_link_hashes = compute_freeze_symlinks(paper, allowed_root=ws.root)
    if frozen_links != current_links:
        problems.append(
            f"symlink map changed after freeze: frozen {sorted(frozen_links)} vs "
            f"current {sorted(current_links)}")
    changed_targets = sorted(k for k, h in frozen_link_hashes.items()
                             if current_link_hashes.get(k) != h)
    if changed_targets:
        problems.append(f"symlink target content changed after freeze: {changed_targets[:5]}")
    # release side: the active bundle must carry the identical frozen set
    # (minus the paths the release policy deliberately excludes)
    pointer_path = ws.reports_dir / "current_release.json"
    if pointer_path.exists():
        pointer = json.loads(pointer_path.read_text())
        bundle_rel = pointer.get("bundle", "")
        if not bundle_rel.startswith("release/"):
            return "FAIL", f"bundle path outside release/ in pointer: {bundle_rel!r}"
        bundle_root = _validated_rel(ws, bundle_rel)
        if bundle_root is None:
            return "FAIL", ("unsafe or degenerate bundle path in release pointer: "
                            f"{bundle_rel!r}")
        bundle_paper = bundle_root / "paper"
        if not bundle_paper.exists():
            problems.append("active release bundle has no manuscript tree")
        else:
            excluded = set()
            if not ctx.config.release.include_chat_logs:
                # mirrors the export filter exactly: link name OR link target
                # matching the chat heuristic is excluded from the bundle
                def _chaty(s: str) -> bool:
                    return any(h in s.lower() for h in ("chat", "transcript", "handoff"))
                excluded = {k for k in files if _chaty(k)}
                excluded |= {k for k, tgt in frozen_links.items()
                             if _chaty(k) or _chaty(str(tgt))}
            bundle_cur = compute_freeze_manifest(bundle_paper)
            # excluded means "allowed to be ABSENT" — a policy-excluded path
            # present in the bundle at all is a release violation (e.g. a
            # chat transcript smuggled in after export)
            bpresent = sorted(k for k in excluded if k in bundle_cur)
            if bpresent:
                problems.append(f"policy-excluded files present in bundle: {bpresent[:5]}")
            bmissing = sorted(k for k in files if k not in excluded and k not in bundle_cur)
            bchanged = sorted(k for k in files
                              if k not in excluded and k in bundle_cur
                              and bundle_cur[k] != files[k])
            # the export never ships symlinks — any symlink inside the bundle
            # manuscript tree is tampering
            bundle_links, _ = compute_freeze_symlinks(bundle_paper)
            if bundle_links:
                problems.append(f"bundle contains symlinks: {sorted(bundle_links)[:5]}")
            # export materializes internal symlinks as regular copies — those
            # copies must exist and match the pinned target content; a
            # regular file at a frozen EXTERNAL symlink path is an addition
            materialized = set(frozen_link_hashes)
            for rel in sorted(materialized - excluded):
                if rel not in bundle_cur:
                    problems.append(f"bundle missing materialized symlink copy: {rel}")
                elif bundle_cur[rel] != frozen_link_hashes[rel]:
                    problems.append(f"bundle copy at frozen symlink path diverges: {rel}")
            badded = sorted(k for k in bundle_cur
                            if k not in files and k not in materialized)
            if bmissing:
                problems.append(f"bundle missing frozen files: {bmissing[:5]}")
            if bchanged:
                problems.append(f"bundle files diverge from freeze: {bchanged[:5]}")
            if badded:
                problems.append(f"bundle carries files outside the freeze: {badded[:5]}")
    if problems:
        return "FAIL", "; ".join(problems)
    return "PASS", f"{len(files)} frozen files hash-identical (reviewed == frozen == release)"


def _u7(ctx: NodeContext) -> tuple[str, str]:
    """Code/data commits match manifests: re-hash the evidence artifacts and
    compare against the intake ledger; verification-grade nodes must carry
    receipts when HoH ran."""
    from ..core.util import read_jsonl, sha256_file

    ws = ctx.workspace
    ledger = ws.evidence_dir / "evidence_ledger.jsonl"
    if not ledger.exists():
        return "NOT_RUN", "no evidence ledger"
    mismatches = []
    checked = 0
    for rec in read_jsonl(ledger):
        p = ws.target_root / rec["path"]
        if not p.exists():
            mismatches.append(f"{rec['path']}: missing")
            continue
        checked += 1
        if sha256_file(p) != rec["sha256"]:
            mismatches.append(f"{rec['path']}: hash changed after intake")
    if mismatches:
        return "FAIL", f"evidence drifted: {mismatches[:5]}"
    hoh_enabled = [n for n in ctx.config.verification.hoh_nodes]
    receipts_missing = [n for n in hoh_enabled
                        if not ws.receipts_for(ctx.run_id, n)]
    if hoh_enabled and receipts_missing:
        return "FAIL", f"verification nodes without receipts: {receipts_missing}"
    return "PASS", f"{checked} artifacts hash-identical to intake; receipts on record"


def _u8(ctx: NodeContext) -> tuple[str, str]:
    # bound to the ACTIVE bundle via the pointer P33 persists — never a
    # lexicographic guess over parked/FAILED/older bundles. The binding is
    # fail-closed: a pointer missing its status/hash/bundle, or a scan without
    # a matching scanned_root, is FAIL — not an unpinned pass.
    ws = ctx.workspace
    pointer_path = ws.reports_dir / "current_release.json"
    if not pointer_path.exists():
        return "NOT_RUN", "no active release bundle (P33 has not exported)"
    pointer = json.loads(pointer_path.read_text())
    if pointer.get("status") != "PASS":
        return "FAIL", f"active release export did not pass (status={pointer.get('status')!r})"
    bundle_rel = pointer.get("bundle", "")
    if not bundle_rel.startswith("release/"):
        return "FAIL", f"bundle path outside release/ in pointer: {bundle_rel!r}"
    bundle_root = _validated_rel(ws, bundle_rel)
    if bundle_root is None:
        return "FAIL", ("unsafe or degenerate bundle path in release pointer: "
                        f"{bundle_rel!r}")
    scan_rel = pointer.get("secret_scan", "")
    if not scan_rel.startswith(bundle_rel + "/"):
        return "FAIL", f"scan path {scan_rel!r} not inside active bundle {bundle_rel!r}"
    scan_path = _validated_rel(ws, scan_rel)
    if scan_path is None:
        return "FAIL", ("unsafe scan path in release pointer: "
                        f"{pointer.get('secret_scan')!r}")
    recorded = pointer.get("secret_scan_sha256")
    if not recorded:
        return "FAIL", "release pointer lacks the scan hash pin"
    if not scan_path.exists():
        return "FAIL", f"active bundle scan missing: {pointer['secret_scan']}"
    if sha256_file(scan_path) != recorded:
        return "FAIL", "secret_scan.json changed since export"
    scan = json.loads(scan_path.read_text())
    scanned_root = scan.get("scanned_root")
    if not scanned_root:
        return "FAIL", "scan report lacks scanned_root"
    if Path(scanned_root).resolve() != bundle_root.resolve():
        return "FAIL", f"scan belongs to {scanned_root}, not active bundle {pointer['bundle']}"
    verdict = scan.get("verdict")
    if verdict != "PASS":
        return "FAIL", f"secret scan verdict: {verdict}"
    # full-bundle tamper evidence: the pointer pins every file of the bundle
    # (P33 export set + P34 build outputs). Anything missing, mutated, added
    # or symlinked afterwards is a release violation.
    manifest = pointer.get("bundle_files")
    if not isinstance(manifest, dict) or not manifest:
        return "FAIL", "release pointer lacks the full bundle manifest"
    bad_keys = [k for k in manifest if Path(k).is_absolute() or ".." in Path(k).parts]
    if bad_keys:
        return "FAIL", f"unsafe paths in bundle manifest: {bad_keys[:3]}"
    problems = []
    current_files: dict[str, str] = {}
    for p in sorted(bundle_root.rglob("*")):
        if p.is_symlink():
            problems.append(f"symlink in bundle: {p.relative_to(bundle_root)}")
            continue
        if p.is_file():
            current_files[p.relative_to(bundle_root).as_posix()] = sha256_file(p)
    for rel, pinned in manifest.items():
        if rel not in current_files:
            problems.append(f"bundle file missing: {rel}")
        elif current_files[rel] != pinned:
            problems.append(f"bundle file mutated: {rel}")
    extra = sorted(k for k in current_files if k not in manifest)
    if extra:
        problems.append(f"unpinned files in bundle: {extra[:5]}")
    if problems:
        return "FAIL", "; ".join(problems[:3])
    return "PASS", (f"active bundle {pointer['bundle']} scanned clean "
                    f"({scan.get('scanned_files')} files), "
                    f"{len(manifest)} files hash-pinned")


def _u9(ctx: NodeContext) -> tuple[str, str]:
    state = ctx.workspace.reports_dir / "paperpal_state.json"
    if not state.exists():
        return "NOT_RUN", "paperpal state missing"
    data = json.loads(state.read_text())
    if data.get("inbox_items"):
        return "PASS", "paperpal results delivered"
    return "HUMAN_REQUIRED", "paperpal manual bridge pending"


def _u10(ctx: NodeContext) -> tuple[str, str]:
    ws = ctx.workspace
    rep = ws.reports_dir / "clean_rebuild.json"
    if not rep.exists():
        return "NOT_RUN", "no clean rebuild report"
    data = json.loads(rep.read_text())
    if not data.get("pdf_produced"):
        return "FAIL", "clean rebuild produced no pdf"
    pdf = Path(data.get("pdf_path", ""))
    if not pdf.exists():
        return "FAIL", f"rebuilt pdf missing: {pdf}"
    freeze = ws.reports_dir / "scientific_freeze.json"
    if freeze.exists():
        frozen_at = json.loads(freeze.read_text()).get("frozen_at", "")
        if data.get("rebuilt_at", "") < frozen_at:
            return "FAIL", "rebuild predates the scientific freeze (stale)"
    return "PASS", "clean bundle rebuilds (post-freeze, this run)"


def _u11(ctx: NodeContext) -> tuple[str, str]:
    ws = ctx.workspace
    receipts = origin_receipts(ws)
    protected = protected_files(ws, ctx.policy.protected_final_prose_paths)
    if not protected:
        return "NOT_RUN", "no protected files yet"
    covered = {r["rel_path"] for r in receipts}
    missing = [p for p in protected if p not in covered]
    if missing:
        return "FAIL", f"protected files without origin receipts: {missing}"
    return "PASS", f"{len(protected)} protected files have origin receipts"


def _u12(ctx: NodeContext) -> tuple[str, str]:
    ws = ctx.workspace
    if not origin_receipts(ws):
        return "NOT_RUN", "no origin receipts on record"
    forbidden = []
    for r in origin_receipts(ws):
        fam = (r.get("backend") or {}).get("family", "unknown")
        if ctx.policy.provenance.disallow_anthropic_generated_final_prose and fam == "anthropic":
            forbidden.append(r["rel_path"])
    if forbidden:
        return "FAIL", f"forbidden model family wrote prose: {sorted(set(forbidden))}"
    return "PASS", "no forbidden origin on protected paths"


def _u13(ctx: NodeContext) -> tuple[str, str]:
    ws = ctx.workspace
    if not origin_receipts(ws):
        return "NOT_RUN", "no origin receipts on record"
    unknown = [r["rel_path"] for r in origin_receipts(ws)
               if (r.get("backend") or {}).get("family", "unknown") == "unknown"]
    if unknown:
        return "FAIL", f"unknown backend wrote prose: {sorted(set(unknown))}"
    return "PASS", "backend identity known for all prose writers"


def _u14(ctx: NodeContext) -> tuple[str, str]:
    receipts = origin_receipts(ctx.workspace)
    if not receipts:
        return "NOT_RUN", "no origin receipts — marking never assessed"
    statuses = {(r.get("backend") or {}).get("marking_status", "unknown") for r in receipts}
    # honesty rule: 'documented_no_marking' may only appear with a registry entry
    # backing it; otherwise the claim is fabricated certainty.
    for r in receipts:
        backend = r.get("backend") or {}
        claimed = backend.get("marking_status", "unknown")
        if claimed == "documented_no_marking":
            registry_status = ctx.marking.status_for(
                backend.get("provider_family", "unknown"), backend.get("model_family", "unknown"))
            if registry_status != "documented_no_marking":
                return "FAIL", (f"origin receipt claims documented_no_marking for "
                                f"{backend.get('provider_family')}/{backend.get('model_family')} "
                                f"but registry says {registry_status}")
    return "PASS", f"marking statuses reported honestly: {sorted(statuses)}"


def _u15(ctx: NodeContext) -> tuple[str, str]:
    # reviewer replacement prose must not be silently copied: remediation records
    rem = ctx.workspace.reports_dir / "remediation_log.json"
    if not rem.exists():
        return "NOT_RUN", "no remediation happened"
    data = json.loads(rem.read_text())
    copied = [r for r in data.get("entries", []) if r.get("reviewer_prose_copied")]
    if copied:
        return "FAIL", "reviewer replacement prose copied into manuscript"
    return "PASS", "remediation reconstructed from primary evidence"


def _u16(ctx: NodeContext) -> tuple[str, str]:
    state = ctx.workspace.reports_dir / "paperpal_state.json"
    if not state.exists():
        return "NOT_RUN", "no paperpal state"
    data = json.loads(state.read_text())
    if not data.get("inbox_items"):
        return "NOT_RUN", "no external paperpal edits"
    diff = ctx.workspace.reports_dir / "semantic_diff.json"
    if not diff.exists():
        return "FAIL", "external edits without semantic reconciliation"
    return "PASS", "external edits semantically reconciled"


U_CHECKS: dict[str, tuple[str, Check]] = {
    "U1": ("every primary claim has evidence", _u1),
    "U2": ("every scientific number matches generated source", _u2),
    "U3": ("figures/tables match their manifests", _u3),
    "U4": ("citations resolve and support the contextual claim", _u4),
    "U5": ("no unresolved CRITICAL/MAJOR review finding", _u5),
    "U6": ("reviewed manuscript == release manuscript", _u6),
    "U7": ("code/data commits match manifests", _u7),
    "U8": ("no secrets/private transcripts enter release", _u8),
    "U9": ("paperpal state PASS or explicit HUMAN_REQUIRED", _u9),
    "U10": ("clean bundle independently rebuilds", _u10),
    "U11": ("final-prose files have allowed origin receipts", _u11),
    "U12": ("forbidden model families did not modify protected prose", _u12),
    "U13": ("backend identity known for final writer invocations", _u13),
    "U14": ("marking status reported honestly", _u14),
    "U15": ("reviewer replacement prose not silently copied", _u15),
    "U16": ("external Paperpal edits underwent semantic reconciliation", _u16),
}


def run_global_closure(ctx: NodeContext) -> NodeOutcome:
    results: dict[str, Any] = {}
    for uid, (title, fn) in U_CHECKS.items():
        try:
            state, note = fn(ctx)
        except Exception as exc:
            # fail-closed: a crashed checker is never silent evidence
            state, note = "FAIL", f"checker error: {type(exc).__name__}: {exc}"
        results[uid] = {"title": title, "state": state, "note": note}
    failed = [u for u, r in results.items() if r["state"] == "FAIL"]
    degraded = [u for u, r in results.items() if r["state"] == "DEGRADED"]
    not_run = [u for u, r in results.items() if r["state"] == "NOT_RUN"]
    human = [u for u, r in results.items() if r["state"] == "HUMAN_REQUIRED"]
    # fail closed: a state outside the known vocabulary is never a PASS
    known = {"PASS", "FAIL", "DEGRADED", "NOT_RUN", "HUMAN_REQUIRED"}
    unknown = [u for u, r in results.items() if r["state"] not in known]
    if unknown:
        failed = failed + unknown
    report = {"closed_at": utcnow(), "invariants": results, "failed": failed,
              "degraded": degraded, "not_run": not_run, "human_required": human,
              "unknown_states": unknown}
    write_json(ctx.workspace.reports_dir / "global_closure.json", report)
    if failed:
        return NodeOutcome(Verdict.FAIL, {"failed": failed, "not_run": not_run})
    if human:
        return NodeOutcome(Verdict.HUMAN_REQUIRED, {"human_required": human, "not_run": not_run})
    # a degraded invariant must never round up to PASS — it blocks CLOSED
    # (run_status_overall requires P35 == PASS)
    if degraded:
        return NodeOutcome(Verdict.DEGRADED, {"degraded": degraded, "not_run": not_run,
                                              "note": "degraded invariants never round up to PASS"})
    if not_run:
        return NodeOutcome(Verdict.DEGRADED, {"not_run": not_run,
                                              "note": "invariants without evidence stay NOT_RUN"})
    return NodeOutcome(Verdict.PASS, {"invariants": len(results)})
