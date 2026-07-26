# Strategy v1.1 Proposal v0.2 — Breadth, Regime Gating, and Volatility Targeting

> **Proposal ID:** `strategy_v1_1_proposal_v0_2`
> **Proposal Version:** `0.2`
> **Proposal Status:** `PROPOSED`
> **Strategy Readiness:** `S0`
> **Autonomy Level:** `1`
> **Execution Scope:** `NONE`
> **Permitted Activity:** `DOCUMENTATION_AND_DESIGN_ONLY`
> **Phase:** `PHASE19A_STRATEGY_V1_1_SPECIFICATION_REVISION`
> **Phase 19A Status:** `COMPLETE`
> **Final Recommendation:** `APPROVE_FOR_DESIGN_REVIEW_ONLY`
> **Target Strategy Version:** `v1.1.0` (not yet active)
> **Canonical Strategy Reference:** `docs/strategy_v1.md` (v1.0.0 — remains active, unchanged)
> **Supersedes:** `STRATEGY_V1_1_PROPOSAL_v0_1` (SHA-256: `0ec59eacb9bffb32eb8593cbe0c1f59e8f7d5790dfff4dcf088bc959f22f400d`)
> **Created:** 2026-07-25
> **Last Updated:** 2026-07-26

## v0.2 Revision Summary

This is a **substantive specification revision** produced under Phase 19A governance.
The following ten corrections were applied to the v0.1 proposal:

1. **Position count** (§1.1, §1.2, §6, §6.1): Removed the claim that 30% ÷ 5% = 6
   concurrent positions. Replaced with an explicit `max_concurrent_positions: 6`
   candidate control requiring human approval. Acknowledged that smaller positions
   could exceed six while remaining below the 30% ceiling.
2. **Deterministic signal contract** (§4.3): Replaced subjective/discretionary signal
   language ("constructive pullback", "flag", "structure looks positive", "intraday
   relative strength") with exact machine-testable rules on completed daily bars.
   All four alignment signals defined formulaically. Discretionary phrases retained
   only as explicitly labeled human commentary with no eligibility effect.
3. **Cross-sectional ranking** (§4.3.1): Defined 60-session return formula exactly.
   Added deterministic tie-breaker (ascending ticker). Added explicit minimum
   valid-universe threshold. Incomplete universe produces NO_TRADE.
4. **SPY regime data contract** (§4.5): Changed "12-month total return" to
   "252-session price return". Explicitly labeled PRICE RETURN, not total return.
   Required ≥253 valid completed SPY sessions.
5. **Volatility targeting** (§4.6): Added exact failure handling for insufficient
   data, non-positive prices, non-finite values, zero volatility, and stale series.
   Effective budget above ceiling or below zero raises fail-closed error.
6. **Risk bucket terminology** (§4.7, §6, §9): Replaced "sector" with "risk_bucket"
   throughout. Semiconductor separation from IT is a deliberate risk-control grouping,
   not a canonical GICS sector claim.
7. **Deployment order** (§9): Replaced the YAML-first sequence with phases 19A–19H.
   The live `paper-trading-rules.yaml` is edited last (19H), after all implementation,
   testing, and human approval.
8. **Backtest and data integrity** (§8): Added point-in-time, no-future-leakage,
   freeze-universe, delisting, synchronized as-of date, and variant-recording
   requirements.
9. **Output contract** (§4.10): Separated deterministic machine fields from LLM
   commentary. LLM output restricted to `{rank, thesis, invalidation_condition}`
   and must never emit sizing, leverage, or order parameters.
10. **Status and promotion** (§11, §14): Confirmed MSTR/BTC at PROPOSED/S0/NONE.
    Final recommendation: `APPROVE_FOR_DESIGN_REVIEW_ONLY`. Implementation blocked
    until all open decisions resolved, deterministic schemas exist, tests pass,
    OOS/walk-forward evidence exists, invariants re-verified, and human activation
    recorded.

No strategy content was implemented. No code, YAML, configuration, or runtime was
modified.

---

## 0. Reading Order and Authority

This document is a **proposal**. It does not activate anything, does not modify
`paper-trading-rules.yaml`, and does not change `guard.py`. Per CLAUDE.md invariant 6,
Werner never edits `.env` or the rules YAML — every change described in §9 is applied by
Chris, or by a Chris-approved Tier-1 edit.

| Authority | Document | Status |
|---|---|---|
| Active strategy | `docs/strategy_v1.md` (v1.0.0) | **Unchanged by this proposal** |
| Execution authority | `~/.openclaw/risk-rules/paper-trading-rules.yaml` | **Sole allowlist authority** |
| Safety invariants | `CLAUDE.md` §3 | **Untouched** |
| This document | `STRATEGY_V1_1_PROPOSAL_v0_2.md` | `PROPOSED` — advisory design only; Phase 19A complete; supersedes v0_1 |

**Data provenance note:** volatility and correlation figures in this document are
**long-run reference estimates**, not freshly computed values. The FMP historical-chart
endpoints are gated on the current account plan, so no live series was pulled. Every
number marked *(reference)* must be recalibrated from `market/bars` via the bridge before
promotion — IBKR is ground truth per CLAUDE.md §8.

---

## 1. Diagnosis of Strategy v1.0.0

Strategy v1.0.0 is **governance-strong and strategy-thin**. The safety architecture
(H1 token boundary, triple kill switches, single-chokepoint bridge, fail-closed Gate A) is
substantially better than typical retail practice. The strategy content is not.

| Dimension | v1.0.0 state | Assessment |
|---|---|---|
| Safety / governance | H1-enforced, triple-switch, fail-closed | **Strong** |
| Universe breadth | 4 names, all US mega-cap tech | **Weak — ~1 independent bet** |
| Signal specification | "2 of 4 signals align" (discretionary) | **Underspecified** |
| Regime awareness | None at portfolio level | **Missing** |
| Portfolio vol control | Per-position ATR only | **Partial** |
| Evidence of edge | None recorded | **Absent** |

### 1.1 The breadth problem

`docs/strategy_v1.md` §2 defines the allowlist as **AAPL, META, NVDA, AMD**. All four are
US mega-cap technology or semiconductor names with high pairwise correlation
(~0.5–0.75 *(reference)*). Under the Fundamental Law of Active Management:

```
IR ≈ IC × √BR
```

where `BR` counts **independent** bets, not tickers. Four names inside one factor is
approximately **1.3 independent bets**. The strategy is, in effect, a single leveraged
long-tech position expressed four ways.

| Universe change | Tickers | Approx. independent bets | Relative IR |
|---|---|---|---|
| v1.0.0 today | 4 | ~1.3 | 1.00× |
| +6 more tech names | 10 | ~1.8 | ~1.18× |
| +6 names across new sectors | 10 | ~4.2 | ~1.80× |
| **v1.1 proposal (22 / 10 sectors)** | **22** | **~6.5** | **~2.24×** |

The dominant lever is **decorrelation, not ticker count**. This is the single
highest-value change available, requires no new data infrastructure, and is a YAML edit.

### 1.2 Contradiction in the current risk envelope

`docs/strategy_v1.md` §8 states:

> Maximum positions open simultaneously — **2** — *Implied by exposure cap + per-position limit*

The arithmetic does not support this. With `max_position_notional = 5%` and
`max_total_exposure = 30%`:

```
30% ÷ 5% = 6 fully sized 5%-notional positions
```

- **Maximum fully sized 5%-notional positions: 6.**
- **Maximum concurrent positions: not currently enforced** by the 30% exposure ceiling
  and 5% position-size ceiling alone.
- **Smaller positions could allow more than six concurrent positions** while remaining
  below the 30% exposure ceiling.

The "2" in the governing document appears to be a conflation with `max_trades_per_day = 2` (Gate D,
`guard.py:1348`), which is a different constraint entirely. `guard.py` does not
enforce a position count directly — `gate_exposure` (`guard.py:1466`) enforces the
30% notional ceiling, and `gate_notional` (`guard.py:1314`) enforces 5% per symbol.

**v0.2 proposes an explicit hard operational cap:**

```yaml
max_concurrent_positions:
  value: 6
```

Six is a proposed ceiling requiring explicit human approval. It is **not** a
derived consequence of Gate F — it is a separate candidate control. The cap must
apply only to new BUY exposure. SELL and close-only actions must remain exempt.
A new gate (proposed Gate I in §9.4) would enforce this independent of the exposure
ceiling.

### 1.3 The H4.1 ETF block forecloses an entire strategy family

`docs/strategy_v1.md` §3 hard-blocks **"US-domiciled ETFs for BUY (H4.1 block)"**, while §2
lists "Non-leveraged, non-inverse US-listed ETFs" as an allowed *placeholder* type with
none in the allowlist. These two clauses are in tension, and §3 is the operative block.

Consequence: **no index-level strategy is expressible.** Vol-targeted index trend
following, risk-parity sleeves, and any SPY/QQQ core are all unimplementable as BUY orders.
Everything must be single-name. This is a legitimate choice, but it should be a *deliberate*
one rather than an artifact — it removes the best-evidenced, lowest-complexity strategy
family from consideration.

v1.1 is designed to work **entirely within the H4.1 block** (single-name only), and treats
SPY as a **read-only regime reference** (bars only, never an order). See §4.5.

---

## 2. Design Principles for v1.1

1. **The advisory layer may only tighten, never loosen.** Every mechanism introduced here
   reduces exposure below the YAML ceiling. None can raise it. This preserves the
   two-tier risk model (CLAUDE.md §5) and the H2 single-source-of-truth property.
2. **Sizing stays deterministic and stays in `guard.py`.** Hermes never emits a size, a
   leverage figure, or a confidence multiplier.
3. **Prefer fewer parameters.** Every new parameter must survive `strategy_v1.md` §15
   anti-overfit check 6.
4. **Conventional parameter values only.** 200-day SMA, 12-month momentum, ATR(14) — no
   fitted values, no optimization over the backtest.
5. **Breadth through decorrelation.** Add bets, not tickers.
6. **No new instrument classes.** No leverage, no options, no futures, no crypto, no ETFs
   for BUY, no shorting.

---

## 3. Leverage Policy — Explicit Rejection

v1.1 formally rejects leverage in all forms, including instrument-embedded leverage. This
section exists so the question is settled by arithmetic rather than re-litigated by
preference.

For an asset with excess drift `μ` and volatility `σ`, continuously rebalanced leverage `L`
compounds at:

```
g(L) = L·μ − (L²·σ²) / 2
```

Growth is **quadratic-negative** in `L`. Two thresholds follow:

```
L*  = μ / σ²        →  growth-maximizing (full Kelly)
L₀  = 2μ / σ² = 2L* →  expected compound growth crosses ZERO
```

Using NDX-like reference values (`μ ≈ 8%` excess, `σ ≈ 23%` *(reference)*):

| Leverage | Expected compound growth |
|---|---|
| 1.0× | +5.4% / yr |
| **1.5× (Kelly-optimal)** | **+6.0% / yr — the maximum** |
| 3.0× (zero-growth point) | ~0% |
| 5.0× | −26% / yr |
| 20× | −898% / yr → ruin, p ≈ 1 |

**Above ~3× on a single equity index, expected compound return is negative even with a
real edge and the full historical bull-market drift.** No signal quality repairs this;
`σ²` is in the denominator and dominates. Full Kelly also implies ~50% drawdowns, so
practical sizing is half-Kelly: **≈0.75× on an NDX-like asset.**

### 3.1 No viable stop distance exists at high leverage

A stop must sit *above* market noise (or microstructure churns it out) and *below* ruin (or
it is decorative). At high leverage that window closes:

| Leverage | Ruin distance | In daily σ (~1.4% *(reference)*) | Viable? |
|---|---|---|---|
| 2× | −50% | ~35σ | Yes |
| 5× | −20% | ~14σ | Marginal |
| 20× | −5% | **~3.5σ** | **No** |

3.5σ daily moves occur routinely. Note also that the v1 hard stop floor is
`entry × 0.95` (−5%) — at 20× leverage that stop **is** −100% of equity. "20× with the
current stop rules" is arithmetically identical to "bet the entire account on every trade."
Margin call arrives well before −5%, and stops do not survive overnight gaps at all.

### 3.2 Instrument-embedded leverage is also rejected

20× on an equity index is not reachable through the permitted universe in any case:
Reg T gives 2× overnight / 4× intraday; portfolio margin ~6.7×. Reaching 20× requires
NQ/MNQ futures or CFDs — both blocked by CLAUDE.md invariant 8 and `strategy_v1.md` §3.
Leveraged ETFs are separately hard-blocked and demonstrate the decay directly:
QQQ ≈ −33% in 2022 against TQQQ ≈ −80% *(reference)*.

### 3.3 The confidence-scaling fallacy

A design of the form *"leverage 1–20 depending on how secure the setup appears"* places the
**least reliable estimate** in the **most dangerous multiplier**:

| Quantity | Approximate daily predictability |
|---|---|
| Direction of return | R² ≈ 0–2% |
| Magnitude of volatility | R² ≈ 40–60% |

Volatility is strongly autocorrelated and forecastable; direction is barely forecastable.
Therefore **scale by measured risk, never by conviction.** LLM-reported confidence is
additionally uncalibrated and upward-biased — it tracks narrative fluency, not accuracy.
Multiplying position size by a model-reported confidence score is the single worst
available use of that model's output.

**v1.1 rule:** Hermes emits `{rank, thesis, invalidation_condition}` and never a size,
weight, leverage figure, or confidence multiplier.

---

## 4. Strategy v1.1 Design

### 4.1 Where edge is claimed to come from

v1.1 makes a deliberately modest claim. It does **not** claim directional forecasting
skill. It claims three things with independent empirical support:

| Source | Mechanism | Evidence class |
|---|---|---|
| Risk control | Cutting gross exposure when volatility spikes; vol clusters and clusters coincide with negative returns | Strong, cross-market |
| Time-series momentum | Absolute trend filter on the market reference | Strong, century-scale, cross-market (Hurst/Ooi/Pedersen) |
| Cross-sectional momentum | Relative-strength ranking within the universe | Strong, cross-market |
| Breadth | More independent bets at the same per-bet IC | Arithmetic (`IR ≈ IC√BR`) |

Cost and execution discipline is the fourth contributor and the only *guaranteed* one.

### 4.2 Proposed universe — 22 names across 10 sectors

Selection criteria: US-listed, large-cap (>$10B), non-penny, deep liquidity and tight
spreads, no ETFs, no ADRs, no leveraged/inverse products. The four v1.0.0 names are
retained.

| Risk Bucket | Symbols | Count |
|---|---|---|
| Information Technology | AAPL, MSFT, AVGO | 3 |
| Semiconductors | NVDA, AMD | 2 |
| Communication Services | META, GOOGL | 2 |
| Health Care | LLY, UNH, JNJ | 3 |
| Consumer Staples | PG, KO | 2 |
| Consumer Discretionary | AMZN, HD | 2 |
| Financials | JPM, BAC | 2 |
| Energy | XOM, CVX | 2 |
| Industrials | CAT, UNP | 2 |
| Utilities | NEE, DUK | 2 |
| **Total** | | **22** |

Technology-adjacent names remain 7 of 22 by count. That residual concentration is handled
by the sector cap in §4.7, not by trimming the list — the names are individually the most
liquid instruments available and are worth keeping *available* even when not
simultaneously holdable.

**This table is informative only.** Per CLAUDE.md §5 and Phase H2, the YAML
`symbol_allowlist.allow` is the sole execution authority; `gate_allowlist`
(`guard.py:1305`) fails closed on anything absent from it.

### 4.3 Signal layer — deterministic contract

All signals use **completed daily bars only**. No incomplete or partially formed bar may
be used. All input series must share the same latest completed US trading session.
Missing, stale, inconsistent, or insufficient data must result in `NO_TRADE`.

ATR(14) is **required** for every candidate. Refer to the canonical ATR implementation
in `guard.py:calc_stop` (`guard.py:1016`). Invalid or unavailable ATR must produce
`NO_TRADE`. No fallback or default ATR value is permitted.

#### 4.3.1 Four alignment signals — exact definitions

All four signals are evaluated on completed daily bars. `t` denotes the latest
completed US trading session. `C[t]` is the closing price for session `t`.
`V[t]` is the session volume.

**1. TREND_20:**

```
C[t] > mean(C[t-19] through C[t])
```

The closing price of the latest completed session exceeds the 20-session simple
moving average of closes, inclusive of the current session.

**2. VOLUME_20:**

```
V[t] > mean(V[t-20] through V[t-1])
```

The volume of the latest completed session exceeds the 20-session simple moving
average of the preceding 20 volumes (sessions t−20 through t−1, exclusive of t).

**3. BREAKOUT_20:**

```
C[t] > max(C[t-20] through C[t-1])
```

The closing price of the latest completed session exceeds the highest close among
the preceding 20 sessions (sessions t−20 through t−1, exclusive of t).

**4. RELATIVE_STRENGTH_20:**

```
symbol_return_20 = C_symbol[t] / C_symbol[t-20] − 1
spy_return_20     = C_SPY[t] / C_SPY[t-20] − 1

Signal is true when: symbol_return_20 > spy_return_20
```

The candidate symbol's 20-session price return exceeds SPY's 20-session price
return over the same completed sessions.

**Entry requirement (v1.1, corrected):**

1. At least **two of the four** alignment signals above are true, **and**
2. ATR(14) is available and valid (invalid ATR → `NO_TRADE`), **and**
3. Candidate ranks in the **top 50%** of the cross-sectional ranking (§4.3.2), **and**
4. Portfolio regime state is not `RISK_OFF` (§4.5), **and**
5. Risk-bucket cap is not breached (§4.7), **and**
6. `max_concurrent_positions` cap is not breached (§6).

#### 4.3.2 Discretionary phrases — explicitly non-operational

The following phrases appeared in v0.1 as informal signal descriptions. They are
retained here as **human commentary only** with no effect on eligibility:

- "constructive pullback"
- "flag"
- "structure looks positive"
- "intraday relative strength"

These are subjective assessments that do not enter the deterministic signal
contract. No automated system may interpret them as eligibility criteria.

#### 4.3.3 Additional retained signals

| Signal | Source | Role in v1.1 |
|---|---|---|
| VIX | CBOE VIX | Retained (advisory) |
| Earnings calendar | Public dates | Retained (advisory, 48h avoidance) |

Parameter count added: **one** (60-session RS lookback) plus the four signal
formulas which use the existing 20-session lookback. All values are conventional,
not fitted.

#### 4.3.4 Cross-sectional ranking — exact definition

The 60-session cross-sectional return is defined exactly as:

```
return_60 = C[t] / C[t-60] − 1
```

Only symbols meeting **all** of the following may participate in the ranking:

- Same as-of session `t` as all other candidates.
- Sufficient completed bars: ≥61 valid daily closes (sessions t−60 through t).
- All prices strictly positive.
- No stale data (latest bar must match the most recent completed session).

**Deterministic ordering:**

1. Primary: descending 60-session return.
2. Tie-breaker: ascending ticker symbol (lexicographic, case-sensitive).

**Eligibility threshold:**

```
eligible_count = ceil(valid_universe_size × 0.50)
```

The first `eligible_count` symbols in the ordered list are rank-eligible.

**Minimum valid-universe threshold:** at least **8 symbols** must have valid data
for the ranking cycle to proceed. This is the number of distinct risk buckets in
the proposed universe (§4.2) — a ranking over fewer than one symbol per risk bucket
is not a meaningful cross-sectional signal. If `valid_universe_size < 8`, the
outcome is `NO_TRADE` for the entire ranking cycle. Do not silently rank an
incomplete universe.

**Explicit non-behavior:** no fallback ranking, no reduced universe, and no
default-eligible assumption when data is insufficient.

### 4.4 Reference series — SPY as read-only regime input

The regime gate and volatility estimate require a market reference. SPY is used
**bars-only, never as an order**:

| Use | Permitted? | Basis |
|---|---|---|
| `market/bars` read on SPY | Yes | Read-only market data; no order path touched |
| SPY in `symbol_allowlist.allow` | **No** | Not proposed; stays out of the YAML |
| SPY BUY / SELL | **No** | H4.1 ETF BUY block; `strategy_v1.md` §3 |

This is consistent with `MSTR_BTC_RESEARCH_PROPOSAL_v0_1.md` §6, which already designates
SPY and QQQ as *research controls only*. Reading bars on a non-allowlisted symbol touches
no gate and no order endpoint.

### 4.5 Regime gate — portfolio-level

Two conventional, unfitted conditions on the SPY reference series using **completed
daily bars only**:

```
A: SPY latest completed close > SPY 200-session SMA
B: SPY 252-session price return > 0

where:
  SPY price return = C_SPY[t] / C_SPY[t-252] − 1
```

**This is PRICE RETURN, not total return.** No dividend-adjusted total-return series
is guaranteed by the current governed data contract. If a dividend-adjusted series
becomes available under a separate governed data contract, condition B may be
re-evaluated in a future version.

**Data requirements:** at least **253 valid completed SPY sessions** must be
available (252 for the return window plus the current close). Missing, stale,
inconsistent, zero, or negative SPY prices must produce `RISK_DATA_INVALID` and
`NO_TRADE` for new BUY proposals.

| State | Condition | Effect on new BUY entries |
|---|---|---|
| `RISK_ON` | A and B both true | Full budget (subject to §4.6) |
| `CAUTION` | Exactly one of A, B true | Budget × 0.5 |
| `RISK_OFF` | Neither true | **No new BUY entries** |
| `RISK_DATA_INVALID` | Insufficient or invalid data | **No new BUY entries** |

SELL is **never** blocked by the regime gate — close-only exits must always be
available, consistent with the Gate E / P2b close-only exemption (`strategy_v1.md` §11).

Parameter count added: **two** (200-session SMA, 252-session return). Both are the
field-standard values.

### 4.6 Volatility targeting — gross exposure scalar

Realized volatility of the SPY reference over 20 completed trading sessions,
annualized:

```
σ̂_ref        = stdev(daily log returns, 20 completed sessions) × √252
σ_target     = 12%  (annualized)
gross_scalar = clamp( σ_target / σ̂_ref , 0.25 , 1.00 )
```

**Data requirements:** at least **21 valid completed SPY closes** are required
(20 log-return intervals). Non-positive prices, non-finite returns, or non-finite
volatility must produce `NO_TRADE`. Zero volatility must fail closed — do not
divide and do not default to 1. A stale SPY series (latest bar older than the most
recent completed session) must produce `NO_TRADE`.

The scalar is then applied to the **advisory** exposure budget:

```
effective_budget = hard_exposure_ceiling × gross_scalar × regime_multiplier
```

**Fail-closed assertions:**

- `effective_budget > hard_exposure_ceiling` → raise a fail-closed error.
- `effective_budget < 0` → raise a fail-closed error.
- `gross_scalar > 1.0` → raise a fail-closed error (clamp failure).

**Critical property:** `gross_scalar ≤ 1.00` by construction, and `regime_multiplier ≤ 1.0`.
The result can therefore **only be at or below the YAML 30% ceiling, never above it.**
`gate_exposure` (`guard.py:1466`) continues to enforce the hard 30% independently. If the
advisory layer fails, is bypassed, or produces a bad number, the guard ceiling still holds.

**Explicit caveat:** SPY volatility is a market-risk proxy only. It does not fully
measure constituent-specific risk, earnings-gap risk, sector-concentration risk, or
pairwise covariance risk. Effective diversification requires the risk-bucket cap (§4.7)
in addition to the gross scalar.

Worked illustration at `max_total_exposure = 30%`:

| σ̂_ref | Regime | `gross_scalar` | Effective budget | vs YAML ceiling |
|---|---|---|---|---|
| 10% | RISK_ON | 1.00 (clamped) | 30.0% | at ceiling |
| 12% | RISK_ON | 1.00 | 30.0% | at ceiling |
| 18% | RISK_ON | 0.67 | 20.0% | below |
| 24% | RISK_ON | 0.50 | 15.0% | below |
| 24% | CAUTION | 0.50 × 0.5 | 7.5% | below |
| 40% | RISK_ON | 0.30 | 9.0% | below |
| 60% | RISK_ON | 0.25 (clamped) | 7.5% | below |
| any | RISK_OFF | — | 0% new BUY | below |
| any | RISK_DATA_INVALID | — | 0% new BUY | below |

Parameter count added: **three** (`σ_target`, 20-session lookback, 0.25 floor).

### 4.7 Risk-bucket concentration cap — proposed Gate I

Breadth is only real if positions are decorrelated. The simplest robust enforcement:

```
Gate I: reject BUY if the candidate's risk bucket already has
        ≥ max_positions_per_risk_bucket open positions
```

Proposed value: **`max_positions_per_risk_bucket = 2`**.

#### 4.7.1 Risk bucket definitions

Every candidate symbol must map to exactly one risk bucket. The semiconductor
separation from Information Technology is a **deliberate risk-control grouping**,
not a canonical GICS sector claim. The term "risk_bucket" is used throughout to
distinguish this grouping from formal GICS classification.

| Risk Bucket | Symbols | Count |
|---|---|---|
| INFORMATION_TECHNOLOGY | AAPL, MSFT, AVGO | 3 |
| SEMICONDUCTORS | NVDA, AMD | 2 |
| COMMUNICATION_SERVICES | META, GOOGL | 2 |
| HEALTH_CARE | LLY, UNH, JNJ | 3 |
| CONSUMER_STAPLES | PG, KO | 2 |
| CONSUMER_DISCRETIONARY | AMZN, HD | 2 |
| FINANCIALS | JPM, BAC | 2 |
| ENERGY | XOM, CVX | 2 |
| INDUSTRIALS | CAT, UNP | 2 |
| UTILITIES | NEE, DUK | 2 |
| **Total** | | **22** |

#### 4.7.2 Risk bucket enforcement rules

- Missing mapping → reject BUY (fail closed).
- Duplicate mapping → reject configuration load.
- Unknown bucket → reject BUY (fail closed).
- SELL and close-only actions remain exempt.

A direct pairwise correlation cap (e.g. reject if 60-session correlation to any
open position > 0.80) is strictly more precise, but requires a maintained
correlation matrix and more data plumbing. Per design principle 3 (fewer
parameters), the risk-bucket cap is proposed for v1.1 and the correlation cap is
deferred to **v1.2 as a candidate**.

### 4.8 Position sizing — unchanged

The v1.0.0 §9 sizing rule is **retained without modification**:

```
notional_cap_shares = floor(5% × NL_EUR × EUR/USD / entry_price)
risk_cap_shares     = floor(2% × NL_EUR × EUR/USD / stop_distance)
final_shares        = min(notional_cap_shares, risk_cap_shares, allowlist_max)
```

Implemented by `compute_final_max_shares` (`guard.py:1268`), which already returns the
binding cap. Note the risk cap is **already ATR-driven** via `stop_distance`, so
per-position volatility scaling exists today. What v1.1 adds is *portfolio-level* gross
scaling (§4.6) — the missing layer, not a replacement for the existing one.

**No change to `compute_final_max_shares` is proposed.** The vol scalar acts on the
exposure budget the advisory layer is willing to propose against, not on the share formula.

### 4.9 Stops and exits — unchanged

`strategy_v1.md` §12 is retained in full: mandatory broker-side child SELL STP,
`calc_stop` (`guard.py:1016`) taking the **max** of four candidates —

```
max( entry − 2×ATR(14), recent_swing_low, 20_day_low, entry × 0.95 )
```

— fail-closed parent cancellation if child stop placement fails, 2R partial profit-taking,
and the §12.3 hard invalidation triggers. The −5% hard floor is unchanged.

### 4.10 Output contract — machine fields and LLM commentary

Every proposal must separate **deterministic machine fields** from **LLM commentary**.
The LLM output must never include or control sizing, leverage, or order parameters.

#### 4.10.1 Deterministic machine fields

These are computed by the calculation module (Phase 19C) and the orchestrator
(Phase 19D). They are **not** produced by the LLM:

| Field | Description |
|---|---|
| `strategy_version` | e.g. `"v1.1.0"` |
| `as_of` | Latest completed US trading session timestamp |
| `data_snapshot_hash` | Hash of all input bar series for reproducibility |
| `eligible` | Boolean — candidate passes all deterministic filters |
| `rejection_reasons` | List of reasons if `eligible` is false |
| `regime_state` | `RISK_ON` / `CAUTION` / `RISK_OFF` / `RISK_DATA_INVALID` |
| `realized_vol` | Annualized 20-session realized SPY volatility |
| `gross_scalar` | Computed vol scalar ∈ [0.25, 1.00] |
| `effective_budget` | Advisory exposure budget (≤ YAML ceiling) |
| `current_exposure` | Current total notional exposure |
| `cross_sectional_rank` | Ordinal rank within the valid universe |
| `valid_universe_size` | Number of symbols with complete data this cycle |
| `aligned_signals` | Which of TREND_20, VOLUME_20, BREAKOUT_20, RS_20 are true |
| `risk_bucket` | Candidate's assigned risk bucket |
| `risk_bucket_capacity_remaining` | Positions available in this risk bucket |
| `concurrent_position_capacity_remaining` | Positions available under `max_concurrent_positions` |

#### 4.10.2 LLM commentary (only)

The LLM may emit **only** these fields and must never deviate:

| Field | Description |
|---|---|
| `rank` | Ordinal preference among eligible candidates |
| `thesis` | Human-readable rationale |
| `invalidation_condition` | Specific, testable condition that would close the position |

#### 4.10.3 LLM output prohibitions

The LLM must **never** include or control:

- `quantity`, `shares`
- `notional`, `notional_amount`
- `leverage`, `leverage_multiplier`
- `confidence`, `confidence_multiplier`, `confidence_score`
- `exposure_budget`, `position_size_pct`
- `stop_distance`, `stop_price`, `take_profit_price`
- `order_type`, `limit_price`, `time_in_force`
- `approval`, `submit`, `auto_execute`

Any LLM output containing these fields must be rejected by the orchestrator before
reaching any order path.

---

## 5. What Does Not Change

| Item | Status under v1.1 |
|---|---|
| All CLAUDE.md §3 safety invariants (1–17) | **Unchanged** |
| `/order` = HTTP 403 permanently | **Unchanged** |
| Triple kill switches, default off | **Unchanged** |
| H1 token requirement for approve + submit | **Unchanged** |
| Preflight → approve → submit as sole path | **Unchanged** |
| Long-only; no shorting | **Unchanged** |
| No options, futures, forex, crypto, CFDs | **Unchanged** |
| No leveraged or inverse ETFs | **Unchanged** |
| H4.1 US-domiciled ETF BUY block | **Unchanged** (see §11 open decision) |
| 5% notional / 2% risk / 30% exposure YAML ceilings | **Unchanged** |
| 2 trades per day (Gate D) | **Unchanged** |
| −1% daily / −3% weekly loss halts (Gate E) | **Unchanged** |
| RTH-only, 15-minute open/close entry blackouts | **Unchanged** |
| Manual approval for every order | **Unchanged** |
| Advisory-only boundary for Hermes and Werner | **Unchanged** |
| Sizing formula (`compute_final_max_shares`) | **Unchanged** |
| `calc_stop` formula | **Unchanged** |
| Phase 18R2 / 18C / Phase 18 governance chain | **Must close before Phase 19 implementation** |

---

## 6. Risk Envelope — v1.1

| Parameter | v1.0.0 | v1.1 proposed | Enforcement |
|---|---|---|---|
| Max notional per position | 5% NL | **5% NL** (unchanged) | Gate B (`guard.py:1314`) |
| Max risk per trade | 2% NL | **2% NL** (unchanged) | Gate C (`guard.py:1333`) |
| Max total exposure (hard ceiling) | 30% NL | **30% NL** (unchanged) | Gate F (`guard.py:1466`) |
| Effective exposure budget (advisory) | n/a | **30% × gross_scalar × regime_mult** | Advisory layer |
| Max concurrent positions | "2" (contradictory) | **6** — proposed hard cap requiring human approval | Proposed Gate I (§9.4) |
| Max positions per risk bucket | none | **2** | Proposed Gate J (§9.4) |
| Max trades per day | 2 | **2** (unchanged) | Gate D (`guard.py:1348`) |
| Daily loss halt | −1% NL | **−1% NL** (unchanged) | Gate E (`guard.py:1357`) |
| Weekly loss halt | −3% NL | **−3% NL** (unchanged) | Gate E |
| Min cash reserve | 70% NL | **≥70% NL** (unchanged) | Implied by Gate F |
| Leverage | none | **none — formally rejected (§3)** | Invariant 8 |
| Portfolio vol target | none | **12% annualized** (advisory) | Advisory layer |

### 6.1 Position-count control

- **Maximum fully sized 5%-notional positions: 6.**
- **Maximum concurrent positions: not currently enforced** by the 30% exposure ceiling
  and 5% position-size ceiling alone.
- **Smaller positions could allow more than six concurrent positions** while remaining
  below the 30% exposure ceiling.

`max_concurrent_positions: 6` is a separately proposed hard operational cap
requiring explicit human approval. It applies only to new BUY exposure. SELL and
close-only actions remain exempt. It is **not mathematically derived from Gate F** —
it is a distinct candidate control. A new gate enforces this independent of the
exposure ceiling. If Chris prefers a different value or no numeric cap, that
decision is recorded in §11.2.

### 6.2 Risk-bucket cap

`max_positions_per_risk_bucket: 2` caps the number of concurrent BUY positions
within any one risk bucket. This complements the position-count cap: the position
cap limits total positions; the risk-bucket cap limits concentration within any
one grouping. See §4.7 for risk bucket definitions and enforcement rules.

---

## 7. MSTR / BTC Disposition — PROPOSED / S0 / NONE

**Recommendation: keep `mstr_btc_research_v0_1` at `PROPOSED`. Do not promote.**

### 7.1 Current governance state (verified)

`docs/strategy-proposals/MSTR_BTC_RESEARCH_PROPOSAL_v0_1.md` records:
`proposal_status: PROPOSED`, `strategy_readiness: S0`, `execution_scope: NONE`,
`permitted_activity: DOCUMENTATION_AND_SCHEMA_PLANNING_ONLY`,
`btc_execution_scope: NONE`, `equity_execution_scope: NONE`, plus
`NOT_APPROVED_FOR_EXECUTION`, `NOT_APPROVED_FOR_BACKTEST_PROMOTION`, and
`NOT_APPROVED_FOR_DATA_COLLECTION_RUNTIME`.

**There is no MSTR/BTC strategy running.** Not even data collection is authorized.

### 7.2 MSTR is instrument-embedded leverage

MSTR realized volatility runs ~80–110% annualized *(reference)*, against NVDA ~50% and
QQQ ~23% *(reference)*. Applying the Kelly criterion from §3, generously assuming
`μ = 30%`:

```
L* = 0.30 / 0.81 ≈ 0.37×
```

Kelly-optimal MSTR is **under 40% of the account, unlevered**. Buying MSTR is buying
leveraged BTC exposure plus a corporate-structure layer the price series does not reveal:
ATM equity issuance (dilution), convertible maturities, and mNAV premium/discount swings
that can move the equity *against* BTC.

### 7.3 The sizing bind

Under the 5% per-symbol notional cap with a −5% stop floor, MSTR risks
**0.25% of NL** per trade:

```
5% notional × 5% stop distance = 0.25% NL risk
```

Sized legally, MSTR cannot move the portfolio. It is only interesting sized large, and it
cannot be sized large. That is the complete case against promotion.

### 7.4 Cost of promotion

Promotion would require, per the Phase 18B data-governance documents: BTC spot bar
ingestion, corporate-event feeds, point-in-time option-chain snapshots
(`OPTION_CHAIN_SNAPSHOT_SCHEMA_v0_1.json`), provider-disagreement handling, and separate
Track A / Track B dataset isolation. That is the **highest** infrastructure cost of any
option on the table, for the **lowest** breadth contribution — one more long-beta name.

### 7.5 The "QQQ fallback" construction is already forbidden

Two independent blocks, plus a third:

1. `MSTR_BTC_RESEARCH_PROPOSAL_v0_1.md` §5: *"Track B must **not** be selected merely
   because Track A returned `NO_TRADE`."* A QQQ fallback triggered by an MSTR `NO_TRADE`
   is precisely the forbidden construction.
2. `strategy_v1.md` §3: H4.1 blocks US-domiciled ETFs for BUY. QQQ BUY is hard-blocked.
3. `gate_allowlist` (`guard.py:1305`) fails closed — QQQ is not in the YAML allowlist.

v1.1 contains no fallback mechanism of any kind. `NO_TRADE` is a terminal, valid outcome.

---

## 8. Statistical Reality of Evaluation

This section exists to calibrate expectations before the paper run, because the most likely
failure mode of this project is **concluding too much from too little data**.

The t-statistic of a Sharpe ratio estimate over `T` years:

```
t ≈ SR × √T
```

| True Sharpe | Years to reach t = 2 | Years to reach t = 3 |
|---|---|---|
| 1.5 | 1.8 | 4.0 |
| 1.0 | 4.0 | 9.0 |
| 0.7 | 8.2 | 18.4 |
| 0.5 | 16.0 | 36.0 |

At Gate D's 2 trades/day ceiling — and realistically a few trades per week — a paper run of
a few months produces **no statistically meaningful evidence of edge whatsoever.**

### 8.1 Backtest and data integrity requirements

Any backtest or evaluation must satisfy:

1. **Freeze the candidate universe** before each evaluation period. Do not allow
   present-day constituent selection to leak into historical periods.
2. **Use point-in-time symbol eligibility** where available. Record delistings and
   removals where applicable.
3. **One synchronized as-of date** for all series. No symbol may be evaluated with
   a different latest session than any other.
4. **Prohibit future bars.** No revised or restated data may be used as if it were
   known at the evaluation date.
5. **Separate periods:** development, validation, and untouched test periods must
   be disjoint and recorded.
6. **Record every attempted strategy variant.** Do not discard failed attempts.
   Apply a multiple-testing haircut when evaluating the best result.
7. **Apply transaction costs and conservative slippage.** Paper-mode P&L biases
   (§8.2) must be explicitly accounted for.
8. **Never promote based on in-sample Sharpe.** A high in-sample Sharpe is more
   likely to indicate overfitting than edge at this sample size.
9. **Never treat paper P&L as proof of edge.** See §8.2.

### 8.2 Paper-mode P&L is upward-biased

| Bias | Direction | Why |
|---|---|---|
| No queue position modeling | Optimistic | Paper fills assume you were first |
| No partial fills | Optimistic | Real partials fragment risk and count as one trade (invariant 15) |
| No market impact | Optimistic | Size moves price in reality |
| Stop fills through gaps | Optimistic | Paper stops fill near trigger; real gaps skip |
| Delayed quotes | Distorting | Paper account quotes are delayed; entry references shift |

So the P&L that *is* produced is biased high on top of being statistically meaningless.

### 8.3 Corollary — a backtest Sharpe above ~1.5 should increase suspicion

With <200 trades and multiple variants tried, a high in-sample Sharpe is far more likely to
indicate overfitting than edge. `strategy_v1.md` §15 already encodes the right response;
apply a multiple-testing haircut before believing any figure.

---

## 9. Implementation Plan — Phased Deployment Order

Phased to match the existing Phase 18 governance chain. **No phase may be skipped,
and each requires its own CI test module.** The live file
`~/.openclaw/risk-rules/paper-trading-rules.yaml` is edited **last (Phase 19H)**,
after all implementation, testing, and human approval are complete.

### 9.1 Phase 19A — Revised documentation and deterministic contracts (this document)

| Item | Status |
|---|---|
| Strategy v1.1 proposal v0.2 with ten corrections | **Complete** |
| Deterministic signal contract (§4.3) | **Complete** |
| Exact cross-sectional ranking (§4.3.4) | **Complete** |
| SPY price-return regime contract (§4.5) | **Complete** |
| Volatility failure handling (§4.6) | **Complete** |
| Risk-bucket terminology (§4.7) | **Complete** |
| Output contract (§4.10) | **Complete** |
| Code changes | **None** |
| YAML changes | **None** |
| Guard changes | **None** |
| Model tier required | Tier 2 (docs) |
| Phase 19A boundary | `PHASE19B_REPOSITORY_CANDIDATE_CONFIG` |

### 9.2 Phase 19B — Repository-local inactive candidate configuration

Repository-local JSON schemas and inactive candidate configuration. **No live YAML
edit.** No runtime effect.

- `symbol_allowlist` schema (22 symbols, JSON).
- `symbol_risk_buckets` schema (mapping, JSON).
- `advisory_params` schema (vol target, regime lookbacks, RS lookback, JSON).
- `max_concurrent_positions` and `max_positions_per_risk_bucket` schema.

All schemas are **inactive candidates** stored in `docs/strategy-proposals/`.
They are not loaded by any running component.

### 9.3 Phase 19C — Pure deterministic calculation module

A new module computing regime state, gross scalar, effective budget, and
cross-sectional RS ranks. **Pure calculation only.**

- No network access.
- No broker endpoint.
- No credential access.
- No LLM invocation.
- No runtime state mutation.
- No order path.

### 9.4 Phase 19D — Shadow advisory orchestrator

Orchestrates the calculation module and emits structured advisory proposals.
**No order path and no executable proposal promotion.**

- Reads SPY bars via bridge `market/bars`.
- Calls Phase 19C calculation functions.
- Emits `{rank, thesis, invalidation_condition}` per §4.10.
- Never emits size, leverage, or order parameters.

### 9.5 Phase 19E — Guard gates behind inactive configuration

New guard gates implemented behind inactive candidate configuration.
Per CLAUDE.md §6, `guard.py` edits require a Tier-1 model and a Chris-approved,
git-tagged change.

| Gate | Responsibility | Applies to | Fail mode |
|---|---|---|---|
| Gate I | `max_concurrent_positions` cap | BUY only | Closed |
| Gate J | `max_positions_per_risk_bucket` cap | BUY only | Closed |

Required-keys update at `guard.py:4015`: add `symbol_risk_buckets`,
`max_concurrent_positions`, `max_positions_per_risk_bucket`, and the advisory
block. Every allowlisted symbol must have a risk-bucket mapping, else raise at
load. Both gates are registered behind the inactive candidate configuration —
they do not activate until the live YAML is edited in Phase 19H.

### 9.6 Phase 19F — Validation

| Test module | Coverage |
|---|---|
| Unit tests | Every deterministic function in Phase 19C |
| Property tests | `effective_budget ≤ hard_exposure_ceiling` for randomized inputs; `gross_scalar ∈ [0.25, 1.00]` |
| Integration tests | Bridge → calculator → orchestrator pipeline |
| Invariant tests | All CLAUDE.md §3 invariants preserved |
| Point-in-time tests | No future leakage; synchronized as-of dates |
| Out-of-sample tests | Walk-forward evaluation on held-out periods |
| Walk-forward tests | Rolling-origin evaluation per §8 |

### 9.7 Phase 19G — Explicit human activation review

Separate governance checkpoint requiring:

- All open decisions (§11) resolved.
- All Phase 19F tests green.
- Out-of-sample and walk-forward evidence exists.
- All safety invariants re-verified.
- Explicit human activation approval recorded.

### 9.8 Phase 19H — Live YAML edit (Chris only, manual)

**Werner does not perform this step** (invariant 6). Chris applies it per
RUNBOOK §L8 with:

- Pre-edit backup and checksum.
- Full rollback plan.
- All tests passing.
- Runtime verification after edit.

Changes to `~/.openclaw/risk-rules/paper-trading-rules.yaml`:

```yaml
symbol_allowlist:
  mode: explicit_list
  allow:                     # expand 4 → 22 (§4.2)
    - AAPL
    - MSFT
    - AVGO
    - NVDA
    - AMD
    - META
    - GOOGL
    - LLY
    - UNH
    - JNJ
    - PG
    - KO
    - AMZN
    - HD
    - JPM
    - BAC
    - XOM
    - CVX
    - CAT
    - UNP
    - NEE
    - DUK

symbol_risk_buckets:         # risk-bucket mapping (§4.7)
  AAPL: INFORMATION_TECHNOLOGY
  MSFT: INFORMATION_TECHNOLOGY
  AVGO: INFORMATION_TECHNOLOGY
  NVDA: SEMICONDUCTORS
  AMD: SEMICONDUCTORS
  META: COMMUNICATION_SERVICES
  GOOGL: COMMUNICATION_SERVICES
  LLY: HEALTH_CARE
  UNH: HEALTH_CARE
  JNJ: HEALTH_CARE
  PG: CONSUMER_STAPLES
  KO: CONSUMER_STAPLES
  AMZN: CONSUMER_DISCRETIONARY
  HD: CONSUMER_DISCRETIONARY
  JPM: FINANCIALS
  BAC: FINANCIALS
  XOM: ENERGY
  CVX: ENERGY
  CAT: INDUSTRIALS
  UNP: INDUSTRIALS
  NEE: UTILITIES
  DUK: UTILITIES

max_concurrent_positions:
  value: 6

max_positions_per_risk_bucket:
  value: 2

advisory:
  portfolio_vol_target_pct: 12
  vol_lookback_sessions: 20
  gross_scalar_floor: 0.25
  regime_sma_sessions: 200
  regime_return_sessions: 252
  regime_caution_multiplier: 0.5
  cross_sectional_rs_lookback_sessions: 60
  cross_sectional_rs_top_fraction: 0.5
  cross_sectional_min_valid_universe: 8
  reference_symbol: SPY
  hermes_risk_per_trade_pct: 0.25
```

**Note:** the `advisory` block also discharges the H3 follow-up recorded in
CLAUDE.md §5 (move the Hermes 0.25% advisory target into the YAML so the
two-tier risk model has one source file).

### 9.9 Dependency order

```
19A (docs) → 19B (candidate schemas) → 19C (calculator) → 19D (orchestrator)
→ 19E (guard gates, inactive) → 19F (validation) → 19G (human review)
→ 19H (live YAML, Chris only)
```

**Phase 19 implementation and activation cannot advance until Phase 18R2, Phase
18C, and the broad Phase 18 governance chain are closed.**

---

## 10. Paper-Run Validation Protocol

**The paper run is an engineering validation, not a strategy trial.** Per §8 it cannot
produce meaningful evidence of edge. It can produce excellent evidence that the machinery
is correct — which is the actual prerequisite for anything else.

### 10.1 Primary pass/fail criteria — plumbing

| # | Check | Pass condition |
|---|---|---|
| 1 | Preflight rejects non-allowlisted symbols | 100% rejection, fail-closed |
| 2 | Gate I rejects 3rd same-sector position | 100% rejection |
| 3 | Child SELL STP attaches to every BUY | 100% attachment |
| 4 | **Fail-closed stop test** | Parent BUY cancelled before fill when child STP placement fails (`strategy_v1.md` §12.1) |
| 5 | Stop quantity equals entry quantity | Exact match, every order |
| 6 | FX fetched on **every** preflight | Zero cached values; CLAUDE.md §5 |
| 7 | Gate D blocks the 3rd trade of a day | 100% block |
| 8 | Gate E halts new BUY at −1% daily | Triggered and logged correctly |
| 9 | Approval expires at 300s, no extension | Expiry enforced, no exceptions |
| 10 | Bridge restart invalidates pending approvals | 100% invalidation (invariant 12) |
| 11 | Monitor reconciliation after every fill | Zero unreconciled fills |
| 12 | Partial fill counts as one daily trade | Invariant 15 upheld |
| 13 | Entry blackout windows respected | Zero entries 9:30–9:45 or 15:45–16:00 ET |
| 14 | Advisory budget never exceeds YAML ceiling | Zero violations, logged every cycle |
| 15 | Hermes never emits a size or leverage figure | Zero occurrences in proposal records |

**Any failure in 1–15 is a blocker.** Fix and restart the validation window.

### 10.2 Secondary observations — recorded, not judged

Logged for later analysis, explicitly **not** used to accept or reject the strategy:

- Realized slippage vs entry reference, per trade
- Distribution of binding cap (`notional` vs `risk`) from `compute_final_max_shares`
- Regime state distribution over the window
- `gross_scalar` distribution over the window
- Frequency of `NO_TRADE` outcomes and their reasons
- Sector distribution of proposals vs fills
- Count of Gate I rejections (does the cap actually bind?)

### 10.3 Explicitly not a success criterion

| Metric | Why excluded |
|---|---|
| Paper P&L | Statistically meaningless at this horizon (§8), upward-biased (§8.1) |
| Win rate | Dominated by noise at n < 100 |
| Paper Sharpe | Requires ~4 years at SR 1.0 for t = 2 |
| Largest winner | Pure selection on noise |

### 10.4 Suggested window

Minimum **60 trading days** *or* until every one of checks 1–15 has been positively
exercised at least once — whichever is **longer**. Checks 4, 8, 9, and 10 may require
deliberate fault injection rather than waiting for natural occurrence; conduct those in a
controlled session, not during a live cycle.

Record results in `docs/KPI_DASHBOARD.md` conventions and gate promotion on
`docs/AUTONOMY_CRITERIA.md`.

---

## 11. Open Decisions for Chris

None of these can be resolved by Werner. Each materially shapes the design.

### 11.1 H4.1 — the ETF BUY block

**Decision required:** keep or lift the US-domiciled ETF BUY block.

| Option | Consequence |
|---|---|
| **Keep** | Single-name only, permanently. v1.1 as written applies unchanged. Index/vol-targeted-core and risk-parity families remain unavailable. |
| **Lift** | Opens the best-evidenced, lowest-complexity strategy family (vol-targeted index trend). Requires a new governance review, and §2/§3 of `strategy_v1.md` must be reconciled — they currently contradict each other. |

v1.1 is written to work under **Keep**. It needs no revision either way, but under
**Lift** a materially stronger v1.2 becomes possible.

### 11.2 Maximum concurrent positions

Accept the proposed `max_concurrent_positions: 6` (§6.1), or a different value?
Six is a proposed hard operational cap, not a derived consequence of Gate F.
The cap must apply only to new BUY; SELL and close-only remain exempt.

### 11.3 Final allowlist

The 22 names in §4.2 are a proposal. Chris owns the list. Considerations: is 22 too many
to follow attentively; should any sector be dropped; should the semiconductor split be
retained.

### 11.4 Volatility target value

12% annualized is proposed as a conventional moderate target. Lower (10%) trades less and
draws down less; higher (15%) tracks the market more closely. This value should **not** be
optimized against a backtest — pick it on risk preference, per design principle 4.

### 11.5 MSTR / BTC

Confirm the §7 recommendation to hold at `PROPOSED`, or direct otherwise.

### 11.6 Meaning of "learning" during the paper run

**Nothing in this architecture learns, and v1.1 proposes that it stay that way.** If
"learning" means Hermes adapting its own parameters from recent P&L, that would be both
ungoverned and statistically hopeless at this sample size (§8). Under v1.1, learning means
exactly one thing: **Chris promoting a versioned strategy change on evidence**, through the
`strategy_v1.md` §15 anti-overfit checklist and §16 versioning discipline. No autonomous
parameter adaptation is proposed, and none should be added.

---

## 12. Anti-Overfit Compliance (`strategy_v1.md` §15)

| # | Check | v1.1 response |
|---|---|---|
| 1 | Addresses an observed failure mode, not hypothetical optimization? | **Pass** — 1-bet universe, contradictory position cap, and absent regime control are documented defects |
| 2 | Tested out-of-sample? | **Pending** — required before promotion; no backtest exists yet |
| 3 | Generalizes across ≥2 allowed symbols? | **Pass** — breadth and regime logic are symbol-agnostic |
| 4 | Survives walk-forward? | **Pending** — Phase 19E and the data-governance rules (18B §8 principles 13–16) require it |
| 5 | Explainable in one sentence? | **Pass** — "Hold more decorrelated names, and hold less of everything when volatility is high or trend is down." |
| 6 | Parameter count direction? | **Increase of 6** (RS lookback, 200d, 12m, vol target, vol lookback, scalar floor). All conventional, none fitted. Sector cap adds a 7th. Justified by §1.1 breadth arithmetic. |
| 7 | Sharpe / max-drawdown improved OOS? | **Pending** — unproven; §8 governs interpretation |
| 8 | "Would this have prevented a past loss?" | **Partial** — the single recorded position (META, 2026-06-09, `docs/trade-journal/`) is too small a sample to answer |
| 9 | Documented with date and rationale? | **Pass** — this document |
| 10 | Preserves advisory-only boundary? | **Pass** — §5; advisory layer can only tighten |

**Checks 2, 4, and 7 are unmet.** Per the §15 failsafe, fewer than 3 failures permits
proposal status but **not** promotion to active strategy. This document is therefore
correctly at `PROPOSED`, and promotion is blocked until out-of-sample and walk-forward
evidence exists.

---

## 13. Explicit Non-Actions

This proposal **does not** and **must not**:

1. Replace or modify `docs/strategy_v1.md` (v1.0.0 remains active)
2. Modify `~/.openclaw/risk-rules/paper-trading-rules.yaml`
3. Modify `.env`, `guard-state.json`, `approval-records.jsonl`, `active-approvals.json`, or `submitted-approvals.json`
4. Modify `guard.py`, `bridge.py`, `monitor.py`, or `bundle_audit.py`
5. Add any symbol to an executable allowlist
6. Enable `IBKR_ALLOW_ORDERS` or `rules.enforced`
7. Generate, read, possess, or transmit an H1 token
8. Access `/etc/ibkr-bridge/h1_token` or any root-owned file
9. Call any IBKR endpoint or any `/order*` endpoint
10. Run a backtest or collect market data
11. Generate a trade proposal or open an order window
12. Enable crypto, options, futures, forex, CFDs, leverage, or shorting
13. Promote `mstr_btc_research_v0_1` beyond `PROPOSED`
14. Introduce any autonomous parameter adaptation or self-modifying logic
15. Subvert the advisory-only boundary of Hermes or Werner

---

## 14. Promotion Requirements

**Current final recommendation: `APPROVE_FOR_DESIGN_REVIEW_ONLY`.**

Implementation readiness remains blocked. To move from `PROPOSED` to active `v1.1.0`:

1. **Chris's explicit approval** of this document
2. **Open decisions §11 resolved** — at minimum 11.1, 11.2, 11.3
3. **Phase 19B–19F implemented** — candidate schemas, calculator, orchestrator,
   guard gates (behind inactive config), and full validation
4. **Deterministic schemas exist** for all machine fields in §4.10.1
5. **All Phase 19F tests green** — unit, property, integration, invariant,
   point-in-time, out-of-sample, and walk-forward
6. **Point-in-time out-of-sample and walk-forward evidence** satisfying
   `strategy_v1.md` §15 checks 2, 4, and 7
7. **Phase 19G human activation review** — explicit approval recorded
8. **Phase 19H live YAML edit** — Chris only, with backup, checksum, rollback
   plan, and runtime verification
9. **Invariants re-verified** — CLAUDE.md §3 (1–17) confirmed intact via
   `ibkr-status` and `GET /status`
10. **Version bump** — `strategy_version: v1.1.0`, changelog entry in
    `docs/strategy_v1_changelog.md`

No step may be skipped or reordered. Execution scope remains `NONE` until a
separate, explicit governance action changes it.

**Phase 19 implementation and activation cannot advance until Phase 18R2, Phase
18C, and the broad Phase 18 governance chain are closed.**

---

## 15. Summary

| Question | Answer |
|---|---|
| Is the MSTR/BTC strategy fine? | There is no such strategy — it is `PROPOSED`/S0 with `execution_scope: NONE` (§7.1) |
| Does it need an update? | It should stay parked. Highest infra cost, lowest breadth gain, and it is instrument-embedded leverage (§7.2–7.4) |
| Is the QQQ fallback fine? | It is forbidden three ways and does not exist in code (§7.5) |
| Would more stocks help? | Yes — but along the **correlation** axis, not ticker count. 4 → 22 across 10 risk buckets raises independent bets ~1.3 → ~6.5 (§1.1, §4.2) |
| Is a 1–20× leverage agent better? | No. Above ~3× expected compound growth is negative regardless of edge; at 20× ruin is certain and no valid stop distance exists (§3) |
| What is the highest-value change? | Allowlist breadth (a YAML edit), then the regime gate, then portfolio vol targeting (§9) |
| Will paper mode teach the bot? | No. It validates plumbing, not edge — edge needs ~4 years at SR 1.0 (§8, §10) |
| Final recommendation | `APPROVE_FOR_DESIGN_REVIEW_ONLY` — implementation blocked per §14 |

**Core design property:** every mechanism v1.1 introduces can only *reduce* exposure below
the YAML ceiling. The guard's hard limits are untouched, `gate_exposure` still enforces 30%
independently, and the advisory layer is structurally incapable of loosening anything.

---

## Document Metadata

| Field | Value |
|---|---|
| Document ID | `STRATEGY_V1_1_PROPOSAL_v0_2` |
| Proposal ID | `strategy_v1_1_proposal_v0_2` |
| Governance Level | Level 1 (advisory-only, design documentation) |
| Phase | 19A |
| Phase Boundary | `PHASE19A_STRATEGY_V1_1_SPECIFICATION_REVISION_COMPLETE` |
| Next Phase Boundary | `PHASE19B_REPOSITORY_CANDIDATE_CONFIG` |
| Target Strategy Version | `v1.1.0` (inactive) |
| Canonical Strategy | `docs/strategy_v1.md` (v1.0.0 — unchanged) |
| Supersedes | `STRATEGY_V1_1_PROPOSAL_v0_1` (SHA-256: `0ec59eacb9bffb32eb8593cbe0c1f59e8f7d5790dfff4dcf088bc959f22f400d`) |
| Superseded By | None |
| Final Recommendation | `APPROVE_FOR_DESIGN_REVIEW_ONLY` |
| Review Cadence | On demand; required before any promotion |
| Model Tier Used | Tier 2 (documentation only — no safety-critical code touched) |

### Version History

| Version | Date | Changes |
|---|---|---|
| 0.2 | 2026-07-26 | Phase 19A substantive specification revision — 10 corrections: (1) position-count fix with explicit max_concurrent_positions cap; (2) deterministic signal contract with exact machine-testable rules; (3) cross-sectional ranking exact formula, tie-breaker, and minimum valid-universe threshold; (4) SPY regime 252-session price return, not total return; (5) volatility targeting exact failure handling and fail-closed assertions; (6) risk-bucket terminology replacing sector; (7) deployment order 19A–19H with live YAML last; (8) backtest and data integrity requirements; (9) output contract separating machine fields from LLM commentary; (10) APPROVE_FOR_DESIGN_REVIEW_ONLY final recommendation. No strategy content implemented. |
| 0.1 | 2026-07-25 | Initial proposal — breadth expansion, regime gate, volatility targeting, Gate I sector cap, leverage rejection, MSTR/BTC disposition, paper-run validation protocol |
