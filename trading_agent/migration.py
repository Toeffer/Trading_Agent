"""Offline, conservative migration of legacy records; never sends orders."""

import hashlib
from datetime import date
import json
from pathlib import Path
from typing import Any

from trading_agent.domain import canonical, content_hash, utcnow
from trading_agent.persistence import ExecutionStore, StateConflict


def migrate_legacy(source: Path, store: ExecutionStore, account: str) -> dict[str, Any]:
    if not source.is_dir() or not account:
        raise ValueError("Explicit legacy source directory and account are required")
    names = (
        "guard-state.json",
        "active-approvals.json",
        "approval-records.jsonl",
        "submitted-approvals.json",
        "guard-events.jsonl",
    )
    files = {
        name: (source / name).read_bytes()
        for name in names
        if (source / name).is_file()
    }
    if "guard-state.json" not in files:
        raise ValueError("Legacy guard-state.json is required")
    decoded: dict[str, Any] = {}
    for name, data in files.items():
        text = data.decode("utf-8")
        decoded[name] = (
            [json.loads(line) for line in text.splitlines() if line.strip()]
            if name.endswith(".jsonl")
            else json.loads(text)
        )
    existing = store.approvals()
    if existing:
        raise StateConflict("MIGRATION_REQUIRES_NO_ACTIVE_APPROVALS")
    risk = decoded["guard-state.json"]
    if not isinstance(risk, dict):
        raise ValueError("INVALID_LEGACY_STATE")
    date.fromisoformat(risk["trade_date"])
    date.fromisoformat(risk["week_start_date"])
    if type(risk.get("daily_trade_count")) is not int or risk["daily_trade_count"] < 0:
        raise ValueError("INVALID_IMPORTED_DAILY_COUNT")
    if any(
        type(risk.get(key)) is not bool
        for key in ("daily_halt_active", "weekly_halt_active")
    ):
        raise ValueError("INVALID_IMPORTED_HALT")
    # Validate before importing anything; loss baselines may never default to 0.
    from trading_agent.domain import money

    for key in ("day_start_nl_eur", "week_start_nl_eur"):
        if money(risk.get(key)) <= 0:
            raise ValueError("MISSING_RISK_BASELINE")
    imported = 0
    quarantined = 0
    approvals = decoded.get("approval-records.jsonl", [])
    events = decoded.get("guard-events.jsonl", [])
    if not isinstance(approvals, list) or not isinstance(events, list):
        raise ValueError("INVALID_LEGACY_HISTORY")

    def related(entry: Any) -> list[dict[str, Any]]:
        identity = entry.get("approval_id") if isinstance(entry, dict) else entry
        return [
            r
            for r in [*approvals, *events]
            if isinstance(r, dict) and identity and r.get("approval_id") == identity
        ]

    with store.transaction() as db:
        if db.execute("SELECT 1 FROM executions LIMIT 1").fetchone():
            raise StateConflict("MIGRATION_REQUIRES_NO_EXECUTION_HISTORY")
        if db.execute(
            "SELECT 1 FROM account_risk WHERE account=?", (account,)
        ).fetchone():
            raise StateConflict("MIGRATION_ALREADY_APPLIED")
        for name, content in decoded.items():
            digest = hashlib.sha256(files[name]).hexdigest()
            db.execute(
                "INSERT INTO legacy_records VALUES(?,?,?)",
                (str(source / name), digest, canonical(content)),
            )
            imported += 1
            # Legacy evidence lacks a reliably reserved execution reference.
            # Quarantine every historical submission, including apparently
            # acknowledged ones; broker reconciliation decides its disposition.
            entries = content if isinstance(content, list) else []
            for entry in entries:
                if name == "submitted-approvals.json" or (
                    isinstance(entry, dict)
                    and entry.get("event_type")
                    in ("order_submitted", "order_unconfirmed", "order_failed")
                ):
                    record = {
                        "source": name,
                        "record": entry,
                        "related_records": related(entry),
                    }
                    result = db.execute(
                        "INSERT OR IGNORE INTO legacy_quarantine(record_hash,account,payload) VALUES(?,?,?)",
                        (content_hash(record), account, canonical(record)),
                    )
                    quarantined += result.rowcount
        db.execute("INSERT INTO account_risk VALUES(?,?)", (account, canonical(risk)))
        store._event(
            db,
            "legacy_import",
            {
                "source": str(source),
                "account": account,
                "files": imported,
                "quarantined": quarantined,
                "unused_approvals": "expired; retained only as historical records",
            },
        )
    return {
        "imported_files": imported,
        "quarantined_records": quarantined,
        "orders_enabled": False,
        "imported_at": utcnow().isoformat(),
    }
