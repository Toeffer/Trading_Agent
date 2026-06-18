# RUNBOOK — OpenClaw / Werner / IBKR Bridge

Operator workflow for the IBKR stocks/ETF bridge. **Read-only by default**; explicit flags
enable pruning. Safety invariants and current state live in `CLAUDE.md`; history lives in
`CHANGELOG.md`.

This runbook has two layers:
- **Part 1 — `ibkr-operator` CLI:** the primary, day-to-day interface. Use this first.
- **Part 2 — Low-level / break-glass:** direct bridge `curl`, Gateway/VNC lifecycle, git,
  MCP, and the Chris-only enable sequence. Use when the CLI is unavailable, when debugging
  a specific endpoint, or for host/Gateway operations the CLI does not cover.

Default bridge base URL: `http://127.0.0.1:8790`.

---

# PART 1 — `ibkr-operator` CLI

## Commands

### `ibkr-operator checklist`
Run the daily checklist (auto-detects state).
```bash
ibkr-operator checklist
ibkr-operator checklist --json
ibkr-operator checklist --explain
ibkr-operator checklist start-of-day    # explicit state
```

### `ibkr-operator daily-report`
Consolidated daily snapshot.
```bash
ibkr-operator daily-report
ibkr-operator daily-report --json
```

### `ibkr-operator export`
Create read-only evidence export.
```bash
ibkr-operator export
ibkr-operator export --json
ibkr-operator export --save                     # write to ~/.openclaw/exports/
ibkr-operator export --verify latest            # verify latest export
ibkr-operator export --verify /path/to/file     # verify specific file
ibkr-operator export --verify latest --json
```

### `ibkr-operator kpi`
KPI / evidence dashboard with GO/HOLD/NO-GO verdict.
```bash
ibkr-operator kpi
ibkr-operator kpi --json
ibkr-operator kpi --json --export     # writes to ~/.openclaw/exports/
```

### `ibkr-operator doctor`
Operator self-test / environment diagnostics (read-only).
```bash
ibkr-operator doctor
ibkr-operator doctor --json
```

### `ibkr-operator hermes-proposal`
Generate a Hermes-advised trade proposal (advisory only — see Part 1 § Hermes).
```bash
ibkr-operator hermes-proposal --canary          # test Hermes invocation
ibkr-operator hermes-proposal                    # default: AAPL BUY 1
ibkr-operator hermes-proposal --symbol NVDA --side BUY --qty 1   # allowlist: AAPL/META/NVDA/AMD
ibkr-operator hermes-proposal --json             # raw JSON output
ibkr-operator hermes-proposal --output proposal.json
```
> Note (2026-06-09): the upstream example used `--symbol SPY`, but SPY was removed from the
> allowlist (KID/PRIIPs). Use a current allowlist symbol. If the CLI's own `--help` still
> prints SPY, that help text is stale — fix it where the string lives.

### `ibkr-operator freeze`
Release freeze / full CLI evidence snapshot (read-only). Runs all subcommands internally
and bundles results.
```bash
ibkr-operator freeze
ibkr-operator freeze --json
```

### `ibkr-operator maintenance`
Inspect and prune artifacts.
```bash
ibkr-operator maintenance                       # read-only report
ibkr-operator maintenance --json

# Dry-run (no deletion):
ibkr-operator maintenance --dry-run --prune-audit    --keep-audit 20
ibkr-operator maintenance --dry-run --prune-releases --keep-releases 20
ibkr-operator maintenance --dry-run --prune-exports  --keep-exports 20

# Execute pruning:
ibkr-operator maintenance --prune-audit    --keep-audit 20
ibkr-operator maintenance --prune-releases --keep-releases 20
ibkr-operator maintenance --prune-exports  --keep-exports 20
```

## Common Workflows

### Daily start (pre-market or RTH open)
```bash
ibkr-operator doctor
ibkr-operator daily-report
```

### Weekend check
```bash
ibkr-operator checklist        # shows "weekend" state, safe to ignore
ibkr-operator daily-report     # shows NO-OP verdict
```

### After trades — evidence capture
```bash
ibkr-operator export --save
ibkr-operator export --verify latest
```

### Stop-breach response (Phase 6A)
When a position breaches its recorded stop or -5% floor:
1. Werner runs Phase 6A review: confirm breach → reconstruct thesis → Hermes
   adversarial review → recommendation (EXIT default).
2. Hermes invoked via Codex CLI / GPT-5.5 (NOT sessions_spawn subagent).
3. If EXIT recommended: Chris unlocks → preflight SELL (Gate G close-only) →
   Chris H1 approve/submit → verify fill → relock.
4. Journal entry: `~/.openclaw/memory/trade-journal/SYMBOL-DATE.md`
5. HOLD requires Chris written STOP_OVERRIDE_REQUESTED.

### Maintenance — review retention
```bash
ibkr-operator maintenance
```

### Maintenance — prune old exports
```bash
ibkr-operator maintenance --dry-run --prune-exports --keep-exports 20
ibkr-operator maintenance --prune-exports --keep-exports 20
```

## Tag Timeline

| Tag | Phase | Description |
|-----|-------|-------------|
| `phase3h_audit_bundle` | 3H | Immutable audit bundle creation |
| `phase3i_audit_verify` | 3I | Audit bundle verification |
| `phase3j_release_tag` | 3J | Release tagging / provenance |
| `phase4b_operator_checklist` | 4B | Operator daily checklist CLI |
| `phase4c_checklist_release_evidence` | 4C | Checklist evidence in release metadata |
| `phase4d_maintenance_prune` | 4D | Audit/release maintenance & pruning |
| `phase4e_resource_guard` | 4E | Resource health monitoring |
| `phase4f_daily_report` | 4F | Consolidated daily report |
| `phase4g_daily_report_evidence` | 4G | Daily report snapshot in audit bundle |
| `phase4h_operator_export` | 4H | Operator evidence export |
| `phase4i_export_retention_verify` | 4I | Export retention & verify |
| `phase4j_help_runbook` | 4J | Help output & runbook |
| `phase4k_doctor_command` | 4K | Operator self-test / doctor command |
| `phase4l_operator_release_freeze` | 4L | Release freeze / full CLI evidence snapshot |

> The bridge-side phases (`3K`–`3Y`: restore drill, DR runbook, reconnect validation,
> status dashboard/hardening/CLI, model-routing policy, dry-run harness/isolation/scenarios/
> report/checkpoint) ran on `bridge.py`/`guard.py` and are logged in `CHANGELOG.md`, not here.
> This timeline tracks only the `ibkr-operator` CLI tool.

## Safety (CLI-level)

| Invariant | Enforced by |
|-----------|-------------|
| **Default read-only** | All commands default to read-only display |
| **No broker mutation** | AST safety check — no `placeOrder`, `cancelOrder`, `/order` |
| **No guard mutation** | AST safety check — no `save_guard_state_atomic`, `initialize_guard_state`, `append_guard_event` |
| **No accidental deletion** | `--dry-run` always available; pruning requires explicit flags |
| **Pruning is opt-in** | Must pass `--prune-audit`, `--prune-releases`, or `--prune-exports` |
| **Protected files never touched** | Safety gate blocks `guard-state.json`, `guard-events.jsonl`, etc. |
| **Secrets never exported** | Export redacts raw guard events, logs, and forbidden strings |

### Read-only commands (always safe)
- `ibkr-operator checklist`
- `ibkr-operator daily-report`
- `ibkr-operator doctor`
- `ibkr-operator hermes-proposal`
- `ibkr-operator export`
- `ibkr-operator freeze`
- `ibkr-operator maintenance` (no flags)
- `ibkr-operator maintenance --dry-run`

### Pruning commands (require explicit flags)
- `ibkr-operator maintenance --prune-audit --keep-audit N`
- `ibkr-operator maintenance --prune-releases --keep-releases N`
- `ibkr-operator maintenance --prune-exports --keep-exports N`

## OOM Recovery — ibkr-bridge.service

**Symptom:** `systemctl status ibkr-bridge` shows `code=killed, status=9/KILL`
or `Failed with result 'oom-kill'`.

**Root cause:** Memory spike from uvicorn worker respawns exceeded `MemoryMax`.

**Current envelope (2026-06-17):**
```ini
MemoryMax=2500M          # raised from 2000M; host has ~6GB available
MemorySwapMax=0          # never swap — fail-closed
OOMPolicy=stop           # stop the unit, don't restart-loop
# No MemoryHigh          # throttling caused unresponsive-but-alive state
Restart=on-failure
RestartSec=30
```

**Procedure:**
```bash
sudo systemctl restart ibkr-bridge.service
sleep 10
# Verify
systemctl show ibkr-bridge.service -p MemoryCurrent -p Result -p ActiveState
ss -tlnp sport = :8790      # must show exactly one LISTEN on 127.0.0.1:8790
curl -s http://127.0.0.1:8790/health  # must return ok=true
cd ~/agents/ibkr-bridge
.venv/bin/python ibkr_operator.py doctor   # should PASS or PASS with H1 MANUAL only
.venv/bin/python ibkr_operator.py kpi      # should be HOLD when only disconnected
# If trade_count_mismatch alert persists after restart:
.venv/bin/python ibkr_operator.py kpi-repair --live
```

## Hermes Advisory Guard (Phase 5B.0) & Invocation Adapter (Phase 5B.1)

Policy: `~/.openclaw/memory/hermes-advisory-guard-policy.md`

Hermes is **advisory-only**. It may:
- Analyze markets, rank candidates, produce trade theses, calculate risk
- Generate proposal drafts using the mandatory 14-field template
- Write post-trade learning notes **only if explicitly requested by Chris**

**Invocation:** Hermes MUST be invoked via its configured Codex CLI path with
GPT-5.5 model. Do NOT use `sessions_spawn` (inherits Werner's model — wrong
model for Hermes analysis). See Phase 6A CHANGELOG entry.

Hermes must **never**:
- Enable, submit, or approve orders
- Call IBKR directly, `/order`, `/order/submit`, or `/order/approve`
- Edit `.env`, rules YAML, guard-state, or approval files
- Bypass Werner, `ibkr-operator`, or the bridge/guard

**Minimum risk rails (Phase 5 pilot — advisory envelope for Hermes proposals):**
- Max position: 5% Net Liq | Max exposure: 25% Net Liq | Max risk/trade: 0.25%
- Max 2 trades/day, 5/week
- No trade without a stop; no trade if drift detected, an open order exists, or a live alert is active
- Daily loss ≥ 1% or weekly ≥ 3% Net Liq = NO TRADE

Every proposal requires Chris approval. Advisory only — no order enabled or submitted.

> ⚠️ **Rails reconciliation (open — see `CHANGELOG.md` Verification Queue):** these pilot
> numbers (0.25% risk/trade, 25% exposure, 5 trades/week) are **tighter** than the guard's
> v1.3-draft caps in `CLAUDE.md §5` (2% risk, 30% exposure, no weekly trade cap). The loss
> halts match (−1% day / −3% week). Most likely these are an advisory overlay (Hermes
> proposes inside a tighter envelope than `guard.py` would permit), but confirm against
> `paper-trading-rules.yaml` + `guard.py` whether the YAML was also tightened.

---

# PART 2 — Low-level / break-glass (direct bridge & host)

Most of these are wrapped by `ibkr-operator` (`doctor`, `daily-report`, `export`, `freeze`).
Use the raw calls for debugging a specific endpoint, or when the CLI is unavailable.

## §L0. Session start
```bash
ibkr-status          # health + readiness + git + audit + release + monitoring + Model Policy
```
Confirm the Model Policy section shows a **Tier 1** model before any safety-critical edit.

## §L1. Direct bridge read path
```bash
curl -s http://127.0.0.1:8790/health    | python3 -m json.tool
curl -s -X POST http://127.0.0.1:8790/connect | python3 -m json.tool
curl -s http://127.0.0.1:8790/positions | python3 -m json.tool
curl -s http://127.0.0.1:8790/account   | python3 -m json.tool
curl -s http://127.0.0.1:8790/account/summary | python3 -m json.tool   # if present
```

## §L2. Market data (not wrapped by the CLI)
```bash
# Quote (delayed)
curl -s -X POST http://127.0.0.1:8790/market/quote \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"AAPL","exchange":"SMART","currency":"USD","delayed":true}' \
  | python3 -m json.tool

# Bars
curl -s -X POST http://127.0.0.1:8790/market/bars \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"AAPL","exchange":"SMART","currency":"USD","duration":"30 D","bar_size":"1 day","what_to_show":"TRADES","use_rth":true}' \
  | python3 -m json.tool | head -n 120
```

## §L3. Order safety check
```bash
curl -s -X POST http://127.0.0.1:8790/order | python3 -m json.tool
```
Expected (always, by design):
```json
{ "detail": "orders disabled: setup/read-only mode" }
```

## §L4. Raw monitoring / readiness / audit one-liners
```bash
# Monitoring (Phase 2F)
curl -s http://127.0.0.1:8790/monitor/health         | python3 -m json.tool
curl -s http://127.0.0.1:8790/monitor/reconciliation | python3 -m json.tool
curl -s 'http://127.0.0.1:8790/monitor/events?type=order_submitted' | python3 -m json.tool
curl -s http://127.0.0.1:8790/monitor/alerts         | python3 -m json.tool
curl -s http://127.0.0.1:8790/monitor/positions/drift | python3 -m json.tool

# Readiness (Phase 3E) — GO/NO-GO verdict
curl -s http://127.0.0.1:8790/readiness | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Verdict: {d[\"verdict\"]}'); [print(f'  {b[\"check\"]}: {b[\"detail\"]}') for b in (d.get(\"blocks\") or [])]"

# Audit bundle / verify / release (Phases 3H–3K)
curl -s http://127.0.0.1:8790/audit/bundle | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Bundle: {d[\"bundle_id\"]} files={len(d[\"files\"])} eps={len(d[\"endpoints\"])} hashes={len(d[\"code_hashes\"])}')"
curl -s http://127.0.0.1:8790/audit/verify | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Verify: {d[\"passed_count\"]}/{d[\"check_count\"]} pass={d[\"pass\"]}')"
curl -s http://127.0.0.1:8790/audit/release/latest | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Latest: {d[\"tag_id\"]} ({d[\"phase_label\"]})')"

# Offline audit CLI (no bridge needed)
cd ~/agents/ibkr-bridge && .venv/bin/python3 bundle_audit.py --list
```

## §L5. Git provenance
```bash
cd ~/agents/ibkr-bridge
git log --oneline --decorate=tags -5
git tag -l
```

## §L6. OpenClaw MCP
```bash
openclaw mcp list
openclaw mcp show ibkr-stocks
systemctl --user restart openclaw-gateway.service
```
Registered server:
```json
{ "ibkr-stocks": {
    "command": "/home/chris/agents/ibkr-bridge/.venv/bin/python",
    "args": ["/home/chris/agents/ibkr-bridge/ibkr_mcp_server.py"] } }
```

## §L7. IBKR Gateway / VNC lifecycle
```bash
ss -ltnp | grep ':4002'                 # is the API port open?

# VNC / display
pkill x11vnc || true
export DISPLAY=:1
pgrep -a Xvfb    || Xvfb :1 -screen 0 1280x900x24 &
pgrep -a openbox || openbox &
x11vnc -display :1 -localhost -forever -nopw -rfbport 5900 -bg

# IB Gateway
export DISPLAY=:1
~/Jts/ibgateway/*/ibgateway &
```
IB Gateway is not a permanently authenticated daemon; if it needs login/2FA, complete it
manually, then reconnect the bridge (§L1).

## §L8. Order-enable sequence — CHRIS ONLY
> Werner never performs these steps and never requests them — it may only walk Chris
> through them. Both switches must be set; either alone keeps `/order/submit` =
> `ORDERS_BLOCKED`. Roll both back after the cycle.

**Step 0 — H1 token canary (mandatory).** Before touching any switches, verify
the H1 approval token is valid:

```
ibkr-operator doctor          # shows h1_token_canary check
# or run manually:
sudo ibkr-trade-window approve aprv_canary
```

Expected result: `Approval 'aprv_canary' not found, expired, or already ruled.`
Any `H1_TOKEN_REQUIRED`, HTTP 401, token error, or unexpected output is **NO-GO**.
Do not proceed if the canary fails.

1. Set `IBKR_ALLOW_ORDERS=true` in `.env`.
2. Set `enforced=true` in `paper-trading-rules.yaml`.
3. Restart the bridge.
4. Run a fresh cycle: preflight → approve → submit.
5. Run monitor reconciliation (§L4) after execution.
6. Roll both switches back to `false`.

## §L9. Bridge restart safety
- All in-memory pending approvals → **invalid** (cannot be ruled on).
- All in-memory approved-but-unsubmitted approvals → **invalid** (cannot be submitted).
- The system **may** scan IBKR open orders on restart for visibility / manual reconciliation.
- The system **must not** auto-submit, auto-cancel, or auto-resume anything.
- If an uncertain submit occurred before the restart, reconcile manually via TWS/IB Gateway.
- A fresh preflight → fresh approval is always required after a restart.

## §L10. Disaster recovery (Phase 3M)
A 12-step operator checklist lives in the bridge repo's runbook; `phase3l` proved
clone + rebuild + restore. Start from `ibkr-status` (§L0) and the audit bundle (§L4) to
establish a known-good baseline, then follow the repo checklist.

## §L11. OOM Recovery (Step 15C)

### Pre-fix OOM history (2026-06-18)

The bridge was repeatedly OOM-killed during Step 15C development:

| Timestamp (UTC) | Root cause | Fix version |
|---|---|---|
| 07:39:08 | Endpoint storm (8 HTTP calls × concurrent gates) | v1 added snapshot cache |
| 09:35:33, 09:46:30, 10:01:31 | Snapshot called `reconcile_snapshot()` + `_check_liveness()` (subprocess forks) | v2 lightweight snapshot |
| 10:52:18 | `_check_liveness()` spawned `systemctl show` + `journalctl` (fork under memory pressure) | v3 zero-fork liveness |
| 12:34:58 | Same v2 fork issue; gates 2/3 failed because bridge was gone | v3 accepted |

All kills: `Main process exited, code=killed, status=9/KILL`, `Failed with result 'oom-kill'`.
MemoryMax was 2500M throughout — the issue was **load-shed** (endpoint storms, subprocess forks), not the memory ceiling.

### Detect OOM
```bash
# Check for recent OOM kills
ibkr-operator doctor                    # K17 no_recent_oom check
curl -s http://127.0.0.1:8790/monitor/liveness | jq .oom_evidence
journalctl -u ibkr-bridge.service --since "1 hour ago" | grep -i oom
```

### Memory envelope
- `MemoryMax=2500M` (set in `systemd/ibkr-bridge.service`)
- `MemorySwapMax=0` (no swap — fail-closed)
- `OOMPolicy=stop` (stop the unit, don't let kernel pick a random victim)
- Current peak: see `systemctl show ibkr-bridge.service -p MemoryPeak`

### If OOM occurs
1. Check `journalctl -k | grep -i oom` for kernel-level victim details.
2. Verify `MemoryMax` is adequate (host has ~6GB available; 2500M is a safe envelope).
3. Check for endpoint storms: concurrent KPI/rehearsal/candidate invocations each
   launch 8 HTTP calls. After Step 15C v3, the `/snapshot` endpoint consolidates these
   into a single cacheable call, and liveness uses zero-fork /proc reads.
4. Restricted from this session: `sudo systemctl restart ibkr-bridge.service`
5. Verify: `ibkr-operator doctor` and `curl http://127.0.0.1:8790/health`

## §L12. Snapshot / Load-Shed (Step 15C v3)

### Consolidated snapshot
Instead of calling 8 separate endpoints, use the single `/snapshot` endpoint:
```bash
curl -s http://127.0.0.1:8790/snapshot | jq .
```
Returns: health, RTH, safety flags, guard state, positions, account values,
reconciliation, and liveness in one response. Cached with 30s TTL.
Includes `_instrumentation` field: `cache_hit`, `build_ms`, `cache_age_seconds`, `in_flight_collapsed`.

### Fast-fail for disconnected IBKR
When IBKR Gateway is disconnected:
- `/positions` returns `{"ok": false, "detail": "IBKR not connected"}` (HTTP 200)
- `/account` returns same fast-fail format
- `/snapshot` includes `positions_ok: false` and `account_ok: false`
- No 503 blocking, no timeout accumulation

### Liveness monitoring (zero-fork)
```bash
curl -s http://127.0.0.1:8790/monitor/liveness | jq .
```
Reports: process RSS/VmPeak/VmSize from `/proc/self/status` (no subprocess forks).
Cached 60s. Zero `systemctl`/`journalctl` calls inside the bridge process.
For systemd-level OOM detection, use the K17 check in `_collect_lightweight_evidence()`
