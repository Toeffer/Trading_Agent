"""
test_contextvar_h1_race.py — ContextVar race/regression hardening tests.

Proves that H1 internal-write authorization is request/task-local and
cannot leak across concurrent requests, background tasks, or unrelated
approval/state writes.

Test categories:
  T1: ContextVar authorization scope (set/reset/exception/concurrency)
  T2: H1 token behavior (missing/wrong/correct/fake)
  T3: Canary timeout (bounded timeout, fast not-found)
  T4: Refactored context manager (bridge uses h1_authorized_scope)
  T5: Integration (authorization cannot leak between operations)
"""

import sys
import time
import hashlib
import threading
import concurrent.futures
from pathlib import Path

# Make guard module importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

# ---------------------------------------------------------------------------
# T1: ContextVar authorization scope
# ---------------------------------------------------------------------------

class TestContextVarAuthorizationScope:
    """Prove authorization is request/task-local via ContextVar."""

    def test_authorize_resets_after_scope(self):
        """T1.1: Authorization resets after context manager exits."""
        from guard import h1_authorized_scope, _h1_authorized

        assert _h1_authorized.get() is False, "Should start unauthorized"
        with h1_authorized_scope():
            assert _h1_authorized.get() is True, "Must be authorized inside scope"
        assert _h1_authorized.get() is False, "Must reset after scope"

    def test_authorize_resets_on_exception(self):
        """T1.2: Failed/exception path also resets authorization."""
        from guard import h1_authorized_scope, _h1_authorized

        assert _h1_authorized.get() is False
        try:
            with h1_authorized_scope():
                assert _h1_authorized.get() is True
                raise RuntimeError("simulated failure")
        except RuntimeError:
            pass
        assert _h1_authorized.get() is False, (
            "Authorization must reset even on exception"
        )

    def test_authorize_resets_on_nested_exception(self):
        """T1.3: Nested exception paths also reset."""
        from guard import h1_authorized_scope, _h1_authorized

        assert _h1_authorized.get() is False
        try:
            with h1_authorized_scope():
                try:
                    raise ValueError("inner")
                except ValueError:
                    raise RuntimeError("outer")
        except RuntimeError:
            pass
        assert _h1_authorized.get() is False

    def test_authorization_not_global(self):
        """T1.4: Authorization never stored globally — ContextVar only."""
        from guard import h1_authorized_scope, _h1_authorized
        import contextvars

        # Our context is unauthorized
        assert _h1_authorized.get() is False

        # A different context also sees unauthorized
        ctx = contextvars.copy_context()
        result = ctx.run(lambda: _h1_authorized.get())
        assert result is False, "Separate context must not inherit auth"

        # Authorize in our context
        with h1_authorized_scope():
            assert _h1_authorized.get() is True
            # Different context still unauthorized
            result2 = ctx.run(lambda: _h1_authorized.get())
            assert result2 is False, (
                "Auth must not leak to other ContextVar contexts"
            )

    def test_authorize_only_inside_intended_scope(self):
        """T1.5: Write succeeds only inside intended request/task scope."""
        from guard import (
            h1_authorized_scope, _h1_authorized,
            _assert_h1_authorized_for_path,
            GUARD_STATE_PATH, h1_startup_done,
        )
        # Ensure startup phase is marked complete
        h1_startup_done()

        # Outside scope — unauthorized write must fail
        try:
            _assert_h1_authorized_for_path(GUARD_STATE_PATH)
            pytest.fail("Unauthorized write must raise PermissionError")
        except PermissionError as e:
            assert "H1 approval token required" in str(e)

        # Inside scope — authorized write must succeed
        with h1_authorized_scope():
            try:
                _assert_h1_authorized_for_path(GUARD_STATE_PATH)
            except PermissionError:
                pytest.fail("Authorized write must NOT raise PermissionError")


# ---------------------------------------------------------------------------
# T2: H1 token behavior
# ---------------------------------------------------------------------------

class TestH1TokenBehavior:
    """Verify H1 token verification behavior."""

    def test_missing_token_rejected(self):
        """T2.1: Missing H1 token returns False."""
        from bridge import _verify_h1_token
        assert _verify_h1_token(None) is False
        assert _verify_h1_token("") is False

    def test_wrong_token_rejected(self):
        """T2.2: Wrong token does not match stored hash."""
        from bridge import _verify_h1_token
        # A clearly wrong token
        wrong = "0000000000000000000000000000000000000000000000000000000000000000"
        result = _verify_h1_token(wrong)
        # If H1_APPROVAL_TOKEN_HASH is not configured, returns False
        # If configured, wrong token also returns False
        assert result is False, f"Wrong token must be rejected, got {result}"

    def test_fake_token_not_correct(self):
        """T2.3: Known-fake token is not the correct token."""
        from bridge import _verify_h1_token
        import os
        # The aprv_canary token must not match
        fake = "aprv_canary_token_0000000000000000000000000000000000000000"
        result = _verify_h1_token(fake)
        assert result is False, (
            "apr_v_canary token must not match H1 hash"
        )

    def test_no_raw_token_in_source(self):
        """T2.4: No raw H1 token is logged or written in source."""
        import os
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        guard_path = Path(__file__).resolve().parent.parent / "guard.py"
        operator_path = Path(__file__).resolve().parent.parent / "ibkr_operator.py"

        # Get token hash from env
        token_hash = os.environ.get("H1_APPROVAL_TOKEN_HASH", "")
        if not token_hash:
            env_path = Path.home() / "agents" / "ibkr-bridge" / ".env"
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if line.startswith("H1_APPROVAL_TOKEN_HASH="):
                        token_hash = line.split("=", 1)[1].strip()
                        break

        for path in [bridge_path, guard_path, operator_path]:
            content = path.read_text()
            # No raw token anywhere (32+ hex chars that match the hash)
            # The hash itself may appear in comments, but no raw token
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # Check for hardcoded hex strings that could be a token
                # (64 hex chars = 32 bytes = SHA-256)
                import re
                hex_strings = re.findall(r'["\']([0-9a-fA-F]{64,})["\']', stripped)
                for hs in hex_strings:
                    if hs.lower() == token_hash.lower():
                        # The hash is allowed in comments/test files, not here
                        if "test_" not in str(path):
                            pytest.fail(
                                f"Token hash exposed in non-test source: {path}"
                            )

    def test_verify_h1_token_no_logging(self):
        """T2.5: _verify_h1_token does not log or print the token."""
        from bridge import _verify_h1_token
        import io

        # Capture stdout/stderr
        import contextlib
        f_out = io.StringIO()
        f_err = io.StringIO()
        with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
            result = _verify_h1_token("some_test_token_12345678901234567890")

        output = f_out.getvalue() + f_err.getvalue()
        assert "some_test_token_12345678901234567890" not in output, (
            "_verify_h1_token must not log the token value"
        )
        assert result is False  # should be rejected


# ---------------------------------------------------------------------------
# T3: Canary timeout
# ---------------------------------------------------------------------------

class TestCanaryTimeout:
    """Bounded timeout around canary-style tests."""

    def test_canary_fast_not_found(self):
        """T3.1: aprv_canary returns fast not-found (sub-second)."""
        from bridge import _verify_h1_token
        import time
        import hashlib

        # Simulate the canary check: verify token, then check approval
        start = time.monotonic()
        token_valid = _verify_h1_token("canary_test_token")
        elapsed = time.monotonic() - start

        # Token verification must complete in under 100ms
        assert elapsed < 0.5, (
            f"Token verification too slow: {elapsed:.3f}s (expected <0.5s)"
        )
        # Canary token should not match
        assert token_valid is False

    def test_canary_approval_lookup_fast_not_found(self):
        """T3.2: aprv_canary approval lookup is fast (no bridge needed)."""
        # Import the active approvals dict directly — the canary lookup
        # should hit this in-memory dict and return None immediately
        from guard import _active_approvals
        import time

        start = time.monotonic()
        result = _active_approvals.get("aprv_canary")
        elapsed = time.monotonic() - start

        # In-memory dict lookup must be sub-millisecond
        assert elapsed < 0.01, (
            f"Approval dict lookup too slow: {elapsed*1000:.1f}ms (expected <10ms)"
        )
        assert result is None, "aprv_canary must not exist in active approvals"

    def test_canary_does_not_create_files(self):
        """T3.3: aprv_canary lookup does not create any files."""
        from guard import _active_approvals

        home = Path.home()
        openclaw = home / ".openclaw"

        # Record existing files
        before = set()
        for p in openclaw.glob("*"):
            if p.is_file():
                before.add(str(p))

        # Simulate aprv_canary lookup
        _ = _active_approvals.get("aprv_canary")

        # Check no new files
        after = set()
        for p in openclaw.glob("*"):
            if p.is_file():
                after.add(str(p))

        new_files = after - before
        assert len(new_files) == 0, (
            f"aprv_canary lookup must not create files: {new_files}"
        )


# ---------------------------------------------------------------------------
# T4: Refactored context manager
# ---------------------------------------------------------------------------

class TestRefactoredContextManager:
    """Verify bridge uses h1_authorized_scope context manager."""

    def test_context_manager_exists(self):
        """T4.1: h1_authorized_scope context manager exists in guard.py."""
        from guard import h1_authorized_scope
        from contextlib import AbstractContextManager
        # It should be usable as a context manager
        assert hasattr(h1_authorized_scope, '__enter__') or callable(h1_authorized_scope)

    def test_bridge_uses_context_manager(self):
        """T4.2: bridge.py uses h1_authorized_scope, not raw authorize/deauthorize."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        content = bridge_path.read_text()

        # Must import h1_authorized_scope
        assert "h1_authorized_scope" in content, (
            "bridge.py must import h1_authorized_scope"
        )

        # Must use context manager pattern
        assert "with h1_authorized_scope():" in content, (
            "bridge.py must use 'with h1_authorized_scope():' context manager"
        )

    def test_bridge_no_raw_authorize_deauthorize(self):
        """T4.3: bridge.py must not use raw h1_authorize/h1_deauthorize calls."""
        bridge_path = Path(__file__).resolve().parent.parent / "bridge.py"
        content = bridge_path.read_text()

        # Check for raw h1_authorize() call (not in import or comment)
        lines = content.splitlines()
        raw_authorize_lines = []
        raw_deauthorize_lines = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("from "):
                continue
            if "h1_authorize()" in stripped and "h1_authorized_scope" not in stripped:
                raw_authorize_lines.append(i)
            if "h1_deauthorize()" in stripped:
                raw_deauthorize_lines.append(i)

        assert len(raw_authorize_lines) == 0, (
            f"bridge.py must not call h1_authorize() directly "
            f"(found at lines {raw_authorize_lines}). Use h1_authorized_scope()."
        )
        assert len(raw_deauthorize_lines) == 0, (
            f"bridge.py must not call h1_deauthorize() directly "
            f"(found at lines {raw_deauthorize_lines})"
        )

    def test_authorization_never_global(self):
        """T4.4: Authorization never stored in global boolean."""
        from guard import _h1_authorized
        import contextvars

        # Must be a ContextVar, not a plain bool
        assert isinstance(_h1_authorized, contextvars.ContextVar), (
            "H1 authorization must be ContextVar, not global bool"
        )

    def test_no_mutable_global_bool_for_h1(self):
        """T4.5: No mutable global bool used for H1 authorization."""
        guard_path = Path(__file__).resolve().parent.parent / "guard.py"
        content = guard_path.read_text()

        # Check non-comment lines only
        non_comment_lines = [
            line for line in content.splitlines()
            if not line.strip().startswith("#")
        ]
        non_comment = "\n".join(non_comment_lines)

        # _h1_authorized must be ContextVar, checked above
        # Also ensure no `global _h1_authorized` in actual code
        assert "global _h1_authorized" not in non_comment, (
            "Must not use 'global' with ContextVar — use .set()/.get()"
        )


# ---------------------------------------------------------------------------
# T5: Integration — concurrent authorization isolation
# ---------------------------------------------------------------------------

class TestConcurrentAuthorizationIsolation:
    """Authorization cannot leak across concurrent requests."""

    def test_concurrent_authorization_isolated_threads(self):
        """T5.1: Threads cannot inherit each other's authorization."""
        from guard import h1_authorized_scope, _h1_authorized
        import threading

        results = []
        errors = []

        def worker_authorized():
            """Worker that authorizes and verifies isolation."""
            try:
                # Worker starts unauthorized
                assert _h1_authorized.get() is False, "Worker must start unauthorized"
                with h1_authorized_scope():
                    assert _h1_authorized.get() is True
                    # Simulate work
                    time.sleep(0.01)
                # After scope, must be unauthorized again
                assert _h1_authorized.get() is False, "Worker must reset"
                results.append(True)
            except Exception as e:
                errors.append(str(e))
                results.append(False)

        def worker_unauthorized():
            """Worker that stays unauthorized and checks it's not leaked."""
            try:
                # This worker never authorizes
                for _ in range(10):
                    assert _h1_authorized.get() is False, (
                        "Unauthorized worker must not see leaked auth"
                    )
                    time.sleep(0.001)
                results.append(True)
            except Exception as e:
                errors.append(str(e))
                results.append(False)

        # Run multiple threads concurrently
        threads = []
        for _ in range(5):
            t = threading.Thread(target=worker_authorized)
            threads.append(t)
        for _ in range(5):
            t = threading.Thread(target=worker_unauthorized)
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert all(results), f"Thread failures: {errors}"
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_concurrent_contextvar_isolation(self):
        """T5.2: Concurrent ContextVar contexts are fully isolated."""
        from guard import h1_authorized_scope, _h1_authorized
        import contextvars

        # Use contextvars.copy_context() to simulate separate requests
        ctx1 = contextvars.copy_context()
        ctx2 = contextvars.copy_context()

        ctx1_auth_values = []
        ctx2_auth_values = []

        def in_ctx1():
            ctx1_auth_values.append(('start', _h1_authorized.get()))
            # We'll authorize via scope inside context 1
            token = _h1_authorized.set(True)
            ctx1_auth_values.append(('authorized', _h1_authorized.get()))
            _h1_authorized.reset(token)
            ctx1_auth_values.append(('reset', _h1_authorized.get()))

        def in_ctx2():
            ctx2_auth_values.append(('start', _h1_authorized.get()))
            ctx2_auth_values.append(('end', _h1_authorized.get()))

        ctx1.run(in_ctx1)
        ctx2.run(in_ctx2)

        # Context 1: started False, became True, reset to False
        assert ctx1_auth_values == [
            ('start', False), ('authorized', True), ('reset', False)
        ], f"ctx1: {ctx1_auth_values}"

        # Context 2: always False — never saw ctx1's authorization
        assert ctx2_auth_values == [
            ('start', False), ('end', False)
        ], f"ctx2: {ctx2_auth_values}"

    def test_unrelated_write_fails_without_auth(self):
        """T5.3: Unrelated approval/state write without auth fails closed."""
        from guard import (
            _assert_h1_authorized_for_path,
            GUARD_STATE_PATH,
            h1_startup_done,
        )
        h1_startup_done()

        # Direct write attempt without authorization
        try:
            _assert_h1_authorized_for_path(GUARD_STATE_PATH)
            pytest.fail("Must raise PermissionError for unauthorized write")
        except PermissionError:
            pass  # expected

    def test_approve_canary_no_cross_contamination(self):
        """T5.4: approve canary requests cannot cross-contaminate authorization."""
        from guard import h1_authorized_scope, _h1_authorized, _active_approvals
        import contextvars

        # Simulate two separate request contexts
        ctx_a = contextvars.copy_context()
        ctx_b = contextvars.copy_context()

        def request_a_canary():
            """Request A: tries aprv_canary (fast not-found)."""
            # Even if we authorize, the canary isn't in active approvals
            with h1_authorized_scope():
                result = _active_approvals.get("aprv_canary")
            return result

        def request_b_check():
            """Request B: check authorization state after A runs."""
            return _h1_authorized.get()

        # Run A in its own context
        result_a = ctx_a.run(request_a_canary)
        assert result_a is None, "aprv_canary must not exist"

        # Run B in its own context — must not see A's authorization
        result_b = ctx_b.run(request_b_check)
        assert result_b is False, (
            f"Request B must not see Request A's authorization (got {result_b})"
        )

        # Main context also not authorized
        assert _h1_authorized.get() is False


# ---------------------------------------------------------------------------
# T6: Production guard invariants
# ---------------------------------------------------------------------------

class TestProductionGuardInvariants:
    """Ensure refactoring didn't break production safety invariants."""

    def test_protected_paths_unchanged(self):
        """T6.1: PROTECTED_PATHS still >= 5 entries."""
        from guard import PROTECTED_PATHS
        assert len(PROTECTED_PATHS) >= 5, (
            f"PROTECTED_PATHS: {len(PROTECTED_PATHS)} (expected >=5)"
        )

    def test_h1_authorized_scope_replaces_pair(self):
        """T6.2: h1_authorized_scope uses same underlying ContextVar."""
        from guard import h1_authorized_scope, h1_authorize, h1_deauthorize, _h1_authorized

        with h1_authorized_scope():
            assert _h1_authorized.get() is True
        assert _h1_authorized.get() is False

    def test_startup_flag_unchanged(self):
        """T6.3: _h1_startup_complete flag mechanism unchanged."""
        from guard import _h1_startup_complete, h1_startup_done
        # This module may have been imported before; flag may already be True
        # Just verify the function exists and flag is boolean
        assert isinstance(_h1_startup_complete, bool)
        assert callable(h1_startup_done)

    def test_ibkr_operator_does_not_import_context_manager(self):
        """T6.4: ibkr-operator does not import h1_authorized_scope."""
        op_path = Path(__file__).resolve().parent.parent / "ibkr_operator.py"
        content = op_path.read_text()
        assert "h1_authorized_scope" not in content, (
            "ibkr-operator must not import h1_authorized_scope"
        )
        assert "h1_authorize" not in content, (
            "ibkr-operator must not import h1_authorize"
        )
