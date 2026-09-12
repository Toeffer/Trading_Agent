import httpx
from fastapi.testclient import TestClient
import pytest

from trading_agent.ui import app


@pytest.fixture
def client():
    yield TestClient(app)
    if hasattr(app.state, "bridge_transport"):
        del app.state.bridge_transport


def test_failed_approval_never_attempts_submission(client):
    calls = []
    def broker(request):
        calls.append(request.url.path)
        assert request.headers["X-H1-Token"] == "synthetic"
        return httpx.Response(409, json={"approved": False})
    app.state.bridge_transport = httpx.MockTransport(broker)
    result = client.post("/api/action", json={"action": "approve-submit", "approval_id": "aprv_test", "h1_token": "synthetic"})
    assert result.status_code == 409
    assert calls == ["/order/approve"]
    assert "synthetic" not in result.text


def test_successful_ui_action_keeps_token_out_of_body(client):
    calls = []
    def broker(request):
        calls.append(request.url.path)
        assert b"synthetic" not in request.content
        return httpx.Response(200, json={"approved": True} if request.url.path.endswith("approve") else
                              {"execution_state": "unknown", "retry_allowed": False})
    app.state.bridge_transport = httpx.MockTransport(broker)
    result = client.post("/api/action", json={"action": "approve-submit", "approval_id": "aprv_test", "h1_token": "synthetic"})
    assert result.json()["retry_allowed"] is False
    assert calls == ["/order/approve", "/order/submit"]


def test_missing_token_and_invalid_action_fail_before_http(client):
    def forbidden(request):
        raise AssertionError("No HTTP operation expected")
    app.state.bridge_transport = httpx.MockTransport(forbidden)
    assert client.post("/api/action", json={"action": "submit", "approval_id": "aprv_test", "h1_token": ""}).status_code == 400
