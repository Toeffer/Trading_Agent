# KPI / Evidence Dashboard

> **Status:** Chris-approved governance document.  
> **Scope:** Read-only observability dashboard for operational readiness and autonomy evidence.  
> **Last updated:** 2026-06-15

---

## 1. Overview

The KPI dashboard (`ibkr-operator kpi`) is a **read-only** command that summarizes the full operational state of the IBKR bridge system. It produces a **GO / HOLD / NO-GO** verdict for the next autonomous cycle based on safety flags, bridge health, monitoring state, autonomy evidence, and doctor checks.

**The dashboard never:**
- Executes, submits, or approves orders
- Mutates broker state
- Reads or uses the H1 token
- Calls `/order` or any `/order/*` endpoint
- Opens the trade window

---

## 2. Running the Dashboard

### Basic usage

```bash
ibkr-operator kpi
```

### JSON output (for scripts/automation)

```bash
ibkr-operator kpi --json
```

### Export to file

```bash
ibkr-operator kpi --json --export
```

Exports are written to `~/.openclaw/exports/kpi-dashboard-<timestamp>.json`.

---

## 3. Dashboard Sections

### 3.1 Bridge Health
- **Reachable:** Whether the bridge HTTP API responded
- **Connected:** IBKR Gateway connection state
- **Mode:** `paper` (read-only) or `live`
- **Read-only:** Confirms paper mode
- **Positions:** Current position count
- **Net Liquidation:** Account net liquidation value (EUR)
- **Endpoints:** How many of the 8 monitored endpoints responded

### 3.2 Safety Flags
- **Bridge `allow_orders`:** Must be `false`
- **`.env` `IBKR_ALLOW_ORDERS`:** Must be `false`
- **`rules.enforced`:** Must be `false`
- **System locked:** RTH/readiness lock state

### 3.3 Monitoring
- **Reconciliation:** Passed/Failed from `/monitor/reconciliation`
- **Active Alerts:** Count of live alerts from `/monitor/alerts`

### 3.4 Latest Events
Last 3 guard events (preflight_pass/fail, etc.) from `/monitor/events`.

### 3.5 Autonomy
- **Current Level:** From `docs/AUTONOMY_CRITERIA.md`
- **Clean Cycles:** Count of completed clean autonomous cycles

### 3.6 Heartbeat
Age of the most recent heartbeat artifact in `~/.openclaw/heartbeat/`.

### 3.7 Doctor
Non-canary doctor checks (does NOT run the full doctor; use `ibkr-operator doctor` separately).

### 3.8 Blocker List
All issues preventing GO, with severity (`NO-GO` / `HOLD`).

---

## 4. Verdict Rules

### GO
All of:
- Bridge reachable and healthy
- All safety flags correct (`IBKR_ALLOW_ORDERS=false`, `rules.enforced=false`)
- IBKR Gateway connected
- Zero active alerts
- Reconciliation passed
- Doctor non-canary checks all pass
- At least one clean autonomous cycle logged
- Heartbeat artifact present and recent (<24h)
- Autonomy level ≥ 1
- System not locked

### HOLD (default)
Any of:
- Autonomy at level 0 (manual approval required)
- Zero clean cycles logged (insufficient evidence)
- Heartbeat artifact missing or stale (>24h)
- IBKR Gateway disconnected
- System locked (RTH closed, etc.)
- Any other evidence gap

**HOLD is the default state.** The system errs on the side of caution.

### NO-GO
Any of:
- Bridge unreachable (can't verify safety)
- `IBKR_ALLOW_ORDERS=true` anywhere (env, bridge, rules)
- `rules.enforced=true`
- Active live alerts present
- Reconciliation failed
- Doctor non-canary checks failed

NO-GO takes priority over HOLD. If any NO-GO condition exists, the verdict is NO-GO regardless of HOLD conditions.

---

## 5. Blocker Severity

| Severity | Meaning | Action |
|---|---|---|
| **NO-GO** | Hard safety violation | Must be resolved before any cycle |
| **HOLD** | Evidence/readiness gap | May be overridden by Chris with written justification |

---

## 6. Data Sources

| Source | Method | What It Provides |
|---|---|---|
| `GET /health` | HTTP | Bridge mode, connection, startup_safety |
| `GET /readiness` | HTTP | Kill switches, system lock |
| `GET /status` | HTTP | Aggregated bridge status |
| `GET /monitor/reconciliation` | HTTP | Reconciliation pass/fail |
| `GET /monitor/alerts` | HTTP | Live alert count |
| `GET /monitor/events` | HTTP | Latest guard events |
| `GET /positions` | HTTP | Position count |
| `GET /account` | HTTP | Net liquidation |
| `.env` | File read | `IBKR_ALLOW_ORDERS` |
| `paper-trading-rules.yaml` | File read | `rules.enforced` |
| `docs/AUTONOMY_CRITERIA.md` | File read | Autonomy level |
| `~/.openclaw/trade-journal/` | File glob | Clean cycle count |
| `~/.openclaw/heartbeat/` | File glob | Heartbeat age |
| `git` | Subprocess | Branch, commit, tag |

---

## 7. Safety Invariants

The KPI dashboard code enforces:
1. **No forbidden endpoints:** `/connect`, `/order`, `/order/preflight`, `/order/approve`, `/order/submit` are banned from the endpoint list
2. **No broker mutation:** AST-level check that KPI functions never call `placeOrder`, `cancelOrder`, `_internal_place_order`, guard mutation functions
3. **No H1 token:** KPI functions never import, read, or reference the H1 token
4. **Default HOLD:** The verdict defaults to HOLD, not GO
5. **Read-only:** All data gathering is GET requests and file reads only

---

## 8. Integration with CI

KPI tests run as part of `scripts/run-ci-local`:
```bash
python -m pytest tests/test_kpi_dashboard.py -v
```

They are not marked `integration` or `live` — they run in the default CI suite.
