import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import threading
from types import SimpleNamespace

import pytest

from trading_agent.broker_adapter import IBKRBroker
from trading_agent.broker_loop import BrokerLoop
from trading_agent.domain import ApprovedOrderPlan, ExecutionState, utcnow
from trading_agent.settings import Settings


def order_plan(side="BUY"):
    now = utcnow()
    return ApprovedOrderPlan("PAPER_TEST", "AAPL", 123, "USD", side, 5, "MKT", Decimal("100"),
                             Decimal("95") if side == "BUY" else None, "a" * 64, "b" * 64,
                             now, now + timedelta(seconds=300), now)


class FakeIB:
    def __init__(self, status="Submitted"):
        self.status = status
        self.orders = []
        self.identities = set()
        self.next_id = 1
        self.client = SimpleNamespace(getReqId=self.req_id)

    def req_id(self):
        value = self.next_id
        self.next_id += 1
        return value

    def isConnected(self):
        return True

    def managedAccounts(self):
        return ["PAPER_TEST"]

    async def qualifyContractsAsync(self, contract):
        self.identities.add(threading.get_ident())
        return [SimpleNamespace(symbol="AAPL", currency="USD", conId=123)]

    def placeOrder(self, contract, order):
        self.identities.add(threading.get_ident())
        trade = SimpleNamespace(order=order, contract=contract, orderStatus=SimpleNamespace(
            status=self.status if order.transmit else "PendingSubmit", filled=0, remaining=order.totalQuantity), fills=[])
        self.orders.append(trade)
        if order.parentId:
            self.orders[0].orderStatus.status = self.status
        return trade

    def disconnect(self):
        pass


@pytest.mark.parametrize("status,expected", [
    ("Submitted", ExecutionState.ACKNOWLEDGED),
    ("PreSubmitted", ExecutionState.ACKNOWLEDGED),
    ("PendingSubmit", ExecutionState.UNKNOWN),
    ("PendingCancel", ExecutionState.UNKNOWN),
])
def test_real_adapter_stages_parent_then_stop_and_waits_for_broker_evidence(status, expected):
    fake = FakeIB(status)
    owner = BrokerLoop(lambda: fake)
    owner.start()
    try:
        broker = IBKRBroker(owner, Settings(account="PAPER_TEST", acknowledgement_timeout=0.05), {})
        result = broker.submit(order_plan(), "exec_test")
        assert result.state == expected
        assert len(fake.orders) == 2
        parent, stop = [t.order for t in fake.orders]
        assert parent.transmit is False and stop.transmit is True
        assert stop.parentId == parent.orderId and stop.auxPrice == 95
        assert len(fake.identities) == 1 and threading.get_ident() not in fake.identities
        assert result.protection_state == ("confirmed" if expected == ExecutionState.ACKNOWLEDGED else "unknown")
    finally:
        owner.close()


def test_real_adapter_sell_has_same_result_contract():
    fake = FakeIB()
    owner = BrokerLoop(lambda: fake)
    owner.start()
    try:
        broker = IBKRBroker(owner, Settings(account="PAPER_TEST"), {})
        result = broker.submit(order_plan("SELL"), "exec_sell")
        assert result.state == ExecutionState.ACKNOWLEDGED
        assert result.protection_state == "not_applicable"
        assert len(fake.orders) == 1
    finally:
        owner.close()


def test_wrong_account_never_reaches_place_order():
    fake = FakeIB()
    owner = BrokerLoop(lambda: fake)
    owner.start()
    try:
        broker = IBKRBroker(owner, Settings(account="OTHER_ACCOUNT"), {})
        with pytest.raises(ValueError, match="ACCOUNT_MISMATCH"):
            broker.submit(order_plan(), "exec_wrong")
        assert not fake.orders
    finally:
        owner.close()


def test_queue_is_bounded_and_timeouts_do_not_resubmit():
    fake = FakeIB()
    owner = BrokerLoop(lambda: fake, capacity=1)
    owner.start()
    async def slow(_):
        await asyncio.sleep(0.15)
        return 1
    try:
        with pytest.raises(TimeoutError):
            owner.run(slow, timeout=0.01, cancel_on_timeout=False)
        with pytest.raises(RuntimeError, match="QUEUE_FULL"):
            owner.run(slow)
    finally:
        owner.close()
