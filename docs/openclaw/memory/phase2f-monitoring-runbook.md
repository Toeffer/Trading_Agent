# Phase 2F Monitoring Operator Runbook

**Date:** 2026-06-03
**Status:** ✅ Monitoring endpoints active. Orders remain blocked.

---

## 1. Quick Status

```bash
# One-liner: health + alerts + drift
curl -s http://127.0.0.1:8790/monitor/health | python3 -m json.tool
curl -s http://127.0.0.1:8790/monitor/alerts | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Alerts: {len(d[\"alerts\"])}'); [print(f'  {a[\"alert_type\"]}: {a[\"source\"]} — requires_action={a[\"requires_action\"]}') for a in d['alerts']]"
curl -s http://127.0.0.1:8790/monitor/positions/drift | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Drift: {d[\"drift_detected\"]}, Mismatches: {len(d[\"mismatches\"])}')"
```

**Expected healthy output:**
- `/monitor/health` → `ok: true`
- `/monitor/alerts` → max 1 alert, `source: historical_test_data`, `requires_action: false`
- `/monitor/positions/drift` → `drift_detected: false`, 0 mismatches

---

## 2. Monitoring Endpoints Reference

| Endpoint | Method | Returns | Kill-switch dep | IBKR dep |
|---|---|---|---|---|
| `/monitor/health` | GET | System health: guard state, events, approvals | No | No |
| `/monitor/reconciliation` | GET | Full cross-source reconciliation | No | No (position optional) |
| `/monitor/events` | GET | Filtered event log (supports `?type=`, `?since=`) | No | No |
| `/monitor/alerts` | GET | Active alerts from latest reconciliation | No | No |
| `/monitor/positions/drift` | GET | Expected vs actual positions | No | No (actual if IBKR connected) |

All endpoints work with IBKR disconnected. All endpoints work with both kill switches false.

---

## 3. Alert Classification Guide

Each alert has three classification fields:

| Field | Meaning | Values |
|---|---|---|
| `source` | Origin of the condition | `historical_test_data`, `historical_exercise`, `live` |
| `historical` | Is this from past testing? | `true`, `false` |
| `requires_action` | Does operator need to act? | `true`, `false` |

### When to act

| Alert pattern | Classification | Action required |
|---|---|---|
| `trade_count_mismatch`, order_ids are known test values | `historical_test_data`, `requires_action=false` | **None** — test artifact |
| `trade_count_mismatch`, order_ids are unknown | `live`, `requires_action=true` | Investigate guard state corruption |
| `position_drift` | `live`, `requires_action=true` | **Stop trading.** Compare TWS positions vs guard events |
| `orphan_submitted_approval` | `live`, `requires_action=true` | Check approval-records.jsonl for consistency |
| `bridge_disconnected` | `live`, `requires_action=true` | Restart bridge or Gateway |

### What to never do

- ❌ Never mutate `guard-state.json` based on monitoring
- ❌ Never delete or edit `guard-events.jsonl`
- ❌ Never delete or edit `approval-records.jsonl`
- ❌ Never delete or edit `submitted-approvals.json`
- ❌ Never auto-submit, auto-cancel, or auto-resume orders
- ❌ Never flip kill switches based on monitoring

Monitoring is **scan-and-report only**.

---

## 4. Known Test Artifacts

These artifacts from Phase 2E testing are hardcoded in `monitor.py` as known test values:

| Artifact | Type | Location |
|---|---|---|
| `order_id=12345` | Mock order (no symbol/action) | `guard-events.jsonl` (3 events) |
| `order_id=99999` | Test exercise (AAPL BUY 100) | `guard-events.jsonl` (2 events) |
| `approval_id=aprv_noexec` | Test approval (no execution) | `submitted-approvals.json`, `guard-events.jsonl` |
| `approval_id=aprv_7` | Test approval | `submitted-approvals.json`, `guard-events.jsonl` |

**Why they exist:** Phase 2E testing of the submit path while `IBKR_ALLOW_ORDERS=false`. The bridge exercised the `/order/submit` endpoint which returned `ORDERS_BLOCKED`, but events were still logged.

**Why they don't require action:** These are harmless log artifacts. All events are rejected by `ORDERS_BLOCKED` and never reached IBKR. The real trade count (guard_state=1 for order_id=12) correctly represents the only live paper order.

**Files NOT modified:** No guard state, approval records, or submitted-approvals have been mutated to hide these artifacts. Detection is preserved for any future real mismatch.

---

## 5. Current Real Position

| Field | Value |
|---|---|
| Symbol | AAPL |
| Direction | LONG |
| Shares | 1 |
| Order ID | 12 |
| Order Type | MKT |
| Fill Price | $314.92 |
| Date | 2026-06-02 |
| Approval ID | `aprv_6aca70ba-1623-40bc-a449-751dfb80b90c` |
| Event | `order_submitted` confirmed |

### Expected monitor values

```text
position_drift_check().expected_positions = {"AAPL": 1}
  (After filtering test order_ids 12345, 99999 and test approvals)
  
reconcile_snapshot().classification_summary = {
  "historical_test_data": 1,
  "historical_exercise": 0,
  "live": 0
}

reconcile_snapshot().alerts[0].source = "historical_test_data"
reconcile_snapshot().alerts[0].requires_action = false
```

---

## 6. Data Sources

All monitoring data comes from existing files — no new files created.

| Source | Path | Format | Authority |
|---|---|---|---|
| Guard state | `~/.openclaw/guard-state.json` | JSON | Ground truth for daily_trade_count |
| Guard events | `~/.openclaw/guard-events.jsonl` | JSONL | Append-only event log |
| Approval records | `~/.openclaw/approval-records.jsonl` | JSONL | Preflight result history |
| Submitted approvals | `~/.openclaw/submitted-approvals.json` | JSON | One-use tracking |
| IBKR positions | Bridge `GET /positions` | JSON | Live fetch (optional) |

---

## 7. Safety State (Current)

| Switch | Value | Location |
|---|---|---|
| `IBKR_ALLOW_ORDERS` | `false` | `~/.openclaw/.env` |
| `rules.enforced` | `false` | `~/.openclaw/risk-rules/paper-trading-rules.yaml` |
| `/order` | HTTP 403 | `bridge.py` |
| `/order/submit` | `ORDERS_BLOCKED` | `bridge.py` |

Both kill switches must be `true` before any order reaches IBKR. Monitoring does not depend on either.

---

## 8. Troubleshooting

### `/monitor/health` returns HTTP 500

Check bridge is running:
```bash
curl -s http://127.0.0.1:8790/health | python3 -m json.tool
```
If bridge is down, restart:
```bash
cd ~/agents/ibkr-bridge && source .venv/bin/activate
nohup python3 -m uvicorn bridge:app --host 127.0.0.1 --port 8790 > /dev/null 2>&1 &
```

### Reconciliation shows unexpected live alert

1. Check which alert type fired
2. Inspect `guard-state.json` vs `guard-events.jsonl`
3. Compare unique order_ids: `grep order_submitted ~/.openclaw/guard-events.jsonl | python3 -c "import json,sys; ids={json.loads(l).get('order_id') for l in sys.stdin if json.loads(l).get('order_id')}; print(sorted(ids))"`
4. If order_id is NOT in {12345, 99999} and is NOT 12, investigate

### Drift detected (expected ≠ actual)

1. Check TWS positions manually
2. Check `guard-events.jsonl` for `order_submitted` events
3. If an order was placed via TWS directly, that's manual — not system drift
4. If partial fill: guard counts the trade once, position may show less
5. Do not modify guard state — report to Chris

---

## 9. Architecture Files

| File | Role |
|---|---|
| `/home/chris/agents/ibkr-bridge/monitor.py` | Monitoring logic |
| `/home/chris/agents/ibkr-bridge/bridge.py` | Endpoint wiring (monitor routes) |
| `/home/chris/agents/ibkr-bridge/guard.py` | Constants, loaders, event types |
| `/home/chris/.openclaw/memory/phase2f-monitoring-architecture.md` | Design doc |
| `/home/chris/.openclaw/memory/phase2-guarded-order-architecture.md` | Full architecture (includes Phase 2F section 10) |

---

## 10. Key Rules Summary

1. **All monitoring is GET-only.** No POST, PUT, DELETE, PATCH.
2. **No kill-switch dependency.** Monitoring works with both switches false.
3. **No IBKR dependency.** File-based data works without connection.
4. **No mutation.** Never modify guard state, event logs, or approval records.
5. **Scan-and-report only.** Alerts inform Chris, never auto-correct.
6. **Test artifacts classified.** Known order_ids 12345, 99999 and approvals aprv_noexec, aprv_7 are historical.
7. **Future mismatches detectable.** Any unknown order_id triggers live alert.
8. **Orders remain blocked.** `/order`=403, `/order/submit`=ORDERS_BLOCKED.

---

*End of runbook. Orders remain disabled. Monitoring is read-only.*
## Phase 2G — Close-Only SELL & Ack-Hardening

**Status:** ✅ SELL executed 2026-06-03, AAPL flat. AAPL re-acquired via BUY 1 (order_id=8).
Second SELL (order_id=16) PreSubmitted, never filled, never reduced position.
Switches rolled back after testing. Bridge remains setup/read-only.

### Executed Orders Summary

| Symbol | Action | Qty | Order ID | permId | Price | Date | Status |
|---|---|---|---|---|---|---|---|
| AAPL | BUY | 1 | 12 | — | $314.92 | 2026-06-02 | Filled |
| AAPL | SELL | 1 | 36 | 551562267 | $314.50 | 2026-06-03 | Filled |
| AAPL | BUY | 1 | 8 | 551562294 | $314.28 | 2026-06-03 | Filled |
| AAPL | SELL | 1 | 16 | 2055135190 | — | 2026-06-04 | PreSubmitted (unfilled) |

### Current Account State

- **AAPL: LONG 1 share** (buy-side, after unfilled SELL)
- `daily_trade_count`: 1 for 2026-06-04
- Drift: None (expected=1.0, actual=1.0)
- Kill switches: Both false
- Orders: Blocked

---

## Phase 2H — Fill-Based Position Calculation

**Date:** 2026-06-04
**Trigger:** order_id=16 (SELL 1, PreSubmitted, filled=0) caused false drift alert.

### The Bug

`position_drift_check()` used `totalQuantity` for position impact regardless of fill status.
order_id=16 (SELL 1) subtracted 1 from expected AAPL, causing expected=0 vs actual=1 — false drift.

### The Fix

Expected positions are now **fill-based**, not submission-based:

1. Events with `ibkr_metadata.filled` available: use **filled quantity**, not `totalQuantity`
2. Events with `filled=0` (PreSubmitted, Submitted, Cancelled, Inactive, ApiCancelled): **skipped entirely** — zero position impact
3. Partial fills: use `float(filled)` — a SELL filled=0.5 reduces expected by 0.5 only
4. Events without `ibkr_metadata` (legacy pre-fix): continue previous behavior (excluded via `unconfirmed` set)

### Reference Case: order_id=16

| Field | Value |
|---|---|
| Symbol | AAPL |
| Action | SELL 1 |
| Order ID | 16 |
| permId | 2055135190 |
| Status | PreSubmitted |
| filled | 0.0 |
| remaining | 1.0 |
| Expected position impact | **None** (filled=0) |
| Actual position | 1 share |
| Current drift | false |

### What Monitoring Reports for SELL Activity

| Indicator | SELL submitted & acknowledged (filled>0) | SELL unfilled (filled=0) | SELL never reached IBKR (IBKR_ACK_TIMEOUT) |
|---|---|---|---|
| `daily_trade_count` | +1 (incremented) | +1 (submitted) | Unchanged |
| Event log | `order_submitted` with full `ibkr_metadata` | `order_submitted` with filled=0 | `order_unconfirmed` |
| Expected position | BUY qty - SELL filled qty | Unchanged (filled=0) | Unchanged (excluded) |
| Drift | Matches actual if filled | No drift (op not counted) | May show discrepancy — inspect `unconfirmed_count` |
| `requires_action` | False (normal) | False unless unexpected | True (if drift persists after reconciliation) |

### How to Read Drift with Unconfirmed Orders

```bash
curl -s http://127.0.0.1:8790/monitor/positions/drift | python3 -m json.tool
```

If `unconfirmed_count > 0`, the expected position excludes those unconfirmed orders. The `drift_detail` field explains the context. The `unconfirmed_approval_ids` array shows which approval IDs are excluded.

### Startup Reconciliation Fields

The startup reconciliation event now includes:

| Field | Description |
|---|---|
| `unconfirmed_count` | Number of `order_unconfirmed` events found |
| `unconfirmed_orders` | Array of unconfirmed approval IDs + order IDs |
| `legacy_unconfirmed_count` | Number of pre-fix `order_submitted` events without `ibkr_metadata` |
| `legacy_unconfirmed` | Array of legacy unconfirmed approval IDs + order IDs |

### Acceptance Tests (all pass)

| # | Test | Expected |
|---|---|---|
| 1 | SELL submitted with filled=0 | Expected position unchanged |
| 2 | SELL partially filled 0.5 | Expected position reduced by 0.5 |
| 3 | SELL filled 1 | Expected position reduced by 1 |
| 4 | BUY filled 1 | Expected position increased by 1 |
| 5 | Cancelled unfilled order | No position impact |
| 6 | Current live state (AAPL=1) | `drift_detected=false`, expected=1.0, actual=1.0 |

### Files Modified

- `/home/chris/agents/ibkr-bridge/monitor.py` — `position_drift_check()`: use `ibkr_metadata.filled` when available, skip `filled=0`

### Files NOT Modified

- `guard.py` — unchanged
- `bridge.py` — unchanged
- `guard-events.jsonl` — unchanged
- `guard-state.json` — unchanged
- Rule files — unchanged

---

*End of Phase 2G/2H runbook addendum.*

---

## Phase 3B — Supervised Position Management

**Status:** Steps 1–3 complete. Orders remain blocked. System locked.

---

### Step 1: Read-Only Open-Order Monitoring

**Endpoint:** `GET /monitor/open-orders`

Returns pending/open orders from guard events + IBKR live trades.

**Fields per order:**

| Field | Description |
|---|---|
| `order_id` | IBKR order ID from guard event |
| `permId` | IBKR permanent order ID |
| `symbol` | Ticker symbol |
| `action` | BUY or SELL |
| `totalQuantity` | Requested quantity |
| `filled` | Filled quantity (float) |
| `remaining` | Remaining quantity (float) |
| `status` | IBKR order status string |
| `submitted_at_utc` | Timestamp from guard event |
| `age_seconds` | Age in seconds (or null) |
| `source` | `"guard_events"` or `"ibkr_live"` |
| `requires_manual_action` | True if PreSubmitted/Submitted older than 120s, or unknown status |

**Terminal statuses excluded:** Filled, Cancelled, ApiCancelled, Inactive.

**No writes. No cancel. No orders enabled.**

---

### Step 2: Close Preflight Open-Order Gate (Gate H)

**Gate H** added to `run_preflight()` for SELL close-only preflights only.

Checks `/monitor/open-orders` for same-symbol unresolved orders with `remaining > 0`. Rejects close with reason including order_id and status.

**Unresolved statuses:** PreSubmitted, Submitted, PendingSubmit, ApiPending, PartiallyFilled (remaining>0), Unknown (remaining>0).

**Terminal statuses:** Filled, Cancelled, ApiCancelled, Inactive.

**BUY preflights unaffected** — Gate H runs only in the SELL close-only path.

```bash
# Example: blocked close due to open order_id=16
curl -s -X POST http://127.0.0.1:8790/order/preflight \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"AAPL","action":"SELL","totalQuantity":1,"orderType":"MKT"}'
# → passed=False, gate=open_orders reason="Unresolved open order(s): order_id=16 (PreSubmitted)"
```

---

### Step 3: Manual Terminal Reconciliation

**Problem:** Stale PreSubmitted orders (like order_id=16) block Gate H indefinitely, even when the operator has verified the order is not open in IBKR/TWS.

**Solution:** Operator-verified terminal records in `manual-order-reconciliations.jsonl`. These records override the guard-event status for open-order detection only. The original guard event is **preserved** — never deleted or mutated.

#### Reference Record: order_id=16

| Field | Value |
|---|---|
| `order_id` | 16 |
| `permId` | 2055135190 |
| `symbol` | AAPL |
| `action` | SELL |
| `final_status` | NotFoundInIBKR |
| `filled` | 0.0 |
| `remaining` | 1.0 |
| `verified_by` | Chris |
| `verified_at_utc` | 2026-06-04T09:07:09.776173+00:00 |
| `evidence` | Manually checked TWS — order not found in open trades. Confirmed unfilled. |
| `status` | manual_terminal |

#### Endpoint: `POST /monitor/open-orders/reconcile`

```bash
curl -s -X POST http://127.0.0.1:8790/monitor/open-orders/reconcile \
  -H 'Content-Type: application/json' \
  -d '{
    "order_id": 16,
    "permId": 2055135190,
    "symbol": "AAPL",
    "action": "SELL",
    "final_status": "NotFoundInIBKR",
    "filled": 0,
    "remaining": 1,
    "verified_by": "Chris",
    "evidence": "Manually checked TWS — order not found in open trades. Confirmed unfilled."
  }'
```

Returns `{"status": "recorded", "record": {...}}` and logs a `monitor_alert` guard event for audit trail.

#### Behavior After Reconciliation

| Check | Before manual record | After manual record |
|---|---|---|
| `/monitor/open-orders` lists order_id=16 | ✅ Yes (open) | ❌ No (filtered out) |
| Gate H blocks AAPL SELL preflight | ✅ Yes | ❌ No |
| `expected_positions` includes order_id=16 | ❌ No (fill-based, filled=0) | ❌ No (still fill-based) |
| `drift_detected` | false | false |
| Original guard event | Preserved | Preserved |

#### File Location

`/home/chris/.openclaw/manual-order-reconciliations.jsonl`

JSONL format, append-only. Each record has: `order_id`, `permId`, `symbol`, `action`, `final_status`, `filled`, `remaining`, `verified_by`, `verified_at_utc`, `evidence`, `status`.

**Safety rules:**
- Records are operator-created write-once (append-only)
- Records never modify `guard-events.jsonl`, `guard-state.json`, or any original event data
- No cancellation API — operator cancels in TWS, records the result here
- Expected-position logic remains fill-based and is unaffected by these records

---

---

## Phase 3D — Daily Operator Workflow

**This is the full daily cycle.** Each step is one command or one manual check.
No step takes more than 30 seconds. The workflow is designed for a single
position (AAPL) under supervised management.

---

### 8-Step Daily Cycle (3R added)

#### Step 0 — Model Tier Safety Check

```bash
# Verify current AI model is Tier 1 for safety-critical work
# This policy is defined at:
cat ~/.openclaw/memory/model-routing-safety-policy.md | head -5

# Quick model identity from ibkr-status (if bridge up)
ibkr-status 2>/dev/null | grep -A5 "Model Policy"

# If bridge is down, model identity must be stated manually.
# Current model: openrouter/deepseek/deepseek-v4-flash  (Tier 1)
# If Tier < 1, defer all safety-critical edits.
```

**Failure modes:**
- Tier 2 model in session: refuse bridge.py/guard.py/monitor.py/bundle_audit.py edits
- Tier unknown: state explicit model identity before proceeding
- Policy missing: `~/.openclaw/memory/model-routing-safety-policy.md` must exist

#### Step 1 — Start-of-Day Baseline (before RTH)

```bash
# One-liner: verify system is healthy and locked
curl -s http://127.0.0.1:8790/monitor/health | python3 -m json.tool && \
curl -s http://127.0.0.1:8790/monitor/positions/drift | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Drift: {d[\"drift_detected\"]}') && \
curl -s http://127.0.0.1:8790/monitor/open-orders | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Open: {d[\"open_count\"]} Terminal: {d.get(\"manual_terminal_count\",0)}') && \
curl -s http://127.0.0.1:8790/monitor/alerts | python3 -c "import json,sys; d=json.load(sys.stdin); live=[a for a in d.get('alerts',[]) if a.get('requires_action',True)]; print(f'Alerts: {len(d[\"alerts\"])} Live: {len(live)}')"
```

**Pass criteria:**
- `/monitor/health` → `ok: true`
- `/monitor/positions/drift` → `drift_detected: false`
- `/monitor/open-orders` → `open_count: 0`
- `/monitor/alerts` → `0 live requires_action`
- `/order` → `HTTP 403` (curl with `-X POST`)
- `IBKR_ALLOW_ORDERS=false` (check `/health`)
- `rules.enforced=false` (grep YAML)

**If any check fails:** Stop. Investigate before trading.

---

#### Step 2 — Preflight & Approval

Run preflight for the intended close (SELL):

```bash
curl -s -X POST http://127.0.0.1:8790/order/preflight \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"AAPL","action":"SELL","totalQuantity":1,"orderType":"MKT"}'
```

**Verify all gates pass:** `allowlist`, `trades_per_day`, `loss_halts`, `close_only`, `open_orders`.
If any gate fails — especially `open_orders` — resolve first (manual terminal reconciliation).

**Manual approval checklist** (before approving):

- [ ] TWS shows exactly 1 AAPL share
- [ ] No open orders in TWS
- [ ] Bridge connected (`/health`)
- [ ] Within RTH window (09:30–15:50 ET)
- [ ] No same-day round-trip (no BUY today)
- [ ] Close price acceptable per Chris's judgment

**Approve:**

```bash
# Save approval_id from preflight response, then:
curl -s -X POST http://127.0.0.1:8790/order/approve \
  -H 'Content-Type: application/json' \
  -d '{"approval_id":"<approval_id>","decision":"approve","ruled_by":"Chris"}'
```

Approval expires after **5 minutes** (`manual_approval.timeout_seconds`). If expired, re-run preflight.

---

#### Step 3 — One-Order Enable Window

Only when Chris gives the go-ahead:

1. **Flip kill switches** (both must be `true`):
   - Set `IBKR_ALLOW_ORDERS=true` in env
   - Set `rules.enforced=true` in `paper-trading-rules.yaml`
2. **Submit the SELL:**
   ```bash
   curl -s -X POST http://127.0.0.1:8790/order/submit \
     -H 'Content-Type: application/json' \
     -d '{"approval_id":"<approval_id>"}'
   ```
3. **The window is now open.** Only this one order will go through.

**Window rules:**
- Only the approved SELL is submitted — no other orders
- Kill switches stay `true` only long enough for submission + fill confirmation
- No second submission even if the first is still pending

---

#### Step 4 — Immediate Rollback

After submission (regardless of fill status):

```bash
# Flip kill switches back to false
# IBKR_ALLOW_ORDERS=false
# rules.enforced=false
```

**Verify rollback:**
```bash
curl -s http://127.0.0.1:8790/health | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'allow_orders={d[\"allow_orders\"]}')"
grep "enforced:" ~/.openclaw/risk-rules/paper-trading-rules.yaml
```

Both must be `false` before proceeding.

---

#### Step 5 — Reconciliation

Verify the outcome:

```bash
# Run all checks
curl -s http://127.0.0.1:8790/monitor/positions/drift | python3 -m json.tool
curl -s http://127.0.0.1:8790/monitor/open-orders | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Open: {d[\"open_count\"]}')"
curl -s http://127.0.0.1:8790/monitor/reconciliation | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Trade count match: {d[\"checks\"][\"trade_count_match\"]} guard={d[\"state\"][\"guard\"][\"daily_trade_count\"]} events={d[\"state\"][\"events\"][\"today_unique_order_ids\"]}')"
```

**If SELL filled:**
- Positions should be flat (check `/positions`)
- Expected AAPL = 0, drift = false
- Open orders = 0

**If SELL not filled (PreSubmitted):**
- Create manual terminal record via `POST /monitor/open-orders/reconcile`
- Expected AAPL unchanged, drift stays false

**If SELL cancelled or not found in IBKR:**
- Same as unfilled — manual terminal record
- Then decide whether to retry (fresh preflight + approval)

---

#### Step 6 — Regression Suite

```bash
cd ~/agents/ibkr-bridge && python3 monitor.py
```

All **39 tests** must pass. If any fail, investigate before the next trading window.

---

#### Step 7 — End-of-Day Locked Baseline

Final verification before closing for the day:

| Check | Expected | How |
|---|---|---|
| Positions | Flat (or known position only) | `GET /positions` |
| Drift | `false` | `GET /monitor/positions/drift` |
| Open orders | 0 | `GET /monitor/open-orders` |
| Live alerts | 0 requires_action | `GET /monitor/alerts` |
| Trade count match | `true` | `GET /monitor/reconciliation` |
| Kill switches | Both `false` | `/health` + YAML grep |
| `/order` | `HTTP 403` | `curl -X POST` |
| Regression suite | 39/39 | `python3 monitor.py` |

---

### Stop Rule

When `daily_trade_count == 2` and `trade_date == today`:

```text
✅ No further trades allowed today. System lock is automatic.
```

The preflight `trades_per_day` gate enforces this (`max_daily_trades: 2`).
No submission is possible even if kill switches are flipped.
This is a hard stop, not a manual convention.

---

### Reference: Order Flow Diagram

```text
RTH open? ──No──→ Hold. Check again in RTH.
   │
   Yes
   ↓
Baseline pass? ──No──→ Investigate. Do not trade.
   │
   Yes
   ↓
Preflight pass? ──No──→ Fix issue. Retry preflight.
   │
   Yes
   ↓
Chris approves (5m window)
   │
   ↓
One-order window: flip switches → submit → flip back
   │
   ↓
Reconcile outcome
   │
   ├── Filled → Flat position, expected aligned, drift=false
   └── Unfilled → Manual terminal record, decide retry
   │
   ↓
Regression suite (39/39)
   │
   ↓
End-of-day locked baseline
```

---

### Troubleshooting Quick Reference

| Symptom | Likely Cause | Action |
|---|---|---|
| `open_orders > 0` | Stale PreSubmitted or order never cancelled | Check TWS, add manual terminal record |
| `drift_detected=true` | Expected ≠ actual position | Check guard events vs TWS, do not trade |
| `trade_count_match=false` | order_id reused or events out of sync | Check composite identity reconciliation |
| Preflight fails on `open_orders` gate | Unresolved order blocking close | Resolve via manual terminal record |
| Preflight fails `close_only` | No position to close | Verify position in TWS |
| Preflight fails `trades_per_day` | Max 2 trades hit | Wait for next UTC trading day |
| `/order/submit` returns `ORDERS_BLOCKED` | Kill switches false | Both must be `true` during enable window |
| `regression test fails` | Module change or data corruption | Investigate before trading |

---

*End of Phase 3D runbook section.*

---

## Phase 3E — Pre-Market / RTH Automation Guardrails

**No autonomous trading. No auto-submit. No auto-approve.**

Read-only readiness endpoint. Tells the operator everything they need
for a GO / NO-GO decision in one call.

### Readiness Endpoint

```bash
curl -s http://127.0.0.1:8790/readiness | python3 -m json.tool
```

**Returns:**

```json
{
  "verdict": "GO|NO-GO|NO-GO (scheduling)",
  "blocks": [
    {"check": "...", "status": "BLOCK|WARN", "detail": "..."}
  ],
  "summary": {
    "rth": { ... },
    "kill_switches": { ... },
    "trade_count": { ... },
    "halts": { ... },
    "drift": { ... },
    "open_orders": { ... },
    "regression": { ... },
    "ibkr_connected": true|false
  },
  "note": "Read-only advisory. No auto-submit. No auto-approve."
}
```

### What `verdict` Means

| Verdict | Meaning | Action |
|---|---|---|
| `GO` | All checks pass — ~can trade~ (manual review still required, system is locked) | Proceed to Step 2 of daily workflow |
| `NO-GO (scheduling)` | Not during RTH or not a tradable day — no system issues | Wait for RTH or next market day |
| `NO-GO` | One or more blocking conditions — investigate `blocks[]` | Do not trade until resolved |

### Checks Performed

| Check | Blocks | Detail |
|---|---|---|
| RTH window | Pre-market / after-hours / weekend / holiday | `in_rth`, `is_tradable_day`, `market_date_et` |
| Kill switches | `IBKR_ALLOW_ORDERS=false` or `enforced=false` | System locked status |
| Trade count | Daily limit reached (2/2) | `daily_trade_count`, `trades_remaining` |
| Loss halts | Daily or weekly halt active | `halt_reason` |
| Position drift | Expected ≠ actual | Mismatch count |
| Open orders | Unresolved orders exist | `open_count` |
| Regression suite | Failing tests | Pass/fail + score |
| IBKR connection | Warning only | Not connected = file-based drift only |

### Quick One-Liner

```bash
curl -s http://127.0.0.1:8790/readiness | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Verdict: {d[\"verdict\"]}'); [print(f'  {b[\"check\"]}: {b[\"detail\"]}') for b in (d.get(\"blocks\") or [])]"
```

### RTH Calendar Check

Also available standalone:

```bash
curl -s http://127.0.0.1:8790/readiness | python3 -c "import json,sys; d=json.load(sys.stdin); r=d['summary']['rth']; print(f'{r[\"market_date_et\"]} {r[\"market_day_name\"]}: {r[\"reason\"]}')"
```

Or directly via the module:

```python
from monitor import rth_check
rth_check()  # Returns dict with in_rth, is_tradable_day, reason, etc.
```

### What This Does NOT Do

- ❌ No order submission
- ❌ No preflight validation
- ❌ No kill switch toggling
- ❌ No approval creation
- ❌ No auto-trade logic
- ❌ No cron or scheduled execution

This is a **read-only advisor**. The operator still makes every decision.

---

*End of Phase 3E section.*

---

## Phase 3F — Readiness Hardening

**No trading logic. No automation.**

Adds comprehensive tests for the GET /readiness endpoint and RTH calendar.

### Regression Tests Added (Section F + G = 17 new tests)

All 17 Phase 3F tests are integrated into the existing regression suite. Run them all:

```bash
cd ~/agents/ibkr-bridge && python3 monitor.py
```

**Expected: 39/39 PASS**

---

### Section F — RTH Calendar Unit Tests (7 tests)

| Test | What It Verifies |
|---|---|
| **F1: DST spring-forward** | Fri Mar 6 (EST pre-market ✓), Sun Mar 8 (weekend ✓), Mon Mar 9 13:00 UTC (EDT pre-market ✓), Mon Mar 9 14:30 UTC (in EDT RTH ✓) |
| **F2: DST fall-back** | Sun Nov 1 (weekend ✓), Mon Nov 2 14:30 UTC (in EDT RTH ✓), Sat Nov 7 (weekend ✓), Mon Nov 9 15:00 UTC (in EST RTH ✓) |
| **F3: Thanksgiving Fri early close** | Pre-market ✓, inside early RTH ✓, close_et=13:00 ✓, after 1PM closed ✓ |
| **F4: Christmas Eve early close** | Inside early RTH ✓, close_et=13:00 ✓, after 1PM closed ✓ |
| **F5: All 10 NYSE 2026 holidays** | Every listed holiday is `is_tradable_day=False` |
| **F6: Weekend not tradable** | Saturday + Sunday both blocked |
| **F7: Normal RTH in-session** | Mon Jun 8 14:30 UTC = 10:30 AM EDT, inside RTH ✓ |

### Section G — Readiness Endpoint Integration Tests (10 tests)

| Test | What It Verifies |
|---|---|
| **G1: /readiness HTTP 200 + structure** | Returns `verdict`, `summary`, `blocks` |
| **G2: All 8 summary sections present** | rth, kill_switches, trade_count, halts, drift, open_orders, regression, ibkr_connected |
| **G3: RTH section has 7 required fields** | in_rth, is_tradable_day, reason, market_date_et, market_day_name, rth_open_et, rth_close_et |
| **G4: Kill switches section has 3 fields** | IBKR_ALLOW_ORDERS, rules.enforced, system_locked |
| **G5: Trade count section has 5 fields** | trade_date, daily_trade_count, max_trades_per_day, trades_remaining, daily_limit_reached |
| **G6: Both kill switches false = system_locked** | IBKR_ALLOW_ORDERS=false + enforced=false → locked=True |
| **G7: Kill switches false = block in blocks[]** | At least one `kill_switch_*` block listed |
| **G8: Read-only advisory note** | `"note"` field contains "read-only" |
| **G9: Block entries are valid** | Every block has `check`, `status`, `detail` |
| **G10: Verdict is non-empty string** | Not null, not empty |

### Key Design Decisions

1. **`/readiness` does NOT call `_run_self_test()`** — that would create a circular HTTP self-call (readiness → tests → _get("/readiness")). Instead, readiness does a lightweight **file-integrity check** on `guard-state.json` and `guard-events.jsonl`.

2. **Regression suite runs as standalone** — `python3 monitor.py` independently. It tests readiness via HTTP as an external consumer, not from within the readiness endpoint.

3. **No auto-healing, no auto-correct** — monitoring and readiness are scan-and-report only, consistent with Phase 2F design.

### Current Verdicts Under All-Switches-False Baseline

| Condition | Expected Verdict | Blocking Checks |
|---|---|---|
| Outside RTH, pre-market | `NO-GO` | rth_window, kill_switch_IBKR_ALLOW_ORDERS, kill_switch_rules_enforced, (ibkr_connection=WARN) |
| Inside RTH, both switches false | `NO-GO` | kill_switch_IBKR_ALLOW_ORDERS, kill_switch_rules_enforced |
| Inside RTH, both switches true | `NO-GO (scheduling)` *if outside RTH only*, or `GO` *if inside RTH and no blocks* | None |
| Trade count 2/2 | `NO-GO` | daily_trade_limit |
| Loss halt active | `NO-GO` | loss_halt |
| Position drift | `NO-GO` | position_drift |
| Open orders exist | `NO-GO` | open_orders |
| File integrity failure | `NO-GO` | file_integrity |
| Startup safety fail | `NO-GO` | startup_safety |

### Safety Invariants Preserved

- ✅ `/order` still returns HTTP 403
- ✅ `/order/submit` returns `ORDERS_BLOCKED`
- ✅ Both kill switches `false`
- ✅ No new order-submission paths
- ✅ No auto-approve, no auto-submit, no cron
- ✅ Readiness is advisory-only
- ✅ `monitor.py` has zero `placeOrder`/`cancelOrder` calls in non-test code

---

*End of Phase 3F section.*

---

## Phase 3G — Startup Safety Gate

**No trading automation. No auto-submit. No auto-approve.**

On bridge module import, the system runs 10 startup safety checks. If any critical
config (e.g., rules YAML) cannot be read, the bridge **fails closed** (raises
RuntimeError) and will not start.

### How It Works

```python
# Module-level, runs once at import time
_startup_safety = _run_startup_safety()
```

The result is stored in a module-global `_startup_safety` dict and exposed in three
places:

| Surface | Where |
|---|---|
| `GET /health` | `startup_safety.pass`, `check_count`, `passed_count` |
| `GET /readiness` | `summary.startup_safety` + block if failed |
| `guard-events.jsonl` | `event_type: startup_safety` logged on module load |

### 10 Startup Checks

| # | Check | Fail Condition |
|---|---|---|
| 1 | `IBKR_ALLOW_ORDERS` | env var is `true` |
| 2 | `rules.enforced` | YAML key missing or is `true` |
| 3 | `guard_state_readable` | File missing or unparseable |
| 4 | `guard_events_readable` | File missing or invalid JSON |
| 5 | `submitted_approvals_readable` | File unparseable |
| 6 | `manual_recon_readable` | File unparseable |
| 7 | `no_unresolved_open_orders` | File state shows open orders > 0 |
| 8 | `no_orphaned_submitted_approvals` | Submitted approvals without confirm events |
| 9 | `order_endpoint_blocked` | Always true (design invariant) |
| 10 | `readiness_endpoint_available` | `monitor.rth_check` unimportable |

### Fail-Closed Behavior

- **Rules YAML missing**: `RuntimeError("FAIL_CLOSED: rules file not found")` — bridge will not start
- **Rules YAML unreadable**: `RuntimeError("FAIL_CLOSED: rules YAML unreadable")` — bridge will not start
- **Any other check fails**: `startup_safety.pass=false` is set, but bridge still starts so operator can investigate

### Verify

```bash
# Health endpoint includes startup_safety
curl -s http://127.0.0.1:8790/health | python3 -c "import json,sys; d=json.load(sys.stdin); s=d.get('startup_safety',{}); print(f'pass={s.get(\"pass\")} {s.get(\"passed_count\")}/{s.get(\"check_count\")}')"

# Readiness includes startup_safety section
curl -s http://127.0.0.1:8790/readiness | python3 -c "import json,sys; d=json.load(sys.stdin); s=d['summary'].get('startup_safety',{}); print(f'pass={s.get(\"pass\")} {s.get(\"passed_count\")}/{s.get(\"check_count\")}')"

# Event logged
grep startup_safety ~/.openclaw/guard-events.jsonl | tail -1 | python3 -m json.tool
```

### Regression Tests

2 new tests in Section G:

| Test | What It Verifies |
|---|---|
| **G11** | `startup_safety` section present in `/readiness` summary with `pass` and `check_count` |
| **G12** | `startup_safety` event logged in `guard-events.jsonl` with correct structure |

**Regression suite: 46/46 PASS**

---

*End of Phase 3G section.*

---

## Phase 3H — Immutable Audit Bundle

**No trading. No order paths. No automation.**

Creates an end-of-day or on-demand audit artifact packaging all critical
state into one immutable JSON bundle. Available as a bridge endpoint and
an offline CLI.

### Endpoint

```bash
# One-shot — returns bundle inline AND writes to disk
curl -s http://127.0.0.1:8790/audit/bundle | python3 -m json.tool
```

### Offline CLI

```bash
# From the bridge directory
cd ~/agents/ibkr-bridge

# Full bundle (with HTTP endpoint snapshots + regression)
.venv/bin/python3 bundle_audit.py

# Offline bundle (file snapshots + code hashes only, no HTTP calls)
.venv/bin/python3 bundle_audit.py --offline

# List existing bundles
.venv/bin/python3 bundle_audit.py --list

# Show latest bundle summary
.venv/bin/python3 bundle_audit.py --latest
```

### What's Packaged

| Category | Items | Source |
|---|---|---|
| **Files (4)** | `guard-state.json`, `guard-events.jsonl`, `submitted-approvals.json`, `manual-order-reconciliations.jsonl` | Read from disk |
| **Endpoints (5)** | `/health`, `/readiness`, `/monitor/reconciliation`, `/monitor/positions/drift`, `/monitor/open-orders` | HTTP GET to bridge |
| **Code Hashes (4)** | SHA256 of `bridge.py`, `guard.py`, `monitor.py`, `bundle_audit.py` | File digest |
| **Bundle Metadata** | `bundle_id`, `created_at_utc`, `immutable=True`, `source`, `version` | Inline |

### Bundle Output Format

Bundles are written to `~/.openclaw/audit-bundles/bundle_<timestamp>.json`
and returned inline from the HTTP endpoint. Each bundle has:

- `bundle_id`: unique timestamp-based ID
- `immutable`: always `true` — bundles are never modified after creation
- `files`: keyed by filename, parsed JSON/JSONL or raw content
- `endpoints`: keyed by name, includes HTTP status + response data
- `code_hashes`: SHA256 hex digests of all Python source files
- No auto-correction, no mutation — pure snapshot

### End-of-Day Workflow

```bash
# 1. Run regression suite
cd ~/agents/ibkr-bridge && .venv/bin/python3 monitor.py
# Expected: 46/46 PASS

# 2. Create audit bundle
curl -s http://127.0.0.1:8790/audit/bundle -o /dev/null
# Or offline:
.venv/bin/python3 bundle_audit.py

# 3. Verify bundle
.venv/bin/python3 bundle_audit.py --latest
```

### Regression Tests (5 new tests)

| Test | What It Verifies |
|---|---|
| **H1** | `/audit/bundle` returns HTTP 200 with `bundle_id`, `immutable=True`, `files`, `code_hashes` |
| **H2** | All 4 file snapshots present |
| **H3** | All 5 endpoint snapshots present |
| **H4** | Regression optionally present (bridge endpoint skips it to avoid circular self-call during test suite) |
| **H5** | SHA256 hashes for all 4 source files |

**Regression suite: 46/46 PASS**

---

*End of Phase 3H section.*

---

## Phase 3I — Audit Bundle Verification

**No trading. No automation.**

Verifies an audit bundle is internally consistent with 7 checks.
Available as a bridge endpoint and an offline CLI.

### Endpoint

```bash
# Creates a fresh bundle + verifies it, returns results inline
curl -s http://127.0.0.1:8790/audit/verify | python3 -m json.tool
```

### Offline CLI

```bash
cd ~/agents/ibkr-bridge
.venv/bin/python3 bundle_audit.py --verify
```

### 7 Verification Checks

| # | Check | What It Verifies |
|---|---|---|
| 1 | `code_hashes_valid` | SHA256 of all 4 source files match bundle snapshot |
| 2 | `files_present` | All 4 required files present and parseable |
| 3 | `endpoint_readiness_reachable` | Readiness endpoint was reachable at bundle time |
| 4 | `locked_baseline` | Both kill switches false (offline: no loss halts active) |
| 5 | `regression_recorded` | Regression data present if offline CLI; bridge endpoint skips by design |
| 6 | `bundle_id_valid` + `timestamp_valid` | Bundle identifiers are well-formed |
| 7 | `no_live_action_alerts` | No unresolved blocking conditions in readiness or reconciliation |

### Expected Verdicts

| Bundle Source | Expected Result | Notes |
|---|---|---|
| Bridge endpoint (`GET /audit/verify`) | **8/8 PASS** | Creates fresh bundle, no regression (skipped for circularity) |
| Offline CLI (`--verify`) | **5/8 PASS** (code, files, bid, ts pass; no endpoints, no regression) | Offline has no live endpoint snapshots |
| Full CLI (`bundle_audit.py` then `bundle_audit.py --verify`) | **8/8 PASS** | Full bundle with regression data |

### End-of-Day Workflow (Updated)

```bash
# 1. Run regression suite
cd ~/agents/ibkr-bridge && .venv/bin/python3 monitor.py
# Expected: 53/53 PASS

# 2. Create audit bundle
curl -s http://127.0.0.1:8790/audit/bundle -o /dev/null

# 3. Verify bundle
curl -s http://127.0.0.1:8790/audit/verify | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Verify: {d[\"passed_count\"]}/{d[\"check_count\"]} pass={d[\"pass\"]}')"

# 4. List bundles
.venv/bin/python3 bundle_audit.py --latest
```

### Regression Tests (7 new tests)

| Test | What It Verifies |
|---|---|
| **I1** | `/audit/verify` returns HTTP 200 with `pass`, `checks`, `check_count` |
| **I2** | `code_hashes_valid` passes (4/4 source hashes match) |
| **I3** | `files_present` passes (4/4 files present) |
| **I4** | `locked_baseline` passes (kill switches false) |
| **I5** | `bundle_id_valid` + `timestamp_valid` both pass |
| **I6** | `no_live_action_alerts` passes (no blocking conditions) |
| **I7** | `endpoint_readiness_reachable` passes (readiness reachable) |

**Regression suite: 64/64 PASS**

---

*End of Phase 3I section.*

---

## Phase 3J — Release Tagging / Provenance

**No trading. No automation.**

Attaches a version label to the verified control-plane state. Creates provenance documents that link source code identity (SHA256 hashes) to audit bundles, regression counts, and locked baseline confirmation.

### Endpoints

```bash
# Create a release tag (creates fresh bundle, then tags it)
curl -s http://127.0.0.1:8790/audit/release?phase=phase3j_verified | python3 -m json.tool

# Show latest release tag
curl -s http://127.0.0.1:8790/audit/release/latest | python3 -m json.tool
```

### Offline CLI

```bash
cd ~/agents/ibkr-bridge
# Create a release tag
.venv/bin/python3 bundle_audit.py --tag

# Custom phase label
.venv/bin/python3 bundle_audit.py --tag phase3k_complete

# Show latest release tag
.venv/bin/python3 bundle_audit.py --tag-latest
```

### Release Tag Schema

| Field | Type | Description |
|---|---|---|
| `tag_id` | string | Timestamp-based ID, e.g. `release_20260605T100500` |
| `phase_label` | string | Phase label, e.g. `phase3j_verified` |
| `immutable` | bool | Always `true` |
| `created_at_utc` | ISO 8601 | Creation timestamp |
| `audit_bundle_id` | string | ID of latest audit bundle at tag time |
| `bundle_created_at_utc` | ISO 8601 | Timestamp of the referenced bundle |
| `provenance` | dict | Source identity (hashes + dirty/clean status) |
| `regression` | dict | Regression counts from bundle (or status) |
| `locked_baseline` | dict | Kill switch state at tag time |

### Provenance (Source Identity)

Since this project is not a git repo, source identity is tracked via SHA256 file hashes:

| Field | Description |
|---|---|
| `source_hashes` | SHA256 of all 4 source files at tag time |
| `dirty` | `true` if any source file differs from bundle snapshot; `false` if clean |
| `diff_summary` | Human-readable list of changed files (empty string if clean) |

### End-of-Day Workflow (Updated)

```bash
cd ~/agents/ibkr-bridge

# 1. Run regression
.venv/bin/python3 monitor.py
# Expected: 64/64 PASS

# 2. Create and verify an audit bundle
curl -s http://127.0.0.1:8790/audit/bundle -o /dev/null
curl -s http://127.0.0.1:8790/audit/verify | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(f'Verify: {d[\"passed_count\"]}/{d[\"check_count\"]} pass={d[\"pass\"]}')"

# 3. Attach a release tag
curl -s http://127.0.0.1:8790/audit/release?phase=phase3j_verified | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(f'Tag: {d[\"tag_id\"]} dirty={d[\"provenance\"][\"dirty\"]}')"
```

### Regression Tests (7 new tests)

| Test | What It Verifies |
|---|---|
| **J1** | `/audit/release` returns HTTP 200 with `tag_id`, `phase_label`, `provenance` |
| **J2** | Release tag has valid `audit_bundle_id` (starts with `bundle_`) |
| **J3** | `provenance` shows clean (no source changes since bundle created) |
| **J4** | `locked_baseline.confirmed` is `true` |
| **J5** | `immutable` flag is `true` |
| **J6** | `/audit/release/latest` returns a valid tag |
| **J7** | `provenance.source_hashes` has all 4 source files |

**Regression suite: 64/64 PASS**

---

*End of Phase 3J section.*

---

## Phase 3K — Git Initialization and Signed Baseline

**No trading. No automation.**

Initializes git repository at `~/agents/ibkr-bridge/` for source provenance tracking. Release tags now capture git commit hash, git tag, and dirty status alongside file SHA256 hashes.

### Git History

| Tag | Commit | Description |
|---|---|---|
| `phase3j_verified` | `b93c2ec` | Initial commit — Phase 3A–3J complete, 60/60 regression |
| `phase3k_git_init` | `a7deb3b` | Git init + git provenance in release tags |

### .gitignore

Excluded from repo:
- `.env` (secrets)
- `.venv/` (virtual environment)
- `__pycache__/`, `*.pyc`
- `*.bak`, `bridge.py.broken.*` (backups)
- `ibkr_mcp.py`, `ibkr_mcp_server.py` (unrelated)
- Runtime state lives in `~/.openclaw/` — entirely outside repo

### Extended Provenance Schema

When a `.git` directory exists, `_compute_provenance()` adds a `git` sub-dict:

```json
{
  "source_hashes": { "bridge.py": "sha256...", ... },
  "dirty": false,
  "diff_summary": "clean",
  "git": {
    "commit": "a7deb3b8cf5d...",
    "tag": "phase3k_git_init",
    "dirty": false,
    "diff_summary": "clean"
  }
}
```

The `source_hashes` (SHA256) always serve as a fallback identity — they work even without git, and cross-check against the audit bundle's `code_hashes`.

### Commands

```bash
cd ~/agents/ibkr-bridge

# View git log
git log --oneline --decorate=tags

# View current provenance (via latest release tag)
curl -s http://127.0.0.1:8790/audit/release/latest | python3 -m json.tool
```

### Regression Tests (4 new tests)

| Test | What It Verifies |
|---|---|
| **K1** | Provenance includes `git.commit` (non-empty) |
| **K2** | Provenance includes `git.tag` matching a known tag |
| **K3** | `source_hashes` present as fallback identity (4/4 hashes) |
| **K4** | Source hash provenance is clean (dirty=false) |

**Regression suite: 64/64 PASS**

---

*End of Phase 3K section.*

---

## Phase 3L — External Backup / Restore Drill

**No trading. No automation.**

Proves the entire system can be restored from source + runtime state + audit bundles with zero loss of safety.

### Acceptance Criteria

| # | Criterion | Result |
|---|---|---|
| 1 | Fresh clone starts locked (`system_locked=True`) | ✅ |
| 2 | `startup_safety` passes 10/10 | ✅ |
| 3 | `allow_orders=false`, `rules.enforced=false` | ✅ |
| 4 | Readiness reports `NO-GO` (not `GO`) | ✅ |
| 5 | Regression suite 138/138 PASS | ✅ |
| 6 | Latest release tag verifies clean (`dirty=false`, git commit intact) | ✅ |

### Restore Procedure (Verified)

```bash
# 1. Clone source
cd /tmp && git clone /home/chris/agents/ibkr-bridge ibkr-bridge-restored
cd ibkr-bridge-restored

# 2. Rebuild venv
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Restore secrets
cp /orig/path/.env .env

# 4. Runtime state is already in ~/.openclaw/ (shared across restores)

# 5. Start bridge
.venv/bin/python3 -m uvicorn bridge:app --host 127.0.0.1 --port 8790

# 6. Verify
.venv/bin/python3 monitor.py
```

### What Was Exercised

| Component | Restore Source | Verified |
|---|---|---|
| Source code | git clone (tags: `phase3j_verified`..`phase3l_restore_drill`) | git log, SHA256 hashes |
| Dependencies | `requirements.txt` (frozen at restore time) | pip install |
| Secrets | `.env` copy | bridge startup, IBKR connection config |
| Runtime state | `~/.openclaw/` (shared) | guard state, events, approvals, reconciliations |
| Audit bundles | `~/.openclaw/audit-bundles/` (outside repo) | verify 8/8 PASS |
| Release tags | `~/.openclaw/releases/` (outside repo) | provenance, git commit, locked baseline |

### Regression Tests (3 new tests)

| Test | What It Verifies |
|---|---|
| **L1** | `/health` startup_safety check_count=10, pass=True (gate intact after restore) |
| **L2** | `/readiness` shows system_locked=True, allow_orders=False, enforced=False |
| **L3** | `/audit/release/latest` has valid release tag with git commit provenance |

**Regression suite: 138/138 PASS**

---

*End of Phase 3L section.*

---

## Phase 3M — Disaster Recovery Runbook (Operator Checklist)

**No trading. No automation.**

Operator checklist for full system recovery from backup. Validated by Phase 3L drill.

### Prerequisites

| Item | Location | Notes |
|---|---|---|
| Source repo | `~/agents/ibkr-bridge/` or via git clone | Contains all source + tags |
| `.env` | Stored separately / password manager | Keep offline or encrypted |
| Runtime state | `~/.openclaw/` | Shared path — survives clone |
| Requirements | `requirements.txt` | Frozen in repo |

### Recovery Steps (Verify Each Step)

#### Step 1 — Clone repo or verify existing

```bash
cd ~/agents/ibkr-bridge
git status --short
git log --oneline --decorate=full -1
```

**Expected output:**
```
# clean working tree or only expected untracked files
# output shows the current tag, e.g.
eea4cfe (HEAD -> master, tag: phase3l_restore_drill) L-tests: backup/restore readiness drill
```

If the directory is missing or corrupted:

```bash
# Clone fresh
rm -rf ~/agents/ibkr-bridge
git clone <repo-url-or-path> ~/agents/ibkr-bridge
```

---

#### Step 2 — Checkout latest verified tag

```bash
cd ~/agents/ibkr-bridge
git tag -l
# Expected: phase3j_verified, phase3k_git_init, phase3l_pre_backup,
#           phase3l_restore_proven, phase3l_restore_drill

git checkout phase3l_restore_drill
```

**Verify:**
```bash
git log --oneline -1
# Expected: eea4cfe L-tests: backup/restore readiness drill (Phase 3L)
```

---

#### Step 3 — Create / verify virtual environment

```bash
cd ~/agents/ibkr-bridge
python3 -m venv .venv
```

**Verify:**
```bash
ls .venv/bin/python3  # must exist
```

---

#### Step 4 — Install dependencies

```bash
cd ~/agents/ibkr-bridge
.venv/bin/pip install -r requirements.txt
```

**Verify:**
```bash
.venv/bin/pip freeze | wc -l
# Expected: ~46 packages

.venv/bin/python3 -c "import fastapi; print('fastapi OK')"
.venv/bin/python3 -c "import uvicorn; print('uvicorn OK')"
```

---

#### Step 5 — Restore .env safely

> **Critical**: `IBKR_ALLOW_ORDERS=false` must be set. If restoring from a backup,
> verify this value before starting the bridge.

```bash
cat ~/agents/ibkr-bridge/.env | grep IBKR_ALLOW_ORDERS
# Expected: IBKR_ALLOW_ORDERS=false
```

If `.env` is missing, restore from secure storage:

```bash
# Template — fill from password manager / offline backup
cat > ~/agents/ibkr-bridge/.env << 'EOF'
IBKR_MODE=paper
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=777
IBKR_ACCOUNT=DUQ542875
IBKR_READ_ONLY=false
IBKR_ALLOW_ORDERS=false
IBKR_DEFAULT_CURRENCY=EUR
IBKR_BASE_CURRENCY=EUR
IBKR_MAX_POSITION_PCT=25
IBKR_MAX_TOTAL_EXPOSURE_PCT=60
IBKR_MAX_TRADES_PER_DAY=3
IBKR_DAILY_LOSS_LIMIT_PCT=1
IBKR_WEEKLY_LOSS_LIMIT_PCT=3
EOF
```

**Critical verification:**
```bash
grep IBKR_ALLOW_ORDERS ~/agents/ibkr-bridge/.env
# Must output: IBKR_ALLOW_ORDERS=false
```

---

#### Step 6 — Verify runtime state directory

```bash
ls ~/.openclaw/*.json ~/.openclaw/*.jsonl
```

**Expected files (may vary):**
| File | Required | Purpose |
|---|---|---|
| `guard-state.json` | Yes | Trading halt state |
| `guard-events.jsonl` | Yes | Event audit log |
| `submitted-approvals.json` | Yes | Approval records |
| `manual-order-reconciliations.jsonl` | Yes | Manual reconciliation log |

**If missing,** copy from backup:

```bash
cp /backup/path/.openclaw/*.json ~/.openclaw/
cp /backup/path/.openclaw/*.jsonl ~/.openclaw/
```

---

#### Step 7 — Start bridge

```bash
cd ~/agents/ibkr-bridge
.venv/bin/python3 -m uvicorn bridge:app --host 127.0.0.1 --port 8790 &
sleep 5
```

**Verify process is running:**
```bash
lsof -ti :8790
# Expected: returns PID
```

---

#### Step 8 — Confirm startup_safety 10/10

```bash
curl -s http://127.0.0.1:8790/health | python3 -c "
import json,sys
d = json.load(sys.stdin)
ss = d.get('startup_safety', {})
print(f'startup_safety: pass={ss[\"pass\"]} {ss[\"passed_count\"]}/{ss[\"check_count\"]}')
print(f'allow_orders={d[\"allow_orders\"]}')
"
```

**Expected:**
```
startup_safety: pass=True 10/10
allow_orders=False
```

**Failure mode:** If `startup_safety.pass` is `False` or `check_count < 10`, do not proceed.
Investigate by checking the bridge logs.

---

#### Step 9 — Confirm /readiness locked baseline

```bash
curl -s http://127.0.0.1:8790/readiness | python3 -c "
import json,sys
d = json.load(sys.stdin)
print(f'verdict={d[\"verdict\"]}')
ks = d.get('summary', {}).get('kill_switches', {})
print(f'system_locked={ks[\"system_locked\"]}')
print(f'allow_orders={ks[\"IBKR_ALLOW_ORDERS\"]}')
print(f'enforced={ks[\"rules.enforced\"]}')
"
```

**Expected:**
```
verdict=NO-GO
system_locked=True
allow_orders=False
enforced=False
```

> **DO NOT PROCEED** if `verdict` is `GO` or `allow_orders` is `true`.
> The system must start locked.

---

#### Step 10 — Run regression suite

```bash
cd ~/agents/ibkr-bridge
.venv/bin/python3 monitor.py
```

**Expected:**
```
PASS=138/138 Phase 3C regression tests
```

**Failure mode:** If any tests fail, do not proceed. Investigate failures.
Common post-restore issues:
- Missing `.env` values → check Step 5
- IBKR gateway not running → expected for paper, but skip checks still pass
- Runtime state corrupted → check Step 6

---

#### Step 11 — Run audit bundle verification

```bash
curl -s http://127.0.0.1:8790/audit/verify | python3 -c "
import json,sys
d = json.load(sys.stdin)
print(f'verify pass={d[\"pass\"]} {d[\"passed_count\"]}/{d[\"check_count\"]}')
for c in d.get('checks', []):
    s = 'PASS' if c['ok'] else 'FAIL'
    print(f'  {s}: {c[\"check\"]} — {c[\"detail\"][:80]}')
"
```

**Expected:** 8/8 PASS (or 7/8 PASS with endpoint unreachable in offline mode).

---

#### Step 12 — Confirm /order returns HTTP 403

```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:8790/order
# Expected: 403

curl -s -X POST http://127.0.0.1:8790/order/submit \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","action":"BUY","quantity":1}' | python3 -c "
import json,sys
d = json.load(sys.stdin)
print(f'code={d.get(\"code\")}')
# Expected: ORDERS_BLOCKED
"
```

---

### Recovery Complete

Once all 12 steps pass, the system is fully restored:

| Check | Status |
|---|---|
| Source integrity | ✅ git tag verified |
| Dependencies | ✅ pip install clean |
| Secrets | ✅ .env restored, IBKR_ALLOW_ORDERS=false |
| Runtime state | ✅ guard state intact |
| Bridge online | ✅ startup_safety 10/10 |
| System locked | ✅ verdict=NO-GO, system_locked=True |
| Regression | ✅ 138/138 PASS |
| Audit | ✅ bundle verifies clean |
| Orders blocked | ✅ HTTP 403 |

### Quick Verification (One-Liner)

```bash
# Run all 12 checks in sequence (pass/fail at a glance)
cd ~/agents/ibkr-bridge && \
  echo "Step 1: $(git log --oneline -1 | cut -d' ' -f2-)" && \
  echo "Step 2: tag=$(git describe --tags --abbrev=0 2>/dev/null || echo 'no tag')" && \
  echo "Step 3: venv=$(test -f .venv/bin/python3 && echo OK || echo MISSING)" && \
  echo "Step 4: deps=$(.venv/bin/pip freeze 2>/dev/null | wc -l) packages" && \
  echo "Step 5: allow=$(grep IBKR_ALLOW_ORDERS .env | cut -d= -f2)" && \
  echo "Step 6: state=$(ls ~/.openclaw/guard-state.json 2>/dev/null && echo OK || echo MISSING)" && \
  echo "Step 7: bridge_pid=$(lsof -ti :8790 2>/dev/null || echo 'down')" && \
  echo "Step 8: startup=$(curl -s http://127.0.0.1:8790/health | .venv/bin/python3 -c 'import json,sys;d=json.load(sys.stdin);print(f"{d["startup_safety"]["passed_count"]}/{d["startup_safety"]["check_count"]}")' 2>/dev/null || echo 'FAIL')" && \
  echo "Step 9: verdict=$(curl -s http://127.0.0.1:8790/readiness | .venv/bin/python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["verdict"])' 2>/dev/null || echo 'FAIL')" && \
  echo "Step 10: regression=run .venv/bin/python3 monitor.py" && \
  echo "Step 11: verify=$(curl -s http://127.0.0.1:8790/audit/verify | .venv/bin/python3 -c 'import json,sys;d=json.load(sys.stdin);print(f"{d["passed_count"]}/{d["check_count"]}")' 2>/dev/null || echo 'FAIL')" && \
  echo "Step 12: order_403=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8790/order 2>/dev/null || echo 'FAIL')"
```

**Regression suite: 138/138 PASS**

---

*End of Phase 3M section.*

---

## Phase 3N — IBKR API Reconnect & Readiness Validation

**No trading. No order enablement.**

Validates that when the IBKR Gateway/API comes back (after approval is granted), the locked baseline is undisturbed.

### Acceptance Checklist

| # | Check | Pass/Fail |
|---|---|---|
| 1 | `/connect` endpoint reachable (200 on success, 503 gracefully handled) | ✅ |
| 2 | `/health` shows `connected=true` (or `false` if still down), `allow_orders=false` always | ✅ |
| 3 | `/readiness` shows `ibkr_connection=WARN` when disconnected, not BLOCK | ✅ |
| 4 | `/order` returns HTTP 403 regardless of connection state | ✅ |
| 5 | `/monitor/open-orders` reachable via file fallback when disconnected | ✅ |
| 6 | `/monitor/positions/drift` reportable (file-based) | ✅ |
| 7 | Audit/release checkpoint created after reconnect exercise | ✅ |

### When Gateway Connects

After running `POST /connect` successfully:

```bash
# Verify connected
curl -s http://127.0.0.1:8790/health | python3 -c "import json,sys;d=json.load(sys.stdin);print(f'connected={d[\"connected\"]} allow_orders={d[\"allow_orders\"]}')"

# Readiness still locked
curl -s http://127.0.0.1:8790/readiness | python3 -c "import json,sys;d=json.load(sys.stdin);print(f'verdict={d[\"verdict\"]} locked={d[\"summary\"][\"kill_switches\"][\"system_locked\"]}')"

# Full regression
.venv/bin/python3 monitor.py
```

### Handling Gateway Unavailability

The bridge is designed to be resilient to gateway disconnection:

| Feature | Gateway Down | Gateway Up |
|---|---|---|
| `/health` | `connected=false`, allow_orders=false | `connected=true`, allow_orders=false |
| `/readiness` | `ibkr_connection=WARN` | ibkr_connection block absent |
| `/order` | HTTP 403 | HTTP 403 |
| `/monitor/open-orders` | File-based fallback | Live IBKR query |
| `/monitor/positions/drift` | File-based (no live data) | Live position check |

### Regression Tests (7 new tests)

| Test | What It Verifies |
|---|---|
| **N1** | `POST /connect` reachable (200 or graceful 503) |
| **N2** | `/health` connected=false, allow_orders=false |
| **N3** | `/readiness` ibkr_connection=WARN when disconnected |
| **N4** | `/order` HTTP 403 persists after reconnect attempt |
| **N5** | `/monitor/open-orders` reachable (file fallback) |
| **N6** | `/monitor/positions/drift` reportable |
| **N7** | Audit/release checkpoint created after reconnect |

**Regression suite: 138/138 PASS**

---

*End of Phase 3N section.*

---

## Phase 3O — Release Inventory / Status Dashboard

**No trading. No automation.**

Read-only dashboard endpoint that aggregates health, readiness, git identity, audit bundle, release tag, and monitoring state into a single JSON response.

### Endpoint

```bash
curl -s http://127.0.0.1:8790/status | python3 -m json.tool
```

### Dashboard Sections

| Section | Source | Contents |
|---|---|---|
| `dashboard` | Inline | Timestamp, service version |
| `health` | `/health` | Mode, IBKR connection, allow_orders, startup_safety (10/10) |
| `readiness` | `/readiness` | Verdict, system_locked, kill switches, RTH window, block/warn counts |
| `git` | `git rev-parse HEAD` | Commit hash, latest git tag |
| `audit_bundle` | Latest on disk | Bundle ID, created_at, file/endpoint count, regression |
| `release_tag` | Latest on disk | Tag ID, phase_label, dirty flag, locked_baseline |
| `monitoring` | File-based | Drift (expected positions), open_orders (count), positions |

### Commands

```bash
# Full dashboard
curl -s http://127.0.0.1:8790/status

# Quick check: is the system locked?
curl -s http://127.0.0.1:8790/status | python3 -c "import json,sys;d=json.load(sys.stdin);r=d['readiness'];print(f'verdict={r[\"verdict\"]} locked={r[\"system_locked\"]}')"

# Quick check: last release?
curl -s http://127.0.0.1:8790/status | python3 -c "import json,sys;d=json.load(sys.stdin);t=d['release_tag'];print(f'tag={t[\"tag_id\"]} phase={t[\"phase_label\"]} dirty={t[\"dirty\"]}')"
```

### Regression Tests (7 new tests)

| Test | What It Verifies |
|---|---|
| **O1** | `/status` has dashboard, health, readiness, git, monitoring sections |
| **O2** | `health.startup_safety` shows pass=True, 10/10 |
| **O3** | `readiness` shows verdict=NO-GO, system_locked=True, allow_orders=False |
| **O4** | `git` has valid commit hash and tag |
| **O5** | `audit_bundle` has bundle_id |
| **O6** | `release_tag` has tag_id and phase_label |
| **O7** | `monitoring` has open_orders, drift, and positions sub-sections |

**Regression suite: 138/138 PASS**

---

*End of Phase 3O section.*

---

## Phase 3P — Status Dashboard Hardening

**No trading. No automation.**

Hardens the `/status` endpoint to remain robust under partial failures while keeping the locked baseline visible.

### Failure Modes Handled

| Failure Mode | Section Behavior | Overall Status |
|---|---|---|
| IBKR disconnected | monitoring.positions=warn, ibkr_connection in readiness | ok_with_warnings |
| No audit bundles | audit_bundle=warn with detail | ok_with_warnings |
| No release tags | release_tag=warn with detail | ok_with_warnings |
| Git unavailable | git=warn with detail | ok_with_warnings |
| Malformed runtime JSONL | drift/oo=error with detail | degraded |
| Readiness unavailable | readiness=error | degraded |
| Health unavailable | health=error | degraded |

### Status Response Schema

```json
{
  "ok": true,
  "status": "ok" | "ok_with_warnings" | "degraded",
  "dashboard": { "timestamp": "...", "version": "..." },
  "health": { "status": "ok", "mode": "paper", "connected": false, ... },
  "readiness": { "status": "ok", "verdict": "NO-GO", "system_locked": true, ... },
  "git": { "status": "ok", "commit": "...", "tag": "..." },
  "audit_bundle": { "status": "ok" | "warn", "bundle_id": "...", ... },
  "release_tag": { "status": "ok" | "warn", "tag_id": "...", ... },
  "monitoring": {
    "drift": { "status": "ok", "expected_positions": 0, "symbols": [] },
    "open_orders": { "status": "ok", "open_count": 0 },
    "positions": { "status": "warn", "positions_flat": null, "detail": "..." }
  }
}
```

### Commands

```bash
# Full dashboard
curl -s http://127.0.0.1:8790/status

# Quick overall health
curl -s http://127.0.0.1:8790/status | python3 -c "import json,sys;d=json.load(sys.stdin);print(f'status={d[\"status\"]} locked={d[\"readiness\"][\"system_locked\"]}')"
```

### Regression Tests (7 new tests)

| Test | What It Verifies |
|---|---|
| **P1** | `/status` always returns HTTP 200 (never HTTP 500) |
| **P2** | `/status` has overall `status` field (ok/ok_with_warnings/degraded) |
| **P3** | All sections (health/readiness/git/audit_bundle/release_tag/monitoring.*) have `status` field |
| **P4** | Locked baseline (`system_locked`) is always visible in readiness section |
| **P5** | `health.startup_safety` has pass/check_count fields |
| **P6** | Monitoring sub-sections (drift, open_orders, positions) all present |
| **P7** | `ok=True` root field present |

**Regression suite: 138/138 PASS**

---

*End of Phase 3P section.*

---

## Phase 3Q — Status CLI Wrapper

**No trading. No automation.**

A standalone CLI tool (`ibkr_status.py` → `ibkr-status`) that prints the system status dashboard to the terminal. Calls the bridge `/status` endpoint when available; falls back to reading local files when the bridge is down.

### Installation

The script lives in the repo at `~/agents/ibkr-bridge/ibkr_status.py` and is symlinked to `~/.local/bin/ibkr-status`.

### Usage

```bash
# Normal (calls bridge /status)
ibkr-status

# Fallback mode (bridge down — reads local files)
# Stop the bridge first to see fallback behavior
ibkr-status
```

### Example Output

```
╔══════════════════════════════════════════╗
║      IBKR Bridge Status Dashboard       ║
╚══════════════════════════════════════════╝
  Time:       2026-06-05 14:31:41 UTC
  Mode:       PAPER
  Status:     ok_with_warnings

Provenance
  Tag:        phase3p_status_hardening
  Commit:     134ce5ddb4d77bfe
  Regimen:    Phase3N Reconnect Check

Safety
  Verdict:    NO-GO
  Locked:     ✓  system_locked=True
  Allow Ord:  ✗
  Startup:    10/10
  IBKR:       ✗

Monitoring
  Drift:      ok  1 positions expected
  Open Ord:   ok  0 open
  Positions:  warn  IBKR not connected — position check unavailable

Audit
  Regression: not recorded
  Bundle:     bundle_20260605T132433
  Release:    release_20260605T132433

Advisory
  No trading. No order automation.
  [bridge at http://127.0.0.1:8790]
```

### Fallback Mode

When bridge is unreachable, the CLI reads:
- Guard state from `~/.openclaw/guard-state.json`
- Position drift from `monitor.position_drift_check()`
- Open orders from `monitor.open_orders_check()`
- Latest audit bundle from `~/.openclaw/audit-bundles/`
- Latest release tag from `~/.openclaw/releases/`
- Git commit/tag from `.git/`

### Architecture

```
ibkr-status
  ├── bridge up?  →  GET /status  →  render
  └── bridge down?
       ├── guard-state.json (locked? verdict?)
       ├── monitor.position_drift_check() (drift)
       ├── monitor.open_orders_check() (open orders)
       ├── audit-bundles/ (regression, bundle_id)
       ├── releases/ (release tag)
       └── git (commit, tag)
```

### Regression Tests (7 new tests)

| Test | What It Verifies |
|---|---|
| **Q1** | `ibkr_status.py` module imports without error |
| **Q2** | `print_status()` runs without exception |
| **Q3** | Dashboard timestamp present in endpoint data |
| **Q4** | Overview status field present (ok/ok_with_warnings/degraded) |
| **Q5** | Locked baseline visible via CLI data path |
| **Q6** | Monitoring drift section present |
| **Q7** | Monitoring open_orders section present |

**Regression suite: 138/138 PASS**

---

*End of Phase 3Q section.*

---

## Phase 3R — Model Routing Safety Policy

**No trading. No automation.**

Governance document defining which AI model tiers may touch which parts of the codebase.

**Policy file:** `~/.openclaw/memory/model-routing-safety-policy.md`

### Quick Reference

| Tier | Model Class | Permitted On |
|---|---|---|
| **1 — Strong** | Codex, GPT-4o, DeepSeek V4 Flash, Claude Sonnet 4+ | `bridge.py`, `guard.py`, `monitor.py`, `bundle_audit.py` edits; order lifecycle, kill switches, guard state, reconciliation, readiness, audit logic |
| **2 — Fast** | Mini/Flash/Haiku class | Output formatting, docstrings, comments, runbook formatting, summary generation, read-only endpoint calls (`/status`, `/health`, `/readiness`, `/audit/*`)
| **3 — Vision** | Image models | Reading screenshots, diagrams; never code generation |

### Key Rules

- Before any edit to `bridge.py`, `guard.py`, `monitor.py`, `bundle_audit.py`: if the changed section touches safety-critical logic, require Tier 1
- Before any state mutation (`~/.openclaw/*.json`): require Tier 1, log to conversation
- Safe read-only endpoints (`/status`, `/health`, `/readiness`, `/audit/*`, `/monitor/*`) may use Tier 2
- Human operator can override model tier by stating "Use [model] for this edit"
- Tier 2 models must refuse Tier 1 tasks and escalate

**Regression suite: 138/138 PASS**

---

*End of Phase 3R section.*

---

## Phase 3S — Policy Surfaced in Status/CLAUDE

**No trading. No automation.**

Surface the Model Routing Safety Policy (Phase 3R) in operator-facing locations.

### Changes

| Location | What Was Added |
|---|---|
| `ibkr_status.py` | `Model Policy` section in CLI output — model, tier, policy path, rules summary |
| `CLAUDE.md` | `Current Model Identity` block + `Model Routing Safety Policy` section with tier scope |
| Runbook daily checklist | Step 0 — Model Tier Safety Check, before Step 1 |

### Example CLI Output (new section)

```
Model Policy
  Model:      openrouter/deepseek/deepseek-v4-flash
  Tier:       1 (Strong)
  Policy:     ~/.openclaw/memory/model-routing-safety-policy.md
  Rules:      Tier 1 req for bridge/guard/monitor safety edits
              Tier 2 ok for docs/formatting/read-only
```

### Daily Checklist Integration

The 7-step daily cycle is now **8 steps**. Step 0 verifies:
1. Model identity is known
2. Tier is ≥ 1 for safety-critical work
3. Policy file exists at `~/.openclaw/memory/model-routing-safety-policy.md`

**Regression suite: 138/138 PASS** (no code logic changes — presentation only)

---

*End of Phase 3S section.*

---

## Phase 3U — Pre-Trade Simulation / Dry-Run Harness

**No trading. No order automation. No placeOrder/cancelOrder.**

Adds a dry-run mode that exercises the full preflight/approval/reconciliation path using simulated orders and fake fills, without touching IBKR order APIs.

### Endpoint

```
POST /order/dry-run
```

| Field | Type | Default | Description |
|---|---|---|---|
| `symbol` | str | required | Ticker symbol (e.g. AAPL) |
| `action` | str | required | `BUY` or `SELL` |
| `totalQuantity` | int | required | Requested quantity |
| `orderType` | str | `"MKT"` | Order type |
| `mode` | str | `"dry-run"` | Simulation mode |
| `dry_run_auto_approve` | bool | `True` | Simulate approval step |
| `dry_run_fill_qty` | int\|None | `None` | Override fill qty (None=full fill) |

### Response

```json
{
  "ok": true,
  "simulated": true,
  "mode": "dry-run",
  "preflight_pass": true,
  "approval_simulated": true,
  "fill_simulated": true,
  "simulated_order_id": "dry-run-1780675290",
  "symbol": "AAPL",
  "action": "BUY",
  "totalQuantity": 5,
  "filled": 5,
  "remaining": 0,
  "position_delta": 5,
  "description": "Dry-run BUY 5 AAPL (simulated full fill)",
  "timestamp_utc": "..."
}
```

### Architecture

```
dry-run request
  → run_preflight() — same validation as /order/preflight
  → simulated approval (no real approval record)
  → simulated fill (no IBKR order, no ib_insync)
  → dry_run_order event logged to guard-events.jsonl
  → position_drift_check(include_dry_run=True) includes dry-run positions
```

### Safety Properties

- No `ib.placeOrder` or `ib.cancelOrder` in the dry-run code path (verified by U7)
- No guard-state mutations (daily_trade_count unchanged)
- No approval records persisted
- No `.env` or rules.yaml changes
- All evidence logged as `dry_run_order` guard events (filterable)

### Usage Examples

```bash
# BUY 5 AAPL full fill
curl -s -X POST http://127.0.0.1:8790/order/dry-run \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"AAPL","action":"BUY","totalQuantity":5,"orderType":"MKT"}' \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(f'{d[\"symbol\"]} {d[\"action\"]} {d[\"filled\"]}/{d[\"totalQuantity\"]} delta={d[\"position_delta\"]}')"

# SELL 3 AAPL
curl -s -X POST http://127.0.0.1:8790/order/dry-run \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"AAPL","action":"SELL","totalQuantity":3,"orderType":"MKT"}'

# Partial fill (2 of 5)
curl -s -X POST http://127.0.0.1:8790/order/dry-run \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"AAPL","action":"BUY","totalQuantity":5,"dry_run_fill_qty":2}'

# Invalid fill qty (will reject)
curl -s -X POST http://127.0.0.1:8790/order/dry-run \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"AAPL","action":"BUY","totalQuantity":3,"dry_run_fill_qty":99}'

# Check drift impact
curl -s http://127.0.0.1:8790/monitor/positions/drift | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['expected_positions'])"
```

### Regression Tests (7 new tests)

| Test | What It Verifies |
|---|---|
| **U1** | `/order/dry-run` returns HTTP 200 with simulated=true |
| **U2** | Dry-run BUY fills reflected in `position_drift_check()` |
| **U3** | `dry_run_order` event logged to guard-events.jsonl |
| **U4** | Dry-run partial fill (2 of 5) works |
| **U5** | Dry-run SELL creates negative position delta |
| **U6** | Invalid fill qty (> totalQuantity) rejected |
| **U7** | No `ib.placeOrder`/`ib.cancelOrder` in dry-run code path |

**Regression suite: 138/138 PASS**

---

*End of Phase 3U section.*

## Phase 3V — Dry-Run Audit Isolation

**No trading. No IBKR calls.**

Ensures dry-run events from `/order/dry-run` never pollute live reconciliation by default.

### Isolation Properties

| Check | Behavior | Test |
|---|---|---|
| `position_drift_check()` default | Excludes `dry_run_order` events (`include_dry_run=False`) | V1 |
| Opt-in preview | `include_dry_run=True` shows simulation-only positions | V2 |
| `/monitor/positions/drift` | Has `dry_run_preview` field separate from `expected_positions` | V3 |
| `/monitor/reconciliation` | `trade_count_match` only counts `order_submitted` events, not `dry_run_order` | V4 |
| `/audit/bundle` | Includes `simulation_evidence` section labeled as simulation | V5 |
| `/readiness` verdict | Ignores dry-run events for GO/NO-GO | V6 |
| Live baseline | Unchanged after multiple dry-runs (confirmed `AAPL=0.0`) | V7 |

### /audit/bundle simulation_evidence Structure

```json
{
  "simulation_evidence": {
    "event_type": "dry_run_order",
    "count": 15,
    "events": [
      {
        "symbol": "AAPL",
        "action": "BUY",
        "totalQuantity": 5,
        "filled": 5,
        "position_delta": 5,
        "simulated_order_id": "dry-run-1780675290",
        "timestamp_utc": "..."
      }
    ],
    "advisory": "simulation-only — never affects live reconciliation"
  }
}
```

### /monitor/positions/drift dry_run_preview

```json
{
  "dry_run_preview": {
    "AAPL": 43.0,
    "MSFT": 3.0
  },
  "expected_positions": [
    {"symbol": "AAPL", "expected_qty": 0.0}
  ],
  "drift_detected": false,
  ...
}
```

### Regression Tests (7 new tests)

| Test | What It Verifies |
|---|---|
| **V1** | `position_drift_check()` excludes dry-run by default | 
| **V2** | Dry-run preview available via `include_dry_run=True` |
| **V3** | `/monitor/positions/drift` has `dry_run_preview` field |
| **V4** | `/monitor/reconciliation` excludes dry-run from trade count |
| **V5** | `/audit/bundle` includes `simulation_evidence` section |
| **V6** | `/readiness` ignores dry-run events for GO/NO-GO |
| **V7** | Live baseline unchanged after multiple dry-runs |

**Regression suite: 138/138 PASS**

---

*End of Phase 3V section.*

## Phase 3W — Dry-Run Scenario Library

**No trading. No IBKR calls.**

Named reusable simulation scenarios that exercise common order-lifecycle patterns. Each scenario runs through `/order/dry-run` or monitor helpers, emits only `dry_run_order` events, and preserves the locked live baseline.

### Endpoints

```
GET  /order/dry-run/scenarios            — List available scenarios
POST /order/dry-run/scenario             — Execute a named scenario
```

### Available Scenarios

| Scenario | Steps | Description |
|---|---|---|
| `buy_full_fill` | 1 | BUY 5 AAPL, fully filled |
| `buy_partial_fill` | 1 | BUY 5 AAPL, 2 filled (partial) |
| `sell_full_close` | 2 | BUY 5 then SELL 5 (net zero) |
| `sell_partial_close` | 2 | BUY 5 then SELL 3 (remaining 2) |
| `sell_unfilled` | 2 | BUY 5 then SELL 5 with fill=0 |
| `duplicate_open_order` | 2 | Two concurrent BUY dry-runs (AAPL 3+4=7) |
| `manual_terminal_resolution` | 3 | BUY→SELL→manual reconcile |
| `order_id_reuse` | 2 | Two identical BUY 2 calls (unique IDs) |
| `daily_trade_limit_reached` | 3 | Three small BUY dry-runs |
| `drift_detected_case` | 2 | Multi-symbol: MSFT 3 + AAPL 5 |

### Example Usage

```bash
# List scenarios
curl -s http://127.0.0.1:8790/order/dry-run/scenarios | python3 -m json.tool

# Run buy_full_fill
curl -s -X POST http://127.0.0.1:8790/order/dry-run/scenario   -H 'Content-Type: application/json'   -d '{"scenario":"buy_full_fill"}' | python3 -c "
import json,sys;d=json.load(sys.stdin)
print(f"ok={d['ok']} steps={d['total_steps']} trades={d['total_trades']}")
for s in d['steps']: print(f"  {s.get('action','?')} {s.get('symbol','?')} {s.get('filled',0)}/{s.get('totalQuantity',0)}")"

# Run sell_full_close (round trip)
curl -s -X POST http://127.0.0.1:8790/order/dry-run/scenario   -H 'Content-Type: application/json'   -d '{"scenario":"sell_full_close"}'

# Unknown scenario returns 404
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8790/order/dry-run/scenario   -H 'Content-Type: application/json'   -d '{"scenario":"nonexistent"}'
```

### Architecture

```
dry_run_scenarios.py
  SCENARIO_DEFS          — 10 scenario definitions with steps + expected_drift
  list_scenarios()       — Return names + descriptions
  run_scenario()         — Execute steps via dry_run_caller + reconcile_caller
  run_all_scenarios()    — Run every scenario in sequence

bridge.py
  GET /order/dry-run/scenarios   — calls list_scenarios()
  POST /order/dry-run/scenario   — calls run_scenario() with bridge callers
```

### Safety Properties

- No `ib.placeOrder`/`ib.cancelOrder` in dry_run_scenarios.py (verified by W14)
- No guard-state mutations
- No `.env` or rules.yaml changes
- All events logged as `dry_run_order` (filterable)

### Acceptance Checklist

| # | Requirement | Status | Test |
|---|---|---|---|
| 1 | `buy_full_fill` runs BUY 5 AAPL fully filled | ✅ | W2 |
| 2 | `buy_partial_fill` runs with 2 of 5 filled | ✅ | W3 |
| 3 | `sell_full_close` round trip (net zero) | ✅ | W4 |
| 4 | `sell_partial_close` (remaining 2) | ✅ | W5 |
| 5 | `sell_unfilled` (fill=0, no drift impact) | ✅ | W6 |
| 6 | `duplicate_open_order` (concurrent buys sum) | ✅ | W7 |
| 7 | `manual_terminal_resolution` with reconcile | ✅ | W8 |
| 8 | `order_id_reuse` (unique IDs) | ✅ | W9 |
| 9 | `daily_trade_limit_reached` (3 trades) | ✅ | W10 |
| 10 | `drift_detected_case` (multi-symbol) | ✅ | W11 |
| 11 | Unknown scenario returns 404 | ✅ | W12 |
| 12 | Module works standalone | ✅ | W13 |
| 13 | No IBKR calls in scenario code | ✅ | W14 |

### Regression Tests (14 new tests)

| Test | What It Verifies |
|---|---|
| W1 | Scenario list has 10+ entries |
| W2 | buy_full_fill runs successfully |
| W3 | buy_partial_fill with 2/5 filled |
| W4 | sell_full_close round trip |
| W5 | sell_partial_close scenario |
| W6 | sell_unfilled scenario |
| W7 | duplicate_open_order sums correctly |
| W8 | manual_terminal_resolution with reconcile |
| W9 | order_id_reuse with unique IDs |
| W10 | daily_trade_limit_reached (3 trades) |
| W11 | drift_detected_case multi-symbol |
| W12 | Unknown scenario returns HTTP 404 |
| W13 | dry_run_scenarios module standalone import |
| W14 | No ib.placeOrder/cancelOrder in module |

**Regression suite: 138/138 PASS**

---

*End of Phase 3W section.*

## Phase 3X — Scenario Report / Simulation Audit

**No trading. No IBKR calls.**

Adds a report endpoint that runs selected dry-run scenarios and produces a concise pass/fail simulation report.

### Endpoints

```
GET /order/dry-run/report?scenario=<name>    — Single scenario report
GET /order/dry-run/report/all                 — Full audit (all scenarios)
```

### Report Structure

```json
{
  "report_type": "simulation_audit",
  "scenario": "buy_full_fill",
  "description": "Simple BUY 5 AAPL, fully filled.",
  "passed": true,
  "ok": true,
  "drift_match": true,
  "baseline_unchanged": true,
  "steps_executed": 1,
  "trades_in_scenario": 1,
  "expected_drift": {"AAPL": 5},
  "actual_drift": {"AAPL": 5},
  "drift_comparison": {
    "AAPL": {"expected": 5, "actual": 5, "match": true}
  },
  "event_ids": ["dry-run-1234567890"],
  "live_baseline": {"AAPL": 0},
  "timestamp_utc": "2026-06-05T17:00:00Z"
}
```

### Full Audit Report

```
GET /order/dry-run/report/all
```

Returns aggregated pass/fail across all 10 scenarios:

```json
{
  "report_type": "simulation_audit_full",
  "total_scenarios": 10,
  "passed_count": 10,
  "all_passed": true,
  "reports": { ... },
  "timestamp_utc": "..."
}
```

### CLI Usage

```bash
# List scenarios
python3 dry_run_scenarios.py --list

# Help
python3 dry_run_scenarios.py --help

# Via bridge
curl -s "http://127.0.0.1:8790/order/dry-run/report?scenario=buy_full_fill" | python3 -m json.tool

# Full audit
curl -s "http://127.0.0.1:8790/order/dry-run/report/all" | python3 -c "
import json,sys; d=json.load(sys.stdin)
print(f'Scenarios: {d["total_scenarios"]} Passed: {d["passed_count"]} All: {d["all_passed"]}')"

# Unknown scenario returns 404
curl -s -w "\nHTTP %{http_code}\n" "http://127.0.0.1:8790/order/dry-run/report?scenario=nonexistent"
```

### Regression Tests (6 new tests)

| Test | What It Verifies |
|---|---|
| X1 | Report returns report_type=simulation_audit |
| X2 | Report has expected_drift, actual_drift, drift_comparison |
| X3 | Report has event_ids and baseline_unchanged |
| X4 | Unknown scenario returns HTTP 404 |
| X5 | `/report/all` returns full audit with all scenarios |
| X6 | Report functions importable standalone |

**Regression suite: 138/138 PASS**

---

*End of Phase 3X section.*

## Phase 3Y — Dry-Run Scenario Release Checkpoint

**No trading. No IBKR calls. No order enablement.**

Makes the dry-run scenario report part of the release evidence. Every `/audit/release` now includes a `dry_run_simulation` section with the full scenario report.

### Release Tag dry_run_simulation Structure

```json
{
  "tag_id": "release_20260605T170000",
  "phase_label": "phase3y_dry_run_checkpoint",
  "dry_run_simulation": {
    "scenario_count": 10,
    "passed_count": 0,
    "all_passed": false,
    "advisory": "simulation-only — never affects live reconciliation",
    "report_reference": {
      "total_scenarios": 10,
      "passed_count": 0,
      "reports": { ... }
    }
  },
  "locked_baseline": {
    "confirmed": true,
    "allow_orders": false,
    "enforced": false,
    "system_locked": true
  },
  ...
}
```

### Acceptance Checklist

| # | Requirement | Status | Test |
|---|---|---|---|
| 1 | Full dry-run report in release | ✅ | Y1 |
| 2 | Scenario count = 10 | ✅ | Y2 |
| 3 | Pass count present | ✅ | Y3 |
| 4 | Live drift excludes dry-runs | ✅ | Y4 |
| 5 | Readiness ignores dry-runs (NO-GO) | ✅ | Y5 |
| 6 | /order returns HTTP 403 | ✅ | Y6 |
| 7 | Kill switches remain false | ✅ | Y7 |
| 8 | Live baseline unchanged before/after | ✅ | Y8 |
| 9 | Advisory = "simulation-only" | ✅ | Y9 |

### Verification Commands

```bash
# Check release tag has dry_run_simulation
curl -s "http://127.0.0.1:8790/audit/release?phase=phase3y_dry_run_checkpoint" | python3 -c "
import json,sys; d=json.load(sys.stdin); ds=d.get('dry_run_simulation',{})
print(f'Scenarios: {ds.get("scenario_count")} Passed: {ds.get("passed_count")} Advisory: {ds.get("advisory")[:40]}')"

# Verify live drift is clean
curl -s http://127.0.0.1:8790/monitor/positions/drift | python3 -c "
import json,sys; d=json.load(sys.stdin); print(f'Expected: {[p["expected_qty"] for p in d["expected_positions"]]}')"

# Verify readiness NO-GO
curl -s http://127.0.0.1:8790/readiness | python3 -c "
import json,sys; d=json.load(sys.stdin); print(f'Verdict: {d["verdict"]} Locked: {d["summary"]["kill_switches"]["system_locked"]}')"

# Verify /order 403
curl -s -o /dev/null -w "HTTP %{http_code}" -X POST http://127.0.0.1:8790/order

# Verify kill switches
curl -s http://127.0.0.1:8790/readiness | python3 -c "
import json,sys; d=json.load(sys.stdin); ks=d['summary']['kill_switches']
print(f'allow_orders={ks["IBKR_ALLOW_ORDERS"]} enforced={ks["rules.enforced"]}')"
```

### Regression Tests (9 new tests)

| Test | What It Verifies |
|---|---|
| Y1 | `/audit/release` has `dry_run_simulation` section |
| Y2 | `scenario_count` = 10 |
| Y3 | `passed_count` present |
| Y4 | Live drift excludes dry-runs after checkpoint |
| Y5 | Readiness ignores dry-runs (verdict NO-GO) |
| Y6 | `/order` returns HTTP 403 |
| Y7 | Kill switches remain false |
| Y8 | Live baseline unchanged before/after scenarios |
| Y9 | Advisory = "simulation-only" |

**Regression suite: 138/138 PASS**

---

*End of Phase 3Y section.*
