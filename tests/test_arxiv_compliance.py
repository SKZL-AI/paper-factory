"""arXiv compliance gate (P32 extension) — adversarial tests.

Every check must fail closed: no disclosure file, no valid schema, no
rendered section in the manuscript → FAIL. The gate never invents a
declaration on the author's behalf.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from paper_factory.venue import arxiv_policy as ax


def _paper(tmp_path: Path, main_tex: str, extra: dict[str, str] | None = None) -> Path:
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text(main_tex, encoding="utf-8")
    for name, content in (extra or {}).items():
        (paper / name).write_text(content, encoding="utf-8")
    return paper


def _cfgdir(tmp_path: Path, disc: dict | None) -> Path:
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    if disc is not None:
        (cfg / "ai_disclosure.yaml").write_text(yaml.safe_dump({"disclosure": disc}))
    return cfg


VALID_DISC = {
    "schema_version": "1.0",
    "ai_use": {
        "used": True,
        "tools": [{"name": "Claude", "developer": "Anthropic", "version": "4.5"}],
        "tasks": [{"stage": "writing", "task": "language_polishing"}],
        "human_oversight": {"reviewed": True},
    },
    "responsibility": {"ai_not_author": True},
}

EN_BODY = ("The results show that the method is effective and that the "
           "analysis is consistent with the data. " * 30)

MAIN_WITH_DISCLOSURE = (
    "\\documentclass{article}\n\\author{Furkan S}\n\\begin{document}\n"
    + EN_BODY + "\n"
    + ax.render_disclosure(VALID_DISC)
    + "\\end{document}\n")


# ---------------------------------------------------------------- disclosure

def test_missing_disclosure_file_fails(tmp_path):
    paper = _paper(tmp_path, MAIN_WITH_DISCLOSURE)
    out = ax.check_ai_disclosure(paper, _cfgdir(tmp_path, None))
    assert out["pass"] is False
    assert "never invents" in out["reason"]


def test_valid_disclosure_and_rendered_section_passes(tmp_path):
    paper = _paper(tmp_path, MAIN_WITH_DISCLOSURE)
    out = ax.check_ai_disclosure(paper, _cfgdir(tmp_path, VALID_DISC))
    assert out["pass"] is True, out


def test_disclosure_declared_but_section_missing_fails(tmp_path):
    paper = _paper(tmp_path, "\\documentclass{article}\n\\begin{document}\n"
                             + EN_BODY + "\\end{document}\n")
    out = ax.check_ai_disclosure(paper, _cfgdir(tmp_path, VALID_DISC))
    assert out["pass"] is False
    assert "expected_text" in out  # the operator gets the exact text to insert


def test_unreviewed_ai_content_fails(tmp_path):
    disc = yaml.safe_load(yaml.safe_dump(VALID_DISC))
    disc["ai_use"]["human_oversight"]["reviewed"] = False
    paper = _paper(tmp_path, MAIN_WITH_DISCLOSURE)
    out = ax.check_ai_disclosure(paper, _cfgdir(tmp_path, disc))
    assert out["pass"] is False
    assert any("reviewed" in v for v in out["violations"])


def test_ai_not_author_must_be_true(tmp_path):
    disc = yaml.safe_load(yaml.safe_dump(VALID_DISC))
    disc["responsibility"]["ai_not_author"] = False
    problems = ax.validate_disclosure(disc)
    assert any("ai_not_author" in p for p in problems)


def test_tool_without_version_flagged(tmp_path):
    disc = yaml.safe_load(yaml.safe_dump(VALID_DISC))
    del disc["ai_use"]["tools"][0]["version"]
    problems = ax.validate_disclosure(disc)
    assert any("version" in p for p in problems)


def test_unknown_gaidet_stage_flagged(tmp_path):
    disc = yaml.safe_load(yaml.safe_dump(VALID_DISC))
    disc["ai_use"]["tasks"][0]["stage"] = "magic"
    problems = ax.validate_disclosure(disc)
    assert any("GAIDeT" in p for p in problems)


def test_used_true_without_tools_fails(tmp_path):
    disc = yaml.safe_load(yaml.safe_dump(VALID_DISC))
    disc["ai_use"]["tools"] = []
    problems = ax.validate_disclosure(disc)
    assert any("no tools declared" in p for p in problems)


def test_negative_declaration_renders_and_passes(tmp_path):
    disc = {"ai_use": {"used": False}, "responsibility": {"ai_not_author": True}}
    paper = _paper(tmp_path, "\\documentclass{article}\n\\begin{document}\n"
                             + EN_BODY + ax.render_disclosure(disc)
                             + "\\end{document}\n")
    out = ax.check_ai_disclosure(paper, _cfgdir(tmp_path, disc))
    assert out["pass"] is True, out
    assert "not employed any generative AI" in ax.render_disclosure(disc)


def test_declared_tool_must_be_named_in_manuscript(tmp_path):
    disc = yaml.safe_load(yaml.safe_dump(VALID_DISC))
    disc["ai_use"]["tools"].append({"name": "Gemini", "developer": "Google",
                                    "version": "3"})
    paper = _paper(tmp_path, MAIN_WITH_DISCLOSURE)  # mentions Claude, not Gemini
    out = ax.check_ai_disclosure(paper, _cfgdir(tmp_path, disc))
    assert out["pass"] is False
    assert out["unnamed"] == ["Gemini"]


def test_malformed_disclosure_yaml_fails(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "ai_disclosure.yaml").write_text("just: noise\n")
    paper = _paper(tmp_path, MAIN_WITH_DISCLOSURE)
    out = ax.check_ai_disclosure(paper, cfg)
    assert out["pass"] is False


# ---------------------------------------------------------------- authorship

def test_llm_as_author_fails(tmp_path):
    paper = _paper(tmp_path, "\\documentclass{article}\n"
                             "\\author{Furkan S \\and ChatGPT}\n"
                             "\\begin{document}x\\end{document}\n")
    out = ax.check_no_ai_authorship(paper)
    assert out["pass"] is False
    assert any("ChatGPT" in o for o in out["offenders"])


def test_human_authors_pass(tmp_path):
    paper = _paper(tmp_path, "\\author{Furkan S, Jane Doe}\n")
    assert ax.check_no_ai_authorship(paper)["pass"] is True


# ---------------------------------------------------------------- meta comments

def test_chatbot_meta_comment_fails(tmp_path):
    paper = _paper(tmp_path, "Some text. As an AI language model, I note that...")
    out = ax.check_no_meta_comments(paper)
    assert out["pass"] is False


def test_latex_comment_is_not_leakage(tmp_path):
    paper = _paper(tmp_path, "Real sentence here.\n% as an AI language model (draft note)\n")
    out = ax.check_no_meta_comments(paper)
    assert out["pass"] is True, out


def test_placeholder_pattern_fails(tmp_path):
    paper = _paper(tmp_path, "As shown in Table [insert table], ...")
    assert ax.check_no_meta_comments(paper)["pass"] is False


# ---------------------------------------------------------------- language

def test_english_passes(tmp_path):
    paper = _paper(tmp_path, EN_BODY)
    out = ax.check_english(paper)
    assert out["pass"] is True, out


def test_german_fails(tmp_path):
    german = ("Die Ergebnisse zeigen, dass die Methode wirksam ist und dass "
              "eine Analyse mit den Daten übereinstimmt. " * 30)
    paper = _paper(tmp_path, german)
    assert ax.check_english(paper)["pass"] is False


# ---------------------------------------------------------------- license

def _cfg(**paper_kw):
    return SimpleNamespace(paper=SimpleNamespace(**paper_kw))


def test_license_missing_fails():
    out = ax.check_license(_cfg())
    assert out["pass"] is False
    assert "irrevocable" in out["reason"]


def test_non_arxiv_license_fails():
    assert ax.check_license(_cfg(license="MIT"))["pass"] is False


def test_arxiv_license_passes():
    assert ax.check_license(_cfg(license="cc-by-4.0"))["pass"]


def test_license_natural_spellings_pass():
    """A-M1: users write 'CC BY 4.0', not the normalized slug."""
    for spelling in ("CC BY 4.0", "CC BY-SA 4.0", "CC BY-NC-ND 4.0",
                     "CC0", "CC0 1.0", "arXiv perpetual non-exclusive license 1.0"):
        out = ax.check_license(_cfg(license=spelling))
        assert out["pass"] is True, spelling


# ---------------------------------------------------------------- files/figures

def test_filename_charset_violation_fails(tmp_path):
    paper = _paper(tmp_path, EN_BODY, {"fig ä.png": "x"})
    out = ax.check_filenames_and_figures(paper)
    assert out["pass"] is False
    assert out["bad_filenames"]


def test_external_figure_url_fails(tmp_path):
    paper = _paper(tmp_path, EN_BODY + "\n\\includegraphics{https://x.test/f.png}\n")
    out = ax.check_filenames_and_figures(paper)
    assert out["pass"] is False
    assert out["external_figures"]


def test_clean_layout_passes(tmp_path):
    paper = _paper(tmp_path, EN_BODY + "\n\\includegraphics{fig1.pdf}\n",
                   {"fig1.pdf": "x"})
    assert ax.check_filenames_and_figures(paper)["pass"] is True


# ---------------------------------------------------------------- self-overlap

def test_duplicate_paragraph_fails(tmp_path):
    para = ("This is a substantial paragraph with more than twenty five words "
            "that the drafting model repeated verbatim in two sections of the "
            "manuscript under review today for testing purposes indeed.")
    paper = _paper(tmp_path, para + "\n\n" + "Different text here.\n\n" + para)
    out = ax.check_self_overlap(paper)
    assert out["pass"] is False
    assert out["reason"] == "duplicate paragraph"


def test_distinct_paragraphs_pass(tmp_path):
    paper = _paper(tmp_path, EN_BODY + "\n\nA second paragraph that shares no "
                                       "verbatim text with the first one at all.")
    assert ax.check_self_overlap(paper)["pass"] is True


# ---------------------------------------------------------------- position rule

def test_position_paper_cs_without_journal_ref_fails():
    out = ax.check_position_paper_rule(_cfg(type="position", category="cs.AI"))
    assert out["pass"] is False
    assert "journal reference" in out["reason"]


def test_position_paper_cs_with_journal_ref_passes():
    assert ax.check_position_paper_rule(
        _cfg(type="position", category="cs.AI", journal_ref="doi:10.1/x"))["pass"]


def test_research_paper_unaffected():
    assert ax.check_position_paper_rule(_cfg(type="research", category="cs.AI"))["pass"]


# ---------------------------------------------------------------- preflight

def test_preflight_is_advisory_and_current():
    out = ax.submission_preflight(_cfg())
    assert "never automatic" in out["note"]
    assert out["rate_limits"]["new_per_calendar_month"] == 2
    assert out["rate_limits"]["since"] == "2026-10-01"


# ---------------------------------------------------------------- P32 integration

def test_p32_arxiv_runs_all_policy_checks(tmp_path):
    """Venue 'arxiv' must add the policy checks on top of the base rules."""
    from paper_factory.core.config import (MarkingRegistry, PaperFactoryConfig,
                                           ProviderPolicyConfig, ProvidersConfig)
    from paper_factory.dag.executor import NodeContext
    from paper_factory.state.store import Workspace
    from paper_factory.venue.compliance import run_venue_compliance

    ws = Workspace(tmp_path)
    paper = ws.paper_dir
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "main.tex").write_text(MAIN_WITH_DISCLOSURE)
    (paper / "references.bib").write_text("@misc{x, title={x}}\n")
    cfg_dir = _cfgdir(tmp_path, VALID_DISC)
    ctx = NodeContext(workspace=ws, run_id="t-arxiv",
                      config=PaperFactoryConfig(), providers=ProvidersConfig(),
                      policy=ProviderPolicyConfig(), marking=MarkingRegistry(),
                      offline=True, target_venue="arxiv", config_dir=cfg_dir)
    outcome = run_venue_compliance(ctx)
    import json
    report = json.loads((ws.reports_dir / "venue_compliance.json").read_text())
    for check in ax.ARXIV_CHECKS:
        assert check in report["checks"], f"missing check {check}"
    # policy gates themselves green; compile outcome depends on the machine
    assert report["checks"]["ai_disclosure"]["pass"] is True
    assert report["checks"]["no_ai_authorship"]["pass"] is True
    # license is not set in the default config → honest FAIL of that check
    assert report["checks"]["license_declared"]["pass"] is False
    assert outcome.verdict.value in ("FAIL", "DEGRADED", "PASS")
    assert (ws.reports_dir / "arxiv_submission_preflight.json").exists()


def test_p32_preprint_venue_unaffected(tmp_path):
    """The preprint venue must not grow arXiv checks (no regression)."""
    from paper_factory.venue.compliance import VENUE_RULES
    assert "ai_disclosure" not in VENUE_RULES["preprint"]
    for check in ax.ARXIV_CHECKS:
        assert check in VENUE_RULES["arxiv"]


# ----------------------------------------------------- reviewer fix-round 2

def test_malformed_yaml_syntax_fails_cleanly(tmp_path):
    """B-MAJOR-1: YAML syntax errors are FAILs, never crashes."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "ai_disclosure.yaml").write_text("disclosure:\n  ai_use: [unclosed\n")
    paper = _paper(tmp_path, MAIN_WITH_DISCLOSURE)
    out = ax.check_ai_disclosure(paper, cfg)
    assert out["pass"] is False
    assert "invalid YAML" in out["reason"]


def test_type_wrong_disclosure_items_are_violations_not_crashes(tmp_path):
    cfg = _cfgdir(tmp_path, {"ai_use": {"used": True, "tools": ["Claude"],
                                        "human_oversight": "yes"},
                             "responsibility": {"ai_not_author": True}})
    paper = _paper(tmp_path, MAIN_WITH_DISCLOSURE)
    out = ax.check_ai_disclosure(paper, cfg)
    assert out["pass"] is False
    assert any("mapping" in v for v in out["violations"])


def test_tasks_required_when_used(tmp_path):
    disc = yaml.safe_load(yaml.safe_dump(VALID_DISC))
    del disc["ai_use"]["tasks"]
    problems = ax.validate_disclosure(disc)
    assert any("tasks" in p for p in problems)


def test_author_nested_braces_still_scanned(tmp_path):
    """B-MAJOR-2: affiliation/font commands must not hide an AI co-author."""
    paper = _paper(tmp_path, "\\author{Jane {\\small Doe} \\and ChatGPT}\n")
    out = ax.check_no_ai_authorship(paper)
    assert out["pass"] is False
    assert any("ChatGPT" in o for o in out["offenders"])


def test_author_tool_name_separator_insensitive(tmp_path):
    paper = _paper(tmp_path, "\\author{GPT 4}\n")
    assert ax.check_no_ai_authorship(paper)["pass"] is False


def test_author_macro_indirection_warns_not_silent(tmp_path):
    paper = _paper(tmp_path, "\\author{\\ourauthors}\n")
    out = ax.check_no_ai_authorship(paper)
    assert out["pass"] is True
    assert out["warnings"]  # reported for manual confirmation


def test_meta_comment_across_linebreak_fails(tmp_path):
    paper = _paper(tmp_path, "Some text. As an AI\nlanguage model, I note that...")
    assert ax.check_no_meta_comments(paper)["pass"] is False


def test_escaped_percent_does_not_truncate_scan(tmp_path):
    paper = _paper(tmp_path, "The rate is 50\\% as an AI language model notes.")
    assert ax.check_no_meta_comments(paper)["pass"] is False


def test_latex_comment_still_not_leakage(tmp_path):
    paper = _paper(tmp_path, "Real text here.\n% as an AI language model\n")
    assert ax.check_no_meta_comments(paper)["pass"] is True


def test_unrelated_declaration_heading_does_not_count(tmp_path):
    """A-m3: 'Declaration of AI Ethics' is not a GenAI-use disclosure."""
    paper = _paper(tmp_path, "\\documentclass{article}\n\\begin{document}\n" + EN_BODY
                             + "\\section*{Declaration of AI Ethics}\nWe care.\n"
                             + "\\end{document}\n")
    out = ax.check_ai_disclosure(paper, _cfgdir(tmp_path, VALID_DISC))
    assert out["pass"] is False


def test_english_input_based_manuscript(tmp_path):
    """A-M2: \\input-structured manuscripts aggregate all tex files."""
    paper = _paper(tmp_path, "\\documentclass{article}\n\\begin{document}\n"
                             "\\input{sections/body}\n\\end{document}\n")
    sec = paper / "sections"
    sec.mkdir()
    (sec / "body.tex").write_text(EN_BODY)
    assert ax.check_english(paper)["pass"] is True


def test_english_generated_macros_excluded(tmp_path):
    """A-M2b: PF-generated metric-binding macros (csname slugs) are not prose
    and must not drag the stopword ratio under the threshold."""
    paper = _paper(tmp_path, "\\documentclass{article}\n\\begin{document}\n"
                             "\\input{sections/body}\n\\end{document}\n")
    sec = paper / "sections"
    sec.mkdir()
    (sec / "body.tex").write_text(EN_BODY)
    gen = paper / "generated"
    gen.mkdir()
    (gen / "numbers.tex").write_text(
        "% generated by paper-factory statistics — do not hand-edit\n"
        + "\\expandafter\\def\\csname pf@evidencegkmetricone\\endcsname{42}\n" * 300)
    assert ax.check_english(paper)["pass"] is True


def test_commented_out_author_not_flagged(tmp_path):
    """A-m8: comments are stripped before the authorship scan."""
    paper = _paper(tmp_path, "\\author{Jane Doe}\n% \\author{ChatGPT}\n")
    out = ax.check_no_ai_authorship(paper)
    assert out["pass"] is True, out


def test_unbalanced_author_warns(tmp_path):
    """A-m9/B-MINOR-a: unbalanced \\author{ is reported, not silently dropped."""
    paper = _paper(tmp_path, "\\author{Jane Doe\nSome text without closing brace\n")
    out = ax.check_no_ai_authorship(paper)
    assert out["pass"] is True
    assert any("unbalanced" in w for w in out["warnings"])


def test_unsigned_generated_prose_counts_as_prose(tmp_path):
    """Hardening (reviewer A): only PF-signed generated files are excluded —
    moving prose into generated/ does not evade the language check."""
    paper = _paper(tmp_path, EN_BODY)
    gen = paper / "generated"
    gen.mkdir()
    (gen / "sneaky.tex").write_text(
        "Die Ergebnisse zeigen, dass die Methode wirksam ist. " * 500)
    out = ax.check_english(paper)
    assert out["pass"] is False, out  # dominant unsigned German prose → FAIL
