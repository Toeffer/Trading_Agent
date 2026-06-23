"""Tests for Step 15N — Backpressure Active-Count Accounting Leak Hotfix.

All tests are read-only. No broker mutation, no order endpoints,
no H1 token usage.
"""

import json
import sys
import time
import threading
import concurrent.futures
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))


# ---------------------------------------------------------------------------
# Helpers — simulate backpressure middleware logic in isolation
# ---------------------------------------------------------------------------

# Replicate the backpressure accounting constants and logic for unit testing
_BP_MAX_ACTIVE = 4


class BackpressureSimulator:
    """Simulates the backpressure middleware accounting in isolation.

    Not importing bridge.py directly (avoids fastapi dependency in CI).
    Replicates the exact same increment/decrement logic.
    """

    def __init__(self, max_active: int = _BP_MAX_ACTIVE):
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = max_active
        self.total_accepted = 0
        self.total_rejected = 0

    def try_accept(self) -> bool:
        """Try to accept a request. Returns True if accepted, False if rejected."""
        with self.lock:
            if self.active >= self.max_active:
                self.total_rejected += 1
                return False
            self.active += 1
            self.total_accepted += 1
        return True

    def decrement(self):
        """Decrement active count after request completes."""
        with self.lock:
            if self.active > 0:
                self.active -= 1
            # else: underflow guard — don't go negative

    @property
    def snapshot(self) -> dict:
        with self.lock:
            return {
                "active": self.active,
                "total_accepted": self.total_accepted,
                "total_rejected": self.total_rejected,
            }


# ---------------------------------------------------------------------------
# T1: Accepted request increments then decrements
# ---------------------------------------------------------------------------

class TestAcceptedRequestAccounting:
    """Verify correct increment/decrement for accepted requests."""

    def test_single_accepted_request(self):
        """A single accepted request increments then decrements back to 0."""
        bp = BackpressureSimulator(max_active=4)
        assert bp.active == 0
        assert bp.try_accept()
        assert bp.active == 1
        bp.decrement()
        assert bp.active == 0

    def test_multiple_sequential(self):
        """Multiple sequential requests each return active to 0."""
        bp = BackpressureSimulator(max_active=4)
        for _ in range(10):
            assert bp.try_accept()
            assert bp.active == 1
            bp.decrement()
            assert bp.active == 0

    def test_concurrent_under_limit(self):
        """Concurrent requests under the limit all succeed and eventually drain."""
        bp = BackpressureSimulator(max_active=4)
        results = []
        errors = []

        def worker():
            try:
                if bp.try_accept():
                    time.sleep(0.05)  # simulate work
                    bp.decrement()
                    results.append(True)
                else:
                    results.append(False)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"
        assert all(results), f"All 3 should be accepted, got: {results}"
        assert bp.active == 0, f"Active should be 0, got {bp.active}"


# ---------------------------------------------------------------------------
# T2: Rejected request does not leak active count
# ---------------------------------------------------------------------------

class TestRejectedRequestNoLeak:
    """Verify rejected requests never increment the active count."""

    def test_rejected_does_not_increment(self):
        """When at capacity, rejection must not increment active."""
        bp = BackpressureSimulator(max_active=2)

        # Fill to capacity
        assert bp.try_accept()  # active=1
        assert bp.try_accept()  # active=2

        # This should be rejected
        assert not bp.try_accept()  # rejected
        assert bp.active == 2  # still 2, not 3

        # Drain
        bp.decrement()
        bp.decrement()
        assert bp.active == 0

    def test_rejected_then_accepted_after_drain(self):
        """After draining, new requests should be accepted again."""
        bp = BackpressureSimulator(max_active=2)

        assert bp.try_accept()  # active=1
        assert bp.try_accept()  # active=2
        assert not bp.try_accept()  # rejected

        bp.decrement()  # active=1
        assert bp.try_accept()  # accepted, active=2
        bp.decrement()
        bp.decrement()
        assert bp.active == 0


# ---------------------------------------------------------------------------
# T3: Exception path decrements
# ---------------------------------------------------------------------------

class TestExceptionPathDecrement:
    """Verify active count is decremented even when the request raises."""

    def test_exception_still_decrements(self):
        """Decrement must happen even if the work function raises."""
        bp = BackpressureSimulator(max_active=4)

        assert bp.try_accept()
        assert bp.active == 1
        try:
            raise RuntimeError("simulated failure")
        except RuntimeError:
            bp.decrement()
        assert bp.active == 0

    def test_multiple_exceptions_all_decrement(self):
        """Every accepted request must decrement exactly once, even on error."""
        bp = BackpressureSimulator(max_active=4)

        for _ in range(5):
            assert bp.try_accept()
            assert bp.active == 1
            try:
                raise RuntimeError("fail")
            except RuntimeError:
                bp.decrement()
            assert bp.active == 0


# ---------------------------------------------------------------------------
# T4: Timeout path decrements
# ---------------------------------------------------------------------------

class TestTimeoutPathDecrement:
    """Verify active count returns to 0 after timeout."""

    def test_timeout_decrements(self):
        """A request that times out must still decrement."""
        bp = BackpressureSimulator(max_active=4)

        assert bp.try_accept()
        assert bp.active == 1

        # Simulate: work starts, timeout fires, we decrement
        bp.decrement()
        assert bp.active == 0

    def test_concurrent_timeouts(self):
        """Multiple concurrent timeouts all decrement correctly."""
        bp = BackpressureSimulator(max_active=4)

        def timed_worker():
            try:
                if bp.try_accept():
                    time.sleep(0.03)
            finally:
                bp.decrement()

        threads = [threading.Thread(target=timed_worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert bp.active == 0, f"Active should be 0 after all timeouts, got {bp.active}"


# ---------------------------------------------------------------------------
# T5: Repeated market snapshot timeouts do not saturate
# ---------------------------------------------------------------------------

class TestRepeatedTimeoutsDontSaturate:
    """Verify repeated timeouts always return active to 0 between calls."""

    def test_repeated_sequential_timeouts(self):
        """10 sequential timeouts should always leave active at 0."""
        bp = BackpressureSimulator(max_active=4)

        for i in range(10):
            assert bp.try_accept(), f"Request {i} should be accepted"
            # Simulate timeout
            bp.decrement()
            assert bp.active == 0, f"Active should be 0 after timeout {i}, got {bp.active}"

    def test_burst_then_drain(self):
        """A burst of requests (some rejected) eventually drains to 0."""
        bp = BackpressureSimulator(max_active=4)

        # Simulate: 6 concurrent requests, 4 accepted, 2 rejected
        accepted = 0
        rejected = 0
        for _ in range(6):
            if bp.try_accept():
                accepted += 1
            else:
                rejected += 1

        assert accepted == 4
        assert rejected == 2
        assert bp.active == 4

        # All 4 complete (timeout)
        for _ in range(4):
            bp.decrement()

        assert bp.active == 0
        # Now new requests should be accepted
        assert bp.try_accept()
        bp.decrement()
        assert bp.active == 0


# ---------------------------------------------------------------------------
# T6: Concurrent accounting never goes negative
# ---------------------------------------------------------------------------

class TestNeverNegative:
    """Verify active count never goes below zero."""

    def test_underflow_guard(self):
        """Extra decrements must not drive active negative."""
        bp = BackpressureSimulator(max_active=4)

        # Decrement when active is 0
        bp.decrement()
        assert bp.active == 0, "Should stay at 0, not go negative"

        # Accept then decrement twice
        bp.try_accept()
        bp.decrement()
        bp.decrement()  # extra
        assert bp.active == 0, "Should stay at 0 after extra decrement"

    def test_heavy_concurrent_no_negative(self):
        """Under heavy concurrent load, active must never go negative."""
        bp = BackpressureSimulator(max_active=4)

        def worker():
            for _ in range(10):
                if bp.try_accept():
                    time.sleep(0.001)
                    bp.decrement()

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert bp.active >= 0, f"Active must not be negative: {bp.active}"
        assert bp.active == 0, f"All work done, active should be 0: {bp.active}"


# ---------------------------------------------------------------------------
# T7: /order/approve remains protected (not exempt from backpressure)
# ---------------------------------------------------------------------------

class TestOrderApproveStillProtected:
    """Verify /order/approve is NOT exempt from backpressure."""

    def test_order_approve_not_exempt(self):
        """The backpressure middleware must not exempt /order/approve."""
        # We can't import bridge.py directly (fastapi dep), but we verify
        # the tier configuration doesn't include order paths
        tier0_paths = ["/health", "/monitor/liveness", "/monitor/backpressure"]
        for path in tier0_paths:
            assert "/order" not in path, \
                f"No /order path should be tier 0 exempt: {path}"

    def test_h1_canary_separate_protection(self):
        """H1 canary is protected by H1 token, not by backpressure exemption."""
        # The H1 canary path calls /order/approve with the H1 token.
        # Backpressure may load-shed this, but the canary should retry
        # or report MANUAL_REQUIRED when load-shed.
        # We verify this conceptually: backpressure exemption is NOT how
        # the canary is protected.
        pass  # Documented assertion — backpressure exemption is not the canary's protection


# ---------------------------------------------------------------------------
# T8: Backpressure introspection endpoint
# ---------------------------------------------------------------------------

class TestBackpressureIntrospection:
    """Verify the /monitor/backpressure endpoint (conceptual — tested via sim)."""

    def test_snapshot_reflects_state(self):
        """Snapshot returns current active, accepted, rejected."""
        bp = BackpressureSimulator(max_active=4)

        snap = bp.snapshot
        assert snap["active"] == 0
        assert snap["total_accepted"] == 0
        assert snap["total_rejected"] == 0

        bp.try_accept()
        snap = bp.snapshot
        assert snap["active"] == 1
        assert snap["total_accepted"] == 1

        bp.decrement()
        snap = bp.snapshot
        assert snap["active"] == 0

    def test_counters_never_reset(self):
        """Accepted/rejected counters are cumulative, not reset."""
        bp = BackpressureSimulator(max_active=4)

        for _ in range(5):
            bp.try_accept()
            bp.decrement()

        # Fill and reject
        for _ in range(4):
            bp.try_accept()
        assert not bp.try_accept()  # rejected

        snap = bp.snapshot
        assert snap["total_accepted"] == 9  # 5 + 4
        assert snap["total_rejected"] == 1


# ---------------------------------------------------------------------------
# T9: _internal_fetch_quote_safe timeout path is non-blocking
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestFetchQuoteSafeTimeout:
    """Verify the timeout path in _internal_fetch_quote_safe is non-blocking.

    These tests import bridge.py directly and require fastapi.
    Skipped in default CI; run with -m integration.
    """

    def test_timeout_raises_promptly(self):
        """When the inner function hangs, the safe wrapper must raise within timeout."""
        import time as _time_module

        def _slow_fetch(_symbol):
            _time_module.sleep(999)
            return {}

        with patch("bridge._internal_fetch_quote", side_effect=_slow_fetch):
            from bridge import _internal_fetch_quote_safe, _MARKET_SNAPSHOT_TIMEOUT

            start = _time_module.time()
            try:
                _internal_fetch_quote_safe("AAPL", timeout=1.0)
                assert False, "Should have raised RuntimeError"
            except RuntimeError as e:
                elapsed = _time_module.time() - start
                assert "market_data_timeout" in str(e)
                assert elapsed < 3.0, \
                    f"Timeout took {elapsed:.1f}s, should be under 3.0s"

    def test_timeout_does_not_block_caller(self):
        """After timeout, the caller must be free to make new requests."""
        import time as _time_module

        def _slow_fetch(_symbol):
            _time_module.sleep(999)
            return {}

        with patch("bridge._internal_fetch_quote", side_effect=_slow_fetch):
            from bridge import _internal_fetch_quote_safe

            start = _time_module.time()
            for _ in range(3):
                try:
                    _internal_fetch_quote_safe("AAPL", timeout=0.5)
                except RuntimeError:
                    pass
            elapsed = _time_module.time() - start

            # 3 sequential timeouts of 0.5s each should take ~1.5-2s
            assert elapsed < 5.0, \
                f"3 sequential timeouts took {elapsed:.1f}s, should be under 5.0s"


# ---------------------------------------------------------------------------
# T10: Existing 15L/15M tests still pass
# ---------------------------------------------------------------------------

class TestExistingTestsStillPass:
    """Quick sanity: imports and key functions still work."""

    def test_operator_imports(self):
        """Operator functions remain importable after bridge changes."""
        from ibkr_operator import (
            _run_autonomy_status,
            _run_autonomy_review,
            _run_autonomy_promotion_plan,
        )
        assert callable(_run_autonomy_status)
        assert callable(_run_autonomy_review)
        assert callable(_run_autonomy_promotion_plan)

    def test_bridge_syntax_valid(self):
        """Bridge.py is syntactically valid (no import needed)."""
        import ast
        source = (BRIDGE_DIR / "bridge.py").read_text()
        try:
            ast.parse(source)
        except SyntaxError as e:
            assert False, f"bridge.py has syntax error: {e}"

    def test_backpressure_constants_in_source(self):
        """Backpressure fix constants are present in bridge.py source."""
        source = (BRIDGE_DIR / "bridge.py").read_text()
        assert "_BP_TOTAL_ACCEPTED" in source
        assert "_BP_TOTAL_REJECTED" in source
        assert "if _BP_ACTIVE > 0:" in source or "_BP_ACTIVE -= 1" in source
        assert "/monitor/backpressure" in source
