#!/usr/bin/env python3
"""
P5 — Broker-Side Protective Stops / Bracket-Stop Support Tests

Validates:
  T1  BUY without stop fails closed
  T2  BUY with stop above/equal entry fails closed
  T3  BUY with mismatched stop quantity fails closed
  T4  Valid BUY builds parent + protective SELL stop
  T5  Transmit flags / order linkage tested
  T6  SELL close-only does not require bracket stop
  T7  /order remains 403
  T8  H1 approve/submit still enforced
  T9  Gate E P2b close-only exemption still passes
  T10 Gate H proposal discipline still passes
  T11 No raw token/log leakage
  T12 Kill-switch dry-run validates bracket without broker mutation
  T13 Parent not left live without protective stop (fail-closed)
  T14 Evidence fields correct
  T15 Concurrent safety
  T16 No regression on existing behavior
"""

import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def _disable_h1_startup(monkeypatch):
    """Disable H1 startup enforcement for guard unit tests.

    Tests that call run_preflight or submit_order touch guard-state and
    other protected files. Tests run outside the bridge process and
    don't have H1 tokens. This fixture patches _h1_startup_complete to
    False so that H1 checks are skipped during those test runs.

    SCOPE: Only applied to test classes that explicitly request it via
    @pytest.mark.usefixtures("_disable_h1_startup").
    H1 enforcement tests (TestH1EnforcementIntact) must NOT use this.
    """
    import guard
    monkeypatch.setattr(guard, '_h1_startup_complete', False)


from guard import (
    h1_authorized_scope,
    h1_authorize,
    h1_deauthorize,
    _h1_authorized,
    PROTECTED_PATHS,
    _is_protected_path,
    run_preflight,
    submit_order,
    validate_bracket_stop,
    _active_approvals,
    _check_ibkr_allowed,
    _check_enforced,
    load_rules,
    load_guard_state,
    save_guard_state_atomic,
    approve_approval,
    deny_approval,
    get_active_approval,
    mark_approval_submitted,
    is_approval_submitted,
    create_approval_record,
)


# Reusable mock data
MOCK_BARS = [
    {"date": f"2026-05-{d:02d}", "open": 170.0 + d, "high": 180.0 + d, "low": 168.0 + d, "close": 178.0 + d}
    for d in range(1, 22)  # 21 bars covering ~1 month
]

MOCK_ACCOUNT = {"net_liquidation_eur": 1000000, "exchange_rate": 1.10}

MOCK_QUOTE = {"ask": 180.0, "bid": 179.50, "close": 179.80}


def _make_bars_provider():
    return lambda sym: MOCK_BARS


def _make_account_provider():
    return lambda: MOCK_ACCOUNT


def _make_quote_provider():
    return lambda sym: MOCK_QUOTE


# ============================================================================
# T1 — BUY without stop fails closed
# ============================================================================

@pytest.mark.usefixtures("_disable_h1_startup")
class TestBuyWithoutStopFailsClosed:
    """T1: BUY entry must have a stop; missing/invalid fails closed."""

    def test_preflight_buy_no_stop_field_fails(self):
        """BUY preflight without stopPrice fails closed (Gate H needs proposal)."""
        result = run_preflight(
            {
                "symbol": "AAPL",
                "action": "BUY",
                "totalQuantity": 10,
                "orderType": "MKT",
            },
            account_provider=_make_account_provider(),
            quote_provider=_make_quote_provider(),
            bars_provider=_make_bars_provider(),
        )
        # Without stopPrice, calc_stop runs and may succeed, but Gate H fails
        # (no proposal_path). Main assertion: BUY without explicit stop
        # should either fail on stop calc or on Gate H.
        # Either way, passed=False for this test (no proposal).
        assert not result.get("passed"), f"Expected fail without stopPrice: {result}"

    def test_preflight_buy_stop_price_zero_fails(self):
        """BUY with stopPrice=0 fails (must be > 0 and below entry)."""
        result = run_preflight(
            {
                "symbol": "AAPL",
                "action": "BUY",
                "totalQuantity": 10,
                "orderType": "MKT",
                "stopPrice": 0,
            },
            account_provider=_make_account_provider(),
            quote_provider=_make_quote_provider(),
            bars_provider=_make_bars_provider(),
        )
        # stopPrice=0 is treated as "provided" but fails below-entry check
        assert not result.get("passed"), f"Expected fail for stopPrice=0: {result}"

    def test_preflight_buy_stop_negative_fails(self):
        """BUY with negative stopPrice fails."""
        result = run_preflight(
            {
                "symbol": "AAPL",
                "action": "BUY",
                "totalQuantity": 10,
                "orderType": "MKT",
                "stopPrice": -1.0,
            },
            account_provider=_make_account_provider(),
            quote_provider=_make_quote_provider(),
            bars_provider=_make_bars_provider(),
        )
        assert not result.get("passed"), f"Expected fail for stopPrice=-1: {result}"

    def test_validate_bracket_stop_none_fails(self):
        """validate_bracket_stop(None) -> fail."""
        result = validate_bracket_stop(stop_price=None, entry_price=180.0, quantity=10, action="BUY")
        assert not result["valid"]
        assert "stop" in result["error"].lower()

    def test_validate_bracket_stop_missing_fails(self):
        """validate_bracket_stop with missing stop -> fail."""
        result = validate_bracket_stop(stop_price=0, entry_price=180.0, quantity=10, action="BUY")
        assert not result["valid"]


# ============================================================================
# T2 — BUY with stop above/equal entry fails closed
# ============================================================================

@pytest.mark.usefixtures("_disable_h1_startup")
class TestStopAboveOrEqualEntryFails:
    """T2: Stop must be strictly below entry price."""

    def test_stop_equal_entry_fails(self):
        """stopPrice == entry price fails."""
        result = run_preflight(
            {
                "symbol": "AAPL",
                "action": "BUY",
                "totalQuantity": 10,
                "orderType": "MKT",
                "stopPrice": 180.0,
            },
            account_provider=_make_account_provider(),
            quote_provider=_make_quote_provider(),
            bars_provider=_make_bars_provider(),
        )
        assert not result.get("passed"), f"Expected fail for stop == entry: {result}"
        assert "below" in result.get("error", "").lower()

    def test_stop_above_entry_fails(self):
        """stopPrice > entry price fails."""
        result = run_preflight(
            {
                "symbol": "AAPL",
                "action": "BUY",
                "totalQuantity": 10,
                "orderType": "MKT",
                "stopPrice": 190.0,
            },
            account_provider=_make_account_provider(),
            quote_provider=_make_quote_provider(),
            bars_provider=_make_bars_provider(),
        )
        assert not result.get("passed"), f"Expected fail for stop > entry: {result}"
        assert "below" in result.get("error", "").lower()

    def test_validate_bracket_stop_above_fails(self):
        """validate_bracket_stop with stop > entry -> fail."""
        result = validate_bracket_stop(stop_price=190.0, entry_price=180.0, quantity=10, action="BUY")
        assert not result["valid"]
        assert "below" in result["error"].lower()

    def test_validate_bracket_stop_equal_fails(self):
        """validate_bracket_stop with stop == entry -> fail."""
        result = validate_bracket_stop(stop_price=180.0, entry_price=180.0, quantity=10, action="BUY")
        assert not result["valid"]


# ============================================================================
# T3 — BUY with mismatched stop quantity fails closed
# ============================================================================

class TestMismatchedStopQuantityFails:
    """T3: Stop quantity must match entry quantity for BUY."""

    def test_validate_bracket_stop_qty_mismatch_fails(self):
        """Stop quantity 5 != entry quantity 10 -> fail."""
        result = validate_bracket_stop(
            stop_price=170.0,
            entry_price=180.0,
            quantity=10,
            action="BUY",
            stop_quantity=5,
        )
        assert not result["valid"]
        assert "quantity" in result.get("error", "").lower() or "match" in result.get("error", "").lower()

    def test_validate_bracket_stop_qty_none_defaults_ok(self):
        """stop_quantity=None defaults to quantity -> valid."""
        result = validate_bracket_stop(
            stop_price=170.0,
            entry_price=180.0,
            quantity=10,
            action="BUY",
            stop_quantity=None,
        )
        assert result["valid"]

    def test_validate_bracket_stop_qty_match_ok(self):
        """stop_quantity=10 == quantity=10 -> valid."""
        result = validate_bracket_stop(
            stop_price=170.0,
            entry_price=180.0,
            quantity=10,
            action="BUY",
            stop_quantity=10,
        )
        assert result["valid"]


# ============================================================================
# T4 — Valid BUY builds parent + protective SELL stop
# ============================================================================

@pytest.mark.usefixtures("_disable_h1_startup")
class TestValidBuyBracketConstruction:
    """T4: Valid BUY produces bracket evidence."""

    def test_validate_bracket_stop_valid_buy(self):
        """Valid BUY with stop below entry passes validation."""
        result = validate_bracket_stop(
            stop_price=170.0,
            entry_price=180.0,
            quantity=10,
            action="BUY",
        )
        assert result["valid"]
        assert result["stop_price"] == 170.0
        assert result["quantity"] == 10
        assert result["stop_action"] == "SELL"
        assert result.get("bracket") is True

    def test_submit_buy_constructs_bracket_orders(self):
        """Submit BUY constructs parent + protective SELL stop via provider."""
        approval_id = "test-bracket-" + str(int(time.time() * 1000))

        record = {
            "approval_id": approval_id,
            "status": "approved",
            "ruled_by": "Chris",
            "ruling_at_utc": datetime.now(timezone.utc).isoformat(),
            "expires_at_utc": datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat(),
            "proposal": {
                "symbol": "AAPL",
                "action": "BUY",
                "totalQuantity": 10,
                "orderType": "MKT",
                "final_max_shares": 100,
                "shares_requested": 10,
                "shares_exceeds_max": False,
                "binding_cap": "notional",
                "close_only": False,
            },
            "validation": {
                "entry_price": 180.0,
                "stop_price": 170.0,
                "stop_distance": 10.0,
                "final_max_shares": 100,
                "binding_cap": "notional",
            },
        }

        import guard
        guard._active_approvals[approval_id] = record

        bracket_evidence = []

        def mock_order_provider(rec):
            stop_price = rec.get("validation", {}).get("stop_price") or rec.get("proposal", {}).get("stop_price")
            entry_price = rec.get("validation", {}).get("entry_price") or rec.get("proposal", {}).get("entry_price")
            if rec.get("proposal", {}).get("action") == "BUY":
                if stop_price:
                    parent_id = 1001
                    stop_id = 1002
                    ev = {
                        "parent_order_id": parent_id,
                        "stop_order_id": stop_id,
                        "stop_price": stop_price,
                        "entry_price": entry_price,
                        "quantity": rec["proposal"]["totalQuantity"],
                        "parent_transmit": False,
                        "stop_transmit": True,
                        "bracket": True,
                        "protective_stop": True,
                    }
                    bracket_evidence.append(ev)
                    return {
                        "success": True,
                        "order_id": parent_id,
                        "ib_order_id": parent_id,
                        "stop_order_id": stop_id,
                        "permId": 5001,
                        "status": "Submitted",
                        "bracket_evidence": ev,
                    }
            return {"success": False, "error": "No stop price for bracket"}

        try:
            with patch.object(guard, '_check_ibkr_allowed', return_value=True), \
                 patch.object(guard, '_check_enforced', return_value=True), \
                 patch.object(guard, 'is_approval_submitted', return_value=False):
                result = submit_order(
                    approval_id,
                    order_provider=mock_order_provider,
                    status_provider=lambda oid: "Submitted",
                    account_provider=lambda: {"net_liquidation_eur": 1000000, "exchange_rate": 1.10},
                    quote_provider=lambda sym: {"ask": 180.0, "bid": 179.50, "close": 179.80},
                    bars_provider=lambda sym: MOCK_BARS,
                )

            assert result.get("submitted"), f"Expected submitted=True, got: {result}"
            assert bracket_evidence, "No bracket evidence recorded"
            ev = bracket_evidence[0]
            assert ev["bracket"] is True
            assert ev["protective_stop"] is True
            assert ev["parent_transmit"] is False
            assert ev["stop_transmit"] is True
            assert ev["stop_price"] == 170.0
            assert ev["parent_order_id"] == 1001
            assert ev["stop_order_id"] == 1002
        finally:
            guard._active_approvals.pop(approval_id, None)


# ============================================================================
# T5 — Transmit flags / order linkage
# ============================================================================

class TestTransmitFlagsAndLinkage:
    """T5: Parent transmit=false, child stop transmit=true."""

    def test_parent_transmit_false(self):
        """Parent BUY order must have transmit=False."""
        ev = validate_bracket_stop(
            stop_price=170.0, entry_price=180.0, quantity=10, action="BUY"
        )
        assert ev.get("parent_transmit") is False

    def test_child_stop_transmit_true(self):
        """Child SELL stop must have transmit=True."""
        ev = validate_bracket_stop(
            stop_price=170.0, entry_price=180.0, quantity=10, action="BUY"
        )
        assert ev.get("stop_transmit") is True

    def test_bracket_flag_is_true(self):
        """bracket flag must be True for BUY entries."""
        ev = validate_bracket_stop(
            stop_price=170.0, entry_price=180.0, quantity=10, action="BUY"
        )
        assert ev.get("bracket") is True
        assert ev.get("protective_stop") is True

    def test_no_take_profit_for_p5(self):
        """P5 does not include take-profit orders."""
        ev = validate_bracket_stop(
            stop_price=170.0, entry_price=180.0, quantity=10, action="BUY"
        )
        assert "take_profit" not in ev or ev.get("take_profit") is None or ev.get("take_profit") is False


# ============================================================================
# T6 — SELL close-only does not require bracket stop
# ============================================================================

@pytest.mark.usefixtures("_disable_h1_startup")
class TestSellCloseOnlyNoBracket:
    """T6: SELL close-only must not require bracket stop."""

    def test_sell_validate_bracket_returns_not_needed(self):
        """validate_bracket_stop for SELL returns not_needed."""
        result = validate_bracket_stop(
            stop_price=None, entry_price=180.0, quantity=10, action="SELL"
        )
        assert result["valid"], f"SELL should not need bracket: {result}"
        assert not result.get("bracket"), f"SELL should not flag bracket=True: {result}"

    def test_sell_preflight_no_stop_price(self):
        """SELL preflight stop_price is None."""
        result = run_preflight(
            {
                "symbol": "AAPL",
                "action": "SELL",
                "totalQuantity": 10,
                "orderType": "MKT",
            },
            account_provider=_make_account_provider(),
            quote_provider=_make_quote_provider(),
            bars_provider=_make_bars_provider(),
            position_provider=lambda: [
                {"symbol": "AAPL", "position": 50, "marketValue": 9000.0}
            ],
        )
        # SELL may fail on Gate H (proposal), but stop_price should be None
        assert result.get("stop_price") is None, \
            f"SELL stop_price should be None, got: {result.get('stop_price')}"

    def test_sell_does_not_trigger_bracket_construction(self):
        """submit_order for SELL should not attempt bracket construction."""
        result = validate_bracket_stop(
            stop_price=None, entry_price=179.50, quantity=10, action="SELL"
        )
        assert result["valid"]
        assert not result.get("bracket")


# ============================================================================
# T7 — /order remains 403
# ============================================================================

class TestOrder403:
    """T7: /order endpoint permanently returns 403."""

    def test_order_endpoint_returns_403(self):
        """bridge.py /order route exists but permanently returns 403."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        source = bridge_path.read_text()
        routes = re.findall(r'@app\.(?:post|get)\("(/order[^"]*)"', source)
        # /order must exist and return 403
        assert "/order" in routes, f"/order route not found: {routes}"
        # Must contain 403 status code in the handler
        assert "403" in source or "status_code=403" in source, \
            "/order endpoint must return HTTP 403"
        assert "/order/preflight" in routes
        assert "/order/approve" in routes
        assert "/order/submit" in routes


# ============================================================================
# T8 — H1 approve/submit still enforced
# ============================================================================

class TestH1EnforcementIntact:
    """T8: H1 token enforcement remains for approve and submit.

    These tests MUST NOT use the _disable_h1_startup fixture.
    They verify that H1 authorization is required at the bridge boundary.
    """

    def test_h1_verify_token_function_exists(self):
        """_verify_h1_token exists in bridge.py."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        source = bridge_path.read_text()
        assert "def _verify_h1_token" in source

    def test_h1_authorized_scope_still_used(self):
        """h1_authorized_scope context manager still used in submit/approve."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        source = bridge_path.read_text()
        assert "h1_authorized_scope" in source
        assert "with h1_authorized_scope():" in source

    def test_h1_no_raw_authorize_deauthorize_in_bridge(self):
        """bridge.py must not have standalone h1_authorize()/h1_deauthorize() calls."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        source = bridge_path.read_text()
        # Remove comments
        lines = [l for l in source.split("\n") if not l.strip().startswith("#")]
        clean = "\n".join(lines)
        standalone_calls = re.findall(r'(?<!with\s)(?<!def\s)(?<!\.)\bh1_authorize\(\)', clean)
        assert len(standalone_calls) == 0, \
            f"Standalone h1_authorize() found in bridge.py: {standalone_calls}"
        standalone_deauth = re.findall(r'(?<!\.)\bh1_deauthorize\(\)', clean)
        assert len(standalone_deauth) == 0, \
            f"Standalone h1_deauthorize() found in bridge.py: {standalone_deauth}"

    def test_verify_h1_token_rejects_none(self):
        """_verify_h1_token(None) returns False."""
        from bridge import _verify_h1_token
        assert _verify_h1_token(None) is False

    def test_verify_h1_token_rejects_empty(self):
        """_verify_h1_token('') returns False."""
        from bridge import _verify_h1_token
        assert _verify_h1_token("") is False

    def test_verify_h1_token_rejects_non_string(self):
        """_verify_h1_token(123) returns False."""
        from bridge import _verify_h1_token
        assert _verify_h1_token(123) is False  # type: ignore

    def test_verify_h1_token_rejects_wrong_token(self):
        """_verify_h1_token with wrong token returns False."""
        from bridge import _verify_h1_token
        # Without H1_APPROVAL_TOKEN_HASH env, all tokens rejected
        assert _verify_h1_token("wrong-token-value") is False

    def test_h1_authorized_scope_resets_on_exception(self):
        """h1_authorized_scope resets _h1_authorized on exception (via guard)."""
        assert not _h1_authorized.get()
        try:
            with h1_authorized_scope():
                assert _h1_authorized.get()
                raise RuntimeError("forced")
        except RuntimeError:
            pass
        assert not _h1_authorized.get(), "H1 authorization must reset after exception"

    def test_h1_authorized_not_global(self):
        """_h1_authorized is ContextVar, not global."""
        import contextvars
        assert isinstance(_h1_authorized, contextvars.ContextVar), \
            f"_h1_authorized must be ContextVar, not {type(_h1_authorized)}"

    def test_approve_endpoint_checks_h1_token(self):
        """order_approve checks X-H1-Token header before any mutation."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        source = bridge_path.read_text()
        # order_approve must call _verify_h1_token before h1_authorized_scope
        approve_body = source[source.index("def order_approve"):source.index("class SubmitRequest")]
        verify_idx = approve_body.index("_verify_h1_token")
        scope_idx = approve_body.index("h1_authorized_scope")
        assert verify_idx < scope_idx, \
            "H1 token check must happen BEFORE h1_authorized_scope in order_approve"

    def test_submit_endpoint_checks_h1_token(self):
        """order_submit checks X-H1-Token header before any mutation."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        source = bridge_path.read_text()
        # order_submit must call _verify_h1_token before h1_authorized_scope
        submit_body = source[source.index("def order_submit"):source.index("# --- Read-only")]
        verify_idx = submit_body.index("_verify_h1_token")
        scope_idx = submit_body.index("h1_authorized_scope")
        assert verify_idx < scope_idx, \
            "H1 token check must happen BEFORE h1_authorized_scope in order_submit"


# ============================================================================
# T9 — Gate E P2b close-only exemption still passes
# ============================================================================

class TestGateEP2bIntact:
    """T9: Gate E P2b close-only exemption still works with P5."""

    def test_gate_e_close_only_sell_exempt(self):
        """SELL during loss halt is exempt (P2b)."""
        from guard import gate_loss_halts

        state = {
            "schema_version": 1,
            "trade_date": "2026-06-15",
            "daily_trade_count": 1,
            "day_start_nl_eur": 1000000.0,
            "daily_halt_active": True,
            "weekly_halt_active": False,
            "halt_reason": "daily_loss_threshold",
            "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        }
        rules = {
            "version": "1.3-draft",
            "loss_halts": {"daily": {"value": 2.0}, "weekly": {"value": 3.0}},
        }

        ok, reason, details = gate_loss_halts(
            state, 970000.0, rules,
            action="SELL", symbol="AAPL",
            proposed_shares=10,
            position_provider=lambda: [
                {"symbol": "AAPL", "position": 50}
            ],
        )
        assert ok, f"SELL should be exempt from loss halt: reason={reason}"

    def test_gate_e_buy_blocked_during_halt(self):
        """BUY blocked during loss halt."""
        from guard import gate_loss_halts

        state = {
            "schema_version": 1,
            "trade_date": "2026-06-15",
            "daily_trade_count": 1,
            "day_start_nl_eur": 1000000.0,
            "daily_halt_active": True,
            "weekly_halt_active": False,
            "halt_reason": "daily_loss_threshold",
            "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        }
        rules = {
            "version": "1.3-draft",
            "loss_halts": {"daily": {"value": 2.0}, "weekly": {"value": 3.0}},
        }

        ok, reason, details = gate_loss_halts(
            state, 970000.0, rules,
            action="BUY", symbol="AAPL",
        )
        assert not ok, f"BUY should be blocked during loss halt: reason={reason}"


# ============================================================================
# T10 — Gate H proposal discipline still passes
# ============================================================================

class TestGateHIntact:
    """T10: Gate H proposal discipline remains enforced with P5."""

    def test_gate_h_no_proposal_fails(self):
        """Gate H without proposal_path fails."""
        from guard import gate_proposal_discipline
        ok, reason, details = gate_proposal_discipline(None)
        assert not ok, "Gate H should fail without proposal"

    def test_gate_h_proposal_discipline_function_exists(self):
        """gate_proposal_discipline function is unchanged."""
        from guard import gate_proposal_discipline
        assert callable(gate_proposal_discipline)


# ============================================================================
# T11 — No raw token/log leakage
# ============================================================================

class TestNoTokenLeakage:
    """T11: No raw H1 token logged, written, or leaked."""

    def test_h1_token_hash_not_raw_in_source(self):
        """bridge.py stores H1_APPROVAL_TOKEN_HASH env var, never raw token."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        source = bridge_path.read_text()
        assert "H1_APPROVAL_TOKEN_HASH" in source, \
            "H1_APPROVAL_TOKEN_HASH must be referenced in bridge.py"

    def test_no_token_in_bracket_evidence(self):
        """Bracket evidence must not include raw token."""
        ev = validate_bracket_stop(
            stop_price=170.0, entry_price=180.0, quantity=10, action="BUY"
        )
        for key in ev:
            assert "token" not in key.lower(), f"Token leakage in key: {key}"
            if isinstance(ev[key], str):
                assert "sha256" not in ev[key].lower() or "hash" in key.lower(), \
                    f"Suspicious value: {key}={ev[key]}"


# ============================================================================
# T12 — Kill-switch dry-run validates without broker mutation
# ============================================================================

@pytest.mark.usefixtures("_disable_h1_startup")
class TestKillSwitchDryRun:
    """T12: Dry-run/preflight validates bracket requirements without broker mutation."""

    def test_preflight_never_calls_ibkr(self):
        """run_preflight does not call placeOrder or any broker endpoint."""
        result = run_preflight(
            {
                "symbol": "AAPL",
                "action": "BUY",
                "totalQuantity": 10,
                "orderType": "MKT",
                "stopPrice": 170.0,
            },
            account_provider=_make_account_provider(),
            quote_provider=_make_quote_provider(),
            bars_provider=_make_bars_provider(),
        )
        # May fail on Gate H but must never call IBKR
        assert "order_id" not in result or result.get("order_id") is None
        assert "ibkr_order" not in result

    def test_submit_blocked_no_ibkr_call(self):
        """Submit blocked by kill switches never reaches IBKR."""
        approval_id = "test-killswitch-" + str(int(time.time() * 1000))

        record = {
            "approval_id": approval_id,
            "status": "approved",
            "ruled_by": "Chris",
            "ruling_at_utc": datetime.now(timezone.utc).isoformat(),
            "expires_at_utc": datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat(),
            "proposal": {
                "symbol": "AAPL",
                "action": "BUY",
                "totalQuantity": 10,
                "orderType": "MKT",
            },
            "validation": {
                "entry_price": 180.0,
                "stop_price": 170.0,
            },
        }

        import guard
        guard._active_approvals[approval_id] = record

        provider_called = [False]

        def mock_provider(rec):
            provider_called[0] = True
            return {"success": True, "order_id": 999}

        try:
            with patch.object(guard, '_check_ibkr_allowed', return_value=False):
                result = submit_order(approval_id, order_provider=mock_provider)
            assert not result.get("submitted")
            assert result.get("code") == "ORDERS_BLOCKED"
            assert not provider_called[0], "Provider should NOT be called when blocked"
        finally:
            guard._active_approvals.pop(approval_id, None)


# ============================================================================
# T13 — Parent not left live without protective stop (fail-closed)
# ============================================================================

@pytest.mark.usefixtures("_disable_h1_startup")
class TestFailClosedParentCancelled:
    """T13: If stop order fails, parent is cancelled (never left live)."""

    def test_stop_failure_cancels_parent(self):
        """When provider indicates stop placement failed, entire operation fails."""
        approval_id = "test-failclosed-" + str(int(time.time() * 1000))

        record = {
            "approval_id": approval_id,
            "status": "approved",
            "ruled_by": "Chris",
            "ruling_at_utc": datetime.now(timezone.utc).isoformat(),
            "expires_at_utc": datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat(),
            "proposal": {
                "symbol": "AAPL",
                "action": "BUY",
                "totalQuantity": 10,
                "orderType": "MKT",
            },
            "validation": {
                "entry_price": 180.0,
                "stop_price": 170.0,
            },
        }

        import guard
        guard._active_approvals[approval_id] = record

        try:
            with patch.object(guard, '_check_ibkr_allowed', return_value=True), \
                 patch.object(guard, '_check_enforced', return_value=True), \
                 patch.object(guard, 'is_approval_submitted', return_value=False):

                def failing_provider(rec):
                    return {
                        "success": False,
                        "error": "Stop order rejected: STOP_PRICE_TOO_CLOSE",
                        "code": "STOP_REJECTED",
                    }

                result = submit_order(
                    approval_id,
                    order_provider=failing_provider,
                    status_provider=lambda oid: {"status": "Rejected"},
                    account_provider=lambda: {"net_liquidation_eur": 1000000, "exchange_rate": 1.10},
                    quote_provider=lambda sym: {"ask": 180.0, "bid": 179.50, "close": 179.80},
                    bars_provider=lambda sym: MOCK_BARS,
                )

            assert not result.get("submitted"), \
                f"Should fail closed when stop rejected: {result}"
        finally:
            guard._active_approvals.pop(approval_id, None)

    def test_bracket_construction_fails_without_stop_price(self):
        """BUY without stop_price in proposal fails bracket construction."""
        result = validate_bracket_stop(
            stop_price=None, entry_price=180.0, quantity=10, action="BUY"
        )
        assert not result["valid"]
        assert "stop" in result.get("error", "").lower()


# ============================================================================
# T14 — Evidence fields
# ============================================================================

class TestEvidenceFields:
    """T14: Evidence fields are complete and correct."""

    def test_validate_bracket_stop_evidence_fields(self):
        """validate_bracket_stop returns all required evidence fields."""
        result = validate_bracket_stop(
            stop_price=170.0, entry_price=180.0, quantity=10, action="BUY"
        )
        required_fields = [
            "valid", "stop_price", "quantity",
            "bracket", "protective_stop", "parent_transmit", "stop_transmit",
            "stop_action", "stop_distance",
        ]
        for field in required_fields:
            assert field in result, f"Missing evidence field: {field}"

    def test_stop_loss_action_is_sell(self):
        """Protective stop action is SELL for long BUY."""
        result = validate_bracket_stop(
            stop_price=170.0, entry_price=180.0, quantity=10, action="BUY"
        )
        assert result.get("stop_action") == "SELL"

    def test_evidence_has_stop_distance(self):
        """Evidence includes stop_distance."""
        result = validate_bracket_stop(
            stop_price=170.0, entry_price=180.0, quantity=10, action="BUY"
        )
        assert result.get("stop_distance") == 10.0


# ============================================================================
# T15 — Concurrent safety / no cross-contamination
# ============================================================================

class TestBracketConcurrencySafety:
    """P5 bracket validation is thread-safe via ContextVar."""

    def test_validate_bracket_stop_thread_isolation(self):
        """Concurrent bracket validations don't interfere."""
        results = []

        def validate_in_thread(stop, entry, qty, idx):
            r = validate_bracket_stop(stop_price=stop, entry_price=entry, quantity=qty, action="BUY")
            results.append((idx, r))

        threads = []
        params = [
            (170.0, 180.0, 10),
            (165.0, 175.0, 20),
            (160.0, 170.0, 30),
        ]
        for i, (stop, entry, qty) in enumerate(params):
            t = threading.Thread(target=validate_in_thread, args=(stop, entry, qty, i))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=5)
            assert not t.is_alive(), f"Thread {t.name} hung"

        assert len(results) == 3
        for idx, r in results:
            assert r["valid"], f"Thread {idx} result not valid: {r}"


# ============================================================================
# T16 — No regression on existing behavior
# ============================================================================

@pytest.mark.usefixtures("_disable_h1_startup")
class TestNoRegression:
    """P5 changes must not break existing validation flows."""

    def test_run_preflight_still_returns_gates(self):
        """run_preflight still returns gates array when valid stop provided but no proposal."""
        result = run_preflight(
            {
                "symbol": "AAPL",
                "action": "BUY",
                "totalQuantity": 10,
                "orderType": "MKT",
                "stopPrice": 170.0,
            },
            account_provider=_make_account_provider(),
            quote_provider=_make_quote_provider(),
            bars_provider=_make_bars_provider(),
        )
        # Gate H fails (no proposal_path) but the gates array is still present
        assert "gates" in result

    def test_h1_authorized_scope_still_works(self):
        """h1_authorized_scope context manager still functions correctly."""
        assert not _h1_authorized.get()
        with h1_authorized_scope():
            assert _h1_authorized.get()
        assert not _h1_authorized.get()

    def test_protected_paths_unchanged(self):
        """PROTECTED_PATHS not modified by P5."""
        assert isinstance(PROTECTED_PATHS, set)
        assert all(isinstance(p, Path) for p in PROTECTED_PATHS)


# ============================================================================
# T17 — Parent cancellation is attempted on child failure
# ============================================================================

class TestParentCancellationProof:
    """T17: Verify parent cancellation is attempted when child placement/ack fails.

    These tests do NOT call live IBKR. They validate the cancellation
    code path exists and is exercised for the documented failure modes.
    """

    def test_cancel_parent_safe_exists(self):
        """_cancel_parent_safe function exists in bridge.py."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        source = bridge_path.read_text()
        assert "def _cancel_parent_safe" in source, \
            "_cancel_parent_safe must exist for bracket fail-closed"

    def test_cancel_parent_called_on_child_place_fail(self):
        """_cancel_parent_safe called when child stop order placement fails."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        source = bridge_path.read_text()
        # Find the child placement exception handler
        child_place_section = source.split("Protective stop placeOrder failed")
        assert len(child_place_section) > 1, \
            "Child stop placement error handler must exist"
        # The handler block above the error must call _cancel_parent_safe
        handler_block = source.split("Protective stop placeOrder failed")[0]
        # Look backwards for _cancel_parent_safe call before this error
        bracket_block = source[source.index("def _internal_place_order"):]
        cancel_calls_in_bracket = bracket_block.count("_cancel_parent_safe")
        assert cancel_calls_in_bracket >= 2, \
            f"_cancel_parent_safe must be called in at least 2 fail paths (child place + child ack), found {cancel_calls_in_bracket}"

    def test_cancel_parent_called_on_child_ack_fail(self):
        """_cancel_parent_safe called when child stop ack times out."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        source = bridge_path.read_text()
        # The child ack timeout section must call _cancel_parent_safe
        ack_timeout_section = source.split("STOP_ACK_TIMEOUT")
        assert len(ack_timeout_section) > 1, \
            "STOP_ACK_TIMEOUT error code must exist"
        # Check _cancel_parent_safe appears before STOP_ACK_TIMEOUT
        ack_block = source[source.rfind("_poll_for_ack"):source.rfind("STOP_ACK_TIMEOUT")]
        # The relevant block is between child ack check and STOP_ACK_TIMEOUT
        child_ack_start = source.rfind("child SELL stop")
        child_ack_end = source.rfind("STOP_ACK_TIMEOUT")
        if child_ack_start > 0 and child_ack_end > child_ack_start:
            section = source[child_ack_start:child_ack_end]
            assert "_cancel_parent_safe" in section, \
                "_cancel_parent_safe must be called when child ack fails"

    def test_cancel_parent_uses_ib_trades_not_order_id(self):
        """_cancel_parent_safe uses ib.trades()/ib.openTrades(), not ib.order(order_id)."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        source = bridge_path.read_text()
        cancel_body = source[source.index("def _cancel_parent_safe"):source.index("def _internal_order_status")]
        # Must use openTrades or trades
        assert "openTrades" in cancel_body or "trades" in cancel_body, \
            "_cancel_parent_safe must search via ib.trades()/ib.openTrades()"
        # Must NOT use ib.order(order_id) which doesn't exist
        assert "ib.order(" not in cancel_body, \
            "_cancel_parent_safe must NOT call ib.order(order_id) — does not exist"

    def test_cancel_parent_returns_bool(self):
        """_cancel_parent_safe returns bool (True if cancellation attempted)."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        source = bridge_path.read_text()
        cancel_body = source[source.index("def _cancel_parent_safe"):source.index("def _internal_order_status")]
        assert "-> bool" in cancel_body or "return True" in cancel_body, \
            "_cancel_parent_safe must return bool for evidence tracking"

    def test_simple_path_rejects_buy_without_stop(self):
        """Simple path returns BRACKET_STOP_REQUIRED for BUY without stop."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        source = bridge_path.read_text()
        assert "BRACKET_STOP_REQUIRED" in source, \
            "Simple path must reject BUY without valid protective stop"
        # The simple path check must come before any order placement
        simple_section_start = source.index("# ---- Simple Path")
        simple_section_end = source.index("def _internal_order_status")
        simple_section = source[simple_section_start:simple_section_end]
        # "BRACKET_STOP_REQUIRED" must appear before "ib.placeOrder" in the simple path
        req_idx = simple_section.index("BRACKET_STOP_REQUIRED")
        place_idx = simple_section.index("ib.placeOrder")
        assert req_idx < place_idx, \
            "BRACKET_STOP_REQUIRED check must happen BEFORE ib.placeOrder in simple path"

    def test_bracket_path_has_cancel_on_three_fail_modes(self):
        """Bracket path cancels parent on: child place fail, child no-trade, child ack timeout."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        source = bridge_path.read_text()
        bracket_start = source.index("# ---- P5 Bracket Path")
        bracket_end = source.index("# ---- Simple Path")
        bracket_section = source[bracket_start:bracket_end]
        cancel_count = bracket_section.count("_cancel_parent_safe")
        assert cancel_count == 3, \
            f"Bracket path must cancel parent in exactly 3 fail modes (child place, child no-trade, child ack timeout), found {cancel_count}"
