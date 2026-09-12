"""Restart invalidation through the authoritative database and HTTP contracts.

The pre-remediation tests assumed operational writes during module import and
JSON execution authority. Those mechanisms have been removed. These cases
retain the invariant while exercising explicit startup and real serialization.
"""
import pytest

from trading_agent.persistence import ExecutionStore, StateConflict
from test_execution_regressions import plan
from test_execution_http import client


@pytest.mark.parametrize("ruling", [None, "approved", "denied"])
def test_restart_invalidates_every_unsubmitted_approval(tmp_path, ruling):
    store = ExecutionStore(tmp_path / "execution.sqlite3")
    aid = store.create_pending(plan())["approval_id"]
    if ruling:
        store.rule(aid, ruling, authorized=True)
    restarted = ExecutionStore(store.path)
    # Opening persistence is not application startup.
    assert restarted.approval(aid)["status"] == (ruling or "pending")
    restarted.startup()
    assert restarted.approval(aid)["status"] == ("denied" if ruling == "denied" else "expired")
    with pytest.raises(StateConflict):
        restarted.reserve(aid, authorized=True)


def test_restart_preserves_reserved_intent_and_prevents_resubmission(tmp_path):
    store = ExecutionStore(tmp_path / "execution.sqlite3")
    aid = store.create_pending(plan())["approval_id"]
    store.rule(aid, "approved", authorized=True)
    original, _ = store.reserve(aid, authorized=True)
    restarted = ExecutionStore(store.path)
    restarted.startup()
    current, created = restarted.reserve(aid, authorized=True)
    assert not created
    assert current["execution_id"] == original["execution_id"]
    assert current["execution_state"] == "unknown"
    assert current["retry_allowed"] is False


@pytest.mark.parametrize("extra", [{"transmit": True}, {"whatIf": True}, {"typo": 1}])
def test_unknown_fields_reach_strict_validation(client, extra):
    http, broker = client
    result = http.post("/order/preflight", json={"symbol": "AAPL", "totalQuantity": 5, "stopPrice": 95, **extra}).json()
    assert result["passed"] is False
    assert "UNKNOWN_REQUEST_FIELD" in result["code"]
    assert not broker.calls
