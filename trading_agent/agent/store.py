"""Separate SQLite authority for the agent simulation, never the broker database."""

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from decimal import Decimal
from typing import Any, Iterator

from trading_agent.agent.contracts import Mandate
from trading_agent.domain import canonical, content_hash, money

APPLICATION_ID = 0x54414741
SCHEMA_VERSION = 1


class AgentStore:
    def __init__(self, path: Path):
        self.path = path.resolve()
        # Opening a report never initializes or upgrades a database.
        with self.connection() as db:
            row = db.execute(
                "SELECT config, config_hash FROM agent WHERE id=1"
            ).fetchone()
            if row is None:
                raise ValueError("AGENT_NOT_INITIALIZED")
            self.mandate = Mandate.parse(json.loads(row["config"]))
            if self.mandate.identity != row["config_hash"]:
                raise ValueError("MANDATE_HASH_MISMATCH")

    @classmethod
    def create(cls, path: Path, config: dict[str, Any]) -> "AgentStore":
        mandate = Mandate.parse(config)
        path = path.resolve()
        # Exclusive creation prevents accidental reuse of execution state.
        with path.open("xb"):
            pass
        state = {
            "cash": str(mandate.raw["initial_cash"]),
            "positions": {},
            "equity": str(mandate.raw["initial_cash"]),
            "daily_count": 0,
            "day": None,
            "week": None,
            "day_anchor": str(mandate.raw["initial_cash"]),
            "week_anchor": str(mandate.raw["initial_cash"]),
            "last_at": None,
        }
        db = sqlite3.connect(path)
        try:
            db.executescript(f"""
                BEGIN IMMEDIATE;
                PRAGMA application_id={APPLICATION_ID};
                PRAGMA user_version={SCHEMA_VERSION};
                CREATE TABLE agent (
                    id INTEGER PRIMARY KEY CHECK(id=1), config TEXT NOT NULL,
                    config_hash TEXT NOT NULL, state TEXT NOT NULL, pause_reason TEXT
                );
                CREATE TABLE cycles (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE, input_hash TEXT NOT NULL,
                    observation TEXT NOT NULL, state_hash TEXT NOT NULL,
                    decision TEXT NOT NULL, decision_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('planned','completed')),
                    result TEXT
                );
                CREATE UNIQUE INDEX one_pending_cycle ON cycles(status) WHERE status='planned';
                CREATE TABLE fills (
                    execution_id TEXT PRIMARY KEY, event_id TEXT NOT NULL,
                    body TEXT NOT NULL, FOREIGN KEY(event_id) REFERENCES cycles(event_id)
                );
            """)
            db.execute(
                "INSERT INTO agent VALUES(1,?,?,?,NULL)",
                (canonical(config), mandate.identity, canonical(state)),
            )
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
        return cls(path)

    @contextmanager
    def connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        mode = "rw" if write else "ro"
        db = sqlite3.connect(self.path.as_uri() + "?mode=" + mode, uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            if db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise ValueError("NOT_AN_AGENT_DATABASE")
            if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise ValueError("UNSUPPORTED_AGENT_DATABASE_VERSION")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            row = db.execute(
                "SELECT config, config_hash FROM agent WHERE id=1"
            ).fetchone()
            if row and (
                content_hash(json.loads(row["config"])) != row["config_hash"]
                or (
                    hasattr(self, "mandate")
                    and row["config_hash"] != self.mandate.identity
                )
            ):
                raise ValueError("MANDATE_HASH_MISMATCH")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def pause(self, reason: str | None) -> None:
        if reason is not None and (not reason.strip() or len(reason) > 500):
            raise ValueError("PAUSE_REASON_REQUIRED")
        with self.connection(write=True) as db:
            db.execute("UPDATE agent SET pause_reason=? WHERE id=1", (reason,))

    def reconciliation(self, db: sqlite3.Connection) -> dict[str, Any]:
        """Independently reconstruct cash/quantities from the simulated fill ledger."""
        state = json.loads(
            db.execute("SELECT state FROM agent WHERE id=1").fetchone()[0]
        )
        cash = money(self.mandate.raw["initial_cash"])
        quantities: dict[str, int] = {}
        for row in db.execute("SELECT body FROM fills ORDER BY rowid"):
            fill = json.loads(row["body"])
            value = (
                fill["quantity"] * money(fill["price"]) / money(fill["base_to_quote"])
            )
            fee = money(fill["commission_base"])
            if fill["side"] == "BUY":
                cash = cash - value - fee
                quantities[fill["symbol"]] = (
                    quantities.get(fill["symbol"], 0) + fill["quantity"]
                )
            else:
                cash = cash + value - fee
                quantities[fill["symbol"]] = (
                    quantities.get(fill["symbol"], 0) - fill["quantity"]
                )
        actual = {s: p["quantity"] for s, p in state["positions"].items()}
        expected = {s: q for s, q in quantities.items() if q}
        latest = db.execute(
            "SELECT result FROM cycles WHERE status='completed' ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        state_matches = latest is None or content_hash(
            json.loads(latest[0])["after"]
        ) == content_hash(state)
        cash_matches = abs(cash - money(state["cash"])) <= Decimal("1e-18")
        positions_match = expected == actual
        return {
            "ok": cash_matches and positions_match and state_matches,
            "cash_matches": cash_matches,
            "positions_match": positions_match,
            "last_cycle_matches": state_matches,
            "source": "local_simulated_fills",
        }

    def report(self) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM agent WHERE id=1").fetchone()
            cycles = db.execute(
                "SELECT event_id,status,result FROM cycles ORDER BY sequence"
            ).fetchall()
            fills = db.execute("SELECT body FROM fills ORDER BY rowid").fetchall()
            return {
                "mode": "simulation",
                "broker_connected": False,
                "mandate_hash": self.mandate.identity,
                "account": self.mandate.account,
                "pause_reason": row["pause_reason"],
                "portfolio": json.loads(row["state"]),
                "reconciliation": self.reconciliation(db),
                "pending": [c["event_id"] for c in cycles if c["status"] == "planned"],
                "cycles": [
                    {
                        "event_id": c["event_id"],
                        "status": c["status"],
                        "result": json.loads(c["result"]) if c["result"] else None,
                    }
                    for c in cycles
                ],
                "fills": [json.loads(f["body"]) for f in fills],
            }
