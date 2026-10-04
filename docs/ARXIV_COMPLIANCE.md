# arXiv Compliance (P32 extension)

Status of policy verification: **2026-10-04**, against primary sources.
The machine-readable checks live in `paper_factory/venue/arxiv_policy.py`
and run as part of P32 when `paper.target: arxiv` (or `--target arxiv`),
plus standalone via `paper-factory compliance --target arxiv`.

## Verified policy facts (primary sources)

| Rule | Policy text (abridged) | Source |
|---|---|---|
| Significant GenAI use must be reported in the work | "we now include in particular text-to-text generative AI among those that should be reported consistent with subject standards" | [help/moderation](https://arxiv.org/help/moderation) |
| No LLM authorship | "generative AI language tools should not be listed as an author" | [help/moderation](https://arxiv.org/help/moderation) |
| Full author responsibility | "they each individually take full responsibility for all its contents, irrespective of how the contents were generated" | [help/moderation](https://arxiv.org/help/moderation) |
| Rate limits (per submitter) | ≤2 new submissions/calendar month, ≤3 active (since 2026-10-01); ≤1 replacement/week after v5 | [blog 2026-10-01](https://blog.arxiv.org/2026/10/01/updated-rate-limit-policy/), [help/moderation](https://info.arxiv.org/help/moderation/index.html) |
| Moderation ≠ peer review | "the arXiv moderation process is not a peer-review process" | [help/moderation](https://arxiv.org/help/moderation) |
| Originality/substance | submissions lacking "originality, novelty, significance" may be declined | [help/moderation](https://arxiv.org/help/moderation) |
| License mandatory + irrevocable | "The license chosen is irrevocable and cannot be changed." (6 options) | [help/license](https://arxiv.org/help/license) |
| Endorsement | first submission (per category) requires endorsement | [help/endorsement](https://arxiv.org/help/endorsement.html) |
| English full version | required since 2026-02-11 | [blog 2025-11-21](https://blog.arxiv.org/2025/11/21/upcoming-policy-change-to-non-english-language-paper-submissions/) |
| Review/position papers in cs | only with journal reference/acceptance proof, since 2025-10-31 | [blog 2025-10-31](https://blog.arxiv.org/2025/10/31/attention-authors-updated-practice-for-review-articles-and-position-papers-in-arxiv-cs-category/) |
| Filename charset / no external figures | `[a-zA-Z0-9_+\-.,=]`, no externally linked files | [help/submit](https://arxiv.org/help/submit) |
| Text overlap | arXiv runs its own corpus overlap detector; known overlaps belong in the comments field | [help/overlap](https://info.arxiv.org/help/overlap.html) |

Enforcement practice (2026): arXiv leadership announced one-year bans for
incontrovertible unchecked LLM output (hallucinated references, leftover
chatbot meta comments) — documented by
[CERN Courier 2026-07-23](https://cerncourier.com/arxivs-one-strike-rule-on-ai/);
no dedicated policy page found (treated as enforcement practice, not policy).

## The checks

| Check | Fails when |
|---|---|
| `ai_disclosure` | no `ai_disclosure.yaml`, schema violation, or the rendered declaration section missing from the manuscript; declared tools must be named in the text |
| `no_ai_authorship` | an AI tool name appears in `\author{}` |
| `no_meta_comments` | chatbot meta-comment patterns in the manuscript (LaTeX comments excluded) |
| `english_language` | stopword heuristic rejects the main text |
| `license_declared` | `paper.license` missing or not one of the six arXiv options (natural spellings like `CC BY 4.0` are normalized) |
| `filenames_and_figures` | filename outside the arXiv charset, or externally linked figures |
| `self_overlap` | verbatim duplicate paragraph (≥25 words) inside the manuscript |
| `position_paper_rule` | `type: review|position` + `category: cs.*` without `journal_ref` |

Plus an advisory `arxiv_submission_preflight.json` (rate limits, endorsement,
license irrevocability) — P37 external submission is never automatic.

## `ai_disclosure.yaml`

Lives in the config dir next to `paper-factory.yaml`
(template: [examples/ai_disclosure.yaml](../examples/ai_disclosure.yaml)).
Task stages use GAIDeT vocabulary (Suchikova et al. 2025,
[doi:10.1080/08989621.2025.2544331](https://pubmed.ncbi.nlm.nih.gov/40781729/)).
The rendered declaration text is generated from the structured fields — the
paper can never drift from the declaration. Paper Factory never invents a
disclosure: no file → FAIL.

## Not locally checkable (honest limits)

- Corpus-wide plagiarism (arXiv's own detector runs server-side)
- Endorsement status of the submitter account
- Actual submission counters — the preflight lists the rules; the human
  submitter confirms them

## Notes

- Check-level FAILs become the P32 node verdict; with the default config
  (`release.clean_build` unset) a failed P32 degrades the pipeline
  (DEGRADED) instead of hard-failing — pre-existing P32 semantics, unchanged.
- Macro-indirected author fields (`\author{\mymacro}`) cannot be expanded
  statically — the check reports them for manual confirmation (warnings),
  it does not silently pass them as human-verified.
- AI tool name matching is separator/case-insensitive and substring-based;
  rare human names that collide with tool names may need a review note.
