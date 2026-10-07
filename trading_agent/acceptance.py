"""Validate the paper exercise's authoritative event sequence, without orders."""

import json
from typing import Any

from trading_agent.domain import ApprovedOrderPlan
from trading_agent.persistence import ExecutionStore


def evidence_report(store: ExecutionStore, buy_id: str, sell_id: str) -> dict[str, Any]:
    buy, sell = store.execution(buy_id), store.execution(sell_id)
    buy_plan = ApprovedOrderPlan.from_dict(store.approval(buy["approval_id"])["plan"])
    sell_plan = ApprovedOrderPlan.from_dict(store.approval(sell["approval_id"])["plan"])
    checks = {
        "separate_approvals": buy["approval_id"] != sell["approval_id"],
        "buy_then_close_sell": buy_plan.side == "BUY" and sell_plan.side == "SELL",
        "same_account_and_contract": (buy_plan.account, buy_plan.contract_id)
        == (sell_plan.account, sell_plan.contract_id),
        "one_share_exercise": buy_plan.quantity == sell_plan.quantity == 1,
        "both_filled": buy["execution_state"] == sell["execution_state"] == "filled",
        "closed_protection": buy["protection_state"] == "closed",
        "separate_sell_approval_after_buy": sell_plan.created_at > buy_plan.created_at,
    }
    with store.connection() as db:
        events = [
            {**dict(row), "payload": json.loads(row["payload"])}
            for row in db.execute("SELECT * FROM outbox ORDER BY sequence")
        ]
        active = db.execute(
            "SELECT COUNT(*) FROM reservations WHERE execution_id IN (?,?) AND active=1",
            (buy_id, sell_id),
        ).fetchone()[0]
    protected = [
        e["sequence"]
        for e in events
        if e["payload"].get("execution_id") == buy_id
        and e["payload"].get("protection_state") == "confirmed"
    ]
    cancelled = [
        e["sequence"]
        for e in events
        if e["event"] == "broker_reconciliation"
        and e["payload"].get("execution_id") == buy_id
        and e["payload"].get("protection_state") == "cancelled"
    ]
    submitted = [
        e["sequence"]
        for e in events
        if e["event"] == "execution_reserved"
        and e["payload"].get("execution_id") == sell_id
    ]
    closed = [
        e
        for e in events
        if e["event"] == "cancelled_protection_closed"
        and e["payload"].get("closing_execution") == sell_id
    ]
    checks["confirmed_stop_then_human_reconciliation_before_sell"] = bool(
        protected
        and cancelled
        and submitted
        and min(protected) < max(cancelled) < min(submitted)
    )
    checks["verified_flat_after_sell"] = bool(closed)
    checks["reservations_released"] = active == 0
    return {
        "schema_version": 1,
        "execution_evidence_consistent": all(checks.values()),
        "checks": checks,
        "buy_execution": buy_id,
        "sell_execution": sell_id,
        "account": buy_plan.account,
        "host_and_release_verified": False,
        "switches_relocked_verified": False,
        "operator_stop_cancellation_attestation_required": True,
    }
