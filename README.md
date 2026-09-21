# PAPER FACTORY

Harness-neutral, evidence-first, agentic research-paper production system.

The canonical entry point is a deterministic CLI — not an interactive agent:

```bash
paper-factory complete
```

Interactive frontends (`/complete-paper` in Kimi/Claude/Pi/OpenCode) are thin
wrappers around the same core.

## What it is

- **PAPER FACTORY CORE** (this repo): deterministic orchestration, persistent
  state (SQLite + immutable JSON/JSONL/YAML artifacts), the P00–P37 research
  DAG, claim–evidence graph, provenance firewall, release machinery, and the
  global closure invariants U1–U16.
- **VeriHarness/HoH** is integrated *through an adapter* as the verification
  kernel (plan → develop → independent QA → receipts → accept/reject).
- **Herdr** is runtime infrastructure (sessions, panes, worktrees) — it never
  decides scientific truth.
- Harnesses (Claude Code, Codex, Kimi, Pi, OpenCode, LiteLLM) are workers;
  the backend model identity is recorded separately from the harness name.

## Install

```bash
git clone <this repo> && cd paper-factory
python3 -m venv .venv && .venv/bin/pip install -e .
# VeriHarness kernel:
.venv/bin/pip install hoh==0.1.0   # or: pip install -e /path/to/veriharness
```

## Commands

```bash
paper-factory doctor     # machine/harness/provider capability inventory
paper-factory intake     # detect input mode, register artifacts
paper-factory plan       # show the DAG with current node states
paper-factory run        # execute the DAG once
paper-factory complete   # the full pipeline
paper-factory complete --dry-run / --resume / --strict / --offline / --target arxiv
paper-factory resume     # continue the latest run (e.g. after a HUMAN_REQUIRED gate)
paper-factory status     # node states of the latest run
paper-factory report     # run report
paper-factory audit      # receipts
paper-factory release    # release bundle state
```

## Hard rules the system enforces

- No empirical final-paper claim without evidence linkage (T0–T4 authority).
- No hand-typed scientific number: raw → metrics → LaTeX macros.
- Final prose only from allowed origins (strict mode excludes Anthropic
  backends from protected paths; unknown backend = deny).
- CRITICAL/MAJOR review findings cannot silently disappear.
- The release bundle carries no secrets, no chat logs, no internal reviews,
  and must rebuild independently.
- P36 is a human final sign-off. P37 (external submission) is never automatic.

## Docs

See `docs/`: ARCHITECTURE, OPERATIONS, PAPER_WORKFLOW, PROVIDER_ROUTING,
VERIHARNESS_INTEGRATION, SCIENTIFIC_INTEGRITY, PROVENANCE_POLICY, RECOVERY,
METHODOLOGY_CONSOLIDATION. The VeriHarness gap analysis:
`VERIHARNESS_GAP_REPORT.md`. Installation evidence: `INSTALLATION_REPORT.md`.
