"""Shared quantitative-claim surface detection for P22 (numbers audit) and U2
(closure provenance gate). One definition, two consumers — no divergent truths.

Tex-aware normalization happens before matching so that LaTeX spacing tricks
(`42\\,\\%`, `42~\\%`), Unicode variants (`％`, en-dash folds) and APA-style
leading-dot p-values (`.05`) cannot evade detection (post-pilot audit,
reviewer findings B-F1/B-F2).
"""
from __future__ import annotations

import re
from pathlib import Path

# sections whose numbers are always claim-bearing; inverted logic on purpose:
# anything NOT known to be design prose is treated as claim-bearing (fail-closed
# for appendices and unknown files — post-pilot review B-F1/B-F2). Compared by
# canonical path relative to paper/ (a "methods.tex" in an appendix directory is
# claim-bearing — post-pilot review B-G7).
_NON_CLAIM_PATHS = {"methods.tex", "introduction.tex", "related_work.tex",
                    "related.tex", "background.tex", "notation.tex",
                    "sections/methods.tex", "sections/introduction.tex",
                    "sections/related_work.tex", "sections/related.tex",
                    "sections/background.tex", "sections/notation.tex"}


def is_claim_section(rel_path: str) -> bool:
    return rel_path not in _NON_CLAIM_PATHS


# kept for backwards compatibility with existing imports
CLAIM_SECTIONS = {"results.tex", "abstract.tex", "discussion.tex"}

# LaTeX spacing/no-op constructs that must not split a quantitative surface
# (control space "\ ", italic correction "\/", empty group "{}", discretionary
# hyphen "\-", \relax, \kern, \phantom, thin spaces, non-breaking "~" —
# post-pilot review B-G1/B-H3)
_LATEX_SPACING = re.compile(
    r"\\[,;:!/ ]|\\-|\\relax\b|\\kern\s*[-0-9.a-z]+|\\phantom\s*\{[^}]*\}|\{\}|~")
_LATEX_PERCENT_MACRO = re.compile(r"\\percent\b")
_UNICODE_PERCENT = "％"  # U+FF05 FULLWIDTH PERCENT SIGN
_UNICODE_HYPHENS = "‐‑‒–—―"  # U+2010..U+2015
_UNICODE_TIMES = "×"      # U+00D7 MULTIPLICATION SIGN

# unambiguous quantitative claims — scanned in every manuscript file
_RE_PERCENT = re.compile(
    r"\b\d+(?:\.\d+)?\s*\\?%|\b\d+(?:\.\d+)?\s*(?:percent|per\s+cent|Prozent)\b"
    r"|\b\d+(?:\.\d+)?-(?:percent|per-cent)\b", re.IGNORECASE)
_RE_PFGET = re.compile(r"\\pfget\s*\{([^}]*)\}")  # TeX skips space before the arg (B-G5)
_RE_RAW_CSNAME = re.compile(r"\\csname\s+pf@([^\s\\]+?)\\endcsname")

# claim-section-only forms (design constants like "5-fold cross-validation" or
# "lr = 1e-3" legitimately live in methods/introduction — they are not results)
_RE_FOLD = re.compile(r"\b\d+(?:\.\d+)?\s*-?\s*fold\b"
                      r"|\b(?:two|three|four|five|six|seven|eight|nine|ten)\s*-?\s*fold\b",
                      re.IGNORECASE)
_RE_SPEEDUP = re.compile(r"\b\d+(?:\.\d+)?\s*x(?=\s|$|[,.;)])"
                         r"|\b\d+(?:\.\d+)?\s+times\s+(?:as\s+)?(?:fast|faster|slow|slower|"
                         r"better|higher|lower|more|less|larger|smaller)\b",
                         re.IGNORECASE)  # "2.5x speedup" / "2.5 times faster" / "times as fast" (B-G2/H3)
_RE_SCI = re.compile(r"\b\d+(?:\.\d+)?[eE][+-]?\d+\b")
_RE_DECIMAL = re.compile(r"(?<![\w.])0?\.\d{2,}\b")          # 0.42 / .42 (APA p < .05)
_RE_DECIMAL_COMMA = re.compile(r"\b\d+,\d{1,2}\b")           # 0,42 (decimal comma)
_RE_SAMPLE_N = re.compile(r"\b[Nn]\s*=\s*\d+")               # N = 1284
_RE_COUNT_UNIT = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:participants|subjects|samples|runs|seeds|iterations|epochs|"
    r"patients|nodes|gpus|hours|minutes|seconds|ms|gb|mb|tb|points)\b", re.IGNORECASE)


_URL_OR_VERB = re.compile(
    r"\\url\{[^}]*\}|\\href\{[^}]*\}|\\path\{[^}]*\}|\\path(.).*?\1"
    r"|\\verb\*?(.).*?\2|\\lstinline\*?(.)[^\n]*?\3")

# the one canonical provenance-accessor line — compared EXACTLY, never by
# prefix (a redefined accessor that ignores its argument would render a
# constant forgery while every pf@ def and use binds cleanly; post-pilot B-K1)
PFGET_ACCESSOR_LINE = ("\\newcommand{\\pfget}[1]{\\ifcsname pf@#1\\endcsname"
                       "\\csname pf@#1\\endcsname\\else\\textbf{??}\\fi}")


def _strip_comments(text: str) -> str:
    """Remove full-line and inline comments. `%` inside \\url{…}/\\verb… is a
    literal, never a comment (post-pilot review B-J3); an escaped \\% survives.
    """
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("%"):
            continue
        protected: list[str] = []

        def _stash(m: re.Match) -> str:
            protected.append(m.group(0))
            return f"\x00{len(protected) - 1}\x00"

        tmp = _URL_OR_VERB.sub(_stash, line)
        tmp = re.sub(r"(?<!\\)%.*$", "", tmp)
        for i, chunk in enumerate(protected):
            tmp = tmp.replace(f"\x00{i}\x00", chunk)
        lines.append(tmp)
    return "\n".join(lines)


def normalize_tex(text: str, strip_comments: bool = True) -> str:
    """Strip comments and normalize spacing/unicode lookalikes.

    Comment stripping is \\url/\\verb-aware; an inline comment must not split a
    macro call from its argument (post-pilot review B-H2). strip_comments=False
    is for text that is NOT LaTeX (e.g. markdown draft claims, where `%` is a
    literal percent sign, not a comment marker)."""
    body = _strip_comments(text) if strip_comments else text
    body = _LATEX_PERCENT_MACRO.sub("%", body)
    body = _LATEX_SPACING.sub("", body)
    body = body.replace(_UNICODE_PERCENT, "%").replace(_UNICODE_TIMES, "x")
    for h in _UNICODE_HYPHENS:
        body = body.replace(h, "-")
    return body


def find_quantitative(text: str, claim_section: bool) -> list[str]:
    """Return the matched quantitative surfaces (normalized text input)."""
    hits = [m.group(0) for m in _RE_PERCENT.finditer(text)]
    if claim_section:
        for rx in (_RE_FOLD, _RE_SPEEDUP, _RE_SCI, _RE_DECIMAL, _RE_DECIMAL_COMMA,
                   _RE_SAMPLE_N, _RE_COUNT_UNIT):
            hits.extend(m.group(0) for m in rx.finditer(text))
    return hits


def find_pfget_uses(text: str) -> set[str]:
    """Macro uses in manuscript text: \\pfget{...} (space-tolerant) and raw
    \\csname pf@...\\endcsname — both are provenance references and both must
    bind to a derived metric (post-pilot review B-G5)."""
    return set(_RE_PFGET.findall(text)) | set(_RE_RAW_CSNAME.findall(text))


def find_pfget_uses_with_spans(text: str) -> list[tuple[str, int]]:
    """Like find_pfget_uses, but with positions — GAP-011 label binding needs
    the context window around each use."""
    out = [(m.group(1), m.start()) for m in _RE_PFGET.finditer(text)]
    out += [(m.group(1), m.start()) for m in _RE_RAW_CSNAME.finditer(text)]
    return sorted(out, key=lambda t: t[1])


def manuscript_tex_files(paper: Path, include_generated: bool = False) -> list[Path]:
    """All manuscript .tex under paper/, recursively — excluding the top-level
    build/ directory (and generated/ unless include_generated=True; raw values
    are legitimate there for number scanning, but generated/captions.tex IS
    printed prose for claim-presence checks — remediation passes True).
    The exclusion is TOP-LEVEL only: a nested sections/build/ or
    sections/generated/ directory is manuscript content (post-pilot review
    B-G6). Symlinks escaping the paper root are never followed into; in-paper
    symlinks resolve to their target content (U2/B1 surface parity)."""
    if not paper.exists():
        return []
    root = paper.resolve()
    excluded = {"build"} if include_generated else {"build", "generated"}
    out = []
    for p in sorted(paper.rglob("*")):
        if p.suffix.lower() != ".tex" or not p.is_file():
            continue
        rel_parts = p.relative_to(paper).parts
        if rel_parts[0] in excluded:
            continue
        if not p.resolve().is_relative_to(root):
            continue  # symlink escape — never scan outside the paper root
        out.append(p)
    return out
