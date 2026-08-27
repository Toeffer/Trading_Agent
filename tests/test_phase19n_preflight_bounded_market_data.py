"""Tests for Phase 19N — bound the quote/bars fetch in the order lifecycle
so it can never hang preflight, dry-run, or submit-time revalidation
(2026-08-27).

Live incident: /order/preflight hung past 75s with zero response and no
access-log line at all (uvicorn only logs after the handler returns, so
this proved the handler was blocked mid-flight, not that the request never
arrived). Root cause, traced against this exact checkout:

  bridge.py's order_preflight() wired guard.run_preflight()'s
  quote_provider/bars_provider to the *unbounded* _internal_fetch_quote /
  _internal_fetch_bars. Both call ib.qualifyContracts(), a synchronous IBKR
  round-trip with no deadline -- against a stalled/slow Gateway this blocks
  forever. guard.run_preflight()'s except clause around the fetch only
  catches (RuntimeError, ValueError, FileNotFoundError); a blocked ib call
  raises nothing, so nothing was ever available to catch. Preflight hung
  before any gate ever ran, with no exception and no log line.

  _internal_fetch_quote_safe already existed (Step 15L-B/15N) as exactly
  the right bounded pattern -- a thread executor with future.result(timeout=...),
  raising RuntimeError("market_data_timeout: ...") on timeout -- but was
  never wired into order_preflight(). No bars equivalent existed at all.
  The same unbounded pair was also wired into /order/submit's revalidation
  (guard.revalidate_before_submit, invariant #5) and /order/dry-run's
  internal preflight call -- same bug, two more places.

Fix: added _internal_fetch_bars_safe (mirrors _internal_fetch_quote_safe
exactly) and re-wired all three call sites to the _safe variants. No
guard.py change was needed: run_preflight()'s except clause already catches
RuntimeError, and revalidate_before_submit()'s quote/bars except clauses
already catch RuntimeError specifically -- the _safe wrappers' timeout
RuntimeError slots into existing, already-correct handling.

This file has two tiers:
  - Non-integration source-regression tests (run in the curated CI suite,
    no fastapi/ib_insync needed) -- prove the fix is actually wired in, not
    just present as a dead function.
  - A guard.py-only behavioral test (also runs in curated CI, no bridge.py
    import needed) -- proves the exact failure mode is fixed: a
    quote_provider/bars_provider that raises RuntimeError (what the _safe
    wrappers do on timeout) must produce a clean, non-hanging, non-raising
    preflight response, not an uncaught exception.
  - @pytest.mark.integration tests mirroring
    test_step15n_backpressure_leak.py's TestFetchQuoteSafeTimeout exactly,
    but for the new _internal_fetch_bars_safe -- import bridge.py directly,
    require fastapi, skipped in default CI.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

import guard  # noqa: E402
from guard import run_preflight  # noqa: E402


BRIDGE_SOURCE = (BRIDGE_DIR / "bridge.py").read_text()


# ---------------------------------------------------------------------------
# T1: Source regression -- the bounded wrappers exist and are actually wired
# in at all three call sites, not just present as dead functions.
# ---------------------------------------------------------------------------

class TestBoundedProvidersAreWiredIn:
    def test_bridge_syntax_valid(self):
        """bridge.py is still syntactically valid (no fastapi import needed)."""
        import ast
        try:
            ast.parse(BRIDGE_SOURCE)
        except SyntaxError as e:
            assert False, f"bridge.py has a syntax error: {e}"

    def test_internal_fetch_bars_safe_exists(self):
        assert "def _internal_fetch_bars_safe(" in BRIDGE_SOURCE

    def test_no_unbounded_provider_wiring_remains(self):
        """No call site may wire the raw (unbounded) fetch functions as
        providers any more -- every "if is_connected()" wiring for
        quote_provider/bars_provider must use the _safe variants."""
        assert "quote_provider=_internal_fetch_quote if" not in BRIDGE_SOURCE, (
            "An unbounded quote_provider wiring survived the Phase 19N fix"
        )
        assert "bars_provider=_internal_fetch_bars if" not in BRIDGE_SOURCE, (
            "An unbounded bars_provider wiring survived the Phase 19N fix"
        )

    def test_preflight_endpoint_uses_safe_providers(self):
        idx = BRIDGE_SOURCE.index("def order_preflight(")
        snippet = BRIDGE_SOURCE[idx: idx + 1500]
        assert "quote_provider=_internal_fetch_quote_safe" in snippet
        assert "bars_provider=_internal_fetch_bars_safe" in snippet

    def test_submit_endpoint_uses_safe_providers(self):
        # submit_order(...) is called from the /order/submit handler; search
        # for the specific call rather than a function def since it's an
        # inline call inside the endpoint body.
        idx = BRIDGE_SOURCE.index("result = submit_order(")
        snippet = BRIDGE_SOURCE[idx: idx + 500]
        assert "quote_provider=_internal_fetch_quote_safe" in snippet
        assert "bars_provider=_internal_fetch_bars_safe" in snippet

    def test_dry_run_endpoint_uses_safe_providers(self):
        idx = BRIDGE_SOURCE.index("preflight = run_preflight(")
        snippet = BRIDGE_SOURCE[idx: idx + 500]
        assert "quote_provider=_internal_fetch_quote_safe" in snippet
        assert "bars_provider=_internal_fetch_bars_safe" in snippet

    def test_bars_safe_mirrors_quote_safe_timeout_pattern(self):
        """The new wrapper must actually bound the call (thread executor +
        future.result(timeout=...)), not just exist as a same-named
        passthrough."""
        idx = BRIDGE_SOURCE.index("def _internal_fetch_bars_safe(")
        snippet = BRIDGE_SOURCE[idx: idx + 2500]
        assert "ThreadPoolExecutor" in snippet
        assert "future.result(timeout=timeout)" in snippet
        assert "concurrent.futures.TimeoutError" in snippet
        assert "raise RuntimeError" in snippet
        assert "market_data_timeout" in snippet
        assert "executor.shutdown(wait=False)" in snippet

    def test_bars_fetch_still_decrements_leaked_thread_counter(self):
        """Symmetric with _internal_fetch_quote: a bars fetch that
        eventually completes after its caller already timed out must still
        decrement the shared leaked-thread counter, or it grows unbounded
        across repeated bars timeouts."""
        idx = BRIDGE_SOURCE.index("def _internal_fetch_bars(")
        end_idx = BRIDGE_SOURCE.index("def _internal_fetch_bars_safe(")
        snippet = BRIDGE_SOURCE[idx:end_idx]
        assert "_decrement_leaked_md_thread()" in snippet


# ---------------------------------------------------------------------------
# T2: guard.py behavior -- a provider that raises RuntimeError (exactly what
# the _safe wrappers do on timeout) must be handled gracefully by
# run_preflight(), never propagate, never hang. Pure guard.py -- no bridge.py
# import, no fastapi needed, runs in the curated suite.
# ---------------------------------------------------------------------------

def _raise_market_data_timeout(symbol: str):
    raise RuntimeError(f"market_data_timeout: market data did not arrive within 8s")


class TestRunPreflightHandlesTimeoutGracefully:
    def test_quote_timeout_produces_clean_failure_not_a_raise(self):
        with patch("guard.load_guard_state", return_value={
                "trade_date": guard.canonical_trade_date(), "daily_trade_count": 0,
                "week_start_date": guard._current_week_monday_utc_str(),
                "week_start_nl_eur": 1_000_000.0,
            }), \
             patch("guard.load_rules", return_value={
                 "symbol_allowlist": {"allow": ["AAPL"]},
                 "max_trades_per_day": {"value": 2},
             }):
            result = run_preflight(
                {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1,
                 "orderType": "MKT", "mode": "paper"},
                account_provider=lambda: {"net_liquidation_eur": 1_000_000.0,
                                           "exchange_rate": 1.08},
                quote_provider=_raise_market_data_timeout,
                bars_provider=lambda symbol: [],
            )

        assert isinstance(result, dict)
        assert result["passed"] is False
        assert "market_data_timeout" in result.get("error", "")

    def test_bars_timeout_produces_clean_failure_not_a_raise(self):
        with patch("guard.load_guard_state", return_value={
                "trade_date": guard.canonical_trade_date(), "daily_trade_count": 0,
                "week_start_date": guard._current_week_monday_utc_str(),
                "week_start_nl_eur": 1_000_000.0,
            }), \
             patch("guard.load_rules", return_value={
                 "symbol_allowlist": {"allow": ["AAPL"]},
                 "max_trades_per_day": {"value": 2},
             }):
            result = run_preflight(
                {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1,
                 "orderType": "MKT", "mode": "paper"},
                account_provider=lambda: {"net_liquidation_eur": 1_000_000.0,
                                           "exchange_rate": 1.08},
                quote_provider=lambda symbol: {"ask": 200.0, "bid": 199.9, "last": 200.0},
                bars_provider=_raise_market_data_timeout,
            )

        assert isinstance(result, dict)
        assert result["passed"] is False
        assert "market_data_timeout" in result.get("error", "")


# ---------------------------------------------------------------------------
# T3: Integration -- _internal_fetch_bars_safe's own timeout behavior,
# mirroring test_step15n_backpressure_leak.py's TestFetchQuoteSafeTimeout.
# Imports bridge.py directly; requires fastapi. Skipped in default CI.
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestFetchBarsSafeTimeout:
    """Verify the timeout path in _internal_fetch_bars_safe is non-blocking."""

    def test_timeout_raises_promptly(self):
        import time as _time_module

        def _slow_fetch(_symbol):
            _time_module.sleep(999)
            return []

        with patch("bridge._internal_fetch_bars", side_effect=_slow_fetch):
            from bridge import _internal_fetch_bars_safe

            start = _time_module.time()
            try:
                _internal_fetch_bars_safe("AAPL", timeout=1.0)
                assert False, "Should have raised RuntimeError"
            except RuntimeError as e:
                elapsed = _time_module.time() - start
                assert "market_data_timeout" in str(e)
                assert elapsed < 3.0, \
                    f"Timeout took {elapsed:.1f}s, should be under 3.0s"

    def test_timeout_does_not_block_caller(self):
        import time as _time_module

        def _slow_fetch(_symbol):
            _time_module.sleep(999)
            return []

        with patch("bridge._internal_fetch_bars", side_effect=_slow_fetch):
            from bridge import _internal_fetch_bars_safe

            start = _time_module.time()
            for _ in range(3):
                try:
                    _internal_fetch_bars_safe("AAPL", timeout=0.5)
                except RuntimeError:
                    pass
            elapsed = _time_module.time() - start

            assert elapsed < 5.0, \
                f"3 sequential timeouts took {elapsed:.1f}s, should be under 5.0s"

    def test_order_preflight_returns_promptly_under_stalled_gateway(self):
        """End-to-end: with both fetches simulated as hung, the /order/preflight
        handler's own run_preflight() call must return a clean failure well
        under the old ~75s+ hang, not time out the test."""
        import time as _time_module

        def _slow_quote(_symbol):
            _time_module.sleep(999)
            return {}

        def _slow_bars(_symbol):
            _time_module.sleep(999)
            return []

        with patch("bridge._internal_fetch_quote", side_effect=_slow_quote), \
             patch("bridge._internal_fetch_bars", side_effect=_slow_bars), \
             patch("guard.load_guard_state", return_value={
                 "trade_date": guard.canonical_trade_date(), "daily_trade_count": 0,
                 "week_start_date": guard._current_week_monday_utc_str(),
                 "week_start_nl_eur": 1_000_000.0,
             }), \
             patch("guard.load_rules", return_value={
                 "symbol_allowlist": {"allow": ["AAPL"]},
                 "max_trades_per_day": {"value": 2},
             }):
            from bridge import _internal_fetch_quote_safe, _internal_fetch_bars_safe

            start = _time_module.time()
            result = run_preflight(
                {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1,
                 "orderType": "MKT", "mode": "paper"},
                account_provider=lambda: {"net_liquidation_eur": 1_000_000.0,
                                           "exchange_rate": 1.08},
                quote_provider=lambda s: _internal_fetch_quote_safe(s, timeout=1.0),
                bars_provider=lambda s: _internal_fetch_bars_safe(s, timeout=1.0),
            )
            elapsed = _time_module.time() - start

        assert isinstance(result, dict)
        assert result["passed"] is False
        assert elapsed < 5.0, \
            f"preflight took {elapsed:.1f}s against a stalled Gateway -- should be bounded, not hang"
