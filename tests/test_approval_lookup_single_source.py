"""Approval lookup — single source of truth (2026-09-07).

bridge._validate_approval_for_submit() and guard.submit_order() each carried
their own copy of "find the approval record and decide whether it may be
submitted": a first-match scan of approval-records.jsonl plus an expiry /
status ladder. Two copies drifted (that is how invariant #12 was violated),
and "first match" on an append-only log reads the original creation line
even after a ruling or a restart invalidation was appended.

Now: guard.find_approval_record() (memory first; on disk the LAST matching
line wins) and guard.validate_approval_for_submit() (the one ladder). The
bridge function is a thin wrapper; submit_order() calls the same function.

Level 1 / portable: guard.py only, tmp paths, no IBKR.
"""

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import guard  # noqa: E402

BRIDGE_SOURCE = (REPO / "bridge.py").read_text()
GUARD_SOURCE = (REPO / "guard.py").read_text()


def _ts(seconds_from_now: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(aid: str, status: str, expires_in: int = 200) -> dict:
    return {
        "approval_id": aid, "status": status, "expires_at_utc": _ts(expires_in),
        "proposal": {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1, "orderType": "MKT"},
    }


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "APPROVAL_RECORDS_PATH", tmp_path / "approval-records.jsonl")
    monkeypatch.setattr(guard, "SUBMITTED_APPROVALS_PATH", tmp_path / "submitted-approvals.json")
    monkeypatch.setattr(guard, "ACTIVE_APPROVALS_PATH", tmp_path / "active-approvals.json")
    monkeypatch.setattr(guard, "GUARD_EVENTS_PATH", tmp_path / "guard-events.jsonl")
    monkeypatch.setattr(guard, "_submitted_approvals", set())
    guard._active_approvals.clear()
    yield tmp_path
    guard._active_approvals.clear()


def _log(tmp_path, *records):
    (tmp_path / "approval-records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))


class TestFindApprovalRecord:
    def test_memory_wins_over_disk(self, isolated):
        _log(isolated, _record("a1", "denied"))
        guard._active_approvals["a1"] = _record("a1", "approved")
        rec, source = guard.find_approval_record("a1")
        assert source == "memory" and rec["status"] == "approved"

    def test_disk_last_line_wins(self, isolated):
        _log(isolated, _record("a1", "pending"), _record("a1", "expired"), _record("other", "approved"))
        rec, source = guard.find_approval_record("a1")
        assert source == "disk" and rec["status"] == "expired"

    def test_missing_is_none(self, isolated):
        assert guard.find_approval_record("nope") == (None, "none")

    def test_malformed_lines_are_skipped(self, isolated):
        (isolated / "approval-records.jsonl").write_text("not json\n" + json.dumps(_record("a1", "approved")) + "\n")
        rec, source = guard.find_approval_record("a1")
        assert source == "disk" and rec["status"] == "approved"


class TestValidateApprovalForSubmit:
    def test_live_approved_is_submittable(self, isolated):
        guard._active_approvals["a1"] = _record("a1", "approved")
        rec, err = guard.validate_approval_for_submit("a1")
        assert err is None and rec["approval_id"] == "a1"

    def test_live_pending_is_not_approved(self, isolated):
        guard._active_approvals["a1"] = _record("a1", "pending")
        rec, err = guard.validate_approval_for_submit("a1")
        assert rec is None and err["code"] == "NOT_APPROVED"

    def test_live_but_past_expiry(self, isolated):
        guard._active_approvals["a1"] = _record("a1", "approved", expires_in=-1)
        assert guard.validate_approval_for_submit("a1")[1]["code"] == "EXPIRED"

    def test_already_submitted(self, isolated, monkeypatch):
        guard._active_approvals["a1"] = _record("a1", "approved")
        monkeypatch.setattr(guard, "_submitted_approvals", {"a1"})
        assert guard.validate_approval_for_submit("a1")[1]["code"] == "ALREADY_SUBMITTED"

    def test_denied_on_disk_reports_denied(self, isolated):
        _log(isolated, _record("a1", "approved"), _record("a1", "denied"))
        err = guard.validate_approval_for_submit("a1")[1]
        assert err["code"] == "NOT_FOUND" and "denied" in err["error"]

    def test_restart_invalidated_line_reports_expired(self, isolated):
        # What the log looks like after guard._load_active_approvals() ran at
        # startup: creation line, then the appended bridge_restart expiry.
        _log(isolated, _record("a1", "approved"), {**_record("a1", "expired"), "expiry_reason": "bridge_restart"})
        assert guard.validate_approval_for_submit("a1")[1]["code"] == "EXPIRED"

    def test_disk_only_approved_is_never_submittable(self, isolated):
        _log(isolated, _record("a1", "approved"))
        rec, err = guard.validate_approval_for_submit("a1")
        assert rec is None and err["code"] == "NOT_FOUND"
        assert "invariant #12" in err["error"]

    def test_unknown_id(self, isolated):
        assert guard.validate_approval_for_submit("nope")[1]["code"] == "NOT_FOUND"


class TestBothCallersUseIt:
    def test_submit_order_uses_shared_ladder(self, isolated):
        _log(isolated, _record("a1", "approved"))
        calls = []
        r = guard.submit_order("a1", order_provider=lambda rec: calls.append(rec) or {"success": True, "order_id": 1})
        assert r["code"] == "NOT_FOUND" and "invariant #12" in r["error"] and calls == []

    def test_submit_order_source_calls_it_and_has_no_private_scan(self):
        start = GUARD_SOURCE.index("\ndef submit_order(")
        body = GUARD_SOURCE[start:GUARD_SOURCE.index("\ndef ", start + 1)]
        assert "validate_approval_for_submit(approval_id)" in body
        assert "APPROVAL_RECORDS_PATH" not in body

    def test_bridge_validator_is_a_thin_wrapper(self):
        start = BRIDGE_SOURCE.index("def _validate_approval_for_submit(")
        body = BRIDGE_SOURCE[start:BRIDGE_SOURCE.index('@app.post("/order/submit")', start)]
        assert "validate_approval_for_submit(approval_id)" in body
        assert "APPROVAL_RECORDS_PATH" not in body
        assert "expires_at_utc" not in body

    def test_find_record_scan_has_no_early_break(self):
        start = GUARD_SOURCE.index("\ndef find_approval_record(")
        body = GUARD_SOURCE[start:GUARD_SOURCE.index("\ndef ", start + 1)]
        assert not re.search(r"^\s+break\s*$", body, re.M)
