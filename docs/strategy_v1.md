# Strategy v1 — Level 1 Advisory-Only Governance Packet

> **Strategy version:** `v1.0.0`  
> **Version ID:** `strategy-v1-2026-07-09`  
> **Status:** Advisory-only. No order execution. No broker mutation.  
> **Scope:** Level 1 governance baseline. Every future proposal must reference this document.  
> **Created:** 2026-07-09  
> **Last updated:** 2026-07-09

---

## 1. Advisory-Only Boundary

**Hermes and OpenClaw (Werner) are advisory-only.** They may analyze, rank, draft, calculate, and recommend. They must never:

- Enable orders (`IBKR_ALLOW_ORDERS` stays `false`)
- Submit, approve, or place broker orders
- Bypass H1 token authorization
- Mutate guard state, rules, or allowlists without H1
- Write to protected files without H1
- Execute autonomous trading cycles outside Level 1 autonomy criteria
- Generate or possess the H1 token (only SHA-256 hash stored)

**The only path to broker execution is:**
1. Guard-state checks pass (bridge guard)
2. `/order/preflight` validation passes (bridge preflight)
3. Chris provides X-H1-Token via `/order/approve` (bridge approval)
4. `/order/submit` places the order (bridge submit)

No other code path, helper, script, or agent may reach IBKR order placement. The bridge is the single chokepoint.

---

## 2. Allowed Instruments

| Symbol | Type | Sector | Rationale |
|---|---|---|---|
| AAPL | Large-cap stock | Technology | Deep liquidity, tight spreads, validated Phase 1 |
| META | Large-cap stock | Communication | Deep liquidity, tight spreads |
| NVDA | Large-cap stock | Technology | Deep liquidity, high volatility — requires tight stops |
| AMD | Large-cap stock | Technology | Semiconductor sector diversification |

**Adding symbols:** Requires Chris to update the allowlist in `paper-trading-rules.yaml`. Unknown symbols fail closed at preflight (Gate A).

**Allowed instrument types:**
- US equities (NASDAQ, NYSE) — large-cap only (>$10B market cap)
- Non-leveraged, non-inverse US-listed ETFs (advisory-only placeholder; none currently in allowlist)

---

## 3. Excluded Instruments

The following are **hard-blocked** and must never appear in proposals:

| Category | Reason |
|---|---|
| Options | Separate risk model required; out of scope |
| Futures | Out of scope for Phase 1–2 |
| Forex | Out of scope |
| Crypto | Permanently disabled |
| Leveraged ETFs (2×, 3×, −1×, −2×, −3×) | Daily reset decay; unconditional rejection |
| Inverse ETFs | Same as leveraged |
| Penny stocks (<$5/share) | Liquidity and fraud risk |
| Non-US equities | Out of scope |
| Short selling (SELL short) | Unlimited loss asymmetry; long-only mandate |
| US-domiciled ETFs for BUY (H4.1 block) | Structural regulatory/prudence block |

---

## 4. Allowed Session / Window

| Parameter | Value |
|---|---|
| Session | US regular trading hours (RTH) only |
| RTH window | 9:30–16:00 ET |
| Entry blackout (open) | First 15 min (9:30–9:45 ET) — no new entries |
| Entry blackout (close) | Last 15 min (15:45–16:00 ET) — no new entries |
| Pre-market | Not supported |
| After-hours | Not supported |
| Days | Monday–Friday (US market open days only) |

**Rationale:** Avoids opening volatility and closing illiquidity. RTH ensures broker-side bracket stops function correctly.

---

## 5. Signal Inputs

Strategy v1 uses the following signal sources (advisory weight only):

| Signal | Source | Weight | Notes |
|---|---|---|---|
| Trend context | Price vs 20-day SMA | Medium | Above SMA = bullish bias |
| Volume confirmation | Today's volume vs 20-day avg | Medium | Rising volume = conviction |
| Structure / price action | Break of consolidation, pullback to support, flag/pennant | Medium | Pattern recognition (advisory) |
| Relative strength | Symbol vs SPY intraday | Low | Outperformance bias |
| ATR(14) | 14-period Average True Range | High | Used for stop distance and position sizing |
| VIX | CBOE VIX index | Low | Advisory only; spike >30% triggers caution |
| Earnings calendar | Public earnings dates | Advisory | Avoid entry within 48h of earnings |

**Minimum bar for entry:** At least TWO of the first four signals should align. ATR is always required for stop calculation.

---

## 6. Data Quality Requirements

Before any proposal is drafted:

| Requirement | Threshold |
|---|---|
| Bar data freshness | ≤1 trading day stale |
| Quote data | Delayed (paper account) is acceptable for analysis; live preferred for execution |
| ATR calculation | Minimum 14 trading days of bars; ≥10 valid closes |
| SMA calculation | Minimum 20 trading days; ≥15 valid closes |
| Volume data | Must be non-zero for the target session |
| Contract resolution | IBKR contract lookup must succeed (SMART exchange, USD currency) |
| Symbol allowlist | Symbol must appear in `paper-trading-rules.yaml` §9 |
| Market open check | RTH gate must confirm market is open if proposing same-day execution |

**Failsafe:** If any data-quality check fails, the proposal must be marked `data_quality: FAIL` and held for review. No preflight may proceed on a proposal with `data_quality: FAIL`.

---

## 7. No-Trade Conditions

Trading must **NOT** occur when ANY of the following is true:

| Condition | Enforcement | Gate |
|---|---|---|
| `IBKR_ALLOW_ORDERS=false` | Hard block | Bridge |
| `rules.enforced=false` | Hard block | Rules |
| System locked (RTH closed or safety engaged) | Hard block | Bridge |
| Daily loss halt active (portfolio −1% from day start) | Hard block for BUY; SELL exempt | Gate E / P2b |
| Weekly loss halt active (portfolio −3% from week start) | Hard block for BUY; SELL exempt | Gate E / P2b |
| Daily trade count ≥ 2 | Hard block | Gate D |
| IBKR Gateway disconnected | Hard block | Bridge health |
| Major unscheduled news (Fed emergency, geopolitical shock) | Chris judgment | Manual |
| Chris unavailable for manual approval | H1 not provided | Manual |
| VIX spike >30% intraday | Advisory caution | Advisory |
| Earnings within 48h for target symbol | Advisory caution | Advisory |
| Symbol not in allowlist | Hard block | Gate A |

---

## 8. Risk Envelope

| Parameter | Limit | Source |
|---|---|---|
| Maximum notional per position | 5% of Net Liquidation (NL) | `max_position_notional` |
| Maximum risk per trade | 2% of NL | `max_risk_per_trade` |
| Maximum total portfolio exposure | 30% of NL | `max_total_exposure` |
| Minimum cash reserve | 70% of NL | Implied by exposure cap |
| Maximum positions open simultaneously | 2 | Implied by exposure cap + per-position limit |
| Maximum daily loss before halt | 1% of NL (from day start) | Gate E (daily loss halt) |
| Maximum weekly loss before halt | 3% of NL (from week start) | Gate E (weekly loss halt) |

**EUR/USD assumption for NL conversion:** FX rate from IBKR account summary or bridge snapshot.

---

## 9. Maximum Position Sizing Rule

The final share count is the **minimum** of three constraints:

```
notional_cap_shares = floor(5% × NL_EUR × EUR/USD / entry_price)
risk_cap_shares     = floor(2% × NL_EUR × EUR/USD / stop_distance)
allowlist_max       = symbol-specific max shares from rules.yaml
final_shares        = min(notional_cap_shares, risk_cap_shares, allowlist_max)
```

- `stop_distance = entry_price − stop_loss` (for BUY)
- Stop loss is calculated by `calc_stop()` using ATR(14), swing low, 20-day low, and −5% hard cap
- For €1M NL with typical 2×ATR stops (1.8–3.4% distance), the notional cap (5%) is consistently binding
- `final_shares` must be ≥ 1; proposals with `final_shares < 1` are rejected

---

## 10. Maximum Daily Trades Rule

| Limit | Value | Enforcement |
|---|---|---|
| Max trades per day | 2 | Gate D (`max_trades_per_day`) |
| Day trades (round-trip same day) | ≤2 | Same as daily cap |
| Max trades per week | Advisory; 6 (3 days × 2) | Not hard-enforced beyond daily |

**Rationale:** Ultra-conservative in Level 1. Limits overtrading and ensures every decision is deliberate. Stays safely under PDT rules.

---

## 11. Maximum Daily Loss Rule

| Limit | Value | Enforcement |
|---|---|---|
| Daily loss halt trigger | Portfolio −1% from day-start NL | Gate E (hard block for new BUY) |
| Weekly loss halt trigger | Portfolio −3% from week-start NL | Gate E (hard block for new BUY) |
| Loss halt scope | Blocks new BUY entries only | P2b exemption for close-only SELL |

**Close-only exemption (P2b):** During a loss halt, SELL orders that reduce or flatten existing long positions may pass Gate E if quantity ≤ confirmed position size. This allows risk reduction during drawdowns.

---

## 12. Stop / Exit Policy

### 12.1 Initial Protective Stop (Mandatory for Every BUY)

Every BUY entry **must** have a broker-side protective SELL stop (STP order) attached before the parent order goes live:

- **Stop price:** Computed by `calc_stop()` as the **tightest valid level** (max of four candidates):
  - `entry_price − 2 × ATR(14)`
  - Recent swing low (20-period)
  - 20-day low
  - `entry_price × 0.95` (−5% hard floor)
- **Stop quantity:** Must match entry quantity exactly
- **Stop type:** STP (stop order) at IBKR, triggered on last price
- **Broker-side requirement:** Child SELL STP with `parentId=<parent>`, `transmit=True`
- **Fail-closed:** If child stop placement fails for any reason, parent BUY must be cancelled before it fills

### 12.2 Trailing Stop (Voluntary, Post-Entry)

Activates after price exceeds entry by 4%:
- Trail distance = `max(2 × ATR(14), 3% below peak)`
- Manually managed — Chris decides when to activate
- Not automated

### 12.3 Hard Invalidation Triggers

A position must be reviewed for exit when:
- Price closes below the initial stop level (even if not yet triggered intraday)
- Symbol drops out of top 50% of its sector on 5-day RS ranking
- News event contradicts the original thesis
- Position loss exceeds 2R (2× initial risk)
- Position age exceeds 20 trading days without reaching profit target

### 12.4 Profit-Taking (Stocks)

- **Partial:** Close 50% when price reaches entry + 2R (2× initial risk)
- **Remainder:** Switch to trailing stop (see §12.2)
- Rationale: Locks risk-adjusted profit on half; lets remainder run

### 12.5 Close-Only SELL (Exit)

- Must reduce or flatten a confirmed existing long position
- Must not increase or open short exposure
- Quantity ≤ confirmed existing position → may pass Gate E during loss halt (P2b)
- No new bracket stop required for exit orders

---

## 13. Broker-Side Bracket Requirement (for Later Phases)

**For Level 1 (current):** All BUY entries require a broker-side protective SELL stop order (STP) attached at submit time, as described in §12.1. This is a **mandatory requirement** enforced by Gate P5.

**For later phases (Level 2+):** The bracket must expand to include:
- **Take-profit limit order (LMT):** Attached at entry + 2R or entry + 2×ATR(14), whichever is tighter
- **One-Cancels-Other (OCO) group:** Stop loss and take profit as OCO children
- **Bracket validation:** Preflight must verify both child orders exist and are correctly linked before parent transmits

**Current status:** Bracket stop only (STP SELL). OCO bracket with take-profit is a future requirement, not enforced in Level 1. This document records that requirement so proposals are forward-compatible.

---

## 14. Review Checklist

Every proposal must pass this checklist before preflight:

| # | Check | Gate |
|---|---|---|
| 1 | Symbol is in allowlist? | Gate A |
| 2 | Notional ≤ 5% NL? | Gate B |
| 3 | Risk ≤ 2% NL? | Gate C |
| 4 | Daily trade count < 2? | Gate D |
| 5 | No loss halt active (or SELL exempt)? | Gate E / P2b |
| 6 | Proposal file complete and valid? | Gate H |
| 7 | Stop price calculated and valid? | P5 |
| 8 | Stop quantity = entry quantity? | P5 |
| 9 | Market open (RTH window)? | RTH check |
| 10 | IBKR Gateway connected? | Bridge health |
| 11 | Data quality checks passed? | §6 |
| 12 | No earnings within 48h? | Advisory |
| 13 | VIX not spiking >30%? | Advisory |
| 14 | Entry blackout window avoided? | §4 |
| 15 | Long-only — not a short sale? | §3 |
| 16 | Strategy v1 governance document referenced in proposal? | This document |
| 17 | Chris review completed? | Manual |
| 18 | H1 token available? | Manual |

---

## 15. Anti-Overfit Checklist

Before promoting any signal, parameter, or rule change:

| # | Check |
|---|---|
| 1 | Does the change address a specific, observed failure mode (not hypothetical optimization)? |
| 2 | Has the change been tested on out-of-sample data (different time period, different symbols)? |
| 3 | Does the change generalize across at least 2 of the 4 allowed symbols? |
| 4 | Does the change survive walk-forward testing (train on period A, test on period B)? |
| 5 | Is the change simple enough to explain in one sentence? |
| 6 | Does the change increase or decrease the total number of parameters? (Prefer fewer) |
| 7 | Has the Sharpe / max-drawdown ratio improved on out-of-sample data? |
| 8 | Has the change been reviewed against the "would this have prevented a past loss?" test? |
| 9 | Is the change documented in the strategy governance changelog with date and rationale? |
| 10 | Does the change preserve the advisory-only boundary (no autonomous execution)? |

**Failsafe:** If ≥3 anti-overfit checks fail, the change stays at "proposal" status and must not be promoted to the active strategy. Strategy parameter changes require a new strategy version (v1.1, v1.2, etc.).

---

## 16. Model / Versioning Discipline

| Rule | Description |
|---|---|
| Version format | `v<MAJOR>.<MINOR>.<PATCH>` (semantic versioning) |
| MAJOR bump | Governance boundary change (e.g., new asset class, autonomy level change) |
| MINOR bump | New signal, parameter change, new symbol added |
| PATCH bump | Clarification, typo fix, documentation improvement |
| Version tag in proposals | Every proposal must reference `strategy_version: "v1.0.0"` |
| Changelog | All version changes documented in `docs/strategy_v1_changelog.md` |
| Rollback | Previous version remains in git history; revert by tag |
| Review gate | MINOR+ bumps require Chris review before proposals can reference the new version |

**Current version:** `v1.0.0` (this document). No prior versions exist.

---

## 17. Evidence Required for Every Future Proposal

Every proposal file (`~/.openclaw/proposals/<id>.json`) must include:

| Field | Description |
|---|---|
| `strategy_version` | `"v1.0.0"` |
| `strategy_doc_ref` | `"docs/strategy_v1.md"` |
| `symbol` | From allowlist |
| `side` | `"BUY"` or `"SELL"` (close-only) |
| `quantity` | Computed by sizing rule (§9) |
| `reason_to_trade` | Free-text thesis |
| `entry_reference` | Price or level |
| `stop_loss` | Computed by `calc_stop()` |
| `max_loss_eur` | `quantity × (entry_price − stop_loss) × EUR/USD` |
| `position_sizing` | `{max_notional_eur, max_shares, sizing_method: "strategy-v1-§9"}` |
| `signals` | Which of the 7 signals aligned (§5) |
| `data_quality` | `"PASS"` or `"FAIL"` with details |
| `review_checklist` | §14 checklist with per-item pass/fail |
| `anti_overfit_check` | `"N/A"` for proposals or §15 checklist for strategy changes |
| `saved_at_utc` | ISO-8601 timestamp |
| `proposed_by` | `"Hermes"` or `"Chris"` |
| `model` | Resolved model string if proposed by Hermes |

---

## 18. Explicit Boundary Statements

### 18.1 Advisory-Only

> **Hermes and OpenClaw (Werner) are advisory-only agents.** They do not enable orders, submit orders, approve orders, bypass H1 authorization, mutate guard state, mutate rules, or execute any broker operation. Their output is analysis, drafts, and recommendations for Chris to review.

### 18.2 Broker Execution Path

> **The only path to IBKR broker execution is the bridge guard → preflight → approve → submit chain.** No other code path, helper script, agent, or tool may place, modify, or cancel broker orders. Every order must pass guard-state checks, preflight validation, Chris's H1-approved authorization, and submit confirmation through the bridge. Shortcuts, workarounds, and direct API calls are forbidden.

### 18.3 Default Safe State

| Setting | Value |
|---|---|
| `IBKR_ALLOW_ORDERS` | `false` |
| `rules.enforced` | `false` |
| `/order` endpoint | 403 (permanent) |
| Bridge mode | Read-only with order-disabled safety flags |
| System locked | true (RTH closed or safety engaged) |

**This is the safe baseline.** Enabling orders requires Chris to explicitly set both `IBKR_ALLOW_ORDERS=true` and `rules.enforced=true`, and provide the X-H1-Token for every approve+submit pair. Re-locking restores the safe baseline immediately.

---

## Document Metadata

| Field | Value |
|---|---|
| Strategy version | `v1.0.0` |
| Version ID | `strategy-v1-2026-07-09` |
| Governance level | Level 1 (advisory-only) |
| Supersedes | `docs/STRATEGY.md` (pre-governance baseline) |
| Changelog | `docs/strategy_v1_changelog.md` |
| Review cadence | Every 30 days or after any trade |
| Next review due | 2026-08-08 |
