from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from trading_agent.application import ExecutionService
from trading_agent.domain import BrokerResult, ExecutionState, PortfolioSnapshot, Position, utcnow
from trading_agent.persistence import ExecutionStore
from trading_agent.risk import RiskPolicy


RULES = {
    "enforced": True, "symbol_allowlist": {"mode": "explicit_list", "allow": ["AAPL", "JPM"]},
    "symbol_sectors": {"AAPL": "TECH", "JPM": "FINANCE"}, "us_etf_blocklist": [],
    "max_position_notional": {"value": 5}, "max_risk_per_trade": {"value": 2},
    "max_total_exposure": {"value": 30}, "max_trades_per_day": {"value": 2},
    "max_positions_per_sector": {"value": 1}, "loss_halts": {"daily": {"value": 1}, "weekly": {"value": 3}},
}


class FakeBroker:
    def __init__(self):
        now = utcnow()
        self.snapshot_value = PortfolioSnapshot(
            "PAPER_TEST", "paper", "EUR", "USD", Decimal("100000"), Decimal("1.1"),
            now, now, "realtime", Decimal("99.99"), Decimal("100"), (), (), 0, False, False, 123)
        self.calls = []
        self.result = BrokerResult(ExecutionState.ACKNOWLEDGED, order_id=1,
                                   stop_order_id=2, protection_state="confirmed")
        self.block = None
        self.entered = threading.Event()

    def snapshot(self, symbol):
        return self.snapshot_value

    def submit(self, plan, reference):
        self.calls.append((plan, reference))
        self.entered.set()
        if self.block:
            self.block.wait(5)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def reconcile(self, plan, reference):
        return self.result


@pytest.fixture
def service(tmp_path):
    broker = FakeBroker()
    service = ExecutionService(ExecutionStore(tmp_path / "execution.db"), broker,
                               rules_provider=lambda: RULES, account="PAPER_TEST",
                               orders_enabled=lambda: True)
    return service, broker


def preflight(service, side="BUY", quantity=5):
    request = {"symbol": "AAPL", "action": side, "totalQuantity": quantity, "orderType": "MKT", "stopPrice": 95}
    proposal = {"symbol": "AAPL", "side": side, "quantity": quantity}
    return service.preflight(request, proposal=proposal)


def approve(service, **kwargs):
    result = preflight(service, **kwargs)
    assert result["passed"], result
    aid = result["approval_id"]
    service.rule(aid, "approve", authorized=True)
    return aid


def test_real_approval_serialization_reaches_adapter_with_stop(service):
    service, broker = service
    aid = approve(service)
    result = service.submit(aid, authorized=True)
    assert result["submitted"]
    assert broker.calls[0][0].stop_price == Decimal("95")


def test_sell_acknowledgement_consumes_approval(service):
    service, broker = service
    broker.snapshot_value = replace(broker.snapshot_value, positions=(Position("AAPL", 5, Decimal("455"), "TECH"),))
    broker.result = BrokerResult(ExecutionState.ACKNOWLEDGED, order_id=1)
    aid = approve(service, side="SELL")
    assert service.submit(aid, authorized=True)["submitted"]
    assert service.submit(aid, authorized=True)["submitted"]
    assert len(broker.calls) == 1


def test_concurrent_submit_calls_broker_once(service):
    service, broker = service
    aid = approve(service)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: service.submit(aid, authorized=True), range(16)))
    assert len(broker.calls) == 1
    assert len({r["execution_id"] for r in results}) == 1


def test_timeout_remains_unknown_without_retry(service):
    service, broker = service
    aid = approve(service)
    broker.result = TimeoutError("late broker reply")
    result = service.submit(aid, authorized=True)
    assert result["execution_state"] == "unknown"
    assert result["retry_allowed"] is False
    assert service.submit(aid, authorized=True)["execution_id"] == result["execution_id"]
    assert len(broker.calls) == 1


def test_binding_rejects_unrelated_proposal(service):
    service, _ = service
    result = service.preflight({"symbol": "AAPL", "action": "SELL", "totalQuantity": 5},
                               proposal={"symbol": "JPM", "side": "BUY", "quantity": 1})
    assert not result["passed"] and result["code"] == "PROPOSAL_MISMATCH"


def test_lmt_validation_never_creates_executable_approval(service):
    service, broker = service
    result = service.preflight({"symbol": "AAPL", "action": "BUY", "totalQuantity": 5,
                                "orderType": "LMT", "limitPrice": 101, "stopPrice": 95},
                               proposal={"symbol": "AAPL", "side": "BUY", "quantity": 5})
    assert result["passed"] and result["validation_only"]
    assert "approval_id" not in result and not broker.calls


def test_real_holdings_are_included_in_exposure(service):
    service, broker = service
    broker.snapshot_value = replace(broker.snapshot_value, positions=(Position("JPM", 400, Decimal("40000"), "FINANCE"),))
    result = preflight(service)
    assert not result["passed"] and result["code"] == "PORTFOLIO_EXPOSURE_EXCEEDED"


def test_submit_revalidates_holdings_and_capacity(service):
    service, broker = service
    broker.snapshot_value = replace(broker.snapshot_value, positions=(Position("AAPL", 5, Decimal("455"), "TECH"),))
    aid = approve(service, side="SELL")
    broker.snapshot_value = replace(broker.snapshot_value, positions=())
    assert service.submit(aid, authorized=True)["code"] == "HOLDINGS_EVIDENCE_MISMATCH"
    assert not broker.calls


def test_loss_halt_allows_confirmed_close_only_exit(service):
    service, broker = service
    broker.snapshot_value = replace(broker.snapshot_value, positions=(Position("AAPL", 5, Decimal("455"), "TECH"),), daily_loss_halt=True)
    aid = approve(service, side="SELL")
    broker.result = BrokerResult(ExecutionState.ACKNOWLEDGED, order_id=1)
    assert service.submit(aid, authorized=True)["submitted"]


@pytest.mark.parametrize("changes", [
    {"base_to_quote": Decimal("NaN")}, {"account": "WRONG_ACCOUNT"},
    {"market_data_type": "delayed"}, {"market_observed_at": utcnow() - timedelta(minutes=5)},
])
def test_invalid_account_or_market_data_blocks_execution(service, changes):
    service, broker = service
    broker.snapshot_value = replace(broker.snapshot_value, **changes)
    assert not preflight(service)["passed"]
    assert not broker.calls


def test_approval_and_submission_require_human_authority(service):
    service, broker = service
    aid = preflight(service)["approval_id"]
    with pytest.raises(PermissionError):
        service.rule(aid, "approve", authorized=False)
    with pytest.raises(PermissionError):
        service.submit(aid, authorized=False)
    assert not broker.calls
