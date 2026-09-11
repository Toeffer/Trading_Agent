"""Account evidence reconciliation, independent of HTTP and broker I/O."""

from dataclasses import asdict, replace
import json
import sqlite3
from datetime import date
from typing import TYPE_CHECKING, Any

from trading_agent.domain import PortfolioSnapshot, canonical, money, timestamp, utcnow

if TYPE_CHECKING:
    from trading_agent.persistence import ExecutionStore


def revision(db: sqlite3.Connection, account: str) -> int:
    row = db.execute(
        "SELECT revision FROM account_revision WHERE account=?", (account,)
    ).fetchone()
    return int(row[0]) if row else 0


def fills(db: sqlite3.Connection, account: str) -> dict[str, dict[str, Any]]:
    """Project verified parent and child evidence without losing identity."""
    result: dict[str, dict[str, Any]] = {}
    for row in db.execute(
        "SELECT b.*,a.plan FROM broker_events b JOIN executions e USING(execution_id) JOIN approvals a USING(approval_id) WHERE b.account=?",
        (account,),
    ):
        plan, event = json.loads(row["plan"]), json.loads(row["payload"])
        result[row["broker_execution_id"]] = {
            "symbol": plan["symbol"],
            "side": plan["side"] if row["role"] == "parent" else "SELL",
            "quantity": event["quantity"],
            "price": event["price"],
            "executed_at": event["observed_at"],
            "role": row["role"],
            "order_key": row["execution_id"],
        }
    for row in db.execute(
        "SELECT * FROM account_fill_history WHERE account=?", (account,)
    ):
        event = json.loads(row["payload"])
        if row["broker_execution_id"] not in result:
            result[row["broker_execution_id"]] = event
    return result


def daily_count(db: sqlite3.Connection, account: str, day: date) -> int:
    first: dict[str, str] = {}
    for event in fills(db, account).values():
        if event["role"] == "parent":
            key = event["order_key"]
            at = timestamp(event["executed_at"]).isoformat()
            first[key] = min(first.get(key, at), at)
    return sum(at[:10] == day.isoformat() for at in first.values())


def reconcile_snapshot(
    store: "ExecutionStore",
    snapshot: PortfolioSnapshot,
    expected: int,
    *,
    authorized_reconciliation: bool = False,
) -> PortfolioSnapshot:
    from trading_agent.persistence import StateConflict

    account = snapshot.account
    if not snapshot.accounting_coverage:
        raise StateConflict("ACCOUNTING_HISTORY_INCOMPLETE")
    with store.transaction() as db:
        if revision(db, account) != expected:
            raise StateConflict("ACCOUNT_EVIDENCE_CHANGED")
        known = fills(db, account)
        for event in snapshot.verified_fills:
            if event.account != account:
                raise StateConflict("ACCOUNT_FILL_IDENTITY_MISMATCH")
            if timestamp(event.executed_at) > snapshot.observed_at:
                raise StateConflict("FUTURE_FILL_EVIDENCE")
            payload = asdict(event)
            payload["executed_at"] = timestamp(event.executed_at).isoformat()
            old = known.get(event.broker_execution_id)
            if old:
                identity = (
                    (event.execution_ref or "").removesuffix(":stop")
                    if old["order_key"].startswith("exec_")
                    else event.order_key
                )
                if old["order_key"] != identity:
                    raise StateConflict("CONFLICTING_FILL_IDENTITY")
                if any(
                    canonical(old[k]) != canonical(payload[k])
                    for k in ("symbol", "side", "quantity", "executed_at", "role")
                ) or money(old["price"]) != money(payload["price"]):
                    raise StateConflict("CONFLICTING_FILL_EVIDENCE")
                continue
            # Application fills must be durably captured by their execution;
            # a snapshot is never allowed to fabricate that execution result.
            if event.execution_ref and event.execution_ref.startswith("exec_"):
                raise StateConflict("EXECUTION_FILL_RECONCILIATION_REQUIRED")
            order_known = any(v["order_key"] == event.order_key for v in known.values())
            if not event.history_complete and not order_known:
                raise StateConflict("ACCOUNTING_HISTORY_INCOMPLETE")
            db.execute(
                "INSERT INTO account_fill_history VALUES(?,?,?,?)",
                (
                    account,
                    event.broker_execution_id,
                    event.order_key,
                    canonical(payload),
                ),
            )
            store._event(db, "account_fill", payload)
            known[event.broker_execution_id] = payload

        references: set[str] = set()
        for order in snapshot.open_orders:
            reference = order.execution_ref or ""
            if not reference.startswith("exec_"):
                continue
            if reference in references:
                raise StateConflict("OPEN_ORDER_EVIDENCE_MISMATCH")
            references.add(reference)
            eid = reference.removesuffix(":stop")
            row = db.execute(
                "SELECT e.filled_quantity,a.plan FROM executions e JOIN approvals a USING(approval_id) WHERE e.account=? AND e.execution_id=?",
                (account, eid),
            ).fetchone()
            if row is None:
                raise StateConflict("UNKNOWN_EXECUTION_REFERENCE")
            plan = json.loads(row["plan"])
            child = reference.endswith(":stop")
            filled = sum(
                v["quantity"]
                for v in known.values()
                if v["order_key"] == eid
                and v["role"] == ("stop" if child else "parent")
            )
            if (
                order.symbol != plan["symbol"]
                or order.side != ("SELL" if child else plan["side"])
                or order.remaining != plan["quantity"] - filled
                or order.contract_id != plan["contract_id"]
            ):
                raise StateConflict("OPEN_ORDER_EVIDENCE_MISMATCH")

        positions = {p.symbol: p.quantity for p in snapshot.positions if p.quantity}
        if len(positions) != sum(bool(p.quantity) for p in snapshot.positions):
            raise StateConflict("DUPLICATE_POSITION_IDENTITY")
        anchor = db.execute(
            "SELECT payload FROM holdings_anchor WHERE account=?", (account,)
        ).fetchone()
        if anchor:
            previous = json.loads(anchor[0])
            if timestamp(snapshot.observed_at) < timestamp(previous["observed_at"]):
                raise StateConflict("STALE_HOLDINGS_EVIDENCE")
            expected_positions = dict(previous["positions"])
            for key, event_payload in known.items():
                if key not in previous["fill_ids"]:
                    symbol = event_payload["symbol"]
                    expected_positions[symbol] = expected_positions.get(
                        symbol, 0
                    ) + event_payload["quantity"] * (
                        1 if event_payload["side"] == "BUY" else -1
                    )
            if {k: v for k, v in expected_positions.items() if v} != positions:
                raise StateConflict("HOLDINGS_EVIDENCE_MISMATCH")
        elif db.execute(
            "SELECT 1 FROM executions WHERE account=? LIMIT 1", (account,)
        ).fetchone():
            # Upgraded databases require human broker reconciliation before an
            # initial anchor can absorb historical execution evidence.
            unresolved = db.execute(
                "SELECT 1 FROM executions WHERE account=? AND execution_state NOT IN ('filled','rejected','cancelled') LIMIT 1",
                (account,),
            ).fetchone()
            if unresolved:
                raise StateConflict("ACCOUNTING_HISTORY_INCOMPLETE")
            unreconciled = db.execute(
                "SELECT 1 FROM executions e WHERE account=? AND NOT EXISTS (SELECT 1 FROM outbox o WHERE o.event='broker_reconciliation' AND json_extract(o.payload,'$.execution_id')=e.execution_id) LIMIT 1",
                (account,),
            ).fetchone()
            if unreconciled:
                raise StateConflict("ACCOUNTING_HISTORY_INCOMPLETE")

        # An imported aggregate cannot be added to identity-based fills without
        # proving which identities it contains. Keep intake locked for review.
        risk = db.execute(
            "SELECT payload FROM account_risk WHERE account=?", (account,)
        ).fetchone()
        first: dict[str, str] = {}
        for event_payload in known.values():
            if event_payload["role"] == "parent":
                key = event_payload["order_key"]
                at = timestamp(event_payload["executed_at"]).isoformat()
                first[key] = min(first.get(key, at), at)
        count = sum(at[:10] == utcnow().date().isoformat() for at in first.values())
        if risk:
            state = json.loads(risk[0])
            if (
                state["trade_date"] == utcnow().date().isoformat()
                and state["daily_trade_count"]
            ):
                own = sum(
                    at[:10] == utcnow().date().isoformat()
                    for key, at in first.items()
                    if key.startswith("exec_")
                )
                if (
                    not authorized_reconciliation
                    or count - own != state["daily_trade_count"]
                    or any(
                        not f.history_complete
                        for f in snapshot.verified_fills
                        if not (f.execution_ref or "").startswith("exec_")
                    )
                ):
                    raise StateConflict("IMPORTED_COUNT_RECONCILIATION_REQUIRED")
                store._event(
                    db,
                    "imported_count_reconciled",
                    {
                        "account": account,
                        "historical_count": state["daily_trade_count"],
                        "order_identities": sorted(first),
                    },
                )
                state["daily_trade_count"] = 0
                db.execute(
                    "UPDATE account_risk SET payload=? WHERE account=?",
                    (canonical(state), account),
                )
        db.execute(
            "INSERT INTO holdings_anchor VALUES(?,?) ON CONFLICT(account) DO UPDATE SET payload=excluded.payload",
            (
                account,
                canonical(
                    {
                        "positions": positions,
                        "fill_ids": sorted(known),
                        "observed_at": snapshot.observed_at,
                    }
                ),
            ),
        )
        return replace(
            snapshot, evidence_revision=revision(db, account), daily_trade_count=count
        )
