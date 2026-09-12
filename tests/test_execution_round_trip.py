"""Complete guard -> SQLite -> actual IBKR adapter flows with a fake client."""
from dataclasses import replace
from decimal import Decimal

from ib_insync import CommissionReport, Execution, Fill
import guard

from trading_agent.acceptance import evidence_report
from trading_agent.application import ExecutionService
from trading_agent.broker_adapter import IBKRBroker
from trading_agent.broker_loop import BrokerLoop
from trading_agent.domain import OpenOrder, Position, utcnow
from trading_agent.persistence import ExecutionStore
from trading_agent.settings import Settings
from test_broker_contract import FakeIB
from test_execution_application import FakeBroker, RULES


class FilledIB(FakeIB):
    def fill(self, trade):
        order = trade.order
        order.permId = order.orderId + 1000
        execution = Execution(execId=f"fill-{order.orderId}", acctNumber=order.account, orderId=order.orderId,
                              clientId=order.clientId, permId=order.permId, shares=order.totalQuantity,
                              price=100, side="BOT" if order.action == "BUY" else "SLD")
        trade.fills.append(Fill(trade.contract, execution, CommissionReport(), utcnow()))
        trade.orderStatus.status = "Filled"
        trade.orderStatus.filled = order.totalQuantity
        trade.orderStatus.remaining = 0

    def placeOrder(self, contract, order):
        trade = super().placeOrder(contract, order)
        if order.parentId:
            self.fill(next(t for t in self.orders if t.order.orderId == order.parentId))
        elif order.transmit:
            self.fill(trade)
        return trade

    def trades(self):
        return self.orders

    async def reqAllOpenOrdersAsync(self):
        return self.orders

    async def reqCompletedOrdersAsync(self, **kwargs):
        return [t for t in self.orders if t.orderStatus.status in ("Filled", "Cancelled")]

    async def reqExecutionsAsync(self):
        return [f for t in self.orders for f in t.fills]


def test_paper_exercise_sequence_through_real_guard_and_adapter(tmp_path, monkeypatch):
    client = FilledIB()
    owner = BrokerLoop(lambda: client)
    owner.start()
    try:
        adapter = IBKRBroker(owner, Settings(account="PAPER_TEST"), {})
        market = FakeBroker()
        monkeypatch.setattr(adapter, "snapshot", market.snapshot)
        store = ExecutionStore(tmp_path / "execution.sqlite3")
        application = ExecutionService(store, adapter, rules_provider=lambda: RULES,
                                       account="PAPER_TEST", orders_enabled=lambda: True)
        monkeypatch.setattr(guard, "_execution_service", application)
        buy = application.preflight({"symbol": "AAPL", "action": "BUY", "totalQuantity": 1, "stopPrice": 95},
                                     proposal={"symbol": "AAPL", "side": "BUY", "quantity": 1})
        with guard.h1_authorized_scope():
            guard.approve_approval(buy["approval_id"])
            bought = guard.submit_order(buy["approval_id"])
            assert guard.submit_order(buy["approval_id"])["execution_id"] == bought["execution_id"]
        assert bought["execution_state"] == "filled" and bought["protection_state"] == "confirmed"
        assert len(client.orders) == 2
        market.snapshot_value = replace(market.snapshot_value,
            positions=(Position("AAPL", 1, Decimal(100), "TECH"),),
            open_orders=(OpenOrder("AAPL", "SELL", 1, Decimal(95), bought["execution_id"] + ":stop", False, 123),))
        request = {"symbol": "AAPL", "action": "SELL", "totalQuantity": 1}
        proposal = {"symbol": "AAPL", "side": "SELL", "quantity": 1}
        assert application.preflight(request, proposal=proposal)["code"] == "CLOSE_ONLY_EXCEEDED"
        # Simulated operator action, outside the application/adapter. Production
        # code has no automatic cancellation operation.
        async def operator_cancels_stop(ib):
            ib.orders[1].orderStatus.status = "Cancelled"
        owner.run(operator_cancels_stop)
        application.reconcile(bought["execution_id"], authorized=True)
        market.snapshot_value = replace(market.snapshot_value, open_orders=())
        sell = application.preflight(request, proposal=proposal)
        with guard.h1_authorized_scope():
            guard.approve_approval(sell["approval_id"])
            sold = guard.submit_order(sell["approval_id"])
        assert sold["execution_state"] == "filled"
        market.snapshot_value = replace(market.snapshot_value, positions=())
        application.reconcile(sold["execution_id"], authorized=True)
        report = evidence_report(store, bought["execution_id"], sold["execution_id"])
        assert report["execution_evidence_consistent"], report
        assert report["host_and_release_verified"] is False
        assert len(client.orders) == 3
        assert store.daily_trade_count("PAPER_TEST", utcnow().date()) == 2
    finally:
        owner.close()
