"""Validate fill and commission evidence separately from strategy decisions."""

from decimal import Decimal
from typing import Any

from trading_agent.domain import ApprovedOrderPlan, canonical, money, timestamp


def evaluate_evidence(
    record: dict[str, Any], plan: ApprovedOrderPlan
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_issues": [],
        "costs_by_currency": {},
        "cost_coverage_complete": False,
        "slippage": None,
        "fill_count": 0,
        "commission_provenance": record.get("commission_provenance"),
        "commission_statement_verification": "requires_operator_verification",
    }
    if "realized_fills" not in record:
        result["evidence_issues"] = ["realized_fills_missing"]
        return result
    unique: dict[str, dict[str, Any]] = {}
    try:
        observed_at = timestamp(record["execution_evidence_observed_at"])
        if observed_at < plan.created_at:
            raise ValueError("INVALID_EXECUTION_OBSERVATION_TIME")
        for raw in record["realized_fills"]:
            key = raw["broker_execution_id"]
            if not isinstance(key, str) or not key:
                raise ValueError("INVALID_FILL_IDENTITY")
            fill = {
                "account": raw["account"],
                "contract_id": raw["contract_id"],
                "side": raw["side"],
                "quantity": raw["quantity"],
                "price": money(raw["price"]),
                "executed_at": timestamp(raw["executed_at"]).isoformat(),
            }
            if (
                fill["account"] != plan.account
                or fill["contract_id"] != plan.contract_id
                or fill["side"] != plan.side
                or type(fill["quantity"]) is not int
                or fill["quantity"] <= 0
                or fill["price"] <= 0
                or not plan.created_at <= timestamp(fill["executed_at"]) <= observed_at
            ):
                raise ValueError("FILL_SCOPE_OR_VALUE_MISMATCH")
            if key in unique and canonical(unique[key]) != canonical(fill):
                raise ValueError("CONFLICTING_FILL_EVIDENCE")
            unique[key] = fill
        quantity = sum(f["quantity"] for f in unique.values())
        if quantity > plan.quantity:
            raise ValueError("EXCESSIVE_FILL_QUANTITY")
    except (KeyError, TypeError, ValueError) as exc:
        result["evidence_issues"] = [
            str(exc) if isinstance(exc, ValueError) else "incomplete_fill_evidence"
        ]
        return result
    result["fill_count"] = len(unique)
    if quantity:
        average = (
            sum((f["quantity"] * f["price"] for f in unique.values()), Decimal(0))
            / quantity
        )
        result["slippage"] = {
            "currency": plan.currency,
            "per_share": str(
                (1 if plan.side == "BUY" else -1) * (average - plan.entry_price)
            ),
            "quantity": str(quantity),
        }
    else:
        result["evidence_issues"].append("no_realized_fills")
    commissions: dict[str, tuple[str, Decimal]] = {}
    try:
        for raw in record.get("commissions", []):
            key, currency = raw["broker_execution_id"], raw["currency"]
            amount = money(raw["amount"])
            if (
                key not in unique
                or not isinstance(currency, str)
                or len(currency) != 3
                or not currency.isalpha()
                or currency != currency.upper()
            ):
                raise ValueError("COMMISSION_IDENTITY_OR_CURRENCY_MISMATCH")
            value = (currency, amount)
            if key in commissions and commissions[key] != value:
                raise ValueError("CONFLICTING_COMMISSION_EVIDENCE")
            commissions[key] = value
        totals: dict[str, Decimal] = {}
        for currency, amount in commissions.values():
            totals[currency] = totals.get(currency, Decimal(0)) + amount
        result["costs_by_currency"] = {
            currency: str(amount) for currency, amount in sorted(totals.items())
        }
        result["cost_coverage_complete"] = (
            bool(unique)
            and commissions.keys() == unique.keys()
            and bool(record.get("commission_provenance"))
        )
        if not result["cost_coverage_complete"]:
            result["evidence_issues"].append("commission_evidence_incomplete")
    except (KeyError, TypeError, ValueError):
        result["evidence_issues"].append("invalid_or_conflicting_commissions")
    return result
