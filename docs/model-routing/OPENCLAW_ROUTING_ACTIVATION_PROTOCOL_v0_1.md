# OpenClaw Routing Adapter Activation Protocol v0.1

**Governance ID:** `openclaw_routing_adapter_v0_1`
**Phase:** 18R2
**Adapter Mode:** SHADOW_ONLY — advisory, no live routing change

---

## 1. Purpose

This protocol defines how the OpenClaw routing adapter transitions from its
current PENDING_INPUT state through manual activation to SHADOW_ROUTE_RESOLVED
operation. The adapter currently resolves transport bindings in shadow mode
without changing any live model routing.

---

## 2. Core Operating Principle

Phase 18R2 shadow mode does not alter live routing:

- **OC requests continue through OpenCode** — the adapter resolves which
  existing OpenCode alias (deepseek-v4-pro or kimi-k3) corresponds to a
  Phase 18R1 logical routing decision, but the OpenCode transport itself
  remains unchanged.
- **GPT/Hermes requests continue through Codex** — the adapter resolves which
  existing Codex alias (gpt-5.5 or gpt-5.6-sol) corresponds to a Phase 18R1
  logical routing decision, but the Codex transport itself remains unchanged.
- **The adapter resolves only which existing alias should be selected.**
  It does not create, configure, or activate any transport or model.

---

## 3. Sanitized Integration Point

Discovered during Phase 18R2 build (no credentials exposed):

| Transport | Discovery Source | Status |
|---|---|---|
| CODEX | `~/.openclaw/agents/main/agent/models.json` — codex provider with alias `gpt-5.5` | gpt-5.5: bound; gpt-5.6-sol: not found |
| OPENCODE | `auth-profiles.json` — `opencode-go:default` profile exists; current model `openrouter/deepseek/deepseek-v4-flash` | deepseek-v4-pro: not found; kimi-k3: not found |

Codex and OpenCode continue to manage their own credentials.
The adapter reads no credentials, copies no credentials, moves no credentials.

---

## 4. Current Binding Status

| Logical Model | Transport | Runtime Alias | Binding State |
|---|---|---|---|
| `gpt-5.5` | CODEX | `gpt-5.5` | BOUND_EXISTING_ALIAS |
| `gpt-5.6-sol` | CODEX | `gpt-5.6-sol` | UNBOUND |
| `deepseek-v4-pro` | OPENCODE | `deepseek-v4-pro` | UNBOUND |
| `kimi-k3` | OPENCODE | `kimi-k3` | UNBOUND |

---

## 5. Activation Gates

### Gate 1: Binding Resolution

All four logical model aliases must be discoverable in their target transports:

- `gpt-5.5` → CODEX: **RESOLVED** (found in codex provider registry)
- `gpt-5.6-sol` → CODEX: **PENDING** (alias not in codex provider)
- `deepseek-v4-pro` → OPENCODE: **PENDING** (alias not found)
- `kimi-k3` → OPENCODE: **PENDING** (alias not found)

### Gate 2: Adapter Shadow Verification

The adapter must correctly resolve all four transport bindings in shadow mode.
Each invocation must:

1. Accept the original routing request and routing decision
2. Validate mutual integrity (hash match, role match, auth flags)
3. Verify cross-transport constraints
4. Resolve or HOLD
5. Produce deterministic adapter hash
6. Never change live routing
7. Never invoke any model

### Gate 3: Manual Operator Review

A human operator must:

1. Review all binding sources against discovery evidence
2. Confirm transport connectivity (by transport, not by adapter)
3. Confirm shadow decisions match expected routes
4. Verify no credentials in governance files
5. Sign the activation approval record
6. Explicitly authorize binding state transition

**Activation requires a separate explicit human-approved step.**
Phase 18R2 cannot activate routing on its own.

### Gate 4: Transport Connectivity

Before live activation (future phase):

1. CODEX transport must be reachable
2. OPENCODE transport must be reachable
3. Each runtime alias must respond to minimal health check
4. Credentials verified by transport layer, not adapter

---

## 6. Post-Activation Requirements

- **Rollback:** Restoring the current pre-Phase-18R2 routing behavior must be
  possible by reverting the binding configuration. No credentials are moved or
  copied, so rollback is a no-credentials operation.
- **Routing self-test:** After activation, a no-prompt/no-model routing
  self-test must be run wherever possible. This self-test must verify that the
  adapter resolves all four paths without invoking any model.
- **CI boundaries:** Live model calls are not part of repository CI. Model
  routing cannot affect trading autonomy or execution authority.
- **Phase 18C gate:** Phase 18C must not begin until manual activation proof
  is either completed or explicitly deferred by the human operator.

---

## 7. Phase 18R2 Explicit Limitations

- **No model invocation** — adapter resolves transport bindings only
- **No live routing change** — `live_routing_changed: false` always
- **No credential access** — adapter reads no API keys or tokens
- **No network access** — adapter performs no HTTP, socket, or subprocess
- **No provider integration** — adapter imports no provider SDKs
- **No direct provider client** — OpenCode and Codex continue to manage their
  own transports, credentials, and client configurations
- **No cross-transport fallback** — gpt models never map to OPENCODE, OC models never map to CODEX
- **No silent substitutions** — models and transports are never silently changed
- **No Phase 18R1 modification** — upstream artifacts are immutable
- **No Phase 18B modification** — upstream artifacts are immutable
- **No STRATEGY.md modification** — canonical strategy unchanged

---

## 8. Next Phase

**PHASE18R2_MANUAL_BINDING_INPUT** — after all four bindings are resolved
and shadow verification is complete. The adapter must demonstrate correct
transport resolution for all four routing paths before manual activation.
