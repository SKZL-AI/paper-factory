"""P35 Global closure: cross-artifact invariants U1–U16.

Every invariant reads real artifacts and reports PASS / FAIL / NOT_RUN /
UNSUPPORTED_ENVIRONMENT. A per-run HoH PASS is necessary for verification
nodes but never sufficient here — closure is Paper Factory's own.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..claims.graph import load_claims
from ..core.results import ClaimStatus, Verdict
from ..core.util import read_jsonl, sha256_file, utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome
from ..provenance.origin import origin_receipts, protected_files
from ..reviews.framework import dedupe_key, load_reviews, unresolved_blocking
from ..statistics.metrics import expected_macro_entries
from ..statistics.quantitative import (
    PFGET_ACCESSOR_LINE,
    _strip_comments,
    find_pfget_uses,
    find_pfget_uses_with_spans,
    find_quantitative,
    is_claim_section,
    manuscript_tex_files,
    normalize_tex,
)

Check = Callable[[NodeContext], tuple[str, str]]  # → (state, note)

# reference cues: a design point attributed to a cited/foreign protocol is not
# a claim about THIS run's macro (GAP-011 R3, reviewer A v4b). Real citation
# markers only — generic discourse markers ('following the', 'protocol of')
# are an evasion vehicle (reviewer B W2).
_REF_CUE = re.compile(r"\\cite|\bet\s+al\.|prior work", re.IGNORECASE)


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
    # sharpness (GAP-005): a claim that asserts evidence must name resolvable
    # artifacts — metric keys, ledger evidence ids, or existing files. A generic
    # 'evidence_ledger' placeholder or a dangling reference is not provenance.
    ws = ctx.workspace
    metric_keys: set[str] = set()
    metrics_path = ws.reports_dir / "paper_metrics.json"
    if metrics_path.exists():
        metric_keys = set(json.loads(metrics_path.read_text()).get("metrics", {}))
    ledger_ids: set[str] = set()
    ledger_path = ws.evidence_dir / "evidence_ledger.jsonl"
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                return "FAIL", f"evidence ledger unreadable line: {line[:60]!r}"
            if not isinstance(entry, dict):
                return "FAIL", f"evidence ledger line is not an object: {line[:60]!r}"
            eid = entry.get("evidence_id")
            if eid:
                if eid in ledger_ids:
                    return "FAIL", f"evidence ledger duplicate id: {eid}"
                ledger_ids.add(eid)
    vague: list[str] = []
    dangling: list[str] = []
    for c in graph.claims:
        # sharpness binds every claim that CARRIES evidence refs (any type —
        # the type field is untrusted input, reviewer A-F3); empirical claims
        # in asserting states additionally MUST carry evidence
        asserting = c.status in (ClaimStatus.VERIFIED, ClaimStatus.EVIDENCE_FOUND,
                                 ClaimStatus.PARTIAL)
        if not c.evidence:
            if c.type == "empirical" and asserting:
                vague.append(f"{c.claim_id}(empty)")
            continue
        for ref in c.evidence:
            if ref in metric_keys or ref in ledger_ids:
                continue
            if ref.strip() == "evidence_ledger":
                # the bare placeholder token, exactly — a real file named
                # results/evidence_ledger.csv is legitimate evidence (A N-A)
                vague.append(f"{c.claim_id}(placeholder)")
            elif _resolve_evidence_path(ws, ref) is not None:
                continue  # concrete artifact inside the target project
            else:
                dangling.append(f"{c.claim_id}→{ref}")
    if vague or dangling:
        return "FAIL", (f"claims with placeholder/unresolvable evidence: "
                        f"vague={vague} dangling={dangling}")
    return "PASS", f"{len(graph.claims)} claims linked"


def _resolve_evidence_path(ws, ref: str) -> Path | None:
    """A file-path evidence ref resolves only if it is a relative path that
    stays inside the TARGET PROJECT (never absolute, never .., never the
    pipeline's own .paper-factory bookkeeping — reviewer B-E1)."""
    p = Path(ref)
    if not ref or p.is_absolute() or not p.parts or ".." in p.parts:
        return None
    root = ws.target_root.resolve()
    resolved = (ws.target_root / p).resolve()
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        return None
    if rel.parts and rel.parts[0] == ".paper-factory":
        return None  # self-referential bookkeeping is not evidence
    return resolved if resolved.is_file() else None


def _manuscript_quantitative_surface(paper: Path) -> tuple[list[str], set[str]]:
    quantitative: list[str] = []
    macro_uses: set[str] = set()
    for s in manuscript_tex_files(paper):
        rel = str(s.relative_to(paper))
        body = normalize_tex(s.read_text(encoding="utf-8", errors="replace"))
        macro_uses |= find_pfget_uses(body)
        if find_quantitative(body, claim_section=is_claim_section(rel)):
            quantitative.append(rel)
    return quantitative, macro_uses


_DEF_CMD = re.compile(r"\\(?:newcommand|renewcommand|def|edef|gdef|xdef|let)\b")
_ANY_CSNAME = re.compile(r"\\csname\b")
_GRAPHICS_RE = re.compile(
    r"\\(?:includegraphics\s*\*?|pgfimage|pgfuseimage|includepdf|includesvg)"
    r"\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
_INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^}]*)\}"
                       r"|\\(?:sub)?import\s*\{([^}]*)\}\s*\{([^}]*)\}")


def _input_violations(paper: Path) -> list[str]:
    """The manuscript may only \\input/\\include/\\import content the pipeline
    actually guards: scanned manuscript files and the policy-bound generated/
    directory. References into build/ (compile output — never scanned nor
    frozen) or escaping the paper root are provenance holes (post-pilot review
    B-L1/B-M2/B-M3).
    """
    violations: list[str] = []
    for s in manuscript_tex_files(paper):
        body = _strip_comments(s.read_text(encoding="utf-8", errors="replace"))
        for m in _INPUT_RE.finditer(body):
            target = (m.group(1) or m.group(2) or "").strip()
            if not target:
                continue
            norm = target.replace("\\", "/")
            parts = [p for p in norm.split("/") if p not in ("", ".")]  # B-M2
            if norm.startswith("/") or ".." in parts:
                violations.append(f"{s.name}: input escapes paper root: {target!r}")
            elif parts and parts[0] == "build":
                violations.append(f"{s.name}: input into unguarded build/: {target!r}")
    return violations
_PF_GDEF_LINE = re.compile(r"^\\expandafter\\gdef\\csname\s+pf@(.+?)\\endcsname\{([^}]*)\}\s*$")
_NUMBERS_ALLOWED_PLAIN = {"\\makeatletter", "\\makeatother"}


def _generated_policy(paper: Path) -> tuple[list[str], dict[str, str]]:
    """generated/ is trusted, so its content is policy-bound by ALLOWLIST, not
    by a definition-token blocklist (TeX is Turing-complete — \\let and
    \\csname-built commands evade token lists; post-pilot review B-J1).

    numbers.tex: every line must be a comment, \\makeatletter/\\makeatother, the
    canonical \\pfget accessor, or a canonical \\expandafter\\gdef\\csname pf@…
    \\endcsname{value} line. All pf@ definitions are returned for full binding
    against paper_metrics.json (not just the manuscript-used subset).
    Other generated/*.tex (e.g. tables.tex): no macro definitions at all.
    """
    gen = paper / "generated"
    if not gen.exists():
        return [], {}
    violations: list[str] = []
    defs: dict[str, str] = {}
    for f in sorted(gen.glob("*.tex")):
        raw = f.read_text(encoding="utf-8", errors="replace")
        text = _strip_comments(raw)  # comments never carry semantics (B-J4)
        if f.name == "numbers.tex":
            for ln, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped in _NUMBERS_ALLOWED_PLAIN:
                    continue
                if stripped == PFGET_ACCESSOR_LINE:
                    continue  # the canonical accessor, compared exactly (B-K1)
                m = _PF_GDEF_LINE.match(stripped)
                if m:
                    defs[m.group(1)] = m.group(2)
                    continue
                violations.append(f"{f.name}:{ln}: non-canonical line {stripped[:60]!r}")
        else:
            # other generated files (e.g. tables.tex): no macro definitions and
            # no \csname indirection at all — TeX is Turing-complete, a token
            # blocklist alone is evadable (post-pilot review B-K2)
            for m in _DEF_CMD.finditer(text):
                snippet = text[max(0, m.start() - 10):m.start() + 50].replace("\n", " ")
                violations.append(f"{f.name}: macro definition not allowed here: …{snippet}…")
            for m in _ANY_CSNAME.finditer(text):
                snippet = text[max(0, m.start() - 10):m.start() + 50].replace("\n", " ")
                violations.append(f"{f.name}: \\csname indirection not allowed here: …{snippet}…")
    return violations, defs


def _labelless_macro_uses(paper: Path, metrics: dict[str, Any]) -> tuple[list[str], int]:
    """GAP-011: for every \\pfget/pf@ use in the manuscript, the surrounding
    prose must name the bound metric's field AND — when the context names a
    design point — the group must match (reviewer B: window-presence is not
    attribution; 'the fpr at load 0.9' citing the load-0.95 macro is a false
    citation). Returns (['<file>:<macro>@<pos>: <reason>', …], skipped_count).

    Attribution rule (nearest-anchor, same principle as the GAP-003 sentence
    binder): the field whose mention sits CLOSEST to the macro use must be
    the macro's own field (ties allowed). A field that is merely present
    somewhere in the window does not label the macro."""
    from ..statistics.metrics import (
        _FIELD_ALIASES,
        _FIELD_DIM_TOKENS,
        _num_scale_match,
        macro_base_names,
    )

    bases = macro_base_names(list(metrics.keys()))
    macro_field: dict[str, str | None] = {}   # original case (CamelCase split)
    macro_key: dict[str, str] = {}
    for key, stat in metrics.items():
        field = str(stat.get("field", "") or "")
        base = bases[key]
        for suffix in ("mean", "std", "n"):
            name = f"{base}{suffix}"
            macro_field[name] = field or None
            macro_key[name] = key
    all_fields = sorted({f for f in macro_field.values() if f})

    def _content_tokens(field: str) -> list[str]:
        # CamelCase is prose-splittable (A F-A): falsePositiveRate →
        # false/positive/rate
        split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", field)
        tokens = [t for t in re.split(r"[^a-z0-9]+", split.lower())
                  if len(t) >= 3 and t not in _FIELD_DIM_TOKENS]
        if not tokens and len(field) >= 3:
            # dim-token-only fields (score, rate, ratio) would be unnameable
            # and make U2 unpassable (A-R2-1): the field names itself
            tokens = [re.sub(r"[^a-z0-9]+", "", field.lower())]
        return [t for t in tokens if t]

    def _mention_positions(field: str, w: str) -> list[int]:
        positions: list[int] = []
        for alias in _FIELD_ALIASES.get(field.lower(), ()):
            stem = re.escape(alias)
            positions += [m.start() for m in re.finditer(
                rf"(?<![a-z0-9]){stem}(?:e?s)?(?![a-z0-9])", w)]
        content = _content_tokens(field)
        if content:
            hits = []
            for t in content:
                hs = [m.start() for m in re.finditer(
                    rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", w)]
                if not hs:
                    hits = []
                    break
                hits.append(min(hs))
            positions += hits
        return positions

    # siblings per (source, field): for the group-dimension check. Group and
    # fixed_design (constant design columns, GAP-011 R2/B-r1) merge into one
    # design-point view.
    by_sf: dict[tuple[str, str], list[tuple[str, dict]]] = {}
    for key, stat in metrics.items():
        merged = dict(stat.get("group") or {})
        merged.update(stat.get("fixed_design") or {})
        by_sf.setdefault((str(stat.get("source", "")),
                          str(stat.get("field", "") or "").lower()), []).append(
            (key, merged))

    bad: list[str] = []
    skipped = 0
    window = 200  # chars on each side — sentence + table-header reach
    for s in manuscript_tex_files(paper):
        body = normalize_tex(s.read_text(encoding="utf-8", errors="replace"))
        body_l = body.lower()
        infos = []
        for name, pos in find_pfget_uses_with_spans(body):
            info = {"name": name, "pos": pos, "lo": max(0, pos - window),
                    "field": macro_field.get(name)}
            if info["field"] is not None:
                merged = dict(metrics[macro_key[name]].get("group") or {})
                merged.update(metrics[macro_key[name]].get("fixed_design") or {})
                info["design"] = merged
            infos.append(info)
        for info in infos:
            field = info["field"]
            if field is None:
                skipped += 1  # legacy metric without field — visible in the note
                continue
            lo = info["lo"]
            w = body_l[lo:info["pos"] + window]
            wpos = info["pos"] - lo
            pos_map = {f: ps for f in all_fields
                       if (ps := _mention_positions(f, w))}
            own_ps = pos_map.get(field)
            if not own_ps:
                bad.append(f"{s.name}:{info['name']}@{info['pos']}: "
                           f"field '{field}' never named")
                continue
            own = min(abs(p - wpos) for p in own_ps)
            dists = {f: min(abs(p - wpos) for p in ps)
                     for f, ps in pos_map.items()}
            nearest = min(dists.values())
            if own > nearest + 5:
                other = min(dists, key=dists.get)
                other_mention_abs = lo + min(pos_map[other],
                                             key=lambda p: abs(p - wpos))
                # enumeration exception (A-R2-2): 'The fpr and latency both
                # improved: \pfget{fpr} and \pfget{latency}' — the nearer
                # foreign mention is part of an enumeration whose own macro
                # follows LATER in the text
                owned_elsewhere = any(
                    o is not info and o["field"] == other
                    and o["pos"] > info["pos"]
                    and other_mention_abs < info["pos"]
                    for o in infos)
                if not owned_elsewhere:
                    bad.append(f"{s.name}:{info['name']}@{info['pos']}: nearest "
                               f"field mention is '{other}', not '{field}' — "
                               f"misattributed macro")
                    continue
            # group check: if the window names a design point of one of this
            # metric's dimensions, it must be THIS macro's group (B-e). The
            # number must be the dimension's ARGUMENT (only connectors between
            # them — GAP-003 X1/Y1); a named point matching NEITHER this group
            # NOR any sibling is an unmeasured design point — flagged (B-r1/r2).
            # group check: a design point named as the dimension's ARGUMENT is
            # attributed to the nearest carrier macro OF THE SAME FIELD
            # (cross-field decoys cannot steal attribution — B-W1); numbers in
            # the macro's own clause are claims and must match THIS group;
            # numbers in a separate clause are design-space context and must
            # at least be measured somewhere (own ∪ siblings — B-W3/W4).
            group = info.get("design") or {}
            for dim, gv in group.items():
                dim_l = str(dim).lower()
                dim_hits = list(re.finditer(
                    rf"(?<![a-z0-9]){re.escape(dim_l)}s?(?![a-z0-9])", w))
                if not dim_hits:
                    continue
                try:
                    gvf = float(gv)
                except (TypeError, ValueError):
                    continue
                sib_vals = [float(sg[dim]) for _sk, sg in
                            by_sf.get((str(metrics[macro_key[info["name"]]].get("source", "")),
                                       field.lower()), [])
                            if dim in sg and str(sg[dim]) != str(gv)
                            and str(sg[dim]).replace(".", "", 1).lstrip("-").isdigit()]
                for m in re.finditer(r"[-+]?\b\d+(?:\.\d+)?\b", w):
                    hit = None
                    for d in dim_hits:
                        if m.end() <= d.start():
                            between = w[m.end():d.start()]
                        elif d.end() <= m.start():
                            between = w[d.end():m.start()]
                        else:
                            continue
                        if re.fullmatch(r"[\s@:=(/%-]*(?:of\s+)?", between):
                            hit = d
                            break
                    if hit is None:
                        continue  # not the dimension's argument
                    num_abs = lo + m.start()
                    # attribute to the nearest carrier OF THE SAME FIELD;
                    # only if none exists, any carrier (B-W1 decoy defense)
                    same_field = [o for o in infos if o["field"] == field
                                  and dim in (o.get("design") or {})]
                    carriers = same_field or [o for o in infos
                                              if dim in (o.get("design") or {})]
                    if carriers and min(
                            carriers, key=lambda o: abs(o["pos"] - num_abs)) is not info:
                        continue  # belongs to another macro of this field
                    # a citation cue excuses the number only when the macro's
                    # OWN design point is also named (B-W2: the cue must not
                    # launder an unattributed own-value claim)
                    seg = body_l[min(num_abs, info["pos"]):max(num_abs, info["pos"])]
                    own_named = any(
                        _num_scale_match(float(m2.group(0)), gvf)
                        for m2 in re.finditer(r"\b\d+(?:\.\d+)?\b", w))
                    if _REF_CUE.search(seg) and own_named:
                        continue  # foreign protocol, own point named — fine
                    # enumeration chain (B-W3): 'at load 0.9 and 2.0' links
                    # further design points to the same dim mention — each
                    # linked value is checked, none hides. Link forms: comma,
                    # hyphen/range dash (Y1: normalize_tex maps –/— to '-'),
                    # 'to', 'and' (+ common adverbs 'and also/even' — Y2)
                    chain = [float(m.group(0))]
                    cursor = m.end()
                    while True:
                        link = re.match(
                            r"\s*(?:,|-|\bto\b|\band\b(?:\s+(?:also|even))?)"
                            r"\s*(\d+(?:\.\d+)?)",
                            w[cursor:])
                        if not link:
                            break
                        chain.append(float(link.group(1)))
                        cursor += link.end()
                    # same-clause test EXCLUDES the number AND its chain tail —
                    # the chain's own decimal points are not clause boundaries
                    # (A-F1: otherwise '0.9 and 0.95' poisons the scan)
                    clause_seg = (w[cursor:wpos] if m.end() <= wpos
                                  else w[wpos:m.start()])
                    same_clause = not re.search(r"[.;:\n]", clause_seg)
                    for n in chain:
                        if _num_scale_match(n, gvf):
                            continue  # names THIS group — fine
                        is_sibling = any(_num_scale_match(n, sv) for sv in sib_vals)
                        if same_clause:
                            if is_sibling:
                                bad.append(f"{s.name}:{info['name']}@{info['pos']}: context "
                                           f"names {dim}={n}, macro carries {dim}={gv} — "
                                           f"wrong design point")
                            else:
                                bad.append(f"{s.name}:{info['name']}@{info['pos']}: context "
                                           f"names {dim}={n}, but no measured group of this "
                                           f"metric has it (macro carries {dim}={gv}) — "
                                           f"unmeasured design point")
                            break
                        # separate clause: design-space context — must be measured
                        # SOMEWHERE for this metric (own ∪ siblings)
                        if not is_sibling:
                            bad.append(f"{s.name}:{info['name']}@{info['pos']}: context "
                                       f"names unmeasured {dim}={n} next to the macro "
                                       f"(measured: {dim}={gv})")
                            break
                    else:
                        continue
                    break
    return bad, skipped


def _u2(ctx: NodeContext) -> tuple[str, str]:
    # Manuscript-level: numbers in the PAPER must derive from generated macros.
    ws = ctx.workspace
    audit = ws.reports_dir / "numbers_units_audit.json"
    if not audit.exists():
        return "NOT_RUN", "no numbers/units audit of the manuscript"
    try:
        findings = json.loads(audit.read_text()).get("findings", [])
    except json.JSONDecodeError:
        return "FAIL", "numbers_units_audit.json unreadable — audit result unverifiable"
    if findings:
        return "FAIL", f"{len(findings)} raw hand-typed numbers in manuscript"
    metrics_path = ws.reports_dir / "paper_metrics.json"
    metrics: dict[str, Any] = {}
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text()).get("metrics", {}) or {}
        except json.JSONDecodeError:
            return "FAIL", "paper_metrics.json unreadable — provenance unverifiable"
    # generated/ allowlist policy + FULL binding of every pf@ definition
    violations, gen_defs = _generated_policy(ws.paper_dir)
    if violations:
        return "FAIL", ("non-canonical content in generated/: "
                        + "; ".join(violations[:3]))
    input_violations = _input_violations(ws.paper_dir)
    if input_violations:
        return "FAIL", ("manuscript inputs into unguarded paths: "
                        + "; ".join(input_violations[:3]))
    if gen_defs:
        if not metrics:
            return "FAIL", "provenance macros defined but paper_metrics.json missing/empty"
        # every definition must carry the derived value (unused defs included —
        # an unused forgery today is a used forgery tomorrow; post-pilot B-J1)
        expected_all = expected_macro_entries(metrics)
        forged = sorted(k for k in gen_defs if k not in expected_all)
        if forged:
            return "FAIL", f"generated/ defines macros absent from paper_metrics.json: {forged[:5]}"
        diverged = sorted(k for k, v in gen_defs.items() if expected_all.get(k) != v)
        if diverged:
            return "FAIL", f"generated/ macro values diverge from paper_metrics.json: {diverged[:5]}"
    quantitative, macro_uses = _manuscript_quantitative_surface(ws.paper_dir)
    # fail-closed provenance gate (post-pilot audit): a quantitative claim or a
    # provenance macro without any derived metrics artifact can never PASS
    if (quantitative or macro_uses) and not metrics:
        return "FAIL", ("quantitative claims in manuscript but no derived metrics "
                        "artifact (paper_metrics.json missing/empty) — no T0/T1 provenance")
    if macro_uses:
        # manuscript uses must be defined in numbers.tex and carry the derived
        # value — a hand-written numbers.tex is forgery, not provenance (B-F3)
        unbound = sorted(macro_uses - set(gen_defs))
        if unbound:
            return "FAIL", (f"manuscript macros without metric source: {unbound[:5]}"
                            f"{'…' if len(unbound) > 5 else ''}")
        # (value binding of the definitions themselves happened above, for ALL
        # defs — used ones are a subset of that check)
        # GAP-011: value binding alone is not enough — the prose around a
        # \pfget use must NAME the bound metric's field, otherwise
        # 'latency improved to \pfget{nll…mean}' passes while citing the nll
        # metric for a latency sentence (reviewer B chain finding).
        mislabeled, label_skipped = _labelless_macro_uses(ws.paper_dir, metrics)
        if mislabeled:
            return "FAIL", ("provenance macro used without naming its metric in "
                            f"context: {mislabeled[:5]}"
                            f"{'…' if len(mislabeled) > 5 else ''}")
        if label_skipped:
            return "PASS", (f"manuscript numbers derive from generated macros "
                            f"({label_skipped} macro use(s) on metrics without "
                            f"field label — label check not applicable)")
    return "PASS", "manuscript numbers derive from generated macros"


def _u3(ctx: NodeContext) -> tuple[str, str]:
    ws = ctx.workspace
    for name in ("figures_manifest.json", "tables_manifest.json"):
        p = ws.reports_dir / name
        if not p.exists():
            return "NOT_RUN", f"{name} missing"
        manifest = json.loads(p.read_text())
        entries = manifest.get("figures") or manifest.get("tables") or []
        # every artifact a manifest declares — entry outputs, per-figure files,
        # entry-level paths, manifest-level output (dict or list forms) — must
        # be content-pinned and hash-matching; existence alone is not binding
        # (post-pilot review B-J2/B-L3/B-M5)
        declared: list[Any] = []
        m_out = manifest.get("output")
        if isinstance(m_out, dict):
            declared.append(m_out)
        elif isinstance(m_out, list):
            declared.extend(m_out)
        for e in entries:
            out = e.get("output") or e.get("outputs")
            if isinstance(out, dict):
                declared.extend(out.values())
            elif isinstance(out, list):
                declared.extend(out)
            files = e.get("files") or {}
            if isinstance(files, dict):
                declared.extend(v for v in files.values() if isinstance(v, dict))
            elif isinstance(files, list):
                declared.extend(files)
            if e.get("path"):
                declared.append({"path": e["path"], "sha256": e.get("sha256")})
        for d in declared:
            if isinstance(d, str):
                d = {"path": d}
            rel, want = d.get("path"), d.get("sha256")
            if not rel:
                continue
            if not want:
                return "FAIL", f"manifest artifact without content pin: {rel}"
            f = ws.root / rel
            if not f.exists():
                f = ws.target_root / rel
            if not f.exists():
                return "FAIL", f"pinned artifact missing: {rel}"
            if sha256_file(f) != want:
                return "FAIL", f"artifact diverged from manifest pin: {rel}"
        inputs: dict[str, str] = dict(manifest.get("input_data_hashes") or {})
        for e in entries:
            inputs.update(e.get("input_data_hashes") or {})
        for rel, want in inputs.items():
            f = ws.root / rel
            if not f.exists():
                f = ws.target_root / rel
            if not f.exists():
                return "FAIL", f"pinned input missing: {rel}"
            if sha256_file(f) != want:
                return "FAIL", f"input data diverged from manifest pin: {rel}"
        # reverse direction (post-pilot review B-M1): every figure the
        # manuscript references must be declared+pinned in the figures manifest
        if name == "figures_manifest.json":
            pinned = set()
            for d in declared:
                if isinstance(d, str):
                    d = {"path": d}
                if d.get("path"):
                    pinned.add(str(d["path"]))
            for s in manuscript_tex_files(ws.paper_dir):
                body = _strip_comments(s.read_text(encoding="utf-8", errors="replace"))
                for m in _GRAPHICS_RE.finditer(body):
                    target = m.group(1).strip().lstrip("./")
                    candidates = {f"paper/{target}",
                                  *(f"paper/{target}.{ext}" for ext in ("pdf", "png", "svg"))}
                    if not candidates & pinned:
                        return "FAIL", (f"manuscript figure not declared/pinned in "
                                        f"figures manifest: {target!r} (in {s.name})")
        # reverse existence (B-O2): a generated tables.tex without a manifest
        # pin is unbound content in a trusted directory
        if name == "tables_manifest.json":
            tables_tex = ws.paper_dir / "generated" / "tables.tex"
            if tables_tex.exists():
                pinned_paths = {str(d.get("path")) for d in declared
                                if isinstance(d, dict) and d.get("path")}
                if "paper/generated/tables.tex" not in pinned_paths:
                    return "FAIL", ("generated/tables.tex exists but is not declared "
                                    "and pinned in tables_manifest.json")
    return "PASS", "figures/tables match manifests (existence + content hashes)"


def _u4(ctx: NodeContext) -> tuple[str, str]:
    # Post-remediation audit wins — but only when it is NOT OLDER than the P21
    # audit: a stale final from an earlier run/remediation must never mask a
    # fresher, stricter audit (reviewer B R3-B2)
    ws = ctx.workspace
    final = ws.reports_dir / "citation_audit_final.json"
    audit = ws.reports_dir / "citation_audit.json"

    def _ts(p) -> str:
        try:
            v = json.loads(p.read_text()).get("audited_at")
        except Exception:
            return ""  # unreadable audit never wins the freshness race
        # non-string values (null, numbers) never win either — str(None) would
        # lexicographically beat any real timestamp (reviewer B R5-NIT)
        return v if isinstance(v, str) else ""

    chosen = None
    if audit.exists():
        chosen = audit
    # a final WITHOUT a readable audited_at never wins the freshness race
    # (str(None)="None" would lexicographically beat any real timestamp).
    # Strictly-greater: on a same-second tie the P21 audit wins — a
    # post-remediation final must never mask a fresh CRITICAL through a
    # timestamp tie (reviewer B B-4; fail-closed direction)
    if final.exists() and (chosen is None
                           or (_ts(final) and _ts(final) > _ts(audit))):
        chosen = final
    if chosen is None:
        return "NOT_RUN", "no citation audit"
    audit = chosen
    data = json.loads(audit.read_text())
    findings = data.get("findings", [])
    crit = [f for f in findings if f.get("kind") in ("false_citation",
                                                     "citation_identity_mismatch")]
    # defense in depth: a record-level IDENTITY_MISMATCH must fail closure even
    # when a hand-built/corrupt audit lost its finding (reviewer B B-3)
    crit_keys = {f.get("key") for f in crit}
    crit_keys |= {r.get("key") for r in data.get("entries", [])
                  if r.get("verdict") == "IDENTITY_MISMATCH"}
    crit_keys.discard(None)
    if crit_keys:
        return "FAIL", (f"false or identity-mismatched citations: "
                        f"{sorted(crit_keys)}")
    if data.get("offline"):
        return "NOT_RUN", "citation audit ran offline — verification pending"
    # B R2-F1 (MAJOR): never attest "resolve" for citations nothing verified —
    # T4-derived entries without DOI and network-unverifiable ones block the
    # closure claim
    unverifiable = [f for f in findings
                    if f.get("kind") in ("unverifiable_citation", "unverifiable_network")]
    if unverifiable:
        kinds = sorted({str(f.get("kind")) for f in unverifiable})
        return "DEGRADED", (f"{len(unverifiable)} citation(s) unverifiable "
                            f"({', '.join(kinds)}): "
                            f"{[f.get('key') for f in unverifiable]}")
    src = "post-remediation" if audit.name.endswith("final.json") else "P21"
    no_doi = [f for f in findings if f.get("kind") == "no_doi"]
    unjudgeable = [f for f in findings if f.get("kind") == "identity_unjudgeable"]
    if no_doi or unjudgeable:
        # books/tech reports legitimately lack DOIs, and a resolved citation
        # whose identity could not be compared is verified only on
        # resolvability — honest scope, not a blanket "all resolve" claim
        parts = []
        if no_doi:
            parts.append(f"{len(no_doi)} without DOI not resolvable (MINOR): "
                         f"{[f.get('key') for f in no_doi]}")
        if unjudgeable:
            parts.append(f"{len(unjudgeable)} resolve but identity not checkable "
                         f"(MINOR): {[f.get('key') for f in unjudgeable]}")
        return "PASS", (f"all DOI-carrying citations resolve ({src} audit); "
                        + "; ".join(parts))
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
        unique = len({dedupe_key(f) for f in blocking})
        return "FAIL", (f"{len(blocking)} unresolved CRITICAL/MAJOR findings "
                        f"({unique} unique)")
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
    from ..core.util import sha256_file

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
    if pointer.get("export_status") != "PASS":
        return "FAIL", f"active release export did not pass (export_status={pointer.get('export_status')!r})"
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
    if not data.get("inbox_items"):
        return "HUMAN_REQUIRED", "paperpal manual bridge pending"
    ev = data.get("evidence_class")
    if ev == "external_paperpal_declared":
        return "PASS", "external paperpal results delivered (declared provenance)"
    if ev == "operator_check":
        return "DEGRADED", "manual operator check only — no external Paperpal evidence"
    # fail-closed: pre-audit state files recorded inbox items without any
    # provenance classification — provenance must be re-established by a human
    return "HUMAN_REQUIRED", "inbox items without provenance classification"


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
    if data.get("evidence_class") != "external_paperpal_declared":
        # an operator check rewrites nothing external — there is nothing to
        # reconcile, and claiming reconciliation would be fabricated evidence
        return "NOT_RUN", "no external edits — operator check needs no reconciliation"
    diff = ctx.workspace.reports_dir / "semantic_diff.json"
    if not diff.exists():
        return "FAIL", "external edits without semantic reconciliation"
    diff_data = json.loads(diff.read_text())
    if diff_data.get("external_edits"):
        return "PASS", "external edits semantically reconciled"
    return "PASS", "external check without prose edits; numbers/claims re-validated"


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
    outcome = (Verdict.FAIL if failed else Verdict.HUMAN_REQUIRED if human
               else Verdict.DEGRADED if (degraded or not_run) else Verdict.PASS)
    # B3: the release pointer must not claim a bare "PASS" while closure fails —
    # stamp the closure outcome onto the active bundle pointer (P33 runs before
    # P35 by design, so the pointer is completed here, where the truth exists)
    pointer_path = ctx.workspace.reports_dir / "current_release.json"
    if pointer_path.exists():
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["closure_overall"] = outcome.value
        pointer["closure_at"] = report["closed_at"]
        write_json(pointer_path, pointer)
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
