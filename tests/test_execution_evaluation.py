from dataclasses import asdict
import json

from trading_agent.domain import canonical
from trading_agent.replay import replay, preregistration
from test_execution_application import service, approve, RULES


def test_replay_uses_recorded_time_and_reports_costs_separately(service):
    application, broker = service
    aid = approve(application)
    plan = application.store.approval(aid)["plan"]
    record = {"schema_version": 1, "release": "a" * 40, "decision_at": plan["created_at"],
              "plan": plan, "portfolio": json.loads(canonical(asdict(broker.snapshot_value))),
              "rules": RULES, "reservations": [], "transaction_costs": "1.25",
              "realized_fills": [{"quantity": 5, "price": "100.10"}], "operational_failures": ["late_ack"]}
    first = replay(record)
    assert replay(record) == first
    assert first["decision"]["allowed"] is True
    assert first["transaction_costs"] == "1.25"
    assert first["slippage"]["per_share"] == "0.10"
    assert first["operational_failures"] == ["late_ack"]


def test_replay_missing_inputs_are_not_strategy_rejections():
    result = replay({"schema_version": 1})
    assert result["decision"] is None
    assert "portfolio" in result["missing_inputs"]


def test_preregistration_does_not_invent_operator_expectations():
    draft = preregistration("a" * 40, "b" * 64)
    assert draft["expected_returns"] is None
    assert draft["paper_acceptance_evidence"] is None
    assert draft["status"] == "draft_requires_operator_expectations"
