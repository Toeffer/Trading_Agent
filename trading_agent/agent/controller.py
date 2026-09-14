"""Durable observe -> reason -> validate -> simulate -> reconcile cycles."""

from copy import deepcopy
import json
from typing import Any

from trading_agent.agent.contracts import Observation
from trading_agent.agent.reasoning import Reasoner, StrategyReasoner
from trading_agent.agent.simulation import apply_cycle, validate_decision
from trading_agent.agent.store import AgentStore
from trading_agent.domain import canonical, content_hash, timestamp


class AgentController:
    def __init__(self, store: AgentStore, reasoner: Reasoner | None = None):
        self.store = store
        self.reasoner = reasoner or StrategyReasoner()
        if self.reasoner.version != store.mandate.raw["strategy"]["version"]:
            raise ValueError("REASONER_VERSION_MISMATCH")

    def prepare(self, raw: dict[str, Any]) -> str:
        # Copy input so callers and providers cannot alter persisted observations.
        observation = Observation.parse(deepcopy(raw), self.store.mandate)
        input_hash = content_hash(observation.raw)
        with self.store.connection(write=True) as db:
            existing = db.execute(
                "SELECT * FROM cycles WHERE event_id=?", (observation.identity,)
            ).fetchone()
            if existing:
                if existing["input_hash"] != input_hash:
                    raise ValueError("EVENT_ID_CONTENT_CONFLICT")
                return observation.identity
            agent = db.execute(
                "SELECT state,pause_reason FROM agent WHERE id=1"
            ).fetchone()
            if agent["pause_reason"]:
                raise RuntimeError("AGENT_PAUSED: " + agent["pause_reason"])
            if db.execute("SELECT 1 FROM cycles WHERE status='planned'").fetchone():
                raise RuntimeError("PENDING_CYCLE_REQUIRES_RECOVERY")
            if not self.store.reconciliation(db)["ok"]:
                raise RuntimeError("PORTFOLIO_LEDGER_MISMATCH")
            mandate = self.store.mandate
            if not mandate.starts_at <= observation.at < mandate.expires_at:
                raise ValueError("OUTSIDE_MANDATE_WINDOW")
            state = json.loads(agent["state"])
            if state["last_at"] and observation.at <= timestamp(state["last_at"]):
                raise ValueError("OUT_OF_ORDER_OBSERVATION")
            decision = self.reasoner.decide(
                deepcopy(observation), deepcopy(mandate), deepcopy(state)
            )
            validate_decision(decision, observation, mandate)
            db.execute(
                "INSERT INTO cycles(event_id,input_hash,observation,state_hash,decision,decision_hash,status) VALUES(?,?,?,?,?,?,'planned')",
                (
                    observation.identity,
                    input_hash,
                    canonical(observation.raw),
                    content_hash(state),
                    canonical(decision),
                    content_hash(decision),
                ),
            )
        return observation.identity

    def complete(self, event_id: str) -> dict[str, Any]:
        # Full local fill + cash/holdings + cycle completion share one transaction.
        # This atomicity is specific to simulation; it is not a broker guarantee.
        with self.store.connection(write=True) as db:
            row = db.execute(
                "SELECT * FROM cycles WHERE event_id=?", (event_id,)
            ).fetchone()
            if row is None:
                raise ValueError("UNKNOWN_CYCLE")
            if row["status"] == "completed":
                return dict(json.loads(row["result"]))
            agent = db.execute(
                "SELECT state,pause_reason FROM agent WHERE id=1"
            ).fetchone()
            if agent["pause_reason"]:
                raise RuntimeError("AGENT_PAUSED: " + agent["pause_reason"])
            state = json.loads(agent["state"])
            if content_hash(state) != row["state_hash"]:
                raise RuntimeError("PORTFOLIO_CHANGED_RECONCILIATION_REQUIRED")
            if not self.store.reconciliation(db)["ok"]:
                raise RuntimeError("PORTFOLIO_LEDGER_MISMATCH")
            raw = json.loads(row["observation"])
            if content_hash(raw) != row["input_hash"]:
                raise RuntimeError("OBSERVATION_HASH_MISMATCH")
            observation = Observation.parse(raw, self.store.mandate)
            decision = json.loads(row["decision"])
            if content_hash(decision) != row["decision_hash"]:
                raise RuntimeError("DECISION_HASH_MISMATCH")
            updated, result, fills = apply_cycle(
                state, observation, self.store.mandate, decision
            )
            for fill in fills:
                db.execute(
                    "INSERT INTO fills VALUES(?,?,?)",
                    (fill["execution_id"], event_id, canonical(fill)),
                )
            db.execute("UPDATE agent SET state=? WHERE id=1", (canonical(updated),))
            db.execute(
                "UPDATE cycles SET status='completed',result=? WHERE event_id=?",
                (canonical(result), event_id),
            )
            return result

    def process(self, raw: dict[str, Any]) -> dict[str, Any]:
        return self.complete(self.prepare(raw))

    def recover(self) -> list[dict[str, Any]]:
        with self.store.connection() as db:
            pending = [
                r[0]
                for r in db.execute(
                    "SELECT event_id FROM cycles WHERE status='planned'"
                )
            ]
        return [self.complete(event_id) for event_id in pending]
