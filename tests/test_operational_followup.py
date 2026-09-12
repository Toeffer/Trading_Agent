import asyncio
import threading
from datetime import timedelta

import pytest

from trading_agent.broker_loop import BrokerLoop
from trading_agent.domain import utcnow
from test_execution_http import client
from test_execution_durability import reserved


def test_readiness_exposes_operator_metrics_without_execution_authority(client):
    http, _ = client
    body = http.get("/execution/readiness").json()
    assert body["operations"]["unresolved_executions"] == 0
    assert body["operations"]["last_account_reconciliation_at"] is None
    assert body["paper_order_ready"] is False
    assert body["operator_actions"]["ORDERS_BLOCKED"]


def test_timeout_keeps_capacity_until_cancellation_finishes():
    class Client:
        def disconnect(self):
            pass
    owner = BrokerLoop(Client, capacity=1)
    owner.start()
    cancelling = threading.Event()
    release = threading.Event()
    async def stubborn(client):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelling.set()
            while not release.is_set():
                await asyncio.sleep(0.001)
    try:
        with pytest.raises(TimeoutError):
            owner.run(stubborn, timeout=0.02)
        assert cancelling.wait(1)
        async def read(client):
            return 1
        with pytest.raises(RuntimeError, match="BROKER_QUEUE_FULL"):
            owner.run(read)
    finally:
        release.set()
        owner.close()


def test_monitoring_reports_durable_backlog_age_and_unknown_execution(tmp_path):
    from trading_agent.operations import observe
    store, eid = reserved(tmp_path)
    at = utcnow() + timedelta(seconds=60)
    report = observe(store, "PAPER_TEST", now=at)
    assert report.unresolved_executions == 1
    assert report.oldest_unresolved_age_seconds >= 60
    assert report.pending_exports > 0
    assert report.oldest_export_age_seconds >= 60
    store.export(tmp_path / "exports")
    assert observe(store, "PAPER_TEST", now=at).pending_exports == 0
    assert store.execution(eid)["retry_allowed"] is False


def test_unknown_reconciliation_is_not_reported_as_success(tmp_path):
    from trading_agent.operations import observe
    from trading_agent.domain import BrokerResult, ExecutionState
    store, eid = reserved(tmp_path)
    store.record_result(eid, BrokerResult(ExecutionState.UNKNOWN), reconciled=True)
    assert observe(store, "PAPER_TEST").last_execution_reconciliation_at is None
    store.record_result(eid, BrokerResult(ExecutionState.REJECTED), reconciled=True)
    assert observe(store, "PAPER_TEST").last_execution_reconciliation_at is not None
    assert observe(store, "OTHER").last_execution_reconciliation_at is None


def test_export_failure_raises_operator_alert_without_losing_state(client, monkeypatch):
    http, _ = client
    runtime = http.app.state.runtime
    runtime.export_failure = True
    body = http.get("/execution/readiness").json()
    assert "EXPORT_BACKLOG" in body["operator_actions"]
    assert body["paper_order_ready"] is False


def test_saturated_owner_is_not_misreported_as_account_disconnect(client):
    http, _ = client
    runtime = http.app.state.runtime
    def full(*args, **kwargs):
        raise RuntimeError("BROKER_QUEUE_FULL")
    runtime.owner.run = full
    body = http.get("/execution/readiness").json()
    assert "BROKER_QUEUE_FULL" in body["blockers"]
    assert "PAPER_ACCOUNT_NOT_CONNECTED" not in body["blockers"]
    assert body["service_ready_for_preflight"] is False
