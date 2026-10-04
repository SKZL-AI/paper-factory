"""arXiv policy checks — the P32 extension for venue "arxiv".

Every rule here is verified against a primary source (status 2026-10-04);
the mapping rule → policy text → URL lives in docs/ARXIV_COMPLIANCE.md.

Design: fail-closed. Anything that requires an author decision (AI-use
disclosure, license choice) FAILs when the declaration is absent — Paper
Factory never invents a declaration on the author's behalf.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

# arXiv license options (help/license) — the choice is irrevocable.
ARXIV_LICENSES = {
    "cc-by-4.0", "cc-by-sa-4.0", "cc-by-nc-sa-4.0", "cc-by-nc-nd-4.0",
    "cc-zero-1.0", "arxiv-perpetual-1.0",
}

# Known generative-AI tool names that must never appear as an author
# (help/moderation: "generative AI language tools should not be listed as an
# author").
AI_TOOL_NAMES = {
    "chatgpt", "gpt-4", "gpt-5", "openai", "claude", "anthropic", "gemini",
    "copilot", "deepseek", "kimi", "moonshot", "llama", "mistral", "grok",
    "perplexity", "qwen", "glm",
}

# Chatbot meta-comment leakage ("one-strike" enforcement practice targets
# unchecked AI output; forgotten meta comments are the canonical tell).
META_COMMENT_PATTERNS = [
    r"\bas an ai language model\b",
    r"\bhere is (?:a|the|your) (?:revised|rewritten|summary|draft)\b",
    r"\bi (?:cannot|can't) (?:browse|access)\b",
    r"\bfill in the (?:real|actual)\b",
    r"\[(?:insert|todo|placeholder)[^\]]*\]",
    r"\bwould you like me to\b",
    r"\blet me know if you\b",
]

# arXiv filename charset (help/submit).
FILENAME_RE = re.compile(r"^[a-zA-Z0-9_+\-.,=]+$")

ENGLISH_STOPWORDS = {
    "the", "of", "and", "in", "to", "is", "are", "was", "for", "with",
    "that", "this", "on", "by", "an", "be", "as", "at", "from", "or",
}

DISCLOSURE_HEADING_RE = re.compile(
    r"declaration of generative ai"
    r"|generative ai (?:and ai-assisted technologies )?in the writing"
    r"|generative ai use|use of generative ai|ai-generated content acknowledgement",
    re.IGNORECASE,
)

GAIDET_STAGES = {
    "ideation", "literature", "data_collection", "analysis", "code",
    "writing", "translation", "figures", "review",
}


class DisclosureError(ValueError):
    """The ai_disclosure.yaml exists but violates the schema/semantics."""


def load_disclosure(config_dir: Path | None) -> dict | None:
    """Load ai_disclosure.yaml from the config dir. None when absent —
    absence is a FAIL for venue arXiv, handled by the caller. A malformed
    file is a DisclosureError, never a crash."""
    if config_dir is None:
        return None
    path = Path(config_dir) / "ai_disclosure.yaml"
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DisclosureError(f"ai_disclosure.yaml: invalid YAML: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("disclosure"), dict):
        raise DisclosureError("ai_disclosure.yaml: top-level 'disclosure' mapping missing")
    return data["disclosure"]


def validate_disclosure(disc: dict) -> list[str]:
    """Schema + semantic validation. Returns a list of violations (empty = ok).
    Type-wrong values are violations, never exceptions."""
    problems: list[str] = []
    ai_use = disc.get("ai_use")
    if not isinstance(ai_use, dict) or "used" not in ai_use:
        return ["ai_use.used missing"]
    if not ai_use["used"]:
        return problems  # negative declaration: nothing more required
    tools = ai_use.get("tools") or []
    if not isinstance(tools, list) or not tools:
        problems.append("ai_use.used is true but no tools declared")
        tools = []
    for i, tool in enumerate(tools):
        if not isinstance(tool, dict):
            problems.append(f"tools[{i}]: must be a mapping (name/developer/version)")
            continue
        if not tool.get("name"):
            problems.append(f"tools[{i}]: name missing")
        if not (tool.get("version") or tool.get("model_id")):
            problems.append(f"tools[{i}] ({tool.get('name', '?')}): version or model_id missing")
    tasks = ai_use.get("tasks") or []
    if not isinstance(tasks, list) or not tasks:
        problems.append("ai_use.tasks missing — declare what was delegated (GAIDeT stages)")
        tasks = []
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            problems.append(f"tasks[{i}]: must be a mapping (stage/task)")
            continue
        stage = task.get("stage")
        if stage not in GAIDET_STAGES:
            problems.append(f"tasks[{i}]: stage '{stage}' not in GAIDeT vocabulary")
    oversight = ai_use.get("human_oversight")
    if not isinstance(oversight, dict) or oversight.get("reviewed") is not True:
        problems.append("human_oversight.reviewed must be true — AI content unreviewed")
    resp = disc.get("responsibility")
    if not isinstance(resp, dict) or resp.get("ai_not_author") is not True:
        problems.append("responsibility.ai_not_author must be true")
    return problems


def render_disclosure(disc: dict) -> str:
    """Render the LaTeX declaration section from the structured disclosure.

    Cached render_text in the YAML is advisory; the canonical text is always
    rendered from the structured fields so the paper can never drift from the
    declaration."""
    ai_use = disc["ai_use"]
    if not ai_use["used"]:
        return ("\\section*{Declaration of Generative AI Use}\n"
                "The authors have not employed any generative AI tools in the "
                "preparation of this work.\n")
    tools = ", ".join(
        f"{t['name']} ({t.get('developer', 'unknown developer')}"
        f"{', ' + str(t.get('version') or t.get('model_id')) if (t.get('version') or t.get('model_id')) else ''})"
        for t in ai_use["tools"])
    tasks = "; ".join(
        f"{t.get('task', 'unspecified')} ({t['stage']}"
        f"{', scope: ' + t['scope'] if t.get('scope') else ''})"
        for t in ai_use.get("tasks") or []) or "not specified"
    return (
        "\\section*{Declaration of Generative AI Use}\n"
        f"During the preparation of this work, the authors used {tools} "
        f"for the following tasks (GAIDeT taxonomy): {tasks}. "
        "All AI-assisted content was reviewed, verified, and edited by the "
        "authors, who take full responsibility for the accuracy, originality, "
        "and integrity of this publication. AI tools are not listed as authors "
        "and bear no responsibility for the content.\n")


def _manuscript_texts(paper_dir: Path) -> dict[str, str]:
    return {str(p.relative_to(paper_dir)): p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(paper_dir.rglob("*.tex")) if p.is_file()}


def check_ai_disclosure(paper_dir: Path, config_dir: Path | None) -> dict:
    """arXiv requires significant GenAI use to be reported in the work
    (help/moderation). The structured declaration must exist, validate, and
    its rendered section must be present in the manuscript."""
    try:
        disc = load_disclosure(config_dir)
    except DisclosureError as exc:
        return {"pass": False, "reason": str(exc)}
    if disc is None:
        return {"pass": False,
                "reason": "ai_disclosure.yaml missing — the author must declare AI use "
                          "(or explicitly declare none); Paper Factory never invents it"}
    problems = validate_disclosure(disc)
    if problems:
        return {"pass": False, "reason": "invalid disclosure", "violations": problems}
    texts = _manuscript_texts(paper_dir)
    if not texts:
        return {"pass": False, "reason": "no manuscript sources found"}
    has_heading = any(DISCLOSURE_HEADING_RE.search(t) for t in texts.values())
    if not has_heading:
        return {"pass": False,
                "reason": "no 'Declaration of Generative AI Use' section in the manuscript",
                "expected_text": render_disclosure(disc)}
    # a disclosure claiming AI use must name its tools in the manuscript
    if disc["ai_use"]["used"]:
        body = "\n".join(texts.values()).lower()
        unnamed = [t["name"] for t in disc["ai_use"]["tools"]
                   if t["name"].lower() not in body]
        if unnamed:
            return {"pass": False, "reason": "declared tools not named in the manuscript",
                    "unnamed": unnamed}
    return {"pass": True, "ai_used": bool(disc["ai_use"]["used"])}


def _author_blocks(text: str) -> list[str]:
    """Extract \\author{...} contents with balanced-brace matching (nested
    affiliation/font commands are real-world practice; a [^}]* regex would
    terminate early and skip the rest of the author list)."""
    blocks: list[str] = []
    for m in re.finditer(r"\\author(?:\[[^\]]*\])?\{", text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        if depth == 0:
            blocks.append(text[m.end():i - 1])
    return blocks


def _norm_name(name: str) -> str:
    """Separator/case-insensitive: 'GPT 4' == 'gpt-4' == 'GPT-4'."""
    return re.sub(r"[\s\-_]+", "", name.lower())


def check_no_ai_authorship(paper_dir: Path) -> dict:
    """LLMs must not be listed as authors (help/moderation). Macro-indirected
    author fields (\\author{\\mymacro}) cannot be expanded statically — they
    are reported for manual confirmation instead of passing silently."""
    offenders: list[str] = []
    warnings: list[str] = []
    norm_tools = {_norm_name(t) for t in AI_TOOL_NAMES}
    for rel, text in _manuscript_texts(paper_dir).items():
        text = _strip_latex_comments(text)
        for block in _author_blocks(text):
            if re.search(r"\\[a-zA-Z]+", re.sub(r"\\and\b|\\thanks", "", block)):
                warnings.append(f"{rel}: author field contains macros — verify manually")
            names = re.split(r",|\\and", block)
            for name in names:
                norm = _norm_name(re.sub(r"\\[a-zA-Z]+|\{|\}", "", name))
                if norm and any(tool in norm for tool in norm_tools):
                    offenders.append(f"{rel}: {name.strip()}")
        if re.search(r"\\author(?:\[[^\]]*\])?\{", text) and not _author_blocks(text):
            warnings.append(f"{rel}: unbalanced \\author{{...}} — verify manually")
    return {"pass": not offenders, "offenders": offenders, "warnings": warnings}


def _strip_latex_comments(text: str) -> str:
    """Remove LaTeX comments; an escaped \\% does NOT start a comment."""
    out_lines = []
    for ln in text.splitlines():
        cut = len(ln)
        for m in re.finditer(r"%", ln):
            # count preceding backslashes: odd → escaped
            bs = 0
            j = m.start() - 1
            while j >= 0 and ln[j] == "\\":
                bs += 1
                j -= 1
            if bs % 2 == 0:
                cut = m.start()
                break
        out_lines.append(ln[:cut])
    return "\n".join(out_lines)


def check_no_meta_comments(paper_dir: Path) -> dict:
    """No chatbot meta-comments / placeholders in the manuscript (enforcement
    practice 2026: unchecked AI output leads to bans). Whitespace-normalized
    scan — a line break inside the pattern is not an escape hatch."""
    hits: list[str] = []
    for rel, text in _manuscript_texts(paper_dir).items():
        body = _strip_latex_comments(text)
        body = re.sub(r"\s+", " ", body)
        for pat in META_COMMENT_PATTERNS:
            for m in re.finditer(pat, body, re.IGNORECASE):
                hits.append(f"{rel}: '{m.group(0)}'")
    return {"pass": not hits, "hits": hits[:20]}


def check_english(paper_dir: Path) -> dict:
    """arXiv requires a full English-language version (policy 2026-02-11).
    Heuristic: stopword ratio over the aggregated manuscript prose
    (\\input-based manuscripts keep content in sections/). Machine-generated
    macro files (paper/generated/ — metric bindings, never prose) are excluded
    from the language pool: checking the language of \\csname slugs is
    meaningless and would false-fail every PF-produced paper."""
    texts = {}
    for rel, t in _manuscript_texts(paper_dir).items():
        # machine-generated files are excluded only when they carry the PF
        # signature — an author cannot evade the language check by moving
        # prose into generated/ (an unmarked file there counts as prose)
        if "generated" in Path(rel).parts and t.lstrip().startswith("% generated by paper-factory"):
            continue
        texts[rel] = t
    if not texts:
        return {"pass": False, "reason": "no manuscript prose sources found"}
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", " ",
                  "\n".join(texts.values()))
    words = [w.lower() for w in re.findall(r"[A-Za-z]{2,}", text)]
    if len(words) < 100:
        return {"pass": False, "reason": "too little text to determine language"}
    ratio = sum(1 for w in words if w in ENGLISH_STOPWORDS) / len(words)
    return {"pass": ratio > 0.10, "english_stopword_ratio": round(ratio, 3)}


def check_license(config) -> dict:
    """License choice is mandatory and irrevocable (help/license). Accepts the
    natural spellings ("CC BY 4.0", "CC0", "arXiv perpetual …") and normalizes
    them onto the six arXiv options."""
    lic = getattr(getattr(config, "paper", None), "license", None)
    if not lic:
        return {"pass": False,
                "reason": "no paper.license in config — choose one of "
                          + ", ".join(sorted(ARXIV_LICENSES)) + " (irrevocable)"}
    norm = _normalize_license(str(lic))
    ok = norm in ARXIV_LICENSES
    return {"pass": ok, "license": lic, "normalized": norm,
            "reason": None if ok else f"'{lic}' is not an arXiv license option"}


_LICENSE_ALIASES = {
    "cc0": "cc-zero-1.0",
    "cc0-1.0": "cc-zero-1.0",
    "cc-zero": "cc-zero-1.0",
    "arxiv": "arxiv-perpetual-1.0",
    "arxiv-1.0": "arxiv-perpetual-1.0",
    "arxiv-license-1.0": "arxiv-perpetual-1.0",
    "arxiv-perpetual-non-exclusive-license-1.0": "arxiv-perpetual-1.0",
}


def _normalize_license(lic: str) -> str:
    norm = re.sub(r"[\s_]+", "-", lic.strip().lower())
    return _LICENSE_ALIASES.get(norm, norm)


def check_filenames_and_figures(paper_dir: Path) -> dict:
    """arXiv filename charset + no externally linked figures (help/submit)."""
    bad_names, ext_figs = [], []
    for p in sorted(paper_dir.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(paper_dir).parts
        if "build" in rel_parts:
            continue
        if not all(FILENAME_RE.match(part) for part in rel_parts):
            bad_names.append(str(p.relative_to(paper_dir)))
    for rel, text in _manuscript_texts(paper_dir).items():
        for m in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}", text):
            if re.match(r"https?://", m.group(1)):
                ext_figs.append(f"{rel}: {m.group(1)}")
    ok = not bad_names and not ext_figs
    return {"pass": ok, "bad_filenames": bad_names, "external_figures": ext_figs}


def check_self_overlap(paper_dir: Path) -> dict:
    """Internal text reuse: LLM drafting loves repeating paragraphs. Flags
    near-duplicate paragraphs inside the manuscript (the local, honest part
    of what arXiv's corpus-wide overlap detector does)."""
    paras: dict[str, str] = {}
    for rel, text in _manuscript_texts(paper_dir).items():
        body = re.sub(r"%.*", "", text)
        for para in re.split(r"\n\s*\n", body):
            norm = re.sub(r"\s+", " ", para).strip().lower()
            norm = re.sub(r"\\[a-zA-Z]+\*?|\{|\}", "", norm)
            if len(norm.split()) >= 25:  # only substantial paragraphs
                if norm in paras:
                    return {"pass": False,
                            "reason": "duplicate paragraph",
                            "first": paras[norm], "duplicate": rel,
                            "preview": norm[:120]}
                paras[norm] = rel
    return {"pass": True, "paragraphs_checked": len(paras)}


def check_position_paper_rule(config) -> dict:
    """Since 2025-10-31 arXiv cs accepts review/position papers only with a
    journal reference (acceptance proof)."""
    paper = getattr(config, "paper", None)
    ptype = str(getattr(paper, "type", "research") or "research").lower()
    cat = str(getattr(paper, "category", "") or "").lower()
    if ptype in {"review", "position"} and cat.startswith("cs"):
        ref = getattr(paper, "journal_ref", None)
        if not ref:
            return {"pass": False,
                    "reason": "review/position paper in cs.* requires a journal "
                              "reference (arXiv practice since 2025-10-31)"}
    return {"pass": True}


def submission_preflight(config) -> dict:
    """Advisory (never silently green, never auto-submit): what the human
    submitter must confirm before P37. Rate limits per submitter since
    2026-10-01: ≤2 new submissions/calendar month, ≤3 active, ≤1 replacement
    per week after v5."""
    return {
        "note": "advisory only — P37 external submission is never automatic",
        "checklist": [
            "submitter account endorsed for every target category",
            "rate limits: ≤2 new submissions this calendar month, ≤3 active, "
            "≤1 replacement/week after v5",
            "license choice is irrevocable — confirmed by the author",
            "self-submission by an author (third-party submission restricted)",
            "known text overlap with own prior work declared in the comments field",
        ],
        "rate_limits": {"new_per_calendar_month": 2, "active_max": 3,
                        "replacement_per_week_after_v5": 1, "since": "2026-10-01"},
    }


ARXIV_CHECKS = [
    "ai_disclosure", "no_ai_authorship", "no_meta_comments", "english_language",
    "license_declared", "filenames_and_figures", "self_overlap",
    "position_paper_rule",
]
