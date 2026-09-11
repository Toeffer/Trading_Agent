"""Extracted operator helpers; historical behavior and command contracts retained."""
from __future__ import annotations

import hashlib

import json

import os

import sys

import time

import urllib.error

import urllib.request

from datetime import datetime, timezone

from pathlib import Path

from typing import Any

_FORBIDDEN_NAMES = frozenset({
    "save_guard_state_atomic", "initialize_guard_state",
    "append_guard_event",
    "create_approval_record", "run_preflight",
    "_internal_place_order",
    "placeOrder", "cancelOrder",
})

HOME = Path.home()

OPENCLAW_DIR = HOME / ".openclaw"

BRIDGE_DIR = HOME / "agents" / "ibkr-bridge"

BRIDGE_URL = os.environ.get("IBKR_BRIDGE_URL", "http://127.0.0.1:8790")

AUDIT_DIR = OPENCLAW_DIR / "audit-bundles"

RELEASE_DIR = OPENCLAW_DIR / "releases"

HEARTBEAT_DIR = OPENCLAW_DIR / "heartbeat"

TESTS_DIR = BRIDGE_DIR / "tests"

GREEN = "\033[92m"

YELLOW = "\033[93m"

RED = "\033[91m"

CYAN = "\033[96m"

BOLD = "\033[1m"

RESET = "\033[0m"

VALID_STATES = frozenset({
    "start-of-day", "sod", "baseline",
    "preflight-ready", "ready", "gates",
    "reconcile", "post-trade", "recon",
    "regression", "tests", "suite",
    "end-of-day", "eod", "lockdown",
})

STATE_ALIASES = {
    "sod": "start-of-day", "baseline": "start-of-day",
    "ready": "preflight-ready", "gates": "preflight-ready",
    "post-trade": "reconcile", "recon": "reconcile",
    "tests": "regression", "suite": "regression",
    "eod": "end-of-day", "lockdown": "end-of-day",
}

_EXPORT_DIR = OPENCLAW_DIR / "exports"

_EXPORT_MAX_BYTES = 256 * 1024  # 256KB cap for the full export file

_HEARTBEAT_ENDPOINTS = [
    "/health",
    "/readiness",
    "/monitor/health",
    "/monitor/reconciliation",
    "/monitor/alerts",
    "/monitor/positions/drift",
    "/positions",
    "/account",
]

_FORBIDDEN_HEARTBEAT_SUBSTRINGS = [
    "/connect",
    "/order/approve",
    "/order/submit",
    "/order/preflight",
    "/order",
]

HEARTBEAT_STALE_THRESHOLD_SECONDS = 2700

_KPI_SNAPSHOT_ENDPOINT = "/snapshot"

_KPI_ENDPOINTS = [
    "/health",
    "/readiness",
    "/status",
    "/monitor/reconciliation",
    "/monitor/alerts",
    "/monitor/events",
    "/positions",
    "/account",
]

_KPI_FORBIDDEN = [
    "/connect",
    "/order/approve",
    "/order/submit",
    "/order/preflight",
    "/order",
]

_GUARD_STATE_REPAIRS_DIR = OPENCLAW_DIR / "guard-state-repairs"

_GUARD_RECONCILE_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not open an order window.",
    "This command did not call any no-order endpoints.",
    "This command did not read H1 token.",
    "This command did not place, modify, cancel, or transmit any order.",
    "This command did not enable IBKR_ALLOW_ORDERS.",
    "This command did not enable rules.enforced.",
    "This command repairs local guard-state.json trade count only — no broker mutation.",
]

_POSITION_DRIFT_REPAIRS_DIR = OPENCLAW_DIR / "position-drift-repairs"

_POSITION_DRIFT_RECONCILE_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not open an order window.",
    "This command did not call any no-order endpoints.",
    "This command did not read H1 token.",
    "This command did not place, modify, cancel, or transmit any order.",
    "This command did not enable IBKR_ALLOW_ORDERS.",
    "This command did not enable rules.enforced.",
    "This command does not assert that any unconfirmed order filled at "
    "the broker — it records an adjustment to computed expected quantity, "
    "evidenced against a live IBKR read, with an audit trail of the "
    "unconfirmed approval_ids open for that symbol at time of repair.",
    "This command repairs local position-reconciliations.json only — no "
    "broker mutation, no rewrite of guard-events.jsonl (append-only).",
]

_PREREG_RUNTIME_SAFETY_PATHS: list[str] = [
    "bridge.py", "guard.py", "monitor.py", "ibkr_operator.py",
    "strategy_v1_1_core.py", "strategy_v1_1_advisory.py",
]

_CYCLE_EXPORT_DIR_NAME = "autonomy-cycles"

_REHEARSAL_FORBIDDEN_ENDPOINTS = frozenset({
    "/order",
    "/order/preflight",
    "/order/approve",
    "/order/submit",
    "/connect",
})

_CANDIDATE_EXPORT_DIR_NAME = "candidate-dryruns"

_CANDIDATE_PROPOSALS_DIR = OPENCLAW_DIR / "proposals"

_AUTONOMY_CYCLES_DIR = OPENCLAW_DIR / "autonomy-cycles"

_CLEAN_CYCLE_LEDGER = _AUTONOMY_CYCLES_DIR / "clean-cycle-ledger.jsonl"

_CANDIDATE_ALLOWED_SYMBOLS: frozenset[str] = frozenset({
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "JPM", "V", "JNJ", "WMT", "PG", "XOM", "UNH", "HD", "BAC",
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "BND", "AGG",
    "EFA", "EEM", "TLT", "LQD", "GLD", "XLF", "XLK", "XLE",
})

_LIGHTWEIGHT_DOCTOR_TIMEOUT = 8.0  # seconds for lightweight checks

_MD_DIAGNOSTICS_EXPORT_DIR = OPENCLAW_DIR / "market-data-diagnostics"

_MD_DIAGNOSTICS_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not open an order window.",
    "This command did not call any no-order endpoints.",
    "This command did not read H1 token.",
    "This command did not place, modify, cancel, or transmit any order.",
    "This command did not enable IBKR_ALLOW_ORDERS.",
    "This command did not enable rules.enforced.",
    "This command is purely diagnostic — no broker/account/order mutation.",
]

_MD_DIAGNOSTICS_COOLDOWN_SECONDS = 30.0  # must wait this long between runs

_MD_RECOVERY_DRILL_EXPORT_DIR = OPENCLAW_DIR / "market-data-drills"

_MD_RECOVERY_DRILL_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not open an order window.",
    "This command did not call any order endpoint.",
    "This command did not read H1 token.",
    "This command did not place, modify, cancel, or transmit any order.",
    "This command did not enable IBKR_ALLOW_ORDERS.",
    "This command did not enable rules.enforced.",
    "This command did not change any config or autonomy files.",
    "This command is purely diagnostic/recovery — no broker/account/order mutation.",
]

_CQ_DRILL_EXPORT_DIR = OPENCLAW_DIR / "contract-qualification-drills"

_CQ_DRILL_EXPLICIT_NON_ACTIONS: list[str] = [
    "No orders placed or modified",
    "No account values queried",
    "No position changes",
    "No IBKR_ALLOW_ORDERS changes",
    "No rules.enforced changes",
    "No autonomy-level changes",
    "No H1 token reads",
    "No /order, /order/preflight, /order/approve, /order/submit",
]

_CQ_DEFAULT_EXCHANGES: list[str] = ["SMART"]

_CQ_ALTERNATE_PRIMARY_EXCHANGES: list[str] = ["NASDAQ", "NYSE", "ARCA"]

_CQ_ALTERNATE_EXCHANGES: list[tuple[str, str]] = [
    # (exchange, primaryExchange) — bounded safe alternates
    ("SMART", "NASDAQ"),
    ("SMART", "NYSE"),
    ("SMART", "ARCA"),
    ("NASDAQ", ""),
    ("NYSE", ""),
]

_RECONNECT_READINESS_EXPORT_DIR = OPENCLAW_DIR / "reconnect-readiness-drills"

_RECONNECT_READINESS_EXPLICIT_NON_ACTIONS: list[str] = [
    "No orders placed or modified",
    "No account values mutated",
    "No position changes",
    "No IBKR_ALLOW_ORDERS changes",
    "No rules.enforced changes",
    "No autonomy-level changes",
    "No H1 token reads",
    "No /order, /order/preflight, /order/approve, /order/submit",
    "No guard-state mutation",
    "No bridge restart",
    "No auto-connect (unless --attempt-connect explicit opt-in)",
]

_RECONNECT_READINESS_FORBIDDEN = frozenset({
    "/order",
    "/order/preflight",
    "/order/approve",
    "/order/submit",
})

_POST_GATEWAY_PROOF_EXPORT_DIR = OPENCLAW_DIR / "post-gateway-reconnect-proofs"

_POST_GATEWAY_PROOF_READONLY_ENDPOINTS = [
    "/status",
    "/readiness",
    "/positions",
    "/account",
    "/monitor/alerts",
    "/monitor/reconciliation",
]

_POST_GATEWAY_PROOF_EXPLICIT_NON_ACTIONS: list[str] = [
    "No orders placed or modified",
    "No account values mutated",
    "No position changes",
    "No IBKR_ALLOW_ORDERS changes",
    "No rules.enforced changes",
    "No autonomy-level changes",
    "No H1 token reads",
    "No /order, /order/preflight, /order/approve, /order/submit",
    "No guard-state mutation",
    "No bridge restart",
    "No Gateway/TWS start or restart",
    "No auto-connect (unless --attempt-connect explicit opt-in)",
]

_CONNECTED_ENDPOINT_REGISTRY: list[dict] = [
    {"name": "health", "path": "/health",
     "category": "local", "applicability": "always"},
    {"name": "status", "path": "/status",
     "category": "broker_readonly", "applicability": "connected_preferred"},
    {"name": "readiness", "path": "/readiness",
     "category": "broker_readonly", "applicability": "always"},
    {"name": "positions", "path": "/positions",
     "category": "broker_readonly", "applicability": "connected_only"},
    {"name": "account", "path": "/account",
     "category": "broker_readonly", "applicability": "connected_only"},
    {"name": "monitor_alerts", "path": "/monitor/alerts",
     "category": "monitor", "applicability": "always"},
    {"name": "monitor_reconciliation", "path": "/monitor/reconciliation",
     "category": "monitor", "applicability": "connected_preferred"},
]

_CONNECTED_ENDPOINT_FORBIDDEN_ENDPOINTS = frozenset({
    "/order",
    "/order/preflight",
    "/order/approve",
    "/order/submit",
})

_CONNECTED_ENDPOINT_EXPORT_DIR = OPENCLAW_DIR / "connected-endpoint-evidence-drills"

_CONNECTED_ENDPOINT_EXPLICIT_NON_ACTIONS: list[str] = [
    "No orders placed or modified",
    "No account values mutated",
    "No position changes",
    "No IBKR_ALLOW_ORDERS changes",
    "No rules.enforced changes",
    "No autonomy-level changes",
    "No H1 token reads",
    "No /order, /order/preflight, /order/approve, /order/submit",
    "No /connect call",
    "No bridge restart",
    "No market-data or contract-diagnostics endpoints",
    "No guard-state mutation",
]

_CONNECTED_STABILITY_EXPORT_DIR = OPENCLAW_DIR / "connected-readonly-stability-drills"

_CONNECTED_STABILITY_READONLY_ENDPOINTS = [
    "/health",
    "/readiness",
    "/positions",
    "/account",
    "/monitor/alerts",
    "/monitor/reconciliation",
]

_CONNECTED_STABILITY_EXPLICIT_NON_ACTIONS: list[str] = [
    "No orders placed or modified",
    "No account values mutated",
    "No position changes",
    "No IBKR_ALLOW_ORDERS changes",
    "No rules.enforced changes",
    "No autonomy-level changes",
    "No H1 token reads",
    "No /order, /order/preflight, /order/approve, /order/submit",
    "No /connect call",
    "No bridge restart",
    "No guard-state mutation",
]

_LOCKED_PREFLIGHT_EXPORT_DIR = OPENCLAW_DIR / "locked-preflight-proofs"

_LOCKED_PREFLIGHT_EXPLICIT_NON_ACTIONS: list[str] = [
    "No /order called",
    "No /order/approve called",
    "No /order/submit called",
    "No H1 token read or used",
    "No trade-window check",
    "No order window opened",
    "No IBKR_ALLOW_ORDERS changes",
    "No rules.enforced changes",
    "No autonomy-level changes",
    "No bridge restart",
    "No auto-reconnect",
    "No approval artifacts created",
    "No broker order submitted, transmitted, cancelled, or modified",
    "No guard-state mutation",
]

_LOCKED_PREFLIGHT_FORBIDDEN_ENDPOINTS = frozenset({
    "/order",
    "/order/approve",
    "/order/submit",
})

_BP_DRAIN_EXPORT_DIR = OPENCLAW_DIR / "backpressure-drain-drills"

_BP_DRAIN_EXPLICIT_NON_ACTIONS: list[str] = [
    "No orders placed or modified",
    "No account values mutated",
    "No position changes",
    "No IBKR_ALLOW_ORDERS changes",
    "No rules.enforced changes",
    "No autonomy-level changes",
    "No H1 token reads",
    "No /order, /order/preflight, /order/approve, /order/submit",
]

_GUARD_DRIFT_EXPORT_DIR = OPENCLAW_DIR / "guard-state-drift-sentinels"

_GUARD_DRIFT_EXPLICIT_NON_ACTIONS: list[str] = [
    "No orders placed or modified",
    "No account values mutated",
    "No position changes",
    "No IBKR_ALLOW_ORDERS changes",
    "No rules.enforced changes",
    "No autonomy-level changes",
    "No guard-state repair (unless --repair flag)",
    "No H1 token reads",
    "No /order, /order/preflight, /order/approve, /order/submit",
]

_AUTONOMY_STATUS_EXPORT_DIR = OPENCLAW_DIR / "autonomy-status"

_CLEAN_CYCLES_REQUIRED = 5

_CLEAN_CYCLES_WINDOW_DAYS = 7

_CANDIDATE_EVIDENCE_MAX_AGE_SECONDS = 600

_DEFAULT_REFRESH_SYMBOL = "AAPL"

_DEFAULT_REFRESH_SIDE = "BUY"

_AUTONOMY_REVIEW_EXPORT_DIR = OPENCLAW_DIR / "autonomy-review"

_MANUAL_REVIEW_CHECKLIST: list[str] = [
    "Confirm no order window was opened.",
    "Confirm safety flags are locked (IBKR_ALLOW_ORDERS=false, rules.enforced=false).",
    "Confirm clean cycles are valid and recent.",
    "Confirm candidate evidence is HOLD/READY only, never NO-GO.",
    "Confirm market data and FX evidence if IBKR connected.",
    "Confirm promotion is manual only — this package does not auto-promote.",
    "Confirm no live orders will be enabled by this review package.",
]

_AUTONOMY_PROMOTION_PLANS_DIR = OPENCLAW_DIR / "autonomy-promotion-plans"

_MANUAL_PROMOTION_PRECONDITIONS: list[str] = [
    "Confirm operator is intentionally reviewing autonomy level 0 -> 1.",
    "Confirm no order window is open (IBKR_ALLOW_ORDERS=false, rules.enforced=false).",
    "Confirm safety flags remain locked throughout.",
    "Confirm fresh connected evidence from autonomy-status --refresh-evidence is READY.",
    "Confirm clean cycles are strict-valid and within the required time window.",
    "Confirm this promotion plan does not itself change any config.",
    "Confirm rollback procedure is understood before any manual change.",
]

_MANUAL_PROMOTION_STEPS: list[str] = [
    "1. Locate the autonomy-level definition in docs/AUTONOMY_CRITERIA.md.",
    "2. Record the current autonomy level value (expected: 0).",
    "3. Apply the manual change from level 0 to level 1 ONLY after operator approval.",
    "4. Do NOT enable IBKR_ALLOW_ORDERS — keep it false.",
    "5. Do NOT enable rules.enforced — keep it false.",
    "6. If the local control component requires restart/reload, perform it now.",
    "7. Immediately run post-promotion validation (see validation steps below).",
]

_MANUAL_ROLLBACK_STEPS: list[str] = [
    "1. Revert autonomy level back to 0 in docs/AUTONOMY_CRITERIA.md.",
    "2. Keep IBKR_ALLOW_ORDERS=false — do not enable.",
    "3. Keep rules.enforced=false — do not enable.",
    "4. Restart/reload the local control component if changed.",
    "5. Run ibkr-operator doctor.",
    "6. Run ibkr-operator kpi.",
    "7. Run ibkr-operator autonomy-status --refresh-evidence.",
    "8. Run ibkr-operator autonomy-review.",
    "9. Export rollback evidence using ibkr-operator autonomy-promotion-plan --export.",
]

_POST_PROMOTION_VALIDATION_STEPS: list[str] = [
    "1. Run ibkr-operator doctor — must PASS.",
    "2. Run ibkr-operator kpi — must be HOLD or better, never NO-GO.",
    "3. Run ibkr-operator autonomy-status — must show current level 1.",
    "4. Verify safety flags are still locked.",
    "5. Verify no order window was opened.",
    "6. Verify no positions changed (compare to pre-promotion snapshot).",
    "7. Verify no active alerts.",
    "8. Verify no broker mutation evidence in guard-state.json.",
]

_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not open an order window.",
    "This command did not call any no-order endpoints (no /order calls).",
    "This command did not read H1 token.",
    "This command did not place, modify, cancel, or transmit any order.",
    "This command did not enable IBKR_ALLOW_ORDERS.",
    "This command did not enable rules.enforced.",
]

_PHASE16A_EXPORT_DIR = OPENCLAW_DIR / "phase15-checkpoints"

_REQUIRED_PHASE15_TAGS: tuple[str, ...] = (
    "phase0_2_step15q_market_data_diagnostics",
    "phase0_2_step15r_market_data_recovery_drill",
    "phase0_2_step15s_contract_qualification_drill",
    "phase0_2_step15t_backpressure_drain_drill",
    "phase0_2_step15u_guard_state_drift_sentinel",
    "phase0_2_step15u_monitor_readonly_trade_date_hotfix",
    "phase0_2_step15v_reconnect_readiness_drill",
    "phase0_2_step15w_post_gateway_reconnect_proof",
    "phase0_2_step15x_connected_endpoint_evidence_normalization",
    "phase0_2_step15y_connected_readonly_stability_drill",
    "phase0_2_step15z_locked_preflight_proof",
)

_PHASE16A_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not call /order, /order/preflight, /order/approve, or /order/submit.",
    "This command did not reconnect the bridge.",
    "This command did not restart the bridge.",
    "This command did not repair guard-state.",
    "This command did not write anything except the export artifact.",
    "This command is purely read-only evidence aggregation.",
]

_PHASE16A_DIAGNOSIS = {
    "ready": "phase15_complete_ready_for_review",
    "missing_tags": "missing_phase15_tags",
    "dirty_worktree": "dirty_worktree",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "unknown": "unknown",
}

_PHASE16B_EXPORT_DIR = OPENCLAW_DIR / "level1-promotion-reviews"

_PHASE16B_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16a_phase15_completion_checkpoint",
    "phase0_2_step15z_locked_preflight_proof",
)

_PHASE16B_DIAGNOSIS = {
    "ready": "level1_promotion_review_ready",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "unknown": "unknown",
}

_PHASE16B_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not set Level 1.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not call /order, /order/preflight, /order/approve, or /order/submit.",
    "This command did not reconnect the bridge.",
    "This command did not restart the bridge.",
    "This command did not repair guard-state.",
    "This command did not mutate broker/account/orders.",
    "This command is purely read-only promotion review evidence aggregation.",
    "Only allowed write is the export artifact.",
]

_PHASE16B_DRY_RUN_STEPS: list[dict] = [
    {
        "step_number": 1,
        "title": "Verify Phase 16B Review Dossier",
        "purpose": "Confirm this promotion review report shows level1_promotion_review_ready / OK",
        "command_or_action": "ibkr-operator manual-level1-promotion-review --json --export",
        "expected_result": "diagnosis=level1_promotion_review_ready, severity=OK",
        "risk": "None — read-only",
        "rollback": "None required",
        "performed": False,
    },
    {
        "step_number": 2,
        "title": "Rehearse Autonomy Cycle with Level-1 Evidence",
        "purpose": "Run a full clean-cycle evidence rehearsal at Level 0 to confirm all gates pass",
        "command_or_action": "ibkr-operator candidate-dryrun --symbol AAPL --side BUY --json --export",
        "expected_result": "All gates pass, KPI HOLD (Level 0), no NO_GO blockers",
        "risk": "None — dry-run only, no order transmitted",
        "rollback": "None required",
        "performed": False,
    },
    {
        "step_number": 3,
        "title": "Run Full Doctor Suite",
        "purpose": "Verify all non-H1 doctor checks pass before promotion",
        "command_or_action": "ibkr-operator doctor --json",
        "expected_result": "PASS or PASS with H1 MANUAL only",
        "risk": "None — read-only",
        "rollback": "None required",
        "performed": False,
    },
    {
        "step_number": 4,
        "title": "Run KPI Dashboard",
        "purpose": "Confirm KPI verdict is HOLD with only autonomy_level_zero and system_locked blockers",
        "command_or_action": "ibkr-operator kpi --json",
        "expected_result": "verdict=HOLD, only expected blockers present",
        "risk": "None — read-only",
        "rollback": "None required",
        "performed": False,
    },
    {
        "step_number": 5,
        "title": "Review Autonomy Criteria Document",
        "purpose": "Human operator reviews docs/AUTONOMY_CRITERIA.md and confirms readiness",
        "command_or_action": "cat ~/agents/ibkr-bridge/docs/AUTONOMY_CRITERIA.md",
        "expected_result": "Operator confirms understanding of Level-1 criteria",
        "risk": "None",
        "rollback": "None required",
        "performed": False,
    },
    {
        "step_number": 6,
        "title": "Manual Operator Go/No-Go Decision",
        "purpose": "Chris makes the final human decision on Level-1 promotion",
        "command_or_action": "Chris executes ibkr-operator autonomy-promotion-plan --target-level 1 --json",
        "expected_result": "Chris approves and signs off",
        "risk": "Promotion changes autonomy level — requires human judgment",
        "rollback": "ibkr-operator autonomy-promotion-plan --target-level 0 (revert to Level 0)",
        "performed": False,
    },
]

_PHASE16C_EXPORT_DIR = OPENCLAW_DIR / "level1-dry-run-gates"

_PHASE16C_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16b_manual_level1_promotion_review",
    "phase16a_phase15_completion_checkpoint",
    "phase0_2_step15z_locked_preflight_proof",
)

_PHASE16C_DIAGNOSIS = {
    "ready": "level1_dry_run_gate_ready",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "unknown": "unknown",
}

_PHASE16C_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not set Level 1.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not call /order, /order/preflight, /order/approve, or /order/submit.",
    "This command did not call trade-window helper.",
    "This command did not reconnect the bridge.",
    "This command did not restart the bridge.",
    "This command did not repair guard-state.",
    "This command did not mutate broker/account/orders.",
    "This command is purely read-only dry-run gate evidence aggregation.",
    "Only allowed write is the export artifact.",
    "The future_apply_command_preview, rollback_command_preview, and relock_command_preview are strings only — they were not executed.",
]

_PHASE16C_DRY_RUN_STEPS: list[dict] = [
    {
        "step_number": 1,
        "title": "Verify Phase 16C Dry-Run Gate Dossier",
        "purpose": "Confirm this gate report shows level1_dry_run_gate_ready / OK",
        "command_or_action": "ibkr-operator level1-promotion-dry-run-gate --json --export",
        "expected_result": "diagnosis=level1_dry_run_gate_ready, severity=OK, gate_ready=true",
        "risk": "None — read-only",
        "rollback": "None required",
        "performed": False,
    },
    {
        "step_number": 2,
        "title": "Review Phase 16B Promotion Review Dossier",
        "purpose": "Confirm Phase 16B review is still clean",
        "command_or_action": "ibkr-operator manual-level1-promotion-review --json",
        "expected_result": "diagnosis=level1_promotion_review_ready, severity=OK",
        "risk": "None — read-only",
        "rollback": "None required",
        "performed": False,
    },
    {
        "step_number": 3,
        "title": "Rehearse Clean-Cycle Candidate Dry-Run",
        "purpose": "Run a full candidate dry-run to confirm all gates pass at Level 0",
        "command_or_action": "ibkr-operator candidate-dryrun --symbol AAPL --side BUY --json --export",
        "expected_result": "All gates pass, KPI HOLD (Level 0), no NO_GO blockers",
        "risk": "None — dry-run only, no order transmitted",
        "rollback": "None required",
        "performed": False,
    },
    {
        "step_number": 4,
        "title": "Run Full Doctor Suite",
        "purpose": "Verify all non-H1 doctor checks pass",
        "command_or_action": "ibkr-operator doctor --json",
        "expected_result": "PASS or PASS with H1 MANUAL only",
        "risk": "None — read-only",
        "rollback": "None required",
        "performed": False,
    },
    {
        "step_number": 5,
        "title": "Run KPI Dashboard",
        "purpose": "Confirm KPI verdict is HOLD with only expected blockers",
        "command_or_action": "ibkr-operator kpi --json",
        "expected_result": "verdict=HOLD, only autonomy_level_zero and system_locked blockers",
        "risk": "None — read-only",
        "rollback": "None required",
        "performed": False,
    },
    {
        "step_number": 6,
        "title": "Review Future Apply Command Preview",
        "purpose": "Operator reviews the exact command that will be run in Phase 16D",
        "command_or_action": "Review future_apply_command_preview in gate output",
        "expected_result": "Operator understands and approves the apply command",
        "risk": "None",
        "rollback": "None required",
        "performed": False,
    },
    {
        "step_number": 7,
        "title": "Review Rollback and Relock Commands",
        "purpose": "Operator reviews rollback and relock command previews",
        "command_or_action": "Review rollback_command_preview and relock_command_preview in gate output",
        "expected_result": "Operator understands and approves rollback/relock plans",
        "risk": "None",
        "rollback": "None required",
        "performed": False,
    },
    {
        "step_number": 8,
        "title": "Manual Operator Go/No-Go Decision",
        "purpose": "Chris makes the final human decision to proceed to Phase 16D apply gate",
        "command_or_action": "Proceed to Phase 16D: explicit human-signed Level-1 apply gate",
        "expected_result": "Chris signs off on Level-1 promotion",
        "risk": "Actual promotion follows in Phase 16D — requires human judgment",
        "rollback": "Phase 16D rollback: ibkr-operator level1-relock",
        "performed": False,
    },
]

_PHASE16C_FUTURE_APPLY_COMMAND_PREVIEW = (
    "ibkr-operator autonomy-promotion-plan --target-level 1 "
    "--confirm-level1 --human-signed-apply --json --export"
)

_PHASE16C_ROLLBACK_COMMAND_PREVIEW = (
    "ibkr-operator autonomy-promotion-plan --target-level 0 "
    "--confirm-rollback --human-signed --json"
)

_PHASE16C_RELOCK_COMMAND_PREVIEW = (
    "ibkr-operator safety-relock --confirm --json"
)

_PHASE16D_EXPORT_DIR = OPENCLAW_DIR / "level1-apply-gates"

_PHASE16D_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16c_level1_promotion_dry_run_gate",
    "phase16b_manual_level1_promotion_review",
    "phase16a_phase15_completion_checkpoint",
    "phase0_2_step15z_locked_preflight_proof",
)

_PHASE16D_DIAGNOSIS = {
    "ready": "level1_apply_gate_ready",
    "applied": "level1_apply_performed",
    "missing_required_tags": "missing_required_tags",
    "missing_explicit_apply_flags": "missing_explicit_apply_flags",
    "dirty_worktree": "dirty_worktree",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "autonomy_not_level0": "autonomy_not_level0",
    "apply_failed": "apply_failed",
    "bridge_not_ready_during_apply": "bridge_not_ready_during_apply",
    "unknown": "unknown",
}

_PHASE16D_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not set IBKR_ALLOW_ORDERS=true.",
    "This command did not set rules.enforced=true.",
    "This command did not unlock system_locked.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not call trade-window helper.",
    "This command did not call /order, /order/preflight, /order/approve, or /order/submit.",
    "This command did not submit orders.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "This command did not mutate broker/account/orders.",
    "Only allowed mutations in apply mode: autonomy_level 0 -> 1, audit export written.",
]

_PHASE16D_EXPLICIT_APPLY_FLAGS: tuple[str, ...] = (
    "--apply",
    "--confirm-level1",
    "--human-signed-apply",
    "--ack-no-order-enablement",
    "--ack-manual-approval-required",
    "--ack-relock-required",
)

_PHASE16E_EXPORT_DIR = OPENCLAW_DIR / "level1-stability-drills"

_PHASE16E_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16d_level1_apply_performed_20260626",
    "phase16d_human_signed_level1_apply_gate",
    "phase16c_level1_promotion_dry_run_gate",
    "phase16b_manual_level1_promotion_review",
    "phase16a_phase15_completion_checkpoint",
    "phase0_2_step15z_locked_preflight_proof",
)

_PHASE16E_DIAGNOSIS = {
    "ready": "level1_post_promotion_stability_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "autonomy_not_level1": "autonomy_not_level1",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "stability_failed": "stability_failed",
    "insufficient_samples": "insufficient_samples",
    "unknown": "unknown",
}

_PHASE16E_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not call trade-window helper.",
    "This command did not call /order, /order/preflight, /order/approve, or /order/submit.",
    "This command did not submit orders.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "This command did not mutate broker/account/orders.",
    "Only allowed write is the export artifact.",
]

_PHASE16F_EXPORT_DIR = OPENCLAW_DIR / "evidence-normalization-checks"

_PHASE16F_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16e_level1_post_promotion_stability_drill",
    "phase16d_level1_apply_performed_20260626",
    "phase16d_human_signed_level1_apply_gate",
)

_PHASE16F_DIAGNOSIS = {
    "ready": "level1_evidence_normalization_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "autonomy_not_level1": "autonomy_not_level1",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "clean_cycles_mismatch": "clean_cycles_mismatch",
    "clean_cycles_defaulted_to_zero": "clean_cycles_defaulted_to_zero",
    "unknown": "unknown",
}

_PHASE16F_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not call trade-window helper.",
    "This command did not call /order, /order/preflight, /order/approve, or /order/submit.",
    "This command did not submit orders.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "This command did not mutate broker/account/orders.",
    "Only allowed write is the export artifact.",
]

_PHASE16G_EXPORT_DIR = OPENCLAW_DIR / "level1-proposal-drills"

_PHASE16G_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16f_level1_evidence_normalization",
    "phase16e_level1_post_promotion_stability_drill",
    "phase16d_level1_apply_performed_20260626",
)

_PHASE16G_DIAGNOSIS = {
    "ready": "level1_proposal_workflow_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "autonomy_not_level1": "autonomy_not_level1",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "clean_cycles_mismatch": "clean_cycles_mismatch",
    "unknown": "unknown",
}

_PHASE16G_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not call trade-window helper.",
    "This command did not call /order, /order/preflight, /order/approve, or /order/submit.",
    "This command did not submit orders.",
    "This command did not call broker mutation endpoints.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "Only allowed write is the export artifact.",
]

_PROPOSAL_SYMBOL_POOL: list[dict] = [
    {"symbol": "SPY", "side": "BUY", "rationale": "Core S&P 500 exposure — broad market participation"},
    {"symbol": "QQQ", "side": "BUY", "rationale": "Nasdaq-100 growth exposure — tech sector allocation"},
    {"symbol": "IWM", "side": "BUY", "rationale": "Russell 2000 small-cap diversification"},
    {"symbol": "TLT", "side": "BUY", "rationale": "Long-duration Treasury hedge against equity drawdown"},
    {"symbol": "GLD", "side": "BUY", "rationale": "Gold allocation — inflation hedge and portfolio diversifier"},
    {"symbol": "VTI", "side": "BUY", "rationale": "Total US market — low-cost broad equity core"},
    {"symbol": "BND", "side": "BUY", "rationale": "Aggregate bond exposure — fixed-income ballast"},
    {"symbol": "VXUS", "side": "BUY", "rationale": "Total international ex-US — geographic diversification"},
    {"symbol": "XLF", "side": "BUY", "rationale": "Financial sector tactical allocation"},
    {"symbol": "XLE", "side": "BUY", "rationale": "Energy sector — inflation-sensitive commodity exposure"},
]

_PHASE16H_EXPORT_DIR = OPENCLAW_DIR / "level1-review-packages"

_PHASE16H_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16g_level1_proposal_workflow_drill",
    "phase16f_level1_evidence_normalization",
    "phase16e_level1_post_promotion_stability_drill",
)

_PHASE16H_DIAGNOSIS = {
    "ready": "level1_human_review_package_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "autonomy_not_level1": "autonomy_not_level1",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "clean_cycles_mismatch": "clean_cycles_mismatch",
    "executable_item_present": "executable_item_present",
    "unknown": "unknown",
}

_PHASE16H_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not call trade-window helper.",
    "This command did not call /order, /order/preflight, /order/approve, or /order/submit.",
    "This command did not submit orders.",
    "This command did not call broker mutation endpoints.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "Only allowed writes are the export artifact and review package artifact.",
]

_REVIEW_CANDIDATE_POOL: list[dict] = [
    {"symbol": "SPY", "side": "BUY", "rationale": "Core S&P 500 exposure — broad market participation"},
    {"symbol": "QQQ", "side": "BUY", "rationale": "Nasdaq-100 growth exposure — tech sector allocation"},
    {"symbol": "IWM", "side": "BUY", "rationale": "Russell 2000 small-cap diversification"},
    {"symbol": "TLT", "side": "BUY", "rationale": "Long-duration Treasury hedge against equity drawdown"},
    {"symbol": "GLD", "side": "BUY", "rationale": "Gold allocation — inflation hedge and portfolio diversifier"},
    {"symbol": "VTI", "side": "BUY", "rationale": "Total US market — low-cost broad equity core"},
    {"symbol": "BND", "side": "BUY", "rationale": "Aggregate bond exposure — fixed-income ballast"},
    {"symbol": "VXUS", "side": "BUY", "rationale": "Total international ex-US — geographic diversification"},
    {"symbol": "XLF", "side": "BUY", "rationale": "Financial sector tactical allocation"},
    {"symbol": "XLE", "side": "BUY", "rationale": "Energy sector — inflation-sensitive commodity exposure"},
]

_PHASE16I_EXPORT_DIR = OPENCLAW_DIR / "level1-review-decisions"

_PHASE16I_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16h_level1_human_review_package_drill",
    "phase16g_level1_proposal_workflow_drill",
    "phase16f_level1_evidence_normalization",
)

_PHASE16I_DIAGNOSIS = {
    "ready": "level1_review_decision_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "autonomy_not_level1": "autonomy_not_level1",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "clean_cycles_mismatch": "clean_cycles_mismatch",
    "review_package_not_found": "review_package_not_found",
    "review_package_not_review_only": "review_package_not_review_only",
    "unknown": "unknown",
}

_PHASE16I_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not call trade-window helper.",
    "This command did not call /order, /order/preflight, /order/approve, or /order/submit.",
    "This command did not submit orders.",
    "This command did not call broker mutation endpoints.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "Only allowed writes are the export artifact and decision artifact.",
    "Accepted items are advisory/audit only — they do NOT trigger order paths.",
]

_DECISION_MODE_VALUES = ("mixed_demo", "accept_all_demo", "reject_all_demo", "defer_all_demo")

_DECISION_LOGIC = {
    "accept_all_demo": lambda i, item: "accept",
    "reject_all_demo": lambda i, item: "reject",
    "defer_all_demo": lambda i, item: "defer",
    "mixed_demo": lambda i, item: "accept" if i % 2 == 0 else ("reject" if i % 3 == 1 else "defer"),
}

_DECISION_RATIONALE_TEMPLATES = {
    "accept": "Advisory acceptance — signals readiness for future order consideration. Does NOT enable orders, open trade window, or route to broker.",
    "reject": "Rejected — rationale may include insufficient risk assessment, market conditions, or position-sizing concerns. Item will not proceed.",
    "defer": "Deferred — requires additional review, data, or conditions before acceptance. Item remains in pending state.",
}

_PHASE16J_EXPORT_DIR = OPENCLAW_DIR / "level1-order-plan-drafts"

_PHASE16J_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16i_level1_review_decision_drill",
    "phase16h_level1_human_review_package_drill",
    "phase16g_level1_proposal_workflow_drill",
)

_PHASE16J_DIAGNOSIS = {
    "ready": "level1_order_plan_draft_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "autonomy_not_level1": "autonomy_not_level1",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "clean_cycles_mismatch": "clean_cycles_mismatch",
    "decision_artifact_not_found": "decision_artifact_not_found",
    "decision_artifact_not_audit_only": "decision_artifact_not_audit_only",
    "executable_item_present": "executable_item_present",
    "broker_order_created": "broker_order_created",
    "unknown": "unknown",
}

_PHASE16J_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not call trade-window helper.",
    "This command did not call /order, /order/preflight, /order/approve, or /order/submit.",
    "This command did not preflight.",
    "This command did not approve.",
    "This command did not submit.",
    "This command did not submit orders.",
    "This command did not create a broker order.",
    "This command did not call broker mutation endpoints.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "Only allowed writes are the export artifact and order-plan-draft artifact.",
    "Draft items are non-executable and must not become broker orders.",
]

_DRAFT_ITEM_TEMPLATE = {
    "executable": False,
    "performed": False,
    "broker_order_created": False,
    "broker_order_id": None,
    "order_type": "LMT",
    "time_in_force": "DAY",
    "limit_price": None,
    "requires_chris_approval": True,
    "requires_future_order_window": True,
    "requires_future_h1": True,
    "future_required_path": "/order/preflight -> /order/approve -> /order/submit",
}

_PHASE16K_EXPORT_DIR = OPENCLAW_DIR / "level1-preflight-simulation-dossiers"

_PHASE16K_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16j_level1_order_plan_draft_drill",
    "phase16i_level1_review_decision_drill",
    "phase16h_level1_human_review_package_drill",
)

_PHASE16K_DIAGNOSIS = {
    "ready": "level1_preflight_simulation_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "autonomy_not_level1": "autonomy_not_level1",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "clean_cycles_mismatch": "clean_cycles_mismatch",
    "order_plan_not_found": "order_plan_not_found",
    "order_plan_not_draft_only": "order_plan_not_draft_only",
    "order_plan_has_executable_items": "order_plan_has_executable_items",
    "order_plan_has_broker_orders": "order_plan_has_broker_orders",
    "no_draft_items_to_simulate": "no_draft_items_to_simulate",
    "unknown": "unknown",
}

_PHASE16K_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not call trade-window helper.",
    "This command did not call /order, /order/preflight, /order/approve, or /order/submit.",
    "This command did not call /order/preflight (simulation only).",
    "This command did not preflight with broker.",
    "This command did not approve.",
    "This command did not submit.",
    "This command did not submit orders.",
    "This command did not create a broker order.",
    "This command did not call broker mutation endpoints.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "Only allowed writes are the export artifact and preflight simulation dossier artifact.",
    "All preflight checks are deterministic local simulations — no broker validation was performed.",
]

_SIMULATION_DOSSIER_ITEM_TEMPLATE: dict[str, Any] = {
    "simulated_preflight_only": True,
    "real_preflight_performed": False,
    "future_real_preflight_required": True,
    "preflight_endpoint_called": False,
    "broker_validation_performed": False,
    "simulated_preflight_status": "PASS (simulated)",
    "simulated_checks": [
        {"check": "margin", "status": "PASS", "detail": "Deterministic local simulation — no broker margin check performed"},
        {"check": "contract", "status": "PASS", "detail": "Deterministic local simulation — no broker contract validation performed"},
        {"check": "risk", "status": "PASS", "detail": "Deterministic local simulation — no broker risk check performed"},
        {"check": "compliance", "status": "PASS", "detail": "Deterministic local simulation — no broker compliance check performed"},
    ],
    "preflight_blockers": [],
    "preflight_warnings": ["Simulated only — real preflight required before submission"],
    "executable": False,
    "performed": False,
    "broker_order_id": None,
    "requires_chris_approval": True,
    "requires_future_order_window": True,
    "requires_future_h1": True,
    "requires_future_chris_approval": True,
    "future_required_path": "/order/preflight -> /order/approve -> /order/submit",
}

_PHASE16L_EXPORT_DIR = OPENCLAW_DIR / "level1-human-approval-packets"

_PHASE16L_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16k_level1_preflight_simulation_dossier",
    "phase16j_level1_order_plan_draft_drill",
    "phase16i_level1_review_decision_drill",
)

_PHASE16L_DIAGNOSIS = {
    "ready": "level1_human_approval_packet_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "autonomy_not_level1": "autonomy_not_level1",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "clean_cycles_mismatch": "clean_cycles_mismatch",
    "dossier_not_found": "dossier_not_found",
    "dossier_not_simulation_only": "dossier_not_simulation_only",
    "dossier_has_real_preflight": "dossier_has_real_preflight",
    "dossier_has_executable_items": "dossier_has_executable_items",
    "no_items_to_approve": "no_items_to_approve",
    "unknown": "unknown",
}

_PHASE16L_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not call trade-window helper.",
    "This command did not call /order, /order/approve, /order/preflight, or /order/submit.",
    "This command did not call /order/approve (packet only).",
    "This command did not approve with broker.",
    "This command did not preflight.",
    "This command did not submit.",
    "This command did not submit orders.",
    "This command did not create a broker order.",
    "This command did not call broker mutation endpoints.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "Only allowed writes are the export artifact and human approval packet artifact.",
    "All items are human approval packets only — no broker approval was performed.",
    "Chris must manually sign and approve before any order path.",
]

_PACKET_ITEM_TEMPLATE: dict[str, Any] = {
    "human_packet_only": True,
    "broker_approval_performed": False,
    "approval_endpoint_called": False,
    "h1_token_used": False,
    "executable": False,
    "performed": False,
    "broker_order_id": None,
    "requires_future_order_window": True,
    "requires_future_h1": True,
    "requires_future_chris_approval": True,
    "future_real_preflight_required": True,
    "future_real_approval_required": True,
    "future_required_path": "/order/preflight -> /order/approve -> /order/submit",
}

_PHASE16M_EXPORT_DIR = OPENCLAW_DIR / "level1-execution-readiness-packets"

_PHASE16M_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16l_level1_human_approval_packet_drill",
    "phase16k_level1_preflight_simulation_dossier",
    "phase16j_level1_order_plan_draft_drill",
)

_PHASE16M_DIAGNOSIS = {
    "ready": "level1_execution_readiness_packet_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "autonomy_not_level1": "autonomy_not_level1",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "clean_cycles_mismatch": "clean_cycles_mismatch",
    "approval_packet_not_found": "approval_packet_not_found",
    "approval_packet_not_packet_only": "approval_packet_not_packet_only",
    "approval_packet_has_broker_activity": "approval_packet_has_broker_activity",
    "approval_packet_has_executable_items": "approval_packet_has_executable_items",
    "no_items_to_assess": "no_items_to_assess",
    "unknown": "unknown",
}

_PHASE16M_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not call trade-window helper.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not submit orders.",
    "This command did not create a broker order.",
    "This command did not call broker mutation endpoints.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "Only allowed writes are the export artifact and execution-readiness packet artifact.",
    "This is NOT execution authorization — execution is NOT currently allowed.",
    "Every readiness item declares execution_authorized_now=false.",
    "Chris must manually approve, open the order window, and use H1 before any real execution.",
]

_READINESS_ITEM_TEMPLATE: dict[str, Any] = {
    "readiness_packet_only": True,
    "execution_authorized_now": False,
    "executable": False,
    "performed": False,
    "broker_order_id": None,
    "order_enablement_required": True,
    "h1_token_used": False,
    "future_order_window_required": True,
    "future_h1_required": True,
    "future_real_preflight_required": True,
    "future_real_approval_required": True,
    "future_real_submit_required": True,
    "future_required_path": (
        "/order/preflight -> /order/approve -> /order/submit"
    ),
}

_PHASE16N_EXPORT_DIR = OPENCLAW_DIR / "level1-readiness-chain-checkpoints"

_PHASE16N_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16m_level1_execution_readiness_packet_drill",
    "phase16l_level1_human_approval_packet_drill",
    "phase16k_level1_preflight_simulation_dossier",
    "phase16j_level1_order_plan_draft_drill",
    "phase16i_level1_review_decision_drill",
    "phase16h_level1_human_review_package_drill",
    "phase16g_level1_proposal_workflow_drill",
)

_PHASE16N_DIAGNOSIS = {
    "ready": "level1_readiness_chain_integrity_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "autonomy_not_level1": "autonomy_not_level1",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "clean_cycles_mismatch": "clean_cycles_mismatch",
    "chain_integrity_broken": "chain_integrity_broken",
    "unknown": "unknown",
}

_PHASE16N_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not call trade-window helper.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not submit orders.",
    "This command did not create a broker order.",
    "This command did not call broker mutation endpoints.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "Only allowed writes are the export artifact and chain-integrity checkpoint artifact.",
    "This checkpoint verifies the full advisory-to-readiness chain is non-executable.",
    "All 7 stages confirmed non-executable and advisory/readiness-only.",
    "No stage has broker_preflight_performed, broker_approval_performed, broker_submit_performed, or broker_order_created.",
]

_CHAIN_STAGE_TEMPLATE: dict[str, Any] = {
    "non_executable": True,
    "advisory_or_readiness_only": True,
    "broker_preflight_performed": False,
    "broker_approval_performed": False,
    "broker_submit_performed": False,
    "broker_order_created": False,
    "executable": False,
    "execution_authorized_now": False,
    "h1_token_used": False,
    "order_window_opened": False,
    "broker_mutation": False,
    "no_order_endpoint_called": True,
    "trade_window_helper_called": False,
    "future_order_window_required": True,
    "future_h1_required": True,
    "future_required_path": "/order/preflight -> /order/approve -> /order/submit",
    "chain_complete": True,
    "chain_order_valid": True,
}

_CHAIN_PIPELINE: list[dict[str, Any]] = [
    {"stage": "16G proposal workflow",
     "phase": "phase16g_level1_proposal_workflow_drill",
     "artifact_type": "proposal_drill"},
    {"stage": "16H human review package",
     "phase": "phase16h_level1_human_review_package_drill",
     "artifact_type": "review_package_drill"},
    {"stage": "16I review decision audit",
     "phase": "phase16i_level1_review_decision_drill",
     "artifact_type": "decision_audit_drill"},
    {"stage": "16J order-plan draft",
     "phase": "phase16j_level1_order_plan_draft_drill",
     "artifact_type": "order_plan_draft"},
    {"stage": "16K simulated preflight dossier",
     "phase": "phase16k_level1_preflight_simulation_dossier",
     "artifact_type": "preflight_simulation_dossier"},
    {"stage": "16L human approval packet",
     "phase": "phase16l_level1_human_approval_packet_drill",
     "artifact_type": "human_approval_packet"},
    {"stage": "16M execution-readiness packet",
     "phase": "phase16m_level1_execution_readiness_packet_drill",
     "artifact_type": "execution_readiness_packet"},
]

_PHASE16O_EXPORT_DIR = OPENCLAW_DIR / "level1-execution-gate-negative-controls"

_PHASE16O_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16n_level1_readiness_chain_integrity_checkpoint",
    "phase16m_level1_execution_readiness_packet_drill",
    "phase16l_level1_human_approval_packet_drill",
    "phase16k_level1_preflight_simulation_dossier",
    "phase16j_level1_order_plan_draft_drill",
)

_PHASE16O_DIAGNOSIS = {
    "ready": "level1_execution_gate_negative_control_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "autonomy_not_level1": "autonomy_not_level1",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "clean_cycles_mismatch": "clean_cycles_mismatch",
    "execution_blocked_as_expected": "execution_blocked_as_expected",
    "unknown": "unknown",
}

_PHASE16O_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not call trade-window helper.",
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not submit orders.",
    "This command did not create a broker order.",
    "This command did not call broker mutation endpoints.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "Only allowed writes are export/negative-control evidence artifacts.",
    "This negative-control drill proves execution remains blocked.",
    "All execution intents are locally blocked with explicit reasons.",
    "No real order path was touched — this is a gate check only.",
]

_EXECUTION_INTENT_TEMPLATE: dict[str, Any] = {
    "blocked": True,
    "executable": False,
    "execution_authorized_now": False,
    "simulated_intent_only": True,
    "expected_result": "blocked",
    "real_preflight_performed": False,
    "real_approval_performed": False,
    "real_submit_performed": False,
    "broker_mutation": False,
    "broker_order_created": False,
    "h1_token_used": False,
    "order_window_opened": False,
    "trade_window_helper_called": False,
    "no_order_endpoint_called": True,
    "simulated_preflight_status": "BLOCKED",
    "simulated_approval_status": "BLOCKED",
    "simulated_submit_status": "BLOCKED",
    "gate_status": "GATE_CLOSED",
    "source_stage": "16O_execution_gate_negative_control",
    "time_in_force": "DAY",
    "performed": False,
}

_DEMO_EXECUTION_INTENTS: list[dict[str, Any]] = [
    {"symbol": "SPY", "side": "BUY", "action": "BUY", "quantity": 10, "order_type": "MKT",
     "requested_action": "BUY 10 SPY MKT", "time_in_force": "DAY"},
    {"symbol": "VTI", "side": "BUY", "action": "BUY", "quantity": 5, "order_type": "LMT",
     "requested_action": "BUY 5 VTI LMT", "time_in_force": "DAY"},
    {"symbol": "BND", "side": "BUY", "action": "BUY", "quantity": 15, "order_type": "MKT",
     "requested_action": "BUY 15 BND MKT", "time_in_force": "DAY"},
    {"symbol": "VXUS", "side": "BUY", "action": "BUY", "quantity": 5, "order_type": "LMT",
     "requested_action": "BUY 5 VXUS LMT", "time_in_force": "DAY"},
    {"symbol": "GLD", "side": "BUY", "action": "BUY", "quantity": 3, "order_type": "MKT",
     "requested_action": "BUY 3 GLD MKT", "time_in_force": "DAY"},
]

_GATE_BLOCKING_REASONS: list[str] = [
    "execution_gate_closed_no_order_window",
    "execution_gate_closed_no_h1_token",
    "execution_gate_closed_no_order_enablement",
    "execution_gate_closed_system_locked",
    "execution_gate_closed_autonomy_level_1",
    "execution_gate_closed_no_real_preflight",
    "execution_gate_closed_no_real_approval",
    "execution_gate_closed_no_real_submit",
    "execution_gate_closed_orders_disabled",
    "execution_gate_closed_rules_enforced",
]

_PHASE16P_EXPORT_DIR = OPENCLAW_DIR / "level1-order-window-canary-negative-controls"

_PHASE16P_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16o_level1_execution_gate_negative_control_drill",
    "phase16n_level1_readiness_chain_integrity_checkpoint",
    "phase16m_level1_execution_readiness_packet_drill",
    "phase16l_level1_human_approval_packet_drill",
    "phase16k_level1_preflight_simulation_dossier",
)

_PHASE16P_DIAGNOSIS = {
    "ready": "level1_order_window_canary_negative_control_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "autonomy_not_level1": "autonomy_not_level1",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "clean_cycles_mismatch": "clean_cycles_mismatch",
    "order_window_not_closed": "order_window_not_closed",
    "unknown": "unknown",
}

_PHASE16P_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not open an order window.",
    "This command did not read H1 token.",
    "This command did not use H1 token.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not submit orders.",
    "This command did not create a broker order.",
    "This command did not call broker mutation endpoints.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "Only allowed writes are export/order-window-canary evidence artifacts.",
    "This negative-control drill proves the order window remains closed.",
    "All H1/order-window-dependent canaries are locally blocked with explicit reasons.",
    "No real order window or H1 token was touched — this is a canary check only.",
]

_ORDER_WINDOW_CANARY_TEMPLATE: dict[str, Any] = {
    "blocked": True,
    "executable": False,
    "execution_authorized_now": False,
    "simulated_canary_only": True,
    "expected_result": "blocked",
    "order_window_opened_by_drill": False,
    "h1_token_used": False,
    "h1_token_read": False,
    "h1_token_available_to_drill": False,
    "trade_window_helper_called": False,
    "order_endpoint_called": False,
    "preflight_endpoint_called": False,
    "approval_endpoint_called": False,
    "submit_endpoint_called": False,
    "broker_mutation": False,
    "broker_order_created": False,
    "gate_status": "GATE_CLOSED",
    "source_stage": "16P_order_window_canary_negative_control",
    "performed": False,
}

_DEMO_ORDER_WINDOW_CANARIES: list[dict[str, Any]] = [
    {"symbol": "SPY", "side": "BUY", "action": "BUY", "quantity": 10, "order_type": "MKT",
     "requested_action": "OPEN_ORDER_WINDOW BUY 10 SPY MKT", "time_in_force": "DAY",
     "requires_h1": True, "requires_order_window": True},
    {"symbol": "VTI", "side": "BUY", "action": "BUY", "quantity": 5, "order_type": "LMT",
     "requested_action": "OPEN_ORDER_WINDOW BUY 5 VTI LMT", "time_in_force": "DAY",
     "requires_h1": True, "requires_order_window": True},
    {"symbol": "BND", "side": "BUY", "action": "BUY", "quantity": 15, "order_type": "MKT",
     "requested_action": "OPEN_ORDER_WINDOW BUY 15 BND MKT", "time_in_force": "DAY",
     "requires_h1": True, "requires_order_window": True},
    {"symbol": "VXUS", "side": "BUY", "action": "BUY", "quantity": 5, "order_type": "LMT",
     "requested_action": "OPEN_ORDER_WINDOW BUY 5 VXUS LMT", "time_in_force": "DAY",
     "requires_h1": True, "requires_order_window": True},
    {"symbol": "GLD", "side": "BUY", "action": "BUY", "quantity": 3, "order_type": "MKT",
     "requested_action": "OPEN_ORDER_WINDOW BUY 3 GLD MKT", "time_in_force": "DAY",
     "requires_h1": True, "requires_order_window": True},
]

_ORDER_WINDOW_CANARY_BLOCKING_REASONS: list[str] = [
    "order_window_closed_no_h1_token",
    "order_window_closed_no_h1_approval",
    "order_window_closed_no_human_authorization",
    "order_window_closed_system_locked",
    "order_window_closed_autonomy_level_1",
    "order_window_closed_orders_disabled",
    "order_window_closed_rules_not_enforced",
    "order_window_closed_no_order_enablement",
]

_PHASE16Q_EXPORT_DIR = OPENCLAW_DIR / "level1-h1-boundary-audits"

_PHASE16Q_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16p_level1_order_window_canary_negative_control_drill",
    "phase16o_level1_execution_gate_negative_control_drill",
    "phase16n_level1_readiness_chain_integrity_checkpoint",
    "phase16m_level1_execution_readiness_packet_drill",
    "phase16l_level1_human_approval_packet_drill",
)

_PHASE16Q_DIAGNOSIS = {
    "ready": "level1_h1_boundary_audit_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "autonomy_not_level1": "autonomy_not_level1",
    "runtime_not_ready": "runtime_not_ready",
    "safety_not_locked": "safety_not_locked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "clean_cycles_mismatch": "clean_cycles_mismatch",
    "h1_boundary_not_intact": "h1_boundary_not_intact",
    "unknown": "unknown",
}

_PHASE16Q_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command never read the raw H1 token file.",
    "This command did not stat or open raw H1 token path.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not open an order window.",
    "This command did not submit orders.",
    "This command did not create a broker order.",
    "This command did not call broker mutation endpoints.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "Only allowed writes are export/H1-boundary audit evidence artifacts.",
    "This H1 boundary audit proves H1 remains unavailable and all H1-dependent actions are manual-required.",
    "No raw H1 token was touched — H1_APPROVAL_TOKEN_HASH is the only expected/configured H1 artifact.",
]

_H1_BOUNDARY_CANARY_TEMPLATE: dict[str, Any] = {
    "blocked": True,
    "executable": False,
    "execution_authorized_now": False,
    "simulated_canary_only": True,
    "expected_result": "blocked",
    "raw_token_read": False,
    "raw_token_path_opened": False,
    "raw_token_value_seen": False,
    "raw_token_logged": False,
    "raw_token_copied": False,
    "raw_token_exported": False,
    "env_hash_expected": True,
    "env_hash_configured": True,
    "env_hash_only": True,
    "h1_header_constructed": False,
    "h1_header_sent": False,
    "approval_endpoint_called": False,
    "submit_endpoint_called": False,
    "preflight_endpoint_called": False,
    "order_endpoint_called": False,
    "order_window_opened": False,
    "trade_window_helper_called": False,
    "broker_mutation": False,
    "broker_order_created": False,
    "gate_status": "H1_BOUNDARY_PRESERVED",
    "source_stage": "16Q_h1_boundary_audit_checkpoint",
    "performed": False,
}

_DEMO_H1_BOUNDARY_CANARIES: list[dict[str, Any]] = [
    {"symbol": "SPY", "side": "BUY", "action": "BUY", "quantity": 10, "order_type": "MKT",
     "requested_action": "H1_APPROVE BUY 10 SPY MKT", "requires_h1": True},
    {"symbol": "VTI", "side": "BUY", "action": "BUY", "quantity": 5, "order_type": "LMT",
     "requested_action": "H1_APPROVE BUY 5 VTI LMT", "requires_h1": True},
    {"symbol": "BND", "side": "BUY", "action": "BUY", "quantity": 15, "order_type": "MKT",
     "requested_action": "H1_APPROVE BUY 15 BND MKT", "requires_h1": True},
    {"symbol": "VXUS", "side": "BUY", "action": "BUY", "quantity": 5, "order_type": "LMT",
     "requested_action": "H1_APPROVE BUY 5 VXUS LMT", "requires_h1": True},
    {"symbol": "GLD", "side": "BUY", "action": "BUY", "quantity": 3, "order_type": "MKT",
     "requested_action": "H1_APPROVE BUY 3 GLD MKT", "requires_h1": True},
]

_H1_BOUNDARY_BLOCKING_REASONS: list[str] = [
    "h1_boundary_intact_no_raw_token_read",
    "h1_boundary_intact_no_raw_token_path_opened",
    "h1_boundary_intact_hash_only_configured",
    "h1_boundary_intact_no_h1_header_constructed",
    "h1_boundary_intact_no_h1_header_sent",
    "h1_boundary_intact_no_approval_endpoint",
    "h1_boundary_intact_no_submit_endpoint",
    "h1_boundary_intact_no_trade_window_helper",
    "h1_boundary_intact_system_locked",
    "h1_boundary_intact_autonomy_level_1",
    "h1_boundary_intact_orders_disabled",
    "h1_boundary_intact_no_broker_mutation",
]

_PHASE16R_EXPORT_DIR = OPENCLAW_DIR / "level1-broker-mutation-firewall-audits"

_PHASE16R_REQUIRED_TAGS: tuple[str, ...] = (
    "phase16q_level1_h1_boundary_audit_checkpoint",
    "phase16p_level1_order_window_canary_negative_control_drill",
    "phase16o_level1_execution_gate_negative_control_drill",
    "phase16n_level1_readiness_chain_integrity_checkpoint",
    "phase16m_level1_execution_readiness_packet_drill",
)

_PHASE16R_DIAGNOSIS = {
    "ready": "level1_broker_mutation_firewall_audit_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "autonomy_not_level1": "autonomy_not_level1",
    "runtime_not_ready": "runtime_not_ready",
    "orders_enabled": "orders_enabled",
    "bridge_allow_orders_enabled": "bridge_allow_orders_enabled",
    "rules_enforced": "rules_enforced",
    "safety_unlocked": "safety_unlocked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "clean_cycles_mismatch": "clean_cycles_mismatch",
    "broker_mutation_firewall_not_intact": "broker_mutation_firewall_not_intact",
    "unknown": "unknown",
}

_PHASE16R_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "Only allowed writes are export/broker-mutation-firewall audit artifacts.",
    "This broker-mutation firewall audit proves all mutation paths remain blocked/unperformed and runtime stays paper/read-only/flat.",
]

_BROKER_MUTATION_CANARY_TEMPLATE: dict[str, Any] = {
    "blocked": True,
    "executable": False,
    "execution_authorized_now": False,
    "simulated_canary_only": True,
    "expected_result": "blocked",
    "order_endpoint_called": False,
    "preflight_endpoint_called": False,
    "approval_endpoint_called": False,
    "submit_endpoint_called": False,
    "mutation_endpoint_called": False,
    "broker_order_created": False,
    "broker_submission_performed": False,
    "broker_cancel_performed": False,
    "broker_modify_performed": False,
    "account_mutation_performed": False,
    "position_mutation_performed": False,
    "order_mutation_performed": False,
    "order_window_opened": False,
    "trade_window_helper_called": False,
    "h1_token_used": False,
    "h1_header_constructed": False,
    "h1_header_sent": False,
    "gate_status": "BROKER_MUTATION_FIREWALL_INTACT",
    "source_stage": "16R_broker_mutation_firewall_audit_checkpoint",
    "performed": False,
}

_DEMO_BROKER_MUTATION_CANARIES: list[dict[str, Any]] = [
    {"symbol": "SPY", "side": "BUY", "action": "BUY", "quantity": 10, "order_type": "MKT",
     "requested_action": "SUBMIT BUY 10 SPY MKT", "requires_mutation": True},
    {"symbol": "VTI", "side": "BUY", "action": "BUY", "quantity": 5, "order_type": "LMT",
     "requested_action": "SUBMIT BUY 5 VTI LMT", "requires_mutation": True},
    {"symbol": "BND", "side": "SELL", "action": "SELL", "quantity": 15, "order_type": "MKT",
     "requested_action": "SUBMIT SELL 15 BND MKT", "requires_mutation": True},
    {"symbol": "VXUS", "side": "BUY", "action": "BUY", "quantity": 5, "order_type": "LMT",
     "requested_action": "SUBMIT BUY 5 VXUS LMT", "requires_mutation": True},
    {"symbol": "GLD", "side": "SELL", "action": "SELL", "quantity": 3, "order_type": "MKT",
     "requested_action": "SUBMIT SELL 3 GLD MKT", "requires_mutation": True},
]

_BROKER_MUTATION_BLOCKING_REASONS: list[str] = [
    "broker_mutation_firewall_intact_no_order_endpoint",
    "broker_mutation_firewall_intact_no_preflight_endpoint",
    "broker_mutation_firewall_intact_no_approval_endpoint",
    "broker_mutation_firewall_intact_no_submit_endpoint",
    "broker_mutation_firewall_intact_no_mutation_endpoint",
    "broker_mutation_firewall_intact_no_broker_order_created",
    "broker_mutation_firewall_intact_no_broker_submission",
    "broker_mutation_firewall_intact_no_broker_cancel",
    "broker_mutation_firewall_intact_no_broker_modify",
    "broker_mutation_firewall_intact_no_account_mutation",
    "broker_mutation_firewall_intact_no_position_mutation",
    "broker_mutation_firewall_intact_no_order_mutation",
    "broker_mutation_firewall_intact_no_order_window",
    "broker_mutation_firewall_intact_no_trade_window_helper",
    "broker_mutation_firewall_intact_system_locked",
    "broker_mutation_firewall_intact_autonomy_level_1",
    "broker_mutation_firewall_intact_orders_disabled",
]

_PHASE16S_EXPORT_DIR = OPENCLAW_DIR / "level1-end-to-end-safety-invariant-checkpoints"

_PHASE16S_REQUIRED_TAGS = (
    "phase16r_level1_broker_mutation_firewall_audit_checkpoint",
    "phase16q_level1_h1_boundary_audit_checkpoint",
    "phase16p_level1_order_window_canary_negative_control_drill",
    "phase16o_level1_execution_gate_negative_control_drill",
    "phase16n_level1_readiness_chain_integrity_checkpoint",
)

_PHASE16S_DIAGNOSIS = {
    "ready": "level1_end_to_end_safety_invariant_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "autonomy_not_level1": "autonomy_not_level1",
    "runtime_not_ready": "runtime_not_ready",
    "orders_enabled": "orders_enabled",
    "bridge_allow_orders_enabled": "bridge_allow_orders_enabled",
    "rules_enforced": "rules_enforced",
    "system_unlocked": "system_unlocked",
    "guard_state_not_clean": "guard_state_not_clean",
    "positions_not_flat": "positions_not_flat",
    "monitor_alerts_active": "monitor_alerts_active",
    "endpoints_not_healthy": "endpoints_not_healthy",
    "doctor_not_acceptable": "doctor_not_acceptable",
    "kpi_not_acceptable": "kpi_not_acceptable",
    "policy_boundary_missing": "policy_boundary_missing",
    "clean_cycles_mismatch": "clean_cycles_mismatch",
    "safety_invariant_broken": "safety_invariant_broken",
    "unknown": "unknown",
}

_PHASE16S_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not restart bridge.",
    "This command did not reconnect automatically.",
    "This command did not repair guard-state.",
    "Only allowed writes are export/end-to-end-safety-invariant artifacts.",
    "This end-to-end safety invariant checkpoint proves all five safety phases (16N–16R) remain intact and Level 1 stays advisory/read-only.",
]

_PHASE16T_EXPORT_DIR = OPENCLAW_DIR / "level1-restart-persistence-safety-checkpoints"

_PHASE16T_REQUIRED_TAGS = (
    "phase16s_level1_end_to_end_safety_invariant_checkpoint",
)

_PHASE16T_DIAGNOSIS = {
    "ready": "level1_restart_persistence_safety_ok",
    "missing_required_tags": "missing_required_tags",
    "dirty_worktree": "dirty_worktree",
    "restart_failed": "restart_failed",
    "bridge_not_reachable_after_restart": "bridge_not_reachable_after_restart",
    "ibkr_not_connected_after_restart": "ibkr_not_connected_after_restart",
    "after_connected_not_true": "after_connected_not_true",
    "after_mode_not_paper": "after_mode_not_paper",
    "after_read_only_not_true": "after_read_only_not_true",
    "after_allow_orders_not_false": "after_allow_orders_not_false",
    "after_endpoints_not_ok": "after_endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "sixteen_s_invariant_not_ok": "sixteen_s_invariant_not_ok",
    "unknown": "unknown",
}

_PHASE16T_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "this command did not call trade-window helper in any mode.",
    "this command did not enable orders.",
    "this command did not change IBKR_ALLOW_ORDERS.",
    "this command did not change rules.enforced.",
    "this command did not unlock system_locked.",
    "this command did not change autonomy level.",
    "this command did not call any mutation endpoint.",
    "Only allowed external action: sudo systemctl restart ibkr-bridge.service.",
    "Only allowed writes are export/restart-persistence-safety artifacts.",
    "This restart-persistence checkpoint proves the complete Level 1 safety invariant survives an ibkr-bridge.service restart without enabling orders, using H1, opening an order window, or touching any broker mutation path.",
]

_PHASE16T_BRIDGE_SERVICE = "ibkr-bridge.service"

_PHASE16T_RESTART_TIMEOUT_SECS = 180

_PHASE16T_RECOVERY_TIMEOUT_SECS = 300

_PHASE16T_POLL_INTERVAL_SECS = 5

_PHASE16U_EXPORT_DIR = OPENCLAW_DIR / "level1-startup-autoconnect-resilience-checkpoints"

_PHASE16U_DIAGNOSIS = {
    "ready": "level1_startup_autoconnect_resilience_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "guard_state_not_clean": "guard_state_not_clean",
    "startup_autoconnect_config_not_found": "startup_autoconnect_config_not_found",
    "startup_autoconnect_retry_window_too_short": "startup_autoconnect_retry_window_too_short",
    "startup_autoconnect_attempts_too_low": "startup_autoconnect_attempts_too_low",
    "startup_autoconnect_not_local_connect": "startup_autoconnect_not_local_connect",
    "unknown": "unknown",
}

_PHASE16U_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "Only allowed writes are export/startup-autoconnect-resilience artifacts.",
    "This checkpoint proves bridge startup auto-connect resilience without restarting the bridge, using H1, opening an order window, or touching any broker mutation path.",
]

_PHASE16V_EXPORT_DIR = OPENCLAW_DIR / "level1-guard-state-rollover-resilience-checkpoints"

_PHASE16V_DIAGNOSIS = {
    "ready": "level1_guard_state_rollover_resilience_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "current_guard_state_not_clean": "current_guard_state_not_clean",
    "reconcile_dry_run_failed": "reconcile_dry_run_failed",
    "synthetic_stale_trade_date_case_failed": "synthetic_stale_trade_date_case_failed",
    "synthetic_false_trade_count_case_failed": "synthetic_false_trade_count_case_failed",
    "synthetic_clean_case_failed": "synthetic_clean_case_failed",
    "synthetic_blocked_repair_case_failed": "synthetic_blocked_repair_case_failed",
    "unknown": "unknown",
}

_PHASE16V_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "Only allowed writes are export/guard-state-rollover-resilience artifacts.",
    "This checkpoint proves guard-state rollover/reconciliation resilience at Level 1 without enabling orders, using H1, opening an order window, or touching any broker mutation path.",
    "Synthetic fixture tests use temp files only — never mutate ~/.openclaw/guard-state.json.",
]

_PHASE16W_EXPORT_DIR = OPENCLAW_DIR / "level1-scheduled-heartbeat-alerting-resilience-checkpoints"

_PHASE16W_DIAGNOSIS = {
    "ready": "level1_scheduled_heartbeat_alerting_resilience_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "heartbeat_missing": "heartbeat_missing",
    "heartbeat_stale": "heartbeat_stale",
    "scheduled_timer_missing": "scheduled_timer_missing",
    "scheduled_timer_not_enabled": "scheduled_timer_not_enabled",
    "synthetic_fresh_heartbeat_failed": "synthetic_fresh_heartbeat_case_failed",
    "synthetic_stale_heartbeat_failed": "synthetic_stale_heartbeat_case_failed",
    "synthetic_missing_timer_failed": "synthetic_missing_timer_case_failed",
    "synthetic_dry_run_alert_failed": "synthetic_dry_run_alert_case_failed",
    "synthetic_read_only_invariant_failed": "synthetic_read_only_invariant_case_failed",
    "unknown": "unknown",
}

_PHASE16W_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "Only allowed writes are export/scheduled-heartbeat-alerting-resilience artifacts.",
    "This checkpoint proves scheduled heartbeat/alerting resilience at Level 1 without enabling orders, using H1, opening an order window, or touching any broker mutation path.",
    "Synthetic fixture tests use temp files only — never mutate real heartbeat artifacts or systemd units.",
]

_PHASE16X_EXPORT_DIR = OPENCLAW_DIR / "level1-os-boundary-h1-isolation-checkpoints"

_PHASE16X_DIAGNOSIS = {
    "ready": "level1_os_boundary_h1_isolation_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "env_file_not_protected": "env_file_not_protected",
    "h1_raw_token_not_protected": "h1_raw_token_not_protected",
    "h1_hash_not_only_in_env": "h1_hash_not_only_in_env",
    "raw_h1_leak_detected": "raw_h1_leak_detected",
    "non_owner_write_not_denied": "non_owner_write_not_denied",
    "bridge_service_user_not_verified": "bridge_service_user_not_verified",
    "synthetic_env_write_denied_failed": "synthetic_env_write_denied_case_failed",
    "synthetic_rules_write_denied_failed": "synthetic_rules_write_denied_case_failed",
    "synthetic_guard_state_write_denied_failed": "synthetic_guard_state_write_denied_case_failed",
    "synthetic_h1_file_mode_failed": "synthetic_h1_file_mode_case_failed",
    "synthetic_raw_h1_leak_scan_failed": "synthetic_raw_h1_leak_scan_case_failed",
    "synthetic_concurrent_h1_isolation_failed": "synthetic_concurrent_h1_isolation_case_failed",
    "synthetic_read_only_invariant_failed": "synthetic_read_only_invariant_case_failed",
    "unknown": "unknown",
}

_PHASE16X_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read raw H1 token contents.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "This command did not mutate .env, rules.yaml, guard-state.json, or the raw H1 token file.",
    "Only allowed writes are export/os-boundary-h1-isolation artifacts.",
    "This checkpoint proves OS boundary and H1 isolation at Level 1 without reading H1 token contents, enabling orders, opening an order window, or touching any broker mutation path.",
    "Synthetic fixture tests use temp files only — never mutate real safety files or H1 tokens.",
]

_PHASE16Y_EXPORT_DIR = OPENCLAW_DIR / "level1-portable-tests-ci-readiness-checkpoints"

_PHASE16Y_DIAGNOSIS = {
    "ready": "level1_portable_tests_ci_readiness_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "pure_tests_not_discovered": "pure_tests_not_discovered",
    "host_acceptance_not_separated": "host_acceptance_not_separated",
    "pure_tests_home_not_isolated": "pure_tests_home_not_isolated",
    "pure_tests_real_openclaw_access": "pure_tests_real_openclaw_access",
    "pure_tests_h1_file_access": "pure_tests_h1_file_access",
    "pure_tests_ibkr_gateway_required": "pure_tests_ibkr_gateway_required",
    "pure_tests_systemd_required": "pure_tests_systemd_required",
    "no_ci_workflow_or_install_plan": "no_ci_workflow_or_install_plan",
    "ci_command_not_documented": "ci_command_not_documented",
    "fresh_clone_command_not_documented": "fresh_clone_command_not_documented",
    "synthetic_home_isolation_case_failed": "synthetic_home_isolation_case_failed",
    "synthetic_no_h1_file_access_case_failed": "synthetic_no_h1_file_access_case_failed",
    "synthetic_acceptance_marker_case_failed": "synthetic_acceptance_marker_case_failed",
    "synthetic_ci_workflow_case_failed": "synthetic_ci_workflow_case_failed",
    "synthetic_read_only_invariant_case_failed": "synthetic_read_only_invariant_case_failed",
    "unknown": "unknown",
}

_PHASE16Y_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "This command did not read ~/.openclaw from pure tests.",
    "This command never read the raw H1 token file from pure tests.",
    "Only allowed writes are export/portable-tests-ci-readiness artifacts.",
    "This checkpoint proves Level 1 portable tests and CI readiness without enabling orders, using H1, opening an order window, or touching any broker mutation path.",
    "Synthetic fixture tests use temp files only — never require real IBKR Gateway, systemd, ~/.openclaw, or H1 token.",
]

_PHASE16Z_EXPORT_DIR = OPENCLAW_DIR / "level1-fresh-clone-ci-workflow-checkpoints"

_PHASE16Z_DIAGNOSIS = {
    "ready": "level1_fresh_clone_ci_workflow_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "no_github_actions_workflow": "no_github_actions_workflow",
    "github_actions_workflow_invalid": "github_actions_workflow_invalid",
    "ci_command_not_exits_zero": "ci_command_not_exits_zero",
    "fresh_clone_command_not_exits_zero": "fresh_clone_command_not_exits_zero",
    "ci_acceptance_tests_not_excluded": "ci_acceptance_tests_not_excluded",
    "pure_tests_home_not_isolated": "pure_tests_home_not_isolated",
    "pure_tests_real_openclaw_access": "pure_tests_real_openclaw_access",
    "pure_tests_h1_file_access": "pure_tests_h1_file_access",
    "pure_tests_ibkr_gateway_required": "pure_tests_ibkr_gateway_required",
    "pure_tests_systemd_required": "pure_tests_systemd_required",
    "host_acceptance_tests_in_ci": "host_acceptance_tests_in_ci",
    "synthetic_workflow_parse_failed": "synthetic_workflow_parse_failed",
    "synthetic_marker_exclusion_failed": "synthetic_marker_exclusion_failed",
    "synthetic_temp_home_ci_failed": "synthetic_temp_home_ci_failed",
    "synthetic_fresh_clone_failed": "synthetic_fresh_clone_failed",
    "synthetic_no_real_openclaw_failed": "synthetic_no_real_openclaw_failed",
    "synthetic_no_h1_file_access_failed": "synthetic_no_h1_file_access_failed",
    "synthetic_read_only_invariant_failed": "synthetic_read_only_invariant_failed",
    "unknown": "unknown",
}

_PHASE16Z_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "This command did not read ~/.openclaw from pure tests.",
    "This command never read the raw H1 token file from pure tests.",
    "Only allowed writes are export/fresh-clone-ci-workflow artifacts.",
    "This checkpoint proves Level 1 fresh-clone CI workflow without enabling orders, using H1, opening an order window, or touching any broker mutation path.",
    "Synthetic fixture tests use temp files only — never require real IBKR Gateway, systemd, ~/.openclaw, or H1 token.",
]

_PHASE17A_EXPORT_DIR = OPENCLAW_DIR / "level1-strategy-v1-governance-checkpoints"

_PHASE17A_DIAGNOSIS = {
    "ready": "level1_strategy_v1_governance_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "strategy_doc_missing": "strategy_doc_missing",
    "risk_envelope_missing": "risk_envelope_missing",
    "no_trade_rules_missing": "no_trade_rules_missing",
    "advisory_boundary_missing": "advisory_boundary_missing",
    "anti_overfit_section_missing": "anti_overfit_section_missing",
    "bracket_requirement_missing": "bracket_requirement_missing",
    "strategy_version_missing": "strategy_version_missing",
    "allowed_instruments_missing": "allowed_instruments_missing",
    "excluded_instruments_missing": "excluded_instruments_missing",
    "signal_inputs_missing": "signal_inputs_missing",
    "data_quality_missing": "data_quality_missing",
    "sizing_rule_missing": "sizing_rule_missing",
    "daily_trade_limit_missing": "daily_trade_limit_missing",
    "daily_loss_limit_missing": "daily_loss_limit_missing",
    "stop_exit_policy_missing": "stop_exit_policy_missing",
    "review_checklist_missing": "review_checklist_missing",
    "broker_execution_boundary_missing": "broker_execution_boundary_missing",
    "synthetic_valid_strategy_doc_failed": "synthetic_valid_strategy_doc_failed",
    "synthetic_missing_risk_envelope_failed": "synthetic_missing_risk_envelope_failed",
    "synthetic_missing_no_trade_rules_failed": "synthetic_missing_no_trade_rules_failed",
    "synthetic_missing_advisory_boundary_failed": "synthetic_missing_advisory_boundary_failed",
    "synthetic_missing_anti_overfit_failed": "synthetic_missing_anti_overfit_failed",
    "synthetic_missing_bracket_requirement_failed": "synthetic_missing_bracket_requirement_failed",
    "synthetic_read_only_invariant_failed": "synthetic_read_only_invariant_failed",
    "unknown": "unknown",
}

_PHASE17A_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "This command did not read ~/.openclaw from pure tests.",
    "This command never read the raw H1 token file from pure tests.",
    "Only allowed writes are export/strategy-v1-governance artifacts.",
    "This checkpoint proves Level 1 strategy v1 governance without enabling orders, using H1, opening an order window, or touching any broker mutation path.",
    "Synthetic fixture tests use temp files only — never require real IBKR Gateway, systemd, ~/.openclaw, or H1 token.",
]

_PHASE17B_EXPORT_DIR = OPENCLAW_DIR / "level1-strategy-v1-proposal-packet-schema-checkpoints"

_PHASE17_REPO_ROOT = Path(__file__).resolve().parents[2]

_PROPOSAL_PACKET_DOC_PATH = _PHASE17_REPO_ROOT / "docs" / "proposal_packet_v1.md"

_PROPOSAL_PACKET_SCHEMA_PATH = _PHASE17_REPO_ROOT / "docs" / "proposal_packet_v1.schema.json"

_PHASE17B_DIAGNOSIS = {
    "ready": "level1_strategy_v1_proposal_packet_schema_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "proposal_packet_doc_missing": "proposal_packet_doc_missing",
    "proposal_packet_schema_missing": "proposal_packet_schema_missing",
    "strategy_v1_ref_not_required": "strategy_v1_ref_not_required",
    "proposal_id_not_required": "proposal_id_not_required",
    "timestamp_not_required": "timestamp_not_required",
    "instrument_not_required": "instrument_not_required",
    "allowed_instrument_check_not_required": "allowed_instrument_check_not_required",
    "signal_thesis_not_required": "signal_thesis_not_required",
    "signal_inputs_not_required": "signal_inputs_not_required",
    "data_quality_not_required": "data_quality_not_required",
    "no_trade_checklist_not_required": "no_trade_checklist_not_required",
    "risk_envelope_check_not_required": "risk_envelope_check_not_required",
    "sizing_not_required": "sizing_not_required",
    "daily_trade_count_not_required": "daily_trade_count_not_required",
    "daily_loss_not_required": "daily_loss_not_required",
    "stop_exit_not_required": "stop_exit_not_required",
    "bracket_simulation_not_required": "bracket_simulation_not_required",
    "advisory_boundary_not_required": "advisory_boundary_not_required",
    "broker_boundary_not_required": "broker_boundary_not_required",
    "human_review_not_required": "human_review_not_required",
    "rejection_reasons_not_required": "rejection_reasons_not_required",
    "evidence_hash_not_required": "evidence_hash_not_required",
    "synthetic_valid_packet_failed": "synthetic_valid_packet_failed",
    "synthetic_missing_strategy_ref_failed": "synthetic_missing_strategy_ref_failed",
    "synthetic_disallowed_instrument_failed": "synthetic_disallowed_instrument_failed",
    "synthetic_missing_data_quality_failed": "synthetic_missing_data_quality_failed",
    "synthetic_missing_no_trade_checklist_failed": "synthetic_missing_no_trade_checklist_failed",
    "synthetic_missing_risk_sizing_failed": "synthetic_missing_risk_sizing_failed",
    "synthetic_missing_stop_bracket_failed": "synthetic_missing_stop_bracket_failed",
    "synthetic_missing_advisory_boundary_failed": "synthetic_missing_advisory_boundary_failed",
    "synthetic_read_only_invariant_failed": "synthetic_read_only_invariant_failed",
    "unknown": "unknown",
}

_PHASE17B_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "This command did not read ~/.openclaw from pure tests.",
    "This command never read the raw H1 token file from pure tests.",
    "Only allowed writes are export/proposal-packet-schema artifacts.",
    "This checkpoint proves Level 1 proposal packet schema without enabling orders, using H1, opening an order window, or touching any broker mutation path.",
    "Synthetic fixture tests use temp files only — never require real IBKR Gateway, systemd, ~/.openclaw, or H1 token.",
]

_PHASE17C_EXPORT_DIR = OPENCLAW_DIR / "level1-strategy-v1-dry-run-proposal-generation-checkpoints"

_PHASE17C_DIAGNOSIS = {
    "ready": "level1_strategy_v1_dry_run_proposal_generation_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "governance_docs_missing": "governance_docs_missing",
    "synthetic_proposal_generation_failed": "synthetic_proposal_generation_failed",
    "synthetic_proposal_schema_validation_failed": "synthetic_proposal_schema_validation_failed",
    "synthetic_advisory_boundary_enforced_failed": "synthetic_advisory_boundary_enforced_failed",
    "synthetic_disallowed_instrument_generation_failed": "synthetic_disallowed_instrument_generation_failed",
    "synthetic_rejection_blocker_deterministic_failed": "synthetic_rejection_blocker_deterministic_failed",
    "synthetic_read_only_invariant_failed": "synthetic_read_only_invariant_failed",
    "unknown": "unknown",
}

_PHASE17C_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "This command did not read ~/.openclaw from pure tests.",
    "This command never read the raw H1 token file from pure tests.",
    "Only allowed writes are export/dry-run-proposal-generation artifacts.",
    "This checkpoint proves Level 1 dry-run proposal generation without enabling orders, using H1, opening an order window, or touching any broker mutation path.",
    "Synthetic fixture tests use temp files only — never require real IBKR Gateway, systemd, ~/.openclaw, or H1 token.",
    "All proposals generated are advisory-only and explicitly non-executable.",
]

_PHASE17D_EXPORT_DIR = OPENCLAW_DIR / "level1-proposal-review-rejection-dossier-checkpoints"

_PHASE17D_DIAGNOSIS = {
    "ready": "level1_proposal_review_rejection_dossier_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "governance_docs_missing": "governance_docs_missing",
    "reviewable_case_failed": "reviewable_case_failed",
    "invalid_schema_rejected_case_failed": "invalid_schema_rejected_case_failed",
    "disallowed_instrument_rejected_case_failed": "disallowed_instrument_rejected_case_failed",
    "data_quality_rejected_case_failed": "data_quality_rejected_case_failed",
    "no_trade_gate_rejected_case_failed": "no_trade_gate_rejected_case_failed",
    "missing_evidence_hash_rejected_case_failed": "missing_evidence_hash_rejected_case_failed",
    "read_only_invariant_case_failed": "read_only_invariant_case_failed",
    "deterministic_case_failed": "deterministic_case_failed",
    "fresh_clone_case_failed": "fresh_clone_case_failed",
    "unknown": "unknown",
}

_PHASE17D_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call /connect.",
    "This command did not call ibkr-trade-window.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "This command did not read ~/.openclaw from pure tests.",
    "This command never read the raw H1 token file from pure tests.",
    "Only allowed writes are export/dossier artifacts.",
    "This checkpoint reviews proposals without enabling orders, using H1, opening an order window, or touching any broker mutation path.",
    "Synthetic fixture tests use in-memory proposals only — never require real IBKR Gateway, systemd, ~/.openclaw, or H1 token.",
    "All dossiers produced are advisory-only and explicitly non-executable.",
]

_PHASE17E_EXPORT_DIR = OPENCLAW_DIR / "level1-human-review-decision-record-checkpoints"

_PHASE17E_DIAGNOSIS = {
    "ready": "level1_human_review_decision_record_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "governance_docs_missing": "governance_docs_missing",
    "accept_for_planning_case_failed": "accept_for_planning_case_failed",
    "rejected_dossier_accept_blocked_case_failed": "rejected_dossier_accept_blocked_case_failed",
    "missing_decision_pending_case_failed": "missing_decision_pending_case_failed",
    "explicit_reject_case_failed": "explicit_reject_case_failed",
    "explicit_defer_case_failed": "explicit_defer_case_failed",
    "missing_reviewer_fail_closed_case_failed": "missing_reviewer_fail_closed_case_failed",
    "missing_reason_fail_closed_case_failed": "missing_reason_fail_closed_case_failed",
    "proposal_hash_mismatch_case_failed": "proposal_hash_mismatch_case_failed",
    "dossier_hash_mismatch_case_failed": "dossier_hash_mismatch_case_failed",
    "accepted_non_executable_case_failed": "accepted_non_executable_case_failed",
    "deterministic_case_failed": "deterministic_case_failed",
    "read_only_invariant_case_failed": "read_only_invariant_case_failed",
    "fresh_clone_case_failed": "fresh_clone_case_failed",
    "unknown": "unknown",
}

_PHASE17E_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call /connect.",
    "This command did not call ibkr-trade-window.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "This command did not read ~/.openclaw from pure tests.",
    "This command never read the raw H1 token file from pure tests.",
    "Only allowed writes are export/decision-record artifacts.",
    "This checkpoint reviews dossiers and creates decision records without enabling orders, using H1, opening an order window, or touching any broker mutation path.",
    "Synthetic fixture tests use in-memory data only — never require real IBKR Gateway, systemd, ~/.openclaw, or H1 token.",
    "All decision records produced are advisory-only and explicitly non-executable.",
    "ACCEPTED_FOR_PLANNING means planning-only; it does not authorize broker execution, order placement, or H1 token usage.",
]

_PHASE17F_EXPORT_DIR = OPENCLAW_DIR / "level1-planning-only-order-plan-draft-checkpoints"

_PHASE17F_DIAGNOSIS = {
    "ready": "level1_planning_only_order_plan_draft_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "planning_draft_ready_case_failed": "planning_draft_ready_case_failed",
    "pending_review_blocked_case_failed": "pending_review_blocked_case_failed",
    "rejected_blocked_case_failed": "rejected_blocked_case_failed",
    "executable_false_case_failed": "executable_false_case_failed",
    "broker_authorized_false_case_failed": "broker_authorized_false_case_failed",
    "preflight_authorized_false_case_failed": "preflight_authorized_false_case_failed",
    "approval_authorized_false_case_failed": "approval_authorized_false_case_failed",
    "submission_authorized_false_case_failed": "submission_authorized_false_case_failed",
    "read_only_invariant_case_failed": "read_only_invariant_case_failed",
    "fresh_clone_case_failed": "fresh_clone_case_failed",
    "deterministic_case_failed": "deterministic_case_failed",
    "hash_mismatch_blocked_case_failed": "hash_mismatch_blocked_case_failed",
    "disallowed_instrument_blocked_case_failed": "disallowed_instrument_blocked_case_failed",
    "invalid_side_blocked_case_failed": "invalid_side_blocked_case_failed",
    "invalid_quantity_blocked_case_failed": "invalid_quantity_blocked_case_failed",
    "stop_below_entry_case_failed": "stop_below_entry_case_failed",
    "stop_quantity_match_case_failed": "stop_quantity_match_case_failed",
    "data_quality_fail_blocked_case_failed": "data_quality_fail_blocked_case_failed",
    "no_trade_fail_blocked_case_failed": "no_trade_fail_blocked_case_failed",
    "unknown": "unknown",
}

_PHASE17F_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call /connect.",
    "This command did not call ibkr-trade-window.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "This command did not read ~/.openclaw from pure tests.",
    "This command never read the raw H1 token file from pure tests.",
    "Only allowed writes are export/order-plan-draft artifacts.",
    "This checkpoint produces planning-only order-plan drafts from decision records without enabling orders, using H1, opening an order window, or touching any broker mutation path.",
    "Synthetic fixture tests use in-memory data only — never require real IBKR Gateway, systemd, ~/.openclaw, or H1 token.",
    "All order-plan drafts produced are advisory-only, non-executable, and non-authorized.",
    "PLANNING_DRAFT_READY means a plan draft exists for human review; it does not authorize broker execution, preflight, approval, or submission.",
]

_PHASE17G_EXPORT_DIR = OPENCLAW_DIR / "level1-planning-only-preflight-simulation-dossier-checkpoints"

_PHASE17G_DIAGNOSIS = {
    "ready": "level1_planning_only_preflight_simulation_dossier_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "simulation_ready_case_failed": "simulation_ready_case_failed",
    "blocked_plan_blocked_case_failed": "blocked_plan_blocked_case_failed",
    "executable_false_case_failed": "executable_false_case_failed",
    "broker_authorized_false_case_failed": "broker_authorized_false_case_failed",
    "preflight_authorized_false_case_failed": "preflight_authorized_false_case_failed",
    "approval_authorized_false_case_failed": "approval_authorized_false_case_failed",
    "submission_authorized_false_case_failed": "submission_authorized_false_case_failed",
    "broker_preflight_called_false_case_failed": "broker_preflight_called_false_case_failed",
    "hash_mismatch_blocked_case_failed": "hash_mismatch_blocked_case_failed",
    "disallowed_instrument_blocked_case_failed": "disallowed_instrument_blocked_case_failed",
    "invalid_side_blocked_case_failed": "invalid_side_blocked_case_failed",
    "invalid_quantity_blocked_case_failed": "invalid_quantity_blocked_case_failed",
    "stop_below_entry_case_failed": "stop_below_entry_case_failed",
    "stop_quantity_match_case_failed": "stop_quantity_match_case_failed",
    "data_quality_fail_blocked_case_failed": "data_quality_fail_blocked_case_failed",
    "no_trade_fail_blocked_case_failed": "no_trade_fail_blocked_case_failed",
    "deterministic_case_failed": "deterministic_case_failed",
    "read_only_invariant_case_failed": "read_only_invariant_case_failed",
    "fresh_clone_case_failed": "fresh_clone_case_failed",
    "full_chain_case_failed": "full_chain_case_failed",
    "unknown": "unknown",
}

_PHASE17G_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call /connect.",
    "This command did not call ibkr-trade-window.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "This command did not read ~/.openclaw from pure tests.",
    "This command never read the raw H1 token file from pure tests.",
    "Only allowed writes are export/simulated-preflight-dossier artifacts.",
    "This checkpoint simulates preflight checks locally from immutable evidence without calling any broker preflight endpoint, enabling orders, using H1, or opening an order window.",
    "Synthetic fixture tests use in-memory data only — never require real IBKR Gateway, systemd, ~/.openclaw, or H1 token.",
    "All simulated preflight dossiers produced are advisory-only, non-executable, and non-authorized.",
    "SIMULATION_READY means a simulated preflight passed local checks for human review; it does not authorize broker execution, preflight, approval, or submission.",
]

_PHASE17H_EXPORT_DIR = OPENCLAW_DIR / "level1-human-simulation-review-decision-record-checkpoints"

_PHASE17H_DIAGNOSIS = {
    "ready": "level1_human_simulation_review_decision_record_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "accept_case_failed": "accept_case_failed",
    "pending_missing_decision_failed": "pending_missing_decision_failed",
    "reject_case_failed": "reject_case_failed",
    "defer_case_failed": "defer_case_failed",
    "missing_reason_fail_closed_failed": "missing_reason_fail_closed_failed",
    "missing_reviewer_fail_closed_failed": "missing_reviewer_fail_closed_failed",
    "blocked_sim_accept_blocked_failed": "blocked_sim_accept_blocked_failed",
    "pending_input_accept_blocked_failed": "pending_input_accept_blocked_failed",
    "non_ready_sim_accept_blocked_failed": "non_ready_sim_accept_blocked_failed",
    "failed_gate_accept_blocked_failed": "failed_gate_accept_blocked_failed",
    "broker_preflight_called_accept_blocked_failed": "broker_preflight_called_accept_blocked_failed",
    "executable_true_accept_blocked_failed": "executable_true_accept_blocked_failed",
    "broker_authorized_true_accept_blocked_failed": "broker_authorized_true_accept_blocked_failed",
    "missing_proposal_hash_failed": "missing_proposal_hash_failed",
    "missing_dossier_hash_failed": "missing_dossier_hash_failed",
    "missing_decision_hash_failed": "missing_decision_hash_failed",
    "missing_order_plan_hash_failed": "missing_order_plan_hash_failed",
    "missing_simulation_hash_failed": "missing_simulation_hash_failed",
    "proposal_hash_mismatch_failed": "proposal_hash_mismatch_failed",
    "dossier_hash_mismatch_failed": "dossier_hash_mismatch_failed",
    "decision_hash_mismatch_failed": "decision_hash_mismatch_failed",
    "order_plan_hash_mismatch_failed": "order_plan_hash_mismatch_failed",
    "simulation_hash_mismatch_failed": "simulation_hash_mismatch_failed",
    "tampered_evidence_ref_failed": "tampered_evidence_ref_failed",
    "blocker_ordering_failed": "blocker_ordering_failed",
    "deterministic_failed": "deterministic_failed",
    "timestamp_independent_failed": "timestamp_independent_failed",
    "immutable_evidence_failed": "immutable_evidence_failed",
    "no_forbidden_endpoints_failed": "no_forbidden_endpoints_failed",
    "no_broker_identifiers_failed": "no_broker_identifiers_failed",
    "read_only_invariant_failed": "read_only_invariant_failed",
    "fresh_clone_failed": "fresh_clone_failed",
    "full_chain_non_executable_failed": "full_chain_non_executable_failed",
    "unknown": "unknown",
}

_PHASE17H_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call /connect.",
    "This command did not call ibkr-trade-window.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "This command did not read ~/.openclaw from pure tests.",
    "This command never read the raw H1 token file from pure tests.",
    "Only allowed writes are export/simulated-review-decision-record artifacts.",
    "This checkpoint produces human review decision records from simulated-preflight dossiers without calling any broker endpoint, enabling orders, using H1, or opening an order window.",
    "Synthetic fixture tests use in-memory data only — never require real IBKR Gateway, systemd, ~/.openclaw, or H1 token.",
    "All decision records produced are advisory-only, non-executable, and non-authorized.",
    "ACCEPTED_FOR_CANDIDATE_PACKAGING means candidate packaging only; it does not authorize broker preflight, execution, approval, or submission.",
    "CANDIDATE_PACKAGING_ONLY means only non-executable planning candidate packaging is permitted, not broker interaction.",
]

_PHASE17I_EXPORT_DIR = OPENCLAW_DIR / "level1-planning-only-candidate-package-checkpoints"

_PHASE17I_DIAGNOSIS = {
    "ready": "level1_planning_only_candidate_package_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "ready_package_case_failed": "ready_package_case_failed",
    "missing_review_decision_failed": "missing_review_decision_failed",
    "rejected_review_blocked_failed": "rejected_review_blocked_failed",
    "deferred_review_blocked_failed": "deferred_review_blocked_failed",
    "pending_review_blocked_failed": "pending_review_blocked_failed",
    "blocked_review_blocked_failed": "blocked_review_blocked_failed",
    "scope_not_candidate_failed": "scope_not_candidate_failed",
    "candidate_not_permitted_failed": "candidate_not_permitted_failed",
    "executable_true_blocked_failed": "executable_true_blocked_failed",
    "broker_authorized_true_blocked_failed": "broker_authorized_true_blocked_failed",
    "broker_preflight_called_true_blocked_failed": "broker_preflight_called_true_blocked_failed",
    "review_has_blockers_failed": "review_has_blockers_failed",
    "missing_proposal_hash_failed": "missing_proposal_hash_failed",
    "missing_dossier_hash_failed": "missing_dossier_hash_failed",
    "missing_decision_hash_failed": "missing_decision_hash_failed",
    "missing_order_plan_hash_failed": "missing_order_plan_hash_failed",
    "missing_simulation_hash_failed": "missing_simulation_hash_failed",
    "missing_review_hash_failed": "missing_review_hash_failed",
    "proposal_hash_mismatch_failed": "proposal_hash_mismatch_failed",
    "dossier_hash_mismatch_failed": "dossier_hash_mismatch_failed",
    "decision_hash_mismatch_failed": "decision_hash_mismatch_failed",
    "order_plan_hash_mismatch_failed": "order_plan_hash_mismatch_failed",
    "simulation_hash_mismatch_failed": "simulation_hash_mismatch_failed",
    "review_hash_mismatch_failed": "review_hash_mismatch_failed",
    "tampered_evidence_ref_failed": "tampered_evidence_ref_failed",
    "disallowed_instrument_failed": "disallowed_instrument_failed",
    "invalid_side_failed": "invalid_side_failed",
    "invalid_quantity_failed": "invalid_quantity_failed",
    "missing_stop_failed": "missing_stop_failed",
    "stop_quantity_mismatch_failed": "stop_quantity_mismatch_failed",
    "data_quality_fail_blocked_failed": "data_quality_fail_blocked_failed",
    "no_trade_fail_blocked_failed": "no_trade_fail_blocked_failed",
    "risk_fail_blocked_failed": "risk_fail_blocked_failed",
    "sizing_fail_blocked_failed": "sizing_fail_blocked_failed",
    "evidence_chain_fail_blocked_failed": "evidence_chain_fail_blocked_failed",
    "deterministic_failed": "deterministic_failed",
    "immutable_evidence_failed": "immutable_evidence_failed",
    "no_forbidden_endpoints_failed": "no_forbidden_endpoints_failed",
    "no_broker_identifiers_failed": "no_broker_identifiers_failed",
    "read_only_invariant_failed": "read_only_invariant_failed",
    "fresh_clone_failed": "fresh_clone_failed",
    "full_chain_failed": "full_chain_failed",
    "unknown": "unknown",
}

_PHASE17I_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call /connect.",
    "This command did not call ibkr-trade-window.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "This command did not read ~/.openclaw from pure tests.",
    "This command never read the raw H1 token file from pure tests.",
    "Only allowed writes are export/candidate-package artifacts.",
    "This checkpoint produces candidate packages for human inspection without calling any broker endpoint, enabling orders, using H1, or opening an order window.",
    "Synthetic fixture tests use in-memory data only — never require real IBKR Gateway, systemd, ~/.openclaw, or H1 token.",
    "All candidate packages produced are advisory-only, non-executable, and non-authorized.",
    "CANDIDATE_PACKAGE_READY means a planning-only candidate package is ready for human inspection; it does not authorize broker preflight, execution, approval, or submission.",
    "PLANNING_ONLY means no live market data, no broker interaction, and no execution capability.",
]

_PHASE17J_EXPORT_DIR = OPENCLAW_DIR / "level1-human-candidate-package-review-decision-records"

_PHASE17J_DIAGNOSIS = {
    "ready": "level1_human_candidate_package_review_decision_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "ready_accept_case_failed": "ready_accept_case_failed",
    "missing_decision_failed": "missing_decision_failed",
    "rejected_decision_failed": "rejected_decision_failed",
    "deferred_decision_failed": "deferred_decision_failed",
    "blocked_decision_failed": "blocked_decision_failed",
    "invalid_decision_failed": "invalid_decision_failed",
    "missing_reviewer_failed": "missing_reviewer_failed",
    "rejected_missing_reason_failed": "rejected_missing_reason_failed",
    "deferred_missing_reason_failed": "deferred_missing_reason_failed",
    "package_not_ready_failed": "package_not_ready_failed",
    "package_not_planning_only_failed": "package_not_planning_only_failed",
    "cpp_not_true_failed": "cpp_not_true_failed",
    "executable_true_failed": "executable_true_failed",
    "broker_authorized_true_failed": "broker_authorized_true_failed",
    "preflight_authorized_true_failed": "preflight_authorized_true_failed",
    "approval_authorized_true_failed": "approval_authorized_true_failed",
    "submission_authorized_true_failed": "submission_authorized_true_failed",
    "broker_preflight_called_true_failed": "broker_preflight_called_true_failed",
    "actual_preflight_completed_true_failed": "actual_preflight_completed_true_failed",
    "actual_order_created_true_failed": "actual_order_created_true_failed",
    "package_has_blockers_failed": "package_has_blockers_failed",
    "disallowed_instrument_failed": "disallowed_instrument_failed",
    "invalid_side_failed": "invalid_side_failed",
    "invalid_quantity_failed": "invalid_quantity_failed",
    "stop_above_entry_failed": "stop_above_entry_failed",
    "stop_quantity_mismatch_failed": "stop_quantity_mismatch_failed",
    "data_quality_failed": "data_quality_failed",
    "no_trade_failed": "no_trade_failed",
    "risk_failed": "risk_failed",
    "sizing_failed": "sizing_failed",
    "evidence_chain_failed": "evidence_chain_failed",
    "simulated_gate_failed": "simulated_gate_failed",
    "missing_proposal_hash_failed": "missing_proposal_hash_failed",
    "proposal_hash_mismatch_failed": "proposal_hash_mismatch_failed",
    "dossier_hash_mismatch_failed": "dossier_hash_mismatch_failed",
    "decision_hash_mismatch_failed": "decision_hash_mismatch_failed",
    "order_plan_hash_mismatch_failed": "order_plan_hash_mismatch_failed",
    "simulation_hash_mismatch_failed": "simulation_hash_mismatch_failed",
    "review_hash_mismatch_failed": "review_hash_mismatch_failed",
    "tampered_evidence_ref_failed": "tampered_evidence_ref_failed",
    "deterministic_failed": "deterministic_failed",
    "no_forbidden_endpoints_failed": "no_forbidden_endpoints_failed",
    "no_broker_identifiers_failed": "no_broker_identifiers_failed",
    "read_only_invariant_failed": "read_only_invariant_failed",
    "fresh_clone_failed": "fresh_clone_failed",
    "full_chain_failed": "full_chain_failed",
    "unknown": "unknown",
}

_PHASE17J_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call /connect.",
    "This command did not call ibkr-trade-window.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "This command did not read ~/.openclaw from pure tests.",
    "This command never read the raw H1 token file from pure tests.",
    "Only allowed writes are export/candidate-review-decision artifacts.",
    "This checkpoint reviews candidate packages without calling any broker endpoint, enabling orders, using H1, or opening an order window.",
    "Synthetic fixture tests use in-memory data only — never require real IBKR Gateway, systemd, ~/.openclaw, or H1 token.",
    "All review decision records produced are advisory-only, non-executable, and non-authorized.",
    "ACCEPTED_FOR_PREFLIGHT_REQUEST_DRAFTING means a human reviewer authorizes only drafting a non-executable guarded-preflight request; it does not authorize broker preflight, execution, approval, or submission.",
    "PREFLIGHT_REQUEST_DRAFTING_ONLY means no live market data, no broker interaction, and no execution capability.",
]

_DISALLOWED_IBKR_SYMBOLS: set = {
    "TSLA", "GME", "AMC", "BBBY", "MARA", "RIOT", "COIN",
    "SPY", "QQQ", "IWM", "DIA",  # broad-market ETFs — for strategy-v1 only allowed large-cap stocks
}

_PHASE17K_EXPORT_DIR = OPENCLAW_DIR / "level1-guarded-preflight-request-draft-checkpoints"

_PHASE17K_DIAGNOSIS = {
    "ready": "level1_guarded_preflight_request_draft_ok",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "ready_draft_case_failed": "ready_draft_case_failed",
    "missing_review_failed": "missing_review_failed",
    "rejected_review_failed": "rejected_review_failed",
    "deferred_review_failed": "deferred_review_failed",
    "blocked_review_failed": "blocked_review_failed",
    "review_not_accepted_failed": "review_not_accepted_failed",
    "scope_not_preflight_drafting_failed": "scope_not_preflight_drafting_failed",
    "drafting_not_permitted_failed": "drafting_not_permitted_failed",
    "package_not_planning_only_failed": "package_not_planning_only_failed",
    "executable_true_failed": "executable_true_failed",
    "broker_authorized_true_failed": "broker_authorized_true_failed",
    "preflight_authorized_true_failed": "preflight_authorized_true_failed",
    "approval_authorized_true_failed": "approval_authorized_true_failed",
    "submission_authorized_true_failed": "submission_authorized_true_failed",
    "broker_preflight_called_true_failed": "broker_preflight_called_true_failed",
    "actual_preflight_completed_true_failed": "actual_preflight_completed_true_failed",
    "actual_order_created_true_failed": "actual_order_created_true_failed",
    "review_has_blockers_failed": "review_has_blockers_failed",
    "missing_proposal_hash_failed": "missing_proposal_hash_failed",
    "missing_dossier_hash_failed": "missing_dossier_hash_failed",
    "missing_decision_hash_failed": "missing_decision_hash_failed",
    "missing_order_plan_hash_failed": "missing_order_plan_hash_failed",
    "missing_simulation_hash_failed": "missing_simulation_hash_failed",
    "missing_simulation_review_hash_failed": "missing_simulation_review_hash_failed",
    "missing_candidate_package_hash_failed": "missing_candidate_package_hash_failed",
    "missing_candidate_review_hash_failed": "missing_candidate_review_hash_failed",
    "hash_mismatch_failed": "hash_mismatch_failed",
    "tampered_evidence_ref_failed": "tampered_evidence_ref_failed",
    "deterministic_failed": "deterministic_failed",
    "no_forbidden_endpoints_failed": "no_forbidden_endpoints_failed",
    "no_broker_identifiers_failed": "no_broker_identifiers_failed",
    "read_only_invariant_failed": "read_only_invariant_failed",
    "fresh_clone_failed": "fresh_clone_failed",
    "full_chain_failed": "full_chain_failed",
    "unknown": "unknown",
}

_PHASE17K_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call /connect.",
    "This command did not call ibkr-trade-window.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "This command did not read ~/.openclaw from pure tests.",
    "This command never read the raw H1 token file from pure tests.",
    "Only allowed writes are export/guarded-preflight-request-draft artifacts.",
    "This checkpoint creates preflight request drafts without calling any broker endpoint, enabling orders, using H1, or opening an order window.",
    "Synthetic fixture tests use in-memory data only — never require real IBKR Gateway, systemd, ~/.openclaw, or H1 token.",
    "All preflight request drafts produced are advisory-only, non-executable, and non-authorized.",
    "PREFLIGHT_REQUEST_DRAFT_READY means a draft describing a future guarded broker-preflight request has been produced; it does not authorize broker preflight, execution, approval, or submission.",
    "PREFLIGHT_REQUEST_DRAFTING_ONLY means no live market data, no broker interaction, and no execution capability.",
    "The request body draft is explicitly marked DRAFT, PLANNING_ONLY, NON_EXECUTABLE, and NOT_SENT.",
    "The request headers draft must never contain H1 token or authorization secret.",
    "This draft must never be directly dispatched by any Phase 17K function.",
]

_PHASE17L_EXPORT_DIR = OPENCLAW_DIR / "level1-phase17-chain-closure-checkpoints"

_PHASE17L_DIAGNOSIS = {
    "ready": "phase17_chain_closed",
    "git_worktree_dirty": "git_worktree_dirty",
    "bridge_unreachable": "bridge_unreachable",
    "runtime_not_connected": "runtime_not_connected",
    "mode_not_paper": "mode_not_paper",
    "read_only_not_true": "read_only_not_true",
    "allow_orders_not_false": "allow_orders_not_false",
    "endpoints_not_ok": "endpoints_not_ok",
    "positions_not_flat": "positions_not_flat",
    "guard_state_not_clean": "guard_state_not_clean",
    "kpi_not_hold_system_locked": "kpi_not_hold_system_locked",
    "ready_closure_case_failed": "ready_closure_case_failed",
    "missing_draft_failed": "missing_draft_failed",
    "draft_not_ready_failed": "draft_not_ready_failed",
    "draft_sent_failed": "draft_sent_failed",
    "executable_true_failed": "executable_true_failed",
    "authorization_flags_failed": "authorization_flags_failed",
    "preflight_called_failed": "preflight_called_failed",
    "order_created_failed": "order_created_failed",
    "h1_accessed_failed": "h1_accessed_failed",
    "evidence_hashes_missing_failed": "evidence_hashes_missing_failed",
    "evidence_hashes_mismatch_failed": "evidence_hashes_mismatch_failed",
    "governance_missing_failed": "governance_missing_failed",
    "schema_missing_failed": "schema_missing_failed",
    "deterministic_failed": "deterministic_failed",
    "immutable_refs_failed": "immutable_refs_failed",
    "no_forbidden_endpoints_failed": "no_forbidden_endpoints_failed",
    "no_broker_identifiers_failed": "no_broker_identifiers_failed",
    "read_only_invariant_failed": "read_only_invariant_failed",
    "fresh_clone_failed": "fresh_clone_failed",
    "full_chain_failed": "full_chain_failed",
    "unknown": "unknown",
}

_PHASE17L_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call /connect.",
    "This command did not call ibkr-trade-window.",
    "This command did not call any broker mutation endpoint.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not cancel/modify orders.",
    "This command did not mutate account state.",
    "This command did not mutate position state.",
    "This command did not open an order window.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not send X-H1-Token header.",
    "This command did not call /usr/local/sbin/ibkr-trade-window.",
    "This command did not call trade-window helper in any mode.",
    "This command did not enable orders.",
    "This command did not change IBKR_ALLOW_ORDERS.",
    "This command did not change rules.enforced.",
    "This command did not unlock system_locked.",
    "This command did not change autonomy level.",
    "This command did not call any mutation endpoint.",
    "This command did not read ~/.openclaw from pure tests.",
    "This command never read the raw H1 token file from pure tests.",
    "Only allowed writes are export/chain-closure artifacts.",
    "This checkpoint closes the Phase 17 evidence chain without calling any broker endpoint, enabling orders, using H1, or opening an order window.",
    "Synthetic fixture tests use in-memory data only — never require real IBKR Gateway, systemd, ~/.openclaw, or H1 token.",
    "All closure records produced are archival-only, non-executable, and non-authorized.",
    "PHASE17_CLOSED means the complete 17A–17K chain is present, consistent, non-executable, and safe to archive.",
    "This closure does not authorize any Phase 18 activity.",
    "The next phase boundary is PHASE18_RESEARCH_GOVERNANCE.",
]

_ENV_PATH = BRIDGE_DIR / ".env"

_H1_TOKEN_PATH = Path("/etc/ibkr-bridge/h1_token")

_GUARD_STATE_PATH = OPENCLAW_DIR / "guard-state.json"

_RULES_PATH = BRIDGE_DIR / "rules" / "paper-trading-rules.yaml"

_CI_WORKFLOW_PATH = BRIDGE_DIR / ".github" / "workflows" / "ci.yml"

_CI_ALT_WORKFLOW_PATHS = [
    BRIDGE_DIR / ".github" / "workflows" / "test.yml",
    BRIDGE_DIR / ".github" / "workflows" / "python-ci.yml",
]

_CI_SCRIPT_PATH = BRIDGE_DIR / "scripts" / "run-ci-local"

_STRATEGY_V1_PATH = BRIDGE_DIR / "docs" / "strategy_v1.md"

_PHASE18A_REPO_ROOT = Path(__file__).resolve().parents[2]

_PHASE18A_PROPOSALS_DIR = _PHASE18A_REPO_ROOT / "docs" / "strategy-proposals"

_PHASE18A_PROPOSAL_DOC = _PHASE18A_PROPOSALS_DIR / "MSTR_BTC_RESEARCH_PROPOSAL_v0_1.md"

_PHASE18A_DATA_REQ_DOC = _PHASE18A_PROPOSALS_DIR / "MSTR_BTC_DATA_REQUIREMENTS_v0_1.md"

_PHASE18A_MANIFEST_PATH = _PHASE18A_PROPOSALS_DIR / "mstr_btc_research_v0_1.manifest.json"

_PHASE18A_STRATEGY_V1_PATH = _PHASE18A_REPO_ROOT / "docs" / "strategy_v1.md"

_PHASE18A_STRATEGY_MD_PATH = _PHASE18A_REPO_ROOT / "docs" / "STRATEGY.md"

_PHASE18A_EXPORT_DIR = OPENCLAW_DIR / "level1-mstr-btc-research-proposal-governance-checkpoints"

_PHASE18A_DIAGNOSIS = {
    "ready": "phase18a_research_proposal_governance_ok",
    "proposal_doc_missing": "proposal_doc_missing",
    "data_requirements_doc_missing": "data_requirements_doc_missing",
    "manifest_missing": "manifest_missing",
    "manifest_invalid_json": "manifest_invalid_json",
    "manifest_field_missing": "manifest_field_missing",
    "manifest_field_invalid": "manifest_field_invalid",
    "proposal_doc_sha256_mismatch": "proposal_doc_sha256_mismatch",
    "data_requirements_doc_sha256_mismatch": "data_requirements_doc_sha256_mismatch",
    "deterministic_manifest_hash_mismatch": "deterministic_manifest_hash_mismatch",
    "execution_scope_not_none": "execution_scope_not_none",
    "allowlist_change_true": "allowlist_change_true",
    "replaces_strategy_v1_true": "replaces_strategy_v1_true",
    "canonical_strategy_unchanged_false": "canonical_strategy_unchanged_false",
    "research_only_not_true": "research_only_not_true",
    "autonomy_level_not_1": "autonomy_level_not_1",
    "strategy_v1_modified": "strategy_v1_modified",
    "strategy_md_modified": "strategy_md_modified",
    "unknown": "unknown",
}

_PHASE18A_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not call /order.",
    "This command did not call /order/preflight.",
    "This command did not call /order/approve.",
    "This command did not call /order/submit.",
    "This command did not call any broker mutation endpoint.",
    "This command did not call /connect.",
    "This command did not call ibkr-trade-window.",
    "This command did not create broker orders.",
    "This command did not submit orders.",
    "This command did not read/use H1 token.",
    "This command did not construct X-H1-Token header.",
    "This command did not read H1 token.",
    "This command did not modify .env, paper-trading-rules.yaml, or guard-state.json.",
    "This command did not enable IBKR_ALLOW_ORDERS or rules.enforced.",
    "This command did not access any broker, network, or data provider.",
    "This command reads only repository-relative Phase 18A documents.",
    "This command never modifies files (export is opt-in with --export flag).",
    "This checkpoint is documentation governance only — no execution scope, no allowlist change, no broker mutation.",
    "All synthetic fixtures use in-memory data only.",
]

_PHASE18B_DIAGNOSIS = {
    "ready": "phase18b_data_schema_provider_governance_ok",
    "checkpoint_failed": "checkpoint_failed",
    "internal_error": "internal_error",
    "unknown": "unknown",
}

_PHASE18B_GOVERNANCE_DIR = Path(__file__).resolve().parents[2] / "docs" / "strategy-proposals" / "data-governance"

_PHASE18B_PHASE18A_MANIFEST = Path(__file__).resolve().parents[2] / "docs" / "strategy-proposals" / "mstr_btc_research_v0_1.manifest.json"

_PHASE18B_CANONICAL_STRATEGY = Path(__file__).resolve().parents[2] / "docs" / "STRATEGY.md"

_PHASE18B_GOVERNED_FILES = [
    ("EQUITY_BAR_SCHEMA_v0_1.json", _PHASE18B_GOVERNANCE_DIR / "EQUITY_BAR_SCHEMA_v0_1.json"),
    ("BTC_SPOT_BAR_SCHEMA_v0_1.json", _PHASE18B_GOVERNANCE_DIR / "BTC_SPOT_BAR_SCHEMA_v0_1.json"),
    ("CORPORATE_EVENT_SCHEMA_v0_1.json", _PHASE18B_GOVERNANCE_DIR / "CORPORATE_EVENT_SCHEMA_v0_1.json"),
    ("OPTION_CHAIN_SNAPSHOT_SCHEMA_v0_1.json", _PHASE18B_GOVERNANCE_DIR / "OPTION_CHAIN_SNAPSHOT_SCHEMA_v0_1.json"),
    ("DATASET_MANIFEST_SCHEMA_v0_1.json", _PHASE18B_GOVERNANCE_DIR / "DATASET_MANIFEST_SCHEMA_v0_1.json"),
    ("MSTR_BTC_PROVIDER_GOVERNANCE_v0_1.json", _PHASE18B_GOVERNANCE_DIR / "MSTR_BTC_PROVIDER_GOVERNANCE_v0_1.json"),
    ("MSTR_BTC_DATA_QUALITY_POLICY_v0_1.json", _PHASE18B_GOVERNANCE_DIR / "MSTR_BTC_DATA_QUALITY_POLICY_v0_1.json"),
]

_PHASE18B_EXPECTED_ROLES = [
    "EQUITY_BARS_PRIMARY", "EQUITY_BARS_SECONDARY",
    "BTC_SPOT_PRIMARY", "BTC_SPOT_SECONDARY",
    "CORPORATE_EVENTS_PRIMARY", "CORPORATE_EVENTS_SECONDARY",
    "OPTION_SNAPSHOTS_PRIMARY", "OPTION_SNAPSHOTS_SECONDARY",
    "MARKET_CALENDAR_REFERENCE", "CORPORATE_ACTION_REFERENCE",
]

_PHASE18B_QUALITY_OUTCOMES = ["ACCEPT", "ACCEPT_WITH_WARNING", "QUARANTINE", "REJECT", "NO_TRADE"]

_PHASE18B_QUALITY_SCENARIOS = [
    "missing_records", "stale_records", "duplicate_records",
    "conflicting_records", "out_of_order_records", "future_dated_records",
    "revised_records", "malformed_timestamps", "invalid_prices",
    "invalid_volumes", "incomplete_bars", "adjustment_mismatches",
    "provider_disagreement", "venue_disagreement", "missing_corporate_events",
    "ambiguous_event_availability", "invalid_option_markets",
    "missing_point_in_time_option_snapshots", "look_ahead_contamination",
    "cross_track_contamination", "schema_version_mismatch",
    "manifest_hash_mismatch", "source_license_uncertainty",
]

_PHASE18B_NON_ACTIONS = [
    "no provider selected", "no credentials created", "no network access",
    "no data collected", "no ingestion runtime", "no database",
    "no scheduler", "no backtest", "no feature generation",
    "no label generation", "no model training", "no forecast",
    "no candidate generation", "no options selection", "no broker access",
    "no H1 access", "no allowlist change", "no rules change",
    "no Strategy v1 replacement", "no execution authority",
]

_PHASE18B_CREDENTIAL_FORBIDDEN = [
    "api_key", "apikey", "api_secret", "passwor", "secret_key",
    "access_token", "bearer_token",
]

_PHASE18B_COMMON_FIELDS = [
    "schema_version", "record_id", "raw_record_hash", "provider_role_id",
    "provider_record_id", "instrument_id", "asset_class", "research_track",
    "execution_eligible", "event_timestamp_utc", "source_timestamp_utc",
    "ingestion_timestamp_utc", "available_at_utc", "revision_number",
    "is_final", "data_quality_state",
]

_PHASE18R1_DIAGNOSIS = {
    "ready": "phase18r1_model_routing_governance_ok",
    "checkpoint_failed": "checkpoint_failed",
    "internal_error": "internal_error",
    "unknown": "unknown",
}

_PHASE18R1_MODEL_ROUTING_DIR = Path(__file__).resolve().parents[2] / "docs" / "model-routing"

_PHASE18R1_PHASE18B_MANIFEST = Path(__file__).resolve().parents[2] / "docs" / "strategy-proposals" / "data-governance" / "mstr_btc_data_governance_v0_1.manifest.json"

_PHASE18R1_PHASE18A_MANIFEST = Path(__file__).resolve().parents[2] / "docs" / "strategy-proposals" / "mstr_btc_research_v0_1.manifest.json"

_PHASE18R1_CANONICAL_STRATEGY = Path(__file__).resolve().parents[2] / "docs" / "STRATEGY.md"

_PHASE18R1_GOVERNED_FILES = [
    ("MODEL_CATALOG_v0_1.json", _PHASE18R1_MODEL_ROUTING_DIR / "MODEL_CATALOG_v0_1.json"),
    ("MODEL_ROUTING_POLICY_v0_1.json", _PHASE18R1_MODEL_ROUTING_DIR / "MODEL_ROUTING_POLICY_v0_1.json"),
    ("MODEL_ROUTING_DECISION_SCHEMA_v0_1.json", _PHASE18R1_MODEL_ROUTING_DIR / "MODEL_ROUTING_DECISION_SCHEMA_v0_1.json"),
    ("MODEL_ROUTING_EVALUATION_PROTOCOL_v0_1.md", _PHASE18R1_MODEL_ROUTING_DIR / "MODEL_ROUTING_EVALUATION_PROTOCOL_v0_1.md"),
    ("model_routing.py", Path(__file__).resolve().parents[2] / "model_routing.py"),
]

_PHASE18R1_EXPECTED_ROLE_ASSIGNMENTS = {
    "gpt-5.5": ["HERMES_DEFAULT"],
    "gpt-5.6-sol": ["HERMES_ESCALATION"],
    "deepseek-v4-pro": ["OC_DEFAULT"],
    "kimi-k3": ["OC_ESCALATION"],
}

_PHASE18R1_AUTH_FLAGS = [
    "network_access_authorized", "credentials_authorized",
    "collection_authorized", "ingestion_authorized",
    "storage_runtime_authorized", "scheduler_authorized",
    "backtest_authorized", "modeling_authorized",
    "forecasting_authorized", "candidate_generation_authorized",
    "execution_authorized", "allowlist_change",
    "rules_change", "broker_change", "guard_change",
    "runtime_invocation_authorized", "provider_integration_authorized",
    "broker_mutation_authorized", "trading_execution_authorized",
]

_PHASE18R1_REQUIRED_LABELS = [
    "PHASE18R1_MODEL_ROUTING_GOVERNANCE_READY",
    "ROUTING_CONTRACT_READY",
    "R0_ROUTING_READINESS",
    "LEVEL1",
    "ADVISORY_ONLY",
    "HUMAN_FINAL_AUTHORITY",
    "DRY_RUN_ONLY",
    "NO_MODEL_INVOCATION",
    "NO_PROVIDER_INTEGRATION",
    "NO_CREDENTIALS",
    "NO_NETWORK_ACCESS",
    "NO_BROKER_MUTATION",
    "NO_TRADING_EXECUTION",
    "TRADING_AUTONOMY_UNCHANGED",
    "HERMES_DEFAULT_GPT_5_5",
    "HERMES_ESCALATION_GPT_5_6_SOL",
    "OC_DEFAULT_DEEPSEEK_V4_PRO",
    "OC_ESCALATION_KIMI_K3",
    "FAIL_CLOSED_ROUTING",
    "PHASE18B_UNCHANGED",
    "STRATEGY_V1_UNCHANGED",
    "PHASE18R2_NOT_STARTED",
    "PHASE18C_NOT_STARTED",
]

_PHASE18R2_DIAGNOSIS = {
    "ready": "phase18r2_openclaw_routing_adapter_ready",
    "pending": "phase18r2_pending_input_bindings_incomplete",
    "blocked": "phase18r2_blocked",
    "checkpoint_failed": "checkpoint_failed",
    "internal_error": "internal_error",
}

_PHASE18R2_ADAPTER_DIR = Path(__file__).resolve().parents[2] / "docs" / "model-routing"

_PHASE18R2_R1_MANIFEST = Path(__file__).resolve().parents[2] / "docs" / "model-routing" / "model_routing_governance_v0_1.manifest.json"

_PHASE18R2_B_MANIFEST = Path(__file__).resolve().parents[2] / "docs" / "strategy-proposals" / "data-governance" / "mstr_btc_data_governance_v0_1.manifest.json"

_PHASE18R2_STRATEGY = Path(__file__).resolve().parents[2] / "docs" / "STRATEGY.md"

_PHASE18R2_GOVERNED_FILES = [
    ("OPENCLAW_ROUTING_BINDINGS_v0_1.json", _PHASE18R2_ADAPTER_DIR / "OPENCLAW_ROUTING_BINDINGS_v0_1.json"),
    ("OPENCLAW_ROUTING_ADAPTER_POLICY_v0_1.json", _PHASE18R2_ADAPTER_DIR / "OPENCLAW_ROUTING_ADAPTER_POLICY_v0_1.json"),
    ("OPENCLAW_ROUTING_ADAPTER_DECISION_SCHEMA_v0_1.json", _PHASE18R2_ADAPTER_DIR / "OPENCLAW_ROUTING_ADAPTER_DECISION_SCHEMA_v0_1.json"),
    ("OPENCLAW_ROUTING_ACTIVATION_PROTOCOL_v0_1.md", _PHASE18R2_ADAPTER_DIR / "OPENCLAW_ROUTING_ACTIVATION_PROTOCOL_v0_1.md"),
    ("openclaw_routing_adapter.py", Path(__file__).resolve().parents[2] / "openclaw_routing_adapter.py"),
]

_PHASE18R2_PENDING_INPUT_LABELS = [
    "PHASE18R2_OPENCLAW_ROUTING_ADAPTER_PENDING_INPUT",
    "PENDING_INPUT",
    "A0_ADAPTER_READINESS",
    "LEVEL1",
    "ADVISORY_ONLY",
    "HUMAN_FINAL_AUTHORITY",
    "SHADOW_ONLY",
    "LIVE_ROUTING_UNCHANGED",
    "BINDINGS_INCOMPLETE",
    "NO_CROSS_TRANSPORT_FALLBACK",
    "NO_SILENT_MODEL_SUBSTITUTION",
    "NO_DIRECT_PROVIDER_INTEGRATION",
    "NO_DIRECT_CREDENTIAL_ACCESS",
    "NO_DIRECT_NETWORK_ACCESS",
    "NO_DIRECT_MODEL_INVOCATION",
    "NO_BROKER_MUTATION",
    "NO_TRADING_EXECUTION",
    "TRADING_AUTONOMY_UNCHANGED",
    "FAIL_CLOSED_ADAPTER",
    "PHASE18R1_UNCHANGED",
    "PHASE18B_UNCHANGED",
    "STRATEGY_V1_UNCHANGED",
    "PHASE18C_NOT_STARTED",
]

_PHASE18R2_READY_LABELS = [
    "PHASE18R2_OPENCLAW_ROUTING_ADAPTER_READY",
    "ADAPTER_READY_FOR_MANUAL_ACTIVATION",
    "A0_ADAPTER_READINESS",
    "LEVEL1",
    "ADVISORY_ONLY",
    "HUMAN_FINAL_AUTHORITY",
    "SHADOW_ONLY",
    "LIVE_ROUTING_UNCHANGED",
    "BINDINGS_COMPLETE",
    "BOUND_BINDING_COUNT_3",
    "HERMES_DEFAULT_CODEX_GPT_5_5_BOUND",
    "HERMES_ESCALATION_CODEX_GPT_5_6_SOL_BOUND",
    "OC_DEFAULT_OPENCODE_DEEPSEEK_V4_PRO_BOUND",
    "OC_ESCALATION_ROLE_RETIRED",
    "NO_CROSS_TRANSPORT_FALLBACK",
    "NO_SILENT_MODEL_SUBSTITUTION",
    "NO_DIRECT_PROVIDER_INTEGRATION",
    "NO_DIRECT_CREDENTIAL_ACCESS",
    "NO_DIRECT_NETWORK_ACCESS",
    "NO_DIRECT_MODEL_INVOCATION",
    "NO_BROKER_MUTATION",
    "NO_TRADING_EXECUTION",
    "TRADING_AUTONOMY_UNCHANGED",
    "FAIL_CLOSED_ADAPTER",
    "PHASE18R1_UNCHANGED",
    "PHASE18B_UNCHANGED",
    "STRATEGY_V1_UNCHANGED",
    "PHASE18C_NOT_STARTED",
]


def _fetch(endpoint: str) -> tuple[int, Any]:
    url = f"{BRIDGE_URL}{endpoint}"
    try:
        r = urllib.request.urlopen(url, timeout=5)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(body) if body else {}
        except Exception:
            return e.code, {"_error": body[:200]}
    except Exception as e:
        return 0, {"_error": str(e)}


def _get_git_timeline() -> dict:
    """Collect git branch, current commit, and recent tags."""
    import subprocess as _sp
    repo = Path(__file__).resolve().parents[2]
    try:
        branch = _sp.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=repo
        , encoding="utf-8").stdout.strip()
    except Exception:
        branch = "?"
    try:
        commit = _sp.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=repo
        , encoding="utf-8").stdout.strip()
    except Exception:
        commit = "?"
    try:
        tags_out = _sp.run(
            ["git", "tag", "--sort=-creatordate"],
            capture_output=True, text=True, timeout=5, cwd=repo
        , encoding="utf-8").stdout.strip().splitlines()
        recent_tags = tags_out[:20] if tags_out else []
    except Exception:
        recent_tags = []
    return {
        "branch": branch,
        "commit": commit,
        "tag_count": len(recent_tags),
        "recent_tags": recent_tags,
    }


def _git_metadata(repo_path: Path) -> dict:
    """Return branch, short commit, and latest tag from git.

    Uses bounded subprocess timeouts so KPI never hangs on git.
    """
    import subprocess as _sp
    _GIT_TIMEOUT = 3  # seconds — git should be sub-second locally
    result = {"branch": "?", "commit_short": "?", "tag": "?"}
    try:
        p = _sp.run(["git", "-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"],
                     capture_output=True, text=True, timeout=_GIT_TIMEOUT, encoding="utf-8")
        result["branch"] = p.stdout.strip()
    except Exception:
        pass
    try:
        p = _sp.run(["git", "-C", str(repo_path), "rev-parse", "--short", "HEAD"],
                     capture_output=True, text=True, timeout=_GIT_TIMEOUT, encoding="utf-8")
        result["commit_short"] = p.stdout.strip()
    except Exception:
        pass
    try:
        p = _sp.run(["git", "-C", str(repo_path), "describe", "--tags", "--abbrev=0"],
                     capture_output=True, text=True, timeout=_GIT_TIMEOUT, encoding="utf-8")
        result["tag"] = p.stdout.strip() or "none"
    except Exception:
        pass
    return result


def _read_env_safety(env_path: Path) -> dict:
    """Read IBKR_ALLOW_ORDERS from .env (file only, not process env)."""
    result = {"IBKR_ALLOW_ORDERS": "?", "found": False}
    if not env_path.exists():
        return result
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#"):
                continue
            if "=" in line and not line.startswith("export "):
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k == "IBKR_ALLOW_ORDERS":
                    result["IBKR_ALLOW_ORDERS"] = v
                    result["found"] = True
                    break
    except Exception:
        pass
    return result


def _read_rules_enforced(rules_path: Path) -> dict:
    """Read rules.enforced from paper-trading-rules.yaml (file only)."""
    result = {"enforced": "?", "found": False}
    if not rules_path.exists():
        return result
    try:
        content = rules_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "enforced:" in stripped:
                # Handle inline comment: 'enforced: false # comment'
                val_part = stripped.split("enforced:", 1)[1]
                val = val_part.split("#", 1)[0].strip()
                result["enforced"] = val
                result["found"] = True
                break
    except Exception:
        pass
    return result


def _atomic_write_json(path: Path, data: object) -> None:
    """Atomically write JSON to path (tmp + rename). Bypasses H1 guard for maintenance."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
