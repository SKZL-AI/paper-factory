"""Regression tests for the release-integrity hardening (H1–H4) and the P20
section-check wiring. All checks are local files only — no LLM invocations,
no HoH runs, no network.

H1: secret scan never false-greens (streaming, chunk overlap, symlinks)
H2: U6 compares the full canonical freeze manifest (workspace + bundle)
H3: U8 binds to the active bundle via the P33 pointer (no lexicographic guess)
H4: corrupt review artifacts fail closed (REVIEW_ARTIFACT_INVALID)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from paper_factory.core.config import (MarkingRegistry, PaperFactoryConfig,
                                       ProviderPolicyConfig, ProvidersConfig)
from paper_factory.core.results import Verdict
from paper_factory.core.util import read_json, sha256_file, write_json
from paper_factory.dag.executor import NodeContext
from paper_factory.dag.handlers import build_handlers
from paper_factory.manuscript.scaffold import run_manuscript_architecture
from paper_factory.release import closure as closure_mod
from paper_factory.release.export import run_clean_export
from paper_factory.release.secrets import CHUNK_SIZE, scan_tree
from paper_factory.reviews.framework import load_reviews
from paper_factory.reviews.remediation import run_remediation, run_scientific_freeze
from paper_factory.state.store import Workspace

SECRET = "sk-ant-" + "A1b2" * 10  # 47 chars of key-shaped material


def _ctx(tmp_path: Path, *, allow_writer: bool = False) -> NodeContext:
    policy = ProviderPolicyConfig()
    if allow_writer:
        # mirrors tests/e2e-config: the deterministic writer role may write prose
        policy = ProviderPolicyConfig(role_policy={
            "manuscript_writer": {"writes_final_prose": True,
                                  "preferred_harnesses": ["kimi"]}})
    return NodeContext(workspace=Workspace(tmp_path), run_id="test-hardening",
                       config=PaperFactoryConfig(), providers=ProvidersConfig(),
                       policy=policy, marking=MarkingRegistry(),
                       offline=True, strict=True)


# ---------------------------------------------------------------------------
# H1: secret scan — large files streamed, chunk boundaries covered, symlinks fail
# ---------------------------------------------------------------------------

def test_h1_large_file_with_secret_fails(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    payload = ("lorem ipsum dolor sit amet " * 40).encode()  # ~1 KiB
    with (bundle / "big.log").open("wb") as fh:
        while fh.tell() < 5_500_000:
            fh.write(payload)
        fh.write(SECRET.encode())  # secret at >5 MB — previously skipped
        fh.write(payload)
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    assert any(f["kind"] == "anthropic_key" for f in out["findings"])
    assert out["scanned_files"] == 1


def test_h1_secret_spanning_chunk_boundary_fails(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    secret = SECRET.encode()
    (bundle / "edge.txt").write_bytes(b"x" * (CHUNK_SIZE - 10) + secret + b"y" * 100)
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    kinds = [f["kind"] for f in out["findings"]]
    assert "anthropic_key" in kinds
    # the overlap window must not double-report the boundary match
    assert kinds.count("anthropic_key") == 1


def test_h1_clean_large_file_passes(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    with (bundle / "big.txt").open("w", encoding="utf-8") as fh:
        for i in range(0, 6_000_000, 64):
            fh.write(f"{i:050d} padding line\n")
    out = scan_tree(bundle)
    assert out["verdict"] == "PASS"
    assert out["scanned_files"] == 1


def test_h1_symlink_inside_tree_fails_closed(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "real.txt").write_text("harmless\n", encoding="utf-8")
    (bundle / "link.txt").symlink_to(bundle / "real.txt")
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    assert out["symlinks"] == ["link.txt"]


def test_h1_symlink_escape_fails_closed(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("nothing here\n", encoding="utf-8")
    (bundle / "escape.txt").symlink_to(outside)
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    assert out["symlinks"] == ["escape.txt"]


@pytest.mark.parametrize("enc", ["utf-16-le", "utf-16-be"])
def test_h1_utf16_secret_detected(tmp_path, enc):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "note.txt").write_bytes(f"prefix {SECRET} suffix".encode(enc))
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    assert any(f["kind"] == "anthropic_key" for f in out["findings"])


def test_h1_utf16_secret_across_chunk_boundary(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    filler = "a" * (CHUNK_SIZE // 2 - 30)  # ≈ 1 MiB once encoded as utf-16-le
    (bundle / "big.txt").write_bytes((filler + SECRET + "tail").encode("utf-16-le"))
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    assert any(f["kind"] == "anthropic_key" for f in out["findings"])


def test_h1_degraded_invariant_blocks_closure_pass(tmp_path, monkeypatch):
    checks = {uid: (title, (lambda c: ("PASS", "ok"))) for uid, (title, _fn)
              in closure_mod.U_CHECKS.items()}
    checks["U8"] = ("u8", lambda c: ("DEGRADED", "simulated partial scan"))
    monkeypatch.setattr(closure_mod, "U_CHECKS", checks)
    ctx = _ctx(tmp_path)
    outcome = closure_mod.run_global_closure(ctx)
    assert outcome.verdict == Verdict.DEGRADED  # never rounded up to PASS
    report = read_json(ctx.workspace.reports_dir / "global_closure.json")
    assert report["degraded"] == ["U8"]


# ---------------------------------------------------------------------------
# H2: U6 — full freeze manifest, workspace and active bundle
# ---------------------------------------------------------------------------

def _frozen_workspace(ctx: NodeContext) -> Workspace:
    ws = ctx.workspace
    (ws.paper_dir / "sections").mkdir(parents=True, exist_ok=True)
    (ws.paper_dir / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    (ws.paper_dir / "sections" / "results.tex").write_text("\\section{Results}\n",
                                                           encoding="utf-8")
    outcome = run_scientific_freeze(ctx)
    assert outcome.verdict == Verdict.PASS
    return ws


def _mk_pointer(ws: Workspace, bundle_name: str) -> None:
    write_json(ws.reports_dir / "current_release.json", {
        "paper_id": bundle_name, "export_status": "PASS", "bundle": f"release/{bundle_name}",
        "secret_scan": f"release/{bundle_name}/secret_scan.json",
        "secret_scan_sha256": None, "exported_at": "2026-09-22T00:00:00Z",
        "run_id": "r"})


def test_h2_unmodified_freeze_passes(tmp_path):
    ctx = _ctx(tmp_path)
    _frozen_workspace(ctx)
    state, note = closure_mod._u6(ctx)
    assert state == "PASS", note


def test_h2_main_tex_mutation_fails(tmp_path):
    ctx = _ctx(tmp_path)
    _frozen_workspace(ctx)
    main = ctx.workspace.paper_dir / "main.tex"
    main.write_text(main.read_text(encoding="utf-8") + "\\usepackage{changed}\n",
                    encoding="utf-8")
    state, note = closure_mod._u6(ctx)
    assert state == "FAIL" and "mutated" in note


def test_h2_section_mutation_fails(tmp_path):
    ctx = _ctx(tmp_path)
    _frozen_workspace(ctx)
    section = ctx.workspace.paper_dir / "sections" / "results.tex"
    section.write_text(section.read_text(encoding="utf-8") + "altered after freeze\n",
                       encoding="utf-8")
    state, note = closure_mod._u6(ctx)
    assert state == "FAIL" and "results.tex" in note


def test_h2_new_section_after_freeze_fails(tmp_path):
    ctx = _ctx(tmp_path)
    _frozen_workspace(ctx)
    (ctx.workspace.paper_dir / "sections" / "appendix.tex").write_text(
        "\\section{Appendix}\n", encoding="utf-8")
    state, note = closure_mod._u6(ctx)
    assert state == "FAIL" and "added" in note


def test_h2_deleted_frozen_file_fails(tmp_path):
    ctx = _ctx(tmp_path)
    ws = _frozen_workspace(ctx)
    victim = ws.paper_dir / "sections" / "results.tex"
    victim.rename(victim.with_name(victim.name + ".v1.bak"))  # archived, not deleted
    state, note = closure_mod._u6(ctx)
    assert state == "FAIL" and "deleted" in note


def test_h2_bundle_divergence_fails(tmp_path):
    ctx = _ctx(tmp_path)
    ws = _frozen_workspace(ctx)
    bundle_paper = ws.release_dir / "demo" / "paper"
    (bundle_paper / "sections").mkdir(parents=True)
    (bundle_paper / "main.tex").write_text(
        (ws.paper_dir / "main.tex").read_text(encoding="utf-8"), encoding="utf-8")
    (bundle_paper / "sections" / "results.tex").write_text(
        "\\section{Results}\ntampered in the bundle\n", encoding="utf-8")
    _mk_pointer(ws, "demo")
    state, note = closure_mod._u6(ctx)
    assert state == "FAIL" and "bundle" in note


def test_h2_bundle_matching_freeze_passes(tmp_path):
    ctx = _ctx(tmp_path)
    ws = _frozen_workspace(ctx)
    bundle_paper = ws.release_dir / "demo" / "paper"
    bundle_paper.mkdir(parents=True)
    for rel, digest in read_json(ws.reports_dir / "scientific_freeze.json")["files"].items():
        target = bundle_paper / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ws.paper_dir / rel).read_bytes())
    _mk_pointer(ws, "demo")
    state, note = closure_mod._u6(ctx)
    assert state == "PASS", note


# ---------------------------------------------------------------------------
# H3: U8 — bound to the active bundle via the P33 pointer
# ---------------------------------------------------------------------------

def _mk_bundle(ws: Workspace, name: str, verdict: str) -> Path:
    bundle = ws.release_dir / name
    bundle.mkdir(parents=True)
    write_json(bundle / "secret_scan.json", {
        "scanned_root": str(bundle), "scanned_files": 1, "findings": [],
        "errors": [], "symlinks": [], "encoding_fallbacks": [], "verdict": verdict})
    return bundle


def _mk_full_pointer(ws: Workspace, bundle: Path, status: str = "PASS") -> None:
    scan = bundle / "secret_scan.json"
    files = {p.relative_to(bundle).as_posix(): sha256_file(p)
             for p in sorted(bundle.rglob("*")) if p.is_file() and not p.is_symlink()}
    write_json(ws.reports_dir / "current_release.json", {
        "paper_id": bundle.name, "export_status": status,
        "bundle": f"release/{bundle.name}",
        "secret_scan": f"release/{bundle.name}/secret_scan.json",
        "secret_scan_sha256": sha256_file(scan),
        "bundle_files": files,
        "exported_at": "2026-09-22T00:00:00Z", "run_id": "r"})


def test_h3_u8_follows_pointer_not_lexicographic_order(tmp_path):
    ctx = _ctx(tmp_path)
    ws = ctx.workspace
    active = _mk_bundle(ws, "aaa_active", "PASS")
    _mk_bundle(ws, "zzz_stale.FAILED.20260101T000000Z", "FAIL")  # sorts last
    _mk_full_pointer(ws, active)
    state, note = closure_mod._u8(ctx)
    assert state == "PASS", note


def test_h3_u8_fail_of_active_bundle_fails_despite_stale_pass(tmp_path):
    ctx = _ctx(tmp_path)
    ws = ctx.workspace
    _mk_bundle(ws, "zzz_stale", "PASS")  # lexicographically last, irrelevant
    active = _mk_bundle(ws, "aaa_active", "FAIL")
    _mk_full_pointer(ws, active)
    state, _note = closure_mod._u8(ctx)
    assert state == "FAIL"


def test_h3_u8_scan_hash_tamper_fails(tmp_path):
    ctx = _ctx(tmp_path)
    ws = ctx.workspace
    active = _mk_bundle(ws, "demo", "PASS")
    _mk_full_pointer(ws, active)
    scan = active / "secret_scan.json"
    scan.write_text(scan.read_text(encoding="utf-8") + " ", encoding="utf-8")
    state, note = closure_mod._u8(ctx)
    assert state == "FAIL" and "changed since export" in note


def test_h3_u8_wrong_scanned_root_fails(tmp_path):
    ctx = _ctx(tmp_path)
    ws = ctx.workspace
    active = _mk_bundle(ws, "demo", "PASS")
    scan = active / "secret_scan.json"
    payload = read_json(scan)
    payload["scanned_root"] = str(ws.release_dir / "other")
    write_json(scan, payload)
    _mk_full_pointer(ws, active)  # hash computed over the tampered scan: binding intact
    state, note = closure_mod._u8(ctx)
    assert state == "FAIL" and "not active bundle" in note


def test_h3_u8_missing_pointer_is_not_run(tmp_path):
    ctx = _ctx(tmp_path)
    state, _note = closure_mod._u8(ctx)
    assert state == "NOT_RUN"


def test_h3_export_persists_active_bundle_pointer(tmp_path):
    ctx = _ctx(tmp_path)
    ws = ctx.workspace
    (ws.paper_dir / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    outcome = run_clean_export(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    pointer = read_json(ws.reports_dir / "current_release.json")
    assert pointer["export_status"] == "PASS"
    scan_path = ws.root / pointer["secret_scan"]
    assert scan_path.exists()
    assert sha256_file(scan_path) == pointer["secret_scan_sha256"]
    state, note = closure_mod._u8(ctx)
    assert state == "PASS", note


# ---------------------------------------------------------------------------
# H4: corrupt review artifacts never disappear silently
# ---------------------------------------------------------------------------

def test_h4_load_reviews_surfaces_invalid(tmp_path):
    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir()
    write_json(reviews_dir / "good.json",
               {"review_id": "r1", "reviewer": "x", "findings": []})
    (reviews_dir / "broken.json").write_text("{ not json", encoding="utf-8")
    (reviews_dir / "schema.json").write_text(json.dumps({"review_id": 5}),
                                             encoding="utf-8")
    reviews, invalid = load_reviews(reviews_dir)
    assert [r.review_id for r in reviews] == ["r1"]
    assert len(invalid) == 2
    assert all(i["kind"] == "REVIEW_ARTIFACT_INVALID" for i in invalid)
    assert any(p["path"].endswith("broken.json") for p in invalid)
    assert all(p["error"] for p in invalid)


def test_h4_u5_fails_on_invalid_review(tmp_path):
    ctx = _ctx(tmp_path)
    (ctx.workspace.reviews_dir / "broken.json").write_text("{ nope", encoding="utf-8")
    state, note = closure_mod._u5(ctx)
    assert state == "FAIL" and "REVIEW_ARTIFACT_INVALID" in note


def test_h4_remediation_fails_closed_on_invalid_review(tmp_path):
    ctx = _ctx(tmp_path)
    (ctx.workspace.reviews_dir / "broken.json").write_text("{ nope", encoding="utf-8")
    outcome = run_remediation(ctx)
    assert outcome.verdict == Verdict.FAIL
    assert outcome.detail["reason"] == "REVIEW_ARTIFACT_INVALID"


# ---------------------------------------------------------------------------
# P20 wiring: the section structure check actually runs inside the DAG chain
# ---------------------------------------------------------------------------

def test_p20_chain_runs_structure_check_and_fails_on_placeholders(tmp_path):
    ctx = _ctx(tmp_path, allow_writer=True)
    run_manuscript_architecture(ctx)  # scaffold still holds <<PF:...>> placeholders
    handler = build_handlers([])["P20"]
    outcome = handler(ctx, None)
    assert outcome.verdict == Verdict.FAIL
    report = read_json(ctx.workspace.reports_dir / "manuscript_structure_check.json")
    assert report["verdict"] == "FAIL"


def test_p20_chain_passes_on_clean_manuscript(tmp_path):
    ctx = _ctx(tmp_path, allow_writer=True)
    run_manuscript_architecture(ctx)
    ws = ctx.workspace
    for section in ("methods", "results", "introduction", "discussion"):
        (ws.paper_dir / "sections" / f"{section}.tex").write_text(
            f"\\section{{{section.title()}}}\n\\label{{sec:{section}}}\nclean prose\n",
            encoding="utf-8")
    outcome = build_handlers([])["P20"](ctx, None)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    report = read_json(ws.reports_dir / "manuscript_structure_check.json")
    assert report["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# Round 2: dual-review findings (Reviewer A: C1, M1–M6 / Reviewer B: F1–F9)
# ---------------------------------------------------------------------------

def test_r2_f1_mixed_ascii_then_utf16_secret_fails(tmp_path):
    # classification deception: a clean ASCII prefix must not hide a UTF-16
    # secret later in the file — regardless of where the prefix ends
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    secret16 = SECRET.encode("utf-16-le")
    (bundle / "mixed1.bin").write_bytes(b"h" * 1024 + secret16)     # probe: binary
    (bundle / "mixed2.bin").write_bytes(b"h" * 8192 + secret16)     # probe: clean text
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    hits = [f for f in out["findings"] if f["kind"] == "anthropic_key"]
    assert {f["file"] for f in hits} == {"mixed1.bin", "mixed2.bin"}


def test_r2_f2_aligned_binary_with_ascii_secret_fails(tmp_path):
    # uint32-LE-style aligned content must not be misread as UTF-16 in a way
    # that loses the raw byte view of an ASCII secret
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "array.bin").write_bytes(b"A\x00\x00\x00" * 500 + SECRET.encode())
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    assert any(f["kind"] == "anthropic_key" for f in out["findings"])


def test_r2_f3_utf16_with_trailing_surrogate_fails(tmp_path):
    # strict decoding dies on the lone surrogate; the byte-space UTF-16 views
    # (errors=replace) must still see the secret
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "note.txt").write_bytes(
        f"prefix {SECRET} suffix".encode("utf-16-le") + b"\x00\xd8")
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    assert any(f["kind"] == "anthropic_key" for f in out["findings"])


def test_r2_f4_entropy_assignment_detected_in_binary_file(tmp_path):
    # one non-UTF-8 byte must not cost the entropy layer
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "cfg.bin").write_bytes(
        b"hdr \xfc\n" + b'api_key = "k9Xf2mQ7vB4nZ8pL3cR6tY1uI5oA0sD9"' + b"\n")
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    assert any(f["kind"] == "high_entropy_assignment" for f in out["findings"])


def test_r2_f5_token_growing_across_boundary_reported_once(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    token = ("sk-ant-" + "B" * 9000).encode()  # longer than the look-back
    (bundle / "edge.txt").write_bytes(b"x" * (CHUNK_SIZE - 100) + token + b"\ntail")
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    hits = [f for f in out["findings"] if f["kind"] == "anthropic_key"]
    assert len(hits) == 1
    assert hits[0]["span"][1] - hits[0]["span"][0] == len(token)


def test_r2_f6_missing_scan_root_fails_closed(tmp_path):
    out = scan_tree(tmp_path / "does-not-exist")
    assert out["verdict"] == "FAIL"
    assert out["errors"]


def test_r2_f7_special_file_fails_closed(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    os.mkfifo(bundle / "pipe.fifo")
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    assert any("not a regular file" in e for e in out["errors"])


def test_r2_f9_allowlist_prefix_is_not_a_bypass(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "cfg.txt").write_text(
        'token = "PAPER_FACTORY_k9Xf2mQ7vB4nZ8pL3cR6tY1uI5oA0sD9"\n'
        'credential = "Zx9Qm2Wv8Bn4Kl7Ps3Rt6Yu1Io0Aq5Sd8Fg"\n', encoding="utf-8")
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    kinds = [f["kind"] for f in out["findings"]]
    assert kinds.count("high_entropy_assignment") == 2


def test_r2_c1_u6_fails_when_bundle_manuscript_missing(tmp_path):
    ctx = _ctx(tmp_path)
    ws = _frozen_workspace(ctx)
    (ws.release_dir / "demo").mkdir(parents=True)  # bundle exists, paper/ does not
    _mk_pointer(ws, "demo")
    state, note = closure_mod._u6(ctx)
    assert state == "FAIL" and "no manuscript tree" in note


def test_r2_m1_u6_bundle_addition_fails(tmp_path):
    ctx = _ctx(tmp_path)
    ws = _frozen_workspace(ctx)
    bundle_paper = ws.release_dir / "demo" / "paper"
    bundle_paper.mkdir(parents=True)
    for rel in read_json(ws.reports_dir / "scientific_freeze.json")["files"]:
        target = bundle_paper / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ws.paper_dir / rel).read_bytes())
    (bundle_paper / "sections" / "smuggled.tex").write_text("\\section{Extra}\n",
                                                            encoding="utf-8")
    _mk_pointer(ws, "demo")
    state, note = closure_mod._u6(ctx)
    assert state == "FAIL" and "outside the freeze" in note


@pytest.mark.parametrize("bad", ["", ".", "/etc", "release/../../etc"])
def test_r2_m2_u8_degenerate_or_unsafe_bundle_fails(tmp_path, bad):
    ctx = _ctx(tmp_path)
    ws = ctx.workspace
    write_json(ws.reports_dir / "current_release.json", {
        "paper_id": "x", "export_status": "PASS", "bundle": bad,
        "secret_scan": "release/x/secret_scan.json",
        "secret_scan_sha256": "0" * 64, "exported_at": "2026-09-22T00:00:00Z",
        "run_id": "r"})
    state, _note = closure_mod._u8(ctx)
    assert state == "FAIL"


def test_r2_m3_u8_missing_hash_pin_fails(tmp_path):
    ctx = _ctx(tmp_path)
    ws = ctx.workspace
    _mk_bundle(ws, "demo", "PASS")
    write_json(ws.reports_dir / "current_release.json", {
        "paper_id": "demo", "export_status": "PASS", "bundle": "release/demo",
        "secret_scan": "release/demo/secret_scan.json",
        "secret_scan_sha256": None,  # pin stripped after export
        "exported_at": "2026-09-22T00:00:00Z", "run_id": "r"})
    state, note = closure_mod._u8(ctx)
    assert state == "FAIL" and "hash pin" in note


def test_r2_m3_u8_scan_without_scanned_root_fails(tmp_path):
    ctx = _ctx(tmp_path)
    ws = ctx.workspace
    bundle = _mk_bundle(ws, "demo", "PASS")
    scan = bundle / "secret_scan.json"
    payload = read_json(scan)
    del payload["scanned_root"]
    write_json(scan, payload)
    _mk_full_pointer(ws, bundle)  # re-pins the tampered hash — binding itself intact
    state, note = closure_mod._u8(ctx)
    assert state == "FAIL" and "scanned_root" in note


def test_r2_m3_u8_missing_status_fails(tmp_path):
    ctx = _ctx(tmp_path)
    ws = ctx.workspace
    bundle = _mk_bundle(ws, "demo", "PASS")
    scan = bundle / "secret_scan.json"
    write_json(ws.reports_dir / "current_release.json", {
        "paper_id": "demo", "bundle": "release/demo",
        "secret_scan": "release/demo/secret_scan.json",
        "secret_scan_sha256": sha256_file(scan),
        "exported_at": "2026-09-22T00:00:00Z", "run_id": "r"})
    state, note = closure_mod._u8(ctx)
    assert state == "FAIL" and "status" in note


def test_r2_m4_unknown_invariant_state_blocks_closure(tmp_path, monkeypatch):
    checks = {uid: (title, (lambda c: ("PASS", "ok"))) for uid, (title, _fn)
              in closure_mod.U_CHECKS.items()}
    checks["U8"] = ("u8", lambda c: ("UNSUPPORTED_ENVIRONMENT", "no TeX here"))
    monkeypatch.setattr(closure_mod, "U_CHECKS", checks)
    ctx = _ctx(tmp_path)
    outcome = closure_mod.run_global_closure(ctx)
    assert outcome.verdict == Verdict.FAIL
    report = read_json(ctx.workspace.reports_dir / "global_closure.json")
    assert report["unknown_states"] == ["U8"]


def test_r2_m5_u6_symlink_bundle_escape_fails(tmp_path):
    ctx = _ctx(tmp_path)
    ws = _frozen_workspace(ctx)
    outside = tmp_path / "outside"
    (outside / "paper").mkdir(parents=True)
    (ws.release_dir / "evil").symlink_to(outside)  # bundle dir escapes workspace
    _mk_pointer(ws, "evil")
    state, note = closure_mod._u6(ctx)
    assert state == "FAIL" and "unsafe" in note


def test_r2_m6_review_shaped_novelty_attack_file_is_not_hidden(tmp_path):
    # a review renamed to novelty_attack.json must still load as a review;
    # the genuine P07 artifact (valid JSON, not review-shaped) is skipped;
    # a corrupt file under that name is REVIEW_ARTIFACT_INVALID
    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir()
    write_json(reviews_dir / "novelty_attack.json",
               {"review_id": "disguised", "reviewer": "sneaky",
                "findings": [{"finding_id": "f1", "reviewer": "sneaky",
                              "severity": "CRITICAL", "category": "methods",
                              "statement": "hidden"}]})
    reviews, invalid = load_reviews(reviews_dir)
    assert [r.review_id for r in reviews] == ["disguised"] and not invalid

    write_json(reviews_dir / "novelty_attack.json",
               {"attacked_at": "2026-09-22T00:00:00Z", "claims": {}, "prior_art_pool": []})
    reviews, invalid = load_reviews(reviews_dir)
    assert reviews == [] and invalid == []  # the real P07 artifact, untouched

    # valid JSON that is neither a review nor the P07 artifact shape → invalid
    write_json(reviews_dir / "novelty_attack.json", {"attack": ["query1"]})
    reviews, invalid = load_reviews(reviews_dir)
    assert reviews == [] and len(invalid) == 1

    (reviews_dir / "novelty_attack.json").write_text("{ broken", encoding="utf-8")
    reviews, invalid = load_reviews(reviews_dir)
    assert reviews == [] and len(invalid) == 1


def test_r2_symlink_added_after_freeze_fails(tmp_path):
    ctx = _ctx(tmp_path)
    ws = _frozen_workspace(ctx)
    (ws.paper_dir / "sections" / "linked.tex").symlink_to(ws.paper_dir / "main.tex")
    state, note = closure_mod._u6(ctx)
    assert state == "FAIL" and "symlink" in note


def test_r2_export_same_second_parks_without_collision(tmp_path, monkeypatch):
    monkeypatch.setattr("paper_factory.release.export.utcnow",
                        lambda: "2026-09-22T00:00:00Z")
    ctx = _ctx(tmp_path)
    ws = ctx.workspace
    (ws.paper_dir / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    for _ in range(3):
        outcome = run_clean_export(ctx)
        assert outcome.verdict == Verdict.PASS, outcome.detail
    parked = sorted(p.name for p in ws.release_dir.iterdir() if ".v" in p.name)
    assert len(parked) == 2 and len(set(parked)) == 2


# ---------------------------------------------------------------------------
# Round 3: re-review findings (Reviewer A: R2-N1..N5 / Reviewer B: N-CRITICAL-1
# = same density-gate root cause, N-MINOR-1/2)
# ---------------------------------------------------------------------------

def test_r3_utf16_short_secret_no_density_escape(tmp_path):
    # AWS keys are exactly 20 chars: 20 NULs on one parity must not fall under
    # any density gate — the UTF-16 views run unconditionally
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "data.bin").write_bytes(
        b"\x01\x02\x03" * 100 + "AKIAIOSFODNN7EXAMPLE".encode("utf-16-le"))
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    assert any(f["kind"] == "aws_key" for f in out["findings"])


def test_r3_utf16_secret_straddling_chunk_fails(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    secret = ("ghp_" + "C" * 26).encode("utf-16-le")  # 30 chars, NULs split 15/15
    (bundle / "edge.bin").write_bytes(b"q" * (CHUNK_SIZE - 15) + secret)
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    assert any(f["kind"] == "github_pat" for f in out["findings"])


def test_r3_utf32_short_secret_no_escape(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "data.bin").write_bytes(
        b"\x05" * 64 + "AKIAIOSFODNN7EXAMPLE".encode("utf-32-le"))
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    assert any(f["kind"] == "aws_key" for f in out["findings"])


def test_r3_bracketed_entropy_value_fails(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "cfg.txt").write_text('api_key = "<k9Xf2mQ7vB4nZ8pL3cR6tY1uI5oA0sD9>"\n',
                                    encoding="utf-8")
    out = scan_tree(bundle)
    assert out["verdict"] == "FAIL"
    assert any(f["kind"] == "high_entropy_assignment" for f in out["findings"])


def test_r3_n2_bundle_symlink_fails(tmp_path):
    ctx = _ctx(tmp_path)
    ws = _frozen_workspace(ctx)
    bundle_paper = ws.release_dir / "demo" / "paper"
    bundle_paper.mkdir(parents=True)
    for rel in read_json(ws.reports_dir / "scientific_freeze.json")["files"]:
        target = bundle_paper / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ws.paper_dir / rel).read_bytes())
    # a symlink inside the bundle manuscript tree is tampering (export never
    # ships symlinks)
    (bundle_paper / "sections" / "linked.tex").symlink_to("/etc/hostname")
    _mk_pointer(ws, "demo")
    state, note = closure_mod._u6(ctx)
    assert state == "FAIL" and "symlink" in note


def test_r3_n3_frozen_symlink_path_content_is_pinned(tmp_path):
    ctx = _ctx(tmp_path)
    ws = _ctx_ws_with_symlink_freeze(ctx)
    record = read_json(ws.reports_dir / "scientific_freeze.json")
    assert record["symlinks"] == {"sections/linked.tex": str(ws.paper_dir / "main.tex")}
    assert record["symlink_hashes"]["sections/linked.tex"]
    state, note = closure_mod._u6(ctx)
    assert state == "PASS", note  # untouched: name + content pins hold
    # target content changed after freeze → FAIL
    main = ws.paper_dir / "main.tex"
    main.write_text(main.read_text(encoding="utf-8") + "% mutated\n", encoding="utf-8")
    state, note = closure_mod._u6(ctx)
    assert state == "FAIL" and "mutated" in note


def test_r3_n3_bundle_copy_at_symlink_path_diverges(tmp_path):
    ctx = _ctx(tmp_path)
    ws = _ctx_ws_with_symlink_freeze(ctx)
    bundle_paper = ws.release_dir / "demo" / "paper"
    bundle_paper.mkdir(parents=True)
    for rel in read_json(ws.reports_dir / "scientific_freeze.json")["files"]:
        target = bundle_paper / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ws.paper_dir / rel).read_bytes())
    # export materializes the internal symlink as a regular copy
    (bundle_paper / "sections" / "linked.tex").write_bytes(
        (ws.paper_dir / "main.tex").read_bytes())
    _mk_pointer(ws, "demo")
    state, note = closure_mod._u6(ctx)
    assert state == "PASS", note
    # tampered copy at the frozen symlink path → FAIL via the content pin
    (bundle_paper / "sections" / "linked.tex").write_text("swapped\n", encoding="utf-8")
    state, note = closure_mod._u6(ctx)
    assert state == "FAIL" and "symlink path diverges" in note


def _ctx_ws_with_symlink_freeze(ctx: NodeContext) -> Workspace:
    ws = ctx.workspace
    (ws.paper_dir / "sections").mkdir(parents=True, exist_ok=True)
    (ws.paper_dir / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    (ws.paper_dir / "sections" / "results.tex").write_text("\\section{Results}\n",
                                                           encoding="utf-8")
    (ws.paper_dir / "sections" / "linked.tex").symlink_to(ws.paper_dir / "main.tex")
    assert run_scientific_freeze(ctx).verdict == Verdict.PASS
    return ws


def test_r3_n4_export_skips_dangling_symlink_without_crash(tmp_path):
    ctx = _ctx(tmp_path)
    ws = ctx.workspace
    (ws.paper_dir / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    (ws.paper_dir / "dangling.tex").symlink_to(ws.paper_dir / "does-not-exist.tex")
    outcome = run_clean_export(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    assert any("dangling" in s for s in outcome.detail["skipped_symlinks"])


def test_r3_n5_pointer_bundle_outside_release_fails(tmp_path):
    ctx = _ctx(tmp_path)
    ws = ctx.workspace
    scan = ws.reports_dir / "fake_scan.json"
    write_json(scan, {"scanned_root": str(ws.reports_dir), "verdict": "PASS",
                      "scanned_files": 1, "findings": [], "errors": [],
                      "symlinks": [], "encoding_fallbacks": []})
    write_json(ws.reports_dir / "current_release.json", {
        "paper_id": "x", "export_status": "PASS", "bundle": "reports",
        "secret_scan": "reports/fake_scan.json",
        "secret_scan_sha256": sha256_file(scan),
        "exported_at": "2026-09-22T00:00:00Z", "run_id": "r"})
    state, note = closure_mod._u8(ctx)
    assert state == "FAIL" and "outside release/" in note
    state6, note6 = closure_mod._u6(ctx)
    # U6 without freeze stays NOT_RUN; with freeze the bad pointer must FAIL
    assert state6 == "NOT_RUN"
    _frozen_workspace(ctx)
    state6, note6 = closure_mod._u6(ctx)
    assert state6 == "FAIL" and "outside release/" in note6


# ---------------------------------------------------------------------------
# Round 4: re-review findings (Reviewer A: R3-B1 missing symlink copy,
# R3-B2 excluded-path smuggling, R3-B3 forgeable novelty shape)
# ---------------------------------------------------------------------------

def test_r4_b1_missing_symlink_copy_fails(tmp_path):
    ctx = _ctx(tmp_path)
    ws = _ctx_ws_with_symlink_freeze(ctx)
    bundle_paper = ws.release_dir / "demo" / "paper"
    bundle_paper.mkdir(parents=True)
    # bundle carries the frozen regular files but NOT the materialized copy
    for rel in read_json(ws.reports_dir / "scientific_freeze.json")["files"]:
        target = bundle_paper / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ws.paper_dir / rel).read_bytes())
    _mk_pointer(ws, "demo")
    state, note = closure_mod._u6(ctx)
    assert state == "FAIL" and "missing materialized symlink copy" in note


def test_r4_b2_excluded_path_present_in_bundle_fails(tmp_path):
    ctx = _ctx(tmp_path)
    ws = _frozen_workspace(ctx)
    # a chat-like file is frozen in the workspace but policy-excluded from export
    chat = ws.paper_dir / "chat_log.md"
    chat.write_text("private transcript\n", encoding="utf-8")
    assert run_scientific_freeze(ctx).verdict == Verdict.PASS
    bundle_paper = ws.release_dir / "demo" / "paper"
    bundle_paper.mkdir(parents=True)
    for rel in read_json(ws.reports_dir / "scientific_freeze.json")["files"]:
        if "chat" in rel.lower():
            continue  # correctly excluded from the bundle
        target = bundle_paper / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ws.paper_dir / rel).read_bytes())
    _mk_pointer(ws, "demo")
    state, note = closure_mod._u6(ctx)
    assert state == "PASS", note  # excluded + absent is the legal combination
    # smuggled into the bundle with arbitrary content → FAIL
    (bundle_paper / "chat_log.md").write_text("PRIVATE TRANSCRIPT LEAK\n",
                                              encoding="utf-8")
    state, note = closure_mod._u6(ctx)
    assert state == "FAIL" and "policy-excluded" in note


def test_r4_b3_forged_novelty_shape_does_not_hide_broken_review(tmp_path):
    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir()
    # broken review (invalid severity enum) hiding behind the P07 shape keys
    write_json(reviews_dir / "novelty_attack.json", {
        "attacked_at": "2026-09-22T00:00:00Z", "claims": {},
        "review_id": "disguised", "reviewer": "sneaky",
        "findings": [{"finding_id": "f1", "reviewer": "sneaky",
                      "severity": "CRITICALXX", "category": "methods",
                      "statement": "hidden"}]})
    reviews, invalid = load_reviews(reviews_dir)
    assert reviews == [] and len(invalid) == 1
    assert invalid[0]["kind"] == "REVIEW_ARTIFACT_INVALID"
    # the genuine P07 artifact (shape keys, no review-ish fields) still skips
    write_json(reviews_dir / "novelty_attack.json",
               {"attacked_at": "2026-09-22T00:00:00Z", "claims": {}, "prior_art_pool": []})
    reviews, invalid = load_reviews(reviews_dir)
    assert reviews == [] and invalid == []


# ---------------------------------------------------------------------------
# Round 5: re-review findings (Reviewer A: R4-N1/N2 chat policy vs. symlink
# targets; Reviewer B: R4-MAJOR-1 full-bundle tamper evidence)
# ---------------------------------------------------------------------------

def test_r5_n2_symlink_target_chat_filtered(tmp_path):
    # a neutral symlink name must not launder chat-log content into the bundle
    ctx = _ctx(tmp_path)
    ws = ctx.workspace
    (ws.paper_dir / "handoff").mkdir(parents=True)
    (ws.paper_dir / "handoff" / "notes.md").write_text("PRIVATE TRANSCRIPT\n",
                                                       encoding="utf-8")
    (ws.paper_dir / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    (ws.paper_dir / "figure_data.tex").symlink_to(ws.paper_dir / "handoff" / "notes.md")
    assert run_scientific_freeze(ctx).verdict == Verdict.PASS
    outcome = run_clean_export(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    bundle = ws.release_dir / ws.target_root.name / "paper"
    assert not (bundle / "figure_data.tex").exists()
    assert not (bundle / "handoff" / "notes.md").exists()
    assert any("symlink target" in s for s in outcome.detail["skipped_symlinks"])
    # and the closure mirror agrees: excluded-by-target is allowed to be absent
    state, note = closure_mod._u6(ctx)
    assert state == "PASS", note


def test_r5_n1_chat_named_internal_symlink_no_false_fail(tmp_path):
    # the excluded set must cover frozen link paths too, not just file paths
    ctx = _ctx(tmp_path)
    ws = ctx.workspace
    (ws.paper_dir / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    (ws.paper_dir / "real.tex").write_text("% real\n", encoding="utf-8")
    (ws.paper_dir / "chatfig.tex").symlink_to(ws.paper_dir / "real.tex")
    assert run_scientific_freeze(ctx).verdict == Verdict.PASS
    outcome = run_clean_export(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    state, note = closure_mod._u6(ctx)
    assert state == "PASS", note


def _exported_ctx(tmp_path: Path):
    ctx = _ctx(tmp_path)
    ws = ctx.workspace
    (ws.paper_dir / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    outcome = run_clean_export(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    return ctx, ws


def test_r5_u8_full_bundle_manifest_pins_everything(tmp_path):
    ctx, ws = _exported_ctx(tmp_path)
    state, note = closure_mod._u8(ctx)
    assert state == "PASS", note
    pointer = read_json(ws.reports_dir / "current_release.json")
    bundle = ws.root / pointer["bundle"]

    # (a) unpinned addition at the bundle root
    (bundle / "stolen_keys.txt").write_text("harmless\n", encoding="utf-8")
    state, note = closure_mod._u8(ctx)
    assert state == "FAIL" and "unpinned" in note
    (bundle / "stolen_keys.txt").rename(bundle / "stolen_keys.txt.v1.bak")
    # the renamed-away file is itself unpinned → still FAIL (nothing hides)
    state, note = closure_mod._u8(ctx)
    assert state == "FAIL"

    # (b) fresh bundle; mutate a pinned manifest at the root
    ctx2, ws2 = _exported_ctx(tmp_path / "second")
    pointer2 = read_json(ws2.reports_dir / "current_release.json")
    bundle2 = ws2.root / pointer2["bundle"]
    am = bundle2 / "artifact_manifest.json"
    am.write_text(am.read_text(encoding="utf-8") + " ", encoding="utf-8")
    state, note = closure_mod._u8(ctx2)
    assert state == "FAIL" and "mutated" in note

    # (c) fresh bundle; symlink planted at the root
    ctx3, ws3 = _exported_ctx(tmp_path / "third")
    pointer3 = read_json(ws3.reports_dir / "current_release.json")
    bundle3 = ws3.root / pointer3["bundle"]
    (bundle3 / "evil.txt").symlink_to("/etc/hostname")
    state, note = closure_mod._u8(ctx3)
    assert state == "FAIL" and "symlink" in note


def test_r5_u8_build_outputs_must_be_pinned(tmp_path):
    ctx, ws = _exported_ctx(tmp_path)
    pointer_path = ws.reports_dir / "current_release.json"
    pointer = read_json(pointer_path)
    bundle = ws.root / pointer["bundle"]
    build = bundle / "build"
    build.mkdir()
    (build / "main.pdf").write_bytes(b"%PDF-1.4 fake\n")
    # unpinned build artifact → FAIL
    state, note = closure_mod._u8(ctx)
    assert state == "FAIL" and "unpinned" in note
    # pinned (as P34 does after a rebuild) → PASS
    files = pointer.setdefault("bundle_files", {})
    files["build/main.pdf"] = sha256_file(build / "main.pdf")
    write_json(pointer_path, pointer)
    state, note = closure_mod._u8(ctx)
    assert state == "PASS", note
    # mutated pinned build artifact → FAIL
    (build / "main.pdf").write_bytes(b"%PDF-1.4 tampered\n")
    state, note = closure_mod._u8(ctx)
    assert state == "FAIL" and "mutated" in note
