# MSTR/BTC Research Proposal — v0.1

> **Proposal ID:** `mstr_btc_research_v0_1`
> **Proposal Version:** `0.1`
> **Proposal Status:** `PROPOSED`
> **Strategy Readiness:** `S0`
> **Autonomy Level:** `1`
> **Research Only:** `true`
> **Execution Scope:** `NONE`
> **Permitted Activity:** `DOCUMENTATION_AND_SCHEMA_PLANNING_ONLY`
> **Created:** 2026-07-17
> **Last Updated:** 2026-07-17

---

## 1. Proposal Identity

| Field | Value |
|---|---|
| `proposal_id` | `mstr_btc_research_v0_1` |
| `proposal_version` | `0.1` |
| `proposal_status` | `PROPOSED` |
| `strategy_readiness` | `S0` |
| `autonomy_level` | `1` |
| `research_only` | `true` |
| `execution_scope` | `NONE` |
| `permitted_activity` | `DOCUMENTATION_AND_SCHEMA_PLANNING_ONLY` |
| `options_scope` | `SIMULATION_ONLY` |
| `btc_execution_scope` | `NONE` |
| `equity_execution_scope` | `NONE` |
| `allowlist_change` | `false` |
| `rules_change` | `false` |
| `broker_change` | `false` |
| `guard_change` | `false` |
| `replaces_strategy_v1` | `false` |
| `canonical_strategy_unchanged` | `true` |
| `human_approval_required_for_promotion` | `true` |
| `next_phase_boundary` | `PHASE18B_DATA_SCHEMA_AND_PROVIDER_GOVERNANCE` |
| `canonical_strategy_reference` | `docs/strategy_v1.md` |

---

## 2. Governance States

This proposal recognizes exactly three governance states:

### 2.1 PROPOSED

The research direction is documented and may proceed later to data-schema and provider governance. It does **not** mean that the strategy has an edge, has been approved for trading, or may access an execution path.

**Conditions for PROPOSED:**
- All required proposal documents exist and are internally consistent
- The manifest contains all required metadata fields with correct values
- No governance-critical fields are missing, blank, or semantically invalid
- No execution-scope, allowlist, rules, broker, or guard mutation is indicated
- The canonical Strategy v1 is explicitly marked as unchanged

### 2.2 BLOCKED

The proposal cannot proceed to the next phase. A BLOCKED state indicates a hard governance violation that must be resolved before any promotion.

**BLOCKED triggers include:**
- Any required manifest field is missing, blank, or null
- `replaces_strategy_v1` is `true` (this proposal must never replace v1)
- `canonical_strategy_unchanged` is `false`
- `execution_scope` is not `NONE`
- `btc_execution_scope` is not `NONE`
- `equity_execution_scope` is not `NONE`
- `allowlist_change` is `true`
- `rules_change` is `true`
- `broker_change` is `true`
- `guard_change` is `true`
- `research_only` is not `true`
- `autonomy_level` is not `1`
- `options_scope` is not `SIMULATION_ONLY`
- `permitted_activity` is not `DOCUMENTATION_AND_SCHEMA_PLANNING_ONLY`
- Any proposal document is missing from the expected path
- Any proposal document hash does not match the manifest record

### 2.3 PENDING_INPUT

The proposal is structurally valid but requires additional input or clarification before it can be promoted.

**PENDING_INPUT triggers include:**
- Manifest exists but one or more referenced documents are missing
- Manifest `content_hash` fields do not match current document hashes
- `proposal_status` is not one of the recognized values

---

## 3. Approval State

All approval state flags default to the most restrictive value. No approval is granted at this phase.

| Approval Flag | Value |
|---|---|
| `NOT_APPROVED_FOR_EXECUTION` | `true` |
| `NOT_APPROVED_FOR_ALLOWLIST_CHANGE` | `true` |
| `NOT_APPROVED_FOR_DATA_COLLECTION_RUNTIME` | `true` |
| `NOT_APPROVED_FOR_BACKTEST_PROMOTION` | `true` |
| `NOT_APPROVED_FOR_OPTIONS_EXECUTION` | `true` |

---

## 4. Explicit Non-Actions

This proposal **must not** and **does not**:

1. Replace or activate the canonical Strategy v1 (`docs/strategy_v1.md`)
2. Collect live or historical market data
3. Run a backtest
4. Generate a trade proposal
5. Add instruments to an executable allowlist
6. Enable MSTR, SPY, QQQ, BTC, or options execution
7. Change broker, guard, risk, approval, H1, or runtime behavior
8. Call any IBKR broker endpoint
9. Call any `/order*` endpoint
10. Use or construct an H1 token or X-H1-Token header
11. Access `/etc/ibkr-bridge/h1_token` or any root-owned file
12. Modify `.env`, `paper-trading-rules.yaml`, or `guard-state.json`
13. Open an order window or trade window
14. Enable `IBKR_ALLOW_ORDERS` or `rules.enforced`
15. Subvert the advisory-only boundary of Hermes or Werner

---

## 5. Research Tracks

### Track A — MSTR Equity Research

- **MSTR equity research** is the primary target
- **BTC spot data** is an explanatory research input only
- **QQQ** and **SPY** are market and technology-beta controls
- **MSTR company and capital-structure events** are context or veto inputs
- The model must distinguish:
  - BTC-led movement
  - Already-priced movement
  - Company-specific movement
  - Unstable relationships
- Output is a **structured forecast or `NO_TRADE`**, never an order
- Track A must have its own strategy ID, data requirements, thresholds, models, and reports

### Track B — SPY/QQQ Control Track

- **SPY/QQQ** is an independent control and alternative research track
- Track B must have its **own strategy ID, data, thresholds, models, and reports**
- Track B must **not** be silently mixed with Track A
- Track B must **not** be selected merely because Track A returned `NO_TRADE`
- At most one research candidate may be selected under later frozen rules
- `NO_TRADE` is a valid result for both tracks

---

## 6. Instrument Boundaries

| Instrument | Phase 18A Status | Notes |
|---|---|---|
| MSTR | Research-only | Equity research target; not executable |
| BTC | Data-only | Explanatory input; never broker-executable through this project |
| SPY | Research control only | Market beta control for Tracks A and B |
| QQQ | Research control only | Technology-beta control for Tracks A and B |
| Options | Simulation-only | Not executable; out of scope for execution |
| Futures | Outside scope | Not considered |
| Forex | Not traded | Out of scope |
| Short equity | Outside scope | Long-only mandate preserved |
| Leveraged ETFs | Outside scope | Hard-blocked; unconditional rejection |
| Inverse ETFs | Outside scope | Hard-blocked; unconditional rejection |

**Critical invariant:** No symbol is added to the YAML executable allowlist. The YAML allowlist remains the sole execution authority. The current allowlist (AAPL, META, NVDA, AMD) is unchanged.

---

## 7. Options Boundaries

Phase 18A establishes the following options governance boundaries. These are hard constraints:

| Rule | Status |
|---|---|
| No options contract is executable | Hard constraint |
| No option order endpoint may be added | Hard constraint |
| No option may enter the equity proposal path | Hard constraint |
| No 0DTE (zero days to expiration) | Hard constraint |
| No naked or short-premium options | Hard constraint |
| No multi-leg execution | Hard constraint |
| No exercise or assignment workflow | Hard constraint |

**Future simulation scope (not Phase 18A):** Later phases may consider simulation of long calls and puts only. Any future options phase requires its own schema, guard, risk model, broker adapter, CI tests, and explicit human approval.

---

## 8. Data-Governance Principles

All data handling in later phases (18B+) must adhere to these principles. Phase 18A records them as governance requirements only — no data handling occurs.

| # | Principle | Enforcement |
|---|---|---|
| 1 | All timestamps in UTC | Schema-level |
| 2 | Source timestamp and ingestion timestamp remain distinct | Schema-level |
| 3 | Raw data is immutable | Storage-level |
| 4 | Derived features and labels are versioned separately | Version-control |
| 5 | Every dataset identifies provider and instrument | Schema-level |
| 6 | No feature may use information unavailable at the as-of timestamp | Backtest validation |
| 7 | Missing or stale required data produces `NO_TRADE` | Runtime gate |
| 8 | Provider disagreement lowers confidence or produces `NO_TRADE` | Runtime gate |
| 9 | Track A and Track B retain separate datasets and outcomes | Architecture-level |
| 10 | Historical option research requires point-in-time option-chain snapshots | Data-source requirement |
| 11 | Current option chains must not substitute for historical chains | Data-source requirement |
| 12 | Theoretical option values must not be treated as executable fills | Valuation rule |
| 13 | Chronological train, validation, and test splits are required | Evaluation rule |
| 14 | Random time-series shuffling is prohibited | Evaluation rule |
| 15 | Walk-forward evaluation is required before promotion | Promotion gate |
| 16 | Frozen data, feature, and strategy versions are required | Promotion gate |
| 17 | Realistic spread, slippage, commissions, and obtainable-quote assumptions are required | Simulation rule |

---

## 9. Phase 18A Non-Creations

Phase 18A must NOT create any of the following. These are reserved for later phases (18B+).

| Must Not Create | Reserved For |
|---|---|
| Data collectors | Phase 18B+ |
| Provider API clients | Phase 18B+ |
| Scheduled jobs | Phase 18B+ |
| Databases | Phase 18B+ |
| Raw market-data directories containing collected data | Phase 18B+ |
| Model code | Later phases |
| Feature code | Later phases |
| Label code | Later phases |
| Backtest code | Later phases |
| Forecasting code | Later phases |
| Candidate-generation code | Later phases |
| Option-selection code | Later phases |
| Order-plan code | Later phases |

---

## 10. Canonical Strategy Preservation

| Rule | Status |
|---|---|
| `docs/STRATEGY.md` remains the active Strategy v1 | Confirmed |
| This proposal does not replace `docs/STRATEGY.md` | Confirmed |
| This proposal is not marked Chris-approved | Confirmed — status is `PROPOSED`, approval is pending separate promotion |
| Executable symbol list is not copied from a potentially stale source | Confirmed — YAML allowlist remains sole authority |
| The current YAML allowlist (AAPL, META, NVDA, AMD) remains authoritative | Confirmed |

---

## 11. Promotion Requirements

To move from `PROPOSED` to a higher readiness level, this proposal requires:

1. **Human approval:** Chris must explicitly approve promotion
2. **Phase 18B completion:** Data schema and provider governance documents must exist
3. **Phase 18C+ completion:** Subsequent phases must pass their governance checkpoints
4. **No bypass:** Promotion must follow the Phase 18 chain sequentially
5. **Strategy v1 preserved:** At every promotion gate, `canonical_strategy_unchanged` must remain `true`
6. **Execution scope locked:** At every gate, execution scope must remain `NONE` until explicitly changed by a separate governance action

---

## 12. Document References

| Document | Path | Purpose |
|---|---|---|
| Research Proposal | `docs/strategy-proposals/MSTR_BTC_RESEARCH_PROPOSAL_v0_1.md` | This document |
| Data Requirements | `docs/strategy-proposals/MSTR_BTC_DATA_REQUIREMENTS_v0_1.md` | Track A and B data specifications |
| Manifest | `docs/strategy-proposals/mstr_btc_research_v0_1.manifest.json` | Machine-readable proposal metadata |
| Canonical Strategy | `docs/strategy_v1.md` | Active Strategy v1 (unchanged) |
| Strategy Governance | `docs/STRATEGY.md` | Pre-governance baseline (unchanged) |

---

## 13. Versioning

| Rule | Description |
|---|---|
| Version format | `v<MAJOR>_<MINOR>` (research proposal versioning) |
| MAJOR bump | Governance boundary change or track restructuring |
| MINOR bump | Clarification, typo fix, additional detail |
| Manifest sync | Every document update must update the manifest `content_hash` |
| Changelog | Documented in this section |

**Version history:**

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-07-17 | Initial proposal — S0 research-governance documentation only |

---

## Document Metadata

| Field | Value |
|---|---|
| Document ID | `MSTR_BTC_RESEARCH_PROPOSAL_v0_1` |
| Proposal ID | `mstr_btc_research_v0_1` |
| Governance Level | Level 1 (advisory-only, research-governance) |
| Phase | 18A |
| Phase Boundary | PHASE18B_DATA_SCHEMA_AND_PROVIDER_GOVERNANCE |
| Supersedes | None (new proposal) |
| Superseded By | None |
| Review Cadence | On demand; required before any promotion |
