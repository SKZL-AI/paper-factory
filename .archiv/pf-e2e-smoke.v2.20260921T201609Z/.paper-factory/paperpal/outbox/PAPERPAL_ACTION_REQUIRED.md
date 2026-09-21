# PAPERPAL_ACTION_REQUIRED

Paper Factory has no usable Paperpal API integration on this machine.

## What to do
1. Take the manuscript candidate from `outbox/` (file listed below).
2. Run Paperpal checks: language, references, submission readiness.
3. Put the Paperpal report (and any edited manuscript) into `inbox/`.
4. Resume: `paper-factory complete --resume`

## Rules
- Default mode is report/check — Paperpal is NOT the authoritative final writer.
- If you let Paperpal rewrite prose, say so: it counts as `external_prose_origin`
  and forces a semantic diff (claim strength, causality, numbers, limitations).


- outbox file: `main.tex`
- created: 2026-09-21T20:14:41Z
