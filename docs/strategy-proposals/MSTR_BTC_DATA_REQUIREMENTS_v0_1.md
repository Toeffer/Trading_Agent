# MSTR/BTC Research — Data Requirements v0.1

> **Proposal ID:** `mstr_btc_research_v0_1`
> **Document Version:** `0.1`
> **Document Status:** `PROPOSED`
> **Strategy Readiness:** `S0`
> **Phase:** `18A`
> **Created:** 2026-07-17

---

## 1. Purpose

This document specifies the data requirements for the MSTR/BTC research proposal (Track A) and the SPY/QQQ control track (Track B). No data collection, live queries, or runtime data access is authorized by this document. It is a planning-only specification for later Phase 18B+ implementation.

---

## 2. Data Collection Governance

### 2.1 Current State (Phase 18A)

| Permission | Status |
|---|---|
| Live data collection | **Not authorized** |
| Historical data collection | **Not authorized** |
| IBKR market data access | **Not authorized for these symbols** |
| External data provider access | **Not authorized** |
| Data storage / persistence | **Not authorized** |
| Schema design and planning | **Permitted** (documentation only) |

### 2.2 Future Authorization

All data collection requires:
1. Phase 18B data-schema governance checkpoint to pass
2. Phase 18C+ provider governance checkpoint to pass
3. Explicit human approval (Chris) at each phase boundary
4. No implicit authorization — each phase must be explicitly passed

---

## 3. Track A — MSTR Equity Research Data

### 3.1 Primary Data Sources (Planned)

| Data Type | Provider | Frequency | Purpose |
|---|---|---|---|
| MSTR daily OHLCV bars | IBKR (paper) | Daily | Price action, trend, volatility |
| MSTR intraday quotes | IBKR (paper, delayed) | 15-min delayed | Research analysis only |
| BTC spot price | External (TBD) | Daily | Explanatory correlation input |
| BTC volume | External (TBD) | Daily | Market activity context |
| SPY daily OHLCV | IBKR (paper) | Daily | Market beta control |
| QQQ daily OHLCV | IBKR (paper) | Daily | Technology-beta control |

### 3.2 MSTR Company-Specific Data (Planned)

| Data Type | Source | Frequency | Purpose |
|---|---|---|---|
| BTC holdings (corporate treasury) | Public filings | Quarterly/event-driven | Treasury valuation context |
| Capital structure events | Public filings / news | Event-driven | Veto or context input |
| Earnings announcements | Public calendar | Event-driven | Trading blackout trigger |
| Corporate actions (splits, dividends) | IBKR / public | Event-driven | Contract adjustment awareness |
| Share issuance / buyback | Public filings | Event-driven | Dilution context |

### 3.3 Derived Metrics (Planned)

| Metric | Input Data | Calculation |
|---|---|---|
| MSTR-BTC correlation (rolling) | MSTR + BTC daily closes | Pearson r over N-day window |
| MSTR-BTC beta | MSTR + BTC daily returns | OLS beta over N-day window |
| MSTR-SPY relative strength | MSTR + SPY daily closes | MSTR return / SPY return |
| MSTR-implied BTC premium/discount | MSTR market cap vs BTC holdings | (MSTR market cap / BTC holdings value) − 1 |
| MSTR ATR(14) | MSTR daily OHLC | Standard ATR over 14 periods |
| MSTR 20-day SMA | MSTR daily closes | Simple moving average over 20 periods |
| BTC dominance context | BTC market cap / total crypto market cap | Ratio |

### 3.4 Data Quality Requirements (Planned)

| Requirement | Threshold |
|---|---|
| Minimum MSTR bar history | 60 trading days |
| Minimum valid MSTR closes | ≥50 |
| Minimum BTC spot history | 60 calendar days |
| MSTR-BTC correlation window | 20, 50, 100 day rolling |
| Correlation stability check | Rolling r must not change sign within window |
| Gap detection | Single-day gaps >3σ from mean flagged |
| Data staleness | ≤1 trading day for equities, ≤24h for BTC |

---

## 4. Track B — SPY/QQQ Control Track Data

### 4.1 Primary Data Sources (Planned)

| Data Type | Provider | Frequency | Purpose |
|---|---|---|---|
| SPY daily OHLCV bars | IBKR (paper) | Daily | Independent control research |
| QQQ daily OHLCV bars | IBKR (paper) | Daily | Independent control research |
| SPY intraday quotes | IBKR (paper, delayed) | 15-min delayed | Research analysis only |
| QQQ intraday quotes | IBKR (paper, delayed) | 15-min delayed | Research analysis only |

### 4.2 Derived Metrics (Planned)

| Metric | Input Data | Calculation |
|---|---|---|
| SPY 20-day SMA | SPY daily closes | Simple moving average over 20 periods |
| QQQ 20-day SMA | QQQ daily closes | Simple moving average over 20 periods |
| SPY ATR(14) | SPY daily OHLC | Standard ATR over 14 periods |
| QQQ ATR(14) | QQQ daily OHLC | Standard ATR over 14 periods |
| SPY-QQQ correlation | SPY + QQQ daily returns | Pearson r over 20-day window |
| SPY-QQQ relative strength | SPY + QQQ daily closes | QQQ return / SPY return |

### 4.3 Track B Independence Requirements

| Requirement | Enforcement |
|---|---|
| Separate strategy ID from Track A | Schema-level enforcement |
| Separate data fetch pipeline | Code-level isolation |
| Independent signal thresholds | Config-level separation |
| Independent model/report output | No silent mixing with Track A |
| Track selection governance | At most one track active; NO_TRADE is valid |

---

## 5. Data That Must NOT Be Collected

The following data types are explicitly out of scope and must not be collected even in future phases unless a separate governance action authorizes them:

| Data Type | Reason |
|---|---|
| Options chains (MSTR, SPY, QQQ) | Options execution is out of scope |
| Futures data | Out of scope |
| Forex data | Out of scope |
| Crypto exchange order books | Crypto execution is disabled |
| Leveraged/inverse ETF data | Hard-blocked asset class |
| Penny stock data (<$5) | Hard-blocked asset class |
| Non-US equity data | Out of scope |
| Social media sentiment | Not validated; out of scope |
| Alternative data (satellite, credit card, etc.) | Not validated; out of scope |

---

## 6. Data-Governance Principles

All data handling in later phases (18B+) must adhere to these principles. Phase 18A records them as governance requirements only — no data handling occurs.

### 6.1 Temporal Integrity

| # | Principle | Enforcement |
|---|---|---|
| 1 | All timestamps in UTC | Schema-level — `timestamp_utc` field required on every record |
| 2 | Source timestamp and ingestion timestamp remain distinct | Schema-level — `source_ts` and `ingestion_ts` are separate, non-equal fields |

### 6.2 Data Immutability and Versioning

| # | Principle | Enforcement |
|---|---|---|
| 3 | Raw data is immutable — never modified after initial write | Storage-level — append-only with content-addressed storage |
| 4 | Derived features and labels are versioned separately from raw data | Version-control — `feature_version` and `label_version` tags |
| 5 | Every dataset identifies provider and instrument | Schema-level — `provider_id` and `instrument` required fields |

### 6.3 Temporal Causality

| # | Principle | Enforcement |
|---|---|---|
| 6 | No feature may use information unavailable at the as-of timestamp | Backtest validation — point-in-time replay with temporal fence |
| 7 | Chronological train, validation, and test splits are required | Evaluation rule — splits ordered by time, no future leakage |
| 8 | Random time-series shuffling is prohibited | Evaluation rule — enforced by split validator |

### 6.4 Missing and Conflicting Data

| # | Principle | Enforcement |
|---|---|---|
| 9 | Missing or stale required data produces `NO_TRADE` | Runtime gate — data freshness check before any signal computation |
| 10 | Provider disagreement lowers confidence or produces `NO_TRADE` | Runtime gate — confidence threshold below minimum → `NO_TRADE` |

### 6.5 Track Isolation

| # | Principle | Enforcement |
|---|---|---|
| 11 | Track A and Track B retain separate datasets and outcomes | Architecture-level — no shared data pools, no cross-contamination |

### 6.6 Options Data (Future Reference)

| # | Principle | Enforcement |
|---|---|---|
| 12 | Historical option research requires point-in-time option-chain snapshots | Data-source requirement — snapshots timestamped to market close or event time |
| 13 | Current option chains must not substitute for historical chains | Data-source requirement — live data rejected by historical replay validator |
| 14 | Theoretical option values must not be treated as executable fills | Valuation rule — theoretical prices labeled `THEORETICAL`, never `FILL` |

### 6.7 Walk-Forward and Frozen Versions

| # | Principle | Enforcement |
|---|---|---|
| 15 | Walk-forward evaluation is required before promotion | Promotion gate — must complete at least one full walk-forward cycle |
| 16 | Frozen data, feature, and strategy versions are required | Promotion gate — all versions pinned at promotion time, no live updates |

### 6.8 Realistic Execution Assumptions

| # | Principle | Enforcement |
|---|---|---|
| 17 | Realistic spread, slippage, commissions, and obtainable-quote assumptions are required | Simulation rule — midpoint pricing rejected; must use bid (sell) / ask (buy) + slippage model + commission schedule |

---

## 7. Provider Governance (Placeholder for Phase 18B+)

### 7.1 IBKR Paper Account

- **Current access:** Read-only for allowed symbols (AAPL, META, NVDA, AMD)
- **Phase 18A status:** No new symbols authorized for data access
- **Future:** MSTR, SPY, QQQ contract lookup and bars may be authorized in Phase 18B+
- **Constraint:** IBKR data access requires bridge health, paper account connectivity, and read-only mode

### 7.2 BTC Spot Data Provider (TBD)

- **Candidate providers:** To be evaluated in Phase 18B+
- **Requirements:**
  - Free tier or acceptable cost
  - REST API with JSON response
  - Daily OHLCV (open, high, low, close, volume)
  - Reliable uptime (≥99.5%)
  - Rate-limit transparency
  - No execution capability (data-only provider)

### 7.3 Provider Safety Rules (Planned)

1. No provider may have order-execution capability
2. Provider API keys must be stored with the same security as broker credentials
3. Provider data is advisory-only — IBKR is always ground truth for equities
4. Provider outage must not block Strategy v1 operations
5. Provider data must not be treated as operator instructions

---

## 8. Schema Planning Notes (Phase 18B Preview)

The following schema areas will be addressed in Phase 18B:

1. **Bar data schema:** OHLCV structure with symbol, timestamp, interval
2. **Correlation matrix schema:** Pair-wise correlations with rolling windows
3. **Signal schema:** Normalized signal values with metadata (source, freshness, confidence)
4. **Forecast schema:** Structured output with direction, magnitude, confidence, and NO_TRADE flag
5. **Track selection schema:** Governance record for which track is active
6. **Provider configuration schema:** Connection parameters, rate limits, fallback rules

---

## 9. Version History

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-07-17 | Initial data requirements specification — S0 planning only |

---

## Document Metadata

| Field | Value |
|---|---|
| Document ID | `MSTR_BTC_DATA_REQUIREMENTS_v0_1` |
| Proposal ID | `mstr_btc_research_v0_1` |
| Phase | 18A |
| Readiness | S0 |
| Data Collection Authorized | false |
| Next Phase | PHASE18B_DATA_SCHEMA_AND_PROVIDER_GOVERNANCE |
