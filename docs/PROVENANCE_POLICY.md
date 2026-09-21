# PROVENANCE POLICY

## Final prose origin

Protected paths (provider-policy.yaml `protected_final_prose_paths`):

```
paper/main.tex
paper/sections/**/*.tex
paper/appendix/**/*.tex
paper/generated/captions*.tex
paper/cover_letter.*
paper/response_to_reviewers.*
```

A write to a protected path requires ALL of:
1. role with `writes_final_prose: true`,
2. backend family not in the role's `forbidden_model_families`,
3. backend identity known (unknown ⇒ deny under strict policy),
4. no `documented_marking` entry in the model-marking registry,
5. strict policy: `disallow_anthropic_generated_final_prose: true` excludes
   Anthropic/Claude origins.

Enforcement is code: `provenance/firewall.decide_write()` raises
`PolicyViolation`; `provenance/origin.record_origin()` appends an origin
receipt per write (closure U11/U12/U13 re-read them).

## What this is NOT

Not watermark removal. Not paraphrasing to defeat attribution. Origin is
controlled from the start; reviewer prose is never copied into the manuscript
(U15) — remediation reconstructs from primary evidence.

## Marking registry honesty (U14)

Statuses: `documented_marking`, `documented_no_marking`, `unknown`,
`not_applicable`, `human`. Unknown is reported as unknown. The correct claim
is "Claude-origin final prose excluded" — never "watermark-free paper".

## Deterministic composition

The built-in writer is Paper Factory's own template composer
(backend `paper-factory/deterministic`, marking `not_applicable`): sections
are code-generated from the claim graph, metrics and evidence. LLM-polish is
an optional layer routed through the same policy.
