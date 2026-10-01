"""Suggestion classification for the Paperpal bridge (consultant brief F).

No blind 'accept all' — ever. Every captured Paperpal suggestion is
classified before anyone may act on it:

    SAFE_MECHANICAL          pure typography / spelling / punctuation
    SEMANTICALLY_GUARDED     grammar/style rewrite — may only be applied
                             after a semantic diff proves numbers, claims,
                             math, citation ids and terminology unchanged
    SCIENTIFIC_OR_AMBIGUOUS  touches claims, numbers, results, methods,
                             limitations, citations or scientific terms —
                             never auto-applied; stored as a proposal for
                             U16/P36.

v1 of the Word adapter is capture-only: nothing is applied at all, so the
classifier's job is to produce the visible proposal list.
"""
from __future__ import annotations

import re

SAFE_CATEGORIES = {"typography", "spelling", "punctuation", "mechanics"}
SCIENTIFIC_CATEGORIES = {"citation", "reference", "terminology", "academic style"}

_NUMBER = re.compile(r"\d")
# written-out numbers count as numbers (reviewer B R3-F4): 'seven epochs' →
# 'eight epochs' is a scientific change, not mechanics
_NUMBER_WORD = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"half|quarter|twice|thrice)\b", re.I)
_CLAIM_WORDS = re.compile(
    r"\b(prove[sd]?|demonstrate[sd]?|show[sd]? that|significant|caus|"
    r"improve[sd]?|outperform|guarantee|always|never|novel|first)\b", re.I)
_MATH = re.compile(r"[=≈≤≥∑∏√±×÷]|\balpha\b|\bbeta\b|\\\[a-zA-Z]+")
_CITEKEY = re.compile(r"\[\d+\]|\\cite|\bdoi\b|arXiv", re.I)


def classify_suggestion(category: str, before: str, after: str) -> str:
    """Classify one captured suggestion. Order matters: anything touching
    scientific content is SCIENTIFIC_OR_AMBIGUOUS even when Paperpal files
    it under 'grammar'."""
    cat = (category or "").strip().lower()
    joined = f"{before} {after}"
    if cat in SCIENTIFIC_CATEGORIES or _CITEKEY.search(joined):
        return "SCIENTIFIC_OR_AMBIGUOUS"
    if _MATH.search(joined) or _CLAIM_WORDS.search(joined):
        return "SCIENTIFIC_OR_AMBIGUOUS"
    if _NUMBER.search(before) or _NUMBER.search(after):
        return "SCIENTIFIC_OR_AMBIGUOUS"
    if _NUMBER_WORD.search(before) or _NUMBER_WORD.search(after):
        return "SCIENTIFIC_OR_AMBIGUOUS"
    if cat in SAFE_CATEGORIES:
        return "SAFE_MECHANICAL"
    return "SEMANTICALLY_GUARDED"
