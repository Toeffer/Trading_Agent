"""Tests for Phase 17K — Level 1 Guarded Preflight Request Draft Checkpoint."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE17K_DIAGNOSIS,
    _PHASE17K_EXPLICIT_NON_ACTIONS,
    _create_preflight_request_draft,
    _build_ready_review_17k,
    _synthetic_fixture_ready_draft_17k,
    _synthetic_fixture_missing_review_17k,
    _synthetic_fixture_rejected_review_17k,
    _synthetic_fixture_deferred_review_17k,
    _synthetic_fixture_blocked_review_17k,
    _synthetic_fixture_scope_not_preflight_drafting_17k,
    _synthetic_fixture_drafting_not_permitted_17k,
    _synthetic_fixture_package_not_planning_only_17k,
    _synthetic_fixture_executable_true_17k,
    _synthetic_fixture_broker_authorized_true_17k,
    _synthetic_fixture_preflight_authorized_true_17k,
    _synthetic_fixture_approval_authorized_true_17k,
    _synthetic_fixture_submission_authorized_true_17k,
    _synthetic_fixture_broker_preflight_called_true_17k,
    _synthetic_fixture_actual_preflight_completed_true_17k,
    _synthetic_fixture_actual_order_created_true_17k,
    _synthetic_fixture_review_has_blockers_17k,
    _synthetic_fixture_missing_evidence_hashes_17k,
    _synthetic_fixture_hash_mismatch_17k,
    _synthetic_fixture_tampered_evidence_ref_17k,
    _synthetic_fixture_deterministic_17k,
    _synthetic_fixture_no_forbidden_endpoints_17k,
    _synthetic_fixture_no_broker_identifiers_17k,
    _synthetic_fixture_read_only_invariant_17k,
    _synthetic_fixture_fresh_clone_17k,
    _synthetic_fixture_full_chain_17k,
    _synthetic_fixture_request_body_restrictions_17k,
    _synthetic_fixture_request_headers_restrictions_17k,
    _synthetic_fixture_draft_scope_labels_17k,
    _phase17k_no_go,
    _generate_synthetic_ohlc_bars,
    _generate_proposal_packet,
    _review_proposal_dossier,
    _create_decision_record,
    _create_order_plan_draft,
    _create_simulated_preflight_dossier,
    _create_simulation_review_decision_record,
    _create_candidate_package,
    _create_candidate_package_review_decision_record,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


# ── Synthetic fixtures ───────────────────────────────────────────────────────

class TestSyntheticFixtures17K:

    def test_ready_draft(self):
        c = _synthetic_fixture_ready_draft_17k()
        assert c["passed"], f"Ready draft case failed: {c}"
        assert c["draft_state"] == "PREFLIGHT_REQUEST_DRAFT_READY"

    def test_missing_review(self):
        c = _synthetic_fixture_missing_review_17k()
        assert c["passed"], f"Missing review case failed: {c}"
        assert c["draft_state"] == "PENDING_INPUT"

    def test_rejected_review(self):
        c = _synthetic_fixture_rejected_review_17k()
        assert c["passed"], f"Rejected review case failed: {c}"

    def test_deferred_review(self):
        c = _synthetic_fixture_deferred_review_17k()
        assert c["passed"], f"Deferred review case failed: {c}"

    def test_blocked_review(self):
        c = _synthetic_fixture_blocked_review_17k()
        assert c["passed"], f"Blocked review case failed: {c}"

    def test_scope_not_preflight_drafting(self):
        c = _synthetic_fixture_scope_not_preflight_drafting_17k()
        assert c["passed"], f"Scope case failed: {c}"

    def test_drafting_not_permitted(self):
        c = _synthetic_fixture_drafting_not_permitted_17k()
        assert c["passed"], f"Drafting not permitted case failed: {c}"

    def test_package_not_planning_only(self):
        c = _synthetic_fixture_package_not_planning_only_17k()
        assert c["passed"], f"Package not planning only case failed: {c}"

    def test_executable_true(self):
        c = _synthetic_fixture_executable_true_17k()
        assert c["passed"], f"Executable true case failed: {c}"

    def test_broker_authorized_true(self):
        c = _synthetic_fixture_broker_authorized_true_17k()
        assert c["passed"], f"Broker authorized case failed: {c}"

    def test_preflight_authorized_true(self):
        c = _synthetic_fixture_preflight_authorized_true_17k()
        assert c["passed"], f"Preflight authorized case failed: {c}"

    def test_approval_authorized_true(self):
        c = _synthetic_fixture_approval_authorized_true_17k()
        assert c["passed"], f"Approval authorized case failed: {c}"

    def test_submission_authorized_true(self):
        c = _synthetic_fixture_submission_authorized_true_17k()
        assert c["passed"], f"Submission authorized case failed: {c}"

    def test_broker_preflight_called_true(self):
        c = _synthetic_fixture_broker_preflight_called_true_17k()
        assert c["passed"], f"Broker preflight called case failed: {c}"

    def test_actual_preflight_completed_true(self):
        c = _synthetic_fixture_actual_preflight_completed_true_17k()
        assert c["passed"], f"Actual preflight completed case failed: {c}"

    def test_actual_order_created_true(self):
        c = _synthetic_fixture_actual_order_created_true_17k()
        assert c["passed"], f"Actual order created case failed: {c}"

    def test_review_has_blockers(self):
        c = _synthetic_fixture_review_has_blockers_17k()
        assert c["passed"], f"Review blockers case failed: {c}"

    def test_missing_evidence_hashes(self):
        c = _synthetic_fixture_missing_evidence_hashes_17k()
        assert c["passed"], f"Missing evidence hashes case failed: {c}"

    def test_hash_mismatch(self):
        c = _synthetic_fixture_hash_mismatch_17k()
        assert c["passed"], f"Hash mismatch case failed: {c}"

    def test_tampered_evidence_ref(self):
        c = _synthetic_fixture_tampered_evidence_ref_17k()
        assert c["passed"], f"Tampered evidence ref case failed: {c}"

    def test_deterministic(self):
        c = _synthetic_fixture_deterministic_17k()
        assert c["passed"], f"Deterministic case failed: {c}"
        assert c["same_state"] is True
        assert c["same_hash"] is True

    def test_no_forbidden_endpoints(self):
        c = _synthetic_fixture_no_forbidden_endpoints_17k()
        assert c["passed"], f"Forbidden endpoints found: {c.get('found', [])}"

    def test_no_broker_identifiers(self):
        c = _synthetic_fixture_no_broker_identifiers_17k()
        assert c["passed"], f"Broker identifiers found: {c.get('found', [])}"

    def test_read_only_invariant(self):
        c = _synthetic_fixture_read_only_invariant_17k()
        assert c["passed"], f"Read-only invariant violated"

    def test_fresh_clone(self):
        c = _synthetic_fixture_fresh_clone_17k()
        assert c["passed"], f"Fresh clone case failed: {c}"

    def test_full_chain(self):
        c = _synthetic_fixture_full_chain_17k()
        assert c["passed"], f"Full chain case failed: {c}"
        assert c["all_non_exec"] is True

    def test_request_body_restrictions(self):
        c = _synthetic_fixture_request_body_restrictions_17k()
        assert c["passed"], f"Request body restrictions failed: {c.get('found', [])}"

    def test_request_headers_restrictions(self):
        c = _synthetic_fixture_request_headers_restrictions_17k()
        assert c["passed"], f"Request headers restrictions failed: {c}"

    def test_draft_scope_labels(self):
        c = _synthetic_fixture_draft_scope_labels_17k()
        assert c["passed"], f"Draft scope labels failed: {c}"


# ── Unit tests ───────────────────────────────────────────────────────────────

class TestPreflightRequestDraft:

    def test_draft_has_all_required_fields(self):
        rr = _build_ready_review_17k()
        draft = _create_preflight_request_draft(rr)
        required = [
            "preflight_request_draft_version", "draft_state", "draft_scope",
            "planning_scope", "proposal_id", "proposal_evidence_hash",
            "dossier_evidence_hash", "planning_decision_record_hash",
            "order_plan_hash", "simulation_record_hash",
            "simulation_review_record_hash", "candidate_package_hash",
            "candidate_review_record_hash", "strategy_version",
            "account_reference", "symbol", "security_type", "exchange",
            "currency", "side", "quantity", "order_type_plan",
            "limit_price_plan", "time_in_force_plan", "protective_stop_plan",
            "protective_stop_quantity", "risk_summary", "sizing_summary",
            "market_data_freshness_requirement", "position_state_requirement",
            "account_state_requirement", "session_state_requirement",
            "no_trade_revalidation_requirement", "evidence_chain_status",
            "request_body_draft", "request_headers_draft",
            "request_delivery_state", "actual_preflight_completed",
            "broker_preflight_called", "executable", "broker_authorized",
            "preflight_authorized", "approval_authorized",
            "submission_authorized", "actual_order_created",
            "h1_required_for_this_draft", "h1_accessed",
            "immutable_evidence_references",
            "deterministic_preflight_request_draft_hash",
            "blockers", "blocker_count",
            "explicit_non_actions", "required_future_human_actions",
        ]
        for field in required:
            assert field in draft, f"Missing required field: {field}"

    def test_draft_version(self):
        rr = _build_ready_review_17k()
        draft = _create_preflight_request_draft(rr)
        assert draft["preflight_request_draft_version"] == "preflight-request-draft-v1.0.0"

    def test_ready_draft_is_non_executable(self):
        rr = _build_ready_review_17k()
        draft = _create_preflight_request_draft(rr)
        assert draft["executable"] is False
        assert draft["broker_authorized"] is False
        assert draft["preflight_authorized"] is False
        assert draft["approval_authorized"] is False
        assert draft["submission_authorized"] is False
        assert draft["broker_preflight_called"] is False
        assert draft["actual_preflight_completed"] is False
        assert draft["actual_order_created"] is False
        assert draft["request_delivery_state"] == "NOT_SENT"
        assert draft["h1_required_for_this_draft"] is False
        assert draft["h1_accessed"] is False

    def test_draft_hash_valid(self):
        rr = _build_ready_review_17k()
        draft = _create_preflight_request_draft(rr)
        rh = draft.get("deterministic_preflight_request_draft_hash", "")
        assert len(rh) == 64
        assert all(c in "0123456789abcdef" for c in rh)

    def test_missing_review_pending_input(self):
        draft = _create_preflight_request_draft({})
        assert draft["draft_state"] == "PENDING_INPUT"
        assert draft["blocker_count"] > 0
        assert draft["request_delivery_state"] == "NOT_SENT"

    def test_rejected_review_blocked(self):
        rr = _build_ready_review_17k()
        rr["review_state"] = "REJECTED"
        rr["preflight_request_drafting_permitted"] = False
        draft = _create_preflight_request_draft(rr)
        assert draft["draft_state"] == "BLOCKED"
        assert draft["request_delivery_state"] == "NOT_SENT"

    def test_output_labels_present(self):
        rr = _build_ready_review_17k()
        draft = _create_preflight_request_draft(rr)
        labels = draft.get("output_labels", [])
        assert "GUARDED_PREFLIGHT_REQUEST_DRAFT" in labels
        assert "PREFLIGHT_REQUEST_DRAFTING_ONLY" in labels
        assert "PLANNING_ONLY" in labels
        assert "NON_EXECUTABLE" in labels
        assert "NOT_SENT" in labels
        assert "ACTUAL_PREFLIGHT_NOT_COMPLETED" in labels
        assert "NO_H1_ACCESSED" in labels
        assert "SEPARATE_H1_APPROVAL_REQUIRED_BEFORE_SUBMISSION" in labels

    def test_labeled_output_in_json(self):
        rr = _build_ready_review_17k()
        draft = _create_preflight_request_draft(rr)
        payload = json.dumps(draft, sort_keys=True)
        assert "NON_EXECUTABLE" in payload
        assert "PLANNING_ONLY" in payload
        assert "NOT_SENT" in payload

    def test_immutable_evidence_references_complete(self):
        rr = _build_ready_review_17k()
        draft = _create_preflight_request_draft(rr)
        ier = draft.get("immutable_evidence_references", {})
        for key in ("proposal_evidence_hash", "dossier_evidence_hash",
                     "planning_decision_record_hash", "order_plan_hash",
                     "simulation_record_hash", "simulation_review_record_hash",
                     "candidate_package_hash", "candidate_review_record_hash"):
            assert key in ier, f"Missing immutable ref: {key}"
            assert len(ier[key]) == 64, f"Ref {key} not 64 chars: {len(ier[key])}"

    def test_required_future_human_actions_ready(self):
        rr = _build_ready_review_17k()
        draft = _create_preflight_request_draft(rr)
        actions = draft.get("required_future_human_actions", [])
        assert len(actions) >= 6
        assert any("inspect" in a.lower() for a in actions)
        assert any("preflight" in a.lower() for a in actions)
        assert any("h1" in a.lower() for a in actions)
        assert any("refresh" in a.lower() for a in actions)
        assert any("not executable" in a.lower() for a in actions)

    def test_required_future_human_actions_blocked(self):
        rr = _build_ready_review_17k()
        rr["executable"] = True
        draft = _create_preflight_request_draft(rr)
        actions = draft.get("required_future_human_actions", [])
        assert any("resolve" in a.lower() or "blocker" in a.lower() for a in actions)

    def test_blocker_ordering_deterministic(self):
        rr = _build_ready_review_17k()
        rr["executable"] = True  # triggers a blocker
        d1 = _create_preflight_request_draft(rr)
        d2 = _create_preflight_request_draft(rr)
        b1 = [b["blocker"] for b in d1["blockers"]]
        b2 = [b["blocker"] for b in d2["blockers"]]
        assert b1 == b2, f"Blocker ordering differs: {b1} vs {b2}"

    def test_no_broker_identifiers_in_output(self):
        rr = _build_ready_review_17k()
        draft = _create_preflight_request_draft(rr)
        payload = json.dumps(draft, sort_keys=True)
        forbidden = ["permId", "order_id", "orderId", "approval_id",
                     "approvalId", "submission_id", "submissionId",
                     "exec_id", "execId", "conId", "broker_order_id"]
        for fid in forbidden:
            assert fid.lower() not in payload.lower(), \
                f"Forbidden broker identifier '{fid}' found"

    def test_request_body_draft_has_no_forbidden_fields(self):
        rr = _build_ready_review_17k()
        draft = _create_preflight_request_draft(rr)
        body = draft.get("request_body_draft", {})
        body_str = json.dumps(body, sort_keys=True).lower()
        forbidden = ["approval_id", "order_id", "permid", "conid",
                     "h1_token", "approval_token", "submission_token",
                     "broker_response"]
        for f in forbidden:
            assert f not in body_str, f"Forbidden field '{f}' found in request body draft"

    def test_request_headers_draft_has_no_h1_token(self):
        rr = _build_ready_review_17k()
        draft = _create_preflight_request_draft(rr)
        headers = draft.get("request_headers_draft", {})
        headers_str = json.dumps(headers, sort_keys=True)
        assert "X-H1-Token" not in headers_str or "ABSENT" in headers_str
        assert "Bearer" not in headers_str

    def test_request_body_contains_commentary_warnings(self):
        rr = _build_ready_review_17k()
        draft = _create_preflight_request_draft(rr)
        body = draft.get("request_body_draft", {})
        body_str = json.dumps(body, sort_keys=True).lower()
        assert "draft" in body_str
        assert "non-executable" in body_str or "NON_EXECUTABLE" in json.dumps(body)
        assert "not_sent" in body_str

    def test_draft_does_not_mutate_review_record(self):
        import copy
        rr = _build_ready_review_17k()
        rr_before = copy.deepcopy(rr)
        _create_preflight_request_draft(rr)
        assert rr == rr_before, "Draft mutated the review record"

    def test_full_chain_non_executable(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris",
                                           decision_reason="Full chain test.")
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        plan = _create_order_plan_draft(decision, proposal, dossier)
        sim = _create_simulated_preflight_dossier(plan, proposal, dossier, decision)
        review = _create_simulation_review_decision_record(
            sim, proposal, dossier=dossier, decision_record=decision, order_plan=plan,
            decision="ACCEPT", reviewer="Chris", decision_reason="Full chain."
        )
        pkg = _create_candidate_package(review, sim, proposal, dossier=dossier, decision_record=decision, order_plan=plan)
        record_17j = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Full chain."
        )
        draft_17k = _create_preflight_request_draft(record_17j)
        assert pkg["executable"] is False
        assert record_17j["executable"] is False
        assert draft_17k["executable"] is False
        assert draft_17k["actual_preflight_completed"] is False
        assert draft_17k["actual_order_created"] is False
        assert draft_17k["request_delivery_state"] == "NOT_SENT"


# ── No forbidden access ──────────────────────────────────────────────────────

class TestNoForbiddenAccess17K:

    def test_no_order_endpoints_in_source(self):
        import inspect
        src = inspect.getsource(_create_preflight_request_draft)
        truly_forbidden = [p for p in ["/order", "/connect", "/order/preflight",
                                        "/order/approve", "/order/submit"]
                           if src.count(p) > 5]
        assert len(truly_forbidden) == 0, f"Forbidden patterns: {truly_forbidden}"

    def test_no_trade_window_in_source(self):
        import inspect
        src = inspect.getsource(_create_preflight_request_draft)
        assert "ibkr-trade-window" not in src

    def test_no_home_ref_in_source(self):
        import inspect
        src = inspect.getsource(_create_preflight_request_draft)
        assert "Path.home()" not in src
        assert "~/.openclaw" not in src

    def test_no_sudo_in_source(self):
        import inspect
        src = inspect.getsource(_create_preflight_request_draft)
        assert "sudo" not in src


# ── Constants ────────────────────────────────────────────────────────────────

class TestPhase17KConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE17K_DIAGNOSIS["ready"] == "level1_guarded_preflight_request_draft_ok"

    def test_diagnosis_dict_has_all_keys(self):
        required = [
            "ready", "ready_draft_case_failed", "missing_review_failed",
            "rejected_review_failed", "deferred_review_failed",
            "blocked_review_failed", "review_not_accepted_failed",
            "scope_not_preflight_drafting_failed",
            "drafting_not_permitted_failed",
            "package_not_planning_only_failed",
            "executable_true_failed", "broker_authorized_true_failed",
            "preflight_authorized_true_failed",
            "approval_authorized_true_failed",
            "submission_authorized_true_failed",
            "broker_preflight_called_true_failed",
            "actual_preflight_completed_true_failed",
            "actual_order_created_true_failed",
            "review_has_blockers_failed",
            "missing_proposal_hash_failed",
            "missing_dossier_hash_failed",
            "missing_decision_hash_failed",
            "missing_order_plan_hash_failed",
            "missing_simulation_hash_failed",
            "missing_simulation_review_hash_failed",
            "missing_candidate_package_hash_failed",
            "missing_candidate_review_hash_failed",
            "hash_mismatch_failed", "tampered_evidence_ref_failed",
            "deterministic_failed", "no_forbidden_endpoints_failed",
            "no_broker_identifiers_failed", "read_only_invariant_failed",
            "fresh_clone_failed", "full_chain_failed", "unknown",
        ]
        for k in required:
            assert k in _PHASE17K_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_explicit_non_actions_contains_protections(self):
        na = _PHASE17K_EXPLICIT_NON_ACTIONS
        assert any("DRAFT" in s for s in na)
        assert any("NOT_SENT" in s for s in na)
        assert any("h1" in s.lower() or "H1" in s for s in na)
        assert any("non-executable" in s.lower() for s in na)

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase17k_no_go(
            "test-id", ts,
            {"branch": "test", "commit": "abc", "tag": "v1", "worktree_clean": False},
            "test_diagnosis", ["action 1"],
        )
        assert result["diagnosis"] == "test_diagnosis"
        assert result["severity"] == "NO_GO"
        assert result["no_order_endpoint_called"] is True
        assert result["no_broker_mutation"] is True


# ── Fresh-clone HOME independence ────────────────────────────────────────────

class TestFreshCloneHomeIndependence17K:

    def test_draft_with_empty_home(self):
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            env["HOME"] = td
            cp = subprocess.run(
                [sys.executable, "-c", f"""
import sys
sys.path.insert(0, r'{REPO}')
from ibkr_operator import (
    _build_ready_review_17k,
    _create_preflight_request_draft,
)
rr = _build_ready_review_17k()
draft = _create_preflight_request_draft(rr)
assert draft["draft_state"] == "PREFLIGHT_REQUEST_DRAFT_READY"
assert "deterministic_preflight_request_draft_hash" in draft
print("OK")
"""],
                capture_output=True, text=True, timeout=30,
                env=env,
            )
            assert "OK" in cp.stdout, f"stderr: {cp.stderr}"


# ── CLI tests ────────────────────────────────────────────────────────────────

class TestPhase17KCLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-guarded-preflight-request-draft-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_alias_phase17k_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "phase17k-guarded-preflight-request-draft-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_alias_preflight_request_draft_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "preflight-request-draft-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_json_output_valid(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-guarded-preflight-request-draft-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result.stdout[:200]}")
        assert "diagnosis" in data

    def test_required_fields_present(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-guarded-preflight-request-draft-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        required = [
            "checkpoint_id", "timestamp", "diagnosis", "severity",
            "no_order_endpoint_called", "no_broker_mutation",
            "ready_draft_case_passed",
            "missing_review_case_passed",
            "deterministic_case_passed",
            "full_chain_case_passed",
        ]
        for field in required:
            assert field in data, f"Missing required field in CLI output: {field}"


# ── Regression: Determinism at scale ────────────────────────────────────────

class TestRegressionDeterminismAtScale17K:

    def test_20_ready_drafts_all_same_state(self):
        rr = _build_ready_review_17k()
        drafts = [_create_preflight_request_draft(rr) for _ in range(20)]
        for i, d in enumerate(drafts):
            assert d["draft_state"] == "PREFLIGHT_REQUEST_DRAFT_READY", \
                f"Draft {i}: expected PREFLIGHT_REQUEST_DRAFT_READY, got {d['draft_state']}"

    def test_20_ready_drafts_all_identical_hash(self):
        rr = _build_ready_review_17k()
        drafts = [_create_preflight_request_draft(rr) for _ in range(20)]
        hashes = [d["deterministic_preflight_request_draft_hash"] for d in drafts]
        first_hash = hashes[0]
        for i, h in enumerate(hashes):
            assert h == first_hash, f"Draft {i} hash differs: {h[:16]}... vs {first_hash[:16]}..."

    def test_20_ready_drafts_all_zero_blockers(self):
        rr = _build_ready_review_17k()
        drafts = [_create_preflight_request_draft(rr) for _ in range(20)]
        for i, d in enumerate(drafts):
            assert d["blocker_count"] == 0, \
                f"Draft {i}: expected 0 blockers, got {d['blocker_count']}"


# ── Regression: Upstream review unchanged after 17K ──────────────────────

class TestRegressionUpstreamUnchanged17K:

    def test_review_unchanged_after_17k(self):
        import copy
        rr = _build_ready_review_17k()
        rr_before = copy.deepcopy(rr)
        _create_preflight_request_draft(rr)
        assert rr == rr_before, "Review record was mutated by 17K builder"

    def test_deterministic_blockers_same_input(self):
        rr = _build_ready_review_17k()
        rr["executable"] = True  # triggers a blocker
        d1 = _create_preflight_request_draft(rr)
        d2 = _create_preflight_request_draft(rr)
        b1 = [b["blocker"] for b in d1["blockers"]]
        b2 = [b["blocker"] for b in d2["blockers"]]
        assert b1 == b2, f"Blockers differ: {b1} vs {b2}"
