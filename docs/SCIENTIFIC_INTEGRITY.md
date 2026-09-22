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
decimals in manuscript sections and main.tex. Known scope, stated honestly: the draft-side
integrity audit matches decimals with ≥2 places and percentages; bare integers (years, counts)
are out of scope because they are too noisy to police deterministically.

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
scanner (pattern + entropy) fails closed: files of any size are streamed with
a boundary overlap (nothing is skipped for size), non-text files are scanned
under 13 byte-space views at once (latin-1, UTF-16 LE/BE both parities,
UTF-32 LE/BE all four parities — no density gate an attacker could split a
payload around), and a symlink inside the bundle fails the scan. U8 reads the
scan of the *active* bundle via the pointer P33 persists
(`reports/current_release.json`, hash-pinned) — never a lexicographic guess —
and additionally verifies the full bundle manifest (`bundle_files`: the P33
export set plus the P34 build outputs): any unpinned, mutated, missing or
symlinked file fails closure. Build artifacts are pinned but not scanned by
design: they derive from scanned, pinned sources via pdflatex without shell
escapes. U6 compares the full canonical freeze manifest (every frozen file:
present, hash-identical, none added; symlink map and pinned internal symlink
targets included) against both the workspace and the active bundle. Corrupt
review artifacts fail closed as REVIEW_ARTIFACT_INVALID instead of being
skipped. A DEGRADED or unknown invariant state never rounds up to closure
PASS. The bundle rebuilds independently (P34) before closure passes (U10).

Trust boundary: closure detects tampering with release artifacts against the
records in `reports/` (freeze record, release pointer). The integrity of
`reports/` itself is an operator assumption — it is the trust root of every
closure check, not something closure can prove from inside.
