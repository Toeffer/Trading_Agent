"""Tests for the IBKR owner-thread fix (2026-09-28).

Bug: ib_insync binds the Gateway socket to the event loop of the thread that
connects, but each synchronous call runs the calling thread's own loop, so
replies are read only while the connecting thread's loop runs. bridge.py
served each request on whichever worker thread was free and gave each thread
its own loop, so an IBKR round trip made off the connecting thread blocked
until its caller gave up -- against a healthy Gateway, with isConnected()
still True. The per-call executors in _internal_fetch_quote_safe /
_internal_fetch_bars_safe (Phase 19N) made it deterministic: every connected
/order/preflight failed at "Data retrieval failed: market_data_timeout".
/market/bars and /contract/stock handed ib calls to an executor thread with
no event loop at all and raised instead of running.

Fix: one IBKR owner thread (bridge._run_on_ib_owner) connects and runs every
ib_insync call; ib.RequestTimeout bounds each request.

Also covers the EUR/USD fix: IBKR's ExchangeRate is per currency (value of 1
unit in base terms, BASE row = 1.00); sizing needs USD per EUR =
1 / ExchangeRate[USD], never a silent 1.0.

Tiers (all portable, in the curated CI suite):
  - AST audit: no ib_insync call in bridge.py outside the owner thread.
  - Pure guard.py FX tests.
  - A subprocess probe running the real bridge.py (isolated HOME) against
    tests/fake_ib_gateway.py, which answers every request instantly.
"""

import ast
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import guard  # noqa: E402

sys.path.insert(0, str(REPO / "tests"))
import fake_ib_gateway  # noqa: E402

BRIDGE_SOURCE = (REPO / "bridge.py").read_text()


# ── AST audit: every ib_insync call runs on the owner thread ────────────────

# Functions whose bodies run on the owner thread by construction.
_OWNER_HELPERS = {"_pump_ib_events", "_read_ib_cache"}
# Attribute reads that are safe from any thread (plain state, no I/O).
_ANY_THREAD_IB_CALLS = {"isConnected"}


def _decorated_with_owner_call(fn: ast.FunctionDef) -> bool:
    for d in fn.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        if isinstance(target, ast.Name) and target.id == "_ib_owner_call":
            return True
    return False


def _owner_dispatched_lambdas(fn: ast.FunctionDef) -> set:
    """Lambdas passed as the callable to _run_on_ib_owner(...)."""
    out = set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_run_on_ib_owner" and node.args
                and isinstance(node.args[0], ast.Lambda)):
            out.add(id(node.args[0]))
    return out


def _ib_calls_off_owner(source: str) -> list[str]:
    offenders = []
    for fn in ast.parse(source).body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        if (fn.name.endswith("_on_ib_owner") or fn.name in _OWNER_HELPERS
                or _decorated_with_owner_call(fn)):
            continue
        dispatched = _owner_dispatched_lambdas(fn)
        stack = list(fn.body)
        while stack:
            node = stack.pop()
            if isinstance(node, ast.Lambda) and id(node) in dispatched:
                continue
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "ib"
                    and node.func.attr not in _ANY_THREAD_IB_CALLS):
                offenders.append(f"{fn.name}:{node.lineno} ib.{node.func.attr}()")
            stack.extend(ast.iter_child_nodes(node))
    return offenders


class TestOwnerThreadAudit:
    def test_no_ib_call_outside_owner_thread(self):
        offenders = _ib_calls_off_owner(BRIDGE_SOURCE)
        assert offenders == [], (
            "ib_insync calls outside the IBKR owner thread (wrap them in "
            "_run_on_ib_owner / _ib_read, or run them in an owner-pinned "
            f"function): {offenders}"
        )

    def test_audit_catches_an_off_owner_call(self):
        bad = "def handler():\n    return ib.qualifyContracts(c)\n"
        assert _ib_calls_off_owner(bad) == ["handler:2 ib.qualifyContracts()"]

    def test_no_per_call_executor_hands_ib_to_a_foreign_thread(self):
        assert "executor.submit(ib." not in BRIDGE_SOURCE

    def test_order_placement_never_abandoned(self):
        assert "@_ib_owner_call(timeout=None)\ndef _internal_place_order(" in BRIDGE_SOURCE

    def test_connect_runs_on_owner_and_sets_request_timeout(self):
        assert "_run_on_ib_owner(_connect_on_ib_owner" in BRIDGE_SOURCE
        assert "ib.RequestTimeout = _IB_REQUEST_TIMEOUT" in BRIDGE_SOURCE

    def test_no_silent_fx_fallback(self):
        assert '_get("ExchangeRate") or 1.0' not in BRIDGE_SOURCE


# ── EUR/USD from IBKR's per-currency ExchangeRate rows (pure guard.py) ──────

class TestUsdPerBase:
    def test_inverts_usd_row_regardless_of_row_order(self):
        rows = [("ExchangeRate", "0.8700", "USD"), ("ExchangeRate", "1.00", "EUR"),
                ("ExchangeRate", "1.00", "BASE")]
        assert guard.usd_per_base_from_account_values(rows) == pytest.approx(1 / 0.87)
        assert guard.usd_per_base_from_account_values(reversed(rows)) == pytest.approx(1 / 0.87)

    def test_missing_usd_row_is_none_not_one(self):
        rows = [("ExchangeRate", "1.00", "BASE"), ("ExchangeRate", "1.00", "EUR")]
        assert guard.usd_per_base_from_account_values(rows) is None

    def test_usd_base_account_is_identity(self):
        assert guard.usd_per_base_from_account_values([("ExchangeRate", "1.00", "USD")]) == 1.0

    @pytest.mark.parametrize("value", ["", "n/a", "0", "-1"])
    def test_unusable_usd_row_is_none(self, value):
        assert guard.usd_per_base_from_account_values([("ExchangeRate", value, "USD")]) is None

    def test_fetch_account_uses_usd_row_not_last_row(self):
        values = [
            {"tag": "NetLiquidation", "value": "1000000", "currency": "EUR"},
            {"tag": "ExchangeRate", "value": "0.8700", "currency": "USD"},
            {"tag": "ExchangeRate", "value": "1.00", "currency": "BASE"},
        ]
        with patch("guard._bridge_get", return_value={"ok": True, "values": values}):
            acct = guard.fetch_account()
        assert acct["exchange_rate"] == pytest.approx(1 / 0.87)

    def test_fetch_account_without_usd_row_is_none(self):
        values = [
            {"tag": "NetLiquidation", "value": "1000000", "currency": "EUR"},
            {"tag": "ExchangeRate", "value": "1.00", "currency": "BASE"},
        ]
        with patch("guard._bridge_get", return_value={"ok": True, "values": values}):
            acct = guard.fetch_account()
        assert acct["exchange_rate"] is None


# ── Missing market data: NaN ticker fields never reach sizing ──────────────

class TestMissingMarketData:
    """ib_insync leaves ticker fields it never received as NaN. Once preflight
    actually receives quotes (owner-thread fix), a quote without a usable ask
    must be a clean validation failure. Before: a NaN ask passed calc_stop's
    "> 0" check and crashed sizing (ValueError: cannot convert float NaN to
    integer, HTTP 500); a None ask crashed the explicit-stop comparisons."""

    BARS = [{"date": d, "open": o, "high": h, "low": lo, "close": c, "volume": 1000}
            for d, o, h, lo, c in fake_ib_gateway.BARS]

    def _preflight(self, ask, **stop):
        state = {"trade_date": guard.canonical_trade_date(), "daily_trade_count": 0,
                 "week_start_date": guard._current_week_monday_utc_str(),
                 "week_start_nl_eur": 1_000_000.0}
        rules = yaml.safe_load(RULES_YAML)
        with patch("guard.load_guard_state", return_value=state), \
             patch("guard.load_rules", return_value=rules), \
             patch("guard.append_guard_event"):
            return guard.run_preflight(
                {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1,
                 "orderType": "MKT", "mode": "paper", **stop},
                account_provider=lambda: {"net_liquidation_eur": 1_000_000.0,
                                          "exchange_rate": 1.15},
                quote_provider=lambda s: {"ask": ask, "bid": None, "last": 200.5},
                bars_provider=lambda s: self.BARS,
            )

    @pytest.mark.parametrize("stop", [{}, {"stopPercent": -5.0}, {"stopPrice": 190.0}],
                             ids=["computed-stop", "stopPercent", "stopPrice"])
    @pytest.mark.parametrize("ask", [None, float("nan")], ids=["none", "nan"])
    def test_buy_without_usable_ask_is_a_clean_failure(self, ask, stop):
        result = self._preflight(ask, **stop)
        assert result["passed"] is False
        assert "No usable ask price" in result["error"]

    def test_buy_with_ask_still_sizes(self):
        result = self._preflight(200.6)
        assert result["entry_price"] == 200.6
        assert result.get("gates"), result

    def test_bridge_quote_sanitizer_maps_nan_to_none(self):
        # Both _sf helpers (quote and bars) must drop non-finite values.
        assert BRIDGE_SOURCE.count("if not math.isfinite(fv) or fv <= -1.0:") == 2


# ── Real bridge.py against the fake Gateway (subprocess, isolated HOME) ─────

RULES_YAML = textwrap.dedent("""
    rules_version: "1.3-draft"
    enforced: false
    max_position_notional: {value: 5}
    max_risk_per_trade: {value: 2}
    max_total_exposure: {value: 30}
    max_trades_per_day: {value: 2}
    loss_halts: {daily: {value: 1.0}, weekly: {value: 3.0}}
    initial_stop_loss: {atr_multiplier: 2, atr_period: 14, absolute_floor_percent: 5}
    symbol_allowlist: {mode: explicit_list, allow: [AAPL, MSFT]}
    symbol_sectors: {AAPL: INFORMATION_TECHNOLOGY, MSFT: INFORMATION_TECHNOLOGY}
    max_positions_per_sector: {value: 1}
    manual_approval: {enabled: true, timeout_seconds: 300}
    order_endpoint_gate: {}
    guard_state: {file: guard-state.json}
    preflight: {strict_mode: true, response_type: validation_results_only}
    logging: {file: guard-events.jsonl}
""")

BRIDGE_PROBE = textwrap.dedent("""
    import contextvars, json, os, sys, threading, time
    from concurrent.futures import ThreadPoolExecutor
    sys.path.insert(0, os.environ["REPO"])
    sys.path.insert(0, os.path.join(os.environ["REPO"], "tests"))
    from fake_ib_gateway import FakeIBGateway
    gw = FakeIBGateway()
    os.environ["IBKR_PORT"] = str(gw.port)
    import bridge, guard
    from fastapi.testclient import TestClient

    # Test fixture for the isolated HOME: guard state is an H1-protected file.
    with guard.h1_authorized_scope():
        guard.initialize_guard_state_if_missing()

    def timed(fn, *a, **k):
        t0 = time.monotonic()
        try:
            res, err = fn(*a, **k), None
        except Exception as e:
            res, err = None, f"{type(e).__name__}: {e}"
        return {"result": res, "error": err, "seconds": round(time.monotonic() - t0, 2)}

    def in_new_thread(fn, *a, **k):
        # A fresh thread with its own event loop -- what an anyio worker is.
        def run():
            bridge.ensure_loop()
            return fn(*a, **k)
        with ThreadPoolExecutor(1) as ex:
            return ex.submit(run).result()

    def leaked():
        return bridge._MD_LEAKED_THREAD_COUNT

    def wait_leaked_zero(limit=10.0):
        t0 = time.monotonic()
        while leaked() and time.monotonic() - t0 < limit:
            time.sleep(0.05)
        return leaked()

    out = {}
    out["connect"] = in_new_thread(timed, bridge.connect)

    # The bounded fetchers preflight uses, each from yet another thread.
    out["quote_safe"] = in_new_thread(timed, bridge._internal_fetch_quote_safe, "AAPL")
    out["bars_safe"] = in_new_thread(timed, bridge._internal_fetch_bars_safe, "AAPL")
    out["quote_not_found"] = in_new_thread(timed, bridge._internal_fetch_quote_safe, "NOPE")
    out["account"] = timed(bridge._internal_fetch_account)
    out["positions"] = timed(bridge._internal_fetch_positions)

    c = TestClient(bridge.app)
    def post(path, body):
        t0 = time.monotonic()
        r = c.post(path, json=body)
        return {"status": r.status_code, "body": r.json(), "seconds": round(time.monotonic() - t0, 2)}

    with ThreadPoolExecutor(2) as ex:
        out["concurrent_quotes"] = list(ex.map(lambda _: post("/market/quote", {"symbol": "AAPL"}), range(2)))
    out["bars_http"] = post("/market/bars", {"symbol": "AAPL"})
    out["contract_http"] = post("/contract/stock", {"symbol": "MSFT"})
    out["preflight_http"] = post("/order/preflight", {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1})
    out["preflight_no_ask_http"] = post("/order/preflight", {"symbol": "MSFT", "action": "BUY", "totalQuantity": 1})
    out["backpressure_after"] = c.get("/monitor/backpressure").json()

    # Owner-thread dispatch semantics.
    cv = contextvars.ContextVar("cv", default="unset")
    cv.set("caller")
    out["ctx_on_owner"] = bridge._run_on_ib_owner(cv.get)
    idents = {bridge._run_on_ib_owner(threading.get_ident),
              in_new_thread(bridge._run_on_ib_owner, threading.get_ident)}
    out["owner_idents"] = len(idents)
    out["owner_is_caller"] = threading.get_ident() in idents

    gate, ran = threading.Event(), []
    blocker = threading.Thread(target=bridge._run_on_ib_owner, args=(gate.wait, 10), kwargs={"timeout": None})
    blocker.start(); time.sleep(0.2)
    out["queued_timeout"] = timed(bridge._run_on_ib_owner, ran.append, 1, timeout=0.2)
    out["queued_counted"] = leaked()
    gate.set(); blocker.join(5)
    bridge._run_on_ib_owner(lambda: None)
    out["queued_job_ran"] = bool(ran)

    release = threading.Event()
    out["running_timeout"] = timed(bridge._run_on_ib_owner, release.wait, 10, timeout=0.2)
    out["running_counted"] = leaked()
    release.set()
    out["running_counted_after"] = wait_leaked_zero()

    # Stalled Gateway: request never answered. RequestTimeout shortened so the
    # probe stays fast; production uses bridge._IB_REQUEST_TIMEOUT.
    bridge.ib.RequestTimeout = 2
    out["stalled_quote"] = timed(bridge._internal_fetch_quote_safe, "HANG", timeout=1)
    out["stalled_counted"] = leaked()
    out["stalled_counted_after"] = wait_leaked_zero()
    out["stalled_http"] = post("/market/quote", {"symbol": "HANG"})
    out["recovered_bars"] = timed(bridge._internal_fetch_bars_safe, "AAPL")
    out["still_connected"] = bridge.is_connected()
    print("PROBE_JSON " + json.dumps(out, default=str))
    sys.stdout.flush()
    os._exit(0)
""")


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    pytest.importorskip("ib_insync")
    home = tmp_path_factory.mktemp("home")
    oc = home / ".openclaw"
    (oc / "risk-rules").mkdir(parents=True)
    (oc / "risk-rules" / "paper-trading-rules.yaml").write_text(RULES_YAML)
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("IBKR_")},
        "HOME": str(home),
        "REPO": str(REPO),
        "IBKR_ALLOW_ORDERS": "false",
        "IBKR_READ_ONLY": "true",
        "IBKR_CLIENT_ID": "777",
    }
    proc = subprocess.run(
        [sys.executable, "-c", BRIDGE_PROBE], env=env, cwd=str(home),
        capture_output=True, text=True, timeout=180,
    )
    lines = [l for l in proc.stdout.splitlines() if l.startswith("PROBE_JSON ")]
    assert lines, f"bridge probe produced no result\nstdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-3000:]}"
    return json.loads(lines[-1][len("PROBE_JSON "):])


class TestAgainstFakeGateway:
    def test_connects(self, probe):
        assert probe["connect"]["error"] is None
        assert probe["connect"]["result"]["connected"] is True

    def test_quote_safe_off_connecting_thread_returns_data(self, probe):
        q = probe["quote_safe"]
        assert q["error"] is None, q
        assert q["result"]["last"] == fake_ib_gateway.LAST_PRICE
        assert q["result"]["ask"] == fake_ib_gateway.ASK_PRICE
        assert q["seconds"] < 6          # ib.sleep(3) inside, not the 8 s deadline

    def test_bars_safe_off_connecting_thread_returns_bars(self, probe):
        b = probe["bars_safe"]
        assert b["error"] is None, b
        assert [bar["close"] for bar in b["result"]] == [c for *_, c in fake_ib_gateway.BARS]
        assert b["seconds"] < 2

    def test_unknown_contract_is_an_error_not_a_timeout(self, probe):
        err = probe["quote_not_found"]["error"]
        assert "Contract not found" in err and "timeout" not in err

    def test_account_fx_is_usd_per_eur(self, probe):
        acct = probe["account"]
        assert acct["error"] is None, acct
        assert acct["result"]["net_liquidation_eur"] == 1_000_000.0
        assert acct["result"]["exchange_rate"] == pytest.approx(1 / 0.87)

    def test_positions(self, probe):
        assert probe["positions"] == {"result": [], "error": None, "seconds": probe["positions"]["seconds"]}

    def test_concurrent_market_quotes_all_answer(self, probe):
        for r in probe["concurrent_quotes"]:
            assert r["status"] == 200, r
            assert r["body"]["last"] == 190.5

    def test_market_bars_endpoint(self, probe):
        r = probe["bars_http"]
        assert r["status"] == 200, r
        assert r["body"]["count"] == len(fake_ib_gateway.BARS)

    def test_contract_lookup_endpoint(self, probe):
        r = probe["contract_http"]
        assert r["status"] == 200, r
        assert r["body"]["matches"][0]["conId"] == 265598

    def test_connected_preflight_reaches_the_gates(self, probe):
        r = probe["preflight_http"]
        assert r["status"] == 200, r
        body = r["body"]
        text = json.dumps(body)
        assert "Data retrieval failed" not in text and "market_data_timeout" not in text, body
        assert body.get("gates"), body              # data, FX and stop calc all passed
        assert body["entry_price"] == fake_ib_gateway.ASK_PRICE   # sized from the ask

    def test_preflight_without_ask_is_a_clean_failure(self, probe):
        r = probe["preflight_no_ask_http"]
        assert r["status"] == 200, r
        assert r["body"]["passed"] is False
        assert "No usable ask price" in r["body"]["error"]

    def test_no_slot_or_thread_left_behind(self, probe):
        bp = probe["backpressure_after"]
        assert bp["active"] <= 1          # only the /monitor/backpressure request itself
        assert bp["leaked_md_threads"] == 0

    def test_single_owner_thread_distinct_from_callers(self, probe):
        assert probe["owner_idents"] == 1
        assert probe["owner_is_caller"] is False

    def test_caller_contextvars_apply_on_owner(self, probe):
        assert probe["ctx_on_owner"] == "caller"

    def test_queued_job_is_cancelled_on_timeout(self, probe):
        assert "IBOwnerTimeout" in probe["queued_timeout"]["error"]
        assert probe["queued_counted"] == 0
        assert probe["queued_job_ran"] is False

    def test_running_job_is_counted_until_it_finishes(self, probe):
        assert "IBOwnerTimeout" in probe["running_timeout"]["error"]
        assert probe["running_counted"] == 1
        assert probe["running_counted_after"] == 0

    def test_stalled_gateway_is_bounded_and_recovers(self, probe):
        s = probe["stalled_quote"]
        assert "market_data_timeout" in s["error"]
        assert s["seconds"] < 2
        assert probe["stalled_counted"] == 1
        assert probe["stalled_counted_after"] == 0
        assert probe["stalled_http"]["status"] == 503
        assert "market_data_timeout" in probe["stalled_http"]["body"]["detail"]
        assert probe["recovered_bars"]["error"] is None
        assert probe["still_connected"] is True
