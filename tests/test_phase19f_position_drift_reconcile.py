"""Tests for Phase 19F — Position-Drift Reconciliation for Unconfirmed-Order Mismatches.

Sibling to tests/test_step15o_guard_state_reconcile.py — same mocking
convention (mock urllib.request.urlopen per-URL, mock monitor.load_events,
redirect repair/output directories to tmp_path).

All tests are read-only against the live system. No broker mutation, no
order endpoints, no H1 token usage, no autonomy level changes. The only
file writes are to a tmp_path-redirected position-reconciliations.json
and its audit-export directory.
"""

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_urlopen_response(payload: dict):
    """Build a context-manager mock matching urllib.request.urlopen()'s
    return value: .read().decode() -> JSON string."""
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    cm.__exit__.return_value = False
    return cm


def _make_urlopen_side_effect(drift: dict, health: dict, open_orders: dict):
    """Route urllib.request.urlopen() to a canned response by URL suffix,
    matching how _run_position_drift_reconcile calls three different
    bridge endpoints via the same urllib.request.urlopen name."""
    def _side_effect(req, timeout=5.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.endswith("/monitor/positions/drift"):
            return _mock_urlopen_response(drift)
        if url.endswith("/health"):
            return _mock_urlopen_response(health)
        if url.endswith("/monitor/open-orders"):
            return _mock_urlopen_response(open_orders)
        raise AssertionError(f"Unexpected URL in test: {url}")
    return _side_effect


def _aapl_drift(expected_qty=1.0, actual_qty=0, unconfirmed_ids=None):
    unconfirmed_ids = unconfirmed_ids if unconfirmed_ids is not None else ["aprv_d39f1f84-b8fd-4d6a-9a99-0485b677dd4f"]
    return {
        "drift_detected": True,
        "expected_positions": [{"symbol": "AAPL", "expected_qty": expected_qty}],
        "actual_positions": [],
        "mismatches": [{"symbol": "AAPL", "expected_qty": expected_qty,
                        "actual_qty": actual_qty, "avgCost": None}],
        "unconfirmed_count": len(unconfirmed_ids),
        "unconfirmed_approval_ids": unconfirmed_ids,
        "drift_detail": "Drift likely caused by unconfirmed (IBKR-unacknowledged) orders",
    }


def _clean_drift():
    return {
        "drift_detected": False,
        "expected_positions": [], "actual_positions": [],
        "mismatches": [], "unconfirmed_count": 0,
        "unconfirmed_approval_ids": [], "drift_detail": None,
    }


_HEALTH_CONNECTED = {"connected": True}
_HEALTH_DISCONNECTED = {"connected": False}
_NO_OPEN_ORDERS = {"open_order_count": 0, "ibkr_order_count": 0}
_SOME_OPEN_ORDERS = {"open_order_count": 2, "ibkr_order_count": 2}

def _make_load_events_side_effect(all_events):
    """Filter by event_type the way monitor.load_events() really does —
    position_drift_check() calls it 2-3 times with different event_types
    in the same call; a flat return_value=... mock would cross-contaminate
    those calls (an order_submitted event would also be "returned" for the
    order_unconfirmed query), so this needs to actually filter."""
    def _side_effect(event_type=None, since_utc=None):
        if event_type is None:
            return list(all_events)
        wanted = set(event_type.split(","))
        return [e for e in all_events if e.get("event_type") in wanted]
    return _side_effect


# Confirmed AAPL BUY (order 36, filled) + the never-acknowledged AAPL SELL
# (order 24, no ibkr_metadata — matches the real "legacy pre-fix" shape in
# monitor.position_drift_check()'s own comment). Raw netting: order 36
# contributes +1 (confirmed filled), order 24 is correctly excluded
# (still-conservative default) → raw expected = +1, matching the real
# AAPL: expected 1.0 seen live tonight.
_AAPL_UNCONFIRMED_EVENT = [
    {
        "event_id": "evt-0036", "event_type": "order_submitted",
        "symbol": "AAPL", "action": "BUY", "totalQuantity": 1,
        "approval_id": "aprv_confirmed_buy_36", "order_id": 36,
        "ibkr_metadata": {"filled": 1, "permId": 551562267},
        "timestamp_utc": "2026-06-03T10:00:00Z",
    },
    {
        "event_id": "evt-0024", "event_type": "order_submitted",
        "symbol": "AAPL", "action": "SELL", "totalQuantity": 1,
        "approval_id": "aprv_d39f1f84-b8fd-4d6a-9a99-0485b677dd4f",
        "order_id": 24, "timestamp_utc": "2026-06-09T10:00:00Z",
    },
]


def _write_approval_records(path, records: dict):
    """Write a minimal approval-records.jsonl: {approval_id: status}."""
    lines = [json.dumps({"approval_id": aid, "status": status}) for aid, status in records.items()]
    path.write_text("\n".join(lines) + ("\n" if lines else ""))


def _base_patches(tmp_path, drift, health, open_orders, events=None, approval_records=None):
    """Common patch set for a single call to _run_position_drift_reconcile.

    approval_records: {approval_id: status} written to a tmp_path-redirected
    approval-records.jsonl. Defaults to empty (no record for any candidate) —
    the same shape as the real aprv_d39f1f84 incident, where an
    order_submitted event existed with no corresponding ruled approval.
    """
    events = events if events is not None else _AAPL_UNCONFIRMED_EVENT
    records_path = tmp_path / "approval-records.jsonl"
    _write_approval_records(records_path, approval_records or {})
    return [
        patch("ibkr_operator._git_metadata", return_value={
            "branch": "test", "commit": "abc123", "tag": "test"}),
        patch("ibkr_operator.urllib.request.urlopen",
              side_effect=_make_urlopen_side_effect(drift, health, open_orders)),
        patch("ibkr_operator._POSITION_DRIFT_REPAIRS_DIR", tmp_path / "position-drift-repairs"),
        patch("monitor.load_events", side_effect=_make_load_events_side_effect(events)),
        patch("ibkr_operator.os.getenv", return_value="false"),
        patch("guard.APPROVAL_RECORDS_PATH", records_path),
    ]


def _run_with_patches(patches, **kwargs):
    from ibkr_operator import _run_position_drift_reconcile
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        return _run_position_drift_reconcile(**kwargs)


# ---------------------------------------------------------------------------
# T1: Command exists and is registered
# ---------------------------------------------------------------------------

class TestCommandExists:
    def test_function_importable(self):
        from ibkr_operator import _run_position_drift_reconcile
        assert callable(_run_position_drift_reconcile)

    def test_aliases_registered(self):
        import subprocess
        for alias in ("position-drift-reconcile", "position-drift-repair", "reconcile-position-drift"):
            r = subprocess.run(
                [sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"), alias, "--help"],
                capture_output=True, text=True, timeout=15,
            )
            assert r.returncode == 0, f"{alias} --help failed: {r.stderr}"


# ---------------------------------------------------------------------------
# T2: Dry-run detects a repairable mismatch
# ---------------------------------------------------------------------------

class TestDryRunDetectsRepairableMismatch:
    def test_mismatch_with_ruled_unconfirmed_evidence_recommends_repair(self, tmp_path):
        # A genuinely approved-and-submitted order that IBKR never
        # acknowledged — the case this tool exists for. Not aprv_d39f1f84
        # (that ID is reserved below for the legacy/never-ruled regression).
        patches = _base_patches(
            tmp_path, _aapl_drift(), _HEALTH_CONNECTED, _NO_OPEN_ORDERS,
            approval_records={"aprv_d39f1f84-b8fd-4d6a-9a99-0485b677dd4f": "approved"},
        )
        result = _run_with_patches(patches, apply_repair=False, confirm_local_state_repair=False)

        assert result["mode"] == "dry_run"
        assert result["drift_detected"] is True
        assert result["repair_recommended"] is True
        assert result["repair_applied"] is False
        r = result["per_symbol_results"][0]
        assert r["symbol"] == "AAPL"
        assert r["qty_delta"] == -1.0
        assert r["candidate_unconfirmed_approval_ids"] == ["aprv_d39f1f84-b8fd-4d6a-9a99-0485b677dd4f"]
        assert r["excluded_unruled_approval_ids"] == []
        assert r["repair_recommended"] is True
        assert r["repair_applied"] is False

    def test_no_mismatch_is_a_noop(self, tmp_path):
        patches = _base_patches(tmp_path, _clean_drift(), _HEALTH_CONNECTED, _NO_OPEN_ORDERS)
        result = _run_with_patches(patches, apply_repair=False, confirm_local_state_repair=False)

        assert result["drift_detected"] is False
        assert result["per_symbol_results"] == []
        assert result["repair_recommended"] is False
        assert result["repair_applied"] is False


# ---------------------------------------------------------------------------
# T3: Refuses to repair an unexplained mismatch
# ---------------------------------------------------------------------------

class TestRefusesNeverRuledCandidateApproval:
    """Regression for the live 2026-08-13 incident: aprv_d39f1f84 has an
    order_submitted event (order_id=24, AAPL SELL) but its own
    approval-records.jsonl entry was never ruled (status="pending",
    ruled_by=None, expired 5 minutes after creation on 2026-06-03). A
    submission without a ruled approval cannot be real fill evidence and
    must not be presented as an ordinary unconfirmed-but-possibly-filled
    candidate."""

    def test_pending_never_ruled_approval_does_not_recommend_repair(self, tmp_path):
        patches = _base_patches(
            tmp_path, _aapl_drift(), _HEALTH_CONNECTED, _NO_OPEN_ORDERS,
            approval_records={"aprv_d39f1f84-b8fd-4d6a-9a99-0485b677dd4f": "pending"},
        )
        result = _run_with_patches(patches, apply_repair=False, confirm_local_state_repair=False)

        r = result["per_symbol_results"][0]
        assert r["repair_recommended"] is False
        assert r["candidate_unconfirmed_approval_ids"] == []
        assert r["excluded_unruled_approval_ids"] == ["aprv_d39f1f84-b8fd-4d6a-9a99-0485b677dd4f"]
        checks = {b["check"] for b in r["blockers"]}
        assert "only_legacy_unruled_evidence" in checks

    def test_missing_approval_record_entirely_does_not_recommend_repair(self, tmp_path):
        # No approval-records.jsonl entry at all for the candidate — same
        # "cannot vouch for this" outcome as an explicitly unruled one.
        patches = _base_patches(
            tmp_path, _aapl_drift(), _HEALTH_CONNECTED, _NO_OPEN_ORDERS,
            approval_records={},
        )
        result = _run_with_patches(patches, apply_repair=False, confirm_local_state_repair=False)

        r = result["per_symbol_results"][0]
        assert r["repair_recommended"] is False
        checks = {b["check"] for b in r["blockers"]}
        assert "only_legacy_unruled_evidence" in checks


class TestRefusesUnexplainedMismatch:
    def test_mismatch_with_no_unconfirmed_evidence_is_blocked(self, tmp_path):
        # Mismatch exists, but no unconfirmed order on record for that symbol —
        # this tool must refuse (an unexplained drift is not its job).
        drift = _aapl_drift(unconfirmed_ids=[])
        patches = _base_patches(tmp_path, drift, _HEALTH_CONNECTED, _NO_OPEN_ORDERS, events=[])
        result = _run_with_patches(patches, apply_repair=False, confirm_local_state_repair=False)

        r = result["per_symbol_results"][0]
        assert r["repair_recommended"] is False
        checks = {b["check"] for b in r["blockers"]}
        assert "no_unconfirmed_evidence" in checks

    def test_unconfirmed_order_for_different_symbol_does_not_count(self, tmp_path):
        # Unconfirmed order exists, but for QQQ, not the AAPL mismatch —
        # must not be treated as explaining the AAPL gap.
        drift = _aapl_drift(unconfirmed_ids=["aprv_other"])
        qqq_event = [{
            "event_id": "evt-0002", "event_type": "order_submitted",
            "symbol": "QQQ", "action": "BUY", "totalQuantity": 5,
            "approval_id": "aprv_other", "order_id": 40,
        }]
        patches = _base_patches(tmp_path, drift, _HEALTH_CONNECTED, _NO_OPEN_ORDERS, events=qqq_event)
        result = _run_with_patches(patches, apply_repair=False, confirm_local_state_repair=False)

        r = result["per_symbol_results"][0]
        assert r["symbol"] == "AAPL"
        assert r["candidate_unconfirmed_approval_ids"] == []
        assert r["repair_recommended"] is False


# ---------------------------------------------------------------------------
# T4: Safety gates block repair
# ---------------------------------------------------------------------------

class TestSafetyGatesBlockRepair:
    def test_ibkr_disconnected_blocks(self, tmp_path):
        patches = _base_patches(tmp_path, _aapl_drift(), _HEALTH_DISCONNECTED, _NO_OPEN_ORDERS)
        result = _run_with_patches(patches, apply_repair=False, confirm_local_state_repair=False)

        r = result["per_symbol_results"][0]
        assert r["repair_recommended"] is False
        checks = {b["check"] for b in r["blockers"]}
        assert "ibkr_not_connected" in checks

    def test_open_orders_block(self, tmp_path):
        patches = _base_patches(tmp_path, _aapl_drift(), _HEALTH_CONNECTED, _SOME_OPEN_ORDERS)
        result = _run_with_patches(patches, apply_repair=False, confirm_local_state_repair=False)

        r = result["per_symbol_results"][0]
        assert r["repair_recommended"] is False
        checks = {b["check"] for b in r["blockers"]}
        assert "open_orders_exist" in checks

    def test_safety_unlocked_blocks(self, tmp_path):
        from ibkr_operator import _run_position_drift_reconcile
        records_path = tmp_path / "approval-records.jsonl"
        _write_approval_records(records_path, {"aprv_d39f1f84-b8fd-4d6a-9a99-0485b677dd4f": "approved"})
        patches_list = [
            patch("ibkr_operator._git_metadata", return_value={
                "branch": "test", "commit": "abc123", "tag": "test"}),
            patch("ibkr_operator.urllib.request.urlopen",
                  side_effect=_make_urlopen_side_effect(_aapl_drift(), _HEALTH_CONNECTED, _NO_OPEN_ORDERS)),
            patch("ibkr_operator._POSITION_DRIFT_REPAIRS_DIR", tmp_path / "position-drift-repairs"),
            patch("monitor.load_events", side_effect=_make_load_events_side_effect(_AAPL_UNCONFIRMED_EVENT)),
            # os.getenv mocked to "true" for every lookup, including
            # IBKR_ALLOW_ORDERS — simulates the kill switch being unlocked.
            patch("ibkr_operator.os.getenv", return_value="true"),
            patch("guard.APPROVAL_RECORDS_PATH", records_path),
        ]
        with patches_list[0], patches_list[1], patches_list[2], patches_list[3], patches_list[4], patches_list[5]:
            result = _run_position_drift_reconcile(apply_repair=False, confirm_local_state_repair=False)

        r = result["per_symbol_results"][0]
        assert r["repair_recommended"] is False
        checks = {b["check"] for b in r["blockers"]}
        assert "safety_unlocked" in checks

    def test_bridge_unreachable_holds_with_no_crash(self, tmp_path):
        with patch("ibkr_operator._git_metadata", return_value={
                "branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator._POSITION_DRIFT_REPAIRS_DIR", tmp_path / "position-drift-repairs"):
            from ibkr_operator import _run_position_drift_reconcile
            result = _run_position_drift_reconcile(apply_repair=False, confirm_local_state_repair=False)

        assert result["repair_recommended"] is False
        assert result["repair_applied"] is False
        checks = {b["check"] for b in result["blockers"]}
        assert "bridge_unreachable" in checks


# ---------------------------------------------------------------------------
# T5: Apply requires confirmation flag
# ---------------------------------------------------------------------------

class TestApplyRequiresConfirmation:
    def test_apply_without_confirmation_is_dry_run(self, tmp_path):
        recon_path = tmp_path / "position-reconciliations.json"
        patches = _base_patches(
            tmp_path, _aapl_drift(), _HEALTH_CONNECTED, _NO_OPEN_ORDERS,
            approval_records={"aprv_d39f1f84-b8fd-4d6a-9a99-0485b677dd4f": "approved"},
        )
        with patch("monitor.POSITION_RECONCILIATIONS_PATH", recon_path):
            result = _run_with_patches(patches, apply_repair=True, confirm_local_state_repair=False)

        assert result["mode"] == "dry_run"
        assert result["repair_applied"] is False
        assert not recon_path.exists()


# ---------------------------------------------------------------------------
# T6: Apply writes the reconciliation and it's honoured by position_drift_check()
# ---------------------------------------------------------------------------

class TestApplyWritesReconciliation:
    def test_apply_writes_file_and_nets_to_zero(self, tmp_path):
        recon_path = tmp_path / "position-reconciliations.json"
        records_path = tmp_path / "approval-records.jsonl"
        _write_approval_records(records_path, {"aprv_d39f1f84-b8fd-4d6a-9a99-0485b677dd4f": "approved"})

        with patch("ibkr_operator._git_metadata", return_value={
                "branch": "test", "commit": "abc123", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_make_urlopen_side_effect(_aapl_drift(), _HEALTH_CONNECTED, _NO_OPEN_ORDERS)), \
             patch("ibkr_operator._POSITION_DRIFT_REPAIRS_DIR", tmp_path / "position-drift-repairs"), \
             patch("monitor.load_events", side_effect=_make_load_events_side_effect(_AAPL_UNCONFIRMED_EVENT)), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("guard.APPROVAL_RECORDS_PATH", records_path), \
             patch("monitor.POSITION_RECONCILIATIONS_PATH", recon_path):
            from ibkr_operator import _run_position_drift_reconcile
            result = _run_position_drift_reconcile(apply_repair=True, confirm_local_state_repair=True)

        assert result["mode"] == "apply"
        assert result["repair_applied"] is True
        assert recon_path.exists()

        data = json.loads(recon_path.read_text())
        assert len(data["reconciliations"]) == 1
        rec = data["reconciliations"][0]
        assert rec["symbol"] == "AAPL"
        assert rec["qty_delta"] == -1.0
        assert rec["associated_unconfirmed_approval_ids"] == ["aprv_d39f1f84-b8fd-4d6a-9a99-0485b677dd4f"]
        # Must not assert the order filled — only that expected was adjusted.
        assert "does not assert" in rec["note"].lower()

        r = result["per_symbol_results"][0]
        assert r["repair_verified"] is True
        assert r["expected_qty_after"] == 0

    def test_reconciliation_is_honoured_by_position_drift_check(self, tmp_path):
        """End-to-end: after a reconciliation is recorded, the general
        position_drift_check() (not just this tool's own re-verify step)
        reflects the adjustment — this is what /monitor/positions/drift
        and therefore the fixed /readiness will read on the next call."""
        recon_path = tmp_path / "position-reconciliations.json"
        recon_path.write_text(json.dumps({
            "schema_version": 1,
            "reconciliations": [{
                "repair_id": "posdrift-repair-test",
                "timestamp_utc": "2026-08-11T15:30:00Z",
                "symbol": "AAPL",
                "qty_delta": -1.0,
                "expected_qty_before": 1.0,
                "actual_qty_at_reconciliation": 0,
                "associated_unconfirmed_approval_ids": ["aprv_d39f1f84-b8fd-4d6a-9a99-0485b677dd4f"],
                "reason": "live_ibkr_ground_truth_reconciliation",
                "note": "Does not assert the associated unconfirmed order(s) filled.",
            }],
        }))

        with patch("monitor.load_events", side_effect=_make_load_events_side_effect(_AAPL_UNCONFIRMED_EVENT)), \
             patch("monitor.POSITION_RECONCILIATIONS_PATH", recon_path):
            from monitor import position_drift_check
            result = position_drift_check()

        # Confirmed BUY (order 36) nets +1.0; unconfirmed SELL (order 24,
        # still correctly excluded from raw netting — the conservative
        # default) contributes nothing. Raw netting = +1.0. The
        # reconciliation delta (-1.0) is what brings expected_positions
        # down to match live IBKR's 0.
        assert result["expected_positions"].get("AAPL", 0) == 0
        assert result["applied_reconciliations"] == [{
            "repair_id": "posdrift-repair-test", "symbol": "AAPL", "qty_delta": -1.0,
        }]

    def test_missing_reconciliations_file_fails_open_to_empty(self, tmp_path):
        """A missing position-reconciliations.json must never crash
        position_drift_check() or fabricate an adjustment."""
        recon_path = tmp_path / "does-not-exist.json"
        with patch("monitor.load_events", return_value=[]), \
             patch("monitor.POSITION_RECONCILIATIONS_PATH", recon_path):
            from monitor import position_drift_check
            result = position_drift_check()

        assert result["applied_reconciliations"] is None

    def test_corrupt_reconciliations_file_fails_open_to_empty(self, tmp_path):
        recon_path = tmp_path / "corrupt.json"
        recon_path.write_text("{not valid json")
        with patch("monitor.load_events", return_value=[]), \
             patch("monitor.POSITION_RECONCILIATIONS_PATH", recon_path):
            from monitor import position_drift_check
            result = position_drift_check()

        assert result["applied_reconciliations"] is None


# ---------------------------------------------------------------------------
# T7: Explicit non-actions and evidence hash present
# ---------------------------------------------------------------------------

class TestExplicitNonActionsAndEvidence:
    def test_result_carries_explicit_non_actions_and_hash(self, tmp_path):
        patches = _base_patches(tmp_path, _aapl_drift(), _HEALTH_CONNECTED, _NO_OPEN_ORDERS)
        result = _run_with_patches(patches, apply_repair=False, confirm_local_state_repair=False)

        assert result["no_broker_mutation"] is True
        assert result["no_order_window_opened"] is True
        assert len(result["evidence_hash"]) == 64  # SHA-256 hex digest
        non_actions_text = " ".join(result["explicit_non_actions"]).lower()
        assert "does not assert" in non_actions_text
        assert "did not read h1 token" in non_actions_text
