from trading_agent.cli.operator_legacy import (_PHASE16B_DIAGNOSIS, _PHASE16C_DIAGNOSIS, _PHASE16D_DIAGNOSIS, _PHASE16D_EXPLICIT_APPLY_FLAGS, _PHASE16E_DIAGNOSIS, _PHASE16E_EXPLICIT_NON_ACTIONS, _PHASE16F_DIAGNOSIS, _PHASE16F_EXPLICIT_NON_ACTIONS, _PHASE16G_DIAGNOSIS, _PHASE16G_EXPLICIT_NON_ACTIONS, _PHASE16H_DIAGNOSIS, _PHASE16H_EXPLICIT_NON_ACTIONS, _PHASE16I_DIAGNOSIS, _PHASE16I_EXPLICIT_NON_ACTIONS, _PHASE16J_DIAGNOSIS, _PHASE16J_EXPLICIT_NON_ACTIONS, _PHASE16K_DIAGNOSIS, _PHASE16K_EXPLICIT_NON_ACTIONS, _PHASE16L_DIAGNOSIS, _PHASE16L_EXPLICIT_NON_ACTIONS, _PHASE16M_DIAGNOSIS, _PHASE16M_EXPLICIT_NON_ACTIONS, _PHASE16N_DIAGNOSIS, _PHASE16N_EXPLICIT_NON_ACTIONS, _PHASE16O_DIAGNOSIS, _PHASE16O_EXPLICIT_NON_ACTIONS, _PHASE16P_DIAGNOSIS, _PHASE16P_EXPLICIT_NON_ACTIONS, _PHASE16Q_DIAGNOSIS, _PHASE16Q_EXPLICIT_NON_ACTIONS, _PHASE16R_DIAGNOSIS, _PHASE16R_EXPLICIT_NON_ACTIONS, _PHASE16S_DIAGNOSIS, _PHASE16S_EXPLICIT_NON_ACTIONS, _PHASE16S_EXPORT_DIR, _PHASE16T_BRIDGE_SERVICE, _PHASE16T_DIAGNOSIS, _PHASE16T_EXPLICIT_NON_ACTIONS, _PHASE16T_EXPORT_DIR, _PHASE16U_DIAGNOSIS, _PHASE16U_EXPORT_DIR, _PHASE16V_DIAGNOSIS, _PHASE16V_EXPORT_DIR, _PHASE16W_DIAGNOSIS, _PHASE16W_EXPORT_DIR, _PHASE16X_DIAGNOSIS, _PHASE16X_EXPORT_DIR, _PHASE16Y_DIAGNOSIS, _PHASE16Y_EXPORT_DIR, _PHASE16Z_DIAGNOSIS, _PHASE16Z_EXPORT_DIR, _compute_evidence_hash, _phase16u_no_go, _phase16v_no_go, _phase16w_no_go, _phase16x_no_go, _phase16y_no_go, _phase16z_no_go, _print_level1_apply_gate, _print_level1_broker_mutation_firewall_audit_checkpoint, _print_level1_end_to_end_safety_invariant_checkpoint, _print_level1_evidence_normalization_check, _print_level1_execution_gate_negative_control_drill, _print_level1_execution_readiness_packet_drill, _print_level1_fresh_clone_ci_workflow_checkpoint, _print_level1_guard_state_rollover_resilience_checkpoint, _print_level1_h1_boundary_audit_checkpoint, _print_level1_human_approval_packet_drill, _print_level1_human_review_package_drill, _print_level1_order_plan_draft_drill, _print_level1_order_window_canary_negative_control_drill, _print_level1_os_boundary_h1_isolation_checkpoint, _print_level1_portable_tests_ci_readiness_checkpoint, _print_level1_post_promotion_stability_drill, _print_level1_preflight_simulation_dossier, _print_level1_promotion_dry_run_gate, _print_level1_proposal_workflow_drill, _print_level1_readiness_chain_integrity_checkpoint, _print_level1_restart_persistence_safety_checkpoint, _print_level1_review_decision_drill, _print_level1_scheduled_heartbeat_alerting_resilience_checkpoint, _print_level1_startup_autoconnect_resilience_checkpoint, _print_manual_level1_promotion_review, _print_phase15_completion_checkpoint, _print_promotion_plan, _run_autonomy_promotion_plan, _run_level1_apply_gate, _run_level1_broker_mutation_firewall_audit_checkpoint, _run_level1_end_to_end_safety_invariant_checkpoint, _run_level1_evidence_normalization_check, _run_level1_execution_gate_negative_control_drill, _run_level1_execution_readiness_packet_drill, _run_level1_fresh_clone_ci_workflow_checkpoint, _run_level1_guard_state_rollover_resilience_checkpoint, _run_level1_h1_boundary_audit_checkpoint, _run_level1_human_approval_packet_drill, _run_level1_human_review_package_drill, _run_level1_order_plan_draft_drill, _run_level1_order_window_canary_negative_control_drill, _run_level1_os_boundary_h1_isolation_checkpoint, _run_level1_portable_tests_ci_readiness_checkpoint, _run_level1_post_promotion_stability_drill, _run_level1_preflight_simulation_dossier, _run_level1_promotion_dry_run_gate, _run_level1_proposal_workflow_drill, _run_level1_readiness_chain_integrity_checkpoint, _run_level1_restart_persistence_safety_checkpoint, _run_level1_review_decision_drill, _run_level1_scheduled_heartbeat_alerting_resilience_checkpoint, _run_level1_startup_autoconnect_resilience_checkpoint, _run_manual_level1_promotion_review, _run_phase15_completion_checkpoint, datetime, json, sys, timezone)

def command_14(args, parser):
    result = _run_autonomy_promotion_plan(target_level=args.target_level)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_promotion_plan(result)
    if args.export:
        ep = result.get("_export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result["plan_status"] == "READY_FOR_MANUAL_DECISION" else 1
    sys.exit(exit_code)


def command_28(args, parser):
    try:
        result = _run_phase15_completion_checkpoint()
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str,
            "diagnosis": "unknown",
            "severity": "NO_GO",
            "phase15_complete": False,
            "operator_action_required": True,
            "suggested_operator_actions": [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
            "internal_exception": True,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "h1_token_not_used": True,
            "export_path": None,
        }
        print(f"Checkpoint internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_phase15_completion_checkpoint(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("phase15_complete", False) else 1
    sys.exit(exit_code)


def command_29(args, parser):
    try:
        result = _run_manual_level1_promotion_review()
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str,
            "diagnosis": "unknown",
            "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [
                f"Internal error: {type(exc).__name__}",
                "Run ibkr-operator doctor",
            ],
            "promotion_allowed_now": False,
            "order_enablement_allowed_now": False,
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "h1_token_not_used": True,
            "export_path": None,
        }
        print(f"Promotion review internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_manual_level1_promotion_review(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16B_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_30(args, parser):
    try:
        result = _run_level1_promotion_dry_run_gate()
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str,
            "diagnosis": "unknown",
            "severity": "NO_GO",
            "operator_action_required": True,
            "gate_ready": False,
            "suggested_operator_actions": [
                f"Internal error: {type(exc).__name__}",
                "Run ibkr-operator doctor",
            ],
            "promotion_allowed_now": False,
            "promotion_performed": False,
            "order_enablement_allowed_now": False,
            "order_enablement_performed": False,
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "h1_token_not_used": True,
            "export_path": None,
        }
        print(f"Dry-run gate internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_promotion_dry_run_gate(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16C_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_31(args, parser):
    apply_flags_raw = {
        "--apply": getattr(args, "apply", False),
        "--confirm-level1": getattr(args, "confirm_level1", False),
        "--human-signed-apply": getattr(args, "human_signed_apply", False),
        "--ack-no-order-enablement": getattr(args, "ack_no_order_enablement", False),
        "--ack-manual-approval-required": getattr(args, "ack_manual_approval_required", False),
        "--ack-relock-required": getattr(args, "ack_relock_required", False),
    }
    apply_mode = all(apply_flags_raw.values())
    present_flags = tuple(k for k, v in apply_flags_raw.items() if v)
    try:
        result = _run_level1_apply_gate(
            apply_mode=apply_mode,
            apply_flags_present=present_flags,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str,
            "mode": "apply" if apply_mode else "review",
            "diagnosis": "unknown",
            "severity": "NO_GO",
            "operator_action_required": True,
            "apply_gate": {
                "apply_ready": False,
                "apply_requested": apply_mode,
                "apply_performed": False,
                "target_autonomy_level": "1",
                "prior_autonomy_level": "?",
                "resulting_autonomy_level": "?",
                "order_enablement_performed": False,
                "promotion_allowed_now": False,
                "order_enablement_allowed_now": False,
                "required_flags": list(_PHASE16D_EXPLICIT_APPLY_FLAGS),
                "missing_flags": list(_PHASE16D_EXPLICIT_APPLY_FLAGS),
                "human_signoff_statement": "",
                "rollback_command_preview": "",
                "relock_command_preview": "",
            },
            "suggested_operator_actions": [
                f"Internal error: {type(exc).__name__}",
                "Run ibkr-operator doctor",
            ],
            "promotion_allowed_now": False,
            "promotion_performed": False,
            "order_enablement_allowed_now": False,
            "order_enablement_performed": False,
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "h1_token_not_used": True,
            "export_path": None,
        }
        print(f"Apply gate internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_apply_gate(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    # Exit 0 if ready or applied
    ok_diagnoses = (_PHASE16D_DIAGNOSIS["ready"], _PHASE16D_DIAGNOSIS["applied"])
    exit_code = 0 if result.get("diagnosis") in ok_diagnoses else 1
    sys.exit(exit_code)


def command_32(args, parser):
    samples_req = getattr(args, "samples", 5)
    interval_sec = getattr(args, "interval", 10)
    try:
        result = _run_level1_post_promotion_stability_drill(
            samples_requested=samples_req,
            interval_seconds=interval_sec,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str,
            "drill_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}",
            "samples_requested": samples_req,
            "samples_collected": 0,
            "interval_seconds": interval_sec,
            "diagnosis": "unknown",
            "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [
                f"Internal error: {type(exc).__name__}",
                "Run ibkr-operator doctor",
            ],
            "git": {},
            "required_tags": {},
            "baseline": {},
            "samples": [],
            "stability_summary": {},
            "doctor_summary": {},
            "kpi_summary": {},
            "policy_summary": {},
            "promotion_allowed_now": False,
            "order_enablement_allowed_now": False,
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "h1_token_not_used": True,
            "evidence_hash": _compute_evidence_hash({"diagnosis": "unknown"}),
            "explicit_non_actions": _PHASE16E_EXPLICIT_NON_ACTIONS,
        }
        print(f"Stability drill internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_post_promotion_stability_drill(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16E_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_33(args, parser):
    try:
        result = _run_level1_evidence_normalization_check()
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str,
            "check_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}",
            "diagnosis": _PHASE16F_DIAGNOSIS["unknown"],
            "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [
                f"Internal error: {type(exc).__name__}",
                "Run ibkr-operator doctor",
            ],
            "git": {},
            "required_tags": {},
            "runtime": {},
            "autonomy": {},
            "safety": {},
            "guard_state": {},
            "normalization_summary": {},
            "kpi_summary": {},
            "doctor_summary": {},
            "policy_summary": {},
            "promotion_allowed_now": False,
            "order_enablement_allowed_now": False,
            "order_enablement_performed": False,
            "promotion_performed": False,
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "h1_token_not_used": True,
            "evidence_hash": _compute_evidence_hash({"diagnosis": _PHASE16F_DIAGNOSIS["unknown"]}),
            "explicit_non_actions": _PHASE16F_EXPLICIT_NON_ACTIONS,
        }
        print(f"Evidence normalization check internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_evidence_normalization_check(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16F_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_34(args, parser):
    demo_cand = getattr(args, "demo_candidates", 2)
    proposal_src = getattr(args, "proposal_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_proposal_workflow_drill(
            demo_candidates=demo_cand,
            proposal_source=proposal_src,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str,
            "drill_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}",
            "diagnosis": _PHASE16G_DIAGNOSIS["unknown"],
            "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [
                f"Internal error: {type(exc).__name__}",
                "Run ibkr-operator doctor",
            ],
            "git": {},
            "required_tags": {},
            "runtime": {},
            "autonomy": {},
            "safety": {},
            "guard_state": {},
            "proposal_workflow": {},
            "proposal_batch": {"batch_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}", "status": "error", "items": []},
            "workflow_summary": {},
            "kpi_summary": {},
            "doctor_summary": {},
            "policy_summary": {},
            "promotion_allowed_now": False,
            "order_enablement_allowed_now": False,
            "order_enablement_performed": False,
            "promotion_performed": False,
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "no_order_window_seen": True,
            "no_h1_seen": True,
            "h1_token_not_used": True,
            "evidence_hash": _compute_evidence_hash({"diagnosis": _PHASE16G_DIAGNOSIS["unknown"]}),
            "explicit_non_actions": _PHASE16G_EXPLICIT_NON_ACTIONS,
        }
        print(f"Proposal workflow drill internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_proposal_workflow_drill(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16G_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_35(args, parser):
    demo_cand = getattr(args, "demo_candidates", 2)
    try:
        result = _run_level1_human_review_package_drill(
            demo_candidates=demo_cand,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str,
            "drill_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}",
            "diagnosis": _PHASE16H_DIAGNOSIS["unknown"],
            "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [
                f"Internal error: {type(exc).__name__}",
                "Run ibkr-operator doctor",
            ],
            "git": {},
            "required_tags": {},
            "runtime": {},
            "autonomy": {},
            "safety": {},
            "guard_state": {},
            "review_workflow": {},
            "review_package": {"package_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}", "status": "error", "items": []},
            "workflow_summary": {},
            "kpi_summary": {},
            "doctor_summary": {},
            "policy_summary": {},
            "promotion_allowed_now": False,
            "order_enablement_allowed_now": False,
            "order_enablement_performed": False,
            "promotion_performed": False,
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "no_order_window_seen": True,
            "no_h1_seen": True,
            "h1_token_not_used": True,
            "evidence_hash": _compute_evidence_hash({"diagnosis": _PHASE16H_DIAGNOSIS["unknown"]}),
            "explicit_non_actions": _PHASE16H_EXPLICIT_NON_ACTIONS,
        }
        print(f"Review package drill internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_human_review_package_drill(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
        rp = result.get("review_package_path")
        if rp:
            print(f"  Review package written: {rp}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16H_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_36(args, parser):
    demo_cand = getattr(args, "demo_candidates", 2)
    decision_mode = getattr(args, "decision_mode", "mixed_demo")
    review_pkg = getattr(args, "review_package", None)
    try:
        result = _run_level1_review_decision_drill(
            demo_candidates=demo_cand,
            decision_mode=decision_mode,
            review_package_path=review_pkg,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str,
            "drill_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}",
            "diagnosis": _PHASE16I_DIAGNOSIS["unknown"],
            "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [
                f"Internal error: {type(exc).__name__}",
                "Run ibkr-operator doctor",
            ],
            "git": {},
            "required_tags": {},
            "runtime": {},
            "autonomy": {},
            "safety": {},
            "guard_state": {},
            "input_review_package": {},
            "review_decision": {"decisions_count": 0, "accepted_count": 0, "rejected_count": 0, "deferred_count": 0, "decision_items": []},
            "decision_artifact": {},
            "decision_artifact_hash": _compute_evidence_hash({}),
            "review_workflow": {},
            "workflow_summary": {},
            "kpi_summary": {},
            "doctor_summary": {},
            "policy_summary": {},
            "promotion_allowed_now": False,
            "order_enablement_allowed_now": False,
            "order_enablement_performed": False,
            "promotion_performed": False,
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "no_order_window_seen": True,
            "no_h1_seen": True,
            "h1_token_not_used": True,
            "evidence_hash": _compute_evidence_hash({"diagnosis": _PHASE16I_DIAGNOSIS["unknown"]}),
            "explicit_non_actions": _PHASE16I_EXPLICIT_NON_ACTIONS,
        }
        print(f"Review decision drill internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_review_decision_drill(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
        da = result.get("decision_artifact_path")
        if da:
            print(f"  Decision artifact written: {da}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16I_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_37(args, parser):
    demo_cand = getattr(args, "demo_candidates", 3)
    decision_mode = getattr(args, "decision_mode", "mixed_demo")
    decision_artifact = getattr(args, "decision_artifact", None)
    try:
        result = _run_level1_order_plan_draft_drill(
            demo_candidates=demo_cand,
            decision_mode=decision_mode,
            decision_artifact_path=decision_artifact,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str,
            "drill_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}",
            "diagnosis": _PHASE16J_DIAGNOSIS["unknown"],
            "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [
                f"Internal error: {type(exc).__name__}",
                "Run ibkr-operator doctor",
            ],
            "git": {},
            "required_tags": {},
            "runtime": {},
            "autonomy": {},
            "safety": {},
            "guard_state": {},
            "input_decision_artifact": {},
            "order_plan_draft": {"plan_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}", "status": "error", "draft_items": []},
            "plan_artifact": {},
            "plan_artifact_hash": _compute_evidence_hash({}),
            "plan_workflow": {},
            "workflow_summary": {},
            "kpi_summary": {},
            "doctor_summary": {},
            "policy_summary": {},
            "promotion_allowed_now": False,
            "order_enablement_allowed_now": False,
            "order_enablement_performed": False,
            "promotion_performed": False,
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "no_order_window_seen": True,
            "no_h1_seen": True,
            "h1_token_not_used": True,
            "evidence_hash": _compute_evidence_hash({"diagnosis": _PHASE16J_DIAGNOSIS["unknown"]}),
            "explicit_non_actions": _PHASE16J_EXPLICIT_NON_ACTIONS,
        }
        print(f"Order-plan draft drill internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_order_plan_draft_drill(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
        pa = result.get("plan_artifact_path")
        if pa:
            print(f"  Plan artifact written: {pa}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16J_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_38(args, parser):
    demo_cand = getattr(args, "demo_candidates", 3)
    decision_mode = getattr(args, "decision_mode", "mixed_demo")
    order_plan = getattr(args, "order_plan", None)
    sim_source = getattr(args, "simulation_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_preflight_simulation_dossier(
            demo_candidates=demo_cand,
            decision_mode=decision_mode,
            order_plan_path=order_plan,
            simulation_source=sim_source,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str,
            "dossier_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}",
            "diagnosis": _PHASE16K_DIAGNOSIS["unknown"],
            "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [
                f"Internal error: {type(exc).__name__}",
                "Run ibkr-operator doctor",
            ],
            "git": {},
            "required_tags": {},
            "runtime": {},
            "autonomy": {},
            "safety": {},
            "guard_state": {},
            "input_order_plan": {},
            "preflight_simulation": {"simulation_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}", "status": "error", "simulated_items": []},
            "dossier_artifact": {},
            "dossier_artifact_hash": _compute_evidence_hash({}),
            "simulation_workflow": {},
            "workflow_summary": {},
            "kpi_summary": {},
            "doctor_summary": {},
            "policy_summary": {},
            "promotion_allowed_now": False,
            "order_enablement_allowed_now": False,
            "order_enablement_performed": False,
            "promotion_performed": False,
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "no_order_window_seen": True,
            "no_h1_seen": True,
            "h1_token_not_used": True,
            "no_preflight_endpoint_called": True,
            "evidence_hash": _compute_evidence_hash({"diagnosis": _PHASE16K_DIAGNOSIS["unknown"]}),
            "explicit_non_actions": _PHASE16K_EXPLICIT_NON_ACTIONS,
        }
        print(f"Preflight simulation dossier internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_preflight_simulation_dossier(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
        da = result.get("dossier_artifact_path")
        if da:
            print(f"  Dossier artifact written: {da}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") in (_PHASE16K_DIAGNOSIS["ready"], _PHASE16K_DIAGNOSIS["no_draft_items_to_simulate"]) else 1
    sys.exit(exit_code)


def command_39(args, parser):
    demo_cand = getattr(args, "demo_candidates", 3)
    decision_mode = getattr(args, "decision_mode", "mixed_demo")
    preflight_dossier = getattr(args, "preflight_dossier", None)
    packet_source = getattr(args, "packet_source", "synthetic_readonly_demo")
    reviewer = getattr(args, "reviewer", "Chris")
    try:
        result = _run_level1_human_approval_packet_drill(
            demo_candidates=demo_cand,
            decision_mode=decision_mode,
            preflight_dossier_path=preflight_dossier,
            packet_source=packet_source,
            reviewer=reviewer,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str,
            "packet_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}",
            "diagnosis": _PHASE16L_DIAGNOSIS["unknown"],
            "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [
                f"Internal error: {type(exc).__name__}",
                "Run ibkr-operator doctor",
            ],
            "git": {},
            "required_tags": {},
            "runtime": {},
            "autonomy": {},
            "safety": {},
            "guard_state": {},
            "input_preflight_dossier": {},
            "human_approval_packet": {"packet_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}", "status": "error", "packet_items": []},
            "packet_artifact": {},
            "packet_artifact_hash": _compute_evidence_hash({}),
            "approval_workflow": {},
            "workflow_summary": {},
            "kpi_summary": {},
            "doctor_summary": {},
            "policy_summary": {},
            "promotion_allowed_now": False,
            "order_enablement_allowed_now": False,
            "order_enablement_performed": False,
            "promotion_performed": False,
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "no_order_window_seen": True,
            "no_h1_seen": True,
            "h1_token_not_used": True,
            "no_approval_endpoint_called": True,
            "evidence_hash": _compute_evidence_hash({"diagnosis": _PHASE16L_DIAGNOSIS["unknown"]}),
            "explicit_non_actions": _PHASE16L_EXPLICIT_NON_ACTIONS,
        }
        print(f"Human approval packet drill internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_human_approval_packet_drill(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
        pp = result.get("packet_artifact_path")
        if pp:
            print(f"  Packet artifact written: {pp}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") in (_PHASE16L_DIAGNOSIS["ready"], _PHASE16L_DIAGNOSIS["no_items_to_approve"]) else 1
    sys.exit(exit_code)


def command_40(args, parser):
    demo_cand = getattr(args, "demo_candidates", 3)
    decision_mode = getattr(args, "decision_mode", "mixed_demo")
    approval_packet = getattr(args, "approval_packet", None)
    packet_source = getattr(args, "packet_source", "synthetic_readonly_demo")
    reviewer = getattr(args, "reviewer", "Chris")
    try:
        result = _run_level1_execution_readiness_packet_drill(
            demo_candidates=demo_cand,
            decision_mode=decision_mode,
            approval_packet_path=approval_packet,
            packet_source=packet_source,
            reviewer=reviewer,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str,
            "packet_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}",
            "diagnosis": _PHASE16M_DIAGNOSIS["unknown"],
            "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [
                f"Internal error: {type(exc).__name__}",
                "Run ibkr-operator doctor",
            ],
            "git": {},
            "required_tags": {},
            "runtime": {},
            "autonomy": {},
            "safety": {},
            "guard_state": {},
            "input_approval_packet": {},
            "execution_readiness_packet": {"packet_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}", "status": "error", "readiness_items": []},
            "readiness_artifact": {},
            "readiness_artifact_hash": _compute_evidence_hash({}),
            "readiness_workflow": {},
            "workflow_summary": {},
            "kpi_summary": {},
            "doctor_summary": {},
            "policy_summary": {},
            "promotion_allowed_now": False,
            "order_enablement_allowed_now": False,
            "order_enablement_performed": False,
            "promotion_performed": False,
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "no_order_window_seen": True,
            "no_h1_seen": True,
            "h1_token_not_used": True,
            "no_preflight_endpoint_called": True,
            "no_approval_endpoint_called": True,
            "no_submit_endpoint_called": True,
            "evidence_hash": _compute_evidence_hash({"diagnosis": _PHASE16M_DIAGNOSIS["unknown"]}),
            "explicit_non_actions": _PHASE16M_EXPLICIT_NON_ACTIONS,
        }
        print(f"Execution-readiness packet drill internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_execution_readiness_packet_drill(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
        rp = result.get("readiness_artifact_path")
        if rp:
            print(f"  Readiness artifact written: {rp}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") in (_PHASE16M_DIAGNOSIS["ready"], _PHASE16M_DIAGNOSIS["no_items_to_assess"]) else 1
    sys.exit(exit_code)


def command_41(args, parser):
    demo_cand = getattr(args, "demo_candidates", 3)
    decision_mode = getattr(args, "decision_mode", "mixed_demo")
    chain_source = getattr(args, "chain_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_readiness_chain_integrity_checkpoint(
            demo_candidates=demo_cand,
            decision_mode=decision_mode,
            chain_source=chain_source,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str,
            "checkpoint_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}",
            "diagnosis": _PHASE16N_DIAGNOSIS["unknown"],
            "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [
                f"Internal error: {type(exc).__name__}",
                "Run ibkr-operator doctor",
            ],
            "git": {},
            "required_tags": {},
            "runtime": {},
            "autonomy": {},
            "safety": {},
            "guard_state": {},
            "chain_integrity": {"stages_expected_count": 7, "stages_verified_count": 0, "stages_missing": [], "stages": [], "chain_intact": False, "chain_complete": False, "chain_order_valid": False, "verdict": "CHAIN_BROKEN"},
            "chain_complete": False,
            "chain_order_valid": False,
            "all_stages_non_executable": False,
            "all_stages_advisory_or_readiness_only": False,
            "all_items_non_executable": False,
            "no_stage_authorizes_execution": False,
            "no_stage_calls_order_path": False,
            "no_stage_uses_h1": False,
            "no_stage_opens_order_window": False,
            "no_stage_creates_broker_order": False,
            "no_stage_mutates_broker": False,
            "no_stage_calls_trade_window_helper": False,
            "final_stage_readiness_only": False,
            "final_stage_execution_authorized_now": None,
            "final_stage_order_enablement_required": None,
            "readiness_chain_checkpoint": {
                "checkpoint_id": f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}",
                "status": "checkpoint_only",
                "checkpoint_source": "error",
                "executable": False,
                "execution_authorized_now": False,
                "order_enablement_required": True,
                "future_order_window_required": True,
                "future_h1_required": True,
                "future_real_preflight_required": True,
                "future_real_approval_required": True,
                "future_real_submit_required": True,
                "future_required_path": "/order/preflight -> /order/approve -> /order/submit",
            },
            "integrity_checklist": [],
            "workflow_summary": {},
            "no_order_path_called": True,
            "no_broker_order_created": True,
            "no_broker_submission": True,
            "kpi_summary": {},
            "doctor_summary": {},
            "policy_summary": {},
            "promotion_allowed_now": False,
            "order_enablement_allowed_now": False,
            "order_enablement_performed": False,
            "promotion_performed": False,
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "no_order_window_seen": True,
            "no_h1_seen": True,
            "h1_token_not_used": True,
            "no_preflight_endpoint_called": True,
            "no_approval_endpoint_called": True,
            "no_submit_endpoint_called": True,
            "evidence_hash": _compute_evidence_hash({"diagnosis": _PHASE16N_DIAGNOSIS["unknown"]}),
            "explicit_non_actions": _PHASE16N_EXPLICIT_NON_ACTIONS,
        }
        print(f"Chain integrity checkpoint internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_readiness_chain_integrity_checkpoint(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16N_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_42(args, parser):
    demo_cand = getattr(args, "demo_candidates", 3)
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_h1_boundary_audit_checkpoint(
            demo_candidates=demo_cand,
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str, "checkpoint_id": checkpoint_id,
            "canonical_trade_date": "?", "trade_date_stale": False,
            "halt_active": False, "guard_state_clean": False,
            "diagnosis": _PHASE16Q_DIAGNOSIS["unknown"], "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
            "git": {}, "required_tags": {}, "runtime": {}, "autonomy": {}, "safety": {}, "guard_state": {},
            "h1_boundary_audit": {"status": "control_failure", "audit_only": True, "canaries_count": 0,
                                  "checkpoint_id": checkpoint_id},
            "h1_dependent_controls": {"controls_count": 0, "controls_passed_count": 0, "controls_failed_count": 0, "controls": []},
            "h1_probe_matrix": {"raw_token_read_allowed": False, "raw_token_read_performed": False, "manual_canary_status": "MANUAL_REQUIRED"},
            "blocked_h1_attempts": [],
            "canary_intents": [],
            "h1_boundary_checklist": [], "workflow_summary": {},
            "all_canaries_blocked": False, "no_canary_executed": False,
            "h1_boundary_intact": False,
            "kpi_summary": {}, "doctor_summary": {}, "policy_summary": {},
            "promotion_allowed_now": False, "order_enablement_allowed_now": False,
            "order_enablement_performed": False, "promotion_performed": False,
            "execution_authorized_now": False, "execution_performed": False,
            "no_broker_mutation": True, "no_broker_order_created": True,
            "no_order_window_opened": True,
            "h1_token_not_used": True, "h1_token_not_read": True,
            "no_raw_token_read": True,
            "no_raw_token_value_seen": True,
            "no_raw_token_logged": True,
            "no_raw_token_copied": True,
            "no_raw_token_exported": True,
            "no_h1_header_constructed": True,
            "no_h1_header_sent": True,
            "no_approval_endpoint_called": True, "no_submit_endpoint_called": True,
            "no_order_endpoint_called": True, "no_preflight_endpoint_called": True,
            "no_trade_window_helper_called": True,
            "no_trade_window_helper_called_by_drill": True,
            "no_order_window_seen": True,
            "no_h1_seen": True,
            "h1_boundary_preserved": True,
            "manual_canary_required": True,
            "manual_canary_executed": False,
            "env_hash_only": True,
            "evidence_hash": _compute_evidence_hash({"diagnosis": _PHASE16Q_DIAGNOSIS["unknown"]}),
            "explicit_non_actions": _PHASE16Q_EXPLICIT_NON_ACTIONS,
        }
        print(f"H1 boundary audit internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_h1_boundary_audit_checkpoint(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16Q_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_43(args, parser):
    demo_cand = getattr(args, "demo_candidates", 3)
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_broker_mutation_firewall_audit_checkpoint(
            demo_candidates=demo_cand,
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str, "checkpoint_id": checkpoint_id,
            "canonical_trade_date": "?", "trade_date_stale": False,
            "halt_active": False, "guard_state_clean": False,
            "diagnosis": _PHASE16R_DIAGNOSIS["unknown"], "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
            "git": {}, "required_tags": {}, "runtime": {}, "autonomy": {}, "safety": {}, "guard_state": {},
            "broker_mutation_firewall": {"status": "control_failure", "audit_only": True,
                                            "canaries_count": 0, "checkpoint_id": checkpoint_id},
            "mutation_surface_audit": {"surfaces_count": 0, "surfaces_passed_count": 0,
                                         "surfaces_failed_count": 0, "surfaces": []},
            "read_only_evidence": {"evidence_paths_count": 0, "evidence_paths": [],
                                   "only_export_artifacts_written": True,
                                   "no_runtime_config_mutation": True,
                                   "no_env_mutation": True, "no_rules_mutation": True,
                                   "no_guard_repair_performed": True,
                                   "no_service_restart": True, "no_reconnect_attempted": True},
            "mutation_probe_matrix": {"bridge_read_only": True, "bridge_allow_orders": False,
                                      "env_allow_orders": True, "system_locked": True,
                                      "broker_submission_allowed": False},
            "blocked_mutation_attempts": [], "canary_intents": [],
            "broker_mutation_checklist": [], "workflow_summary": {},
            "all_canaries_blocked": False, "no_canary_executed": False,
            "broker_mutation_firewall_intact": False,
            "kpi_summary": {}, "doctor_summary": {}, "policy_summary": {},
            "promotion_allowed_now": False, "order_enablement_allowed_now": False,
            "order_enablement_performed": False, "promotion_performed": False,
            "execution_authorized_now": False, "execution_performed": False,
            "no_broker_mutation": True, "no_broker_order_created": True,
            "no_broker_submission": True, "no_account_mutation": True,
            "no_position_mutation": True, "no_order_window_opened": True,
            "no_h1_token_used": True, "no_h1_token_read": True,
            "no_h1_header_constructed": True, "no_h1_header_sent": True,
            "no_order_endpoint_called": True, "no_preflight_endpoint_called": True,
            "no_approval_endpoint_called": True, "no_submit_endpoint_called": True,
            "no_trade_window_helper_called": True,
            "no_trade_window_helper_called_by_drill": True,
            "no_mutation_endpoint_called": True,
            "no_order_mutation": True,
            "h1_token_not_used": True,
            "all_mutation_surfaces_blocked": False,
            "all_blocks_expected": False,
            "current_level": 0,
            "evidence_hash": _compute_evidence_hash({"diagnosis": _PHASE16R_DIAGNOSIS["unknown"]}),
            "explicit_non_actions": _PHASE16R_EXPLICIT_NON_ACTIONS,
        }
        print(f"Broker-mutation firewall audit internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_broker_mutation_firewall_audit_checkpoint(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16R_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_44(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_end_to_end_safety_invariant_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str, "checkpoint_id": checkpoint_id,
            "canonical_trade_date": "?", "trade_date_stale": False,
            "halt_active": False, "guard_state_clean": False,
            "diagnosis": _PHASE16S_DIAGNOSIS["unknown"], "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
            "git": {}, "required_tags": {}, "runtime": {}, "autonomy": {}, "safety": {}, "guard_state": {},
            "end_to_end_safety_invariant": {"status": "invariant_broken", "all_boundaries_intact": False},
            "invariant_matrix": {},
            "invariant_checklist": [],
            "kpi_acceptable": False, "doctor_acceptable": False,
            "policy_boundary_ok": False, "mutation_boundary_ok": True,
            "h1_boundary_ok": True, "order_window_boundary_ok": True,
            "execution_gate_boundary_ok": True,
            "kpi_summary": {}, "doctor_summary": {}, "policy_summary": {},
            "promotion_allowed_now": False, "order_enablement_allowed_now": False,
            "order_enablement_performed": False, "promotion_performed": False,
            "execution_authorized_now": False, "execution_performed": False,
            "current_level": 0,
            "no_broker_mutation": True, "no_broker_order_created": True,
            "no_broker_submission": True, "no_account_mutation": True,
            "no_position_mutation": True, "no_order_mutation": True,
            "no_order_window_opened": True, "no_mutation_endpoint_called": True,
            "h1_token_not_used": True, "no_h1_token_used": True,
            "no_h1_token_read": True,
            "no_h1_header_constructed": True, "no_h1_header_sent": True,
            "no_order_endpoint_called": True, "no_preflight_endpoint_called": True,
            "no_approval_endpoint_called": True, "no_submit_endpoint_called": True,
            "no_trade_window_helper_called": True,
            "no_trade_window_helper_called_by_drill": True,
            "all_mutation_surfaces_blocked": True, "all_blocks_expected": True,
            "evidence_hash": _compute_evidence_hash({"diagnosis": _PHASE16S_DIAGNOSIS["unknown"]}),
            "explicit_non_actions": _PHASE16S_EXPLICIT_NON_ACTIONS,
        }
    if args.export and not result.get("export_path"):
        # export was already done in run function; re-export here
        try:
            _PHASE16S_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            ep = _PHASE16S_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            import json as _json
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_end_to_end_safety_invariant_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16S_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_45(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_restart_persistence_safety_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str, "checkpoint_id": checkpoint_id,
            "diagnosis": _PHASE16T_DIAGNOSIS["unknown"], "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
            "git": {}, "required_tags": {},
            "before": {}, "after": {},
            "restart_performed": False, "restart_attempted": False,
            "restart_command_timed_out": False,
            "restart_target": _PHASE16T_BRIDGE_SERVICE,
            "restart_error": f"{type(exc).__name__}",
            "bridge_reachable_after_restart": False,
            "recovery_poll_seconds": None,
            "service_active_after_seconds": None,
            "health_reachable_after_seconds": None,
            "connected_after_seconds": None,
            "kpi_healthy_after_seconds": None,
            "sixteen_s_after_exit": None,
            "guard_state_clean": False, "guard_state": {},
            "sixteen_s_invariant_ok": False,
            "sixteen_s_before_exit": None,
            "sixteen_s_before_timestamp": "?",
            "sixteen_s_before_checkpoint_id": "?",
            "sixteen_s_before_export_path": None,
            "sixteen_s_before_diagnosis": "?",
            "sixteen_s_before_severity": "?",
            "sixteen_s_before_runtime_connected": False,
            "sixteen_s_before_guard_state_clean": False,
            "sixteen_s_before_invariant_intact": False,
            "sixteen_s_before_all_boundaries_intact": False,
            "sixteen_s_before_summary": {"diagnosis": "?", "severity": "?", "invariant_intact": False, "exit_code": None, "runtime_connected": False, "guard_state_clean": False, "all_boundaries_intact": False},
            "sixteen_s_after_summary": {"diagnosis": "N/A (not run)", "severity": "N/A (not run)", "invariant_intact": False},
            "restart_persistence_audit": {
                "invariant_survived": False,
                "restart_attempted": False,
                "restart_performed": False,
                "restart_command_timed_out": False,
                "restart_target": _PHASE16T_BRIDGE_SERVICE,
            },
            "no_broker_mutation": True, "no_broker_order_created": True,
            "no_broker_submission": True, "no_account_mutation": True,
            "no_position_mutation": True, "no_order_mutation": True,
            "no_order_window_opened": True, "no_mutation_endpoint_called": True,
            "no_order_endpoint_called": True, "no_preflight_endpoint_called": True,
            "no_approval_endpoint_called": True, "no_submit_endpoint_called": True,
            "h1_token_not_used": True, "no_h1_token_used": True,
            "no_h1_token_read": True, "no_h1_header_constructed": True,
            "no_h1_header_sent": True, "no_trade_window_helper_called": True,
            "no_trade_window_helper_called_by_drill": True,
            "all_mutation_surfaces_blocked": True, "all_blocks_expected": True,
            "execution_authorized_now": False, "order_enablement_allowed_now": False,
            "order_enablement_performed": False, "execution_performed": False,
            "current_level": 1,
            "evidence_hash": _compute_evidence_hash({"diagnosis": _PHASE16T_DIAGNOSIS["unknown"]}),
            "explicit_non_actions": _PHASE16T_EXPLICIT_NON_ACTIONS,
        }
    if args.export and not result.get("export_path"):
        try:
            _PHASE16T_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            ep = _PHASE16T_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            import json as _json
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_restart_persistence_safety_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16T_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_46(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_startup_autoconnect_resilience_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"16u-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase16u_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE16U_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE16U_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            ep = _PHASE16U_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            import json as _json
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_startup_autoconnect_resilience_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16U_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_47(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_guard_state_rollover_resilience_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"16v-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase16v_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE16V_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE16V_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE16V_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_guard_state_rollover_resilience_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16V_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_48(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_scheduled_heartbeat_alerting_resilience_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"16w-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase16w_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE16W_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE16W_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE16W_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_scheduled_heartbeat_alerting_resilience_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16W_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_49(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_os_boundary_h1_isolation_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"16x-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase16x_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE16X_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE16X_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE16X_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_os_boundary_h1_isolation_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16X_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_50(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_portable_tests_ci_readiness_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"16y-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase16y_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE16Y_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE16Y_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE16Y_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_portable_tests_ci_readiness_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16Y_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_51(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_fresh_clone_ci_workflow_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"16z-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase16z_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE16Z_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE16Z_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE16Z_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_fresh_clone_ci_workflow_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16Z_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_72(args, parser):
    demo_cand = getattr(args, "demo_candidates", 3)
    chain_source = getattr(args, "chain_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_order_window_canary_negative_control_drill(
            demo_candidates=demo_cand,
            chain_source=chain_source,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        drill_id = f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str, "drill_id": drill_id,
            "diagnosis": _PHASE16P_DIAGNOSIS["unknown"], "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
            "git": {}, "required_tags": {}, "runtime": {}, "autonomy": {}, "safety": {}, "guard_state": {},
            "order_window_canary": {"status": "control_failure", "negative_control_only": True, "canaries_count": 0,
                                    "canary_id": drill_id, "canary_type": "ORDER_WINDOW_NEGATIVE_CONTROL"},
            "canary_negative_controls": {"controls_count": 0, "controls_passed_count": 0, "controls_failed_count": 0, "controls": []},
            "h1_boundary_probe": {"probe_only": True, "raw_token_read": False, "h1_header_sent": False, "manual_canary_required": True},
            "order_window_matrix": {"level1_execution_allowed": False, "order_window_open": False, "orders_enabled": False},
            "blocked_canary_attempts": [],
            "canary_intents": [],
            "order_window_checklist": [], "workflow_summary": {},
            "all_canaries_blocked": False, "no_canary_executed": False,
            "order_window_closed_as_expected": False,
            "kpi_summary": {}, "doctor_summary": {}, "policy_summary": {},
            "promotion_allowed_now": False, "order_enablement_allowed_now": False,
            "order_enablement_performed": False, "promotion_performed": False,
            "no_broker_mutation": True, "no_broker_order_created": True,
            "no_order_window_opened": True, "no_order_window_seen": True,
            "no_h1_seen": True, "h1_token_not_used": True,
            "no_preflight_endpoint_called": True, "no_approval_endpoint_called": True,
            "no_submit_endpoint_called": True, "no_order_endpoint_called": True,
            "no_trade_window_helper_called": True,
            "no_trade_window_helper_called_by_drill": True,
            "evidence_hash": _compute_evidence_hash({"diagnosis": _PHASE16P_DIAGNOSIS["unknown"]}),
            "explicit_non_actions": _PHASE16P_EXPLICIT_NON_ACTIONS,
        }
        print(f"Order-window canary drill internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_order_window_canary_negative_control_drill(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16P_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_73(args, parser):
    demo_cand = getattr(args, "demo_candidates", 3)
    decision_mode = getattr(args, "decision_mode", "mixed_demo")
    chain_source = getattr(args, "chain_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_execution_gate_negative_control_drill(
            demo_candidates=demo_cand,
            decision_mode=decision_mode,
            chain_source=chain_source,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        drill_id = f"error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = {
            "command": f"ibkr-operator {args.command}",
            "timestamp": ts_str, "drill_id": drill_id,
            "diagnosis": _PHASE16O_DIAGNOSIS["unknown"], "severity": "NO_GO",
            "operator_action_required": True,
            "suggested_operator_actions": [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
            "git": {}, "required_tags": {}, "runtime": {}, "autonomy": {}, "safety": {}, "guard_state": {},
            "negative_control_plan": {"execution_intents_count": 0, "execution_intents": [], "all_intents_blocked": False},
            "execution_gate_negative_controls": {"status": "control_failure", "negative_control_only": True, "controls_count": 0},
            "blocked_execution_attempts": [],
            "gate_matrix": {"level1_execution_allowed": False, "readiness_chain_sufficient_for_execution": False},
            "negative_control_checklist": [], "workflow_summary": {},
            "execution_blocked_as_expected": False, "all_intents_blocked": False, "no_intent_executed": False,
            "kpi_summary": {}, "doctor_summary": {}, "policy_summary": {},
            "promotion_allowed_now": False, "order_enablement_allowed_now": False,
            "order_enablement_performed": False, "promotion_performed": False,
            "execution_authorized_now": False, "execution_performed": False,
            "no_broker_mutation": True, "no_broker_order_created": True,
            "no_order_window_opened": True, "no_order_window_seen": True,
            "no_h1_seen": True, "h1_token_not_used": True,
            "no_preflight_endpoint_called": True, "no_approval_endpoint_called": True,
            "no_submit_endpoint_called": True, "no_order_endpoint_called": True,
            "no_trade_window_helper_called": True,
            "evidence_hash": _compute_evidence_hash({"diagnosis": _PHASE16O_DIAGNOSIS["unknown"]}),
            "explicit_non_actions": _PHASE16O_EXPLICIT_NON_ACTIONS,
        }
        print(f"Negative-control drill internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_execution_gate_negative_control_drill(result)
    if args.export:
        ep = result.get("export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE16O_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)
