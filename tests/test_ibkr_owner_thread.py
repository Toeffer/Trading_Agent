"""Research FX regressions and owner-loop behavior against the wire simulator.

The durable BrokerLoop supersedes the research branch's root-module decorators.
These tests exercise that owner and its compatibility proxy instead of auditing
the retired monolith. Execution/timeout contracts also live in test_broker_contract.
"""
import asyncio
import contextvars
import threading
import textwrap
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from unittest.mock import patch

import pytest
import yaml

import guard
from sim.ib_gateway import SimGateway, ACCOUNT, ASK_PRICE, LAST_PRICE, BARS
from trading_agent.broker_loop import BrokerLoop
from trading_agent.compatibility import ReadOnlyBrokerProxy
from trading_agent.runtime import Runtime
from trading_agent.settings import Settings
from trading_agent.domain import utcnow
from test_execution_application import service  # noqa: F401 -- shared fixture

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

    @pytest.mark.parametrize("value", ["", "n/a", "0", "-1", "nan", "inf", "-inf"])
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

class TestMissingMarketData:
    @pytest.mark.parametrize("ask", [None, Decimal("NaN"), Decimal("Infinity"), Decimal("0")])
    @pytest.mark.parametrize("stop", [{}, {"stopPercent": -5.0}, {"stopPrice": 95}])
    def test_buy_without_usable_ask_fails_before_approval(self, service, ask, stop):
        execution, broker = service
        broker.snapshot_value = replace(broker.snapshot_value, ask=ask)
        result = execution.preflight(
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1, **stop},
            proposal={"symbol": "AAPL", "side": "BUY", "quantity": 1})
        assert result["passed"] is False
        assert not execution.store.approvals() and not broker.calls

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), None])
    def test_bridge_sanitizer_drops_nonfinite_values(self, value):
        from trading_agent.http_compat import _safe_float
        assert _safe_float(value) is None


def test_readonly_proxy_uses_one_owner_for_all_callers():
    identities = set()
    context = contextvars.ContextVar("research_owner", default="unset")
    class Client:
        async def qualifyContractsAsync(self, *contracts):
            identities.add(threading.get_ident())
            await asyncio.sleep(0)
            return contracts, context.get()
        def disconnect(self):
            identities.add(threading.get_ident())
    owner = BrokerLoop(Client)
    owner.start()
    proxy = ReadOnlyBrokerProxy(owner)
    def read(number):
        context.set(str(number))
        return proxy.qualifyContracts(number)
    try:
        with ThreadPoolExecutor(3) as pool:
            assert list(pool.map(read, range(3))) == [((n,), str(n)) for n in range(3)]
        with pytest.raises(AttributeError):
            proxy.placeOrder
    finally:
        owner.close()
    assert len(identities) == 1 and threading.get_ident() not in identities


@pytest.fixture
def wire(tmp_path):
    gateway = SimGateway()
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(RULES_YAML)
    runtime = Runtime(Settings(account=ACCOUNT, port=gateway.port,
                               rules_path=rules_path, state_dir=tmp_path / "state",
                               proposal_dir=tmp_path / "proposals"))
    runtime.store.initialize_risk(ACCOUNT, {
        "day_start_nl_eur": 1000000, "week_start_nl_eur": 1000000,
        "trade_date": guard.canonical_trade_date(),
        "week_start_date": guard._current_week_monday_utc_str(),
        "daily_trade_count": 0,
    }, authorized=True)
    runtime.start()
    try:
        assert runtime.broker.connect()["managed_accounts"] == [ACCOUNT]
        yield runtime, ReadOnlyBrokerProxy(runtime.owner)
    finally:
        runtime.close()
        gateway.close()


def test_concurrent_readers_get_wire_quotes_and_bars(wire):
    from ib_insync import Stock
    runtime, proxy = wire
    def read(_):
        contract = proxy.qualifyContracts(Stock("AAPL", "SMART", "USD"))[0]
        return proxy.reqHistoricalData(contract, "", "30 D", "1 day", "TRADES", True)
    with ThreadPoolExecutor(3) as pool:
        bars = list(pool.map(read, range(3)))
    assert all([b.close for b in result] == [b[-1] for b in BARS] for result in bars)
    snapshot = runtime.broker.snapshot("AAPL")
    assert float(snapshot.ask) == ASK_PRICE
    assert float(snapshot.base_to_quote) == pytest.approx(1 / 0.87)


def test_stalled_read_is_bounded_and_owner_recovers(wire):
    from ib_insync import Stock
    runtime, proxy = wire
    async def stalled(ib):
        return await ib.qualifyContractsAsync(Stock("HANG", "SMART", "USD"))
    with pytest.raises(TimeoutError, match="DEADLINE_EXCEEDED"):
        runtime.owner.run(stalled, timeout=0.1)
    assert proxy.qualifyContracts(Stock("AAPL", "SMART", "USD"))[0].symbol == "AAPL"
    assert runtime.owner.diagnostics()["in_flight"] == 0


def test_real_wire_preflight_reaches_durable_approval(wire):
    runtime, _ = wire
    result = runtime.service.preflight(
        {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1},
        proposal={"symbol": "AAPL", "side": "BUY", "quantity": 1})
    assert result["passed"], result
    assert float(result["entry_price"]) == ASK_PRICE
    assert runtime.store.approval(result["approval_id"])["status"] == "pending"
