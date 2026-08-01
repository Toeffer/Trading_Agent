"""Phase 19A — Level 1 Strategy v1.1 Design Proposal Governance Checkpoint.

Asserts that the Strategy v1.1 proposal and its manifest exist, that the
manifest carries correct governance metadata, that content hashes match the
actual files, and that no execution scope, allowlist, rules, guard, or env
mutation is indicated.

Also verifies the proposal's claims *about the codebase* rather than trusting
them, so the document cannot drift away from guard.py.

Paths resolve relative to this file, never to a deployment path.
"""

import hashlib
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PROPOSALS_DIR = REPO / "docs" / "strategy-proposals"
PROPOSAL_DOC = PROPOSALS_DIR / "STRATEGY_V1_1_PROPOSAL_v0_1.md"
MANIFEST_PATH = PROPOSALS_DIR / "strategy_v1_1_proposal_v0_1.manifest.json"
CANONICAL_STRATEGY = REPO / "docs" / "strategy_v1.md"
STRATEGY_CHANGELOG = REPO / "docs" / "strategy_v1_changelog.md"
GUARD_PATH = REPO / "guard.py"

VALID_STATUSES = {"PROPOSED", "BLOCKED", "PENDING_INPUT"}


def _load_manifest() -> dict:
    assert MANIFEST_PATH.exists(), f"manifest missing: {MANIFEST_PATH}"
    return json.loads(MANIFEST_PATH.read_text())


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _deterministic_hash(manifest: dict) -> str:
    """Identical algorithm to _compute_deterministic_manifest_hash_18a."""
    no_hash = {k: v for k, v in manifest.items()
               if k != "deterministic_manifest_hash"}
    canonical = json.dumps(no_hash, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Document presence ───────────────────────────────────────────────────────


class TestDocumentsExist:

    def test_proposals_dir_exists(self):
        assert PROPOSALS_DIR.is_dir()

    def test_proposal_doc_exists(self):
        assert PROPOSAL_DOC.exists(), "Phase 19A proposal document missing"

    def test_manifest_exists(self):
        assert MANIFEST_PATH.exists(), "Phase 19A manifest missing"

    def test_canonical_strategy_exists(self):
        assert CANONICAL_STRATEGY.exists()

    def test_strategy_changelog_exists(self):
        """Closes the dangling reference from strategy_v1.md section 16."""
        assert STRATEGY_CHANGELOG.exists(), \
            "docs/strategy_v1_changelog.md is referenced by strategy_v1.md and must exist"

    def test_every_referenced_document_exists(self):
        m = _load_manifest()
        for key, entry in m["documents"].items():
            path = REPO / entry["path"]
            assert path.exists(), f"documents.{key} points at missing file: {entry['path']}"


# ── Manifest structure ──────────────────────────────────────────────────────


class TestManifestStructure:

    def test_manifest_is_valid_json(self):
        assert isinstance(_load_manifest(), dict)

    def test_manifest_version_present(self):
        assert "manifest_version" in _load_manifest()

    def test_phase_is_19a(self):
        assert _load_manifest()["phase"] == "19A"

    def test_manifest_id_matches_filename(self):
        m = _load_manifest()
        assert m["manifest_id"] == MANIFEST_PATH.stem

    def test_governance_states_complete(self):
        assert set(_load_manifest()["governance_states"]) == VALID_STATUSES

    def test_required_top_level_sections_present(self):
        m = _load_manifest()
        for key in [
            "proposal_identity", "design_review_state", "governance_states",
            "approval_state", "explicit_non_actions", "design_summary",
            "leverage_disposition", "mstr_btc_disposition", "decisions",
            "anti_overfit_compliance", "implementation_phases",
            "promotion_requirements", "documents", "required_output_labels",
            "phase19a_diagnosis", "verified_against_code", "content_hashes",
        ]:
            assert key in m, f"manifest missing required section: {key}"


# ── Governance invariants ───────────────────────────────────────────────────


class TestGovernanceInvariants:

    def test_status_is_valid(self):
        assert _load_manifest()["proposal_identity"]["proposal_status"] in VALID_STATUSES

    def test_status_is_proposed(self):
        assert _load_manifest()["proposal_identity"]["proposal_status"] == "PROPOSED"

    def test_readiness_is_s0(self):
        assert _load_manifest()["proposal_identity"]["strategy_readiness"] == "S0"

    def test_autonomy_level_is_1(self):
        assert _load_manifest()["proposal_identity"]["autonomy_level"] == 1

    def test_design_only_is_true(self):
        assert _load_manifest()["proposal_identity"]["design_only"] is True

    def test_execution_scope_is_none(self):
        assert _load_manifest()["proposal_identity"]["execution_scope"] == "NONE"

    def test_leverage_scope_is_none(self):
        """Phase 19A formally rejects leverage; scope must be NONE."""
        assert _load_manifest()["proposal_identity"]["leverage_scope"] == "NONE"

    def test_target_strategy_not_active(self):
        assert _load_manifest()["proposal_identity"]["target_strategy_active"] is False

    @pytest.mark.parametrize("flag", [
        "allowlist_change", "rules_change", "broker_change",
        "guard_change", "env_change", "replaces_strategy_v1",
    ])
    def test_mutation_flags_are_false(self, flag):
        assert _load_manifest()["proposal_identity"][flag] is False, \
            f"{flag} must be false in a design-only phase"

    def test_canonical_strategy_unchanged_flag(self):
        assert _load_manifest()["proposal_identity"]["canonical_strategy_unchanged"] is True

    def test_human_approval_required(self):
        assert _load_manifest()["proposal_identity"]["human_approval_required_for_promotion"] is True

    def test_next_phase_boundary_is_19b(self):
        assert _load_manifest()["proposal_identity"]["next_phase_boundary"] == \
            "PHASE19B_ALLOWLIST_AND_ADVISORY_CONFIG"

    def test_all_approval_flags_restrictive(self):
        approval = _load_manifest()["approval_state"]
        assert approval, "approval_state must not be empty"
        for key, value in approval.items():
            assert value is True, f"{key} must be True (most restrictive)"

    def test_leverage_not_approved(self):
        assert _load_manifest()["approval_state"]["NOT_APPROVED_FOR_LEVERAGE"] is True

    def test_permitted_activity_is_design_only(self):
        assert _load_manifest()["proposal_identity"]["permitted_activity"] == \
            "DOCUMENTATION_AND_DESIGN_ONLY"


# ── Content hashes ──────────────────────────────────────────────────────────


class TestContentHashes:

    def test_proposal_sha256_present_and_wellformed(self):
        h = _load_manifest().get("proposal_document_sha256", "")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_proposal_sha256_matches_actual_file(self):
        m = _load_manifest()
        assert m["proposal_document_sha256"] == _sha256_file(PROPOSAL_DOC), \
            "Proposal document changed without regenerating the manifest"

    def test_deterministic_hash_present_and_wellformed(self):
        h = _load_manifest().get("deterministic_manifest_hash", "")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic_hash_is_reproducible(self):
        m = _load_manifest()
        assert m["deterministic_manifest_hash"] == _deterministic_hash(m), \
            "Manifest was hand-edited; re-run the generator"

    def test_proposal_document_path_matches(self):
        m = _load_manifest()
        assert m["proposal_document"] == "docs/strategy-proposals/STRATEGY_V1_1_PROPOSAL_v0_1.md"


# ── Design review state ─────────────────────────────────────────────────────


class TestDesignReviewState:

    def test_design_review_recorded(self):
        drs = _load_manifest()["design_review_state"]
        assert drs["design_review_required"] is True
        assert drs["design_review_status"] in {"PENDING", "COMPLETE"}

    def test_review_complete_and_consistent(self):
        drs = _load_manifest()["design_review_state"]
        assert drs["design_review_status"] == "COMPLETE"
        assert drs["design_review_completed"] is True

    def test_all_found_defects_are_corrected(self):
        drs = _load_manifest()["design_review_state"]
        assert drs["defects_found"] == drs["defects_corrected"], \
            "A design review with uncorrected defects cannot be COMPLETE"

    def test_defect_list_matches_count(self):
        drs = _load_manifest()["design_review_state"]
        assert len(drs["defects"]) == drs["defects_found"]

    def test_each_defect_has_resolution(self):
        for d in _load_manifest()["design_review_state"]["defects"]:
            assert d["id"] and d["defect"] and d["resolution"], \
                f"defect {d.get('id')} is incompletely recorded"

    def test_doc_version_matches_manifest(self):
        version = _load_manifest()["proposal_identity"]["proposal_version"]
        text = PROPOSAL_DOC.read_text()
        assert f"**Proposal Version:** `{version}`" in text, \
            "Proposal document version header disagrees with the manifest"


# ── Decisions and promotion gating ──────────────────────────────────────────


class TestDecisionsAndPromotion:

    def test_resolved_decisions_recorded(self):
        resolved = _load_manifest()["decisions"]["resolved"]
        ids = {d["id"] for d in resolved}
        assert {"11.2", "11.4"} <= ids

    def test_resolved_decisions_have_resolutions(self):
        for d in _load_manifest()["decisions"]["resolved"]:
            assert d["resolution"], f"decision {d['id']} lacks a resolution"

    def test_open_decisions_consistent_with_resolved_flag(self):
        """Open decisions stay visible until resolved; once none remain the
        manifest must say so explicitly rather than just going quiet."""
        d = _load_manifest()["decisions"]
        if d["open_requiring_chris"]:
            assert not d.get("all_decisions_resolved"), \
                "manifest claims all decisions resolved but still lists open ones"
        else:
            assert d.get("all_decisions_resolved") is True, \
                "no open decisions listed, but all_decisions_resolved is not set"
            assert d.get("all_decisions_resolved_at")

    def test_no_decision_is_both_open_and_resolved(self):
        d = _load_manifest()["decisions"]
        resolved_ids = {x["id"] for x in d["resolved"]}
        for entry in d["open_requiring_chris"]:
            oid = entry.split()[0]
            assert oid not in resolved_ids, f"decision {oid} listed as both open and resolved"

    def test_anti_overfit_blocks_promotion(self):
        ao = _load_manifest()["anti_overfit_compliance"]
        assert ao["promotion_blocked_by_anti_overfit"] is True
        assert set(ao["checks_unmet"]) == {2, 4, 7}

    def test_unmet_checks_have_detail(self):
        ao = _load_manifest()["anti_overfit_compliance"]
        for check in ao["checks_unmet"]:
            assert str(check) in ao["unmet_detail"], f"check {check} lacks detail"

    def test_follow_up_obligations_recorded(self):
        assert _load_manifest()["follow_up_obligations"], \
            "Outstanding obligations must be recorded, not implicit"

    def test_phase_dependency_order(self):
        phases = _load_manifest()["implementation_phases"]
        assert phases["dependency_order"] == ["19A", "19B", "19C", "19D", "19E"]

    def test_19a_declares_no_code_changes(self):
        assert _load_manifest()["implementation_phases"]["19A"]["code_changes"] is False


# ── Claims about the codebase, verified against the codebase ────────────────


class TestClaimsVerifiedAgainstCode:
    """The proposal makes assertions about guard.py. Verify them, don't trust them."""

    def test_gate_letter_i_is_actually_free(self):
        source = GUARD_PATH.read_text()
        letters = set(re.findall(r"Gate ([A-Z])\b", source))
        assert "I" not in letters, \
            "Gate I is claimed free but guard.py already uses it"
        assert {"A", "B", "C", "D", "E", "F", "G", "H"} <= letters

    def test_gate_h_is_proposal_discipline(self):
        source = GUARD_PATH.read_text()
        idx = source.find("def gate_proposal_discipline")
        assert idx != -1
        assert "Gate H" in source[idx:idx + 400]

    def test_yaml_loader_accepts_unknown_keys(self):
        """Phase 19B adds new YAML keys before guard.py knows about them."""
        source = GUARD_PATH.read_text()
        assert "missing = [k for k in required_keys if k not in rules]" in source, \
            "Rules loader no longer validates by required-keys only; 19B may not be backward compatible"

    def test_sizing_formula_unchanged(self):
        source = GUARD_PATH.read_text()
        assert "def compute_final_max_shares" in source
        assert "min(shares_by_notional, shares_by_risk)" in source, \
            "Sizing formula changed; proposal section 4.8 claims it is unchanged"

    def test_calc_stop_still_uses_five_percent_floor(self):
        source = GUARD_PATH.read_text()
        idx = source.find("def calc_stop")
        assert idx != -1
        assert "0.95" in source[idx:idx + 1200], \
            "calc_stop -5% hard floor missing; proposal section 4.9 claims it is unchanged"

    def test_manifest_code_claims_marked_verified(self):
        vac = _load_manifest()["verified_against_code"]
        for key in ["gate_letter_i_free", "yaml_unknown_keys_accepted",
                    "sizing_formula_unchanged"]:
            assert vac[key]["verified"] is True

    def test_operator_main_duplication_record_matches_reality(self):
        """The manifest's claim about main() must track the actual file.

        Fires in both directions: if the defect is recorded as open, main()
        must still be duplicated; if recorded as resolved, it must not be.
        """
        vac = _load_manifest()["verified_against_code"]["operator_main_duplicated"]
        operator = REPO / "ibkr_operator.py"
        count = len(re.findall(r"^def main\(", operator.read_text(), re.M))
        if vac.get("is_defect"):
            assert count > 1, \
                "main() is no longer duplicated — update the manifest and unblock the phase19a CLI command"
        else:
            assert count == 1, \
                f"manifest records the duplication as resolved but found {count} main() definitions"
            assert vac.get("resolved") is True

    def test_operator_has_no_duplicated_top_level_names(self):
        """Regression guard for the de-duplication."""
        import ast
        import collections
        tree = ast.parse((REPO / "ibkr_operator.py").read_text())
        names = collections.defaultdict(list)
        for node in tree.body:
            name = getattr(node, "name", None)
            if name is None and isinstance(node, ast.Assign):
                name = getattr(node.targets[0], "id", None)
            if name:
                names[name].append(node.lineno)
        dupes = {k: v for k, v in names.items() if len(v) > 1}
        assert not dupes, f"duplicated top-level definitions reintroduced: {dupes}"

    def test_no_script_references_the_raw_token_path(self):
        """Mirrors the T7 invariant — the manifest generator must stay clean."""
        gen = REPO / "scripts" / "gen_strategy_v1_1_manifest.py"
        if gen.exists():
            assert "/etc/ibkr-bridge/h1_token" not in gen.read_text(), \
                "manifest generator must not embed the raw H1 token path"


# ── Canonical strategy preservation ─────────────────────────────────────────


class TestCanonicalStrategyPreservation:

    def test_strategy_v1_still_declares_v1_0_0(self):
        assert "v1.0.0" in CANONICAL_STRATEGY.read_text()

    def test_strategy_v1_does_not_reference_this_proposal(self):
        content = CANONICAL_STRATEGY.read_text().lower()
        assert "strategy_v1_1_proposal" not in content, \
            "Phase 19A must not modify the canonical strategy"

    def test_strategy_v1_allowlist_unchanged(self):
        """The 22-symbol expansion must not have leaked into the active strategy."""
        content = CANONICAL_STRATEGY.read_text()
        for symbol in ["AAPL", "META", "NVDA", "AMD"]:
            assert symbol in content
        for symbol in ["XOM", "CVX", "DUK", "NEE", "UNP"]:
            assert symbol not in content, \
                f"{symbol} leaked into the active strategy document"

    def test_no_yaml_rules_file_in_repo_gained_new_symbols(self):
        """Phase 19A must not touch any YAML rules file."""
        for yp in list(REPO.glob("**/*.yaml")) + list(REPO.glob("**/*.yml")):
            content = yp.read_text()
            for symbol in ["XOM", "CVX", "DUK", "NEE", "UNP", "MSTR"]:
                assert symbol not in content, f"{symbol} found in {yp}"


# ── Output labels ───────────────────────────────────────────────────────────


class TestOutputLabels:

    def test_required_labels_present(self):
        labels = _load_manifest()["required_output_labels"]
        for expected in [
            "PHASE19A_STRATEGY_V1_1_DESIGN_PROPOSAL_GOVERNANCE",
            "PROPOSED", "DESIGN_ONLY", "NON_EXECUTABLE", "NO_EXECUTION_SCOPE",
            "NO_ALLOWLIST_CHANGE", "NO_GUARD_CHANGE", "NO_H1_ACCESSED",
            "NO_LEVERAGE", "STRATEGY_V1_UNCHANGED", "S0_READINESS", "LEVEL1",
        ]:
            assert expected in labels, f"missing output label: {expected}"

    def test_diagnosis_map_has_ready_code(self):
        assert _load_manifest()["phase19a_diagnosis"]["ready"] == \
            "phase19a_design_proposal_governance_ok"


# ── Safety boundary in the document itself ──────────────────────────────────


class TestDocumentSafetyBoundary:

    def test_doc_does_not_enable_kill_switches(self):
        content = PROPOSAL_DOC.read_text()
        assert "IBKR_ALLOW_ORDERS=true" not in content
        assert "rules.enforced=true" not in content

    def test_doc_declares_explicit_non_actions(self):
        assert len(_load_manifest()["explicit_non_actions"]) >= 10

    def test_doc_rejects_leverage(self):
        ld = _load_manifest()["leverage_disposition"]
        assert ld["leverage_recommendation"] == "REJECTED"
        assert ld["instrument_embedded_leverage_rejected"] is True

    def test_mstr_btc_held_at_proposed(self):
        md = _load_manifest()["mstr_btc_disposition"]
        assert md["recommendation"] == "HOLD_AT_PROPOSED"
        assert md["promotion_requested"] is False
        assert md["referenced_proposal_status_unchanged"] is True

    def test_advisory_layer_cannot_loosen(self):
        summary = _load_manifest()["design_summary"]["inverse_vol_scalar_proposed"]
        assert summary["can_only_tighten"] is True
        assert summary["can_never_exceed_yaml_ceiling"] is True

    def test_vol_reference_is_not_labeled_a_target(self):
        """Design-review defect D2 must not regress."""
        summary = _load_manifest()["design_summary"]["inverse_vol_scalar_proposed"]
        assert summary["is_portfolio_vol_target"] is False
        assert summary["vol_reference_pct"] == 16


# ── Paper-run pre-registration infrastructure (§10.4) ───────────────────────


class TestPreregistrationInfrastructure:

    TEMPLATE = REPO / "docs" / "paper-runs" / "TEMPLATE-preregistration.md"
    SEAL = REPO / "scripts" / "seal-preregistration.py"

    def test_template_exists(self):
        assert self.TEMPLATE.exists()

    def test_readme_exists(self):
        assert (REPO / "docs" / "paper-runs" / "README.md").exists()

    def test_seal_script_exists(self):
        assert self.SEAL.exists()

    def test_template_covers_all_seven_required_fields(self):
        text = self.TEMPLATE.read_text()
        for heading in ["Run identity", "Strategy version under test",
                        "Expected observations", "Falsifiers", "Decision rules",
                        "Explicitly excluded", "Revision budget", "Seal"]:
            assert heading in text, f"template missing section: {heading}"

    def test_template_carries_all_fifteen_falsifiers(self):
        text = self.TEMPLATE.read_text()
        for n in range(1, 16):
            assert f"| F{n} |" in text, f"falsifier F{n} missing from template"

    def test_expected_values_are_left_blank(self):
        """§3 must be the operator's prior, never pre-filled by the assistant."""
        text = self.TEMPLATE.read_text()
        section = text[text.index("## 3. Expected observations"):text.index("## 4. Falsifiers")]
        assert section.count("<<FILL IN>>") >= 8, \
            "expected-observation ranges must be blank — a suggested value is an anchor, not a prior"

    def test_template_excludes_pnl_from_decisions(self):
        text = self.TEMPLATE.read_text()
        section = text[text.index("## 6. Explicitly excluded"):text.index("## 7. Revision budget")]
        for metric in ["Paper P&L", "Win rate", "Paper Sharpe"]:
            assert metric in section

    def test_revision_budget_is_one(self):
        text = self.TEMPLATE.read_text()
        section = text[text.index("## 7. Revision budget"):]
        assert "**1**" in section

    def test_manifest_records_the_infrastructure(self):
        infra = _load_manifest()["paper_run_infrastructure"]
        assert infra["expected_values_supplied_by"] == "Chris only"
        for key in ["preregistration_template", "readme", "seal_script"]:
            assert (REPO / infra[key]).exists(), f"{key} points at a missing file"


# ── Approval record ─────────────────────────────────────────────────────────


class TestApprovalRecord:

    def test_design_approval_recorded(self):
        a = _load_manifest()["chris_approval"]
        assert a["design_approved"] is True
        assert a["approved_utc"]

    def test_approval_does_not_extend_to_execution(self):
        """Design approval must not silently relax any restrictive flag."""
        m = _load_manifest()
        assert m["chris_approval"]["does_not_approve"]
        for key, value in m["approval_state"].items():
            assert value is True, \
                f"{key} was relaxed — design approval does not authorise execution"

    def test_phase_19a_still_declares_no_mutations(self):
        pi = _load_manifest()["proposal_identity"]
        for flag in ["allowlist_change", "rules_change", "guard_change", "env_change"]:
            assert pi[flag] is False


# ── CI covers this branch (§9.6 follow-up) ──────────────────────────────────


class TestCiCoversDevelopmentBranches:

    def test_ci_push_trigger_includes_claude_branches(self):
        ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
        assert "'claude/*'" in ci, \
            "CI push trigger does not match claude/* — commits on this branch would run no CI"
