# ibkr-operator — Runbook

Read-only operator workflow for IBKR stocks/ETF bridge monitoring.
All commands are **read-only by default**. Explicit flags enable pruning.

---

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
ibkr-operator export --verify /path/to/file    # verify specific file
ibkr-operator export --verify latest --json
```

### `ibkr-operator doctor`
Operator self-test / environment diagnostics (read-only).
```bash
ibkr-operator doctor
ibkr-operator doctor --json
```

### `ibkr-operator hermes-proposal`
Generate a Hermes-advised trade proposal (advisory only).
```bash
ibkr-operator hermes-proposal --canary          # test Hermes invocation
ibkr-operator hermes-proposal                    # default: AAPL BUY 1
ibkr-operator hermes-proposal --symbol SPY --side BUY --qty 1
ibkr-operator hermes-proposal --json             # raw JSON output
ibkr-operator hermes-proposal --output proposal.json
```

### `ibkr-operator freeze`
Release freeze / full CLI evidence snapshot (read-only). Runs all subcommands
internally and bundles results.
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
ibkr-operator maintenance --dry-run --prune-audit --keep-audit 20
ibkr-operator maintenance --dry-run --prune-releases --keep-releases 20
ibkr-operator maintenance --dry-run --prune-exports --keep-exports 20

# Execute pruning:
ibkr-operator maintenance --prune-audit --keep-audit 20
ibkr-operator maintenance --prune-releases --keep-releases 20
ibkr-operator maintenance --prune-exports --keep-exports 20
```

---

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

### Maintenance — review retention
```bash
ibkr-operator maintenance
```

### Maintenance — prune old exports
```bash
ibkr-operator maintenance --dry-run --prune-exports --keep-exports 20
ibkr-operator maintenance --prune-exports --keep-exports 20
```

---

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

---

## Safety

| Invariant | Enforced by |
|-----------|-------------|
| **Default read-only** | All commands default to read-only display |
| **No broker mutation** | AST safety check — no `placeOrder`, `cancelOrder`, `/order` |
| **No guard mutation** | AST safety check — no `save_guard_state_atomic`, `initialize_guard_state`, `append_guard_event` |
| **No accidental deletion** | `--dry-run` always available; pruning requires explicit flags |
| **Pruning is opt-in** | Must pass `--prune-audit`, `--prune-releases`, or `--prune-exports` |
| **Protected files never touch** | Safety gate blocks guard-state.json, guard-events.jsonl, etc. |
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

---

## Hermes Advisory Guard (Phase 5B.0) & Invocation Adapter (Phase 5B.1)

Policy: `~/.openclaw/memory/hermes-advisory-guard-policy.md`

Hermes is **advisory-only**. It may:
- Analyze markets, rank candidates, produce trade theses, calculate risk
- Generate proposal drafts using the mandatory 14-field template
- Write post-trade learning notes **only if explicitly requested by Chris**

Hermes must **never**:
- Enable, submit, or approve orders
- Call IBKR directly, `/order`, `/order/submit`, or `/order/approve`
- Edit `.env`, rules YAML, guard-state, or approval files
- Bypass Werner, ibkr-operator, or bridge/guard

Minimum risk rails (Phase 5 pilot):
- Max position: 5% Net Liq | Max exposure: 25% Net Liq | Max risk/trade: 0.25%
- Max 2 trades/day, 5/week
- No trade without stop, if drift detected, open order, or live alert
- Daily loss ≥ 1% or weekly ≥ 3% Net Liq = NO TRADE

Every proposal requires Chris approval. Advisory only — no order enabled or submitted.

### Pruning commands (require explicit flags)
- `ibkr-operator maintenance --prune-audit --keep-audit N`
- `ibkr-operator maintenance --prune-releases --keep-releases N`
- `ibkr-operator maintenance --prune-exports --keep-exports N`