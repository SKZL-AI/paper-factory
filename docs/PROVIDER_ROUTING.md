# PROVIDER ROUTING

## Harness ≠ backend

Every invocation receipt records both: harness (name+version) AND backend
(provider_family, model_family, endpoint_alias). A harness named "claude"
pointing at a GLM endpoint is recorded as its actual backend when verifiable
(`ANTHROPIC_BASE_URL` → endpoint_alias + family `unknown-compatible`; we never
guess a family from a URL).

## Selection (`providers/router.py`)

`select_for_role(role)`:
1. candidates from `role_preferences[role].preferred` (providers.yaml);
2. filter: enabled, doctor present, `forbidden_model_families` from
   provider-policy.yaml;
3. provenance gates for prose-writing roles (documented marking ⇒ excluded,
   unknown backend ⇒ deny when policy says deny);
4. independence: if the role has `preferred_different_family_from` (or is in
   `independence_required_for`), a same-family candidate is only used as
   explicitly recorded `DEGRADED_INDEPENDENCE` — never silently;
5. `allow_degraded_independence: false` turns the fallback into
   HarnessUnavailable.

`invoke()` writes an `InvocationReceipt` (sha256 of prompt and response,
identity block, exit code) to `receipts/invocations.jsonl`.

## This machine (2026-09-21)

| Harness | Version | Backend | Status |
|---|---|---|---|
| claude | 2.1.278 | anthropic (ANTHROPIC_API_KEY present) | available |
| codex | 0.153.4 | openai (OPENAI_API_KEY present) | available |
| kimi | 2.0.2 | moonshot (CLI login) | available |
| pi | 0.85.1 | per its config | available |
| opencode | — | — | not installed (UNAVAILABLE) |
| litellm | — | gateway | only when PAPER_FACTORY_LITELLM_* env set |

Capabilities are never inferred from names — each adapter parses `--help`
output (see `state/harness_capabilities.json`).
