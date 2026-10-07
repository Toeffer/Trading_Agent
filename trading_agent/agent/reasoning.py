"""Bounded strategy tool use, optional recorded model opinions, explicit decisions."""

from typing import Any, Protocol

from strategy_v1_1_core import (
    compute_cross_sectional_rs,
    compute_effective_budget,
    compute_gross_scalar,
    compute_realized_vol,
    compute_regime_state,
    compute_sma,
)
from trading_agent.agent.contracts import Mandate, Observation, numeric_bars
from trading_agent.domain import money, timestamp


class Reasoner(Protocol):
    version: str

    def decide(
        self, observation: Observation, mandate: Mandate, portfolio: dict[str, Any]
    ) -> dict[str, Any]: ...


class StrategyReasoner:
    """New baseline using existing v1.1 tools; not an activation of advisory v1.1."""

    version = "agent-trend-v1"

    def decide(
        self, observation: Observation, mandate: Mandate, portfolio: dict[str, Any]
    ) -> dict[str, Any]:
        event = observation.raw
        quotes = event["quotes"]
        reference = numeric_bars(event["reference_bars"])
        histories = {s: numeric_bars(q["bars"]) for s, q in quotes.items()}
        regime = compute_regime_state(reference)
        ranks = compute_cross_sectional_rs(histories, total_allowlist=len(histories))
        vol = compute_realized_vol(reference)
        scalar = compute_gross_scalar(vol["sigma_ref"])
        budget = compute_effective_budget(
            float(mandate.policy.max_exposure_pct * 100),
            scalar["gross_scalar"],
            regime["regime"],
        )
        trace = {
            "regime": regime,
            "relative_strength": ranks,
            "volatility": vol,
            "gross_scalar": scalar,
            "budget": budget,
        }
        decisions: list[dict[str, Any]] = []
        for symbol in sorted(quotes):
            position = portfolio["positions"].get(symbol)
            opinion = event.get("opinions", {}).get(symbol)
            sma = compute_sma(histories[symbol], 20)
            trend = sma is not None and money(
                quotes[symbol]["bars"][-1]["close"]
            ) > money(sma)
            action, reason, protective = "HOLD", "NO_SETUP", False
            if position:
                age = (
                    observation.at - timestamp(position["opened_at"])
                ).total_seconds() / 86400
                if money(quotes[symbol]["bid"]) <= money(position["stop_price"]):
                    action, reason, protective = "EXIT", "PROTECTIVE_STOP", True
                elif opinion and opinion["action"] == "EXIT":
                    action, reason = "EXIT", "THESIS_INVALIDATED"
                elif age >= mandate.raw["strategy"]["max_holding_days"]:
                    action, reason = "EXIT", "HOLDING_PERIOD_EXPIRED"
                elif regime["valid"] and regime["regime"] == "RISK_OFF":
                    action, reason = "EXIT", "REGIME_RISK_OFF"
                elif sma is not None and not trend:
                    action, reason = "EXIT", "TREND_INVALIDATED"
                else:
                    reason = "POSITION_THESIS_INTACT"
            elif opinion and opinion["action"] != "ENTER":
                reason = "RECORDED_OPINION_ABSTAIN"
            elif not regime["valid"] or ranks["no_trade"] or not vol["valid"]:
                reason = "INSUFFICIENT_STRATEGY_DATA"
            elif regime["regime"] == "RISK_OFF":
                reason = "REGIME_RISK_OFF"
            elif trend and symbol in ranks["top_half_symbols"]:
                action, reason = "ENTER", "TREND_AND_RELATIVE_STRENGTH"
            thesis = (
                opinion["thesis"]
                if opinion
                else position["thesis"]
                if position
                else "Positive trend and relative strength within the reference-market regime."
            )
            invalidation = (
                opinion["invalidation"]
                if opinion
                else position["invalidation"]
                if position
                else "Protective stop, trend/regime reversal or maximum holding period."
            )
            decisions.append(
                {
                    "symbol": symbol,
                    "action": action,
                    "reason": reason,
                    "protective": protective,
                    "thesis": thesis,
                    "invalidation": invalidation,
                    "opinion": opinion,
                    "sma20": sma,
                }
            )
        # Exits free simulated capacity before new entries. Rank order decides
        # allocation when several candidates compete for a limited budget.
        rank_order = {item["symbol"]: item["rank"] for item in ranks["ranks"]}
        decisions.sort(
            key=lambda d: (
                d["action"] != "EXIT",
                rank_order.get(d["symbol"], 999),
                d["symbol"],
            )
        )
        return {
            "version": self.version,
            "observed_at": observation.at.isoformat(),
            "tools": trace,
            "budget_fraction": str(money(budget["effective_budget_pct"]) / 100),
            "decisions": decisions,
        }
