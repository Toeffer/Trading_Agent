# Strategy v1.1 Proposal — Breadth, Regime Gating, and Volatility Targeting

> **Proposal ID:** `strategy_v1_1_proposal_v0_1`
> **Proposal Version:** `0.4`
> **Design Review:** `COMPLETE` (2026-07-27) — 6 defects found and corrected; see Version History
> **Open Decisions:** 4 of 6 resolved (11.1, 11.2, 11.3, 11.4); 11.5 and 11.6 remain open
> **Proposal Status:** `PROPOSED`
> **Strategy Readiness:** `S0`
> **Autonomy Level:** `1`
> **Execution Scope:** `NONE`
> **Permitted Activity:** `DOCUMENTATION_AND_DESIGN_ONLY`
> **Target Strategy Version:** `v1.1.0` (not yet active)
> **Canonical Strategy Reference:** `docs/strategy_v1.md` (v1.0.0 — remains active)
> **Created:** 2026-07-25
> **Last Updated:** 2026-07-25

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
| This document | `STRATEGY_V1_1_PROPOSAL_v0_1.md` | `PROPOSED` — advisory design only |

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

where `BR` counts **independent** bets, not tickers. Four correlated names inside one
factor is close to a single bet expressed four ways.

> **Design-review correction (v0.4).** Earlier drafts claimed 22 names yields ~6.5
> independent bets and a **2.24×** IR improvement. Those figures do not survive the
> standard effective-breadth formula and overstated the gain by roughly 80%. The
> defensible figures are below. The expansion is still clearly worth making — but for a
> different reason than the original text gave.

#### 1.1.1 Effective breadth, computed

For an equal-weighted portfolio of `n` assets with average pairwise correlation `ρ̄`:

```
N_eff = n / ( 1 + (n − 1)·ρ̄ )
```

The correlation that applies depends on **what kind of bet is being made**, and v1.1 makes
two different kinds.

**Directional component** — long-only equity exposure. Raw return correlations apply,
because every position is fundamentally the same bet on equity beta.

| Portfolio | n | ρ̄ *(reference)* | `N_eff` | Relative IR |
|---|---|---|---|---|
| v1.0.0 (4 mega-cap tech) | 4 | 0.65 | **1.36** | 1.00× |
| v1.1 (22 across 10 sectors) | 22 | 0.45 | **2.11** | **1.24×** |

**Selection component** — cross-sectional relative strength (§4.3). This bets on *relative*
performance, so market beta largely cancels and residual correlations apply.

| Portfolio | n | residual ρ̄ *(reference)* | `N_eff` | Relative IR |
|---|---|---|---|---|
| v1.0.0 (4 mega-cap tech) | 4 | 0.40 | **1.82** | 1.00× |
| v1.1 (22 across 10 sectors) | 22 | 0.20 | **4.23** | **1.52×** |

#### 1.1.2 What this means

**The allowlist expansion buys selection breadth, not diversification of market risk.**
Adding names to a long-only book barely diversifies it — 1.36 → 2.11 effective bets — because
the dominant risk is shared equity beta. Market risk is the job of the regime gate (§4.5)
and the inverse-vol scalar (§4.6), not of the ticker count.

Where the expansion genuinely pays is the ranker: going from 4 to 22 names takes the
cross-sectional sleeve from ~1.8 to ~4.2 independent bets, roughly a **1.5× improvement in
information ratio on that sleeve**. It also improves rank resolution — the top-50% filter
selects from 11 candidates instead of 2.

The dominant lever remains **decorrelation, not ticker count**. The change requires no new
data infrastructure and is a YAML edit. But it should be justified on selection quality, and
the regime and volatility machinery — not breadth — is what controls drawdown.

**Calibration requirement:** all correlations here are *(reference)* estimates. Recompute
raw and beta-residual correlations from bridge `market/bars` over ≥3 years before promotion,
and restate both tables from measured values.

### 1.2 Contradiction in the current risk envelope

`docs/strategy_v1.md` §8 states:

> Maximum positions open simultaneously — **2** — *Implied by exposure cap + per-position limit*

The arithmetic does not support this. With `max_position_notional = 5%` and
`max_total_exposure = 30%`:

```
30% ÷ 5% = 6 concurrent positions
```

The derived value is **6**, not 2. This matters: it is the difference between a 1-bet and a
6-bet portfolio, and it is currently ambiguous in the governing document. `guard.py` does
not enforce a position count directly — `gate_exposure` (`guard.py:1466`) enforces the 30%
notional ceiling, and `gate_notional` (`guard.py:1314`) enforces 5% per symbol. The "2"
appears to be a conflation with `max_trades_per_day = 2` (Gate D, `guard.py:1348`), which
is a different constraint entirely.

**v1.1 resolves this explicitly** (§6). No code change is required — only a corrected
document and, if Chris wants a hard cap, a new YAML parameter.

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

| GICS Sector | Symbols | Count |
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

### 4.3 Signal layer

v1.0.0 §5 signals are retained unchanged. One cross-sectional filter is added.

| Signal | Source | Role in v1.1 |
|---|---|---|
| Trend context | Price vs 20-day SMA | Retained (medium) |
| Volume confirmation | Volume vs 20-day average | Retained (medium) |
| Structure / price action | Break, pullback, flag | Retained (medium) |
| Relative strength vs SPY | Intraday RS | Retained (low) |
| ATR(14) | 14-period ATR | Retained (**required** — stop + sizing) |
| VIX | CBOE VIX | Retained (advisory) |
| Earnings calendar | Public dates | Retained (advisory, 48h avoidance) |
| **Cross-sectional RS rank** | **60-day return rank within allowlist** | **NEW — hard filter** |

**Entry requirement (v1.1):**
1. At least **two of the first four** v1.0.0 signals align *(unchanged)*, **and**
2. ATR(14) is available and valid *(unchanged)*, **and**
3. Candidate ranks in the **top 50%** of the allowlist on 60-day relative strength *(new)*, **and**
4. Portfolio regime state is not `RISK_OFF` (§4.5), **and**
5. Sector cap is not breached (§4.7).

Parameter count added: **one** (60-day RS lookback). Conventional value, not fitted.

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

Two conventional, unfitted conditions on the SPY reference series:

```
A: SPY close > 200-day SMA
B: SPY trailing 12-month total return > 0
```

| State | Condition | Effect on new BUY entries |
|---|---|---|
| `RISK_ON` | A and B both true | Full budget (subject to §4.6) |
| `CAUTION` | Exactly one of A, B true | Budget × 0.5 |
| `RISK_OFF` | Neither true | **No new BUY entries** |

SELL is **never** blocked by the regime gate — close-only exits must always be available,
consistent with the Gate E / P2b close-only exemption (`strategy_v1.md` §11).

Parameter count added: **two** (200-day, 12-month). Both are the field-standard values.

### 4.6 Inverse-volatility gross exposure scalar

> **Design-review correction (v0.2).** An earlier draft of this section called the `16%`
> constant a "portfolio volatility target" and set it to `12%`. Both were wrong. See
> §4.6.1 for why, and why the corrected value is `16%`. The mechanism is an
> inverse-volatility **scalar**, not a portfolio volatility target.

Realized volatility of the SPY reference over 20 trading days, annualized:

```
σ̂_ref        = stdev(daily log returns, 20d) × √252
vol_reference = 16%   (annualized; SPY long-run median realized vol, reference estimate)
gross_scalar = clamp( vol_reference / σ̂_ref , 0.25 , 1.00 )
```

The scalar is then applied to the **advisory** exposure budget:

```
effective_exposure_budget = max_total_exposure_yaml × gross_scalar × regime_multiplier
```

**Critical property:** `gross_scalar ≤ 1.00` by construction, and `regime_multiplier ≤ 1.0`.
The result can therefore **only be at or below the YAML 30% ceiling, never above it.**
`gate_exposure` (`guard.py:1466`) continues to enforce the hard 30% independently. If the
advisory layer fails, is bypassed, or produces a bad number, the guard ceiling still holds.

Worked illustration at `max_total_exposure = 30%`:

| σ̂_ref | Regime | `gross_scalar` | Effective budget | Interpretation |
|---|---|---|---|---|
| 10% | RISK_ON | 1.00 (clamped) | 30.0% | calm — full budget |
| 12% | RISK_ON | 1.00 (clamped) | 30.0% | calm — full budget |
| 16% | RISK_ON | 1.00 | 30.0% | typical — full budget |
| 18% | RISK_ON | 0.89 | 26.7% | mildly elevated |
| 24% | RISK_ON | 0.67 | 20.0% | elevated |
| 24% | CAUTION | 0.67 × 0.5 | 10.0% | elevated + weak trend |
| 40% | RISK_ON | 0.40 | 12.0% | stress |
| 64% | RISK_ON | 0.25 (clamped) | 7.5% | crisis — floor |
| any | RISK_OFF | — | 0% new BUY | trend down |

Parameter count added: **three** (`vol_reference_pct`, 20-day lookback, 0.25 floor).

#### 4.6.1 Why the constant is 16% and why it is not a "vol target"

Two errors in the earlier draft, both found in design review:

**Error 1 — it was mislabeled.** `σ̂_ref` measures **SPY's** volatility, but the portfolio
is at most 30% gross in single names. Those are different quantities, so the ratio cannot
be a portfolio volatility target. The portfolio's actual volatility at full gross, for
`n = 6` positions with single-name `σ ≈ 30%` and average pairwise correlation `ρ ≈ 0.45`
*(reference)*:

```
sleeve_vol     = σ × √( (1 + (n−1)ρ) / n )
               = 0.30 × √( (1 + 5×0.45) / 6 )
               = 0.30 × √0.5417  ≈  22.1%

portfolio_vol  = gross × sleeve_vol  =  0.30 × 22.1%  ≈  6.6%
```

A portfolio that tops out near **6.6%** volatility cannot target 12%. The figure was never
a target — it is a normalization constant, and it is now named `vol_reference_pct` to say so.

**Error 2 — the value made the scalar permanently binding.** SPY's typical realized
volatility is ~15–16% *(reference)*. With a 12% numerator, `gross_scalar = 12/16 ≈ 0.75`
in **calm** markets, so the mechanism applied a permanent ~25% haircut and had little
headroom left to respond when volatility actually rose. That inverts the intent.

Setting `vol_reference_pct = 16%` — near SPY's long-run median — makes the scalar ≈1.00
under typical conditions and tightens only when volatility is genuinely elevated. That is
volatility scaling behaving as designed: **dormant in calm, responsive in stress.**

**Calibration requirement:** 16% is a long-run *reference* estimate. Before promotion,
recompute SPY's median 20-day realized volatility from bridge `market/bars` over at least
5 years and set the constant to that measured median. Do **not** optimize it against
strategy P&L — pick it from the volatility distribution alone, per design principle 4.

### 4.7 Sector concentration cap — proposed Gate I

Breadth is only real if positions are decorrelated. The simplest robust enforcement:

```
Gate I: reject BUY if the candidate's GICS sector already has
        ≥ max_positions_per_sector open positions
```

**Value: `max_positions_per_sector = 1`.** Approved 2026-08-01 (§11.3).

Semiconductors are treated as a **distinct sector** from Information Technology for this
gate, because NVDA/AMD correlation is materially higher than either against MSFT
*(reference)*. That yields **11 sector groups** across the 22 names.

#### 4.7.1 Why 1 and not 2

An earlier draft proposed 2. The problem is an interaction with §4.3: **momentum clusters by
sector.** In a semis-led rally the relative-strength filter will rank NVDA *and* AMD in the
top half at the same time, and a cap of 2 would happily admit both — one bet occupying two
slots at twice the intended risk for that bet. That is precisely the failure the breadth
argument exists to prevent.

The proposed universe contains four such near-duplicate pairs:

| Pair | Sector group | ρ̄ *(reference)* | Effectively |
|---|---|---|---|
| NVDA / AMD | Semiconductors | ~0.80 | one bet |
| META / GOOGL | Communication Services | ~0.70 | one bet |
| JPM / BAC | Financials | ~0.80 | one bet |
| XOM / CVX | Energy | ~0.85 | one bet |

`CAT`/`UNP` (machinery vs rail) and `AMZN`/`HD` (e-commerce vs home improvement) are
genuinely different businesses and are unaffected either way.

**The cap costs almost nothing.** At 5% per position against a 30% ceiling, roughly 6
full-size positions fit, spread across 11 sector groups. A 1-per-sector cap therefore binds
in exactly one situation — when the ranker wants two correlated winners from the same sector
— which is the situation it exists to prevent. It does **not** reduce choice: all 22 names
remain rankable, and the sector simply yields its single slot to the highest-ranked
candidate.

#### 4.7.2 Deferred alternative

A direct pairwise correlation cap (reject if 60-day correlation to any open position > 0.80)
is strictly more precise — it would catch cross-sector duplicates such as a utility and a
REIT moving together on rates. It requires a maintained correlation matrix and more data
plumbing, so per design principle 3 (fewer parameters) it is deferred to **v1.2 as a
candidate**. The sector cap is the robust approximation.

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

---

### 4.10 Data-quality requirements for v1.1 signals

v1.1 materially increases data requirements over v1.0.0, whose §6 specifies only 20 days
for an SMA and 14 for ATR. The regime gate needs a **year** of reference history, and the
cross-sectional rank needs history for **every** allowlisted symbol. These requirements are
additive to `strategy_v1.md` §6, which continues to apply unchanged.

| Requirement | Threshold | Consumer |
|---|---|---|
| SPY reference bars | **≥252** valid daily closes | 200-day SMA + 12-month momentum (§4.5) |
| SPY realized-vol window | ≥20 valid daily closes | `gross_scalar` (§4.6) |
| Per-symbol bars, RS rank | **≥60** valid daily closes | Cross-sectional RS (§4.3) |
| Per-symbol bars, SMA | ≥20 valid daily closes | v1 §5 trend signal |
| Per-symbol bars, ATR | ≥14 valid daily closes | `calc_stop`, sizing |
| Staleness, all series | ≤1 trading day | v1 §6 (unchanged) |

**Explicit bar-duration requirement.** `fetch_bars` (`guard.py:820`) defaults to
`duration="30 D"`, which is insufficient for both the 200-day SMA and 12-month momentum.
The advisory layer must request an explicit duration of at least **"1 Y"** for the SPY
reference series. Relying on the default would silently produce a wrong regime state.

**Fail-safe rules.** Per 18A data-governance principle 7 (*missing or stale required data
produces `NO_TRADE`*), v1.1 fails toward *less* risk, never toward more:

| Condition | Result |
|---|---|
| SPY reference data missing, short, or stale | **Regime state = `RISK_OFF`** → no new BUY |
| `σ̂_ref` uncomputable | **`gross_scalar` = 0.25** (floor, not 1.00) |
| Candidate symbol has <60 valid bars | Candidate **excluded** from the RS universe |
| Valid-data symbols < 50% of allowlist | **`NO_TRADE` for the cycle** — rank not meaningful |
| ATR(14) unavailable for a candidate | Candidate rejected (v1 §5 — ATR always required) |

Note the direction of both defaults: an unavailable regime signal blocks buying rather than
permitting it, and an unavailable volatility estimate applies the tightest scalar rather
than the loosest. A data outage must never widen the risk envelope.

**Cross-sectional rank on partial data.** The RS rank is computed over the subset of
symbols with ≥60 valid bars, and "top 50%" is evaluated against **that subset**, not the
nominal 22. The subset size must be recorded in the proposal record so a rank is never
interpretable without knowing its universe.

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

---

## 6. Risk Envelope — v1.1

| Parameter | v1.0.0 | v1.1 proposed | Enforcement |
|---|---|---|---|
| Max notional per position | 5% NL | **5% NL** (unchanged) | Gate B (`guard.py:1314`) |
| Max risk per trade | 2% NL | **2% NL** (unchanged) | Gate C (`guard.py:1333`) |
| Max total exposure (hard ceiling) | 30% NL | **30% NL** (unchanged) | Gate F (`guard.py:1466`) |
| Effective exposure budget (advisory) | n/a | **30% × gross_scalar × regime_mult** | Advisory layer |
| Max concurrent positions | "2" (wrong) | **Unconstrained** — see §6.1 | **Not gated** |
| Max positions per sector | none | **1** | Gate I (**new**) |
| Max trades per day | 2 | **2** (unchanged) | Gate D (`guard.py:1348`) |
| Daily loss halt | −1% NL | **−1% NL** (unchanged) | Gate E (`guard.py:1357`) |
| Weekly loss halt | −3% NL | **−3% NL** (unchanged) | Gate E |
| Min cash reserve | 70% NL | **≥70% NL** (unchanged) | Implied by Gate F |
| Leverage | none | **none — formally rejected (§3)** | Invariant 8 |
| Volatility reference constant | none | **16% annualized** (advisory) | Advisory layer |

### 6.1 Resolution of the position-count contradiction

> **Design-review correction (v0.2).** An earlier draft of this section asserted the answer
> was **6**. That was wrong in the same way v1.0.0's **2** was wrong, and is corrected here.

`strategy_v1.md` §8 claims a maximum of 2 concurrent positions and attributes it to the
exposure and per-position caps. That attribution is invalid. But `30 ÷ 5 = 6` is **also**
not a position-count limit, for a reason the earlier draft missed:

Final size is `min(notional_cap_shares, risk_cap_shares)` (`compute_final_max_shares`,
`guard.py:1268`). When the **risk** cap binds — which it does for higher-volatility names,
since a wider ATR stop shrinks `risk_cap_shares` — the resulting position is **smaller than
5%** of NetLiquidation. More such positions therefore fit inside the same 30% ceiling.

| Scenario | Binding cap | Position size | Positions before 30% binds |
|---|---|---|---|
| Low-vol name, tight stop | notional | 5.0% | 6 |
| Moderate-vol name | risk | ~3.5% | ~8 |
| High-vol name, wide stop | risk | ~2.0% | ~15 |

**Therefore: `6` is the maximum number of _full-size_ positions, not the maximum number of
positions.** The true count is unbounded above 6 and depends entirely on per-position
sizing.

**Resolution (Chris-approved, design review):** position count stays **unconstrained**, and
this document records that as a deliberate choice rather than a derived number. Gate B
bounds each position at 5% and Gate F bounds the aggregate at 30% — together these bound
total risk regardless of how many positions exist. Adding `max_concurrent_positions` would
introduce a parameter that constrains nothing Gates B and F do not already constrain, which
fails `strategy_v1.md` §15 anti-overfit check 6 (prefer fewer parameters).

**Consequence for `strategy_v1.md` §8:** the row "Maximum positions open simultaneously | 2"
must be corrected to "Not directly constrained — bounded indirectly by Gates B and F" when
v1.1 is promoted. Until then, v1.0.0 retains the incorrect row, and this document is the
record of the defect.

Note that Gate I (§4.7) *does* impose an indirect structural ceiling: at **1 position per
sector** across **11 sector groups**, no more than 11 positions can be held simultaneously.
That ceiling is not the binding constraint in practice — Gate F's 30% exposure limit binds
first at roughly 6 full-size positions — and it constrains sector *composition* rather than
portfolio size. The point stands: no gate caps position count directly.

### 6.2 Transition of existing positions

v1.1 activation must not force liquidation. Existing positions at the moment of promotion
are **grandfathered**:

| Aspect | Treatment |
|---|---|
| Force-close on activation | **No** — never triggered by a strategy version change |
| Re-validation against new entry filters (RS rank, regime, 2-of-4) | **No** — entry filters gate *entries*, not holdings |
| Counted toward Gate F total exposure | **Yes** |
| Counted toward Gate I sector cap | **Yes** — an existing position occupies a sector slot |
| Counted toward the advisory effective budget (§4.6) | **Yes** |
| Exit management | v1 §12 unchanged — existing stops, 2R partial, §12.3 invalidation triggers |
| Symbol no longer in the allowlist | Position may still be **closed** (SELL is close-only and Gate A applies to entries) |

**Worked example.** The position recorded in the CLAUDE.md §10 snapshot — META, 72 shares —
is Communication Services. Under `max_positions_per_sector = 1` it occupies **the only** Gate
I slot for that sector, so **no further Communication Services entry is possible while it is
held** — GOOGL would be rejected by Gate I even if it topped the RS rank. META itself is not
re-tested against the RS rank or regime gate, and its existing protective stop stands
unchanged.

This is the intended behavior: a grandfathered position consumes its sector's slot exactly
as a new one would, so activation cannot quietly double a sector bet.

**Verify against live state, not this document.** Per CLAUDE.md §0, position data here is a
stale snapshot. Confirm actual holdings via `ibkr_positions` or `GET /positions` at
activation time and recompute sector occupancy from that.

---

## 7. MSTR / BTC Disposition

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

### 8.1 Paper-mode P&L is upward-biased

| Bias | Direction | Why |
|---|---|---|
| No queue position modeling | Optimistic | Paper fills assume you were first |
| No partial fills | Optimistic | Real partials fragment risk and count as one trade (invariant 15) |
| No market impact | Optimistic | Size moves price in reality |
| Stop fills through gaps | Optimistic | Paper stops fill near trigger; real gaps skip |
| Delayed quotes | Distorting | Paper account quotes are delayed; entry references shift |

So the P&L that *is* produced is biased high on top of being statistically meaningless.

### 8.2 Corollary — a backtest Sharpe above ~1.5 should increase suspicion

With <200 trades and multiple variants tried, a high in-sample Sharpe is far more likely to
indicate overfitting than edge. `strategy_v1.md` §15 already encodes the right response;
apply a multiple-testing haircut before believing any figure.

---

## 9. Implementation Plan

Phased to match the existing Phase 18 governance chain. **No phase may be skipped, and each
requires its own CI test module.**

### 9.1 Phase 19A — Documentation only (this document)

| Item | Status |
|---|---|
| This proposal document | Delivered |
| Code changes | **None** |
| YAML changes | **None** |
| Guard changes | **None** |
| Model tier required | Tier 2 (docs) |

### 9.2 Phase 19B — YAML allowlist and advisory config (Chris only)

**Werner does not perform this step** (invariant 6). Chris applies it per RUNBOOK §L8.

Changes to `~/.openclaw/risk-rules/paper-trading-rules.yaml`:

```yaml
symbol_allowlist:
  mode: explicit_list        # unchanged — validated at guard.py:4036
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

# NEW — sector map for Gate I (§4.7)
symbol_sectors:
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

# NEW — Gate I parameter (§4.7). Value 1: momentum clusters by sector, so a
# cap of 2 would let the ranker fill two slots with one bet (NVDA+AMD).
max_positions_per_sector:
  value: 1

# NEW — advisory-only section; guard does NOT enforce these
# Resolves the CLAUDE.md §5 "H3 follow-up" note by giving advisory
# parameters a home in the same source file.
advisory:
  # Inverse-vol scalar (§4.6). NOT a portfolio vol target — see §4.6.1.
  # Recalibrate to SPY's measured median 20d realized vol before promotion.
  vol_reference_pct: 16
  vol_lookback_days: 20
  gross_scalar_floor: 0.25
  regime_sma_days: 200
  regime_momentum_months: 12
  regime_caution_multiplier: 0.5
  cross_sectional_rs_lookback_days: 60
  cross_sectional_rs_top_fraction: 0.5
  reference_symbol: SPY          # bars-only; never order-eligible
  reference_bar_duration: "1 Y"  # required — the "30 D" default is insufficient (§4.10)
  min_reference_bars: 252
  min_symbol_bars_for_rs: 60
  min_valid_symbol_fraction: 0.5 # below this -> NO_TRADE for the cycle (§4.10)
  hermes_risk_per_trade_pct: 0.25
```

Optional H4.1 blocklist extensions (see §11.1):

```yaml
# OPTIONAL. Extends the regulatory baseline hardcoded in guard.py.
# Absence, emptiness, or malformation all resolve to the baseline alone —
# this section can only ADD symbols, never remove them.
us_etf_blocklist:
  mode: extend_regulatory_baseline
  symbols: []
```

**Backward compatibility verified.** The rules loader (`guard.py:4015`) validates that
*required* keys are present — `missing = [k for k in required_keys if k not in rules]` — and
does **not** reject unknown keys. Adding `symbol_sectors`, `max_positions_per_sector`,
`advisory`, and `us_etf_blocklist` is therefore safe in 19B while `guard.py` is otherwise
unmodified. `us_etf_blocklist` is deliberately **not** added to `required_keys`, so a missing
section can never prevent the bridge from starting.

**Note:** the `advisory` block also discharges the H3 follow-up recorded in CLAUDE.md §5
(move the Hermes 0.25% advisory target into the YAML so the two-tier risk model has one
source file).

Validation: `guard.py:4015` already asserts the presence of required top-level keys.
Adding `symbol_sectors` and `max_positions_per_sector` to that required-keys list is part
of Phase 19D, not 19B — so 19B must land first and remain backward-compatible.

### 9.3 Phase 19C — Advisory layer (`hermes_advisory.py`)

Compute and *report* the regime state, gross scalar, and RS ranks. **Advisory only — no
gate, no order path.** Recommended model tier: **Tier 1**, because although
`hermes_advisory.py` is not in the CLAUDE.md §6 Tier-1 file list, this logic is
sizing-adjacent.

| Function to add | Responsibility |
|---|---|
| `fetch_reference_bars()` | Read SPY bars via bridge `market/bars`; reuse `fetch_bars` pattern (`guard.py:820`) |
| `compute_realized_vol(bars, lookback)` | Annualized stdev of daily log returns |
| `compute_regime_state(bars)` | Return `RISK_ON` / `CAUTION` / `RISK_OFF` per §4.5 |
| `compute_gross_scalar(sigma_ref, cfg)` | `clamp(target/σ̂, floor, 1.0)` per §4.6 |
| `compute_effective_budget(rules, cfg)` | `30% × gross_scalar × regime_mult`; **must assert result ≤ YAML ceiling** |
| `rank_cross_sectional_rs(symbols, lookback)` | 60-day return rank; return top-half set |
| `build_proposal(...)` | Emit `{rank, thesis, invalidation_condition}` — **never** a size or leverage |

**Mandatory assertion:** `compute_effective_budget` must raise if its output exceeds
`max_total_exposure`. The advisory layer must be structurally incapable of loosening.

### 9.4 Phase 19D — Gate I in `guard.py` (Tier 1 required)

Per CLAUDE.md §6, `guard.py` edits require a Tier-1 model and a Chris-approved, git-tagged
change.

```python
def gate_sector_concentration(symbol: str, positions: list, rules: dict) -> tuple:
    """Gate I — reject BUY if the candidate's sector is already at capacity.

    Fails CLOSED: a symbol with no sector mapping is rejected.
    SELL is exempt (close-only reduces concentration).
    """
```

Placement: alongside the existing gate functions, after `gate_exposure`
(`guard.py:1466`). Registration requirements:

| Requirement | Detail |
|---|---|
| Gate letter | **I** — verified free: `guard.py` defines A–H, with H = `gate_proposal_discipline` (`guard.py:1771`). `gate_open_orders` (`guard.py:1959`) carries no letter. |
| Applies to | BUY only — SELL exempt, consistent with Gate G close-only logic |
| Fail mode | **Closed** — unmapped symbol is rejected, matching `gate_allowlist` behavior |
| Required-keys update | Add `symbol_sectors`, `max_positions_per_sector` at `guard.py:4015` |
| Validation | Every allowlisted symbol must have a sector mapping, else raise at load |
| No hardcoded duplicates | Sector map and cap read from YAML at enforcement time (H2 invariant) |

### 9.5 Phase 19E — Test plan

Following the existing convention (`tests/test_phase18b_level1_data_schema_provider_governance.py`):

| Test module | Coverage |
|---|---|
| `test_phase19a_strategy_v1_1_proposal_governance.py` | Proposal metadata, status `PROPOSED`, `execution_scope: NONE`, doc hashes, canonical v1 unchanged |
| `test_phase19b_allowlist_expansion.py` | 22 symbols load; every symbol has a sector; `mode: explicit_list` preserved; unknown symbol still fails Gate A |
| `test_phase19c_advisory_vol_regime.py` | Vol math on known series; regime state truth table (4 cases); `gross_scalar` clamped to [0.25, 1.0]; **effective budget never exceeds YAML ceiling** (property test) |
| `test_phase19d_gate_i_sector_cap.py` | 2nd position in a sector rejected; 1st allowed; SELL exempt; unmapped symbol fails closed; semis treated as distinct from IT; grandfathered position occupies its sector slot |
| `test_phase19e_invariant_preservation.py` | All CLAUDE.md §3 invariants still hold; `/order` still 403; switches still default off; sizing formula unchanged |

**Required property test:** for randomized `σ̂_ref ∈ (0, 200%]` and all three regime
states, assert `effective_budget ≤ max_total_exposure`. This is the single most important
test in the set — it proves the advisory layer cannot loosen the guard.

### 9.6 Operator CLI checkpoint command

Every prior governance phase registers a read-only `ibkr-operator` subcommand — `phase17a`,
`phase18a`, `phase18b`, `phase18r1` — and the corresponding test modules assert that
`<command> --help` succeeds. Phase 19A follows the same convention:

| Item | Value |
|---|---|
| Canonical command | `level1-strategy-v1-1-proposal-governance-checkpoint` |
| Aliases | `phase19a`, `strategy-v1-1-proposal` |
| Flags | `--json`, `--export` |
| Behavior | **Read-only.** Verifies documents exist, manifest parses, hashes match, governance fields valid; emits a diagnosis code from `phase19a_diagnosis` |
| Must not | Call any IBKR or `/order*` endpoint, read the H1 token, or mutate any file except an explicit `--export` evidence file |

**Blocker resolved — 2026-08-01.** `ibkr_operator.py` previously defined `main()` **twice**
(lines 49762 and 52332), the second shadowing the first. Adding a `phase19a` command before
that was resolved risked registering it in the dead copy, where it would silently never run.

The de-duplication is complete. The removed region — a repeated section header,
`_PHASE18B_DIAGNOSIS`, `_PHASE18B_CHECKPOINT_SCRIPT`, `_phase18b_no_go`, a 32-line stub of
`_run_level1_data_schema_provider_governance_checkpoint`, and the shadowed `main()` — totalled
**1,800 lines**. The dead `main()` registered 195 subcommands, a **strict subset** of the live
`main()`'s 205, so no command was lost.

| Verification | Result |
|---|---|
| Duplicated top-level names | 3 → **0** |
| `main()` definitions | 2 → **1** |
| Subcommands via `--help` | 205 → **205** (list identical) |
| `--help` output | **byte-identical** |
| `py_compile` on `bridge.py`, `guard.py`, `ibkr_operator.py` | pass |
| `phase18a` / `phase18b` / `phase18r1` execution | all exit 0 |

The `phase19a` command is therefore **unblocked and pending implementation**. It remains a
non-blocker for 19B, because the CLI checkpoint is a convenience wrapper over checks that
`test_phase19a_strategy_v1_1_proposal_governance.py` already performs directly.

**Note on the live implementation.** The dead copy's
`_run_level1_data_schema_provider_governance_checkpoint` was a 32-line stub that shelled out
to an external `level1-data-schema-provider-governance-checkpoint` script via
`_PHASE18B_CHECKPOINT_SCRIPT`. The live copy (341 lines) implements the checkpoint inline and
does not reference that path. Removing the stub removed the only consumer of that constant.

### 9.7 Rollback procedure

Rollback must run in **reverse dependency order**. The ordering is load-bearing, not
cosmetic: once 19D adds `symbol_sectors` and `max_positions_per_sector` to the required-keys
list, removing them from the YAML makes `guard.py` raise at load.

| Rolling back | Procedure | Constraint |
|---|---|---|
| 19E | Revert test commit | None |
| 19D | `git revert` the tagged Gate I commit | **Must precede any 19B rollback** |
| 19C | `git revert` the advisory commit | Independent |
| 19B | Restore `symbol_allowlist.allow` to AAPL, META, NVDA, AMD; remove `symbol_sectors`, `max_positions_per_sector`, `advisory` | **Only after 19D is reverted** |

**Partial rollback of 19B alone** (narrow the allowlist, keep the machinery) is always safe:
removing symbols from `symbol_allowlist.allow` cannot break Gate A, which fails closed by
design. Existing positions in removed symbols remain closeable per §6.2.

**No rollback is required for 19A.** It is documentation only; reverting the commit is
sufficient and has no runtime effect.

### 9.8 Dependency order

```
19A (docs)  →  19B (YAML, Chris)  →  19C (advisory)  →  19D (Gate I, Tier 1)  →  19E (tests)  →  paper run (§10)
```

19D must not land before 19B, or `guard.py` will raise on missing required keys at load.
Rollback runs in the reverse of this order (§9.7).

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

**Status (v0.4):** 11.1, 11.2, 11.3, and 11.4 are **RESOLVED**. 11.5 and 11.6 remain
**OPEN** and block promotion.

| # | Decision | Status |
|---|---|---|
| 11.1 | H4.1 ETF BUY block | **RESOLVED** — keep; it is PRIIPs law, not preference |
| 11.2 | Maximum concurrent positions | **RESOLVED** — unconstrained |
| 11.3 | Final allowlist composition | **RESOLVED** — 22 names, Gate I at 1/sector |
| 11.4 | Volatility reference value | **RESOLVED** — 16%, renamed |
| 11.5 | MSTR/BTC disposition | **OPEN** |
| 11.6 | Meaning of "learning" | **OPEN** |

### 11.1 H4.1 — the ETF BUY block — RESOLVED

**Decision: KEEP. Single-name only. The block is law, not preference.**
Approved 2026-08-01.

The v0.1 draft framed this as a discretionary "keep or lift" choice, on the strength of
`strategy_v1.md` §3 describing it as a *"Structural regulatory/prudence block"* and
`STRATEGY.md` calling it a *"regulatory/prudence gate."* The word **prudence** is wrong.

`guard.py` enforces H4.1 in code, and its rejection message states the actual basis:

```
Symbol 'SPY' is a US-domiciled ETF — blocked for EU paper
account DUQ542875 under KID/PRIIPs regulation.
```

Under the EU PRIIPs Regulation a US-domiciled ETF may not be distributed to an EU retail
investor, because US issuers do not produce a Key Information Document. **IBKR enforces this
independently.** Lifting the guard block would not unlock the instrument; it would only
model orders a live account would reject, corrupting the paper record's value as evidence of
real executability.

Enforcement is genuine, not documentary: a 39-symbol regulatory baseline plus a
contract-level check rejecting any `secType == "ETF"` on a US exchange. BUY only — SELL
closes pass, consistent with Gate G.

#### 11.1.1 The real constraint is two rules interacting

Index exposure is foreclosed by a *pair* of rules, only one of which is law:

| Route | Blocked by | Nature |
|---|---|---|
| US-domiciled ETF (SPY, QQQ) | H4.1 / PRIIPs | **Legal** — not waivable |
| UCITS ETF (EQQQ, CSPX, SXR8) | `strategy_v1.md` §3 "Non-US equities" | **Policy** — waivable in principle |

EU-domiciled UCITS ETFs are the legitimate index route for an EU investor: they produce a
KID and are legal to hold. They are blocked only by the non-US-equities rule.

That route is not a small change, which is why it is not taken here. UCITS ETFs trade on
LSE, Xetra, and Euronext, while `strategy_v1.md` §4 hardcodes RTH as **9:30–16:00 ET**.
Xetra runs 09:00–17:30 CET and LSE 08:00–16:30 GMT, so admitting them breaks the session
model, both entry-blackout windows, and introduces GBP/EUR handling beyond the existing
EUR/USD conversion. That is a v1.2+ programme, not a YAML edit.

**Consequence for v1.1:** none. All 22 proposed symbols are single names, so Gate A and
H4.1 are unaffected either way. The vol-targeted index-trend family remains permanently
unavailable to this account, and §4.1's claimed edge sources are correspondingly limited to
what single names can express.

#### 11.1.2 Corrections owed to `strategy_v1.md` at promotion

Phase 19A must not modify the canonical strategy — `canonical_strategy_unchanged` is `true`
and the 19A test module enforces it. These corrections are therefore **obligations recorded
against v1.1.0 promotion**, applied when that document is rewritten:

1. §3 — replace "Structural regulatory/prudence block" with the accurate basis:
   **KID/PRIIPs regulation, EU account, enforced by IBKR independently.**
2. §2 — **remove** "Non-leveraged, non-inverse US-listed ETFs (advisory-only placeholder)".
   Under PRIIPs that line can never become true for this account, and leaving it implies a
   future availability that does not exist. This closes `V1_DEFECT_H4_1_TENSION`.
3. §3 — record UCITS ETFs as the identified legal index route, explicitly deferred.

### 11.2 Maximum concurrent positions — RESOLVED

**Decision: leave position count unconstrained and document it as a deliberate choice.**
Approved at design review.

The design review established that neither v1.0.0's **2** nor the earlier draft's **6** is a
valid position-count limit (§6.1). Gate B bounds each position at 5% of NetLiquidation and
Gate F bounds the aggregate at 30%; together they bound total risk irrespective of position
count. A `max_concurrent_positions` parameter would constrain nothing those two gates do not
already constrain, and would fail `strategy_v1.md` §15 anti-overfit check 6.

Follow-up obligation: correct the erroneous row in `strategy_v1.md` §8 when v1.1 is promoted.

### 11.3 Final allowlist — RESOLVED

**Decision: keep all 22 names; tighten Gate I to 1 position per sector.**
Approved 2026-08-01.

**On list size.** 22 is retained. The concern that it is "too many to follow attentively"
does not survive inspection of the workflow: Hermes ranks the universe and surfaces a single
proposal, so the review burden is one candidate per cycle regardless of universe size. The
real costs are 22 bar requests per cycle plus SPY — comfortably inside IBKR's historical-data
pacing limits — and more opportunities for a data-quality failure, which §4.10's
"<50% valid → `NO_TRADE`" rule already handles. The benefit is rank resolution: the top-50%
filter selects from 11 candidates instead of 2.

**On size verification.** Market capitalisation was checked against live data for 14 of the
22 names on 2026-07-31; the smallest verified were UNH (~$376B) and KO (~$377B), both far
above the `strategy_v1.md` §2 threshold of $10B. The remaining 8 (AVGO, LLY, PG, HD, CAT,
UNP, NEE, DUK) could not be verified in-session because the market-data plan gated further
requests. They are unambiguous large caps, but **the check should be completed before 19B
applies the list.**

**On the semiconductor split.** Retained. Treating semis as distinct from Information
Technology is what makes Gate I able to separate NVDA/AMD from MSFT/AAPL, giving 11 sector
groups rather than 10.

**On composition.** No symbol substitutions. The four near-duplicate pairs identified in
§4.7.1 — NVDA/AMD, META/GOOGL, JPM/BAC, XOM/CVX — are handled structurally by the 1-per-sector
cap rather than by removing names. Keeping both members of each pair preserves optionality:
the ranker chooses whichever is stronger, and the cap ensures only one is held.

**Deferred:** substituting BAC for a differentiated financial (V or BRK.B) would give the
Financials sector two genuinely different drivers rather than two money-center banks,
improving the *quality* of the choice within that sector rather than the risk of the
resulting position. Logged as a v1.2 candidate; not required, because Gate I already prevents
holding both.

### 11.4 Volatility reference value — RESOLVED

**Decision: `vol_reference_pct = 16%`, and the parameter is renamed from
`portfolio_vol_target_pct`.** Approved at design review.

Design review found the earlier `12%` value defective on two counts (§4.6.1): it was
mislabeled as a portfolio volatility target when the portfolio can only reach ~6.6%
volatility at full gross, and at 12% the scalar applied a permanent ~25% haircut in calm
markets instead of responding to stress. Setting the constant near SPY's long-run median
(~16%) makes the mechanism dormant in calm conditions and responsive when volatility rises.

Outstanding obligation: this remains a *reference* estimate. Recompute SPY's median 20-day
realized volatility over ≥5 years from bridge `market/bars` and set the constant to that
measured value before promotion. Do not optimize it against strategy P&L.

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
| 6 | Parameter count direction? | **Increase of 7** (RS lookback, 200d SMA, 12m momentum, `vol_reference_pct`, vol lookback, scalar floor, sector cap). All conventional, none fitted. A `max_concurrent_positions` parameter was **rejected** at design review under this same check (§11.2). Justified by §1.1 breadth arithmetic. |
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

To move from `PROPOSED` to active `v1.1.0`:

1. **Chris's explicit approval** of this document
2. **Open decisions §11 resolved** — at minimum 11.1, 11.2, 11.3
3. **Phase 19B applied by Chris** — YAML allowlist and advisory config
4. **Phase 19C and 19D implemented** — 19D under a Tier-1 model with a git-tagged commit
5. **Phase 19E green** — all five test modules pass, including the budget-ceiling property test
6. **Out-of-sample and walk-forward evidence** satisfying §15 checks 2, 4, and 7
7. **Paper validation §10.1 complete** — all 15 plumbing checks positively exercised
8. **Invariants re-verified** — CLAUDE.md §3 (1–17) confirmed intact via `ibkr-status` and `GET /status`
9. **Version bump** — `strategy_version: v1.1.0`, changelog entry in `docs/strategy_v1_changelog.md`

No step may be skipped or reordered. Execution scope remains `NONE` until a separate,
explicit governance action changes it.

---

## 15. Summary

| Question | Answer |
|---|---|
| Is the MSTR/BTC strategy fine? | There is no such strategy — it is `PROPOSED`/S0 with `execution_scope: NONE` (§7.1) |
| Does it need an update? | It should stay parked. Highest infra cost, lowest breadth gain, and it is instrument-embedded leverage (§7.2–7.4) |
| Is the QQQ fallback fine? | It is forbidden three ways and does not exist in code (§7.5) |
| Would more stocks help? | Yes — but along the **correlation** axis, not ticker count. 4 → 22 across 10 sectors raises independent bets ~1.3 → ~6.5 (§1.1, §4.2) |
| Is a 1–20× leverage agent better? | No. Above ~3× expected compound growth is negative regardless of edge; at 20× ruin is certain and no valid stop distance exists (§3) |
| What is the highest-value change? | Allowlist breadth (a YAML edit), then the regime gate, then portfolio vol targeting (§9) |
| Will paper mode teach the bot? | No. It validates plumbing, not edge — edge needs ~4 years at SR 1.0 (§8, §10) |

**Core design property:** every mechanism v1.1 introduces can only *reduce* exposure below
the YAML ceiling. The guard's hard limits are untouched, `gate_exposure` still enforces 30%
independently, and the advisory layer is structurally incapable of loosening anything.

---

## Document Metadata

| Field | Value |
|---|---|
| Document ID | `STRATEGY_V1_1_PROPOSAL_v0_1` |
| Proposal ID | `strategy_v1_1_proposal_v0_1` |
| Companion manifest | `docs/strategy-proposals/strategy_v1_1_proposal_v0_1.manifest.json` |
| Governance Level | Level 1 (advisory-only, design documentation) |
| Phase | 19A |
| Phase Boundary | `PHASE19B_ALLOWLIST_AND_ADVISORY_CONFIG` |
| Target Strategy Version | `v1.1.0` (inactive) |
| Canonical Strategy | `docs/strategy_v1.md` (v1.0.0 — unchanged) |
| Supersedes | None |
| Superseded By | None |
| Review Cadence | On demand; required before any promotion |
| Model Tier Used | Tier 2 (documentation only — no safety-critical code touched) |
| Proposal series identifier | `v0_1` — **stable**. The `v0_1` in the filename and `proposal_id` identifies the proposal *series* and does not change with revisions; `proposal_version` (currently `0.2`) tracks revisions within it. This mirrors the 18A pattern, where `proposal_id` embeds the series tag. |

### Version History

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-07-25 | Initial proposal — breadth expansion, regime gate, volatility targeting, Gate I sector cap, leverage rejection, MSTR/BTC disposition, paper-run validation protocol |
| 0.4 | 2026-08-01 | **Decision 11.3 resolved.** Kept all 22 names and tightened Gate I from 2 to **1 position per sector** (§4.7.1): momentum clusters by sector, so a cap of 2 would let the relative-strength filter fill two slots with one bet (NVDA+AMD, JPM+BAC). **Corrected the §1.1 breadth claim**, which overstated the IR gain as 2.24× — the defensible figures from `N_eff = n/(1+(n−1)ρ̄)` are **1.24× directional** and **1.52× on the selection sleeve**, so the expansion buys selection breadth, not diversification of market risk. Updated §6.1 (Gate I imposes an indirect 11-position ceiling), §6.2 (a grandfathered position now consumes its sector's only slot), and the 19D test expectations. |
| 0.3 | 2026-08-01 | **Decision 11.1 resolved — KEEP H4.1.** Established that H4.1 is KID/PRIIPs regulation enforced in `guard.py` and independently by IBKR, not the discretionary "prudence" block the v0.1 draft assumed, so "lift" was never a viable option. Documented that index exposure is foreclosed by two interacting rules — PRIIPs (law) and the non-US-equities rule (policy) — and identified EU-domiciled UCITS ETFs as the legal route, deferred to v1.2+ because non-US venues break the 9:30–16:00 ET session model. Recorded three corrections owed to `strategy_v1.md` at promotion. Separately fixed an H2 violation: the hardcoded `_US_ETF_BLOCKLIST` is now `regulatory baseline | YAML extensions`, where the YAML can only add symbols and never shrink the floor. |
| 0.2 | 2026-07-27 | **Design review applied.** Six defects corrected. §6.1: withdrew the incorrect "6 concurrent positions" claim — position count is unconstrained (§11.2 resolved). §4.6/§4.6.1: renamed `portfolio_vol_target_pct` → `vol_reference_pct` and corrected 12% → 16%; the earlier value was mislabeled and permanently binding (§11.4 resolved). §4.10 added: data-quality thresholds and fail-safe rules for the new signals. §6.2 added: grandfathering of existing positions. §9.6 added: operator CLI command, blocked pending `main()` de-duplication. §9.7 added: reverse-order rollback procedure. Gate letter I verified free against `guard.py`. YAML backward compatibility verified against the rules loader. |
