# Autonomous Cycle Criteria

> **Status:** Chris-approved governance document.  
> **Scope:** Defines when and how Werner/OpenClaw may operate autonomously within the IBKR paper-trading system.  
> **Default state:** Zero autonomy. All orders require Chris's manual approval via H1 token.  
> **Last updated:** 2026-06-15

---

## 1. What Counts as One Autonomous Cycle

An **autonomous cycle** is a complete end-to-end trading workflow executed by Werner/OpenClaw without Chris's real-time intervention for every step. A single cycle includes:

1. **Pre-cycle checks** — verify safety baseline, market state, account state
2. **Candidate analysis** — Hermes advisory input, ranking, thesis generation
3. **Proposal preparation** — produce a Gate-H-compliant proposal file
4. **Preflight validation** — run `/order/preflight` with all providers
5. **Approval request** — present the preflight result and proposal to Chris
6. **Submission** — (if Chris approved) run `/order/submit` with H1 token
7. **Post-cycle monitoring** — poll order status, record evidence, update journal
8. **Cycle closure** — mark cycle complete, update state

**At current autonomy level (0):** Steps 5–6 require Chris's active participation (H1 token). Werner may only execute steps 1–4 and 7–8 autonomously.

---

## 2. Required Pre-Cycle Checks

Before ANY cycle begins (autonomous or manual), Werner must verify:

### 2.1 Safety Baseline
| Check | Required | Failure Action |
|---|---|---|
| `IBKR_ALLOW_ORDERS=false` confirmed | Yes | Abort cycle; notify Chris |
| `rules.enforced=false` confirmed | Yes | Abort cycle; notify Chris |
| `/order` returns 403 | Yes | Abort cycle; notify Chris |
| Bridge is systemd-owned (`User=chris`, `ProtectSystem=strict`) | Yes | Abort cycle |
| No duplicate bridge processes | Yes | Abort cycle |

### 2.2 Market State
| Check | Required | Failure Action |
|---|---|---|
| RTH is open (9:30–16:00 ET) | Advisory | Warn; Chris may override |
| Not in first/last 15 minutes | Advisory | Warn |
| VIX not spiking >30% | Advisory | Warn |
| No symbol-specific halts | Yes | Abort cycle for that symbol |

### 2.3 Account State
| Check | Required | Failure Action |
|---|---|---|
| Net liquidation > 0 | Yes | Abort cycle |
| Daily loss halt not active | Yes (BUY) | SELL close-only still allowed (P2b) |
| Weekly loss halt not active | Yes (BUY) | SELL close-only still allowed (P2b) |
| Daily trade count < 2 | Yes | Abort cycle |
| EUR/USD FX rate plausibility (0.80–1.40) | Yes | Abort cycle |

### 2.4 System Health
| Check | Required | Failure Action |
|---|---|---|
| `ibkr-operator doctor` passes | Yes | Abort cycle |
| Hermes advisory guard policy readable | Yes | Warn; continue |
| Proposal directory writable | Yes | Abort cycle |
| Guard state readable and parseable | Yes | Abort cycle |

---

## 3. Required Proposal Fields

Every proposal file (JSON under `~/.openclaw/proposals/`) must contain ALL of the following. Gate H enforces this automatically — missing fields fail closed.

### 3.1 Common Fields (BUY and SELL)
| Field | Type | Required |
|---|---|---|
| `symbol` | string (uppercase) | Yes |
| `side` | "BUY" or "SELL" | Yes |
| `quantity` | integer > 0 | Yes |
| `reason_to_trade` | string (free text) | Yes |
| `entry_reference` | string (price, level, or "ask" for MKT) | Yes |
| `proposal_id` | string (UUID) | Yes |
| `saved_at_utc` | ISO-8601 timestamp | Yes |

### 3.2 BUY-Specific Fields
| Field | Type | Required |
|---|---|---|
| `stop_loss` | number > 0 | Yes |
| `max_loss` | number > 0 (EUR) | Yes |
| `position_sizing.max_notional_eur` | number > 0 | Yes |
| `position_sizing.max_shares` | integer > 0 | Yes |
| `entry_criteria_met` | array of strings | Yes |
| `hermes_thesis` | string or null | Advisory |
| `hermes_model` | string or null | Required if Hermes contributed |

### 3.3 SELL-Specific Fields
| Field | Type | Required |
|---|---|---|
| `entry_reference` | original portfolio entry price | Yes |
| `reason_to_trade` | exit rationale | Yes |
| `position_sizing` | not required for SELL | No |

---

## 4. Required Approval Evidence

When Chris approves a trade via `/order/approve`, the following evidence must be recorded:

### 4.1 Approval Record (automatic)
- `approval_id` — unique identifier
- `ruled_by` — "Chris"
- `ruling_at_utc` — timestamp of approval
- `decision` — "approve" or "deny"
- `proposal` — full proposal snapshot at time of approval
- `validation` — entry_price, stop_price, stop_distance, final_max_shares, binding_cap

### 4.2 Submission Evidence (automatic, P5)
- Parent order ID and permId
- Stop order ID and permId (for BUY)
- Stop price, quantity
- Transmit flags (parent=False, stop=True)
- `bracket=true`, `protective_stop=true`
- IBKR acknowledgment status

### 4.3 Hermes Attribution (if Hermes contributed)
- Resolved model string
- Thesis text
- Confidence/ranking if provided

---

## 5. Required Post-Cycle Monitoring

After submission (whether the cycle was autonomous or manual), Werner must:

### 5.1 Immediate (<5 minutes)
- Poll order status until terminal (Filled, Cancelled, Inactive)
- Record fill price, fill time, commissions
- Update `trade-journal` with execution details
- Log to `guard-events.jsonl`

### 5.2 End-of-Day
- Run position drift check
- Update guard state (`daily_trade_count`, `last_updated_utc`)
- Generate daily summary:
  - P&L for open positions
  - Day P&L
  - Remaining trade allowance
  - Loss halt status

### 5.3 End-of-Week
- Run weekly reconciliation
- Verify all submitted approvals match IBKR fills
- Check for orphan bracket stops
- Generate weekly report

---

## 6. Hard Stop Conditions Requiring Chris

Werner must abort the current cycle and notify Chris immediately when ANY of the following occurs:

| Condition | Action |
|---|---|
| Any safety baseline check fails (§2.1) | Abort; notify Chris |
| Doctor fails mid-cycle | Abort; notify Chris |
| IBKR Gateway disconnects | Abort; notify Chris |
| Order status is "Rejected" or "Cancelled" | Abort; notify Chris with error |
| Bracket stop placement fails (parent cancelled) | Abort; notify Chris with P5 evidence |
| Guard state becomes unreadable or corrupted | Abort; do NOT attempt repair |
| Any protected file PermissionError (H1 bypass attempt) | Abort; lock down |
| EUR/USD rate outside plausibility range | Abort |
| Daily trade count unexpectedly ≥2 | Abort |
| Unexpected duplicate bridge process detected | Abort; notify Chris |

---

## 7. Maximum Number of Clean Cycles Before Expanding Autonomy

### 7.1 What "Clean Cycle" Means

A cycle is **clean** when ALL of the following are true:

1. All pre-cycle checks pass without warnings
2. Hermes provides a well-formed thesis (not empty, not vague)
3. Proposal passes Gate H on first submission
4. Preflight passes all gates (A–H) with no warnings
5. Chris approves within the approval timeout (5 minutes)
6. Order is acknowledged by IBKR within polling window
7. P5 bracket stop is successfully attached (for BUY)
8. Order fills at or near expected price (±1% of entry reference)
9. No post-cycle alerts, anomalies, or reconciliation gaps
10. Daily/weekly loss halts remain inactive throughout

### 7.2 Autonomy Levels

| Level | Clean Cycles Required | What Changes |
|---|---|---|
| **0 (current)** | N/A | Zero autonomy. Chris must approve and provide H1 token for every submit. |
| **1** | 5 consecutive clean cycles | Werner may prepare and submit proposals to Chris in batch. Chris still approves individually. |
| **2** | 10 consecutive clean cycles (after reaching Level 1) | Werner may pre-approve proposals that pass all gates and are ≤1% of NL notional. Chris reviews post-hoc within 24h. |
| **3** | 20 consecutive clean cycles (after reaching Level 2) | Werner may execute up to 1 trade/day autonomously within tighter limits (≤2% NL notional, ≤1% NL risk). Chris reviews daily. |
| **4+** | Not defined | Requires separate governance review. |

**Hard invariant:** Autonomy Level >0 requires `IBKR_ALLOW_ORDERS=true` and `rules.enforced=true` to be set by Chris. Werner must never enable these autonomously.

### 7.3 Autonomy Downgrade Triggers

Autonomy level drops to 0 immediately when:
- Any trade loses >2R
- A bracket stop is triggered (protective stop hit)
- Daily loss halt activates
- Weekly loss halt activates
- Any hard stop condition (§6) fires
- Chris requests downgrade

---

## 8. Rollback / Relock Process

When Chris issues a relock command or any hard stop condition fires:

### 8.1 Immediate Relock (automatic)
1. Set `IBKR_ALLOW_ORDERS=false` in `.env`
2. Set `rules.enforced=false` in `paper-trading-rules.yaml`
3. Restart bridge via `systemctl restart ibkr-bridge`
4. Verify `/order` returns 403
5. Verify doctor passes
6. Log relock event to guard-events.jsonl

### 8.2 Position Management During Relock
- Existing positions are NOT automatically closed
- P5 bracket stops remain active at IBKR (broker-side)
- Chris may manually close positions via standard approval path
- Werner must flag any position that has breached its stop level

### 8.3 Relock Verification
- Run `ibkr-operator doctor` — must pass
- Run `scripts/run-ci-local` — must pass
- Confirm no orphan bracket stops via IBKR TWS/API
- Confirm bridge process count = 1, owned by chris
- Confirm `ProtectSystem=strict`, `NoNewPrivileges=yes`

---

## 9. Cycle Logging Requirements

Every cycle (autonomous or manual) must produce:

### 9.1 Proposal File
Saved to `~/.openclaw/proposals/<proposal_id>.json`

### 9.2 Guard Events
Logged to `guard-events.jsonl`:
- `preflight_pass` or `preflight_fail`
- `approval_approved` or `approval_denied`
- `order_submitted` (with P5 bracket evidence)
- `order_filled` or `order_failed`
- Any `submit_blocked`, `submit_revalidation_failed`, `order_unconfirmed`

### 9.3 Trade Journal Entry
Logged to `docs/trade-journal/`:
- Symbol, action, quantity, entry price, stop price
- Fill price, fill time
- P&L (realized and unrealized)
- Hermes model (if advisory contributed)
- Notes/learnings

---

## 10. Hard Invariants (Never Weakened)

These invariants are Tier-1 and must never be weakened, bypassed, or worked around by any autonomy level:

1. **Hermes remains advisory-only** — never executes, approves, or submits orders
2. **Werner/OpenClaw may prepare proposals but must not bypass Gate H or H1**
3. **Bridge remains the only broker-action path** — no direct IBKR API calls
4. **`/order` remains 403** — permanently blocked
5. **BUY entries require P5 broker-side protective stops** — fail-closed if stop missing
6. **Close-only SELL exits remain allowed only for reducing/flattening confirmed long positions**
7. **All orders require `/order/preflight` → `/order/approve` → `/order/submit`** — no shortcuts
8. **Default state remains locked** — `IBKR_ALLOW_ORDERS=false`, `rules.enforced=false`
9. **H1 token never stored in app code, CI, or tests** — only SHA-256 hash in `.env`
10. **No raw token reads except the operator boundary (`ibkr-trade-window`, `ibkr_operator.py`)**
