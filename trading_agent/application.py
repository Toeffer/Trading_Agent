"""Explicit application workflows; dependencies are injected, never global I/O."""

from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal
import sqlite3
import threading
from typing import Any, Protocol

from trading_agent.domain import (
    ApprovedOrderPlan,
    BrokerResult,
    ExecutionState,
    PortfolioSnapshot,
    content_hash,
    money,
    utcnow,
)
from trading_agent.persistence import ExecutionStore, StateConflict
from trading_agent.risk import RiskPolicy, RiskRejected, evaluate, validate_snapshot


class Broker(Protocol):
    def snapshot(self, symbol: str) -> PortfolioSnapshot: ...
    def submit(self, plan: ApprovedOrderPlan, reference: str) -> BrokerResult: ...
    def reconcile(self, plan: ApprovedOrderPlan, reference: str) -> BrokerResult: ...


class ExecutionService:
    def __init__(
        self,
        store: ExecutionStore,
        broker: Broker,
        *,
        rules_provider: Callable[[], dict[str, Any]],
        account: str,
        orders_enabled: Callable[[], bool],
        stop_provider: Callable[[str, Decimal], Decimal] | None = None,
        release: str = "unverified",
        account_risk_provider: Callable[
            [PortfolioSnapshot, RiskPolicy], PortfolioSnapshot
        ]
        | None = None,
    ):
        self.store = store
        self.broker = broker
        self.rules_provider = rules_provider
        self.account = account
        self.orders_enabled = orders_enabled
        self.stop_provider = stop_provider
        self.release = release
        self.account_risk_provider = account_risk_provider
        self._account_lock = threading.RLock()

    def _snapshot(self, symbol: str, policy: RiskPolicy) -> PortfolioSnapshot:
        from trading_agent.accounting import reconcile_snapshot

        revision = self.store.evidence_revision(self.account)
        snapshot = self.broker.snapshot(symbol)
        validate_snapshot(snapshot, expected_account=self.account)
        if self.account_risk_provider is not None:
            snapshot = self.account_risk_provider(snapshot, policy)
        return reconcile_snapshot(self.store, snapshot, revision)

    def preflight(
        self, request: dict[str, Any], *, proposal: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            allowed = {
                "symbol",
                "action",
                "totalQuantity",
                "orderType",
                "limitPrice",
                "stopPrice",
                "stopPercent",
                "mode",
            }
            extra = request.keys() - allowed
            if extra:
                raise RiskRejected("UNKNOWN_REQUEST_FIELD:" + sorted(extra)[0])
            symbol = str(request.get("symbol", "")).upper().strip()
            side = str(request.get("action", "BUY")).upper()
            quantity = request.get("totalQuantity")
            if (
                type(quantity) is not int
                or quantity <= 0
                or side not in ("BUY", "SELL")
            ):
                raise RiskRejected("INVALID_ORDER_QUANTITY_OR_SIDE")
            if request.get("mode", "paper") != "paper":
                raise RiskRejected("PAPER_ONLY")
            if (
                str(proposal.get("symbol", "")).strip().upper() != symbol
                or str(proposal.get("side", "")).strip().upper() != side
                or type(proposal.get("quantity")) is not int
                or proposal["quantity"] != quantity
            ):
                raise RiskRejected("PROPOSAL_MISMATCH")
            order_type = str(request.get("orderType", "MKT")).upper()
            if order_type not in ("MKT", "LMT"):
                raise RiskRejected("UNSUPPORTED_ORDER_TYPE")
            if order_type == "LMT" and money(request.get("limitPrice")) <= 0:
                raise RiskRejected("LIMIT_PRICE_REQUIRED")
            if "stopPrice" in request and "stopPercent" in request:
                raise RiskRejected("AMBIGUOUS_STOP_CONSTRAINT")
            if (
                "orderType" in proposal
                and str(proposal["orderType"]).upper() != order_type
            ):
                raise RiskRejected("PROPOSAL_MISMATCH")
            for key, aliases in {
                "limitPrice": ("limitPrice", "limit_price"),
                "stopPrice": ("stopPrice", "stop_price"),
                "stopPercent": ("stopPercent",),
            }.items():
                for name in aliases:
                    if name in proposal and (
                        key not in request
                        or money(proposal[name]) != money(request[key])
                    ):
                        raise RiskRejected("PROPOSAL_PRICE_MISMATCH")
            if "account" in proposal and proposal["account"] != self.account:
                raise RiskRejected("PROPOSAL_ACCOUNT_MISMATCH")
            rules = self.rules_provider()
            policy = RiskPolicy.from_rules(rules)
            snapshot = self._snapshot(symbol, policy)
            entry = snapshot.ask if side == "BUY" else snapshot.bid
            if (
                "currency" in proposal
                and proposal["currency"] != snapshot.quote_currency
            ):
                raise RiskRejected("PROPOSAL_CURRENCY_MISMATCH")
            if (
                "contract_id" in proposal
                and proposal["contract_id"] != snapshot.contract_id
            ):
                raise RiskRejected("PROPOSAL_CONTRACT_MISMATCH")
            for key in ("entry_price", "entry_reference_price"):
                if key in proposal and (
                    money(proposal[key]) <= 0
                    or abs(entry / money(proposal[key]) - 1) > Decimal("0.01")
                ):
                    raise RiskRejected("PROPOSAL_ENTRY_PRICE_MISMATCH")
            if (
                side == "BUY"
                and "max_entry_price" in proposal
                and entry > money(proposal["max_entry_price"])
            ):
                raise RiskRejected("PROPOSAL_ENTRY_PRICE_MISMATCH")
            if (
                side == "SELL"
                and "min_exit_price" in proposal
                and entry < money(proposal["min_exit_price"])
            ):
                raise RiskRejected("PROPOSAL_EXIT_PRICE_MISMATCH")
            stop = None
            if side == "BUY":
                if "stopPercent" in request:
                    percent = money(request["stopPercent"])
                    if not -100 < percent < 0:
                        raise RiskRejected("INVALID_STOP_PERCENT")
                    stop = entry * (1 + percent / 100)
                elif "stopPrice" in request:
                    stop = money(request["stopPrice"])
                elif self.stop_provider is not None:
                    stop = self.stop_provider(symbol, entry)
                else:
                    raise RiskRejected("STOP_DATA_UNAVAILABLE")
            now = utcnow()
            plan = ApprovedOrderPlan(
                self.account,
                symbol,
                snapshot.contract_id,
                snapshot.quote_currency,
                side,
                quantity,
                "MKT",
                entry,
                stop,
                content_hash(proposal),
                policy.policy_hash,
                now,
                now + timedelta(seconds=300),
                snapshot.market_observed_at,
                proposal_id=proposal.get("proposal_id"),
                stop_basis="atr"
                if side == "BUY" and not {"stopPrice", "stopPercent"} & request.keys()
                else "explicit",
                max_entry_price=money(proposal["max_entry_price"])
                if "max_entry_price" in proposal
                else None,
                min_exit_price=money(proposal["min_exit_price"])
                if "min_exit_price" in proposal
                else None,
            )
            reservations = self.store.reservations(self.account)
            evaluate(plan, snapshot, policy, reservations, now=now)
            result: dict[str, Any] = {
                "passed": True,
                "symbol": symbol,
                "action": side,
                "totalQuantity": quantity,
                "orderType": order_type,
                "entry_price": str(entry),
                "stop_price": str(stop) if stop else None,
                "validation_only": order_type == "LMT",
                "close_only": side == "SELL",
            }
            if order_type == "LMT":
                result["limitPrice"] = str(money(request["limitPrice"]))
                return result
            evidence = {
                "schema_version": 2,
                "release": self.release,
                "decision_at": now,
                "plan": plan.to_dict(),
                "portfolio": asdict(snapshot),
                "rules": rules,
                "reservations": reservations,
            }
            approval = self.store.create_pending(plan, evidence=evidence)
            result.update(
                approval_id=approval["approval_id"],
                approval_expires_at_utc=approval["expires_at"],
            )
            return result
        except (
            ValueError,
            KeyError,
            TypeError,
            OSError,
            RuntimeError,
            sqlite3.Error,
        ) as exc:
            code = (
                str(exc)
                if isinstance(exc, (RiskRejected, StateConflict))
                else "PREFLIGHT_UNAVAILABLE"
            )
            return {"passed": False, "code": code, "error": code}

    def rule(self, aid: str, decision: str, *, authorized: bool) -> dict[str, Any]:
        if decision not in ("approve", "deny"):
            raise ValueError("INVALID_DECISION")
        return self.store.rule(
            aid,
            "approved" if decision == "approve" else "denied",
            authorized=authorized,
        )

    def reconcile_account(self, symbol: str, *, authorized: bool) -> dict[str, Any]:
        from trading_agent.accounting import reconcile_snapshot

        if authorized is not True:
            raise PermissionError("H1_TOKEN_REQUIRED")
        with self._account_lock:
            policy = RiskPolicy.from_rules(self.rules_provider())
            if symbol not in policy.allowed_symbols:
                raise StateConflict("SYMBOL_NOT_ALLOWED")
            revision = self.store.evidence_revision(self.account)
            snapshot = self.broker.snapshot(symbol)
            validate_snapshot(snapshot, expected_account=self.account)
            if self.account_risk_provider:
                snapshot = self.account_risk_provider(snapshot, policy)
            snapshot = reconcile_snapshot(
                self.store, snapshot, revision, authorized_reconciliation=True
            )
            return {
                "account": self.account,
                "evidence_revision": snapshot.evidence_revision,
                "daily_trade_count": snapshot.daily_trade_count,
                "order_switches_changed": False,
                "resumption": "requires_operator_review",
            }

    def submit(self, aid: str, *, authorized: bool) -> dict[str, Any]:
        if authorized is not True:
            raise PermissionError("H1_TOKEN_REQUIRED")
        with self._account_lock:
            previous = self.store.execution_for_approval(aid)
            if previous is not None:
                return previous
            try:
                rules = self.rules_provider()
                if (
                    self.orders_enabled() is not True
                    or rules.get("enforced") is not True
                ):
                    raise RiskRejected("ORDERS_BLOCKED")
                approval = self.store.approval(aid)
                plan = ApprovedOrderPlan.from_dict(approval["plan"])
                policy = RiskPolicy.from_rules(rules)
                snapshot = self._snapshot(plan.symbol, policy)
                if plan.side == "BUY" and plan.stop_basis == "atr":
                    if self.stop_provider is None or plan.stop_price is None:
                        raise RiskRejected("STOP_DATA_UNAVAILABLE")
                    fresh_stop = self.stop_provider(plan.symbol, snapshot.ask)
                    if abs(fresh_stop / plan.stop_price - 1) > Decimal("0.02"):
                        raise RiskRejected("STOP_DRIFT")

                evidence = {
                    "schema_version": 2,
                    "release": self.release,
                    "plan": plan.to_dict(),
                    "portfolio": asdict(snapshot),
                    "rules": rules,
                }

                def validate(
                    approved: ApprovedOrderPlan, reservations: list[dict[str, Any]]
                ) -> None:
                    current_rules = self.rules_provider()
                    if (
                        self.orders_enabled() is not True
                        or current_rules.get("enforced") is not True
                    ):
                        raise RiskRejected("ORDERS_BLOCKED")
                    if (
                        RiskPolicy.from_rules(current_rules).policy_hash
                        != policy.policy_hash
                    ):
                        raise RiskRejected("POLICY_CHANGED")
                    decision_at = utcnow()
                    evaluate(approved, snapshot, policy, reservations, now=decision_at)
                    evidence.update(decision_at=decision_at, reservations=reservations)

                execution, created = self.store.reserve(
                    aid, authorized=authorized, validate=validate, evidence=evidence
                )
                if not created:
                    return execution
            except (
                ValueError,
                KeyError,
                TypeError,
                OSError,
                RuntimeError,
                sqlite3.Error,
            ) as exc:
                code = (
                    str(exc)
                    if isinstance(exc, (RiskRejected, StateConflict))
                    else "REVALIDATION_UNAVAILABLE"
                )
                return {
                    "submitted": False,
                    "code": code,
                    "error": code,
                    "retry_allowed": False,
                }
            eid = execution["execution_id"]
            try:
                result = self.broker.submit(plan, eid)
                if not isinstance(result, BrokerResult):
                    raise TypeError("BROKER_RESULT_CONTRACT")
                if plan.side == "BUY" and result.protection_state not in (
                    "confirmed",
                    "closed",
                ):
                    result = replace(
                        result, state=ExecutionState.UNKNOWN, protection_state="unknown"
                    )
            except Exception:
                result = BrokerResult(
                    ExecutionState.UNKNOWN,
                    protection_state="unknown"
                    if plan.side == "BUY"
                    else "not_applicable",
                    error_code="BROKER_OUTCOME_UNKNOWN",
                )
            try:
                self.store.record_result(eid, result)
            except Exception:
                # The committed intent remains reserved even if recording the
                # reply fails. Never report this as a retryable provider reject.
                return {
                    **execution,
                    "execution_state": "unknown",
                    "submitted": False,
                    "code": "RESULT_PERSISTENCE_UNCERTAIN",
                    "retry_allowed": False,
                }
            return self.store.execution(eid)

    def reconcile(self, eid: str, *, authorized: bool) -> dict[str, Any]:
        if authorized is not True:
            raise PermissionError("H1_TOKEN_REQUIRED")
        with self._account_lock:
            execution = self.store.execution(eid)
            plan = ApprovedOrderPlan.from_dict(
                self.store.approval(execution["approval_id"])["plan"]
            )
            result = self.broker.reconcile(plan, eid)
            if not isinstance(result, BrokerResult):
                raise StateConflict("BROKER_EVIDENCE_UNAVAILABLE")
            if plan.side == "BUY" and result.protection_state not in (
                "confirmed",
                "closed",
                "cancelled",
            ):
                result = replace(
                    result, state=ExecutionState.UNKNOWN, protection_state="unknown"
                )
            self.store.record_result(eid, result, reconciled=True)
            if (
                plan.side == "SELL"
                and self.store.execution(eid)["execution_state"] == "filled"
            ):
                from trading_agent.risk import validate_snapshot

                snapshot = self.broker.snapshot(plan.symbol)
                validate_snapshot(snapshot, plan.account)
                if not any(
                    p.symbol == plan.symbol and p.quantity for p in snapshot.positions
                ) and not any(
                    o.symbol == plan.symbol and o.remaining
                    for o in snapshot.open_orders
                ):
                    self.store.close_cancelled_protection(
                        plan.account, plan.symbol, eid
                    )
            return self.store.execution(eid)
