from datetime import timedelta
import hashlib
import json

import pytest

from trading_agent.domain import utcnow
from trading_agent.migration import migrate_legacy
from trading_agent.persistence import ExecutionStore, StateConflict
from test_execution_regressions import plan


def legacy(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    today = utcnow().date()
    risk = {"trade_date": today.isoformat(), "week_start_date": (today - timedelta(days=today.weekday())).isoformat(),
            "day_start_nl_eur": "100000", "week_start_nl_eur": "101000", "daily_trade_count": 1,
            "daily_halt_active": False, "weekly_halt_active": True}
    (source / "guard-state.json").write_bytes(json.dumps(risk).encode("utf-8") + b"\r\n")
    (source / "submitted-approvals.json").write_bytes(b'["old-approval"]\r\n')
    return source


def test_migration_preserves_bytes_provenance_and_quarantines(tmp_path):
    source = legacy(tmp_path)
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    store = ExecutionStore(tmp_path / "state.sqlite3")
    result = migrate_legacy(source, store, "PAPER_TEST")
    assert result["quarantined_records"] == 1
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before
    with store.connection() as db:
        hashes = {row[0] for row in db.execute("SELECT record_hash FROM legacy_records")}
    assert hashes == {hashlib.sha256(value).hexdigest() for value in before.values()}
    assert store.risk_state("PAPER_TEST")["weekly_halt_active"] is True
    aid = store.create_pending(plan())["approval_id"]
    store.rule(aid, "approved", authorized=True)
    with pytest.raises(StateConflict, match="UNRESOLVED_LEGACY"):
        store.reserve(aid, authorized=True)


def test_invalid_legacy_baseline_imports_nothing(tmp_path):
    source = legacy(tmp_path)
    state = json.loads((source / "guard-state.json").read_bytes())
    state["day_start_nl_eur"] = "NaN"
    (source / "guard-state.json").write_text(json.dumps(state), encoding="utf-8")
    store = ExecutionStore(tmp_path / "state.sqlite3")
    with pytest.raises(ValueError):
        migrate_legacy(source, store, "PAPER_TEST")
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM legacy_records").fetchone()[0] == 0
