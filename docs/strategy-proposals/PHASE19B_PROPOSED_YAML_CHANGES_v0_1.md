# Phase 19B — `paper-trading-rules.yaml` Changes — APPLIED LIVE (2026-08-10)

> **Status: confirmed applied to the live bridge host.** Chris made this edit himself on
> `/home/chris/.openclaw/risk-rules/paper-trading-rules.yaml`, per CLAUDE.md invariant 6 —
> Werner walked through the diff but never wrote the file. Verified field-by-field via
> Werner's read-only output (headers, `grep`/`sed` extracts, `yaml.safe_load()` parse check,
> `/health`, `/readiness`) on 2026-08-10:
>
> - `symbol_allowlist.allow` — exactly the 22 symbols below, correct order, rationale text
>   updated (no longer says "three symbols validated in Phase 1")
> - `symbol_sectors` — 22 entries, exact 1:1 match with the allowlist, no orphans/extras,
>   10 distinct sectors
> - `max_positions_per_sector.value: 1` — present, no numbering collision with the file's
>   existing rule 10 (landed as sub-rules `9a`/`9b`)
> - `advisory` — all 14 fields present, correctly nested, `vol_reference_pct: 13`
> - NOTES block updated with the Phase 19B line
> - `yaml.safe_load()` parses cleanly; `/health` and `/readiness` unaffected (still
>   `startup_safety: 11/11`, no drift, no new blocks) both before and after the full edit
>
> This document is kept below as the historical draft/spec this was applied from. Per
> CLAUDE.md invariant 6, Werner never modified `.env` or `paper-trading-rules.yaml` at any
> point in this process — this document exists so Chris could copy the block below into
> `~/.openclaw/risk-rules/paper-trading-rules.yaml` on the bridge host himself, per
> RUNBOOK §L8, which is what happened.
>
> Content verbatim from `STRATEGY_V1_1_PROPOSAL_v0_1.md` §9.2, cross-checked 2026-08-06
> against `strategy_v1_1_core.py`'s `FROZEN_UNIVERSE` and advisory defaults on
> `phase19b-strategy-v1-1-implementation` — the 22-symbol/11-sector map and every advisory
> constant match exactly between the two; no drift found.
>
> **2026-08-06 update:** one parameter, `vol_reference_pct`, has been recalibrated from
> real SPY price history per the proposal's own §4.6.1 instruction ("recompute SPY's
> median 20-day realized volatility... over at least 5 years and set the constant to that
> measured median"). See **Methodology** below. Every other advisory parameter is left at
> the proposal's conventional/field-standard value on purpose — §4 and design principle 4
> forbid fitting them, and doing so would violate the proposal's own anti-overfit
> discipline. See **Why the rest stay put**.

## What changes

| Key | Before | After |
|---|---|---|
| `symbol_allowlist.allow` | 4 symbols (AAPL, META, NVDA, AMD) | 22 symbols (§4.2) |
| `symbol_sectors` | *(absent)* | **NEW** — 22-symbol → 11-sector map, for Gate I |
| `max_positions_per_sector` | *(absent)* | **NEW** — `value: 1` |
| `advisory` | *(absent)* | **NEW** — regime/vol/RS constants, non-enforced (`vol_reference_pct` recalibrated to `13` from real SPY data, not the proposal's `16` placeholder — see Methodology) |
| `us_etf_blocklist` | *(absent)* | **OPTIONAL** — extends the regulatory baseline only |

`symbol_sectors` and `max_positions_per_sector` are **not yet** in `guard.py`'s
`required_keys` list — that addition is Phase 19D, which must land *after* this YAML is
live (§9.9 dependency order). Landing this YAML alone, with `guard.py` unmodified, is
backward-compatible: the loader only checks that required keys are present, and does not
reject unknown ones.

## Proposed content

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

# NEW — advisory-only section; guard does NOT enforce these.
# Resolves the CLAUDE.md §5 "H3 follow-up" note by giving advisory
# parameters a home in the same source file.
advisory:
  # Inverse-vol scalar (§4.6). NOT a portfolio vol target — see §4.6.1.
  # RECALIBRATED 2026-08-06 from real SPY history (was 16, the proposal's
  # placeholder reference estimate) — see "Methodology" below. Median
  # 20-trading-day annualized realized vol, 2019-01-02 to 2026-08-06
  # (source: FMP historical-price-eod-full, not the IBKR bridge — recompute
  # from bridge market/bars before this ever gates a live paper cycle).
  vol_reference_pct: 13
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

### Optional — H4.1 blocklist extension (§11.1)

```yaml
# OPTIONAL. Extends the regulatory baseline hardcoded in guard.py.
# Absence, emptiness, or malformation all resolve to the baseline alone —
# this section can only ADD symbols, never remove them.
us_etf_blocklist:
  mode: extend_regulatory_baseline
  symbols: []
```

1. **Resolved (2026-08-06):** two independent implementations of the regime/vol/RS/Gate-I
   logic existed unmerged — `strategy_v1_1_core.py` on
   `phase19b-strategy-v1-1-implementation`, and `hermes_advisory.py` + `guard.py` Gate I on
   `phase19c-advisory-layer`. Chris decided `strategy_v1_1_core.py` is canonical;
   `phase19c-advisory-layer` is superseded and will not be merged. This doesn't change the
   YAML content above — both implementations read the identical
   `symbol_sectors`/`max_positions_per_sector`/`advisory` shape.
2. **Do not merge Phase 19D (`guard.py` Gate I / required-keys change) before this YAML is
   live on the bridge host.** Once `required_keys` includes `symbol_sectors` and
   `max_positions_per_sector`, the bridge will refuse to start without them present in the
   live file (§9.9).
3. Validate with `guard.py`'s existing loader semantics before/after: unknown keys are
   never rejected, so applying this alone (with `guard.py` unmodified) cannot break
   startup.
4. `vol_reference_pct` below has been recalibrated from real data (see Methodology) — it
   is no longer the proposal's `16` placeholder. **Recompute it again from the IBKR
   bridge's own `market/bars` before this ever gates a live paper cycle** — FMP data is a
   real, independent, non-IBKR source, sufficient for this design-time recalibration, but
   CLAUDE.md §8 still names IBKR as ground truth for anything that actually sizes a trade.

## Methodology — `vol_reference_pct` recalibration

The proposal (§4.6.1) explicitly instructs recalibrating this constant from data, and
explicitly forbids fitting it to strategy P&L: *"recompute SPY's median 20-day realized
volatility from bridge `market/bars` over at least 5 years and set the constant to that
measured median. Do not optimize it against strategy P&L — pick it from the volatility
distribution alone."* The bridge isn't reachable from this session, so the recomputation
below uses FMP's `historical-price-eod-full` endpoint for SPY as a real, independent
substitute — label it as such, not as IBKR-sourced, per CLAUDE.md §8.

**Data:** SPY daily OHLCV, 2019-01-02 through 2026-08-06 (1,909 daily bars, ~7.6 years).
**Method:** daily log returns → 20-trading-day rolling window → population stdev ×
`√252` (annualized) → median of that rolling series.

| Window | n obs | Median | Mean |
|---|---:|---:|---:|
| Full sample (2019-01-02 – 2026-08-06, incl. 2020 COVID crash) | 1,889 | **13.23%** | 15.87% |
| Last ~5 years (2021-08-02 onward) | 1,239 | **13.40%** | 15.25% |
| 2021-01-01 onward (excludes 2020 entirely) | 1,384 | **13.26%** | 14.94% |

All three windows — full sample, last-5-years, and with the 2020 crash excluded entirely —
agree to within 0.2 points: **median ≈ 13%**. The mean runs 2-3 points higher in every
window because it is pulled up by the fat right tail (max observed: 91.86% during the
2020 crash) — exactly why the proposal specifies *median*, not mean, as the calibration
target. `vol_reference_pct` is set to **13** (rounded from 13.2-13.4%), down from the
proposal's `16` placeholder, which was already flagged there as "SPY's typical realized
volatility is ~15-16% *(reference)*" — closer to the mean than the median.

**Why this matters mechanically:** `gross_scalar = clamp(vol_reference_pct / σ̂_ref, 0.25, 1.00)`.
A lower reference constant means the scalar clamps to 1.00 (full budget) only when
realized vol is at or below 13%, rather than 16% — i.e. it starts tightening exposure
*sooner* as volatility rises, matching where SPY's volatility distribution actually sits
rather than its less-typical elevated tail. This is a **tightening** change only — it can
only reduce the advisory-suggested budget relative to the placeholder, never increase it,
consistent with design principle 1 ("the advisory layer may only tighten, never loosen").

**Where the `13` actually lives.** `strategy_v1_1_core.py`'s own `DEFAULT_VOL_REFERENCE_PCT`
module constant is left at `16.0` — B2's `TestComputeGrossScalar`/`TestGrossScalarExtended`
hardcode numeric assertions built on that exact default (e.g. `compute_gross_scalar(0.20)`
→ `0.8`, which is `0.16/0.20`), so changing the constant would break frozen tests for no
functional gain. HIQ-008 already documents that `vol_reference_pct` "comes from advisory
config" at runtime — the module default is only a fallback for callers that omit it. The
recalibrated `13` belongs in, and is sourced from, the YAML `advisory.vol_reference_pct`
value above; that's what a future B4 wiring pass would actually pass in.

## Why the rest stay put

Design principle 4 states plainly: *"Conventional parameter values only. 200-day SMA,
12-month momentum, ATR(14) — no fitted values, no optimization over the backtest."* And
§4.3: the 60-day RS lookback is *"conventional value, not fitted."* Refitting any of these
against a backtest — even a well-intentioned one — would violate that discipline and the
`strategy_v1.md` §15 anti-overfit check the proposal holds itself to. So "financially/
scientifically best" for these means *keep the literature-standard value*, not search for
a better-looking number:

| Parameter | Value | Basis |
|---|---|---|
| `regime_sma_days` | 200 | Field-standard trend filter (≈10-month SMA timing; Faber 2007-style trend-following, shown to reduce drawdowns cross-market over long samples) |
| `regime_momentum_months` | 12 | Classic academic momentum formation window (Jegadeesh & Titman 1993 cross-sectional momentum; Moskowitz/Ooi/Pedersen time-series momentum use similar horizons cross-market) |
| `cross_sectional_rs_lookback_days` | 60 | Explicitly "conventional value, not fitted" per §4.3 — an intermediate-term relative-strength window, deliberately short of a full backtest sweep |
| `cross_sectional_rs_top_fraction` | 0.5 | Keeps breadth (all 22 names stay rankable) rather than over-concentrating on a fitted percentile |
| `gross_scalar_floor` | 0.25 | Risk-management choice, not a data-fit — worked example in §4.6 shows this caps the crisis-state gross budget at 7.5% of NetLiq against the 30% ceiling |
| `regime_caution_multiplier` | 0.5 | Risk-management choice — halves budget on a mixed trend/momentum read rather than binarizing regime state |
| `max_positions_per_sector` | 1 | Already resolved by Chris (decision 11.3, 2026-08-01) on empirical correlation grounds (NVDA/AMD, META/GOOGL, JPM/BAC, XOM/CVX pairs) — out of scope for this recalibration pass; not touched here |
| `hermes_risk_per_trade_pct` | 0.25 | Governance-locked — CLAUDE.md §5's two-tier risk model already fixes this at 0.25% NetLiq; not a tunable |

If useful, I can also empirically re-verify the sector-pair correlations behind
`max_positions_per_sector` (currently *(reference)* estimates in §4.7.1) against real
price history the same way — that's a separate, already-resolved decision, so I didn't do
it unprompted here.
