import hashlib
import asyncio
from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from trading_agent.api import install
from trading_agent.application import ExecutionService
from trading_agent.persistence import ExecutionStore
from trading_agent.settings import Settings
from test_execution_application import FakeBroker, RULES


@pytest.fixture
def client(tmp_path):
    broker = FakeBroker()
    store = ExecutionStore(tmp_path / "execution.db")
    service = ExecutionService(store, broker, rules_provider=lambda: RULES,
                               account="PAPER_TEST", orders_enabled=lambda: True)
    app = FastAPI()
    settings = Settings(account="PAPER_TEST", token_hash=hashlib.sha256(b"synthetic-test-token").hexdigest())
    broker.event_failure = False
    session = SimpleNamespace(isConnected=lambda: True, managedAccounts=lambda: ["PAPER_TEST"])
    app.state.runtime = SimpleNamespace(settings=settings, service=service, store=store,
        owner=SimpleNamespace(run=lambda operation, **kwargs: asyncio.run(operation(session))),
        broker=broker, load_rules=lambda: RULES, export_failure=False,
        proposal=lambda path: {"symbol": "AAPL", "side": "BUY", "quantity": 5})
    install(app)
    with TestClient(app) as c:
        yield c, broker


def test_complete_http_preflight_approval_submit_and_repeat(client):
    client, broker = client
    result = client.post("/order/preflight", json={"symbol": "AAPL", "totalQuantity": 5,
                                                 "stopPrice": 95, "proposal_path": "fixture.json"}).json()
    assert result["passed"], result
    aid = result["approval_id"]
    detail = client.get("/order/approvals/" + aid).json()
    assert Decimal(detail["plan"]["stop_price"]) == Decimal("95")
    assert client.post("/order/approve", json={"approval_id": aid, "decision": "approve"}).status_code == 403
    headers = {"X-H1-Token": "synthetic-test-token"}
    assert client.post("/order/approve", json={"approval_id": aid, "decision": "approve"}, headers=headers).json()["approved"]
    assert client.post("/order/submit", json={"approval_id": aid}).status_code == 403
    submitted = client.post("/order/submit", json={"approval_id": aid}, headers=headers).json()
    assert submitted["submitted"], submitted
    repeated = client.post("/order/submit", json={"approval_id": aid}, headers=headers).json()
    assert repeated["execution_id"] == submitted["execution_id"]
    assert client.get("/order/executions/" + submitted["execution_id"]).json()["retry_allowed"] is False
    assert len(broker.calls) == 1


@pytest.mark.parametrize("quantity", [True, 1.2, "5"])
def test_http_rejects_coerced_quantities(client, quantity):
    client, broker = client
    assert client.post("/order/preflight", json={"symbol": "AAPL", "totalQuantity": quantity}).status_code == 422
    assert not broker.calls


def test_http_rejects_unknown_preflight_fields(client):
    client, _ = client
    result = client.post("/order/preflight", json={"symbol": "AAPL", "totalQuantity": 5, "whatIf": True}).json()
    assert result["passed"] is False
    assert "UNKNOWN_REQUEST_FIELD" in result["code"]


def test_health_reports_identity_without_claiming_order_readiness(client):
    client, broker = client
    health = client.get("/health").json()
    assert health["connected"] is True
    assert health["account"] == "PAPER_TEST"
    assert len(health["configuration_hash"]) == 64
    status = client.get("/status").json()["execution"]
    assert status["paper_order_ready"] is False
    assert "ORDERS_BLOCKED" in status["blockers"]
    assert "RELEASE_NOT_VERIFIED" in status["blockers"]
    broker.event_failure = True
    assert "BROKER_EVENT_REVIEW_REQUIRED" in client.get("/readiness").json()["blockers"]


def test_account_reconciliation_requires_h1_and_rejects_injected_fills(client):
    client, _ = client
    assert client.post("/order/account/reconcile", json={"symbol": "AAPL"}).status_code == 403
    assert client.post("/order/account/reconcile", json={"symbol": "AAPL", "fills": []},
                       headers={"X-H1-Token": "synthetic-test-token"}).status_code == 422


def test_health_without_runtime_is_unavailable():
    app = FastAPI()
    install(app)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 503


def test_importing_bridge_does_not_construct_client_or_read_rules(monkeypatch):
    import importlib
    import ib_insync
    def forbidden(*args, **kwargs):
        raise AssertionError("Broker construction at import")
    monkeypatch.setattr(ib_insync, "IB", forbidden)
    module = importlib.import_module("bridge")
    assert module.ib is None
    assert module._startup_safety["state"] == "not_started"
    assert len([r for r in module.app.routes if getattr(r, "path", None) == "/order/submit"]) == 1
