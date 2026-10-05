# v1.5 — Evidence Intelligence: Decision Gates (conditional version)

Date: 2026-10-05 · Branch: `v1.5/decision-gates` · Base: v1.4.0 (`61a2686`)

v1.5 is **conditional by design**: a release happens only if a gate demonstrates
real new productive capability. This document records the four gate decisions.
Result: **no v1.5.0 release** — the evidence says REJECT/DEFER on all four;
the roadmap moves directly to v2.0 stabilization.

## Gate A — PaperQA2 Literature Provider: DEFER (benefit gate defined, benchmark NOT_RUN)

- Status quo: PF-native literature path (`paper_factory/literature/`:
  discovery, citation verify, authoritative-URL verify, novelty) is the
  canonical reference and is not up for replacement. `paperqa` exists as an
  optional extra (`pyproject [literature]`) and is probed in inventory, but
  has **no consumer in the code** (grep-proven).
- A benefit benchmark (same query set, same evidence policy; compare coverage,
  precision, citation identity, source traceability, contradiction discovery,
  runtime, LLM cost, failure semantics) **requires paid LLM/network calls** —
  PaperQA2 is agentic RAG over an LLM. Per the program policy, a mandatory
  paid external API defers exactly this block instead of stopping the program.
- The benchmark is **defined, not run**: gate criteria and comparison axes are
  fixed here; execution waits for an authorized budget decision.
- Reopening condition: a real literature task where PF-native retrieval is
  demonstrably insufficient, plus an authorized benchmark budget.

## Gate B — Additional citation provider: REJECT_NO_CURRENT_NEED

- No proven capability gap: the canonical P21 path verifies DOI, arXiv and
  authoritative URLs (v1.0 pilot: 21/21 references verified, including the
  no-DOI authoritative-URL class with HTTPS/host/title/hash provenance).
- External resolvers may complement candidates later, but must never silently
  weaken identity rules — no candidate exists today that would add anything.

## Gate C — Provider SDK: REJECT_NO_CURRENT_NEED (rule satisfied negatively)

- The rule: build a broad provider SDK only when at least two real independent
  provider implementations of the same contract class exist. Verification
  plane has exactly one external backend (VeriHarness). The reproduction
  plane's three backends (local/snakemake/nextflow) are served by the
  **conformance suite**, which is the correct instrument for N internal
  backends — an SDK abstraction would add nothing a consumer needs.
- Registry + conformance suite remain the extension points.

## Gate D — Reviewer ensemble via VeriHarness: VALUE ALREADY MEASURED, no code

- The question was whether multiple specialised reviewers add measurable value
  to PF review gates. The evidence exists in-repo: the adversarial dual reviews
  of v1.2/v1.3/v1.4 caught real CRITICAL/MAJOR defects each round (vacuous
  gate wiring, replay namespace, default-path crash, silent argv corruption,
  orphan reaping) — dual independent review is demonstrably load-bearing.
- VeriHarness ensembles behind the verification contract remain the way to add
  more independent reviewers. No second orchestration is built in PF.
- Review is a gate, never an approval; P36 stays human.

## Conclusion

All four gates: DEFER(A) / REJECT(B) / REJECT(C) / REUSED-not-new(D). No new
productive capability → **no v1.5.0 release** (per the master plan's own
condition). Proceed directly to v2.0 contract stabilization. `docs/ROADMAP.md`
is updated accordingly.
