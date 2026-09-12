"""Read-only operational evidence and manual response guidance."""

from dataclasses import dataclass
from datetime import datetime

from trading_agent.domain import timestamp, utcnow
from trading_agent.persistence import ExecutionStore


@dataclass(frozen=True, slots=True)
class OperationalEvidence:
    account: str
    unresolved_executions: int
    oldest_unresolved_age_seconds: float | None
    pending_exports: int
    oldest_export_age_seconds: float | None
    last_account_reconciliation_at: str | None
    last_execution_reconciliation_at: str | None
    observed_at: str
    export_scope: str = "execution_service"


ACTIONS: dict[str, str] = {
    "UNRESOLVED_EXECUTION": "Keep intake locked; inspect execution status and reconcile broker evidence with H1. Never resubmit.",
    "UNRESOLVED_LEGACY_EXECUTION": "Reconcile quarantined historical identities against broker evidence before enabling intake.",
    "BROKER_EVENT_REVIEW_REQUIRED": "Keep intake locked; preserve database and broker evidence, repair event persistence, then reconcile manually.",
    "BROKER_QUEUE_FULL": "Stop new requests, inspect stalled broker operations and deadlines; do not retry uncertain submissions.",
    "PAPER_ACCOUNT_NOT_CONNECTED": "Verify the configured paper account and gateway connection before requesting fresh preflight.",
    "BROKER_STATUS_UNAVAILABLE": "Inspect the owner loop and gateway responsiveness. Preserve unresolved intents; do not infer a disconnected account from a timeout.",
    "EXPORT_BACKLOG": "Inspect export directory permissions and disk capacity; preserve SQLite and retry exports after repair.",
    "ORDERS_BLOCKED": "Leave switches disabled until release checks and the human paper window are explicitly approved.",
    "H1_NOT_CONFIGURED": "Have the administrator configure the human approval credential; never put secrets in logs or arguments.",
    "RELEASE_NOT_VERIFIED": "Verify the deployed commit and configuration against the reviewed candidate.",
}


def operator_actions(codes: list[str]) -> dict[str, str]:
    return {
        code: ACTIONS.get(
            code,
            "Keep intake locked and investigate the recorded blocker before operator reconciliation.",
        )
        for code in codes
    }


def observe(
    store: ExecutionStore, account: str, *, now: datetime | None = None
) -> OperationalEvidence:
    at = now or utcnow()

    def age(value: str | None) -> float | None:
        return max(0.0, (at - timestamp(value)).total_seconds()) if value else None

    with store.connection() as db:
        db.execute("BEGIN")
        unresolved = db.execute(
            "SELECT COUNT(*),MIN(created_at) FROM executions WHERE account=? AND (execution_state IN ('unknown','submitting') OR protection_state='unknown')",
            (account,),
        ).fetchone()
        exports = db.execute(
            "SELECT COUNT(*),MIN(created_at) FROM outbox WHERE exported=0"
        ).fetchone()
        account_reconciled = db.execute(
            "SELECT MAX(created_at) FROM outbox WHERE event='account_reconciliation' AND json_extract(payload,'$.account')=?",
            (account,),
        ).fetchone()[0]
        execution_reconciled = db.execute(
            "SELECT MAX(o.created_at) FROM outbox o JOIN executions e ON e.execution_id=json_extract(o.payload,'$.execution_id') WHERE o.event='broker_reconciliation' AND e.account=? AND json_extract(o.payload,'$.recorded_execution_state') NOT IN ('unknown','submitting') AND json_extract(o.payload,'$.recorded_protection_state') <> 'unknown'",
            (account,),
        ).fetchone()[0]
    return OperationalEvidence(
        account,
        unresolved[0],
        age(unresolved[1]),
        exports[0],
        age(exports[1]),
        account_reconciled,
        execution_reconciled,
        at.isoformat(),
    )
