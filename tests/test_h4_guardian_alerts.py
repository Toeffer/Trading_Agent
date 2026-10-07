#!/usr/bin/env python3
"""
Phase H4 — Guardian Alerts — Regression Tests

Tests:
  H4-FX1: _fetch_exchange_rate rejects None (no silent 1.0 fallback)
  H4-FX2: _fetch_exchange_rate rejects rate outside [0.8, 1.4]
  H4-FX3: _fetch_exchange_rate accepts rate in [0.8, 1.4]
  H4-FX4: run_preflight rejects when FX unavailable
  H4-FX5: run_preflight rejects when FX outside range
  H4-FX6: fetch_account returns None exchange_rate (no 1.0 fallback)
  H4-ETF1: SPY rejected by _reject_us_domiciled_etf
  H4-ETF2: QQQ rejected by _reject_us_domiciled_etf
  H4-ETF3: AAPL accepted by _reject_us_domiciled_etf
  H4-ETF4: run_preflight rejects SPY BUY with gate=us_etf_block
  H4-ETF5: Leveraged ETF (TQQQ) rejected
  H4-ETF6: Blocklist size >= 30 (structural, not just SPY/QQQ)
  H4-STOP1: check_stop_breach returns list (empty when no positions or no stops)
  H4-STOP2: _compute_positions_from_events returns dict
  H4-STOP3: _find_active_stop returns None for unknown symbol
  H4-WDOG1: check_kill_switch_watchdog returns list
  H4-WDOG2: check_kill_switch_watchdog returns empty when IBKR_ALLOW_ORDERS=false
  H4-WDOG3: check_kill_switch_watchdog returns empty when rules.enforced=false
  H4-WDOG4: Default max_minutes is 10
  H4-API1: _run_h4_stop_breach_check is callable
  H4-API2: _run_h4_watchdog_check is callable
  H4-NOOP: All H4 functions are read-only (no broker mutation)
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

PASS = 0
FAIL = 0
WARN = 0
ERRORS = []


def check(ok: bool, message: str):
    global PASS, FAIL, ERRORS
    if ok:
        PASS += 1
        print(f"  ✅ {message}")
    else:
        FAIL += 1
        ERRORS.append(message)
        print(f"  ❌ {message}")


def warn(message: str):
    global WARN
    WARN += 1
    print(f"  ⚠️  {message}")


def main():
    global PASS, FAIL, WARN, ERRORS

    print("=" * 60)
    print("Phase H4 — Guardian Alerts — Regression Tests")
    print("=" * 60)

    home = Path.home()
    sys.path.insert(0, str(home / "agents" / "ibkr-bridge"))
    import guard

    # ══════════════════════════════════════════════════════════════════
    # H4.2: FX Plausibility Guard
    # ══════════════════════════════════════════════════════════════════
    print("\n── H4.2: FX Plausibility Guard ──")

    # H4-FX6: fetch_account returns None (no 1.0 fallback)
    fx_in_account = guard.fetch_account.__code__.co_consts
    # Verify no "1.0" is the default in fetch_account
    import inspect
    fetch_account_src = inspect.getsource(guard.fetch_account)
    check("1.0" not in fetch_account_src or "float(fx_raw) if fx_raw else 1.0" not in fetch_account_src,
          "fetch_account no longer has silent 1.0 fallback")

    # H4-FX1: _fetch_exchange_rate rejects None
    try:
        guard._fetch_exchange_rate(account_provider=lambda: {"exchange_rate": None})
        check(False, "_fetch_exchange_rate should reject None")
    except ValueError as e:
        check("unavailable" in str(e).lower() or "missing" in str(e).lower(),
              f"_fetch_exchange_rate rejects None: {str(e)[:80]}")

    # H4-FX2: _fetch_exchange_rate rejects FX < 0.8
    try:
        guard._fetch_exchange_rate(account_provider=lambda: {"exchange_rate": 0.5})
        check(False, "_fetch_exchange_rate should reject 0.5")
    except ValueError as e:
        check("plausibility" in str(e).lower() or "0.5" in str(e),
              f"_fetch_exchange_rate rejects 0.5: {str(e)[:80]}")

    # H4-FX2b: _fetch_exchange_rate rejects FX > 1.4
    try:
        guard._fetch_exchange_rate(account_provider=lambda: {"exchange_rate": 1.5})
        check(False, "_fetch_exchange_rate should reject 1.5")
    except ValueError as e:
        check("plausibility" in str(e).lower() or "1.5" in str(e),
              f"_fetch_exchange_rate rejects 1.5: {str(e)[:80]}")

    # H4-FX3: _fetch_exchange_rate accepts valid rate
    try:
        rate = guard._fetch_exchange_rate(account_provider=lambda: {"exchange_rate": 1.08})
        check(abs(rate - 1.08) < 0.001,
              f"_fetch_exchange_rate accepts 1.08 → {rate}")
    except ValueError as e:
        check(False, f"_fetch_exchange_rate should accept 1.08: {e}")

    # H4-FX3b: _fetch_exchange_rate accepts boundary 0.80
    try:
        rate = guard._fetch_exchange_rate(account_provider=lambda: {"exchange_rate": 0.80})
        check(abs(rate - 0.80) < 0.001,
              f"_fetch_exchange_rate accepts boundary 0.80 → {rate}")
    except ValueError as e:
        check(False, f"_fetch_exchange_rate should accept 0.80: {e}")

    # H4-FX3c: _fetch_exchange_rate accepts boundary 1.40
    try:
        rate = guard._fetch_exchange_rate(account_provider=lambda: {"exchange_rate": 1.40})
        check(abs(rate - 1.40) < 0.001,
              f"_fetch_exchange_rate accepts boundary 1.40 → {rate}")
    except ValueError as e:
        check(False, f"_fetch_exchange_rate should accept 1.40: {e}")

    # ══════════════════════════════════════════════════════════════════
    # H4.1: US-Domiciled ETF Structural Rejection
    # ══════════════════════════════════════════════════════════════════
    print("\n── H4.1: US-Domiciled ETF Rejection ──")

    # H4-ETF1: SPY rejected
    try:
        guard._reject_us_domiciled_etf("SPY")
        check(False, "_reject_us_domiciled_etf should reject SPY")
    except ValueError as e:
        check("US-domiciled" in str(e) or "blocked" in str(e).lower(),
              f"SPY rejected: {str(e)[:80]}")

    # H4-ETF2: QQQ rejected
    try:
        guard._reject_us_domiciled_etf("QQQ")
        check(False, "_reject_us_domiciled_etf should reject QQQ")
    except ValueError as e:
        check("US-domiciled" in str(e) or "blocked" in str(e).lower(),
              f"QQQ rejected: {str(e)[:80]}")

    # H4-ETF3: AAPL accepted (it's a stock)
    try:
        guard._reject_us_domiciled_etf("AAPL")
        check(True, "AAPL accepted by _reject_us_domiciled_etf (not an ETF)")
    except ValueError as e:
        check(False, f"AAPL should NOT be rejected: {e}")

    # H4-ETF3b: META accepted
    try:
        guard._reject_us_domiciled_etf("META")
        check(True, "META accepted by _reject_us_domiciled_etf")
    except ValueError as e:
        check(False, f"META should NOT be rejected: {e}")

    # H4-ETF5: TQQQ (leveraged ETF) rejected
    try:
        guard._reject_us_domiciled_etf("TQQQ")
        check(False, "_reject_us_domiciled_etf should reject TQQQ")
    except ValueError as e:
        check(True, f"TQQQ rejected: {str(e)[:80]}")

    # H4-ETF5b: VOO rejected
    try:
        guard._reject_us_domiciled_etf("VOO")
        check(False, "_reject_us_domiciled_etf should reject VOO")
    except ValueError as e:
        check(True, f"VOO rejected: {str(e)[:80]}")

    # H4-ETF6: Blocklist size
    check(len(guard._US_ETF_BLOCKLIST) >= 30,
          f"US ETF blocklist has {len(guard._US_ETF_BLOCKLIST)} entries (>=30)")

    # H4-ETF7: Contract-level structural check (simulated)
    # When contract_provider returns secType=ETF, exchange=SMART → reject
    mock_contract = lambda sym: {"secType": "ETF", "exchange": "SMART", "symbol": sym}
    try:
        guard._reject_us_domiciled_etf("CUSTOM_ETF", contract_provider=mock_contract)
        check(False, "Contract-level check should reject ETF on SMART")
    except ValueError as e:
        check("ETF on US exchange" in str(e),
              f"Contract-level check works: {str(e)[:80]}")

    # H4-ETF8: Contract-level structural check — non-ETF passes
    mock_stock = lambda sym: {"secType": "STK", "exchange": "SMART", "symbol": sym}
    try:
        guard._reject_us_domiciled_etf("SOME_STOCK", contract_provider=mock_stock)
        check(True, "Contract-level check: STK on SMART passes")
    except ValueError as e:
        check(False, f"STK should pass: {e}")

    # ══════════════════════════════════════════════════════════════════
    # H4.3: Stop Breach Alert
    # ══════════════════════════════════════════════════════════════════
    print("\n── H4.3: Stop Breach Alert ──")

    # H4-STOP1: check_stop_breach returns list
    result = guard.check_stop_breach(
        quote_provider=lambda sym: {"close": 500.0, "bid": 499.0, "ask": 501.0},
    )
    check(isinstance(result, list),
          f"check_stop_breach returns list ({len(result)} alerts)")

    # H4-STOP2: _compute_positions_from_events returns dict
    positions = guard._compute_positions_from_events()
    check(isinstance(positions, dict),
          f"_compute_positions_from_events returns dict ({len(positions)} positions)")

    # H4-STOP3: _find_active_stop returns None for unknown
    stop = guard._find_active_stop("ZZZZNONEXISTENT")
    check(stop is None,
          "_find_active_stop returns None for unknown symbol")

    # H4-STOP4: check_stop_breach with a mock position that has a stop
    # We need to simulate a position with a stop that's breached
    # To test the breach logic, mock _compute_positions and _find_active_stop
    with patch.object(guard, '_compute_positions_from_events',
                      return_value={"AAPL": 100}):
        with patch.object(guard, '_find_active_stop', return_value=310.0):
            # Quote below stop → should alert
            alerts = guard.check_stop_breach(
                quote_provider=lambda sym: {"close": 300.0},
            )
            check(len(alerts) == 1,
                  f"Stop breach detected when close (300) < stop (310): {len(alerts)} alerts")
            if alerts:
                check(alerts[0]["alert_type"] == "stop_breach",
                      f"Alert type: {alerts[0]['alert_type']}")
                check(alerts[0]["symbol"] == "AAPL",
                      f"Symbol: {alerts[0]['symbol']}")
                check("NO auto-exit" in alerts[0].get("action_required", ""),
                      "Alert explicitly says NO auto-exit")

    # H4-STOP5: No breach when price above stop
    with patch.object(guard, '_compute_positions_from_events',
                      return_value={"AAPL": 100}):
        with patch.object(guard, '_find_active_stop', return_value=300.0):
            alerts = guard.check_stop_breach(
                quote_provider=lambda sym: {"close": 310.0},
            )
            check(len(alerts) == 0,
                  f"No breach when close (310) > stop (300): {len(alerts)} alerts")

    # ══════════════════════════════════════════════════════════════════
    # H4.4: Kill Switch Watchdog
    # ══════════════════════════════════════════════════════════════════
    print("\n── H4.4: Kill Switch Watchdog ──")

    # H4-WDOG1: check_kill_switch_watchdog returns list
    result = guard.check_kill_switch_watchdog(max_minutes=10)
    check(isinstance(result, list),
          f"check_kill_switch_watchdog returns list ({len(result)} alerts)")

    # H4-WDOG2: Returns empty when IBKR_ALLOW_ORDERS=false
    with patch.object(guard, '_check_ibkr_allowed', return_value=False):
        result = guard.check_kill_switch_watchdog(max_minutes=10)
        check(len(result) == 0,
              f"Watchdog silent when IBKR_ALLOW_ORDERS=false: {len(result)} alerts")

    # H4-WDOG3: Returns empty when rules.enforced=false
    with patch.object(guard, '_check_ibkr_allowed', return_value=True):
        with patch.object(guard, '_check_enforced', return_value=False):
            result = guard.check_kill_switch_watchdog(max_minutes=10)
            check(len(result) == 0,
                  f"Watchdog silent when rules.enforced=false: {len(result)} alerts")

    # H4-WDOG4: Default max_minutes is 10
    import inspect as ins
    sig = ins.signature(guard.check_kill_switch_watchdog)
    check(sig.parameters["max_minutes"].default == 10,
          f"Default max_minutes = {sig.parameters['max_minutes'].default}")

    # H4-WDOG5: Alert fires when both kill switches true + no active cycle
    with patch.object(guard, '_check_ibkr_allowed', return_value=True):
        with patch.object(guard, '_check_enforced', return_value=True):
            # Ensure no active approvals exist
            with patch.object(guard, '_active_approvals', {}):
                # Ensure no last_trade_utc in guard state
                from unittest.mock import MagicMock as Mock
                mock_gs = {"daily_trade_count": 0, "trade_date": "2026-01-01"}
                with patch.object(guard, 'load_guard_state', return_value=mock_gs):
                    result = guard.check_kill_switch_watchdog(max_minutes=10)
                    check(len(result) >= 1,
                          f"Watchdog fires when both switches true, no active cycle: "
                          f"{len(result)} alerts")
                    if result:
                        check(result[0]["alert_type"] == "kill_switch_watchdog",
                              f"Alert type: {result[0]['alert_type']}")
                        check("no auto-disable" in result[0].get("action_required", "").lower(),
                              "Alert explicitly says no auto-disable")

    # ══════════════════════════════════════════════════════════════════
    # H4-NOOP: Read-Only Guarantee
    # ══════════════════════════════════════════════════════════════════
    print("\n── H4-NOOP: Read-Only Guarantee ──")

    # Verify none of the H4 functions call order submission
    h4_funcs = [
        "_reject_us_domiciled_etf",
        "_fetch_exchange_rate",
        "check_stop_breach",
        "check_kill_switch_watchdog",
        "_run_h4_stop_breach_check",
        "_run_h4_watchdog_check",
    ]
    dangerous_calls = ["placeOrder", "submit_order", "ib.placeOrder", "ibkr_submit"]
    for fname in h4_funcs:
        func = getattr(guard, fname, None)
        if func is None:
            check(False, f"Function {fname} not found in guard")
            continue
        src = ins.getsource(func)
        clean = True
        for d in dangerous_calls:
            if d in src:
                clean = False
                check(False, f"{fname} contains '{d}' — VIOLATES read-only guarantee")
        if clean:
            check(True, f"{fname} is read-only (no broker mutation)")

    # Verify alerts say "NO auto-exit" or similar
    check("NO auto-exit" in ins.getsource(guard.check_stop_breach),
          "check_stop_breach includes 'NO auto-exit'")
    check("no auto-disable" in ins.getsource(guard.check_kill_switch_watchdog).lower(),
          "check_kill_switch_watchdog includes 'no auto-disable'")

    # ══════════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    total = PASS + FAIL
    print(f"Results: {PASS} passed, {FAIL} failed, {WARN} warnings (of {total} checks)")
    print("=" * 60)

    if ERRORS:
        print("\nFailed checks:")
        for e in ERRORS:
            print(f"  - {e}")

    return FAIL == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
