"""Behavioral regressions for the audited approval-to-broker boundary."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_agent.domain import ApprovedOrderPlan, BrokerResult, ExecutionState
from trading_agent.persistence import ExecutionStore, StateConflict


def plan(side="BUY", quantity=5):
    now = datetime.now(timezone.utc)
    return ApprovedOrderPlan(
        account="PAPER_TEST", symbol="AAPL", contract_id=123, currency="USD",
        side=side, quantity=quantity, order_type="MKT", entry_price=Decimal("100"),
        stop_price=Decimal("95") if side == "BUY" else None,
        proposal_hash="a" * 64, policy_hash="b" * 64,
        created_at=now, expires_at=now + timedelta(seconds=300),
        market_observed_at=now,
    )


def test_approved_plan_round_trip_keeps_buy_stop():
    original = plan()
    restored = ApprovedOrderPlan.from_json(original.to_json())
    assert restored == original
    assert restored.stop_price == Decimal("95")
    with pytest.raises((AttributeError, TypeError)):
        restored.quantity = 100


def test_pending_creation_never_grants_human_authority(tmp_path):
    store = ExecutionStore(tmp_path / "execution.db")
    approval = store.create_pending(plan())
    with pytest.raises(PermissionError):
        store.rule(approval["approval_id"], "approved", authorized=False)
    assert store.approval(approval["approval_id"])["status"] == "pending"


def test_duplicate_submission_is_reserved_once_across_connections(tmp_path):
    path = tmp_path / "execution.db"
    store = ExecutionStore(path)
    approval = store.create_pending(plan())
    aid = approval["approval_id"]
    store.rule(aid, "approved", authorized=True)

    def reserve(_):
        return ExecutionStore(path).reserve(aid, authorized=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(16)))
    assert sum(created for _, created in results) == 1
    assert len({record["execution_id"] for record, _ in results}) == 1


def test_unknown_execution_blocks_new_approval_and_cannot_be_retried(tmp_path):
    store = ExecutionStore(tmp_path / "execution.db")
    first = store.create_pending(plan())["approval_id"]
    store.rule(first, "approved", authorized=True)
    execution, _ = store.reserve(first, authorized=True)
    store.record_result(execution["execution_id"], BrokerResult(ExecutionState.UNKNOWN))
    same, created = store.reserve(first, authorized=True)
    assert not created and same["execution_state"] == "unknown"
    second = store.create_pending(plan())["approval_id"]
    store.rule(second, "approved", authorized=True)
    with pytest.raises(StateConflict, match="UNRESOLVED_EXECUTION"):
        store.reserve(second, authorized=True)


def test_restart_invalidates_approvals_and_keeps_uncertain_intent(tmp_path):
    store = ExecutionStore(tmp_path / "execution.db")
    pending = store.create_pending(plan())["approval_id"]
    approved = store.create_pending(plan())["approval_id"]
    store.rule(approved, "approved", authorized=True)
    sent = store.create_pending(plan())["approval_id"]
    store.rule(sent, "approved", authorized=True)
    execution, _ = store.reserve(sent, authorized=True)
    store.startup()
    assert store.approval(pending)["status"] == "expired"
    assert store.approval(approved)["status"] == "expired"
    assert store.execution(execution["execution_id"])["execution_state"] == "unknown"


def test_partial_fill_is_counted_once_and_callbacks_deduplicated(tmp_path):
    store = ExecutionStore(tmp_path / "execution.db")
    aid = store.create_pending(plan())["approval_id"]
    store.rule(aid, "approved", authorized=True)
    execution, _ = store.reserve(aid, authorized=True)
    eid = execution["execution_id"]
    assert store.record_fill(eid, "fill-1", 2, Decimal("100"))
    assert not store.record_fill(eid, "fill-1", 2, Decimal("100"))
    assert store.record_fill(eid, "fill-2", 3, Decimal("101"))
    assert store.daily_trade_count("PAPER_TEST", datetime.now(timezone.utc).date()) == 1
    assert store.execution(eid)["filled_quantity"] == 5


def test_limit_orders_cannot_become_executable_plans():
    values = plan().to_dict()
    values["order_type"] = "LMT"
    with pytest.raises(ValueError, match="MKT"):
        ApprovedOrderPlan.from_dict(values)


@pytest.mark.parametrize("field,value", [("entry_price", "NaN"), ("quantity", True), ("account", "")])
def test_invalid_plan_values_fail_closed(field, value):
    values = plan().to_dict()
    values[field] = value
    with pytest.raises(ValueError):
        ApprovedOrderPlan.from_dict(values)
