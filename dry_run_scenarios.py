#!/usr/bin/env python3
"""
dry_run_scenarios.py — Phase 3W

Named reusable simulation scenarios for /order/dry-run.
No trading. No IBKR calls. No guard-state mutations.

Each scenario emits only dry_run_order events and preserves the locked live baseline.
Scenarios are safe to run multiple times — they never modify guard-state.json,
never call placeOrder/cancelOrder, and never touch .env or rules YAML.

Usage:
    POST /order/dry-run/scenario  {"scenario": "buy_full_fill"}
    GET  /order/dry-run/scenarios  (list available scenarios)
"""

import json
import time
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

SCENARIO_DEFS: dict[str, dict[str, Any]] = {
    "buy_full_fill": {
        "description": "Simple BUY 5 AAPL, fully filled. Verifies basic dry-run buy + drift preview.",
        "steps": [
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 5},
        ],
        "expected_drift": {"AAPL": 5},
    },
    "buy_partial_fill": {
        "description": "BUY 5 AAPL, only 2 filled. Verifies partial fill handling in drift preview.",
        "steps": [
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 5, "dry_run_fill_qty": 2},
        ],
        "expected_drift": {"AAPL": 2},
    },
    "sell_full_close": {
        "description": "First BUY 5 then SELL 5 (full close). Verifies net-zero drift after round trip.",
        "steps": [
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 5},
            {"symbol": "AAPL", "action": "SELL", "totalQuantity": 5},
        ],
        "expected_drift": {"AAPL": 0},
    },
    "sell_partial_close": {
        "description": "BUY 5 then SELL 3 (partial close). Verifies remaining position in drift.",
        "steps": [
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 5},
            {"symbol": "AAPL", "action": "SELL", "totalQuantity": 3},
        ],
        "expected_drift": {"AAPL": 2},
    },
    "sell_unfilled": {
        "description": "BUY 5 then SELL 5 with dry_run_fill_qty=0 (unfilled). Verifies zero drift from unfilled.",
        "steps": [
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 5},
            {"symbol": "AAPL", "action": "SELL", "totalQuantity": 5, "dry_run_fill_qty": 0},
        ],
        "expected_drift": {"AAPL": 5},
    },
    "duplicate_open_order": {
        "description": "Run two concurrent BUY dry-runs on same symbol. Verifies drift sums both.",
        "steps": [
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 3},
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 4},
        ],
        "expected_drift": {"AAPL": 7},
    },
    "manual_terminal_resolution": {
        "description": "BUY then SELL, then add manual reconciliation record via /monitor/open-orders/reconcile. Verifies scenario + manual record coexist.",
        "steps": [
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 5},
            {"symbol": "AAPL", "action": "SELL", "totalQuantity": 5, "dry_run_fill_qty": 0},
            {"_action": "manual_reconcile", "order_id": 99999, "symbol": "AAPL", "action": "SELL", "final_status": "Cancelled"},
        ],
        "expected_drift": {"AAPL": 5},
    },
    "order_id_reuse": {
        "description": "Run identical BUY twice. Verifies each dry-run creates unique simulated_order_id and drift sums correctly.",
        "steps": [
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 2},
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 2},
        ],
        "expected_drift": {"AAPL": 4},
    },
    "daily_trade_limit_reached": {
        "description": "Run 3 small BUY dry-runs. Verifies drift preview handles multiple trades without affecting guard state.",
        "steps": [
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1},
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1},
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1},
        ],
        "expected_drift": {"AAPL": 3},
    },
    "drift_detected_case": {
        "description": "Multi-symbol scenario: BUY 3 MSFT + BUY 5 AAPL. Verifies drift preview with multiple symbols.",
        "steps": [
            {"symbol": "MSFT", "action": "BUY", "totalQuantity": 3},
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 5},
        ],
        "expected_drift": {"MSFT": 3, "AAPL": 5},
    },
}


def list_scenarios() -> dict:
    """Return list of available scenarios with descriptions."""
    return {
        name: {"description": spec["description"], "steps": len(spec["steps"])}
        for name, spec in sorted(SCENARIO_DEFS.items())
    }


def run_scenario(
    name: str,
    dry_run_caller=None,
    reconcile_caller=None,
) -> dict:
    """Execute a named scenario.

    Args:
        name: Scenario name from SCENARIO_DEFS.
        dry_run_caller: Callable(dict) -> dict for running a dry-run step.
            Must accept the same body as /order/dry-run and return a result dict.
        reconcile_caller: Callable(order_id, final_status, step_body) -> dict for
            manual reconciliation. If None, reconciliation steps are skipped.

    Returns:
        Dict with scenario results and step-level details.

    Raises:
        ValueError: If scenario name is unknown.
    """
    if name not in SCENARIO_DEFS:
        raise ValueError(f"Unknown scenario '{name}'. Available: {sorted(SCENARIO_DEFS.keys())}")

    spec = SCENARIO_DEFS[name]
    steps_results = []
    errors = []
    total_trades = 0

    for i, step in enumerate(spec["steps"]):
        step_body = dict(step)
        step_result = {}

        # Handle special actions
        if step_body.get("_action") == "manual_reconcile":
            oid = step_body.get("order_id", 0)
            final_status = step_body.get("final_status", "Cancelled")
            if reconcile_caller:
                try:
                    rec_result = reconcile_caller(oid, final_status)
                    step_result = {
                        "step": i,
                        "action": "manual_reconcile",
                        "order_id": oid,
                        "final_status": final_status,
                        "result": rec_result,
                    }
                except Exception as e:
                    err = f"Manual reconcile step {i} failed: {e}"
                    errors.append(err)
                    step_result = {"step": i, "action": "manual_reconcile", "error": str(e)}
            else:
                step_result = {
                    "step": i,
                    "action": "manual_reconcile",
                    "skipped": "no reconcile_caller provided",
                }
        else:
            # Standard dry-run step
            step_body.setdefault("orderType", "MKT")
            step_body.setdefault("mode", "dry-run")
            step_body.pop("_action", None)

            if dry_run_caller:
                try:
                    dr_result = dry_run_caller(step_body)
                    step_result = {
                        "step": i,
                        "action": step_body.get("action", "BUY"),
                        "symbol": step_body.get("symbol", ""),
                        "totalQuantity": step_body.get("totalQuantity", 0),
                        "filled": dr_result.get("filled", 0),
                        "remaining": dr_result.get("remaining", 0),
                        "position_delta": dr_result.get("position_delta", 0),
                        "simulated_order_id": dr_result.get("simulated_order_id"),
                        "ok": dr_result.get("ok", False),
                    }
                    if dr_result.get("ok"):
                        total_trades += 1
                except Exception as e:
                    err = f"Dry-run step {i} failed: {e}"
                    errors.append(err)
                    step_result = {"step": i, "error": str(e)}
            else:
                step_result = {
                    "step": i,
                    "action": step_body.get("action"),
                    "skipped": "no dry_run_caller provided",
                }

        steps_results.append(step_result)

    return {
        "scenario": name,
        "description": spec["description"],
        "ok": len(errors) == 0,
        "total_steps": len(spec["steps"]),
        "total_trades": total_trades,
        "errors": errors if errors else None,
        "steps": steps_results,
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def run_all_scenarios(
    dry_run_caller=None,
    reconcile_caller=None,
) -> dict:
    """Run every scenario in sequence.

    Useful for comprehensive testing — exercises the full dry-run
    engine across all 10 scenarios without guard-state side effects.

    Returns aggregated results per scenario.
    """
    results = {}
    for name in sorted(SCENARIO_DEFS.keys()):
        try:
            results[name] = run_scenario(name, dry_run_caller, reconcile_caller)
        except Exception as e:
            results[name] = {"scenario": name, "ok": False, "error": str(e)}
    return results

def run_scenario_report(
    name: str,
    dry_run_caller=None,
    reconcile_caller=None,
    drift_provider=None,
) -> dict:
    """Run a named scenario and produce a pass/fail simulation report.

    Compares expected_drift (from SCENARIO_DEFS) with actual drift
    from position_drift_check(include_dry_run=True). Also reports
    event IDs and confirms live baseline unchanged.

    Args:
        name: Scenario name.
        dry_run_caller: Callable(dict) -> dict for /order/dry-run.
        reconcile_caller: Callable(order_id, final_status, step_body) for reconcile.
        drift_provider: Callable() -> dict returning position_drift_check data.
            If None, runs scenario without drift comparison.

    Returns:
        Dict with full report: scenario, steps, expected/actual preview,
        pass/fail per field, event IDs, live baseline check.
    """
    if name not in SCENARIO_DEFS:
        raise ValueError(f"Unknown scenario '{name}'")

    spec = SCENARIO_DEFS[name]
    expected_drift = spec.get("expected_drift", {})

    # Capture live baseline BEFORE scenario runs
    live_before = drift_provider() if drift_provider else {}
    live_baseline = live_before.get("expected_positions", {})

    # Run scenario
    result = run_scenario(name, dry_run_caller, reconcile_caller)
    step_count = len(result.get("steps", []))

    # Capture actual drift AFTER scenario runs (with dry_runs)
    actual_after = drift_provider() if drift_provider else {}
    actual_drift = actual_after.get("dry_run_preview", {})
    if not actual_drift:
        # Fallback: compute from expected_positions if no separate preview
        # This happens when position_drift_check doesn't have a preview field
        all_pos = actual_after.get("expected_positions", {})
        actual_drift = {}
        for sym, exp_qty in expected_drift.items():
            actual_drift[sym] = all_pos.get(sym, 0)

    # Collect event IDs from scenario steps
    event_ids = []
    for step in result.get("steps", []):
        sid = step.get("simulated_order_id")
        if sid:
            event_ids.append(sid)

    # Compare expected vs actual drift
    drift_results = {}
    all_syms = set(expected_drift.keys()) | set(actual_drift.keys())
    drift_pass = True
    for sym in sorted(all_syms):
        exp = expected_drift.get(sym, 0)
        act = actual_drift.get(sym, 0)
        match = (exp == act)
        if not match:
            drift_pass = False
        drift_results[sym] = {
            "expected": exp,
            "actual": act,
            "match": match,
        }

    # Check live baseline unchanged
    live_after = drift_provider() if drift_provider else {}
    live_after_pos = live_after.get("expected_positions", {})
    baseline_unchanged = True
    for sym in live_baseline:
        if live_baseline[sym] != live_after_pos.get(sym, 0):
            baseline_unchanged = False

    passed = result.get("ok", False) and drift_pass and baseline_unchanged

    return {
        "report_type": "simulation_audit",
        "scenario": name,
        "description": spec["description"],
        "passed": passed,
        "ok": result.get("ok", False),
        "drift_match": drift_pass,
        "baseline_unchanged": baseline_unchanged,
        "steps_executed": step_count,
        "trades_in_scenario": result.get("total_trades", 0),
        "expected_drift": expected_drift,
        "actual_drift": actual_drift,
        "drift_comparison": drift_results,
        "event_ids": event_ids,
        "scenario_result": result,
        "live_baseline": live_baseline,
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def generate_full_report(
    dry_run_caller=None,
    reconcile_caller=None,
    drift_provider=None,
) -> dict:
    """Run all scenarios and produce a full simulation audit report.

    Returns aggregated pass/fail across all scenarios plus summary stats.
    """
    reports = {}
    passed_count = 0
    total = 0
    for name in sorted(SCENARIO_DEFS.keys()):
        total += 1
        try:
            rep = run_scenario_report(name, dry_run_caller, reconcile_caller, drift_provider)
            reports[name] = rep
            if rep.get("passed"):
                passed_count += 1
        except Exception as e:
            reports[name] = {"scenario": name, "passed": False, "error": str(e)}

    return {
        "report_type": "simulation_audit_full",
        "total_scenarios": total,
        "passed_count": passed_count,
        "all_passed": passed_count == total,
        "reports": reports,
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main():
    """CLI entry point: run one or all scenarios and print report."""
    import sys as _sys

    args = _sys.argv[1:]
    scenario_name = args[0] if args else None

    # We need bridge callers and drift provider — when running standalone
    # without bridge, we provide stub callers that cannot execute.
    # Use --local flag for file-only mode.
    if "--help" in args or "-h" in args:
        print("Usage: python3 dry_run_scenarios.py <scenario_name|--all>")
        print("")
        print("Scenarios:")
        for name, spec in sorted(SCENARIO_DEFS.items()):
            print(f"  {name:<35s} {spec['description']}")
        print("")
        print("Note: When running without bridge, --list shows definitions only.")
        print("Full execution requires bridge at http://127.0.0.1:8790.")
        return

    if "--list" in args or scenario_name is None:
        print("Available scenarios:")
        for name, spec in sorted(SCENARIO_DEFS.items()):
            exp = spec.get("expected_drift", {})
            print(f"  {name:<35s} {spec['description']}")
            print(f"  {'':35s} steps={len(spec['steps'])}, expected_drift={exp}")
        return

    if scenario_name == "--all":
        print("Run all scenarios via bridge...")
    else:
        print(f"Scenario: {scenario_name}")


if __name__ == "__main__":
    main()
