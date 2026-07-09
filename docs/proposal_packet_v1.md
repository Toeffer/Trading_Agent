# Proposal Packet v1 — Level 1 Advisory-Only Schema

> **Schema version:** `proposal-packet-v1.0.0`  
> **Status:** Advisory-only. Defines the required shape of every Level 1 strategy proposal.  
> **References:** `docs/strategy_v1.md` (governance baseline)  
> **Machine schema:** `docs/proposal_packet_v1.schema.json`  
> **Created:** 2026-07-09

---

## 1. Purpose

Every Level 1 advisory proposal — whether drafted by Hermes, Werner, or Chris — must conform to this packet schema before it enters review, approval simulation, bracket simulation, or execution-readiness work.

The schema is **machine-checkable** via the JSON Schema at `docs/proposal_packet_v1.schema.json`. A proposal that fails schema validation must be rejected with specific rejection reasons before any further processing.

---

## 2. Required Fields

A valid proposal packet is a JSON object with the following required fields:

| # | Field | Type | Description |
|---|---|---|---|
| 1 | `proposal_id` | string | Unique ID: `prop-{date}-{seq}`, e.g. `prop-20260709-001` |
| 2 | `timestamp` | string | ISO-8601 UTC timestamp of proposal creation |
| 3 | `strategy_version` | string | Must be `"v1.0.0"` |
| 4 | `strategy_doc_ref` | string | Must be `"docs/strategy_v1.md"` |
| 5 | `symbol` | string | IBKR symbol; must be in allowlist (AAPL, META, NVDA, AMD) |
| 6 | `side` | string | `"BUY"` or `"SELL"` (SELL = close-only, no short) |
| 7 | `quantity` | integer | Positive integer; computed by sizing rule (§9 of strategy_v1.md) |
| 8 | `entry_price` | number | Planned entry price or reference level |
| 9 | `signal_thesis` | string | Free-text thesis explaining why this trade (min 20 chars) |
| 10 | `signal_inputs` | object | Which signals aligned (see §3 below) |
| 11 | `data_quality` | object | Data quality evidence (see §4 below) |
| 12 | `no_trade_checklist` | object | No-trade conditions check (see §5 below) |
| 13 | `risk_envelope_check` | object | Risk envelope validation (see §6 below) |
| 14 | `sizing_calculation` | object | Position sizing computation (see §7 below) |
| 15 | `daily_trade_count_check` | object | Daily trade count validation |
| 16 | `daily_loss_check` | object | Daily loss halt check |
| 17 | `stop_exit_plan` | object | Stop and exit strategy (see §8 below) |
| 18 | `bracket_simulation` | object | Broker-side bracket requirement (see §9 below) |
| 19 | `advisory_only_statement` | string | Must contain "advisory-only" or "no broker execution" |
| 20 | `broker_execution_path` | string | Must reference guard→preflight→approve→submit chain |
| 21 | `human_review_checklist` | object | Review checklist with per-item pass/fail (see §10) |
| 22 | `proposed_by` | string | `"Hermes"`, `"Werner"`, or `"Chris"` |
| 23 | `model` | string | Resolved model string if proposed by an agent; `"human"` if by Chris |
| 24 | `rejection_reasons` | array | Empty if proposal passes; populated with reasons if rejected |
| 25 | `evidence_hash` | string | SHA-256 hash of the proposal JSON (canonical form) |
| 26 | `export_path` | string | Path where this proposal is persisted (optional for in-memory proposals) |

---

## 3. Signal Inputs Object

```json
{
  "trend_context": {
    "aligned": true,
    "detail": "Price above 20-day SMA ($182.40 vs SMA $178.15)"
  },
  "volume_confirmation": {
    "aligned": true,
    "detail": "Today's volume 112% of 20-day avg"
  },
  "structure": {
    "aligned": false,
    "detail": "No clear consolidation break"
  },
  "relative_strength": {
    "aligned": true,
    "detail": "AAPL +1.2% vs SPY +0.3%"
  },
  "atr_14": 3.21,
  "vix_level": 18.5,
  "signals_aligned_count": 2,
  "min_signals_met": true
}
```

**Rules:**
- At least 2 of the first 4 signals must be `aligned: true`
- `min_signals_met` must be `true`
- `atr_14` must be a positive number
- `vix_level` must be present (may be `null` if unavailable)

---

## 4. Data Quality Object

```json
{
  "bar_data_freshness_days": 1,
  "bar_data_ok": true,
  "atr_valid_closes": 14,
  "atr_ok": true,
  "sma_valid_closes": 20,
  "sma_ok": true,
  "volume_nonzero": true,
  "contract_lookup_ok": true,
  "market_open_ok": false,
  "overall": "PASS"
}
```

**Rules:**
- `overall` must be `"PASS"`; any failure → `"FAIL"`
- `bar_data_ok` must be true
- `atr_ok` must be true
- `sma_ok` must be true
- `contract_lookup_ok` must be true

---

## 5. No-Trade Checklist Object

```json
{
  "ibkr_allow_orders_false": true,
  "rules_enforced_false": true,
  "system_locked": true,
  "daily_loss_halt_active": false,
  "weekly_loss_halt_active": false,
  "daily_trade_count": 0,
  "daily_trade_count_ok": true,
  "ibkr_gateway_connected": true,
  "rth_window_open": false,
  "vix_spike_30pct": false,
  "earnings_48h": false,
  "symbol_in_allowlist": true,
  "overall": "PASS"
}
```

**Rules:**
- `overall` must be `"PASS"`
- `symbol_in_allowlist` must be true
- `ibkr_gateway_connected` must be true
- Any hard-block condition set to true → `"FAIL"`

---

## 6. Risk Envelope Check Object

```json
{
  "net_liquidation_eur": 1000000.00,
  "max_notional_5pct_eur": 50000.00,
  "proposed_notional_eur": 25000.00,
  "notional_ok": true,
  "max_risk_2pct_eur": 20000.00,
  "proposed_risk_eur": 8000.00,
  "risk_ok": true,
  "total_exposure_30pct_eur": 300000.00,
  "proposed_total_exposure_eur": 25000.00,
  "total_exposure_ok": true,
  "overall": "PASS"
}
```

**Rules:**
- All `*_ok` fields must be true
- `overall` must be `"PASS"`

---

## 7. Sizing Calculation Object

```json
{
  "notional_cap_shares": 125,
  "risk_cap_shares": 100,
  "allowlist_max_shares": 200,
  "final_shares": 100,
  "sizing_method": "strategy-v1-§9",
  "entry_price": 200.00,
  "stop_loss": 192.00,
  "stop_distance": 8.00,
  "stop_distance_pct": 4.0,
  "fx_eurusd": 1.08,
  "overall": "PASS"
}
```

**Rules:**
- `final_shares` must be `min(notional_cap_shares, risk_cap_shares, allowlist_max_shares)`
- `final_shares` must be ≥ 1
- `stop_distance_pct` must be ≤ 5.0 (hard cap)
- `sizing_method` must reference strategy_v1.md

---

## 8. Stop / Exit Plan Object

```json
{
  "initial_stop_loss": 192.00,
  "stop_type": "STP",
  "stop_calculation_method": "calc_stop()",
  "stop_candidates": {
    "atr_2x": 192.00,
    "swing_low": 194.00,
    "day20_low": 193.50,
    "hard_cap_5pct": 190.00
  },
  "chosen_stop": 194.00,
  "bracket_required": true,
  "profit_target_2r": 216.00,
  "partial_exit_50pct_at_2r": true,
  "trailing_activation_4pct": true,
  "invalidation_triggers": [
    "Close below initial stop",
    "2R loss exceeded",
    "News contradicts thesis"
  ],
  "overall": "PASS"
}
```

**Rules:**
- `bracket_required` must be true for BUY proposals
- `chosen_stop` must be the max of the four candidates (tightest valid)
- `stop_type` must be `"STP"` for IBKR

---

## 9. Bracket Simulation Object (Advisory)

```json
{
  "bracket_required": true,
  "parent_order_type": "MKT",
  "child_stop_type": "STP",
  "child_stop_price": 194.00,
  "child_stop_quantity": 100,
  "oco_group": false,
  "oco_note": "OCO bracket with take-profit deferred to Level 2+",
  "fail_closed": true,
  "overall": "PASS"
}
```

**Rules:**
- `bracket_required` must be true for BUY
- `child_stop_quantity` must equal `quantity` from root
- `fail_closed` must be true (child failure → cancel parent)
- `oco_group` is false in Level 1 (deferred)

---

## 10. Human Review Checklist Object

```json
{
  "gate_a_allowlist": true,
  "gate_b_notional": true,
  "gate_c_risk": true,
  "gate_d_daily_count": true,
  "gate_e_loss_halt": true,
  "gate_h_proposal": true,
  "p5_stop_check": true,
  "rth_window": false,
  "bridge_health": true,
  "data_quality": true,
  "advisory_boundary": true,
  "broker_execution_path": true,
  "strategy_v1_referenced": true,
  "chris_review_complete": false,
  "overall": "PENDING_CHRIS_REVIEW"
}
```

**Rules:**
- All gate checks must be true (or N/A with explanation)
- `chris_review_complete` is false by default (human step)
- `overall` is `"PENDING_CHRIS_REVIEW"` until Chris approves

---

## 11. Advisory-Only Boundary

Every proposal packet must include an explicit advisory-only statement and broker execution boundary:

- **`advisory_only_statement`:** Must contain the phrase "advisory-only" or "no broker execution" and declare that this proposal does not authorize any order.
- **`broker_execution_path`:** Must describe the only permitted path: `guard → preflight → approve → submit` via the bridge, with Chris's H1 token required for approve+submit.

---

## 12. Rejection Reasons

If a proposal fails any check, the `rejection_reasons` array must be populated. Each reason is an object:

```json
{
  "check": "gate_a_allowlist",
  "reason": "Symbol TSLA is not in the allowed instruments list (AAPL, META, NVDA, AMD)",
  "severity": "HARD_BLOCK"
}
```

Severity levels:
- `HARD_BLOCK` — Cannot proceed; proposal is invalid
- `ADVISORY_CAUTION` — May proceed with Chris override
- `DATA_MISSING` — Required data unavailable; retry later

---

## 13. Evidence Hash

The `evidence_hash` is the SHA-256 hex digest of the canonical JSON form of the proposal (sorted keys, no whitespace). It provides tamper-evidence and links the proposal to any downstream artifacts.

```python
import hashlib, json
canonical = json.dumps(proposal, sort_keys=True, separators=(",", ":"))
evidence_hash = hashlib.sha256(canonical.encode()).hexdigest()
```

---

## 14. Machine Validation

All proposals must pass validation against `docs/proposal_packet_v1.schema.json` before entering any review pipeline.

Validation can be performed by:
- `jsonschema.validate(proposal, schema)` in Python
- Any JSON Schema validator (ajv, etc.)
- The Phase 17B checkpoint's built-in synthetic validator

A proposal that fails schema validation must be rejected with specific `rejection_reasons` entries identifying the failed constraints.

---

## 15. Example — Minimal Valid Proposal

```json
{
  "proposal_id": "prop-20260709-001",
  "timestamp": "2026-07-09T14:30:00Z",
  "strategy_version": "v1.0.0",
  "strategy_doc_ref": "docs/strategy_v1.md",
  "symbol": "AAPL",
  "side": "BUY",
  "quantity": 100,
  "entry_price": 200.00,
  "signal_thesis": "AAPL breaking above consolidation after strong earnings. Volume confirming.",
  "signal_inputs": {
    "trend_context": {"aligned": true, "detail": "Price above 20 SMA"},
    "volume_confirmation": {"aligned": true, "detail": "Volume 112% of avg"},
    "structure": {"aligned": false, "detail": "No clear pattern"},
    "relative_strength": {"aligned": false, "detail": "Matching SPY"},
    "atr_14": 3.21,
    "vix_level": 18.5,
    "signals_aligned_count": 2,
    "min_signals_met": true
  },
  "data_quality": {
    "bar_data_freshness_days": 1,
    "bar_data_ok": true,
    "atr_valid_closes": 14,
    "atr_ok": true,
    "sma_valid_closes": 20,
    "sma_ok": true,
    "volume_nonzero": true,
    "contract_lookup_ok": true,
    "market_open_ok": false,
    "overall": "PASS"
  },
  "no_trade_checklist": {
    "ibkr_allow_orders_false": true,
    "rules_enforced_false": true,
    "system_locked": true,
    "daily_loss_halt_active": false,
    "weekly_loss_halt_active": false,
    "daily_trade_count": 0,
    "daily_trade_count_ok": true,
    "ibkr_gateway_connected": true,
    "rth_window_open": false,
    "vix_spike_30pct": false,
    "earnings_48h": false,
    "symbol_in_allowlist": true,
    "overall": "PASS"
  },
  "risk_envelope_check": {
    "net_liquidation_eur": 1000000.00,
    "max_notional_5pct_eur": 50000.00,
    "proposed_notional_eur": 20000.00,
    "notional_ok": true,
    "max_risk_2pct_eur": 20000.00,
    "proposed_risk_eur": 8000.00,
    "risk_ok": true,
    "total_exposure_30pct_eur": 300000.00,
    "proposed_total_exposure_eur": 20000.00,
    "total_exposure_ok": true,
    "overall": "PASS"
  },
  "sizing_calculation": {
    "notional_cap_shares": 125,
    "risk_cap_shares": 100,
    "allowlist_max_shares": 200,
    "final_shares": 100,
    "sizing_method": "strategy-v1-§9",
    "entry_price": 200.00,
    "stop_loss": 192.00,
    "stop_distance": 8.00,
    "stop_distance_pct": 4.0,
    "fx_eurusd": 1.08,
    "overall": "PASS"
  },
  "daily_trade_count_check": {
    "current_count": 0,
    "max_allowed": 2,
    "ok": true
  },
  "daily_loss_check": {
    "day_start_nl_eur": 1000000.00,
    "current_nl_eur": 1000000.00,
    "loss_pct": 0.0,
    "loss_halt_1pct": false,
    "ok": true
  },
  "stop_exit_plan": {
    "initial_stop_loss": 194.00,
    "stop_type": "STP",
    "stop_calculation_method": "calc_stop()",
    "stop_candidates": {
      "atr_2x": 192.00,
      "swing_low": 194.00,
      "day20_low": 193.50,
      "hard_cap_5pct": 190.00
    },
    "chosen_stop": 194.00,
    "bracket_required": true,
    "profit_target_2r": 208.00,
    "partial_exit_50pct_at_2r": true,
    "trailing_activation_4pct": true,
    "invalidation_triggers": ["Close below stop", "2R loss", "News contradiction"],
    "overall": "PASS"
  },
  "bracket_simulation": {
    "bracket_required": true,
    "parent_order_type": "MKT",
    "child_stop_type": "STP",
    "child_stop_price": 194.00,
    "child_stop_quantity": 100,
    "oco_group": false,
    "oco_note": "OCO bracket with take-profit deferred to Level 2+",
    "fail_closed": true,
    "overall": "PASS"
  },
  "advisory_only_statement": "This proposal is advisory-only. It does not authorize any broker order, execution, or mutation.",
  "broker_execution_path": "Only path: bridge guard → preflight → approve → submit with Chris H1 token.",
  "human_review_checklist": {
    "gate_a_allowlist": true,
    "gate_b_notional": true,
    "gate_c_risk": true,
    "gate_d_daily_count": true,
    "gate_e_loss_halt": true,
    "gate_h_proposal": true,
    "p5_stop_check": true,
    "rth_window": false,
    "bridge_health": true,
    "data_quality": true,
    "advisory_boundary": true,
    "broker_execution_path": true,
    "strategy_v1_referenced": true,
    "chris_review_complete": false,
    "overall": "PENDING_CHRIS_REVIEW"
  },
  "proposed_by": "Werner",
  "model": "opencode-go/deepseek-v4-pro",
  "rejection_reasons": [],
  "evidence_hash": "placeholder",
  "export_path": null
}
```

---

## Document Metadata

| Field | Value |
|---|---|
| Schema version | `proposal-packet-v1.0.0` |
| JSON Schema | `docs/proposal_packet_v1.schema.json` |
| Governance ref | `docs/strategy_v1.md` v1.0.0 |
| Governance level | Level 1 (advisory-only) |
| Created | 2026-07-09 |
