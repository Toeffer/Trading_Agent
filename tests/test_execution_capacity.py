from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

from trading_agent.domain import BrokerResult, ExecutionState, Position, OpenOrder
from test_execution_application import service, approve, RULES


def test_different_approvals_cannot_consume_same_daily_capacity(service):
    application, broker = service
    rules = deepcopy(RULES)
    rules["max_trades_per_day"]["value"] = 1
    application.rules_provider = lambda: rules
    first, second = approve(application), approve(application)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda aid: application.submit(aid, authorized=True), [first, second]))
    assert sum(r.get("submitted", False) for r in results) == 1
    assert len(broker.calls) == 1
    assert any(r.get("code") == "DAILY_CAPACITY_EXCEEDED" for r in results)


def test_different_sells_cannot_reserve_same_holdings(service):
    application, broker = service
    broker.snapshot_value = replace(broker.snapshot_value, positions=(Position("AAPL", 5, Decimal(500), "TECH"),))
    broker.result = BrokerResult(ExecutionState.ACKNOWLEDGED)
    first, second = approve(application, side="SELL"), approve(application, side="SELL")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda aid: application.submit(aid, authorized=True), [first, second]))
    assert sum(r.get("submitted", False) for r in results) == 1
    assert len(broker.calls) == 1
    assert any(r.get("code") == "CLOSE_ONLY_EXCEEDED" for r in results)


def test_open_protective_sell_prevents_double_selling(service):
    application, broker = service
    broker.snapshot_value = replace(broker.snapshot_value,
        positions=(Position("AAPL", 5, Decimal(500), "TECH"),),
        open_orders=(OpenOrder("AAPL", "SELL", 5, Decimal(475), "manual-protective-stop", False),))
    result = application.preflight({"symbol": "AAPL", "action": "SELL", "totalQuantity": 5},
                                   proposal={"symbol": "AAPL", "side": "SELL", "quantity": 5})
    assert result["passed"] is False
    assert result["code"] == "CLOSE_ONLY_EXCEEDED"


def test_changing_proposal_after_preflight_cannot_change_approved_quantity(service):
    application, broker = service
    proposal = {"symbol": "AAPL", "side": "BUY", "quantity": 5}
    result = application.preflight({"symbol": "AAPL", "totalQuantity": 5, "stopPrice": 95}, proposal=proposal)
    aid = result["approval_id"]
    proposal["quantity"] = 1000
    proposal["symbol"] = "JPM"
    application.rule(aid, "approve", authorized=True)
    assert application.submit(aid, authorized=True)["submitted"] is True
    assert broker.calls[0][0].symbol == "AAPL" and broker.calls[0][0].quantity == 5
