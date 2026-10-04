# Changelog

## [1.1.0] — 2026-10-04

arXiv compliance layer (P32 extension), verified against primary arXiv
sources on 2026-10-04:

- New checks for venue `arxiv`: structured AI-use disclosure
  (`ai_disclosure.yaml`, GAIDeT vocabulary, fail-closed), no-LLM-authorship
  scan, chatbot meta-comment scan, English-language check, license allowlist
  (6 arXiv options), filename/figure rules, self-overlap detection,
  cs review/position-paper journal-reference rule
- Advisory `arxiv_submission_preflight.json` (rate limits 2/month + 3 active
  since 2026-10-01, endorsement, license irrevocability)
- New CLI command: `paper-factory compliance --target arxiv`
- `paper` config gains `license`, `type`, `category`, `journal_ref`
- Docs: `docs/ARXIV_COMPLIANCE.md` with the verified policy mapping
- 44 adversarial tests

## [1.0.1] — 2026-10-04

Repository professionalization (no pipeline-semantics change):

- GitHub CI green on Python 3.11/3.12 (TeX/pandoc toolchain in the workflow,
  honest skips for machine-dependent adapter tests)
- MIT LICENSE file, CITATION.cff, professional README, position paper
  (`docs/paper/`), reports moved to `docs/reports/`, machine paths
  desensitized

## [1.0.0] — 2026-10-02 (v1.0 Freeze)

First public release. Evidence-first, harness-neutral research-paper
production core, validated end-to-end on a real pilot paper.

- Deterministic P00–P37 research DAG with persistent state and receipts
- Global closure invariants U1–U16 (claim support, citation identity,
  number-to-metric binding, remediation integrity, external-edit reconciliation)
- VeriHarness/HoH verification-kernel adapter; provider router with
  Claude/Kimi/Codex/Pi/OpenCode/GLM/LiteLLM worker adapters
- Microsoft Word + Paperpal integration (ownership-scoped, capture-only)
- Citation verification incl. authoritative-URL path for no-DOI sources
- Durable human decisions with collision-hardened finding identity
- arXiv-ready release packaging; P36 human sign-off; P37 never automatic
- 574 tests (+2 Windows-only environment skips); 245 unique writing-assistant suggestions
  processed capture-only, 100 % dispositioned (75 applied, 124 rejected,
  46 not applicable)

Evidence: `V1_FREEZE_REPORT.md`, `docs/reports/FINAL_ACCEPTANCE_2026-10-02.md`.
