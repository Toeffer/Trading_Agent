"""Safety invariant #12 + strict preflight — regression tests.

Two deviations found in a repo review (2026-09-07):

1. Invariant #12 (CLAUDE.md §3.12, RUNBOOK §L9) says every pending or
   approved-but-unsubmitted approval is invalid after a bridge restart.
   guard._load_active_approvals() did the opposite: it restored them from
   active-approvals.json at startup, and both submit validators
   (guard.submit_order, bridge._validate_approval_for_submit) accepted an
   approval that existed only on disk. An approval ruled up to 300 s before
   a restart came back live in the new process.

2. CLAUDE.md §5 says preflight is strict (unknown fields rejected).
   guard._validate_preflight_request() does reject them, but
   bridge.PreflightRequest used Pydantic's default extra="ignore", so an
   unknown field was silently dropped before the guard saw it.

Level 1 / portable: no IBKR, no ~/.openclaw, no H1 token. The bridge-level
behavioral checks run the bridge in a subprocess with HOME redirected to a
temp dir and are skipped if fastapi is not installed (CI installs it).
"""

import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import guard  # noqa: E402

BRIDGE_SOURCE = (REPO / "bridge.py").read_text()
GUARD_SOURCE = (REPO / "guard.py").read_text()


def _ts(seconds_from_now: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _record(aid: str, status: str, expires_in: int = 200) -> dict:
    return {
        "approval_id": aid,
        "status": status,
        "expires_at_utc": _ts(expires_in),
        "created_at_utc": _ts(-10),
        "proposal": {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1, "orderType": "MKT"},
    }


@pytest.fixture
def isolated_guard(tmp_path, monkeypatch):
    """Point every guard file at tmp_path and start from empty in-memory state."""
    monkeypatch.setattr(guard, "ACTIVE_APPROVALS_PATH", tmp_path / "active-approvals.json")
    monkeypatch.setattr(guard, "APPROVAL_RECORDS_PATH", tmp_path / "approval-records.jsonl")
    monkeypatch.setattr(guard, "SUBMITTED_APPROVALS_PATH", tmp_path / "submitted-approvals.json")
    monkeypatch.setattr(guard, "GUARD_EVENTS_PATH", tmp_path / "guard-events.jsonl")
    monkeypatch.setattr(guard, "GUARD_STATE_PATH", tmp_path / "guard-state.json")
    monkeypatch.setattr(guard, "_submitted_approvals", set())
    guard._active_approvals.clear()
    yield tmp_path
    guard._active_approvals.clear()


def _events(tmp_path: Path) -> list[dict]:
    p = tmp_path / "guard-events.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def _records(tmp_path: Path) -> list[dict]:
    p = tmp_path / "approval-records.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


# ── Invariant #12: startup invalidates, never restores ─────────────────────


class TestStartupInvalidation:
    def test_live_pending_and_approved_are_invalidated_not_restored(self, isolated_guard):
        tmp = isolated_guard
        snapshot = {
            "aprv_pending": _record("aprv_pending", "pending"),
            "aprv_approved": _record("aprv_approved", "approved"),
        }
        (tmp / "active-approvals.json").write_text(json.dumps(snapshot))
        (tmp / "approval-records.jsonl").write_text(
            json.dumps(_record("aprv_pending", "pending")) + "\n"
            + json.dumps(_record("aprv_approved", "pending")) + "\n"
        )

        result = guard._load_active_approvals()

        # Nothing comes back live.
        assert result == {}
        assert guard._active_approvals == {}
        # Snapshot reset so nothing on disk still reads as active.
        assert json.loads((tmp / "active-approvals.json").read_text()) == {}
        # Each was recorded as expired with the restart reason.
        tail = {r["approval_id"]: r for r in _records(tmp)[2:]}
        assert set(tail) == {"aprv_pending", "aprv_approved"}
        for r in tail.values():
            assert r["status"] == "expired"
            assert r["ruled_by"] == "system"
            assert r["expiry_reason"] == "bridge_restart"
            assert r["was_live_at_restart"] is True
        # Snapshot (rewritten on every mutation) wins over the append-only log.
        assert tail["aprv_approved"]["previous_status"] == "approved"
        assert tail["aprv_pending"]["previous_status"] == "pending"
        # One guard event per invalidated approval.
        evs = [e for e in _events(tmp) if e.get("event_type") == "approval_invalidated_restart"]
        assert {e["approval_id"] for e in evs} == {"aprv_pending", "aprv_approved"}

    def test_submitted_denied_and_expired_records_are_left_alone(self, isolated_guard, monkeypatch):
        tmp = isolated_guard
        monkeypatch.setattr(guard, "_submitted_approvals", {"aprv_done"})
        snapshot = {
            "aprv_done": _record("aprv_done", "approved"),
            "aprv_denied": _record("aprv_denied", "denied"),
            "aprv_old": _record("aprv_old", "expired"),
        }
        (tmp / "active-approvals.json").write_text(json.dumps(snapshot))

        guard._load_active_approvals()

        assert guard._active_approvals == {}
        assert _records(tmp) == []
        assert [e for e in _events(tmp) if e.get("event_type") == "approval_invalidated_restart"] == []

    def test_no_files_is_a_clean_noop(self, isolated_guard):
        tmp = isolated_guard
        assert guard._load_active_approvals() == {}
        assert not (tmp / "approval-records.jsonl").exists()
        assert not (tmp / "active-approvals.json").exists()

    def test_startup_reconcile_still_calls_it(self):
        # reconcile_approvals_on_startup() is the only production caller; the
        # name is kept so that call site and existing test patches keep working.
        assert GUARD_SOURCE.count("_load_active_approvals()") >= 2
        assert "into _active_approvals so that submit_order finds them after restart" not in GUARD_SOURCE


# ── Invariant #12: submit refuses approvals that exist only on disk ─────────


class TestSubmitRefusesDiskOnlyApproval:
    def test_guard_submit_order_returns_not_found_before_kill_switches(self, isolated_guard):
        tmp = isolated_guard
        (tmp / "approval-records.jsonl").write_text(json.dumps(_record("aprv_disk", "approved")) + "\n")
        calls = []

        result = guard.submit_order(
            "aprv_disk",
            order_provider=lambda rec: calls.append(rec) or {"success": True, "order_id": 1},
        )

        assert result["submitted"] is False
        assert result["code"] == "NOT_FOUND"
        assert "restart" in result["error"]
        assert "invariant #12" in result["error"]
        assert calls == []

    def test_guard_submit_order_still_reports_expired_and_submitted_codes(self, isolated_guard, monkeypatch):
        tmp = isolated_guard
        (tmp / "approval-records.jsonl").write_text(
            json.dumps(_record("aprv_stale", "approved", expires_in=-5)) + "\n"
            + json.dumps(_record("aprv_sent", "approved")) + "\n"
        )
        monkeypatch.setattr(guard, "_submitted_approvals", {"aprv_sent"})
        assert guard.submit_order("aprv_stale")["code"] == "EXPIRED"
        assert guard.submit_order("aprv_sent")["code"] == "ALREADY_SUBMITTED"

    def test_bridge_validator_has_matching_check(self):
        # bridge._validate_approval_for_submit runs before guard.submit_order;
        # it must not promote a disk-only record either.
        assert "from_disk = True" in BRIDGE_SOURCE
        assert 'if from_disk and status in ("pending", "approved"):' in BRIDGE_SOURCE


# ── Strict preflight at the HTTP boundary ──────────────────────────────────


class TestStrictPreflightModel:
    def test_preflight_request_keeps_unknown_fields_for_the_guard(self):
        # extra="ignore" (Pydantic default) silently dropped unknown keys
        # before guard._validate_preflight_request() could reject them.
        start = BRIDGE_SOURCE.index("class PreflightRequest(BaseModel):")
        body = BRIDGE_SOURCE[start:start + 1200]
        assert 'model_config = ConfigDict(extra="allow")' in body
        assert "from pydantic import BaseModel, ConfigDict" in BRIDGE_SOURCE

    def test_guard_rejects_unknown_field(self):
        r = guard.run_preflight({"symbol": "AAPL", "action": "BUY", "totalQuantity": 1, "whatIf": True})
        assert r["passed"] is False
        assert "Unknown request field 'whatIf'" in r["error"]


# ── Bridge-level behavioral checks (subprocess, isolated HOME) ─────────────

RULES_YAML = textwrap.dedent("""
    rules_version: "1.3-draft"
    enforced: false
    max_position_notional: {value: 5}
    max_risk_per_trade: {value: 2}
    max_total_exposure: {value: 30}
    max_trades_per_day: {value: 2}
    loss_halts: {daily_pct: 1, weekly_pct: 3}
    initial_stop_loss: {atr_multiplier: 2, atr_period: 14, absolute_floor_percent: 5}
    symbol_allowlist: {mode: explicit_list, allow: [AAPL, MSFT]}
    symbol_sectors: {AAPL: INFORMATION_TECHNOLOGY, MSFT: INFORMATION_TECHNOLOGY}
    max_positions_per_sector: {value: 1}
    manual_approval: {enabled: true, timeout_seconds: 300}
    order_endpoint_gate: {}
    guard_state: {file: guard-state.json}
    preflight: {strict_mode: true, response_type: validation_results_only}
    logging: {file: guard-events.jsonl}
""")

BRIDGE_PROBE = textwrap.dedent("""
    import hashlib, json, os, sys
    from datetime import datetime, timedelta, timezone
    home = os.environ["HOME"]
    oc = os.path.join(home, ".openclaw")
    exp = (datetime.now(timezone.utc) + timedelta(seconds=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec = {"approval_id": "aprv_prerestart", "status": "approved", "expires_at_utc": exp,
           "proposal": {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1, "orderType": "MKT"}}
    with open(os.path.join(oc, "active-approvals.json"), "w") as f:
        json.dump({"aprv_prerestart": rec}, f)
    sys.path.insert(0, os.environ["REPO"])
    import guard, bridge
    from fastapi.testclient import TestClient
    c = TestClient(bridge.app)
    out = {
        "in_memory_after_start": sorted(guard._active_approvals),
        "snapshot_after_start": json.load(open(os.path.join(oc, "active-approvals.json"))),
        "validator": bridge._validate_approval_for_submit("aprv_prerestart"),
        "records_after_start": [json.loads(l) for l in open(os.path.join(oc, "approval-records.jsonl"))
                                if l.strip()],
        "submit": c.post("/order/submit", json={"approval_id": "aprv_prerestart"},
                         headers={"X-H1-Token": "testtoken"}).json(),
        "approve": c.post("/order/approve", json={"approval_id": "aprv_prerestart", "decision": "approve"},
                          headers={"X-H1-Token": "testtoken"}).status_code,
        "preflight_unknown": c.post("/order/preflight",
                                    json={"symbol": "AAPL", "action": "BUY", "totalQuantity": 1, "whatIf": True}).json(),
        "preflight_known_shape": c.post("/order/preflight",
                                        json={"symbol": "TSLA", "action": "BUY", "totalQuantity": 1}).json(),
    }
    print("PROBE_JSON " + json.dumps(out))
""")


@pytest.fixture(scope="module")
def bridge_probe(tmp_path_factory):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    home = tmp_path_factory.mktemp("home")
    oc = home / ".openclaw"
    (oc / "risk-rules").mkdir(parents=True)
    (oc / "risk-rules" / "paper-trading-rules.yaml").write_text(RULES_YAML)
    import hashlib
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("IBKR_")},
        "HOME": str(home),
        "REPO": str(REPO),
        "IBKR_ALLOW_ORDERS": "false",
        "H1_APPROVAL_TOKEN_HASH": hashlib.sha256(b"testtoken").hexdigest(),
    }
    proc = subprocess.run(
        [sys.executable, "-c", BRIDGE_PROBE], env=env, cwd=str(home),
        capture_output=True, text=True, timeout=180,
    )
    lines = [l for l in proc.stdout.splitlines() if l.startswith("PROBE_JSON ")]
    assert lines, f"bridge probe produced no result\nstdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-3000:]}"
    return json.loads(lines[-1][len("PROBE_JSON "):])


class TestBridgeAfterRestart:
    def test_approval_on_disk_is_not_live_after_restart(self, bridge_probe):
        assert bridge_probe["in_memory_after_start"] == []
        assert bridge_probe["snapshot_after_start"] == {}

    def test_on_disk_copy_was_expired_with_restart_reason(self, bridge_probe):
        recs = [r for r in bridge_probe["records_after_start"] if r["approval_id"] == "aprv_prerestart"]
        assert recs and recs[-1]["status"] == "expired"
        assert recs[-1]["expiry_reason"] == "bridge_restart"
        assert recs[-1]["previous_status"] == "approved"

    def test_bridge_validator_refuses_it(self, bridge_probe):
        # Startup already expired the on-disk copy, so the validator reports
        # EXPIRED; NOT_FOUND is the answer if the log were missing. Either
        # way it never returns None (= "valid, go on to the kill switches").
        v = bridge_probe["validator"]
        assert v is not None
        assert v["code"] in ("EXPIRED", "NOT_FOUND")

    def test_submit_and_approve_refuse_it_even_with_h1_token(self, bridge_probe):
        assert bridge_probe["submit"]["submitted"] is False
        assert bridge_probe["submit"]["code"] in ("EXPIRED", "NOT_FOUND")
        assert bridge_probe["approve"] == 404


class TestBridgeStrictPreflight:
    def test_unknown_field_is_rejected_at_the_endpoint(self, bridge_probe):
        r = bridge_probe["preflight_unknown"]
        assert r["passed"] is False
        assert "Unknown request field 'whatIf'" in r["error"]

    def test_known_fields_still_reach_the_gates(self, bridge_probe):
        r = bridge_probe["preflight_known_shape"]
        assert r["passed"] is False
        assert r.get("gate") == "allowlist"
