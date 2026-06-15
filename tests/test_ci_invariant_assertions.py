#!/usr/bin/env python3
"""
CI Invariant Safety Assertions

Validates code invariants that must never regress. These are grep/parse-
based checks that enforce structural safety rules.

  T1  /order endpoint remains permanently 403
  T2  H1 approve requires X-H1-Token before any mutation
  T3  H1 submit requires X-H1-Token before any mutation
  T4  P5 simple BUY path rejects BUY without stop (BRACKET_STOP_REQUIRED)
  T5  No 'IBKR_ALLOW_ORDERS=true' in tests/scripts/workflows except as quoted assertions
  T6  No 'rules.enforced=true' in tests/scripts/workflows except as quoted assertions
  T7  No raw '/etc/ibkr-bridge/h1_token' reads in app code or CI
  T8  bridge.py h1_authorized_scope used, no raw h1_authorize/h1_deauthorize
"""

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BRIDGE_PATH = PROJECT_ROOT / "bridge.py"
GUARD_PATH = PROJECT_ROOT / "guard.py"
OPERATOR_PATH = PROJECT_ROOT / "ibkr_operator.py"
TESTS_DIR = PROJECT_ROOT / "tests"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"


# ============================================================================
# T1 — /order remains permanently 403
# ============================================================================

class TestOrder403Invariant:
    """T1: /order endpoint must remain permanently 403."""

    def test_order_endpoint_exists_and_returns_403(self):
        """bridge.py /order handler must raise HTTPException with 403."""
        source = BRIDGE_PATH.read_text()
        assert "@app.post(\"/order\")" in source, "/order route must exist"
        # The handler must contain HTTPException with status 403
        order_block = source[
            source.index("@app.post(\"/order\")"):
            source.index("def order_blocked")
        ]
        # Find the function body
        fn_start = source.index("def order_blocked")
        fn_end = source.index("@app.post(\"/order/preflight\")")
        fn_body = source[fn_start:fn_end]
        assert "status_code=403" in fn_body or "403" in fn_body, \
            "/order handler must return HTTP 403"

    def test_no_alternative_order_route(self):
        """No other functional /order route exists besides the 403 handler."""
        source = BRIDGE_PATH.read_text()
        # Count @app.post("/order") occurrences
        routes = re.findall(r'@app\.(?:post|get)\("(/order[^"]*)"', source)
        order_routes = [r for r in routes if r == "/order"]
        assert len(order_routes) == 1, \
            f"Exactly one /order route expected, found {len(order_routes)}: {order_routes}"


# ============================================================================
# T2/T3 — H1 enforce token before mutation
# ============================================================================

class TestH1TokenEnforcement:
    """T2/T3: H1 token checks happen before any state mutation."""

    def test_approve_checks_h1_before_mutation(self):
        """order_approve verifies H1 token before h1_authorized_scope."""
        source = BRIDGE_PATH.read_text()
        approve_start = source.index("def order_approve")
        approve_end = source.index("class SubmitRequest")
        approve_body = source[approve_start:approve_end]

        verify_pos = approve_body.index("_verify_h1_token")
        scope_pos = approve_body.index("h1_authorized_scope")
        assert verify_pos < scope_pos, \
            "H1 token must be verified BEFORE h1_authorized_scope in order_approve"

    def test_submit_checks_h1_before_mutation(self):
        """order_submit verifies H1 token before h1_authorized_scope."""
        source = BRIDGE_PATH.read_text()
        submit_start = source.index("def order_submit")
        submit_end = source.index("# --- Read-only market data endpoints ---")
        submit_body = source[submit_start:submit_end]

        verify_pos = submit_body.index("_verify_h1_token")
        scope_pos = submit_body.index("h1_authorized_scope")
        assert verify_pos < scope_pos, \
            "H1 token must be verified BEFORE h1_authorized_scope in order_submit"

    def test_bridge_uses_context_manager_not_raw_pair(self):
        """bridge.py uses h1_authorized_scope, never raw h1_authorize/h1_deauthorize."""
        source = BRIDGE_PATH.read_text()
        assert "h1_authorized_scope" in source
        # Raw calls (outside guard.py) must not exist in bridge.py
        # Remove comments for clean check
        lines = [l for l in source.split("\n") if not l.strip().startswith("#")]
        clean = "\n".join(lines)
        standalone_authorize = re.findall(
            r'(?<!with\s)(?<!def\s)(?<!\.)\bh1_authorize\b(?!d)', clean
        )
        standalone_deauthorize = re.findall(
            r'(?<!\.)\bh1_deauthorize\b', clean
        )
        # h1_authorize and h1_deauthorize are defined in guard.py, imported
        # in bridge.py's import line. That's fine. We check the function body.
        # But the standalone pattern should catch function calls.
        # Filter out import statements
        actual_calls_authorize = [
            m for m in standalone_authorize
            if "from guard import" not in clean[max(0, clean.index(m)-50):clean.index(m)+len(m)]
            and "def h1_authorize" not in clean[max(0, clean.index(m)-50):clean.index(m)+len(m)]
        ]
        actual_calls_deauthorize = [
            m for m in standalone_deauthorize
            if "from guard import" not in clean[max(0, clean.index(m)-50):clean.index(m)+len(m)]
        ]
        assert len(actual_calls_authorize) == 0, \
            f"Raw h1_authorize() found in bridge.py: {actual_calls_authorize}"
        assert len(actual_calls_deauthorize) == 0, \
            f"Raw h1_deauthorize() found in bridge.py: {actual_calls_deauthorize}"


# ============================================================================
# T4 — P5 simple BUY without stop is impossible
# ============================================================================

class TestP5DefenseInvariant:
    """T4: P5 simple path must reject BUY without protective stop."""

    def test_bracket_stop_required_code_exists(self):
        """BRACKET_STOP_REQUIRED error code exists in bridge.py."""
        source = BRIDGE_PATH.read_text()
        assert "BRACKET_STOP_REQUIRED" in source, \
            "BRACKET_STOP_REQUIRED must exist for P5 defense-in-depth"

    def test_simple_path_rejects_buy_before_place_order(self):
        """Simple path checks for BUY and returns BRACKET_STOP_REQUIRED before ib.placeOrder."""
        source = BRIDGE_PATH.read_text()
        simple_start = source.index("# ---- Simple Path")
        simple_end = source.index("def _internal_order_status")
        simple_body = source[simple_start:simple_end]

        # BRACKET_STOP_REQUIRED must appear before any ib.placeOrder in simple path
        req_pos = simple_body.index("BRACKET_STOP_REQUIRED")
        place_pos = simple_body.index("ib.placeOrder")
        assert req_pos < place_pos, \
            "BRACKET_STOP_REQUIRED check must happen BEFORE ib.placeOrder in simple path"

    def test_simple_path_buy_action_check(self):
        """Simple path explicitly checks action.upper() == 'BUY'."""
        source = BRIDGE_PATH.read_text()
        simple_start = source.index("# ---- Simple Path")
        simple_end = source.index("def _internal_order_status")
        simple_body = source[simple_start:simple_end]
        assert 'action.upper() == "BUY"' in simple_body or "action.upper() == 'BUY'" in simple_body, \
            "Simple path must check action for BUY before placing order"

    def test_validate_bracket_stop_in_guard(self):
        """validate_bracket_stop function exists in guard.py."""
        source = GUARD_PATH.read_text()
        assert "def validate_bracket_stop" in source, \
            "validate_bracket_stop must exist in guard.py"

    def test_validate_bracket_stop_called_in_submit_order(self):
        """submit_order calls validate_bracket_stop before calling provider."""
        source = GUARD_PATH.read_text()
        submit_start = source.index("def submit_order")
        submit_end = source.index("# --- Config Loading ---")
        submit_body = source[submit_start:submit_end]

        bracket_check_pos = submit_body.index("validate_bracket_stop")
        provider_call_pos = submit_body.rindex("order_provider(record)")
        assert bracket_check_pos < provider_call_pos, \
            "validate_bracket_stop must be called BEFORE order_provider in submit_order"


# ============================================================================
# T5/T6 — No kill-switch enabling in tests/scripts/workflows
# ============================================================================

class TestKillSwitchInvariants:
    """T5/T6: Tests/scripts/workflows must not enable kill switches."""

    def _grep_files(self, pattern: str, dirs: list[Path]) -> list[str]:
        """Return list of file:line matches, excluding safe contexts."""
        matches: list[str] = []
        for d in dirs:
            if not d.exists():
                continue
            for fp in d.glob("**/*"):
                if not fp.is_file():
                    continue
                if fp.suffix in (".pyc", ".pyo", ".bak", ".swp"):
                    continue
                if "__pycache__" in str(fp):
                    continue
                try:
                    for i, line in enumerate(fp.read_text().splitlines(), 1):
                        if pattern not in line:
                            continue
                        stripped = line.strip()
                        # Allow: comments, assertion strings, docstrings, env var references
                        if stripped.startswith("#"):
                            continue
                        if '"""' in stripped or "'''" in stripped:
                            continue
                        # Allow explicit safety-assertion checks
                        if 'assert "' in stripped or "assert '" in stripped:
                            continue
                        # Allow the safety check itself (this file)
                        if fp.name == "test_ci_invariant_assertions.py":
                            continue
                        # Allow KPI dashboard test files (safety assertions)
                        if fp.name == "test_kpi_dashboard.py":
                            continue
                        # Allow strategy/autonomy doc tests (safety assertions)
                        if fp.name == "test_strategy_autonomy_docs.py":
                            continue
                        # Allow quoted false values (safety references)
                        if '"IBKR_ALLOW_ORDERS=false"' in line or "'IBKR_ALLOW_ORDERS=false'" in line:
                            continue
                        if '"rules.enforced=false"' in line or "'rules.enforced=false'" in line:
                            continue
                        # True only as literal check in assertion message
                        if f'"{pattern}"' in line or f"'{pattern}'" in line:
                            continue
                        matches.append(f"{fp.relative_to(PROJECT_ROOT)}:{i}: {stripped[:120]}")
                except Exception:
                    pass
        return matches

    def test_no_allow_orders_true_in_tests(self):
        """No 'IBKR_ALLOW_ORDERS=true' in tests/ except as quoted assertions."""
        matches = self._grep_files("IBKR_ALLOW_ORDERS=true", [TESTS_DIR])
        assert len(matches) == 0, \
            f"IBKR_ALLOW_ORDERS=true found in tests:\n" + "\n".join(matches)

    def test_no_allow_orders_true_in_scripts(self):
        """No 'IBKR_ALLOW_ORDERS=true' in scripts/ except as quoted assertions."""
        matches = self._grep_files("IBKR_ALLOW_ORDERS=true", [SCRIPTS_DIR])
        assert len(matches) == 0, \
            f"IBKR_ALLOW_ORDERS=true found in scripts:\n" + "\n".join(matches)

    def test_no_allow_orders_true_in_workflows(self):
        """No 'IBKR_ALLOW_ORDERS=true' in .github/workflows/ except as quoted assertions."""
        matches = self._grep_files("IBKR_ALLOW_ORDERS=true", [WORKFLOWS_DIR])
        assert len(matches) == 0, \
            f"IBKR_ALLOW_ORDERS=true found in workflows:\n" + "\n".join(matches)

    def test_no_rules_enforced_true_in_tests(self):
        """No 'rules.enforced=true' in tests/ except as quoted assertions."""
        matches = self._grep_files("rules.enforced=true", [TESTS_DIR])
        assert len(matches) == 0, \
            f"rules.enforced=true found in tests:\n" + "\n".join(matches)

    def test_no_rules_enforced_true_in_scripts(self):
        """No 'rules.enforced=true' in scripts/ except as quoted assertions."""
        matches = self._grep_files("rules.enforced=true", [SCRIPTS_DIR])
        assert len(matches) == 0, \
            f"rules.enforced=true found in scripts:\n" + "\n".join(matches)

    def test_no_rules_enforced_true_in_workflows(self):
        """No 'rules.enforced=true' in .github/workflows/ except as quoted assertions."""
        matches = self._grep_files("rules.enforced=true", [WORKFLOWS_DIR])
        assert len(matches) == 0, \
            f"rules.enforced=true found in workflows:\n" + "\n".join(matches)


# ============================================================================
# T7 — No raw H1 token reads
# ============================================================================

class TestNoRawTokenReads:
    """T7: No raw /etc/ibkr-bridge/h1_token reads in app or CI."""

    def test_no_h1_token_file_read_in_app(self):
        """App code (excluding operator CLI) never reads a raw h1_token file path."""
        # ibkr_operator.py is the operator CLI — it references the token
        # file path for documentation and the H1 canary check. Exclude it.
        for path in [BRIDGE_PATH, GUARD_PATH]:
            source = path.read_text()
            assert "/etc/ibkr-bridge/h1_token" not in source, \
                f"{path.name} must not contain /etc/ibkr-bridge/h1_token file path"

    def test_no_h1_token_file_read_in_ci(self):
        """CI workflows never reference a raw h1_token file path."""
        if WORKFLOWS_DIR.exists():
            for fp in WORKFLOWS_DIR.glob("*.yml"):
                source = fp.read_text()
                assert "/etc/ibkr-bridge/h1_token" not in source, \
                    f"{fp.name} must not reference raw h1_token file"

    def test_no_h1_token_file_read_in_scripts(self):
        """Scripts (except ibkr-trade-window) never reference h1_token file."""
        # ibkr-trade-window IS the H1 authorization boundary — it must
        # read the token file. All other scripts must not reference it.
        ALLOWED_SCRIPTS = {"ibkr-trade-window"}
        if SCRIPTS_DIR.exists():
            for fp in SCRIPTS_DIR.glob("*"):
                if fp.name in ALLOWED_SCRIPTS:
                    continue
                if fp.is_file() and fp.suffix not in (".pyc", ".pyo"):
                    source = fp.read_text()
                    assert "/etc/ibkr-bridge/h1_token" not in source, \
                        f"{fp.name} must not reference raw h1_token file"
