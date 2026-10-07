from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

import pytest

from trading_agent.domain import BrokerResult, ExecutionState, utcnow, timestamp
from trading_agent.replay import replay
from trading_agent.recovery import rehearse
from trading_agent.persistence import ExecutionStore
from trading_agent.operations import observe
from test_execution_application import service, approve
from test_execution_durability import reserved


def test_disposable_upgrade_preserves_source_and_fill_evidence(tmp_path):
    store, eid = reserved(tmp_path)
    store.record_fill(eid, "verified", 2, Decimal(100), observed_at=utcnow())
    with store.connection() as db:
        db.execute("PRAGMA user_version=2")
    report = rehearse(store.path, tmp_path / "rehearsal")
    assert report["rehearsal_passed"]
    assert report["source_schema"] == 2
    assert report["broker_contacted"] is False
    with store.connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
    copy = ExecutionStore.open_readonly(tmp_path / "rehearsal" / "candidate.sqlite3")
    assert copy.execution(eid)["execution_state"] == "unknown"
    assert copy.execution(eid)["retry_allowed"] is False
    with pytest.raises(ValueError):
        rehearse(store.path, tmp_path / "rehearsal")


def test_successful_account_reconciliation_has_durable_timestamp(service):
    app, _ = service
    assert observe(app.store, app.account).last_account_reconciliation_at is None
    with pytest.raises(PermissionError):
        app.reconcile_account("AAPL", authorized=False)
    assert observe(app.store, app.account).last_account_reconciliation_at is None
    app.reconcile_account("AAPL", authorized=True)
    assert observe(app.store, app.account).last_account_reconciliation_at is not None


@pytest.fixture
def record(service):
    app, broker = service
    aid = approve(app)
    broker.result = BrokerResult(ExecutionState.PARTIAL, protection_state="confirmed", filled_quantity=2,
        fills=(("first", 2, Decimal("100.10"), utcnow()),))
    app.submit(aid, authorized=True)
    saved = app.store.decision_snapshots()[-1]
    assert saved["schema_version"] == 3
    return saved


def test_export_replays_actual_persisted_fills_and_decision(record):
    result = replay(record)
    assert result["decision_matches_recorded"] is True
    assert result["slippage"]["quantity"] == "2"
    assert result["slippage"]["per_share"] == "0.10"
    assert result["cost_coverage_complete"] is False
    assert "commission_evidence_incomplete" in result["evidence_issues"]


def test_duplicate_fill_and_commission_do_not_double_costs(record):
    record["realized_fills"] *= 2
    commission = {"broker_execution_id": "first", "currency": "USD", "amount": "1.25"}
    record["commissions"] = [commission, deepcopy(commission)]
    record["commission_provenance"] = "synthetic-statement"
    result = replay(record)
    assert result["fill_count"] == 1
    assert result["costs_by_currency"] == {"USD": "1.25"}
    assert result["cost_coverage_complete"] is True


@pytest.mark.parametrize("field,value", [("quantity", 6), ("price", "NaN"), ("account", "OTHER"), ("contract_id", 999), ("executed_at", "2026-09-01T12:00:00"), ("executed_at", "2500-01-01T00:00:00+00:00")])
def test_invalid_fill_evidence_does_not_change_strategy_decision(record, field, value):
    record["realized_fills"][0][field] = value
    result = replay(record)
    assert result["decision"]["allowed"] is True
    assert result["slippage"] is None
    assert result["evidence_issues"]


def test_conflicting_duplicate_timestamp_is_reported(record):
    other = deepcopy(record["realized_fills"][0])
    other["executed_at"] = (timestamp(other["executed_at"]) + timedelta(microseconds=1)).isoformat()
    record["realized_fills"].append(other)
    assert "CONFLICTING_FILL_EVIDENCE" in replay(record)["evidence_issues"]


def test_recorded_decision_mismatch_is_visible(record):
    record["recorded_decision"] = {"allowed": False, "code": "DAILY_CAPACITY_EXCEEDED"}
    assert replay(record)["decision_matches_recorded"] is False


def test_conflicting_commission_cannot_produce_complete_cost_coverage(record):
    record["commissions"] = [{"broker_execution_id": "first", "currency": "USD", "amount": "1"},
                             {"broker_execution_id": "first", "currency": "USD", "amount": "2"}]
    result = replay(record)
    assert result["cost_coverage_complete"] is False
    assert result["costs_by_currency"] == {}
    assert "invalid_or_conflicting_commissions" in result["evidence_issues"]
