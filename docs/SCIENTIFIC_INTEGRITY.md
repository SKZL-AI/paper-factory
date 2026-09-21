# SCIENTIFIC INTEGRITY

## Evidence authority (T0–T4)

T0 empirical source artifacts (results, data, code, run manifests) ·
T1 derived evidence (metrics, tables, figures) · T2 external literature ·
T3 project rationale / chat provenance · T4 draft prose.
Higher tiers override lower ones. A draft never overrides an artifact.

## Numbers

raw → normalized → analysis → `paper_metrics.json` → LaTeX macros → paper.
The statistics pipeline groups by design parameters (never pools across
loads/filters — regression test exists). The integrity audit re-reads drafts
and flags: numbers in metric range but off every derived value
(tolerance: 5% or the print rounding unit), and significance claims with no
computed test artifact. The numbers/units audit (P22) forbids hand-typed
decimals in manuscript sections.

## Claims

`claims.yaml`: every empirical claim carries status PROPOSED → EVIDENCE_FOUND →
VERIFIED / PARTIAL / CONTRADICTED / UNSUPPORTED / RETIRED. VERIFIED requires
evidence linkage (validated in code). Closure U1 re-checks at the end.

## Citations

Every bibliography DOI is resolved against Crossref AND OpenAlex; NOT_FOUND is
a CRITICAL finding; remediation drops the entry and re-audits
(`citation_audit_final.json`); closure U4 reads the post-remediation audit.
No citation is invented; offline mode reports NOT_RUN, not PASS.

## Reviews

Structured findings (CRITICAL/MAJOR/MINOR/NIT) with dispositions
(RESOLVED / NOT_APPLICABLE / ACCEPTED_LIMITATION / AUTHOR_DECISION).
CRITICAL/MAJOR without disposition block closure (U5). Adversarial review is
a separate reviewer id; model-family independence is recorded or honestly
marked DEGRADED_INDEPENDENCE.

## Reproducibility

P10 re-executes the project's own pipeline in a scratch copy and compares
result hashes; mismatches are reported, not hidden.

## Release

Clean export excludes chat logs, internal reviews, local config. The secret
scanner (pattern + entropy) fails closed. The bundle rebuilds independently
(P34) before closure passes (U10).
