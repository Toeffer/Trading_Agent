from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from trading_agent.domain import AccountFill, BrokerResult, ExecutionState, Position, utcnow
from trading_agent.persistence import StateConflict
from test_execution_application import service, approve
from test_execution_durability import reserved


def test_duplicate_fill_with_changed_timestamp_is_conflicting(tmp_path):
    store, eid = reserved(tmp_path)
    at = utcnow()
    store.record_fill(eid, "fill", 2, Decimal(100), observed_at=at)
    with pytest.raises(StateConflict, match="CONFLICTING_FILL_EVIDENCE"):
        store.record_fill(eid, "fill", 2, Decimal(100), observed_at=at - timedelta(days=1))


def test_stop_fills_cannot_exceed_approved_quantity(tmp_path):
    store, eid = reserved(tmp_path, "BUY")
    result = BrokerResult(ExecutionState.ACKNOWLEDGED, protection_state="confirmed",
        stop_fills=(("stop-one", 3, Decimal(95), utcnow()), ("stop-two", 3, Decimal(95), utcnow())))
    with pytest.raises(StateConflict, match="STOP_FILL_EXCEEDS"):
        store.record_result(eid, result)


def test_partial_sell_reserves_only_unfilled_shares_after_holdings_refresh(service):
    app, broker = service
    broker.snapshot_value = replace(broker.snapshot_value,
        positions=(Position("AAPL", 10, Decimal(1000), "TECH"),))
    aid = approve(app, side="SELL", quantity=5)
    broker.result = BrokerResult(ExecutionState.PARTIAL, filled_quantity=2,
        fills=(("sell-first", 2, Decimal(100), utcnow()),))
    app.submit(aid, authorized=True)
    broker.snapshot_value = replace(broker.snapshot_value,
        positions=(Position("AAPL", 8, Decimal(800), "TECH"),))
    result = app.preflight({"symbol": "AAPL", "action": "SELL", "totalQuantity": 5},
                           proposal={"symbol": "AAPL", "side": "SELL", "quantity": 5})
    assert result["passed"], result


def test_stale_holdings_after_fill_block_new_approval(service):
    app, broker = service
    aid = approve(app)
    broker.result = BrokerResult(ExecutionState.PARTIAL, protection_state="confirmed",
        filled_quantity=2, fills=(("buy-first", 2, Decimal(100), utcnow()),))
    app.submit(aid, authorized=True)
    result = app.preflight({"symbol": "AAPL", "totalQuantity": 1, "stopPrice": 95},
                           proposal={"symbol": "AAPL", "side": "BUY", "quantity": 1})
    assert result.get("code") == "HOLDINGS_EVIDENCE_MISMATCH", result


def test_fill_between_snapshot_and_reservation_blocks_transmission(service, monkeypatch):
    app, broker = service
    aid = approve(app)
    first = app.submit(aid, authorized=True)
    second = approve(app, quantity=1)
    reserve = app.store.reserve
    def raced(*args, **kwargs):
        app.store.record_fill(first["execution_id"], "raced", 1, Decimal(100), observed_at=utcnow())
        return reserve(*args, **kwargs)
    monkeypatch.setattr(app.store, "reserve", raced)
    result = app.submit(second, authorized=True)
    assert result.get("code") == "ACCOUNT_EVIDENCE_CHANGED", result
    assert len(broker.calls) == 1


def test_external_partial_order_is_counted_only_on_first_fill_date(service):
    app, broker = service
    yesterday = utcnow() - timedelta(days=1)
    first = AccountFill("PAPER_TEST", "external-one", "perm:100", "AAPL", "BUY", 2, Decimal(100), yesterday, history_complete=True)
    second = replace(first, broker_execution_id="external-two", quantity=1, executed_at=utcnow())
    broker.snapshot_value = replace(broker.snapshot_value,
        positions=(Position("AAPL", 3, Decimal(300), "TECH"),), verified_fills=(first, second), observed_at=utcnow())
    from trading_agent.risk import RiskPolicy
    snapshot = app._snapshot("AAPL", RiskPolicy.from_rules(app.rules_provider()))
    assert snapshot.daily_trade_count == 0
    assert app._snapshot("AAPL", RiskPolicy.from_rules(app.rules_provider())).daily_trade_count == 0


def test_unproven_external_history_blocks_intake(service):
    app, broker = service
    event = AccountFill("PAPER_TEST", "unknown", "perm:100", "AAPL", "BUY", 2, Decimal(100), utcnow())
    broker.snapshot_value = replace(broker.snapshot_value,
        positions=(Position("AAPL", 2, Decimal(200), "TECH"),), verified_fills=(event,), observed_at=utcnow())
    result = app.preflight({"symbol": "AAPL", "totalQuantity": 1, "stopPrice": 95},
                           proposal={"symbol": "AAPL", "side": "BUY", "quantity": 1})
    assert result["code"] == "ACCOUNTING_HISTORY_INCOMPLETE"


def test_v2_upgrade_preserves_fills_and_requires_reconciliation(tmp_path):
    from trading_agent.persistence import ExecutionStore
    store, eid = reserved(tmp_path)
    store.record_fill(eid, "before-upgrade", 2, Decimal(100), observed_at=utcnow())
    with store.connection() as db:
        original = tuple(db.execute("SELECT * FROM fills").fetchone())
        db.execute("PRAGMA user_version=2")
    upgraded = ExecutionStore(store.path)
    with upgraded.connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert tuple(db.execute("SELECT * FROM fills").fetchone()) == original
    assert upgraded.execution(eid)["execution_state"] == "unknown"
    assert upgraded.execution(eid)["retry_allowed"] is False
