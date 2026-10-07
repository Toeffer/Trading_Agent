from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import sqlite3

import pytest

from trading_agent.domain import BrokerResult, ExecutionState, utcnow
from trading_agent.persistence import ExecutionStore, StateConflict
from trading_agent.ownership import ServiceLock
from test_execution_regressions import plan


def reserved(tmp_path, side="SELL"):
    store = ExecutionStore(tmp_path / "execution.sqlite3")
    aid = store.create_pending(plan(side))["approval_id"]
    store.rule(aid, "approved", authorized=True)
    execution, _ = store.reserve(aid, authorized=True)
    return store, execution["execution_id"]


def test_result_and_fills_roll_back_together_on_conflicting_evidence(tmp_path):
    store, eid = reserved(tmp_path)
    now = utcnow()
    result = BrokerResult(ExecutionState.FILLED, filled_quantity=5,
        fills=(("one", 2, Decimal(100), now), ("two", 6, Decimal(100), now)))
    with pytest.raises(StateConflict):
        store.record_result(eid, result)
    assert store.execution(eid)["execution_state"] == "unknown"
    assert store.execution(eid)["filled_quantity"] == 0
    assert len(store.reservations("PAPER_TEST")) == 1
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM broker_events").fetchone()[0] == 0


def test_late_fill_stays_quarantined_until_human_reconciliation(tmp_path):
    store, eid = reserved(tmp_path)
    store.record_result(eid, BrokerResult(ExecutionState.UNKNOWN))
    result = BrokerResult(ExecutionState.FILLED, filled_quantity=5,
        fills=(("late", 5, Decimal(100), utcnow()),))
    store.record_result(eid, result)
    assert store.execution(eid)["execution_state"] == "unknown"
    assert store.execution(eid)["filled_quantity"] == 5
    assert store.reservations("PAPER_TEST")
    store.record_result(eid, result, reconciled=True)
    assert store.execution(eid)["execution_state"] == "filled"
    assert not store.reservations("PAPER_TEST")


def test_fill_total_without_execution_evidence_is_unknown(tmp_path):
    store, eid = reserved(tmp_path)
    store.record_result(eid, BrokerResult(ExecutionState.FILLED, filled_quantity=5))
    assert store.execution(eid)["execution_state"] == "unknown"
    assert store.reservations("PAPER_TEST")


def test_outbox_export_failure_preserves_authoritative_events(tmp_path, monkeypatch):
    store, eid = reserved(tmp_path)
    real = type(tmp_path).replace
    def failed(self, target):
        raise OSError("synthetic disk failure")
    monkeypatch.setattr(type(tmp_path), "replace", failed)
    with pytest.raises(OSError):
        store.export(tmp_path / "exports")
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM outbox WHERE exported=1").fetchone()[0] == 0
    monkeypatch.setattr(type(tmp_path), "replace", real)
    assert store.export(tmp_path / "exports") > 0
    assert store.export(tmp_path / "exports") == 0
    assert store.execution(eid)["retry_allowed"] is False


def test_pending_persistence_failure_leaves_no_record(tmp_path, monkeypatch):
    store = ExecutionStore(tmp_path / "execution.sqlite3")
    def fail(*args):
        raise sqlite3.OperationalError("synthetic persistence failure")
    monkeypatch.setattr(store, "_event", fail)
    with pytest.raises(sqlite3.Error):
        store.create_pending(plan())
    assert store.approvals() == []


def test_partial_fills_on_two_days_count_trade_only_on_first_day(tmp_path):
    store, eid = reserved(tmp_path)
    now = utcnow()
    store.record_fill(eid, "first", 2, Decimal(100), observed_at=now - timedelta(days=1))
    store.record_fill(eid, "second", 3, Decimal(100), observed_at=now)
    assert store.daily_trade_count("PAPER_TEST", now.date()) == 0
    assert store.daily_trade_count("PAPER_TEST", (now - timedelta(days=1)).date()) == 1


def test_one_execution_service_owns_a_state_directory(tmp_path):
    first, second = ServiceLock(tmp_path / "service.lock"), ServiceLock(tmp_path / "service.lock")
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="ALREADY_RUNNING"):
            second.acquire()
    finally:
        first.close()
    second.acquire()
    second.close()
