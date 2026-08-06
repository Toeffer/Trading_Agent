# Phase 19B — Proposed `paper-trading-rules.yaml` Changes (Draft)

> **This file is a draft for Chris to review and apply himself.** It is not the live rules
> file and is not read by `guard.py` or the bridge. Per CLAUDE.md invariant 6, Werner never
> modifies `.env` or `paper-trading-rules.yaml` — this document exists so Chris can copy the
> block below into `~/.openclaw/risk-rules/paper-trading-rules.yaml` on the bridge host
> himself, per RUNBOOK §L8.
>
> Content verbatim from `STRATEGY_V1_1_PROPOSAL_v0_1.md` §9.2, cross-checked 2026-08-06
> against `strategy_v1_1_core.py`'s `FROZEN_UNIVERSE` and advisory defaults on
> `phase19b-strategy-v1-1-implementation` — the 22-symbol/11-sector map and every advisory
> constant match exactly between the two; no drift found.

## What changes

| Key | Before | After |
|---|---|---|
| `symbol_allowlist.allow` | 4 symbols (AAPL, META, NVDA, AMD) | 22 symbols (§4.2) |
| `symbol_sectors` | *(absent)* | **NEW** — 22-symbol → 11-sector map, for Gate I |
| `max_positions_per_sector` | *(absent)* | **NEW** — `value: 1` |
| `advisory` | *(absent)* | **NEW** — regime/vol/RS constants, non-enforced |
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
4. Recalibrate `vol_reference_pct: 16` against SPY's actual measured 20-day realized vol
   before treating any sizing output as validated — the proposal marks this a
   *(reference)* estimate, not a live-computed value.
