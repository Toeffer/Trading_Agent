"""Deterministic evaluation of timestamped, versioned decision snapshots."""

from decimal import Decimal
from pathlib import Path
import json
from typing import Any

from trading_agent.domain import (
    ApprovedOrderPlan,
    AccountFill,
    OpenOrder,
    PortfolioSnapshot,
    Position,
    content_hash,
    money,
    timestamp,
)
from trading_agent.risk import RiskPolicy, RiskRejected, evaluate


def load_snapshot(raw: dict[str, Any]) -> PortfolioSnapshot:
    value = dict(raw)
    for name in ("net_liquidation", "base_to_quote", "bid", "ask"):
        value[name] = money(value[name])
    for name in ("observed_at", "market_observed_at"):
        value[name] = timestamp(value[name])
    value["positions"] = tuple(
        Position(**{**p, "market_value_base": money(p["market_value_base"])})
        for p in value["positions"]
    )
    value["open_orders"] = tuple(
        OpenOrder(**{**o, "value_base": money(o["value_base"])})
        for o in value["open_orders"]
    )
    value["verified_fills"] = tuple(
        AccountFill(
            **{
                **f,
                "price": money(f["price"]),
                "executed_at": timestamp(f["executed_at"]),
            }
        )
        for f in value.get("verified_fills", ())
    )
    return PortfolioSnapshot(**value)


def replay(record: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": 1,
        "input_hash": content_hash(record),
        "release": record.get("release"),
        "decision": None,
        "missing_inputs": [],
        "operational_failures": record.get("operational_failures", []),
        "transaction_costs": None,
        "slippage": None,
    }
    required = {
        "schema_version",
        "release",
        "decision_at",
        "plan",
        "portfolio",
        "rules",
        "reservations",
    }
    missing = sorted(required - record.keys())
    if missing:
        return {**result, "missing_inputs": missing}
    if record["schema_version"] not in (1, 2):
        raise ValueError("UNSUPPORTED_REPLAY_VERSION")
    if record["schema_version"] == 2:
        absent = sorted(
            {"evidence_revision", "verified_fills", "accounting_coverage"}
            - record["portfolio"].keys()
        )
        if absent:
            return {**result, "missing_inputs": ["portfolio." + k for k in absent]}
    try:
        plan = ApprovedOrderPlan.from_dict(record["plan"])
        portfolio = load_snapshot(record["portfolio"])
        policy = RiskPolicy.from_rules(record["rules"])
        at = timestamp(record["decision_at"])
        if at < plan.created_at:
            raise ValueError("REPLAY_PRECEDES_PROPOSAL")
        evaluate(plan, portfolio, policy, record["reservations"], now=at)
        result["decision"] = {"allowed": True, "code": "PASSED"}
    except RiskRejected as exc:
        result["decision"] = {"allowed": False, "code": str(exc)}
    except (KeyError, TypeError, ValueError):
        result["missing_inputs"] = ["invalid_or_incomplete_decision_snapshot"]
        return result
    if "transaction_costs" in record:
        result["transaction_costs"] = str(money(record["transaction_costs"]))
    if "realized_fills" in record:
        fills = record["realized_fills"]
        quantity = sum(money(f["quantity"]) for f in fills)
        if quantity > 0:
            average = (
                sum(
                    (money(f["quantity"]) * money(f["price"]) for f in fills),
                    Decimal(0),
                )
                / quantity
            )
            sign = 1 if plan.side == "BUY" else -1
            result["slippage"] = {
                "currency": plan.currency,
                "per_share": str(sign * (average - plan.entry_price)),
                "quantity": str(quantity),
            }
    return result


def replay_file(source: Path) -> list[dict[str, Any]]:
    return [
        replay(json.loads(line))
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def preregistration(release: str, configuration_hash: str) -> dict[str, Any]:
    if len(release) != 40 or any(c not in "0123456789abcdef" for c in release):
        raise ValueError("Exact release commit required")
    if len(configuration_hash) != 64 or any(
        c not in "0123456789abcdef" for c in configuration_hash
    ):
        raise ValueError("Configuration SHA-256 required")
    return {
        "schema_version": 1,
        "release": release,
        "configuration_hash": configuration_hash,
        "status": "draft_requires_operator_expectations",
        "strategy_parameters_changed": False,
        "expected_returns": None,
        "expected_trade_frequency": None,
        "failure_criteria": None,
        "transaction_cost_assumptions": None,
        "study_start": None,
        "trading_days": 60,
        "paper_acceptance_evidence": None,
        "operator_signed_at": None,
    }
