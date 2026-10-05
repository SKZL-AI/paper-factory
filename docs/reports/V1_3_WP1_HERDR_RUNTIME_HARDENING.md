# v1.3 WP1 — Herdr / CLI-TUI Runtime Hardening: Root Cause & Upstream Proposal

Status: root cause **confirmed from primary sources** (herdr binary docs + VeriHarness
dispatcher source + v1.2 field-test evidence). No PF-side hack introduced;
`--no-herdr` fallback stays. Live PF→VH→Herdr→Runner→Receipt proof: pending one
field attempt (see §5).

## 1. Symptom (field-measured, 2026-10-05)

During the v1.2 integration proof, HoH runs over the Herdr dispatcher stalled in
the **developer role** with `agent_prompt_stalled` when the role backend was a
current CLI TUI (kimi shows a welcome screen; codex shows an empty pane). The
planner role via Herdr worked. Runs: `PF-73ed7828-P05`, `PF-581db7b3-P05`,
`PF-7aeb552c-P05`. The proof ultimately succeeded via
`HarnessDispatcher (--no-herdr)` — subprocess dispatch instead of panes, with the
evidence trade-off documented in `DEFERRED_HARDENING.md`.

## 2. Root cause (proven, not assumed)

Herdr 0.8.0 ships this rule verbatim in its built-in documentation (recovered
from the installed binary, `~/.local/bin/herdr`):

> "A prompt sent from a non-working state must produce an observed lifecycle
> change within five seconds. Otherwise Herdr returns `agent_prompt_stalled`
> instead of waiting indefinitely. This wait tracks lifecycle state, not an
> individual turn; if the agent is already working, completion of the active
> turn may satisfy it."

So the 5-second window is **herdr-internal, hard-coded, and deliberately
conservative** — it is not the `--timeout MS` of `herdr agent prompt`.
VeriHarness already passes a long timeout (`dispatchers.py`: `herdr agent
prompt <target> <full> --wait --timeout <ms>`); that timeout governs the overall
wait, never the stall window.

Why current CLI TUIs trip it: after `agent start`, kimi displays a welcome
screen and codex an empty composer; neither produces a herdr-recognized
lifecycle change within five seconds of the first prompt, so the dispatch is
aborted as `agent_prompt_stalled` before the agent ever processed the text.

Responsibility split (checked against `src/hoh/dispatchers.py` in VeriHarness,
read-only): tab/pane setup, agent start retries and prompt dispatch in
VeriHarness are sound (own tab per role, 240 s start timeout, wrapper timeout
derived from `--timeout`). The defect is upstream in herdr's stall detection,
compounded by TUI-specific lifecycle recognition gaps for newer CLI versions.

## 3. What Paper Factory does NOT do

- No PF-side hack (no synthetic keystrokes, no pane scraping, no fake lifecycle
  pokes) to dodge the stall window.
- No modification of `/home/sai/veriharness` (read-only) or of the herdr binary.
- The `--no-herdr` path (`use_herdr=False`) remains the supported PF fallback,
  with its honest evidence trade-off (no A01/A02/A12 pane evidence).

## 4. Upstream proposal (for github.com/ogulcancelik/herdr)

1. Make the stall window **configurable** (`agent prompt --stall-timeout MS`,
   default 5000) and/or configurable per agent kind.
2. Recognize welcome/onboarding screens of current CLI TUIs (kimi, codex) as a
   lifecycle state, or treat "prompt accepted into composer" as the observed
   change instead of requiring a full state transition.
3. Return structured stall diagnostics: which state was observed, what change
   was expected — so callers can distinguish "agent never got the prompt" from
   "agent is thinking".

VeriHarness-side suggestion (for the VeriHarness maintainers, not PF): an
optional **pre-warm dispatch** — a trivial first prompt that moves a fresh TUI
past its welcome screen into a working state before the real role prompt, since
the 5 s rule only applies to prompts sent from a non-working state.

## 5. Live herdr-path proof (pending field test)

A real PF → VeriHarness → Herdr → runner → receipt → PF run remains desirable.
The stall is backend-specific: roles driven by claude historically worked via
herdr (pre-v1.2 A-runs). One field attempt with all roles on claude is planned
in the v1.3 pilot phase (WP12), subject to claude quota. If it succeeds, this
document gets an addendum; if not, the limitation stands as documented — it is
not a v1.3 release blocker because the verification plane is proven over the
subprocess dispatcher.

## 6. Evidence index

- Field runs: `PF-73ed7828-P05`, `PF-581db7b3-P05`, `PF-7aeb552c-P05` (2026-10-05)
- v1.2 proof report: `docs/reports/V1_2_REAL_VERIHARNESS_INTEGRATION_PROOF.md`
- Herdr rule: herdr 0.8.0 built-in docs (binary strings, quoted above)
- Dispatcher: VeriHarness `src/hoh/dispatchers.py` (`_new_tab_pane`,
  `_start_agent`, `dispatch`, `_wrapper_timeout`)

---

## Addendum 2026-10-05 — WP12 live field test (one attempt, claude roles, herdr path)

Announced in §5; executed exactly once as part of the WP12 pilot matrix.

**Pre-checks (no cost):** herdr 0.8.0 present, claude CLI 2.1.289 present.

**Attempt:** run `PF-4ca0e67c-P05`, planner/developer/qa all claude,
`use_herdr=True` (real herdr pane dispatch via the VeriHarness adapter;
the script gained backward-compatible `--herdr` / `--roles` / `--evidence`
flags for this — defaults unchanged). Evidence:
`docs/reports/v1_3_integration_proof_herdr_20261005T124256Z.json`.

**Result: the 5 s stall did NOT trigger for claude.** Tab/pane setup and
prompt dispatch worked; the planner role completed (`agent_status: done`).
The run then blocked in the developer pane: claude showed its
folder-trust approval dialog ("Yes, I trust this folder"), which HoH
deliberately does not answer automatically → `condition: BLOCKED`,
stage DEVELOPING → VH verdict FAIL → differential **MISMATCH** (native
side PASS). This is an honest field result, not a regression of the v1.2
proof: the binding verification evidence remains the subprocess-path
proof in `V1_2_REAL_VERIHARNESS_INTEGRATION_PROOF.md` (differential MATCH).

**New finding (claude-specific, distinct from the stall):** claude's
trust dialog blocks unattended herdr dispatches into not-yet-trusted
folders. Options for a future attempt (none executed — quota discipline
and the one-attempt rule): pre-trust the PF/HoH working folder in the
claude configuration before dispatch, or an upstream HoH/VeriHarness
mechanism to declare trusted workdirs. PF itself does not auto-confirm
dialogs (§3 stands).

**Cleanup:** the run's own herdr tabs were closed after the run
(workspace w6F, tabs of this run plus one leftover developer tab from
the morning's stall attempt). Foreign panes/workspaces untouched.
The blocked HoH run was left blocked for a human (`hoh unblock
PF-4ca0e67c-P05`) — no silent continuation.
