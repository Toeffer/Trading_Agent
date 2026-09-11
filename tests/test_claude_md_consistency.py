"""CLAUDE.md consistency test (the "test 139" promised in CLAUDE.md §9 since June).

CLAUDE.md is the load-bearing policy document Werner treats as truth. §0 says
the live system wins on conflict, but a stale claim still misleads until
someone notices. This test makes CI notice.

Scope: only claims that can be verified from repository contents — no
~/.openclaw, no bridge process, no IBKR. Checks against the live YAML are
behind the existing `live` marker (skipped by default, see tests/conftest.py).

Every assertion here names the CLAUDE.md section it reads and the code it
compares against, so a failure says which side to change.
"""

from source_helpers import implementation_source

import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import guard  # noqa: E402

CLAUDE_MD = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
BRIDGE_SOURCE = implementation_source('bridge.py')
GUARD_SOURCE = implementation_source('guard.py', historical=True)

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}


def _section(heading_prefix: str) -> str:
    """Return the text of the CLAUDE.md section whose '## ' heading starts with prefix."""
    m = re.search(rf"^## {re.escape(heading_prefix)}.*?$(.*?)(?=^## |\Z)", CLAUDE_MD, re.M | re.S)
    assert m, f"CLAUDE.md section '{heading_prefix}' not found"
    return m.group(1)


def _function_source(source: str, name: str) -> str:
    start = source.index(f"\ndef {name}(")
    nxt = re.search(r"\ndef ", source[start + 1:])
    return source[start: start + 1 + nxt.start()] if nxt else source[start:]


# ── §5 preflight request contract ─────────────────────────────────────────


class TestPreflightContract:
    def test_field_list_matches_guard_allowed_request_fields(self):
        sec = _section("5.")
        m = re.search(r"Fields: `([^`]+)`", sec)
        assert m, "§5 must state the preflight field list as Fields: `a, b, c`"
        documented = {f.strip() for f in m.group(1).split(",")}
        assert documented == set(guard.ALLOWED_REQUEST_FIELDS), (
            f"§5 fields {sorted(documented)} != guard.ALLOWED_REQUEST_FIELDS "
            f"{sorted(guard.ALLOWED_REQUEST_FIELDS)}"
        )

    def test_bridge_only_proposal_path_is_documented_and_real(self):
        sec = _section("5.")
        assert "`proposal_path`" in sec
        model = _function_source(BRIDGE_SOURCE.replace("\nclass ", "\ndef "), "PreflightRequest")
        assert "proposal_path" in model

    def test_actions_and_order_types(self):
        sec = _section("5.")
        assert re.search(r"Actions: `BUY`, `SELL`", sec)
        assert set(guard.ALLOWED_ACTIONS) == {"BUY", "SELL"}
        assert re.search(r"Types: `MKT`, `LMT`", sec)
        assert set(guard.ALLOWED_ORDER_TYPES) == {"MKT", "LMT"}

    def test_strict_fields_claim_is_backed_by_bridge_and_guard(self):
        assert "unknown fields rejected" in _section("5.")
        assert "Unknown request field" in _function_source(GUARD_SOURCE, "_validate_preflight_request")
        model = _function_source(BRIDGE_SOURCE.replace("\nclass ", "\ndef "), "PreflightRequest")
        assert 'extra="allow"' in model, "bridge must pass unknown fields through to the guard"


# ── §5 gate wiring ─────────────────────────────────────────────────────────


class TestHistoricalGateWiring:
    documented = set(re.findall(r"`(gate_[a-z_]+)`", _section("5.")))
    defined = set(re.findall(r"^def (gate_[a-z_]+)\(", GUARD_SOURCE, re.M))
    wired = set(re.findall(r"\b(gate_[a-z_]+)\(", _function_source(GUARD_SOURCE, "run_preflight")))

    def test_every_documented_gate_exists(self):
        assert self.documented, "§5 must list gates as `gate_xxx` names"
        assert self.documented <= self.defined, self.documented - self.defined

    def test_every_defined_gate_is_documented(self):
        assert self.defined <= self.documented, (
            f"gate functions missing from CLAUDE.md §5: {sorted(self.defined - self.documented)}"
        )

    def test_every_defined_gate_is_wired_into_run_preflight(self):
        # This is the assertion that would have caught Gate G (gate_close_only)
        # being defined but never called between 63052ed and 2026-09-07.
        assert self.defined <= self.wired, (
            f"gate functions defined but never called in run_preflight(): "
            f"{sorted(self.defined - self.wired)}"
        )

    def test_sell_branch_calls_gate_close_only_with_its_own_result(self):
        body = _function_source(GUARD_SOURCE, "run_preflight")
        sell_branch = body[body.index("if is_close:\n        # SELL (close-only)"):body.index("    else:\n        # BUY: run gates")]
        call = sell_branch.index("gate_close_only(")
        entry = sell_branch.index('"gate": "close_only"')
        assert call < entry, "close_only gate entry must come from gate_close_only(), not a reused result"


# ── §4 endpoint map ────────────────────────────────────────────────────────


class TestEndpointMap:
    def test_monitor_get_endpoint_count(self):
        sec = _section("4.")
        m = re.search(r"(\w+)\s+read-only `GET /monitor/\*` endpoints", sec)
        assert m, "§4 must state '<n> read-only `GET /monitor/*` endpoints'"
        documented = _WORDS.get(m.group(1).lower()) or int(m.group(1))
        actual = len(re.findall(r'^@app\.get\("/monitor', BRIDGE_SOURCE, re.M))
        assert documented == actual, f"§4 says {documented} GET /monitor endpoints, bridge has {actual}"

    def test_monitor_post_endpoint(self):
        sec = _section("4.")
        assert "`POST /monitor/open-orders/reconcile`" in sec
        posts = re.findall(r'^@app\.post\("(/monitor[^"]*)"', BRIDGE_SOURCE, re.M)
        assert posts == ["/monitor/open-orders/reconcile"], posts

    def test_order_endpoint_is_permanently_403(self):
        handler = BRIDGE_SOURCE[BRIDGE_SOURCE.index('@app.post("/order")'):]
        handler = handler[:handler.index("\n\n\n")]
        assert "status_code=403" in handler
        assert "placeOrder" not in handler


# ── §3 kill switches, approval lifecycle ───────────────────────────────────


class TestSafetyInvariantsClaims:
    def test_allow_orders_defaults_false_in_bridge_and_guard(self):
        assert 'os.getenv("IBKR_ALLOW_ORDERS", "false")' in BRIDGE_SOURCE
        assert "IBKR_ALLOW_ORDERS=false" in _section("3.")

    def test_approve_and_submit_require_h1_header(self):
        for ep in ('"/order/approve"', '"/order/submit"'):
            fn = BRIDGE_SOURCE[BRIDGE_SOURCE.index(f"@app.post({ep})"):]
            fn = fn[:fn.index("\n\n\n")]
            assert 'alias="X-H1-Token"' in fn, ep
            assert "_verify_h1_token(x_h1_token)" in fn, ep
        assert "X-H1-Token" in _section("3.")

    def test_approval_ttl_300s_no_extension(self):
        assert guard.APPROVAL_TIMEOUT_SECONDS == 300
        assert re.search(r"300\s?s", _section("3."))
        assert "300 s TTL" in _section("10.")

    def test_submit_is_mkt_only(self):
        from trading_agent.domain import ApprovedOrderPlan
        from test_execution_regressions import plan
        import pytest
        for order_type in ("LMT", "STP", "MOC"):
            with pytest.raises(ValueError, match="MKT"):
                ApprovedOrderPlan.from_dict({**plan().to_dict(), "order_type": order_type})
        assert "always MKT" in _section("5.")

    def test_restart_invalidation_claim_is_implemented(self):
        assert re.search(r"approved-but-unsubmitted approvals are\s+invalid", _section("3."))
        loader = _function_source(GUARD_SOURCE, "_load_active_approvals")
        assert "bridge_restart" in loader and "_active_approvals.clear()" in loader


# ── §5 stop formula and rules version ──────────────────────────────────────


class TestStopFormulaAndRulesVersion:
    def test_stop_constants(self):
        sec = _section("5.")
        assert f"ATR({guard.ATR_PERIOD})" in sec
        assert f"{int(guard.ATR_MULTIPLIER)}×ATR" in sec
        assert f"entry × {guard.FLOOR_PERCENT}" in sec

    def test_rules_version(self):
        assert guard.EXPECTED_VERSION in CLAUDE_MD
        assert f"rules_version {guard.EXPECTED_VERSION}" in _section("10.")


# ── §10 must not carry mutable live state ──────────────────────────────────


class TestSnapshotCarriesNoLiveState:
    def test_no_positions_or_trade_count_lines(self):
        block = _section("10.")
        for key in ("positions:", "daily_trade_count:", "halt_active:"):
            assert not re.search(rf"^{re.escape(key)}", block, re.M), (
                f"§10 must not hand-write mutable state ({key}); see §0"
            )

    def test_static_claims_present(self):
        block = _section("10.")
        for needle in ("IBKR_ALLOW_ORDERS=false", "rules.enforced=false",
                       "/order: HTTP 403", "automation-ready NO", "live-ready NO"):
            assert needle in block, needle


# ── Live YAML (opt-in) ─────────────────────────────────────────────────────


@pytest.mark.live
def test_live_rules_yaml_matches_claims():
    yaml = pytest.importorskip("yaml")
    path = Path(os.environ.get(
        "IBKR_RULES_PATH", str(Path.home() / ".openclaw" / "risk-rules" / "paper-trading-rules.yaml")
    ))
    if not path.exists():
        pytest.skip(f"no live rules file at {path}")
    rules = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert rules.get("rules_version") == guard.EXPECTED_VERSION
    assert rules.get("symbol_allowlist", {}).get("mode") == "explicit_list"
    assert rules.get("enforced") is False, "CLAUDE.md §3.2: enforced must sit at false between cycles"
