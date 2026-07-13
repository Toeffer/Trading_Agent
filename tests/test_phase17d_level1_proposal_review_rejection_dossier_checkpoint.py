"""Tests for Phase 17D — Level 1 Proposal Review and Rejection Dossier Checkpoint."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE17D_DIAGNOSIS,
    _PHASE17D_EXPLICIT_NON_ACTIONS,
    _synthetic_fixture_valid_proposal_reviewable_17d,
    _synthetic_fixture_invalid_schema_rejected_17d,
    _synthetic_fixture_disallowed_instrument_rejected_17d,
    _synthetic_fixture_data_quality_rejected_17d,
    _synthetic_fixture_no_trade_gate_rejected_17d,
    _synthetic_fixture_missing_evidence_hash_rejected_17d,
    _synthetic_fixture_read_only_invariant_17d,
    _synthetic_fixture_deterministic_17d,
    _synthetic_fixture_fresh_clone_execution_17d,
    _generate_synthetic_ohlc_bars,
    _generate_proposal_packet,
    _review_proposal_dossier,
    _phase17d_no_go,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


class TestSyntheticFixtures17D:

    def test_valid_proposal_reviewable_passes(self):
        c = _synthetic_fixture_valid_proposal_reviewable_17d()
        assert c["passed"], f"Valid proposal REVIEWABLE case failed: {c}"
        assert c["human_decision_state"] == "REVIEWABLE"
        assert c["rejection_count"] == 0

    def test_invalid_schema_rejected_passes(self):
        c = _synthetic_fixture_invalid_schema_rejected_17d()
        assert c["passed"], f"Invalid schema REJECTED case failed: {c}"
        assert c["human_decision_state"] == "REJECTED"
        assert c["decision_is_rejected"] is True
        assert c["has_schema_rejection"] is True

    def test_disallowed_instrument_rejected_passes(self):
        c = _synthetic_fixture_disallowed_instrument_rejected_17d()
        assert c["passed"], f"Disallowed instrument REJECTED case failed: {c}"
        assert c["human_decision_state"] == "REJECTED"
        assert c["has_allowlist_rejection"] is True

    def test_data_quality_rejected_passes(self):
        c = _synthetic_fixture_data_quality_rejected_17d()
        assert c["passed"], f"Data quality REJECTED case failed: {c}"
        assert c["human_decision_state"] == "REJECTED"
        assert c["has_data_quality_rejection"] is True

    def test_no_trade_gate_rejected_passes(self):
        c = _synthetic_fixture_no_trade_gate_rejected_17d()
        assert c["passed"], f"No-trade gate REJECTED case failed: {c}"
        assert c["human_decision_state"] == "REJECTED"
        assert c["has_no_trade_rejection"] is True

    def test_missing_evidence_hash_rejected_passes(self):
        c = _synthetic_fixture_missing_evidence_hash_rejected_17d()
        assert c["passed"], f"Missing evidence hash REJECTED case failed: {c}"
        assert c["human_decision_state"] == "REJECTED"
        assert c["has_evidence_hash_rejection"] is True

    def test_read_only_invariant_passes(self):
        c = _synthetic_fixture_read_only_invariant_17d()
        assert c["passed"], f"Read-only invariant case failed: {c}"
        assert c["source_clean"] is True

    def test_deterministic_passes(self):
        c = _synthetic_fixture_deterministic_17d()
        assert c["passed"], f"Deterministic case failed: {c}"
        assert c["same_decision_state"] is True
        assert c["same_rejection_count"] is True
        assert c["same_rejection_checks"] is True

    def test_fresh_clone_execution_passes(self):
        c = _synthetic_fixture_fresh_clone_execution_17d()
        assert c["passed"], f"Fresh-clone execution case failed: {c}"
        assert c["no_home_references"] is True
        assert c["runs_without_home"] is True


class TestReviewDossier:

    def test_review_proposal_dossier_has_all_sections(self):
        """Dossier must contain all required sections."""
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        required_sections = [
            "dossier_id", "timestamp", "proposal_identity",
            "evidence_hash_review", "data_quality_assessment",
            "signal_thesis_review", "risk_envelope_review",
            "sizing_review", "no_trade_checklist_review",
            "bracket_stop_review", "advisory_boundary_review",
            "acceptance_blockers", "rejection_reasons",
            "human_decision_state", "immutable_evidence",
            "schema_validation", "strategy_compliance",
            "evidence_hash",
        ]
        for section in required_sections:
            assert section in dossier, f"Missing dossier section: {section}"

    def test_review_proposal_dossier_evidence_hash_valid(self):
        """Dossier must have a valid SHA-256 evidence hash."""
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        eh = dossier.get("evidence_hash", "")
        assert len(eh) == 64
        assert all(c in "0123456789abcdef" for c in eh)

    def test_review_proposal_dossier_deterministic(self):
        """Identical inputs must produce identical dossiers."""
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier1 = _review_proposal_dossier(proposal)
        dossier2 = _review_proposal_dossier(proposal)
        assert dossier1["human_decision_state"] == dossier2["human_decision_state"]
        assert dossier1["rejection_count"] == dossier2["rejection_count"]
        assert dossier1["evidence_hash"] == dossier2["evidence_hash"]
        assert [r["check"] for r in dossier1["rejection_reasons"]] == [r["check"] for r in dossier2["rejection_reasons"]]

    def test_review_proposal_dossier_reviewable_has_no_rejections(self):
        """A valid proposal must produce REVIEWABLE with zero rejections."""
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        assert dossier["human_decision_state"] == "REVIEWABLE"
        assert dossier["rejection_count"] == 0
        assert len(dossier["rejection_reasons"]) == 0

    def test_review_proposal_dossier_rejected_has_rejection_reasons(self):
        """A rejected proposal must have populated rejection_reasons."""
        bars = _generate_synthetic_ohlc_bars("TSLA", 30)
        proposal = _generate_proposal_packet("TSLA", bars)
        dossier = _review_proposal_dossier(proposal)
        assert dossier["human_decision_state"] == "REJECTED"
        assert dossier["rejection_count"] > 0
        assert len(dossier["rejection_reasons"]) > 0
        # Must have a rejection for allowlist
        assert any("allowlist" in r["check"] for r in dossier["rejection_reasons"])

    def test_review_proposal_dossier_acceptance_blockers_structured(self):
        """Acceptance blockers must be properly structured."""
        bars = _generate_synthetic_ohlc_bars("TSLA", 30)
        proposal = _generate_proposal_packet("TSLA", bars)
        dossier = _review_proposal_dossier(proposal)
        blockers = dossier.get("acceptance_blockers", [])
        assert len(blockers) > 0
        for blocker in blockers:
            assert "blocker" in blocker
            assert "detail" in blocker

    def test_review_proposal_dossier_all_allowed_symbols_reviewable(self):
        """All 4 allowed symbols must produce REVIEWABLE."""
        for symbol in ["AAPL", "META", "NVDA", "AMD"]:
            bars = _generate_synthetic_ohlc_bars(symbol, 30)
            proposal = _generate_proposal_packet(symbol, bars)
            dossier = _review_proposal_dossier(proposal)
            assert dossier["human_decision_state"] == "REVIEWABLE", \
                f"{symbol} should be REVIEWABLE but got {dossier['human_decision_state']}"
            assert dossier["rejection_count"] == 0, f"{symbol} has unexpected rejections"

    def test_review_proposal_dossier_disallowed_symbols_rejected(self):
        """Disallowed symbols must produce REJECTED."""
        for symbol in ["TSLA", "GOOG", "BTC", "ETH", "SPY"]:
            bars = _generate_synthetic_ohlc_bars(symbol, 30)
            proposal = _generate_proposal_packet(symbol, bars)
            dossier = _review_proposal_dossier(proposal)
            assert dossier["human_decision_state"] == "REJECTED", \
                f"{symbol} should be REJECTED but got {dossier['human_decision_state']}"

    def test_review_proposal_dossier_data_quality_fail_rejected(self):
        """A proposal with data quality FAIL must be REJECTED."""
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        proposal["data_quality"] = dict(proposal["data_quality"])
        proposal["data_quality"]["overall"] = "FAIL"
        dossier = _review_proposal_dossier(proposal)
        assert dossier["human_decision_state"] == "REJECTED"
        assert any("data_quality" in r["check"] for r in dossier["rejection_reasons"])

    def test_review_proposal_dossier_no_trade_fail_rejected(self):
        """A proposal with no-trade checklist FAIL must be REJECTED."""
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        proposal["no_trade_checklist"] = dict(proposal["no_trade_checklist"])
        proposal["no_trade_checklist"]["overall"] = "FAIL"
        dossier = _review_proposal_dossier(proposal)
        assert dossier["human_decision_state"] == "REJECTED"
        assert any("no_trade" in r["check"] for r in dossier["rejection_reasons"])

    def test_review_proposal_dossier_missing_evidence_hash_rejected(self):
        """A proposal missing evidence hash must be REJECTED."""
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        proposal["evidence_hash"] = ""
        dossier = _review_proposal_dossier(proposal)
        assert dossier["human_decision_state"] == "REJECTED"
        assert any("evidence_hash" in r["check"] for r in dossier["rejection_reasons"])

    def test_review_proposal_dossier_missing_required_fields_rejected(self):
        """A proposal with missing required fields must be REJECTED."""
        bad_proposal = {
            "proposal_id": "prop-bad-001",
            "symbol": "UNKNOWN",
            "side": "UNKNOWN",
            "rejection_reasons": [],
        }
        dossier = _review_proposal_dossier(bad_proposal)
        assert dossier["human_decision_state"] == "REJECTED"
        assert len(dossier["schema_validation"]["missing_fields"]) > 0

    def test_review_proposal_dossier_immutable_evidence_references(self):
        """Dossier must contain immutable evidence references."""
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        ie = dossier.get("immutable_evidence", {})
        assert "proposal_evidence_hash" in ie
        assert "dossier_evidence_hash" in ie
        assert "strategy_version_ref" in ie
        assert "docs/strategy_v1.md" in ie["strategy_version_ref"]

    def test_review_proposal_dossier_severity_hard_block(self):
        """All rejection reasons for hard failures must be HARD_BLOCK severity."""
        bars = _generate_synthetic_ohlc_bars("TSLA", 30)
        proposal = _generate_proposal_packet("TSLA", bars)
        dossier = _review_proposal_dossier(proposal)
        for r in dossier["rejection_reasons"]:
            assert r.get("severity") == "HARD_BLOCK", \
                f"Rejection for {r['check']} has non-HARD_BLOCK severity: {r.get('severity')}"


class TestDossierNoForbiddenAccess:

    def test_review_function_has_no_order_endpoints(self):
        """_review_proposal_dossier must not contain /order references."""
        import inspect
        src = inspect.getsource(_review_proposal_dossier)
        for pat in ["/order", "/connect", "h1_token", "H1_TOKEN", "X-H1-Token"]:
            assert pat not in src, f"Forbidden pattern in _review_proposal_dossier: {pat}"

    def test_review_function_has_no_trade_window(self):
        """_review_proposal_dossier must not reference trade-window."""
        import inspect
        src = inspect.getsource(_review_proposal_dossier)
        assert "ibkr-trade-window" not in src

    def test_review_function_has_no_sudo(self):
        """_review_proposal_dossier must not contain sudo."""
        import inspect
        src = inspect.getsource(_review_proposal_dossier)
        assert "sudo" not in src

    def test_review_function_has_no_home_path_ref(self):
        """_review_proposal_dossier must not reference $HOME or Path.home()."""
        import inspect
        src = inspect.getsource(_review_proposal_dossier)
        assert "Path.home()" not in src
        assert "~/.openclaw" not in src
        assert "OPENCLAW_DIR" not in src


class TestPhase17DConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE17D_DIAGNOSIS["ready"] == "level1_proposal_review_rejection_dossier_ok"

    def test_diagnosis_dict_has_all_required_keys(self):
        required = [
            "ready", "git_worktree_dirty", "bridge_unreachable",
            "runtime_not_connected", "mode_not_paper", "read_only_not_true",
            "allow_orders_not_false", "endpoints_not_ok", "positions_not_flat",
            "guard_state_not_clean", "kpi_not_hold_system_locked",
            "governance_docs_missing",
            "reviewable_case_failed",
            "invalid_schema_rejected_case_failed",
            "disallowed_instrument_rejected_case_failed",
            "data_quality_rejected_case_failed",
            "no_trade_gate_rejected_case_failed",
            "missing_evidence_hash_rejected_case_failed",
            "read_only_invariant_case_failed",
            "deterministic_case_failed",
            "fresh_clone_case_failed",
            "unknown",
        ]
        for k in required:
            assert k in _PHASE17D_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_explicit_non_actions_contains_protections(self):
        na = _PHASE17D_EXPLICIT_NON_ACTIONS
        assert any("/order" in s for s in na)
        assert any("h1_token" in s.lower() or "H1" in s for s in na)
        assert any("advisory" in s.lower() for s in na)
        assert any("/connect" in s for s in na)
        assert any("ibkr-trade-window" in s for s in na)

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase17d_no_go(
            "test-id", ts,
            {"branch": "test", "commit": "abc", "tag": "v1", "worktree_clean": False},
            "test_diagnosis", ["action 1"],
        )
        assert result["diagnosis"] == "test_diagnosis"
        assert result["severity"] == "NO_GO"
        assert result["no_order_endpoint_called"] is True
        assert result["no_broker_mutation"] is True
        assert result["no_connect_called"] is True
        assert result["no_h1_token_used"] is True


class TestPhase17DCLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-proposal-review-rejection-dossier-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_json_output_valid(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-proposal-review-rejection-dossier-checkpoint", "--json"],
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
             "level1-proposal-review-rejection-dossier-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        required = [
            "diagnosis", "severity", "git",
            "runtime_connected", "mode", "read_only", "allow_orders",
            "endpoints_ok", "positions_flat", "guard_state_clean",
            "kpi_hold_only_system_locked",
            "governance_docs_present",
            "reviewable_case_passed",
            "invalid_schema_rejected_case_passed",
            "disallowed_instrument_rejected_case_passed",
            "data_quality_rejected_case_passed",
            "no_trade_gate_rejected_case_passed",
            "missing_evidence_hash_rejected_case_passed",
            "read_only_invariant_case_passed",
            "deterministic_case_passed",
            "fresh_clone_case_passed",
            "no_order_endpoint_called", "no_broker_mutation",
            "no_connect_called", "artifact_created",
        ]
        for field in required:
            assert field in data, f"Missing field: {field}"
        # canonical_dossier only present when diagnosis is OK
        if data.get("diagnosis") == _PHASE17D_DIAGNOSIS["ready"]:
            assert "canonical_dossier" in data
            assert data["canonical_dossier"] is not None

    def test_cli_alias_phase17d_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "phase17d-proposal-review-rejection-dossier-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

    def test_cli_alias_short_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "proposal-review-rejection-dossier-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

    def test_deterministic_diagnosis_on_repeat_run(self):
        """Running twice should produce consistent diagnosis structure."""
        result1 = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-proposal-review-rejection-dossier-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data1 = json.loads(result1.stdout)
        result2 = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-proposal-review-rejection-dossier-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data2 = json.loads(result2.stdout)
        assert data1["diagnosis"] == data2["diagnosis"], \
            f"Non-deterministic diagnosis: {data1['diagnosis']} vs {data2['diagnosis']}"

    def test_canonical_dossier_populated(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-proposal-review-rejection-dossier-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        if data.get("diagnosis") == _PHASE17D_DIAGNOSIS["ready"]:
            cd = data.get("canonical_dossier")
            assert cd is not None, "canonical_dossier should be populated when OK"
            assert "dossier_id" in cd
            assert "human_decision_state" in cd
            assert "evidence_hash" in cd


class TestPhase17DReadOnlyInvariants:

    def test_no_h1_token_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_proposal_review_rejection_dossier_checkpoint
        src = inspect.getsource(_run_level1_proposal_review_rejection_dossier_checkpoint)
        for pat in ["X-H1-Token", "H1_TOKEN_PATH", "/etc/ibkr-bridge/h1_token"]:
            assert pat not in src, f"Forbidden pattern: {pat}"

    def test_no_order_endpoints_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_proposal_review_rejection_dossier_checkpoint
        src = inspect.getsource(_run_level1_proposal_review_rejection_dossier_checkpoint)
        assert "/order" not in src

    def test_no_connect_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_proposal_review_rejection_dossier_checkpoint
        src = inspect.getsource(_run_level1_proposal_review_rejection_dossier_checkpoint)
        assert "/connect" not in src

    def test_no_trade_window_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_proposal_review_rejection_dossier_checkpoint
        src = inspect.getsource(_run_level1_proposal_review_rejection_dossier_checkpoint)
        assert "ibkr-trade-window" not in src

    def test_no_sudo_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_proposal_review_rejection_dossier_checkpoint
        src = inspect.getsource(_run_level1_proposal_review_rejection_dossier_checkpoint)
        assert "sudo" not in src


class TestFreshCloneHomeIndependence:

    def test_fresh_clone_with_empty_home(self):
        """Simulate fresh-clone execution: the review function should not need HOME."""
        import os
        import tempfile
        # Save original HOME
        orig_home = os.environ.get("HOME", "")
        tmpdir = tempfile.mkdtemp()
        try:
            os.environ["HOME"] = tmpdir
            # The review function must not depend on HOME or ~/.openclaw
            from ibkr_operator import _generate_synthetic_ohlc_bars, _generate_proposal_packet, _review_proposal_dossier
            bars = _generate_synthetic_ohlc_bars("AAPL", 30)
            proposal = _generate_proposal_packet("AAPL", bars)
            dossier = _review_proposal_dossier(proposal)
            assert dossier is not None
            assert "dossier_id" in dossier
            assert dossier["human_decision_state"] == "REVIEWABLE"
        finally:
            os.environ["HOME"] = orig_home
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_generate_proposal_packet_with_empty_home(self):
        """verify the proposal generation also works with empty HOME."""
        import os
        import tempfile
        import shutil
        orig_home = os.environ.get("HOME", "")
        tmpdir = tempfile.mkdtemp()
        try:
            os.environ["HOME"] = tmpdir
            from ibkr_operator import _generate_synthetic_ohlc_bars, _generate_proposal_packet
            bars = _generate_synthetic_ohlc_bars("AAPL", 30)
            proposal = _generate_proposal_packet("AAPL", bars)
            assert proposal is not None
            assert proposal.get("symbol") == "AAPL"
        finally:
            os.environ["HOME"] = orig_home
            shutil.rmtree(tmpdir, ignore_errors=True)
