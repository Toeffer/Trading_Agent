# Model Routing Safety Policy — Phase 3R

**No trading. No order automation.**

## Purpose

Ensure every AI-generated operation on the IBKR bridge codebase uses the appropriate model tier. Safety-critical logic requires strong reasoning models (Codex/OpenAI-class). Non-critical formatting and summarization may use fast/mini models.

This policy applies to all human-in-the-loop and autonomous agent invocations of:
- Editing source files (`bridge.py`, `guard.py`, `monitor.py`, `bundle_audit.py`)
- Generating or mutating state files (guard-state, events, approvals, reconciliations)
- Invoking bridge endpoints that touch order or guard logic
- Writing runbook or policy documentation

## Model Tiers

### Tier 1 — Strong Model (Codex / GPT-4o / DeepSeek V4 Flash or better)

**Required for all safety-critical modifications.**

| Scope | Files / Domains |
|---|---|
| Order lifecycle | Any edit to `bridge.py` containing `placeOrder`, `cancelOrder`, `/order`, `/order/submit`, `/order/preflight` |
| Kill switches | Any edit to `bridge.py`, `guard.py`, or `.env` affecting `IBKR_ALLOW_ORDERS`, `rules.enforced`, `system_locked` |
| Guard state | Any mutation of `guard-state.json`, `guard-events.jsonl`, `submitted-approvals.json` |
| Audit integrity | Any edit to `bundle_audit.py`, audit bundle files, release tag files |
| Reconciliation | Any edit to `monitor.py` affecting reconciliation logic |
| Monitoring drift | Any edit to `position_drift_check()` or `open_orders_check()` |
| Startup safety | Any edit to `_run_startup_safety()` in `bridge.py` |
| Readiness verdict | Any edit to `/readiness` endpoint logic or `rth_check()` |
| Bridge HTTP routes | Any new `@app.get`/`@app.post` that processes security-relevant data |
| Regression tests | Any edit to `monitor.py` test sections (A–Q) |

**Minimum acceptable models:**
- `openai/gpt-4o` or newer
- `openai/o3` or newer
- `openrouter/openai/gpt-4o`
- `openrouter/deepseek/deepseek-v4-flash`
- `anthropic/claude-sonnet-4` or newer

**Never use for safety-critical edits:**
- `gpt-4o-mini`, `gpt-4o-mini-*`
- `deepseek-chat` (V3 class)
- `claude-haiku`
- `gemini-*flash*`
- Any model with `mini`, `small`, `light`, `fast`, `tiny` in its name

### Tier 2 — Fast Model (Mini / Flash / Haiku class)

**Permitted only for non-critical, read-only, or cosmetic work.**

| Scope | Details |
|---|---|
| Terminal output formatting | Color coding, alignment, table layout in `ibkr_status.py` |
| Docstring cleanup | Rewording, grammar fixes, PEP 257 compliance |
| Comments and whitespace | Trailing whitespace, comment grammar, non-semantic changes |
| Runbook formatting | Table alignment, markdown lint, section reordering (no content changes) |
| Summary generation | Condensing status output, generating digest reports |
| Non-critical CLI help text | argparse descriptions, usage strings |

**Allowed models:**
- `gpt-4o-mini`
- `claude-haiku`
- `gemini-*-flash`
- `deepseek-chat` (V3)
- Any model with `mini`, `small`, `light`, `fast`, `tiny` for these specific tasks

### Tier 3 — Image / Vision Model

**Permitted for:**
- Reading screenshots of bridge output or error messages
- Analysing guard-events.jsonl or audit bundle visualizations
- Generating architecture diagrams for runbook

**No image model may:**
- Generate code
- Propose state mutations
- Author policy decisions

## Enforcement Rules

### Rule 1 — Edit Guard

Before any edit to `bridge.py`, `guard.py`, `monitor.py`, or `bundle_audit.py`:

1. Identify which sections of the file will change
2. If any changed section is in the Tier 1 scope, the current model **must** be Tier 1
3. If the current model is Tier 2, the edit must be deferred or escalated

### Rule 2 — State Mutation Guard

Before any write to `~/.openclaw/*.json` or `~/.openclaw/*.jsonl`:

1. Verify the current model is Tier 1
2. Log the mutation to the conversation for audit
3. Never batch-approve state mutations without human review

### Rule 3 — Bridge Invocation Guard

Before calling any bridge endpoint that could affect system state:

| Endpoint | Min Tier | Notes |
|---|---|---|
| `POST /connect` | 1 | Changes connection state |
| `POST /disconnect` | 1 | Changes connection state |
| `POST /order` | 1 | Order lifecycle |
| `POST /order/submit` | 1 | Order lifecycle |
| `POST /order/preflight` | 1 | Validate before order |
| `POST /monitor/open-orders/reconcile` | 1 | Reconciliation record |
| `GET /status` | 2 | Read-only dashboard |
| `GET /health` | 2 | Read-only health |
| `GET /readiness` | 2 | Read-only readiness |
| `GET /audit/bundle` | 2 | Read-only bundle |
| `GET /audit/verify` | 2 | Read-only verify |
| `GET /audit/release` | 2 | Read-only release |
| `GET /audit/release/latest` | 2 | Read-only release |
| `GET /monitor/open-orders` | 2 | Read-only |
| `GET /monitor/positions/drift` | 2 | Read-only |
| `GET /monitor/reconciliation` | 2 | Read-only |
| `GET /monitor/alerts` | 2 | Read-only |

### Rule 4 — Human Override

A human operator (Chris) may explicitly override the model tier by stating:
> "Use [model name] for this edit"

The override is recorded in the conversation transcript and expires after the current edit completes.

### Rule 5 — Escalation

If a Tier 2 model is asked to perform a Tier 1 task, it must:
1. Refuse with a clear statement of the policy violation
2. Identify which Tier 1 scope is being violated
3. Recommend escalation to a Tier 1 model

## Policy Violations

| Severity | Example | Consequence |
|---|---|---|
| **Critical** | Tier 2 model edits kill switch logic | Conversation flagged for human review; revert required |
| **High** | Tier 2 model edits order lifecycle | Revert + re-edit with Tier 1; document in guard-events |
| **Medium** | Tier 2 model edits reconciliation logic | Revert + re-edit with Tier 1 |
| **Low** | Tier 2 model edits audit bundle logic without regression test change | Acceptable if reviewed by Tier 1 afterward |

## Current Model Identity

The active model should be declared at the start of any session that involves bridge code edits:

```
Current model: openrouter/deepseek/deepseek-v4-flash
Tier: 1
Safety-critical edits permitted: yes
```

This policy document is itself Tier 2 work (documentation, non-critical).

---

*End of Phase 3R section.*