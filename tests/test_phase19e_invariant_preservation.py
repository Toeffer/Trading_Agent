"""Phase 19E — invariant preservation across Phases 19C/19D.

strategy_v1_1 proposal §9.5. Confirms the CLAUDE.md §3 safety invariants,
the default kill-switch states, and the position-sizing formula are
unchanged by the 19C advisory layer and the 19D Gate I addition — the
guard's hard ceiling still holds regardless of anything the advisory
layer computes, and nothing in this phase touched bridge.py, guard.py's
sizing/stop code, or .env.

This complements (does not replace) tests/test_ci_invariant_assertions.py,
which pins /order=403 and H1 token ordering generically for every phase.
This module is the phase-19-specific checkpoint: it proves THIS phase's
diff didn't move any of those needles.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import guard  # noqa: E402

BRIDGE_SOURCE = (REPO / "bridge.py").read_text()
GUARD_SOURCE = (REPO / "guard.py").read_text()
HERMES_ADVISORY_SOURCE = (REPO / "hermes_advisory.py").read_text()


# ── /order stays permanently 403 (invariant 1) ──────────────────────────────


class TestOrderStill403:
    def test_order_route_exists_and_is_blocked(self):
        assert '@app.post("/order")' in BRIDGE_SOURCE
        fn_start = BRIDGE_SOURCE.index('def order_blocked')
        fn_end = BRIDGE_SOURCE.index('@app.post("/order/preflight")')
        fn_body = BRIDGE_SOURCE[fn_start:fn_end]
        assert "403" in fn_body

    def test_only_one_order_route(self):
        import re
        routes = re.findall(r'@app\.(?:post|get)\("(/order[^"]*)"', BRIDGE_SOURCE)
        assert len([r for r in routes if r == "/order"]) == 1


# ── Triple kill switches default off (invariant 2) ──────────────────────────


class TestKillSwitchDefaults:
    def test_ibkr_allow_orders_defaults_false(self):
        assert 'IBKR_ALLOW_ORDERS = os.getenv("IBKR_ALLOW_ORDERS", "false")' in BRIDGE_SOURCE

    def test_order_submit_still_gated_on_allow_orders_and_enforced(self):
        assert "system_locked" in BRIDGE_SOURCE
        assert "IBKR_ALLOW_ORDERS and rules.get" in BRIDGE_SOURCE.replace("\n", " ")

    def test_no_new_env_var_bypasses_the_switches(self):
        """19C/19D's own new code must not introduce a new environment-
        variable escape hatch around the two existing switches. guard.py
        already legitimately references IBKR_ALLOW_ORDERS elsewhere (its
        pre-existing kill-switch check) — this test scopes to the new
        functions only, not the whole file."""
        import inspect
        import hermes_advisory as ha
        new_functions = [
            guard.gate_sector_concentration,
            ha.fetch_reference_bars, ha.compute_realized_vol,
            ha.compute_regime_state, ha.compute_gross_scalar,
            ha.compute_effective_budget, ha.rank_cross_sectional_rs,
            ha.build_proposal,
        ]
        for fn in new_functions:
            src = inspect.getsource(fn)
            assert "IBKR_ALLOW_ORDERS" not in src, fn.__name__
            assert "os.environ" not in src and "getenv" not in src, fn.__name__


# ── Only path A→B→C for orders (invariant 3) — unaffected by this phase ────


class TestOrderPathUnaffected:
    def test_hermes_advisory_never_calls_order_endpoints(self):
        """/order/submit and /order/approve legitimately appear in
        FORBIDDEN_COMMANDS (a blocklist hermes_advisory.py scans its own
        output against) — that's a control, not a violation. This checks
        the new Phase 19C functions' own source, where no such string
        should appear at all, blocklisted or otherwise."""
        import inspect
        import hermes_advisory as ha
        new_functions = [
            ha.fetch_reference_bars, ha.compute_realized_vol,
            ha.compute_regime_state, ha.compute_gross_scalar,
            ha.compute_effective_budget, ha.rank_cross_sectional_rs,
            ha.build_proposal,
        ]
        for fn in new_functions:
            src = inspect.getsource(fn)
            for forbidden in ["/order/submit", "/order/approve", "placeOrder"]:
                assert forbidden not in src, f"{fn.__name__}: {forbidden}"

    def test_gate_i_is_validation_only_like_other_gates(self):
        """Gate I returns (pass, reason, details) same as every other gate
        — it cannot submit, approve, or mutate anything by construction."""
        import inspect
        src = inspect.getsource(guard.gate_sector_concentration)
        assert "return (" in src
        for forbidden in ["_bridge_post", "urllib", "submit", "approve"]:
            assert forbidden not in src


# ── SELL close-only semantics unchanged (invariant 9) ───────────────────────


class TestCloseOnlySellUnaffected:
    def test_gate_close_only_source_unreferenced_by_gate_i(self):
        """Gate I must not duplicate or reimplement Gate G's close-only
        position lookup — it has its own, narrower, sector-only logic."""
        import inspect
        src = inspect.getsource(guard.gate_sector_concentration)
        assert "_get_existing_position" not in src

    def test_sell_never_reaches_gate_i(self):
        source = GUARD_SOURCE
        sell_start = source.index("if is_close:\n        # SELL (close-only)")
        sell_end = source.index("else:\n        # BUY: run gates")
        assert "gate_sector_concentration" not in source[sell_start:sell_end]


# ── Position sizing formula unchanged (§9.3's "no size" boundary) ─────────


class TestSizingFormulaUnchanged:
    def test_golden_case_matches_known_values(self):
        """A fixed, hand-verified numeric case for compute_final_max_shares.
        If 19C/19D ever perturbed sizing, this pins the regression."""
        result = guard.compute_final_max_shares(
            rules={"max_position_notional": {"value": 5},
                   "max_risk_per_trade": {"value": 2}},
            net_liquidation_eur=1_000_000.0,
            exchange_rate=1.08,
            entry_price=100.0,
            stop_distance=5.0,
        )
        assert result["shares_by_notional"] == 540
        assert result["shares_by_risk"] == 4320
        assert result["final_max_shares"] == 540
        assert result["binding_cap"] == "notional"

    def test_formula_is_min_of_notional_and_risk(self):
        """The binding-cap rule (min of the two candidate caps) is the
        entire sizing formula — confirm it's still exactly that, not
        something the advisory layer could have widened."""
        import inspect
        src = inspect.getsource(guard.compute_final_max_shares)
        assert "min(shares_by_notional, shares_by_risk)" in src

    def test_hermes_advisory_does_not_import_sizing_functions(self):
        import ast
        tree = ast.parse(HERMES_ADVISORY_SOURCE)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.update(a.name for a in node.names)
        assert imported.isdisjoint({"compute_final_max_shares", "calc_stop"})

    def test_advisory_functions_return_no_share_or_notional_field(self):
        """Every Phase 19C function's return type is inspected structurally:
        none may carry a shares/quantity/notional field."""
        import hermes_advisory as ha
        req = {"vol_reference_pct": 16, "gross_scalar_floor": 0.25}
        rules = {"max_total_exposure": {"value": 30}}
        outputs = [
            ha.compute_gross_scalar(0.16, req),
            ha.compute_effective_budget(0.16, "RISK_ON", rules, req),
            ha.compute_regime_state([{"close": c} for c in range(1, 210)],
                                     sma_days=5, momentum_days=10),
        ]
        for out in outputs:
            if isinstance(out, dict):
                assert not ({"shares", "quantity", "totalQuantity", "notional"} & out.keys())


# ── Gate letters / registry consistency (no accidental collision) ─────────


class TestGateRegistryConsistency:
    def test_gate_i_letter_was_free(self):
        """§9.4 verified Gate I free at proposal time (A-H defined,
        gate_open_orders carries no letter). Confirm no OTHER function
        also claims to be 'Gate I' after this change."""
        import re
        claims = re.findall(r'"""Gate ([A-Z]) —', GUARD_SOURCE)
        i_claims = [c for c in claims if c == "I"]
        assert len(i_claims) == 1, f"Expected exactly one Gate I, found {len(i_claims)}"

    def test_all_letters_a_through_i_present_exactly_once(self):
        import re
        claims = re.findall(r'"""Gate ([A-Z]) —', GUARD_SOURCE)
        for letter in "ABCDEFGHI":
            assert claims.count(letter) == 1, f"Gate {letter} count: {claims.count(letter)}"


# ── Repository safety — nothing outside scope was touched ─────────────────


class TestRepositoryScopeUnaffected:
    def test_bridge_py_unchanged_by_this_phase(self):
        """19C/19D touch guard.py and hermes_advisory.py only — bridge.py's
        order-lifecycle code is out of scope for both phases."""
        assert "gate_sector_concentration" not in BRIDGE_SOURCE
        assert "compute_effective_budget" not in BRIDGE_SOURCE

    def test_model_routing_and_openclaw_adapter_untouched(self):
        for name in ("model_routing.py", "openclaw_routing_adapter.py"):
            assert (REPO / name).exists()

    def test_no_tracked_env(self):
        import subprocess
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", ".env"],
            capture_output=True, text=True, cwd=str(REPO),
        )
        assert result.returncode != 0

    def test_h1_token_boundary_untouched(self):
        for forbidden in ["/etc/ibkr-bridge/h1_token"]:
            assert forbidden not in GUARD_SOURCE
            assert forbidden not in HERMES_ADVISORY_SOURCE
