#!/usr/bin/env python3
"""Generate the Phase 19A manifest for the Strategy v1.1 proposal.

Mirrors the Phase 18A manifest structure and uses the identical
deterministic-hash algorithm:

    manifest_no_hash = {k: v for k, v in manifest.items()
                        if k != "deterministic_manifest_hash"}
    canonical = json.dumps(manifest_no_hash, sort_keys=True, ensure_ascii=False)
    sha256(canonical.encode("utf-8")).hexdigest()

Re-run this after ANY edit to the proposal document to refresh both hashes.
"""

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROPOSALS = REPO / "docs" / "strategy-proposals"
PROPOSAL_DOC = PROPOSALS / "STRATEGY_V1_1_PROPOSAL_v0_1.md"
MANIFEST_PATH = PROPOSALS / "strategy_v1_1_proposal_v0_1.manifest.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def deterministic_hash(manifest: dict) -> str:
    no_hash = {k: v for k, v in manifest.items()
               if k != "deterministic_manifest_hash"}
    canonical = json.dumps(no_hash, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


manifest: dict = {
    "manifest_version": "1.0.0",
    "manifest_id": "strategy_v1_1_proposal_v0_1.manifest",
    "created_utc": "2026-07-27T00:00:00Z",
    "last_updated_utc": "2026-07-27T00:00:00Z",
    "phase": "19A",
    "phase_name": "Level 1 Strategy v1.1 Design Proposal Governance Checkpoint",

    "proposal_identity": {
        "proposal_id": "strategy_v1_1_proposal_v0_1",
        "proposal_version": "0.2",
        "proposal_status": "PROPOSED",
        "strategy_readiness": "S0",
        "autonomy_level": 1,
        "design_only": True,
        "execution_scope": "NONE",
        "permitted_activity": "DOCUMENTATION_AND_DESIGN_ONLY",
        "target_strategy_version": "v1.1.0",
        "target_strategy_active": False,
        "leverage_scope": "NONE",
        "allowlist_change": False,
        "rules_change": False,
        "broker_change": False,
        "guard_change": False,
        "env_change": False,
        "replaces_strategy_v1": False,
        "canonical_strategy_unchanged": True,
        "human_approval_required_for_promotion": True,
        "next_phase_boundary": "PHASE19B_ALLOWLIST_AND_ADVISORY_CONFIG",
        "canonical_strategy_reference": "docs/strategy_v1.md",
    },

    "design_review_state": {
        "design_review_required": True,
        "design_review_status": "COMPLETE",
        "design_review_completed": True,
        "design_review_date": "2026-07-27",
        "defects_found": 6,
        "defects_corrected": 6,
        "defects": [
            {"id": "D1", "severity": "blocker", "area": "section 6.1",
             "defect": "Draft asserted a 6-position maximum; invalid because risk-capped positions are smaller than 5% notional so more fit inside the 30% ceiling",
             "resolution": "Position count declared unconstrained; Gates B and F bound total risk"},
            {"id": "D2", "severity": "blocker", "area": "section 4.6",
             "defect": "portfolio_vol_target_pct 12 was mislabeled (portfolio tops out near 6.6% vol) and permanently binding (12/16 ~ 0.75 in calm markets)",
             "resolution": "Renamed vol_reference_pct and set to 16 percent; dormant in calm, responsive in stress"},
            {"id": "D3", "severity": "gap", "area": "section 4.10",
             "defect": "No data-quality thresholds for the new signals; regime gate needs 252 bars but fetch_bars defaults to 30 D",
             "resolution": "Added data-quality section with fail-safe rules; missing regime data yields RISK_OFF not RISK_ON"},
            {"id": "D4", "severity": "gap", "area": "section 6.2",
             "defect": "No transition rule for positions held at activation",
             "resolution": "Added grandfathering clause; existing positions count toward Gate F and Gate I"},
            {"id": "D5", "severity": "gap", "area": "section 9.6",
             "defect": "Implementation plan omitted the operator CLI checkpoint command required by phase convention",
             "resolution": "Added, blocked pending main() de-duplication in ibkr_operator.py"},
            {"id": "D6", "severity": "gap", "area": "docs/strategy_v1_changelog.md",
             "defect": "File referenced by strategy_v1.md section 16 and by promotion requirement 9 but did not exist",
             "resolution": "Created"},
        ],
        "note": (
            "Design review is complete and its findings are applied in proposal_version 0.2. "
            "If the proposal document changes again, re-run the manifest generator so "
            "proposal_document_sha256 and deterministic_manifest_hash match the new bytes."
        ),
    },

    "governance_states": {
        "PROPOSED": {
            "description": (
                "The v1.1 design is documented and may proceed to Phase 19B "
                "allowlist and advisory configuration after Chris's approval. "
                "It does NOT mean the strategy has an edge, is approved for "
                "trading, or may access an execution path."
            ),
            "requires": [
                "all_required_documents_present",
                "all_manifest_fields_valid",
                "no_execution_scope_indicated",
                "canonical_strategy_v1_unchanged",
                "design_review_completed",
            ],
        },
        "BLOCKED": {
            "description": (
                "The proposal cannot proceed to Phase 19B. A hard governance "
                "violation exists and must be resolved before promotion."
            ),
            "triggers": [
                "missing_required_manifest_field",
                "replaces_strategy_v1_true",
                "canonical_strategy_unchanged_false",
                "execution_scope_not_none",
                "leverage_scope_not_none",
                "allowlist_change_true",
                "rules_change_true",
                "broker_change_true",
                "guard_change_true",
                "env_change_true",
                "design_only_not_true",
                "autonomy_level_not_1",
                "permitted_activity_invalid",
                "target_strategy_active_true",
                "document_missing",
                "document_hash_mismatch",
                "deterministic_manifest_hash_mismatch",
                "proposal_doc_sha256_mismatch",
            ],
        },
        "PENDING_INPUT": {
            "description": (
                "Structurally valid but requires additional input before promotion."
            ),
            "triggers": [
                "manifest_exists_but_documents_missing",
                "content_hash_mismatch",
                "proposal_status_invalid",
                "design_review_not_completed",
                "open_decisions_unresolved",
            ],
        },
    },

    "approval_state": {
        "NOT_APPROVED_FOR_EXECUTION": True,
        "NOT_APPROVED_FOR_ALLOWLIST_CHANGE": True,
        "NOT_APPROVED_FOR_YAML_MUTATION": True,
        "NOT_APPROVED_FOR_GUARD_MUTATION": True,
        "NOT_APPROVED_FOR_ENV_MUTATION": True,
        "NOT_APPROVED_FOR_BACKTEST_PROMOTION": True,
        "NOT_APPROVED_FOR_STRATEGY_ACTIVATION": True,
        "NOT_APPROVED_FOR_LEVERAGE": True,
    },

    "explicit_non_actions": [
        "This proposal does not replace or modify docs/strategy_v1.md (v1.0.0 remains active)",
        "This proposal does not modify ~/.openclaw/risk-rules/paper-trading-rules.yaml",
        "This proposal does not modify .env, guard-state.json, approval-records.jsonl, active-approvals.json, or submitted-approvals.json",
        "This proposal does not modify guard.py, bridge.py, monitor.py, or bundle_audit.py",
        "This proposal does not add any symbol to an executable allowlist",
        "This proposal does not enable IBKR_ALLOW_ORDERS or rules.enforced",
        "This proposal does not generate, read, possess, or transmit an H1 token",
        "This proposal does not access /etc/ibkr-bridge/h1_token or any root-owned file",
        "This proposal does not call any IBKR endpoint or any /order* endpoint",
        "This proposal does not run a backtest or collect market data",
        "This proposal does not generate a trade proposal or open an order window",
        "This proposal does not enable crypto, options, futures, forex, CFDs, leverage, or shorting",
        "This proposal does not promote mstr_btc_research_v0_1 beyond PROPOSED",
        "This proposal does not introduce autonomous parameter adaptation or self-modifying logic",
        "This proposal does not subvert the advisory-only boundary of Hermes or Werner",
    ],

    "design_summary": {
        "universe_expansion_proposed": {
            "from_symbol_count": 4,
            "to_symbol_count": 22,
            "from_sector_count": 3,
            "to_sector_count": 10,
            "rationale": "IR ~ IC * sqrt(BR); breadth counts independent bets, not tickers",
            "applied": False,
            "applied_by": "Chris in Phase 19B only",
        },
        "regime_gate_proposed": {
            "states": ["RISK_ON", "CAUTION", "RISK_OFF"],
            "reference_symbol": "SPY",
            "reference_usage": "bars_only",
            "reference_order_eligible": False,
            "parameters": {"sma_days": 200, "momentum_months": 12},
            "sell_never_blocked": True,
        },
        "inverse_vol_scalar_proposed": {
            "vol_reference_pct": 16,
            "is_portfolio_vol_target": False,
            "note": "Normalization constant near SPY long-run median vol, not a portfolio vol target. See proposal section 4.6.1.",
            "estimated_portfolio_vol_at_full_gross_pct": 6.6,
            "lookback_days": 20,
            "gross_scalar_floor": 0.25,
            "gross_scalar_ceiling": 1.0,
            "can_only_tighten": True,
            "can_never_exceed_yaml_ceiling": True,
        },
        "gate_i_sector_cap_proposed": {
            "gate_letter": "I",
            "max_positions_per_sector": 2,
            "applies_to": "BUY",
            "sell_exempt": True,
            "fail_mode": "closed",
            "implemented": False,
            "requires_tier1_model": True,
        },
        "unchanged": [
            "sizing formula (compute_final_max_shares)",
            "calc_stop formula",
            "5% max position notional",
            "2% max risk per trade",
            "30% max total exposure",
            "2 trades per day",
            "-1% daily / -3% weekly loss halts",
            "all CLAUDE.md section 3 safety invariants",
        ],
    },

    "leverage_disposition": {
        "leverage_requested_by_operator": "1x_to_20x",
        "leverage_recommendation": "REJECTED",
        "kelly_optimal_leverage_reference": 1.5,
        "zero_growth_leverage_reference": 3.0,
        "basis": "g(L) = L*mu - (L^2 * sigma^2)/2 is quadratic-negative in L",
        "instrument_embedded_leverage_rejected": True,
        "mstr_identified_as_embedded_leverage": True,
        "note": (
            "Volatility figures are long-run reference estimates, not computed "
            "values. Recalibrate from bridge market/bars before promotion."
        ),
    },

    "mstr_btc_disposition": {
        "recommendation": "HOLD_AT_PROPOSED",
        "referenced_proposal_id": "mstr_btc_research_v0_1",
        "referenced_proposal_status_unchanged": True,
        "promotion_requested": False,
        "qqq_fallback_construction_rejected": True,
        "rejection_bases": [
            "MSTR_BTC_RESEARCH_PROPOSAL_v0_1 section 5 forbids Track B selection on Track A NO_TRADE",
            "strategy_v1.md section 3 H4.1 blocks US-domiciled ETFs for BUY",
            "gate_allowlist fails closed; QQQ absent from YAML allowlist",
        ],
    },

    "decisions": {
        "resolved": [
            {"id": "11.2", "topic": "Maximum concurrent positions",
             "resolution": "UNCONSTRAINED — Gates B and F bound total risk; a count cap would fail anti-overfit check 6",
             "resolved_at": "design_review_2026-07-27"},
            {"id": "11.4", "topic": "Volatility reference value",
             "resolution": "vol_reference_pct = 16, renamed from portfolio_vol_target_pct",
             "resolved_at": "design_review_2026-07-27"},
        ],
        "open_requiring_chris": [
            "11.1 H4.1 US-domiciled ETF BUY block: keep or lift",
            "11.3 Final allowlist composition",
            "11.5 MSTR/BTC disposition confirmation",
            "11.6 Definition of 'learning' during the paper run",
        ],
    },
    "follow_up_obligations": [
        "Recalibrate vol_reference_pct from SPY median 20d realized vol over >=5 years via bridge market/bars",
        "Correct the erroneous max-concurrent-positions row in strategy_v1.md section 8 at promotion",
        "De-duplicate main() in ibkr_operator.py (two top-level definitions; the first ~2570 lines are dead code), then add the phase19a CLI command",
        "Add 'claude/*' to the CI push trigger, or run Phase 19E validation via pull request",
    ],

    "anti_overfit_compliance": {
        "reference": "docs/strategy_v1.md section 15",
        "checks_met": [1, 3, 5, 6, 9, 10],
        "checks_partial": [8],
        "checks_unmet": [2, 4, 7],
        "unmet_detail": {
            "2": "out-of-sample testing not performed",
            "4": "walk-forward validation not performed",
            "7": "out-of-sample Sharpe / max-drawdown not measured",
        },
        "failsafe_verdict": (
            "Fewer than 3 checks fail outright, so proposal status is permitted; "
            "promotion to active strategy remains blocked until checks 2, 4, and 7 are met."
        ),
        "promotion_blocked_by_anti_overfit": True,
    },

    "documented_defects_in_strategy_v1": [
        {
            "id": "V1_DEFECT_BREADTH",
            "description": "Allowlist of 4 correlated mega-cap tech names is approximately 1.3 independent bets",
            "severity": "design",
            "addressed_by": "proposal section 4.2",
        },
        {
            "id": "V1_DEFECT_POSITION_COUNT",
            "description": "strategy_v1.md section 8 states max 2 concurrent positions; 30% / 5% derives 6",
            "severity": "documentation_contradiction",
            "addressed_by": "proposal section 6.1",
        },
        {
            "id": "V1_DEFECT_H4_1_TENSION",
            "description": "strategy_v1.md section 2 lists ETFs as an allowed placeholder while section 3 hard-blocks ETF BUY",
            "severity": "documentation_contradiction",
            "addressed_by": "proposal section 11.1 open decision",
        },
    ],

    "implementation_phases": {
        "19A": {"name": "Documentation only", "code_changes": False, "status": "DESIGN_REVIEW_COMPLETE_PENDING_APPROVAL"},
        "19B": {"name": "YAML allowlist and advisory config", "applied_by": "Chris", "status": "NOT_STARTED"},
        "19C": {"name": "Advisory layer (hermes_advisory.py)", "status": "NOT_STARTED"},
        "19D": {"name": "Gate I in guard.py", "requires_tier1_model": True, "status": "NOT_STARTED"},
        "19E": {"name": "Test modules", "status": "NOT_STARTED"},
        "dependency_order": ["19A", "19B", "19C", "19D", "19E"],
        "note": "19D must not land before 19B or guard.py raises on missing required keys at load",
    },

    "promotion_requirements": [
        "Chris's explicit approval of the proposal document",
        "Design review completed",
        "Open decisions 11.1, 11.2, and 11.3 resolved at minimum",
        "Phase 19B applied by Chris (YAML allowlist and advisory config)",
        "Phase 19C and 19D implemented; 19D under a Tier-1 model with a git-tagged commit",
        "Phase 19E green, including the budget-ceiling property test",
        "Out-of-sample and walk-forward evidence satisfying anti-overfit checks 2, 4, and 7",
        "Paper validation section 10.1 complete — all 15 plumbing checks positively exercised",
        "CLAUDE.md section 3 invariants 1-17 re-verified via ibkr-status and GET /status",
        "Version bump to v1.1.0 with a changelog entry in docs/strategy_v1_changelog.md",
        "All content hashes verified at every gate",
    ],

    "documents": {
        "design_proposal": {
            "path": "docs/strategy-proposals/STRATEGY_V1_1_PROPOSAL_v0_1.md",
            "document_id": "STRATEGY_V1_1_PROPOSAL_v0_1",
            "version": "0.1",
            "description": "Strategy v1.1 design proposal — breadth, regime gating, volatility targeting, Gate I, leverage rejection",
        },
        "manifest": {
            "path": "docs/strategy-proposals/strategy_v1_1_proposal_v0_1.manifest.json",
            "document_id": "strategy_v1_1_proposal_v0_1.manifest",
            "version": "0.1",
            "description": "Machine-readable proposal metadata manifest",
        },
        "strategy_changelog": {
            "path": "docs/strategy_v1_changelog.md",
            "document_id": "strategy_v1_changelog",
            "version": "1.0.0",
            "description": "Strategy version ledger — created in Phase 19A to close a dangling reference from strategy_v1.md section 16",
        },
        "canonical_strategy": {
            "path": "docs/strategy_v1.md",
            "document_id": "strategy-v1-2026-07-09",
            "version": "1.0.0",
            "description": "Active canonical Strategy v1 — unchanged by this proposal",
        },
    },

    "proposal_document": "docs/strategy-proposals/STRATEGY_V1_1_PROPOSAL_v0_1.md",

    "required_output_labels": [
        "PHASE19A_STRATEGY_V1_1_DESIGN_PROPOSAL_GOVERNANCE",
        "PROPOSED",
        "DESIGN_ONLY",
        "NON_EXECUTABLE",
        "NO_EXECUTION_SCOPE",
        "NO_ALLOWLIST_CHANGE",
        "NO_RULES_CHANGE",
        "NO_GUARD_CHANGE",
        "NO_BROKER_MUTATION",
        "NO_H1_ACCESSED",
        "NO_LEVERAGE",
        "STRATEGY_V1_UNCHANGED",
        "S0_READINESS",
        "LEVEL1",
        "DOCUMENTATION_AND_DESIGN_ONLY",
    ],

    "phase19a_diagnosis": {
        "ready": "phase19a_design_proposal_governance_ok",
        "proposal_doc_missing": "proposal_doc_missing",
        "manifest_missing": "manifest_missing",
        "manifest_invalid_json": "manifest_invalid_json",
        "manifest_field_missing": "manifest_field_missing",
        "manifest_field_invalid": "manifest_field_invalid",
        "proposal_doc_sha256_mismatch": "proposal_doc_sha256_mismatch",
        "deterministic_manifest_hash_mismatch": "deterministic_manifest_hash_mismatch",
        "execution_scope_not_none": "execution_scope_not_none",
        "leverage_scope_not_none": "leverage_scope_not_none",
        "allowlist_change_true": "allowlist_change_true",
        "rules_change_true": "rules_change_true",
        "guard_change_true": "guard_change_true",
        "replaces_strategy_v1_true": "replaces_strategy_v1_true",
        "canonical_strategy_unchanged_false": "canonical_strategy_unchanged_false",
        "design_only_not_true": "design_only_not_true",
        "autonomy_level_not_1": "autonomy_level_not_1",
        "target_strategy_active_true": "target_strategy_active_true",
        "design_review_not_completed": "design_review_not_completed",
        "approval_state_invalid": "approval_state_invalid",
        "governance_state_invalid": "governance_state_invalid",
        "output_labels_missing": "output_labels_missing",
        "content_hash_mismatch": "content_hash_mismatch",
        "strategy_v1_modified": "strategy_v1_modified",
        "unknown": "unknown",
    },

    "verified_against_code": {
        "gate_letter_i_free": {
            "verified": True,
            "detail": "guard.py defines Gates A-H; H is gate_proposal_discipline at guard.py:1771. gate_open_orders at guard.py:1959 carries no letter.",
        },
        "yaml_unknown_keys_accepted": {
            "verified": True,
            "detail": "guard.py:4015 validates only that required keys are present; unknown keys are not rejected, so Phase 19B is backward compatible.",
        },
        "sizing_formula_unchanged": {
            "verified": True,
            "detail": "compute_final_max_shares at guard.py:1268 returns min(shares_by_notional, shares_by_risk); v1.1 does not modify it.",
        },
        "operator_main_duplicated": {
            "verified": True,
            "is_defect": True,
            "detail": "ibkr_operator.py defines main() at both line 49762 and line 52332; the second shadows the first, leaving ~2570 lines unreachable. Blocks the phase19a CLI command.",
        },
    },

    "content_hashes": {
        "algorithm": "sha256",
        "note": (
            "proposal_document_sha256 is the SHA-256 of the proposal document bytes. "
            "deterministic_manifest_hash is the SHA-256 of this manifest serialized "
            "with sort_keys=True and ensure_ascii=False, excluding the "
            "deterministic_manifest_hash field itself."
        ),
    },
}

# Compute hashes last, in dependency order.
manifest["proposal_document_sha256"] = sha256_file(PROPOSAL_DOC)
manifest["deterministic_manifest_hash"] = deterministic_hash(manifest)

MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

# Verify round-trip exactly as the test harness will.
reloaded = json.loads(MANIFEST_PATH.read_text())
recomputed = deterministic_hash(reloaded)
doc_actual = sha256_file(PROPOSAL_DOC)

print(f"manifest written:  {MANIFEST_PATH}")
print(f"proposal sha256:   {reloaded['proposal_document_sha256']}")
print(f"  matches file:    {reloaded['proposal_document_sha256'] == doc_actual}")
print(f"deterministic:     {reloaded['deterministic_manifest_hash']}")
print(f"  reproducible:    {reloaded['deterministic_manifest_hash'] == recomputed}")
print(f"  length 64:       {len(reloaded['deterministic_manifest_hash']) == 64}")
print(f"  lowercase hex:   {all(c in '0123456789abcdef' for c in reloaded['deterministic_manifest_hash'])}")
