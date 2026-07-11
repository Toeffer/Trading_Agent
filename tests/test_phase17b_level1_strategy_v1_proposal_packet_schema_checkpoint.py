"""Tests for Phase 17B — Level 1 Strategy v1 Proposal Packet Schema Checkpoint."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE17B_DIAGNOSIS,
    _PHASE17B_EXPLICIT_NON_ACTIONS,
    _synthetic_fixture_valid_proposal_packet,
    _synthetic_fixture_missing_strategy_ref,
    _synthetic_fixture_disallowed_instrument,
    _synthetic_fixture_missing_data_quality,
    _synthetic_fixture_missing_no_trade_checklist_17b,
    _synthetic_fixture_missing_risk_sizing,
    _synthetic_fixture_missing_stop_bracket,
    _synthetic_fixture_missing_advisory_boundary_17b,
    _synthetic_fixture_read_only_invariant_17b,
    _phase17b_no_go,
    _verify_proposal_packet_docs,
    _PROPOSAL_PACKET_DOC_PATH,
    _PROPOSAL_PACKET_SCHEMA_PATH,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


class TestSyntheticFixtures17B:

    def test_synthetic_valid_packet_passes(self):
        c = _synthetic_fixture_valid_proposal_packet()
        assert c["passed"], f"Valid packet case failed: {c}"
        assert c["all_required_fields"] is True
        assert c["symbol_allowed"] is True

    def test_synthetic_missing_strategy_ref_fails(self):
        c = _synthetic_fixture_missing_strategy_ref()
        assert c["passed"], f"Missing strategy ref case failed: {c}"
        assert c["strategy_ref_missing"] is True

    def test_synthetic_disallowed_instrument_fails(self):
        c = _synthetic_fixture_disallowed_instrument()
        assert c["passed"], f"Disallowed instrument case failed: {c}"
        assert c["symbol_not_allowed"] is True

    def test_synthetic_missing_data_quality_fails(self):
        c = _synthetic_fixture_missing_data_quality()
        assert c["passed"], f"Missing data quality case failed: {c}"
        assert c["data_quality_missing"] is True

    def test_synthetic_missing_no_trade_checklist_fails(self):
        c = _synthetic_fixture_missing_no_trade_checklist_17b()
        assert c["passed"], f"Missing no-trade checklist case failed: {c}"
        assert c["no_trade_checklist_missing"] is True

    def test_synthetic_missing_risk_sizing_fails(self):
        c = _synthetic_fixture_missing_risk_sizing()
        assert c["passed"], f"Missing risk/sizing case failed: {c}"
        assert c["risk_missing"] is True
        assert c["sizing_missing"] is True

    def test_synthetic_missing_stop_bracket_fails(self):
        c = _synthetic_fixture_missing_stop_bracket()
        assert c["passed"], f"Missing stop/bracket case failed: {c}"
        assert c["stop_missing"] is True
        assert c["bracket_missing"] is True

    def test_synthetic_missing_advisory_boundary_fails(self):
        c = _synthetic_fixture_missing_advisory_boundary_17b()
        assert c["passed"], f"Missing advisory boundary case failed: {c}"
        assert c["advisory_missing"] is True
        assert c["broker_boundary_missing"] is True

    def test_synthetic_read_only_invariant_passes(self):
        c = _synthetic_fixture_read_only_invariant_17b()
        assert c["passed"], f"Read-only invariant case failed: {c}"
        assert c["source_clean"] is True


class TestPhase17BConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE17B_DIAGNOSIS["ready"] == "level1_strategy_v1_proposal_packet_schema_ok"

    def test_diagnosis_dict_has_all_required_keys(self):
        required = [
            "ready", "git_worktree_dirty", "bridge_unreachable",
            "runtime_not_connected", "mode_not_paper", "read_only_not_true",
            "allow_orders_not_false", "endpoints_not_ok", "positions_not_flat",
            "guard_state_not_clean", "kpi_not_hold_system_locked",
            "proposal_packet_doc_missing", "proposal_packet_schema_missing",
            "strategy_v1_ref_not_required", "proposal_id_not_required",
            "timestamp_not_required", "instrument_not_required",
            "allowed_instrument_check_not_required", "signal_thesis_not_required",
            "signal_inputs_not_required", "data_quality_not_required",
            "no_trade_checklist_not_required", "risk_envelope_check_not_required",
            "sizing_not_required", "daily_trade_count_not_required",
            "daily_loss_not_required", "stop_exit_not_required",
            "bracket_simulation_not_required", "advisory_boundary_not_required",
            "broker_boundary_not_required", "human_review_not_required",
            "rejection_reasons_not_required", "evidence_hash_not_required",
            "synthetic_valid_packet_failed", "synthetic_missing_strategy_ref_failed",
            "synthetic_disallowed_instrument_failed", "synthetic_missing_data_quality_failed",
            "synthetic_missing_no_trade_checklist_failed", "synthetic_missing_risk_sizing_failed",
            "synthetic_missing_stop_bracket_failed", "synthetic_missing_advisory_boundary_failed",
            "synthetic_read_only_invariant_failed", "unknown",
        ]
        for k in required:
            assert k in _PHASE17B_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_explicit_non_actions_contains_proposal_protection(self):
        na = _PHASE17B_EXPLICIT_NON_ACTIONS
        assert any("~/.openclaw" in s for s in na)
        assert any("raw H1 token file" in s or "H1 token" in s for s in na)
        assert any("proposal" in s.lower() for s in na)


class TestProposalPacketDocs:

    def test_doc_verification_returns_structured(self):
        c = _verify_proposal_packet_docs()
        assert "proposal_packet_doc_present" in c
        assert "proposal_packet_schema_present" in c

    def test_doc_md_exists(self):
        assert _PROPOSAL_PACKET_DOC_PATH.exists(), f"Missing: {_PROPOSAL_PACKET_DOC_PATH}"

    def test_schema_json_exists(self):
        assert _PROPOSAL_PACKET_SCHEMA_PATH.exists(), f"Missing: {_PROPOSAL_PACKET_SCHEMA_PATH}"

    def test_schema_json_is_valid_json(self):
        content = _PROPOSAL_PACKET_SCHEMA_PATH.read_text()
        schema = json.loads(content)
        assert "required" in schema
        assert "properties" in schema
        req = schema["required"]
        assert "proposal_id" in req
        assert "symbol" in req
        assert "strategy_version" in req
        assert "signal_thesis" in req
        assert "data_quality" in req
        assert "rejection_reasons" in req
        assert "evidence_hash" in req

    def test_doc_md_references_schema(self):
        content = _PROPOSAL_PACKET_DOC_PATH.read_text()
        assert "schema.json" in content or "JSON Schema" in content

    def test_doc_md_has_required_fields_table(self):
        content = _PROPOSAL_PACKET_DOC_PATH.read_text()
        required_terms = ["proposal_id", "strategy_version", "symbol", "signal_thesis",
                          "data_quality", "rejection_reasons", "evidence_hash"]
        for term in required_terms:
            assert term in content, f"Missing term in doc: {term}"

    def test_doc_md_has_advisory_boundary(self):
        content = _PROPOSAL_PACKET_DOC_PATH.read_text()
        assert "advisory-only" in content.lower() or "Advisory-Only" in content

    def test_doc_md_has_broker_execution_boundary(self):
        content = _PROPOSAL_PACKET_DOC_PATH.read_text()
        assert "broker execution" in content.lower() or "Broker Execution" in content


class TestPhase17BCLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-strategy-v1-proposal-packet-schema-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_json_output_valid(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-strategy-v1-proposal-packet-schema-checkpoint", "--json"],
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
             "level1-strategy-v1-proposal-packet-schema-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        required = [
            "diagnosis", "severity", "git",
            "runtime_connected", "mode", "read_only", "allow_orders",
            "endpoints_ok", "positions_flat", "guard_state_clean",
            "kpi_hold_only_system_locked",
            "proposal_packet_doc_present", "proposal_packet_schema_present",
            "strategy_v1_reference_required", "proposal_id_required",
            "timestamp_required", "instrument_required",
            "allowed_instrument_check_required", "signal_thesis_required",
            "signal_inputs_required", "data_quality_evidence_required",
            "no_trade_checklist_required", "risk_envelope_check_required",
            "sizing_calculation_required", "daily_trade_count_check_required",
            "daily_loss_check_required", "stop_exit_plan_required",
            "bracket_simulation_required", "advisory_only_boundary_required",
            "broker_execution_boundary_required", "human_review_checklist_required",
            "rejection_reasons_required", "evidence_hash_required",
            "no_order_endpoint_called", "no_broker_mutation", "artifact_created",
        ]
        for field in required:
            assert field in data, f"Missing field: {field}"


class TestPhase17BNoGo:

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase17b_no_go(
            "test-id", ts,
            {"branch": "test", "commit": "abc", "tag": "v1", "worktree_clean": False},
            "test_diagnosis", ["action 1"],
        )
        assert result["diagnosis"] == "test_diagnosis"
        assert result["severity"] == "NO_GO"
        assert result["no_order_endpoint_called"] is True
        assert result["no_broker_mutation"] is True


class TestPhase17BReadOnlyInvariants:

    def test_no_h1_token_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_strategy_v1_proposal_packet_schema_checkpoint
        src = inspect.getsource(_run_level1_strategy_v1_proposal_packet_schema_checkpoint)
        for pat in ["X-H1-Token", "H1_TOKEN_PATH", "/etc/ibkr-bridge/h1_token"]:
            assert pat not in src, f"Forbidden pattern: {pat}"

    def test_no_order_endpoints_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_strategy_v1_proposal_packet_schema_checkpoint
        src = inspect.getsource(_run_level1_strategy_v1_proposal_packet_schema_checkpoint)
        assert "/order" not in src

    def test_no_trade_window_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_strategy_v1_proposal_packet_schema_checkpoint
        src = inspect.getsource(_run_level1_strategy_v1_proposal_packet_schema_checkpoint)
        assert "ibkr-trade-window" not in src
