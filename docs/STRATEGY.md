# IBKR Paper-Trading Strategy

> **Status:** Chris-approved baseline for Phase 1–2 paper trading.  
> **Scope:** Strategy definition only. No order execution. No broker mutation.  
> **Default state:** All orders disabled (`IBKR_ALLOW_ORDERS=false`, `rules.enforced=false`).  
> **Last updated:** 2026-06-15

---

## 1. Allowed Market Universe

| Market | Status |
|---|---|
| US equities (NASDAQ, NYSE) | Allowed |
| US-listed ETFs (non-leveraged, non-inverse) | Allowed |
| Non-US equities | Not allowed |
| Options | Not allowed |
| Futures | Not allowed |
| Forex | Not allowed |
| Crypto | Not allowed |
| Leveraged / inverse ETFs | Hard-blocked |
| Penny stocks (<$5) | Not allowed |

**Rationale:** Phase 1–2 paper trading is equity-only. Options, futures, forex, and crypto require separate risk models and are out of scope. Leveraged/inverse ETFs have daily reset decay and are unconditionally rejected.

---

## 2. Allowed Instruments

**Explicit symbol allowlist** (from `paper-trading-rules.yaml` §9):

| Symbol | Type | Rationale |
|---|---|---|
| AAPL | Large-cap stock | Deep liquidity, tight spreads, validated in Phase 1 |
| META | Large-cap stock | Deep liquidity, tight spreads |
| NVDA | Large-cap stock | Deep liquidity, high volatility — requires tight stops |
| AMD | Large-cap stock | Semiconductor sector diversification |

**Adding new symbols:** Requires Chris to update the allowlist in `paper-trading-rules.yaml`. No symbol is tradeable until explicitly added. Gate A (allowlist) enforces this automatically — unknown symbols fail closed at preflight.

**US-domiciled ETF block (H4.1):** Structural rejection of US-domiciled ETFs for BUY entries as long as the block is configured. This is a regulatory/prudence gate, not a strategy decision.

---

## 3. Long-Only Rule

| Direction | Allowed? |
|---|---|
| Long (BUY) | Yes — with P5 bracket stop |
| Short (SELL short) | **Never allowed** |
| Close-only SELL (exit long) | Yes — no new short exposure |

**Rationale:** Paper trading is long-only. Short selling requires margin, borrow costs, and asymmetric risk (unlimited losses). Out of scope for Phase 1–2. The bridge enforces this: action must be "BUY" or "SELL" (close-only).

---

## 4. Setup Criteria

A valid trade setup requires ALL of the following before a preflight is run:

### 4.1 Proposal Required (Gate H)
Every trade requires a persisted proposal file under `~/.openclaw/proposals/` containing:
- `symbol`, `side` (BUY/SELL), `quantity`
- `reason_to_trade` (free-text thesis)
- `entry_reference` (price or level)
- `stop_loss` (price)
- `max_loss` (EUR)
- `position_sizing` (object with `max_notional_eur`, `max_shares`)
- `saved_at_utc`
- For SELL: `entry_reference` may be the portfolio entry price

Gate H fails closed when the proposal is missing, incomplete, or malformed.

### 4.2 Market Conditions (advisory)
- No major earnings in the next 48h for the target symbol (advisory, not hard-blocked)
- VIX not spiking >30% intraday (advisory)
- Symbol is not halted or in a trading pause

### 4.3 Time-of-Day Restrictions
- No entries in the first 15 minutes of US regular trading hours (9:30–9:45 ET)
- No entries in the last 15 minutes (15:45–16:00 ET)
- Pre-market and after-hours not supported

---

## 5. Entry Criteria

### 5.1 Technical Entry (for BUY)
At least TWO of the following conditions should be present (advisory; Hermes may weigh):
1. **Trend context:** Price above 20-day SMA (or 50-day for ETFs)
2. **Volume confirmation:** Today's volume > 20-day average volume (or rising)
3. **Structure:** Break of a consolidation range, pullback to support, or flag/pennant continuation
4. **Relative strength:** Symbol outperforming SPY on the day

### 5.2 Order Type
- BUY entries: **MKT** (immediate execution) or **LMT** (price-controlled)
- All BUY entries require a **P5 broker-side protective stop** attached at submit time
- LMT orders that don't fill within 5 minutes should be cancelled (advisory; not automated)

### 5.3 Entry Sizing (binding)
The final share count is computed by Gate B (notional) and Gate C (risk):

```
notional_cap_shares = floor(5% × NL_EUR × EUR/USD / entry_price)
risk_cap_shares = floor(2% × NL_EUR × EUR/USD / stop_distance)
final_shares = min(notional_cap_shares, risk_cap_shares)
```

For €1M equity with typical 2×ATR stops (1.8–3.4% distance), the notional cap (5%) is consistently binding.

---

## 6. Invalidation / Stop Criteria

### 6.1 Initial Protective Stop (P5 — mandatory for every BUY)
Every BUY entry must have a broker-side protective SELL stop attached before the parent order goes live:

- **Stop price:** Computed by `calc_stop()` as the max of four candidates (tightest valid level):
  - `entry_price - 2 × ATR(14)`
  - Recent swing low
  - 20-day low
  - `entry_price × 0.95` (−5% hard cap)
- **Stop quantity:** Must match entry quantity exactly
- **Stop type:** STP (stop order) at IBKR, triggered on last price
- **Broker-side:** Child SELL STP with `parentId=<parent>`, `transmit=True`
- **Fail-closed:** If child stop placement fails, parent BUY is cancelled

### 6.2 Trailing Stop (voluntary, post-entry)
Activates after price exceeds entry by 4%:
- Trail distance = max(2 × ATR(14), 3% below peak)
- Manually managed — not automated. Chris decides when to activate.

### 6.3 Hard Invalidation
A position must be reviewed for exit when:
- Price closes below the initial stop level (even if stop not yet triggered intraday)
- Symbol drops out of the top 50% of its sector on a 5-day RS ranking
- News event contradicts the original thesis
- Position loss exceeds 2R (2× initial risk)

---

## 7. Profit-Taking / Exit Criteria

### 7.1 Stocks (AAPL, META, NVDA, AMD)
- **Partial:** Close 50% when price reaches entry + 2R (2× initial risk)
- **Remainder:** Switch to trailing stop (see §6.2)
- **Rationale:** Locks risk-adjusted profit on half; lets remainder run

### 7.2 ETFs (not currently in allowlist; placeholder)
- Trailing stop preferred; forced take-profit optional
- Rationale: ETFs trend; forced exits often leave money on the table

### 7.3 Close-Only SELL (Exit)
- Must reduce or flatten a confirmed existing long position
- Must not increase or open short exposure
- Quantity ≤ confirmed existing position → may pass Gate E even during loss halt (P2b exemption)
- No new bracket stop required for exit orders

---

## 8. Position Sizing Assumptions

| Parameter | Value | Source |
|---|---|---|
| Max notional per position | 5% of NL | `max_position_notional` |
| Max risk per trade | 2% of NL | `max_risk_per_trade` |
| Max total exposure | 30% of NL | `max_total_exposure` |
| Cash reserve | ≥70% of NL | Implied by exposure cap |
| Notional cap binding for €1M | ~50–160 shares | Validated on AAPL/SPY/QQQ |

---

## 9. Maximum Daily / Weekly Trade Frequency

| Limit | Value | Enforcement |
|---|---|---|
| Max trades per day | 2 | Gate D (`max_trades_per_day`) |
| Max trades per week | Advisory; 6 (3 days × 2) | Not hard-enforced beyond daily |
| Day trades (round-trip) | ≤2 | Same as daily cap |

**Rationale:** Ultra-conservative in Phase 1–2. Limits overtrading and ensures every decision is deliberate. Stays safely under PDT rules.

---

## 10. No-Trade Conditions

Trading must NOT occur when ANY of the following is true:

| Condition | Enforcement |
|---|---|
| `IBKR_ALLOW_ORDERS=false` | Bridge gate (hard block) |
| `rules.enforced=false` | Rules gate (hard block) |
| Daily loss halt active (portfolio down −1% from day start) | Gate E (hard block for BUY; SELL exempt via P2b) |
| Weekly loss halt active (portfolio down −3% from week start) | Gate E (hard block for BUY; SELL exempt via P2b) |
| Daily trade count ≥ 2 | Gate D (hard block) |
| IBKR Gateway disconnected | Bridge health check |
| RTH closed (outside 9:30–16:00 ET) | RTH check |
| Major unscheduled news (e.g., Fed emergency, geopolitical shock) | Chris judgment (not automated) |
| Chris unavailable for manual approval | H1 token not provided |

---

## 11. Hermes Advisory Usage

Hermes is **advisory-only**. It may:
- Analyze market data (read-only)
- Rank candidates
- Produce trade theses
- Calculate risk metrics
- Generate proposal drafts (for Chris review)

Hermes must **never**:
- Enable, submit, or approve orders
- Mutate guard state, rules, or allowlists
- Bypass Gate H (proposal discipline)
- Bypass Gate E (loss halts) or P2b (close-only exemption)
- Write to protected files without H1 authorization
- Masquerade as Werner in the audit trail

All Hermes artifacts must record the resolved model string. Tests must assert the recorded model is not Werner's model family (P6).

---

## 12. Werner / OpenClaw Boundaries

### Werner / OpenClaw MAY:
- Run read-only market data checks (quotes, bars, account, positions)
- Execute `ibkr-operator doctor` and `ibkr-operator heartbeat`
- Run preflight validation (read-only; never places orders)
- Prepare proposal drafts for Chris
- Analyze guard events, reconciliation, and position drift
- Run `scripts/run-ci-local` and targeted test suites
- Respond to direct operator/admin/status questions from Chris

### Werner / OpenClaw MUST NOT:
- Enable orders (`IBKR_ALLOW_ORDERS` stays `false`)
- Bypass H1 token authorization
- Approve or submit orders without Chris's X-H1-Token
- Modify `paper-trading-rules.yaml` or guard state without H1 authorization
- Write to protected files directly
- Generate or possess the H1 token (only the SHA-256 hash is stored)
- Execute "autonomous cycles" outside defined autonomy criteria

---

## 13. Default State

| Setting | Value |
|---|---|
| `IBKR_ALLOW_ORDERS` | `false` |
| `rules.enforced` | `false` |
| `/order` endpoint | 403 (permanent) |
| Bridge mode | Read-only with order-disabled safety flags |
| Approval path | `/order/preflight` → `/order/approve` → `/order/submit` |
| Approval authority | Chris only (X-H1-Token) |

**This is the safe baseline.** Enabling orders requires Chris to explicitly set both `IBKR_ALLOW_ORDERS=true` and `rules.enforced=true`, and provide the X-H1-Token for every approve+submit pair. Re-locking restores the safe baseline immediately.
