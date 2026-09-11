import pytest
import guard
from test_execution_application import service, approve


def test_guard_compatibility_uses_durable_service_and_requires_h1(service, monkeypatch):
    application, broker = service
    monkeypatch.setattr(guard, "_execution_service", application)
    aid = approve(application)
    with pytest.raises(PermissionError):
        guard.submit_order(aid)
    with guard.h1_authorized_scope():
        first = guard.submit_order(aid)
        second = guard.submit_order(aid)
    assert first["execution_id"] == second["execution_id"]
    assert len(broker.calls) == 1


def test_legacy_injected_provider_cannot_bypass_authority(service, monkeypatch):
    application, broker = service
    monkeypatch.setattr(guard, "_execution_service", application)
    with guard.h1_authorized_scope():
        assert guard.submit_order("anything", order_provider=lambda _: pytest.fail("Called legacy provider"))["submitted"] is False
    assert not broker.calls


def test_guard_h1_nested_scopes_preserve_outer_authorization():
    assert guard._h1_authorized.get() is False
    with guard.h1_authorized_scope():
        with guard.h1_authorized_scope():
            assert guard._h1_authorized.get() is True
        assert guard._h1_authorized.get() is True
    assert guard._h1_authorized.get() is False


def test_legacy_preflight_routes_to_same_application(service, monkeypatch):
    app, broker = service
    monkeypatch.setattr(guard, "_execution_service", app)
    monkeypatch.setattr(guard, "_proposal_loader", lambda path: {"symbol": "AAPL", "side": "BUY", "quantity": 5})
    result = guard.run_preflight({"symbol": "AAPL", "totalQuantity": 5, "stopPrice": 95}, proposal_path="fixture.json")
    assert result["passed"]
    assert app.store.approval(result["approval_id"])["plan"]["quantity"] == 5
    assert not broker.calls


def test_legacy_preflight_without_runtime_is_unavailable(monkeypatch):
    monkeypatch.setattr(guard, "_execution_service", None)
    assert guard.run_preflight({})["code"] == "EXECUTION_RUNTIME_NOT_READY"
