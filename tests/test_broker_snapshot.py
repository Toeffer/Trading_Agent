from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from trading_agent.broker_adapter import IBKRBroker
from trading_agent.broker_loop import BrokerLoop
from trading_agent.domain import utcnow
from trading_agent.settings import Settings
from test_broker_contract import FakeIB


class SnapshotIB(FakeIB):
    def __init__(self):
        super().__init__()
        self.contract = NS(symbol="AAPL", currency="USD", conId=123)
        self.inventory = [NS(account="PAPER_TEST", contract=self.contract, position=5)]
        self.valuations = [NS(account="PAPER_TEST", contract=self.contract, position=5, marketValue=500)]
        self.values = [NS(account="PAPER_TEST", tag="NetLiquidation", currency="EUR", value="100000"),
                       NS(account="PAPER_TEST", tag="ExchangeRate", currency="USD", value="0.9")]
        self.cancelled_data = 0

    async def reqAccountUpdatesAsync(self, account):
        return None

    async def reqPositionsAsync(self):
        return self.inventory

    async def reqAllOpenOrdersAsync(self):
        return self.orders

    async def reqExecutionsAsync(self):
        return []

    def accountValues(self, account):
        return self.values

    def portfolio(self, account):
        return self.valuations

    def reqMarketDataType(self, kind):
        assert kind == 1

    def reqTickByTickData(self, *args):
        return NS(marketDataType=1, tickByTicks=[NS(time=utcnow(), bidPrice=99.99, askPrice=100)])

    def cancelTickByTickData(self, *args):
        self.cancelled_data += 1

    def openTrades(self):
        return self.orders

    def trades(self):
        return self.orders


@pytest.fixture
def broker():
    client = SnapshotIB()
    owner = BrokerLoop(lambda: client)
    owner.start()
    yield IBKRBroker(owner, Settings(account="PAPER_TEST"), {"AAPL": "TECH"}), client
    owner.close()


def test_snapshot_values_actual_holdings_in_account_currency(broker):
    adapter, client = broker
    snapshot = adapter.snapshot("AAPL")
    assert snapshot.positions[0].market_value_base == Decimal("450")
    assert snapshot.base_to_quote == 1 / Decimal("0.9")
    assert client.cancelled_data == 1


def test_missing_valuation_cannot_disappear_as_zero_exposure(broker):
    adapter, client = broker
    client.valuations = []
    with pytest.raises(ValueError, match="VALUATION_INCOMPLETE"):
        adapter.snapshot("AAPL")


@pytest.mark.parametrize("rate", [None, "NaN", "0", "-1"])
def test_missing_or_invalid_fx_fails_closed(broker, rate):
    adapter, client = broker
    if rate is None:
        client.values.pop()
    else:
        client.values[-1].value = rate
    with pytest.raises(ValueError):
        adapter.snapshot("AAPL")


def test_pending_submit_with_default_zero_remaining_still_reserves_shares(broker):
    adapter, client = broker
    client.orders = [NS(contract=client.contract,
        order=NS(account="PAPER_TEST", action="SELL", totalQuantity=3, orderType="STP", auxPrice=95, orderRef="pending", parentId=42, permId=903),
        orderStatus=NS(status="PendingSubmit", remaining=0, filled=0))]
    snapshot = adapter.snapshot("AAPL")
    assert snapshot.open_orders[0].remaining == 3
    assert snapshot.open_orders[0].counts_as_pending_trade is False


@pytest.mark.parametrize("label", ["", "shared-manual-label"])
def test_external_open_orders_keep_distinct_broker_identities(broker, label):
    adapter, client = broker
    client.orders = [NS(contract=client.contract,
        order=NS(account="PAPER_TEST", action="BUY", totalQuantity=1, orderType="LMT",
                 lmtPrice=100, orderRef=label, parentId=0, permId=identity),
        orderStatus=NS(status="Submitted", remaining=1, filled=0)) for identity in (901, 902)]
    snapshot = adapter.snapshot("AAPL")
    assert {order.execution_ref for order in snapshot.open_orders} == {"perm:901", "perm:902"}


def test_external_open_order_without_durable_identity_blocks_snapshot(broker):
    adapter, client = broker
    client.orders = [NS(contract=client.contract,
        order=NS(account="PAPER_TEST", action="BUY", totalQuantity=1, orderType="LMT",
                 lmtPrice=100, orderRef="manual", parentId=0, permId=0),
        orderStatus=NS(status="Submitted", remaining=1, filled=0))]
    with pytest.raises(ValueError, match="OPEN_ORDER_IDENTITY_UNAVAILABLE"):
        adapter.snapshot("AAPL")
