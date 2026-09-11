from trading_agent.cli.operator_legacy import (_PHASE17A_DIAGNOSIS, _PHASE17A_EXPORT_DIR, _PHASE17B_DIAGNOSIS, _PHASE17B_EXPORT_DIR, _PHASE17C_DIAGNOSIS, _PHASE17C_EXPORT_DIR, _PHASE17D_DIAGNOSIS, _PHASE17D_EXPORT_DIR, _PHASE17E_DIAGNOSIS, _PHASE17E_EXPORT_DIR, _PHASE17F_DIAGNOSIS, _PHASE17F_EXPORT_DIR, _PHASE17G_DIAGNOSIS, _PHASE17G_EXPORT_DIR, _PHASE17H_DIAGNOSIS, _PHASE17H_EXPORT_DIR, _PHASE17I_DIAGNOSIS, _PHASE17I_EXPORT_DIR, _PHASE17J_DIAGNOSIS, _PHASE17J_EXPORT_DIR, _PHASE17K_DIAGNOSIS, _PHASE17K_EXPORT_DIR, _PHASE17L_DIAGNOSIS, _PHASE17L_EXPORT_DIR, _phase17a_no_go, _phase17b_no_go, _phase17c_no_go, _phase17d_no_go, _phase17e_no_go, _phase17f_no_go, _phase17g_no_go, _phase17h_no_go, _phase17i_no_go, _phase17j_no_go, _phase17k_no_go, _phase17l_no_go, _print_level1_guarded_preflight_request_draft_checkpoint, _print_level1_human_candidate_package_review_decision_record_checkpoint, _print_level1_human_review_decision_record_checkpoint, _print_level1_human_simulation_review_decision_record_checkpoint, _print_level1_phase17_chain_closure_checkpoint, _print_level1_planning_only_candidate_package_checkpoint, _print_level1_planning_only_order_plan_draft_checkpoint, _print_level1_planning_only_preflight_simulation_dossier_checkpoint, _print_level1_proposal_review_rejection_dossier_checkpoint, _print_level1_strategy_v1_dry_run_proposal_generation_checkpoint, _print_level1_strategy_v1_governance_checkpoint, _print_level1_strategy_v1_proposal_packet_schema_checkpoint, _run_level1_guarded_preflight_request_draft_checkpoint, _run_level1_human_candidate_package_review_decision_record_checkpoint, _run_level1_human_review_decision_record_checkpoint, _run_level1_human_simulation_review_decision_record_checkpoint, _run_level1_phase17_chain_closure_checkpoint, _run_level1_planning_only_candidate_package_checkpoint, _run_level1_planning_only_order_plan_draft_checkpoint, _run_level1_planning_only_preflight_simulation_dossier_checkpoint, _run_level1_proposal_review_rejection_dossier_checkpoint, _run_level1_strategy_v1_dry_run_proposal_generation_checkpoint, _run_level1_strategy_v1_governance_checkpoint, _run_level1_strategy_v1_proposal_packet_schema_checkpoint, datetime, json, sys, timezone)

def command_52(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_strategy_v1_governance_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"17a-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase17a_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE17A_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE17A_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE17A_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_strategy_v1_governance_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE17A_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_53(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_strategy_v1_proposal_packet_schema_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"17b-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase17b_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE17B_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE17B_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE17B_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_strategy_v1_proposal_packet_schema_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE17B_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_54(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_strategy_v1_dry_run_proposal_generation_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"17c-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase17c_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE17C_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE17C_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE17C_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_strategy_v1_dry_run_proposal_generation_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE17C_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_55(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_proposal_review_rejection_dossier_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"17d-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase17d_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE17D_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE17D_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE17D_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_proposal_review_rejection_dossier_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE17D_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_56(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_human_review_decision_record_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"17e-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase17e_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE17E_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE17E_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE17E_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_human_review_decision_record_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE17E_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_57(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_planning_only_order_plan_draft_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"17f-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase17f_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE17F_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE17F_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE17F_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_planning_only_order_plan_draft_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE17F_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_58(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_planning_only_preflight_simulation_dossier_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"17g-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase17g_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE17G_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE17G_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE17G_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_planning_only_preflight_simulation_dossier_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE17G_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_59(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_human_simulation_review_decision_record_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"17h-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase17h_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE17H_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE17H_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE17H_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_human_simulation_review_decision_record_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE17H_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_60(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_planning_only_candidate_package_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"17i-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase17i_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE17I_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE17I_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE17I_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_planning_only_candidate_package_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE17I_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_61(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    reviewer = getattr(args, "reviewer", "") or ""
    decision = getattr(args, "decision", "") or ""
    reason = getattr(args, "reason", "") or ""
    try:
        result = _run_level1_human_candidate_package_review_decision_record_checkpoint(
            audit_source=audit_source,
            reviewer=reviewer,
            decision=decision,
            reason=reason,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"17j-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase17j_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE17J_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE17J_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE17J_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_human_candidate_package_review_decision_record_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE17J_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_62(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    reviewer = getattr(args, "reviewer", "") or ""
    decision = getattr(args, "decision", "") or ""
    reason = getattr(args, "reason", "") or ""
    try:
        result = _run_level1_guarded_preflight_request_draft_checkpoint(
            audit_source=audit_source,
            reviewer=reviewer,
            decision=decision,
            reason=reason,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"17k-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase17k_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE17K_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE17K_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE17K_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_guarded_preflight_request_draft_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE17K_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_63(args, parser):
    audit_source = getattr(args, "audit_source", "synthetic_readonly_demo")
    try:
        result = _run_level1_phase17_chain_closure_checkpoint(
            audit_source=audit_source,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"17l-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase17l_no_go(
            checkpoint_id, ts_str,
            {"branch": "?", "commit": "?", "tag": "?", "worktree_clean": False},
            _PHASE17L_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}", "Run ibkr-operator doctor"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE17L_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE17L_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_level1_phase17_chain_closure_checkpoint(result)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE17L_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)
