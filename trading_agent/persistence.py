"""Transactional approval and execution authority; no broker operations."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, cast
import uuid

from trading_agent.domain import (
    ApprovedOrderPlan,
    BrokerResult,
    canonical,
    money,
    timestamp,
    utcnow,
)


class StateConflict(ValueError):
    pass


class ExecutionStore:
    def __init__(self, path: Path):
        self.path = path
        self.readonly = False
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise StateConflict("UNSUPPORTED_DATABASE_VERSION")
            if version == 3:
                return
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY, account TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','approved','denied','expired','reserved')),
                    plan TEXT NOT NULL, expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL, ruling_at TEXT, ruled_by TEXT);
                CREATE TABLE IF NOT EXISTS executions (
                    execution_id TEXT PRIMARY KEY,
                    approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id),
                    account TEXT NOT NULL, execution_state TEXT NOT NULL,
                    protection_state TEXT NOT NULL, result TEXT,
                    filled_quantity INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reservations (
                    execution_id TEXT PRIMARY KEY REFERENCES executions(execution_id),
                    account TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
                    quantity INTEGER NOT NULL, price TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS fills (
                    account TEXT NOT NULL, broker_execution_id TEXT NOT NULL,
                    execution_id TEXT NOT NULL REFERENCES executions(execution_id),
                    quantity INTEGER NOT NULL CHECK(quantity > 0), price TEXT NOT NULL,
                    observed_at TEXT NOT NULL, PRIMARY KEY(account, broker_execution_id));
                CREATE TABLE IF NOT EXISTS outbox (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL, exported INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS legacy_records (
                    source TEXT NOT NULL, record_hash TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(source, record_hash));
                CREATE TABLE IF NOT EXISTS account_risk (
                    account TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS legacy_quarantine (
                    record_hash TEXT PRIMARY KEY, account TEXT NOT NULL,
                    payload TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0,
                    evidence TEXT);
                CREATE TABLE IF NOT EXISTS broker_events (
                    account TEXT NOT NULL, broker_execution_id TEXT NOT NULL,
                    execution_id TEXT NOT NULL REFERENCES executions(execution_id),
                    role TEXT NOT NULL CHECK(role IN ('parent','stop')), payload TEXT NOT NULL,
                    PRIMARY KEY(account, broker_execution_id));
                CREATE TABLE IF NOT EXISTS account_revision (
                    account TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS account_fill_history (
                    account TEXT NOT NULL, broker_execution_id TEXT NOT NULL,
                    order_key TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(account, broker_execution_id));
                CREATE TABLE IF NOT EXISTS holdings_anchor (
                    account TEXT PRIMARY KEY, payload TEXT NOT NULL);
                PRAGMA user_version=2;
                COMMIT;
            """)
            db.execute("BEGIN IMMEDIATE")
            try:
                for row in db.execute("SELECT * FROM fills").fetchall():
                    self._broker_event(
                        db,
                        row["account"],
                        row["execution_id"],
                        "parent",
                        row["broker_execution_id"],
                        row["quantity"],
                        money(row["price"]),
                        row["observed_at"],
                    )
                if version in (1, 2):
                    for row in db.execute(
                        "SELECT execution_id FROM executions"
                    ).fetchall():
                        db.execute(
                            "UPDATE executions SET execution_state='unknown' WHERE execution_id=?",
                            (row[0],),
                        )
                        db.execute(
                            "UPDATE reservations SET active=1 WHERE execution_id=?",
                            (row[0],),
                        )
                        self._event(
                            db,
                            "broker_result",
                            {
                                "execution_id": row[0],
                                "execution_state": "unknown",
                                "error_code": "SCHEMA_3_RECONCILIATION_REQUIRED",
                            },
                        )
                db.execute("PRAGMA user_version=3")
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @classmethod
    def open_readonly(cls, path: Path) -> "ExecutionStore":
        store = cls.__new__(cls)
        store.path, store.readonly = path, True
        with store.connection() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != 3:
                raise StateConflict("MIGRATION_REQUIRED")
        return store

    @staticmethod
    def backup_existing(source: Path, destination: Path) -> None:
        if not source.is_file() or destination.exists():
            raise ValueError("Existing source and new backup path required")
        destination.touch(exist_ok=False)
        destination.chmod(0o600)
        with sqlite3.connect(
            source.resolve().as_uri() + "?mode=ro", uri=True
        ) as original:
            with sqlite3.connect(destination) as backup:
                original.backup(backup)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(
            self.path.resolve().as_uri() + "?mode=ro"
            if self.readonly
            else str(self.path),
            uri=self.readonly,
            timeout=8,
            isolation_level=None,
        )
        db.row_factory = sqlite3.Row
        try:
            if not self.readonly:
                db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        if self.readonly:
            raise StateConflict("READ_ONLY_STORE")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.rollback()
                raise
            else:
                db.commit()

    @staticmethod
    def _event(db: sqlite3.Connection, event: str, payload: dict[str, Any]) -> None:
        db.execute(
            "INSERT INTO outbox(event,payload,created_at) VALUES(?,?,?)",
            (event, canonical(payload), utcnow().isoformat()),
        )
        if event in (
            "fill",
            "broker_fill_evidence",
            "broker_result",
            "broker_reconciliation",
            "execution_reserved",
            "account_fill",
        ):
            account = payload.get("account")
            if not account and payload.get("execution_id"):
                row = db.execute(
                    "SELECT account FROM executions WHERE execution_id=?",
                    (payload["execution_id"],),
                ).fetchone()
                account = row[0] if row else None
            if account:
                db.execute(
                    "INSERT INTO account_revision VALUES(?,1) ON CONFLICT(account) DO UPDATE SET revision=revision+1",
                    (account,),
                )

    @staticmethod
    def _approval(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["plan"] = json.loads(result["plan"])
        return result

    @staticmethod
    def _execution(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["result"] = json.loads(result["result"]) if result["result"] else None
        result["retry_allowed"] = False
        result["status_url"] = "/order/executions/" + result["execution_id"]
        result["next_action"] = (
            "human_reconciliation"
            if result["execution_state"] == "unknown"
            else "status_lookup"
        )
        result["submitted"] = result["execution_state"] in (
            "acknowledged",
            "partially_filled",
            "filled",
        )
        return result

    def create_pending(
        self, plan: ApprovedOrderPlan, *, evidence: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if utcnow() >= plan.expires_at:
            raise StateConflict("EXPIRED")
        aid = "aprv_" + uuid.uuid4().hex
        with self.transaction() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM approvals WHERE account=? AND status IN ('pending','approved') AND expires_at>?",
                (plan.account, utcnow().isoformat()),
            ).fetchone()[0]
            if count >= 128:
                raise StateConflict("APPROVAL_QUEUE_FULL")
            db.execute(
                "INSERT INTO approvals VALUES(?,?, 'pending', ?,?,?,NULL,NULL)",
                (
                    aid,
                    plan.account,
                    plan.to_json(),
                    plan.expires_at.isoformat(),
                    plan.created_at.isoformat(),
                ),
            )
            self._event(
                db,
                "approval_pending",
                {
                    "approval_id": aid,
                    "plan": plan.to_dict(),
                    "decision_snapshot": evidence,
                },
            )
        return self.approval(aid)

    def approval(self, aid: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM approvals WHERE approval_id=?", (aid,)
            ).fetchone()
            if row is None:
                raise StateConflict("NOT_FOUND")
            return self._approval(row)

    def approvals(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            return [
                self._approval(row)
                for row in db.execute(
                    "SELECT * FROM approvals WHERE status IN ('pending','approved') AND expires_at>?",
                    (utcnow().isoformat(),),
                )
            ]

    def rule(
        self, aid: str, decision: str, *, authorized: bool, actor: str = "human"
    ) -> dict[str, Any]:
        if authorized is not True:
            raise PermissionError("H1_TOKEN_REQUIRED")
        if decision not in ("approved", "denied"):
            raise ValueError("Invalid ruling")
        with self.transaction() as db:
            updated = db.execute(
                "UPDATE approvals SET status=?,ruling_at=?,ruled_by=? "
                "WHERE approval_id=? AND status='pending' AND expires_at>?",
                (decision, utcnow().isoformat(), actor, aid, utcnow().isoformat()),
            )
            if updated.rowcount != 1:
                raise StateConflict("APPROVAL_NOT_PENDING_OR_EXPIRED")
            self._event(
                db, "approval_" + decision, {"approval_id": aid, "actor": actor}
            )
        return self.approval(aid)

    def reserve(
        self,
        aid: str,
        *,
        authorized: bool,
        validate: Callable[[ApprovedOrderPlan, list[dict[str, Any]]], None]
        | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if authorized is not True:
            raise PermissionError("H1_TOKEN_REQUIRED")
        with self.transaction() as db:
            existing = db.execute(
                "SELECT * FROM executions WHERE approval_id=?", (aid,)
            ).fetchone()
            if existing is not None:
                return self._execution(existing), False
            if evidence is not None:
                from trading_agent.accounting import revision

                portfolio = evidence.get("portfolio", {})
                if portfolio.get("evidence_revision") != revision(
                    db, portfolio.get("account", "")
                ):
                    raise StateConflict("ACCOUNT_EVIDENCE_CHANGED")
            row = db.execute(
                "SELECT * FROM approvals WHERE approval_id=?", (aid,)
            ).fetchone()
            if row is None:
                raise StateConflict("NOT_FOUND")
            if row["status"] != "approved" or timestamp(row["expires_at"]) <= utcnow():
                raise StateConflict("APPROVAL_NOT_APPROVED_OR_EXPIRED")
            plan = ApprovedOrderPlan.from_json(row["plan"])
            unresolved = db.execute(
                "SELECT 1 FROM executions WHERE account=? AND "
                "(execution_state IN ('submitting','unknown') OR protection_state='unknown') LIMIT 1",
                (plan.account,),
            ).fetchone()
            if unresolved:
                raise StateConflict("UNRESOLVED_EXECUTION")
            if (
                plan.side == "BUY"
                and db.execute(
                    "SELECT 1 FROM executions WHERE account=? AND protection_state='cancelled' LIMIT 1",
                    (plan.account,),
                ).fetchone()
            ):
                raise StateConflict(
                    "CANCELLED_PROTECTION_REQUIRES_CLOSE_RECONCILIATION"
                )
            if db.execute(
                "SELECT 1 FROM legacy_quarantine WHERE resolved=0 AND account IN (?, '*') LIMIT 1",
                (plan.account,),
            ).fetchone():
                raise StateConflict("UNRESOLVED_LEGACY_EXECUTION")
            reservations = [
                dict(item)
                for item in db.execute(
                    "SELECT r.*,e.filled_quantity FROM reservations r JOIN executions e USING(execution_id) WHERE r.account=? AND r.active=1",
                    (plan.account,),
                )
            ]
            if validate is not None:
                validate(plan, reservations)
            eid = "exec_" + uuid.uuid4().hex
            now = utcnow().isoformat()
            protection = "unknown" if plan.side == "BUY" else "not_applicable"
            db.execute(
                "INSERT INTO executions VALUES(?,?,?,'submitting',?,NULL,0,?,?)",
                (eid, aid, plan.account, protection, now, now),
            )
            db.execute(
                "INSERT INTO reservations VALUES(?,?,?,?,?,?,1)",
                (
                    eid,
                    plan.account,
                    plan.symbol,
                    plan.side,
                    plan.quantity,
                    str(plan.entry_price),
                ),
            )
            db.execute(
                "UPDATE approvals SET status='reserved' WHERE approval_id=?", (aid,)
            )
            self._event(
                db,
                "execution_reserved",
                {
                    "execution_id": eid,
                    "approval_id": aid,
                    "plan": plan.to_dict(),
                    "decision_snapshot": evidence,
                },
            )
        return self.execution(eid), True

    def execution(self, eid: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM executions WHERE execution_id=?", (eid,)
            ).fetchone()
            if row is None:
                raise StateConflict("EXECUTION_NOT_FOUND")
            return self._execution(row)

    def execution_for_approval(self, aid: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM executions WHERE approval_id=?", (aid,)
            ).fetchone()
            return self._execution(row) if row is not None else None

    def reservations(self, account: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT r.*,e.filled_quantity FROM reservations r JOIN executions e USING(execution_id) WHERE r.account=? AND r.active=1",
                    (account,),
                )
            ]

    def evidence_revision(self, account: str) -> int:
        from trading_agent.accounting import revision

        with self.connection() as db:
            return revision(db, account)

    def record_result(
        self, eid: str, result: BrokerResult, *, reconciled: bool = False
    ) -> None:
        try:
            self._record_result(eid, result, reconciled=reconciled)
        except StateConflict:
            self.quarantine_execution(eid)
            raise

    def quarantine_execution(self, eid: str) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE executions SET execution_state='unknown',updated_at=? WHERE execution_id=?",
                (utcnow().isoformat(), eid),
            )
            db.execute("UPDATE reservations SET active=1 WHERE execution_id=?", (eid,))
            self._event(
                db,
                "broker_result",
                {
                    "execution_id": eid,
                    "execution_state": "unknown",
                    "error_code": "CONFLICTING_BROKER_EVIDENCE",
                },
            )

    def _record_result(
        self, eid: str, result: BrokerResult, *, reconciled: bool = False
    ) -> None:
        with self.transaction() as db:
            row = db.execute(
                "SELECT e.*,a.plan FROM executions e JOIN approvals a USING(approval_id) WHERE execution_id=?",
                (eid,),
            ).fetchone()
            if row is None:
                raise StateConflict("EXECUTION_NOT_FOUND")
            plan = ApprovedOrderPlan.from_json(row["plan"])
            for broker_id, quantity, price, observed in result.fills:
                self._record_fill(db, eid, broker_id, quantity, price, observed)
            for broker_id, quantity, price, observed in result.stop_fills:
                self._broker_event(
                    db,
                    row["account"],
                    eid,
                    "stop",
                    broker_id,
                    quantity,
                    price,
                    observed,
                )
            stop_total = sum(
                json.loads(r[0])["quantity"]
                for r in db.execute(
                    "SELECT payload FROM broker_events WHERE execution_id=? AND role='stop'",
                    (eid,),
                )
            )
            if stop_total > plan.quantity or (stop_total and plan.side != "BUY"):
                raise StateConflict("STOP_FILL_EXCEEDS_APPROVED_QUANTITY")
            total = db.execute(
                "SELECT filled_quantity FROM executions WHERE execution_id=?", (eid,)
            ).fetchone()[0]
            if stop_total > total:
                raise StateConflict("STOP_FILL_EXCEEDS_VERIFIED_PARENT_FILLS")
            state = result.state.value
            protection = result.protection_state
            if total == plan.quantity and state != "unknown":
                state = "filled"
            elif state == "filled" or result.filled_quantity > total:
                state = "unknown"  # Status totals alone are not fill evidence.
            elif total and state == "acknowledged":
                state = "partially_filled"
            if plan.side == "BUY" and protection == "not_applicable":
                state, protection = "unknown", "unknown"
            # Delayed callbacks cannot resume quarantined execution. A human
            # must request reconciliation against fresh broker evidence.
            if row["execution_state"] == "unknown" and not reconciled:
                state = "unknown"
            if row["protection_state"] == "cancelled" and not reconciled:
                protection = "cancelled"
            db.execute(
                "UPDATE executions SET execution_state=?,protection_state=?,result=?,updated_at=? WHERE execution_id=?",
                (
                    state,
                    protection,
                    canonical(result.to_dict()),
                    utcnow().isoformat(),
                    eid,
                ),
            )
            if state in ("filled", "rejected", "cancelled") and protection != "unknown":
                db.execute(
                    "UPDATE reservations SET active=0 WHERE execution_id=?", (eid,)
                )
            self._event(
                db,
                "broker_reconciliation" if reconciled else "broker_result",
                {"execution_id": eid, **result.to_dict()},
            )

    def _broker_event(
        self,
        db: sqlite3.Connection,
        account: str,
        eid: str,
        role: str,
        broker_id: str,
        quantity: int,
        price: Decimal,
        observed: Any,
    ) -> bool:
        if (
            not broker_id
            or type(quantity) is not int
            or quantity <= 0
            or money(price) <= 0
        ):
            raise ValueError("Invalid execution evidence")
        payload = canonical(
            {
                "quantity": quantity,
                "price": money(price),
                "observed_at": timestamp(observed),
            }
        )
        old = db.execute(
            "SELECT * FROM broker_events WHERE account=? AND broker_execution_id=?",
            (account, broker_id),
        ).fetchone()
        if old:
            if (
                old["execution_id"] != eid
                or old["role"] != role
                or old["payload"] != payload
            ):
                raise StateConflict("CONFLICTING_FILL_EVIDENCE")
            return False
        db.execute(
            "INSERT INTO broker_events VALUES(?,?,?,?,?)",
            (account, broker_id, eid, role, payload),
        )
        self._event(
            db,
            "broker_fill_evidence",
            {
                "execution_id": eid,
                "role": role,
                "broker_execution_id": broker_id,
                **json.loads(payload),
            },
        )
        return True

    def record_fill(
        self,
        eid: str,
        broker_id: str,
        quantity: int,
        price: Decimal,
        *,
        observed_at: Any = None,
    ) -> bool:
        if (
            type(quantity) is not int
            or quantity <= 0
            or not price.is_finite()
            or price <= 0
            or not broker_id
        ):
            raise ValueError("Invalid execution evidence")
        if observed_at is None:
            with self.connection() as db:
                prior = db.execute(
                    "SELECT observed_at FROM fills WHERE execution_id=? AND broker_execution_id=?",
                    (eid, broker_id),
                ).fetchone()
                observed_at = prior[0] if prior else utcnow()
        observed = timestamp(observed_at).isoformat()
        try:
            with self.transaction() as db:
                return self._record_fill(db, eid, broker_id, quantity, price, observed)
        except StateConflict:
            self.quarantine_execution(eid)
            raise

    def _record_fill(
        self,
        db: sqlite3.Connection,
        eid: str,
        broker_id: str,
        quantity: int,
        price: Decimal,
        observed: Any,
    ) -> bool:
        observed = timestamp(observed).isoformat()
        row = db.execute(
            "SELECT e.*,a.plan FROM executions e JOIN approvals a USING(approval_id) WHERE execution_id=?",
            (eid,),
        ).fetchone()
        if row is None:
            raise StateConflict("EXECUTION_NOT_FOUND")
        old = db.execute(
            "SELECT * FROM fills WHERE account=? AND broker_execution_id=?",
            (row["account"], broker_id),
        ).fetchone()
        if old is not None:
            if (
                old["execution_id"] != eid
                or old["quantity"] != quantity
                or Decimal(old["price"]) != price
                or timestamp(old["observed_at"]) != timestamp(observed)
            ):
                raise StateConflict("CONFLICTING_FILL_EVIDENCE")
            return False
        total = row["filled_quantity"] + quantity
        plan = ApprovedOrderPlan.from_json(row["plan"])
        if total > plan.quantity:
            raise StateConflict("FILL_EXCEEDS_APPROVED_QUANTITY")
        self._broker_event(
            db, row["account"], eid, "parent", broker_id, quantity, price, observed
        )
        db.execute(
            "INSERT INTO fills VALUES(?,?,?,?,?,?)",
            (row["account"], broker_id, eid, quantity, str(price), observed),
        )
        state = (
            "unknown"
            if row["execution_state"] == "unknown"
            else ("filled" if total == plan.quantity else "partially_filled")
        )
        db.execute(
            "UPDATE executions SET filled_quantity=?,execution_state=?,updated_at=? WHERE execution_id=?",
            (total, state, utcnow().isoformat(), eid),
        )
        # Hold reservations until a fresh broker snapshot can absorb fills;
        # terminal evidence releases them through record_result/reconcile.
        self._event(
            db,
            "fill",
            {
                "execution_id": eid,
                "broker_execution_id": broker_id,
                "quantity": quantity,
                "price": price,
                "observed_at": observed,
            },
        )
        return True

    def daily_trade_count(self, account: str, day: date) -> int:
        from trading_agent.accounting import daily_count

        with self.connection() as db:
            return daily_count(db, account, day)

    def close_cancelled_protection(
        self, account: str, symbol: str, closing_execution: str
    ) -> None:
        """Called only after human reconciliation verifies the account is flat."""
        with self.transaction() as db:
            closing = db.execute(
                "SELECT e.execution_state,a.plan FROM executions e JOIN approvals a USING(approval_id) WHERE execution_id=? AND e.account=?",
                (closing_execution, account),
            ).fetchone()
            if not closing or closing["execution_state"] != "filled":
                raise StateConflict("CLOSE_EXECUTION_NOT_FILLED")
            plan = ApprovedOrderPlan.from_json(closing["plan"])
            if plan.side != "SELL" or plan.symbol != symbol:
                raise StateConflict("CLOSE_EXECUTION_MISMATCH")
            rows = db.execute(
                "SELECT e.execution_id,a.plan FROM executions e JOIN approvals a USING(approval_id) WHERE e.account=? AND protection_state='cancelled'",
                (account,),
            ).fetchall()
            for row in rows:
                if ApprovedOrderPlan.from_json(row["plan"]).symbol == symbol:
                    db.execute(
                        "UPDATE executions SET protection_state='closed' WHERE execution_id=?",
                        (row["execution_id"],),
                    )
                    self._event(
                        db,
                        "cancelled_protection_closed",
                        {
                            "execution_id": row["execution_id"],
                            "closing_execution": closing_execution,
                        },
                    )

    def startup(self) -> None:
        with self.transaction() as db:
            expired = [
                row[0]
                for row in db.execute(
                    "SELECT approval_id FROM approvals WHERE status IN ('pending','approved')"
                )
            ]
            db.execute(
                "UPDATE approvals SET status='expired' WHERE status IN ('pending','approved')"
            )
            db.execute(
                "UPDATE executions SET execution_state='unknown' WHERE execution_state IN ('submitting','acknowledged','partially_filled') OR protection_state='confirmed'"
            )
            self._event(db, "startup_invalidation", {"expired_approvals": expired})

    def initialize_risk(
        self, account: str, payload: dict[str, Any], *, authorized: bool
    ) -> None:
        """One-time, human/admin-authorized import; cannot reset a current halt."""
        if authorized is not True:
            raise PermissionError("H1_TOKEN_REQUIRED")
        for key in ("day_start_nl_eur", "week_start_nl_eur"):
            if money(payload.get(key)) <= 0:
                raise ValueError("MISSING_RISK_BASELINE")
        date.fromisoformat(payload["trade_date"])
        date.fromisoformat(payload["week_start_date"])
        if (
            type(payload.get("daily_trade_count")) is not int
            or payload["daily_trade_count"] < 0
        ):
            raise ValueError("INVALID_IMPORTED_DAILY_COUNT")
        with self.transaction() as db:
            if db.execute(
                "SELECT 1 FROM account_risk WHERE account=?", (account,)
            ).fetchone():
                raise StateConflict("RISK_ALREADY_INITIALIZED")
            db.execute(
                "INSERT INTO account_risk VALUES(?,?)", (account, canonical(payload))
            )
            self._event(db, "risk_initialized", {"account": account, "state": payload})

    def risk_state(
        self, account: str, current_net_liquidation: Decimal | None = None
    ) -> dict[str, Any]:
        with self.transaction() as db:
            row = db.execute(
                "SELECT payload FROM account_risk WHERE account=?", (account,)
            ).fetchone()
            if row is None:
                raise StateConflict("RISK_BASELINE_NOT_INITIALIZED")
            state = cast(dict[str, Any], json.loads(row[0]))
            today = utcnow().date()
            monday = today - timedelta(days=today.weekday())
            if (
                date.fromisoformat(state["trade_date"]) > today
                or date.fromisoformat(state["week_start_date"]) > monday
            ):
                raise StateConflict("FUTURE_RISK_BASELINE")
            changed = False
            if current_net_liquidation is not None:
                if money(current_net_liquidation) <= 0:
                    raise ValueError("INVALID_ACCOUNT_VALUE")
                if date.fromisoformat(state["trade_date"]) < today:
                    state.update(
                        trade_date=today.isoformat(),
                        day_start_nl_eur=str(current_net_liquidation),
                        daily_trade_count=0,
                        daily_halt_active=False,
                    )
                    changed = True
                if date.fromisoformat(state["week_start_date"]) < monday:
                    state.update(
                        week_start_date=monday.isoformat(),
                        week_start_nl_eur=str(current_net_liquidation),
                        weekly_halt_active=False,
                    )
                    changed = True
            if changed:
                db.execute(
                    "UPDATE account_risk SET payload=? WHERE account=?",
                    (canonical(state), account),
                )
                self._event(
                    db, "risk_calendar_rollover", {"account": account, "state": state}
                )
            return state

    def backup(self, destination: Path) -> None:
        if destination.exists():
            raise ValueError("Backup destination already exists")
        with self.connection() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()

    def latch_halts(self, account: str, daily: bool, weekly: bool) -> None:
        with self.transaction() as db:
            row = db.execute(
                "SELECT payload FROM account_risk WHERE account=?", (account,)
            ).fetchone()
            if row is None:
                raise StateConflict("RISK_BASELINE_NOT_INITIALIZED")
            state = json.loads(row[0])
            state["daily_halt_active"] = bool(state.get("daily_halt_active") or daily)
            state["weekly_halt_active"] = bool(
                state.get("weekly_halt_active") or weekly
            )
            db.execute(
                "UPDATE account_risk SET payload=? WHERE account=?",
                (canonical(state), account),
            )
            self._event(
                db,
                "loss_halt",
                {
                    "account": account,
                    "daily": state["daily_halt_active"],
                    "weekly": state["weekly_halt_active"],
                },
            )

    def export(self, directory: Path) -> int:
        """Atomic per-event files provide idempotent crash-safe outbox delivery."""
        directory.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute(
                "BEGIN"
            )  # A consistent read snapshot never holds the writer lock during file I/O.
            pending = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM outbox WHERE exported=0 ORDER BY sequence LIMIT 256"
                )
            ]
            # Replace complete compatibility projections, never append twice
            # after a crash. The outbox and database remain authoritative.
            projections = {
                "active-approvals.json": canonical(
                    {
                        row["approval_id"]: self._compat_approval(row)
                        for row in db.execute(
                            "SELECT * FROM approvals WHERE status IN ('pending','approved')"
                        )
                    }
                ),
                "submitted-approvals.json": canonical(
                    [row[0] for row in db.execute("SELECT approval_id FROM executions")]
                ),
                "approval-records.jsonl": "".join(
                    canonical(self._compat_approval(row)) + "\n"
                    for row in db.execute("SELECT * FROM approvals ORDER BY created_at")
                ),
                "guard-events.jsonl": "".join(
                    canonical(
                        {
                            "sequence": row["sequence"],
                            "event_type": row["event"],
                            "timestamp": row["created_at"],
                            **json.loads(row["payload"]),
                        }
                    )
                    + "\n"
                    for row in db.execute("SELECT * FROM outbox ORDER BY sequence")
                ),
            }
            risks = db.execute("SELECT account,payload FROM account_risk").fetchall()
            if len(risks) == 1:
                state = json.loads(risks[0]["payload"])
                from trading_agent.accounting import daily_count

                state["daily_trade_count"] = daily_count(
                    db, risks[0]["account"], date.fromisoformat(state["trade_date"])
                )
                state["accounting_reconciliation_required"] = bool(
                    json.loads(risks[0]["payload"])["daily_trade_count"]
                )
                state["execution_authority"] = "sqlite"
                projections["guard-state.json"] = canonical(state)
            db.commit()
        # A failing or slow filesystem cannot hold up authoritative commits.
        for row in pending:
            self._atomic_export(
                directory / f"{row['sequence']:020d}.json", canonical(row)
            )
        for name, content in projections.items():
            self._atomic_export(directory / name, content)
        if os.name != "nt":
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        with self.transaction() as db:
            db.executemany(
                "UPDATE outbox SET exported=1 WHERE sequence=?",
                ((r["sequence"],) for r in pending),
            )
        return len(pending)

    @staticmethod
    def _atomic_export(target: Path, content: str) -> None:
        temporary = target.with_suffix(target.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)

    @staticmethod
    def _compat_approval(row: sqlite3.Row) -> dict[str, Any]:
        plan = ApprovedOrderPlan.from_json(row["plan"])
        return {
            **ExecutionStore._approval(row),
            "created_at_utc": row["created_at"],
            "expires_at_utc": row["expires_at"],
            "proposal": {
                "symbol": plan.symbol,
                "action": plan.side,
                "totalQuantity": plan.quantity,
                "orderType": plan.order_type,
                "stopPrice": plan.stop_price,
            },
            "validation": {
                "entry_price": plan.entry_price,
                "stop_price": plan.stop_price,
            },
        }

    def decision_snapshots(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            snapshots = []
            for row in db.execute(
                "SELECT sequence,event,payload FROM outbox WHERE event IN ('approval_pending','execution_reserved') ORDER BY sequence"
            ):
                payload = json.loads(row["payload"])
                snapshot = payload.get("decision_snapshot")
                if snapshot is not None:
                    snapshots.append(
                        {
                            **snapshot,
                            "source_event": row["event"],
                            "source_sequence": row["sequence"],
                        }
                    )
            return snapshots
