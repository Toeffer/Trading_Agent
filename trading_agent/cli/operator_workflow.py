from trading_agent.cli.operator_legacy import (BOLD, GREEN, OPENCLAW_DIR, RED, RESET, STATE_ALIASES, VALID_STATES, _make_recovery_drill_error_result, _print_evidence_cycle, _print_guard_state_reconcile, _print_hermes_result, _print_maintenance, _print_market_data_diagnostics, _print_position_drift_reconcile, _print_prereg_pin_verify, _repair_stale_alerts, _run_autonomy_review, _run_autonomy_status, _run_backpressure_drain_drill, _run_candidate_dryrun, _run_connected_endpoint_evidence_drill, _run_connected_readonly_stability_drill, _run_contract_qualification_drill, _run_cycle_rehearsal, _run_evidence_cycle, _run_guard_state_drift_sentinel, _run_guard_state_reconcile, _run_heartbeat, _run_hermes_canary, _run_hermes_proposal, _run_locked_preflight_proof, _run_market_data_diagnostics, _run_market_data_recovery_drill, _run_openclaw_route_decide, _run_position_drift_reconcile, _run_post_gateway_reconnect_proof, _run_prereg_pin_verify, _run_reconnect_readiness_drill, datetime, export_candidate_dryrun, export_cycle_rehearsal, export_kpi, json, print_autonomy_review, print_autonomy_status, print_candidate_dryrun, print_checklist, print_cycle_rehearsal, print_daily_report, print_doctor, print_export, print_freeze, print_kpi, print_repair_evidence, run_checklist, run_daily_report, run_doctor, run_export, run_freeze, run_kpi, sys, timezone, write_export)

def command_0(args, parser):
    result = run_daily_report()
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print_daily_report(result)
    return


def command_1(args, parser):
    if args.verify:
        from bundle_audit import verify_export
        vpath = None if args.verify == "latest" else args.verify
        vresult = verify_export(vpath)
        if args.json:
            print(json.dumps(vresult, indent=2, default=str))
        else:
            v_verdict = "PASS" if vresult["pass"] else "FAIL"
            v_color = GREEN if vresult["pass"] else RED
            print(f"Export Verification: {v_color}{v_verdict}{RESET}")
            print(f"  Source: {vresult.get('source', '?')}")
            print(f"  {vresult.get('passed_count', 0)}/{vresult.get('check_count', 0)}")
            for c in vresult.get("checks", []):
                c_status = f"{GREEN}PASS{RESET}" if c["ok"] else f"{RED}FAIL{RESET}"
                print(f"  {c_status} {c['check']}: {c['detail']}")
        return

    result = run_export()
    if args.save:
        out_path = write_export(result)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"Export written: {out_path}\n")
            print_export(result)
    elif args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print_export(result)
    return


def command_2(args, parser):
    from bundle_audit import (
        maintenance_report,
        execute_prune,
        plan_prune,
        ProtectedPathError,
    )

    has_prune_flag = args.prune_audit or args.prune_releases or args.prune_exports

    if has_prune_flag:
        # Prune mode — requires explicit flags
        if args.dry_run:
            result = plan_prune(
                keep_audit=args.keep_audit,
                keep_releases=args.keep_releases,
                keep_exports=args.keep_exports,
            )
        else:
            try:
                result = execute_prune(
                    keep_audit=args.keep_audit if args.prune_audit else 0,
                    keep_releases=args.keep_releases if args.prune_releases else 0,
                    keep_exports=args.keep_exports,
                    prune_exports=args.prune_exports,
                    dry_run=False,
                )
            except ProtectedPathError as e:
                print(f"SAFETY BLOCKED: {e}", file=sys.stderr)
                sys.exit(99)
    else:
        # Default: read-only report
        result = maintenance_report()

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_maintenance(result)
    return


def command_3(args, parser):
    if args.canary:
        result = _run_hermes_canary()
    else:
        result = _run_hermes_proposal(args.symbol, args.side, args.qty)
    if args.json or args.canary:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_hermes_result(result)
    if args.output and result.get("ok"):
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Output saved to {args.output}")
    return


def command_4(args, parser):
    result = run_doctor()
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print_doctor(result)
    if not result.get("pass", False):
        sys.exit(2)
    return


def command_5(args, parser):
    result = run_freeze()
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print_freeze(result)
    if not result.get("pass", False):
        sys.exit(2)
    return


def command_6(args, parser):
    result = _run_heartbeat()
    artifact_path = result.pop("_artifact_path", None)
    if args.json:
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
    elif not args.quiet:
        endpoints_healthy = result.get("all_endpoints_ok", result.get("ok", False))
        artifact_written = result.get("ok", False)
        if not artifact_written:
            status_str = f"{RED}FAIL{RESET}"
        elif endpoints_healthy:
            status_str = f"{GREEN}OK{RESET}"
        else:
            status_str = f"{RED}DEGRADED{RESET}"
        print(f"{BOLD}IBKR Bridge Heartbeat{RESET}  [{status_str}]")
        print(f"  Timestamp:      {result['timestamp']}")
        print(f"  Bridge:          {result['bridge_url']}")
        print(f"  Connected:       {result['connected']}")
        print(f"  Read-only:       {result['read_only']}")
        print(f"  Allow orders:    {result['allow_orders']}")
        print(f"  Startup safety:  {result['startup_safety_count']} "
              f"({'PASS' if result.get('startup_safety_pass') else 'N/A'})")
        print(f"  Positions:       {result['positions_count']}")
        print(f"  Live alerts:     {result['live_alert_count']}")
        print(f"  Reconciliation:  {'PASS' if result.get('reconciliation_passed') else 'N/A'}")
        print(f"  Endpoints:       {result['endpoints_ok']}/{result['endpoints_total']} OK")
        if result["endpoint_failures"]:
            for f in result["endpoint_failures"]:
                print(f"    {RED}FAIL{RESET} {f}")
        if artifact_path:
            print(f"  Artifact:        {artifact_path}")
    sys.exit(0 if result["ok"] else 2)


def command_7(args, parser):
    evidence = _repair_stale_alerts(dry_run=not args.live)
    if args.json:
        print(json.dumps(evidence, indent=2, default=str))
    else:
        print_repair_evidence(evidence)
    if not args.live:
        print("\n  (dry-run only — use --live to apply repairs)")
    return


def command_8(args, parser):
    result = run_kpi()
    if args.export:
        export_path = export_kpi(result, OPENCLAW_DIR / "exports")
        result["_export_path"] = str(export_path)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print_kpi(result)
        if args.export:
            print(f"  Export written: {result.get('_export_path', '?')}\n")
    sys.exit(2 if result["verdict"] == "NO-GO" else 0)


def command_9(args, parser):
    result = _run_cycle_rehearsal()
    if args.export:
        export_path = export_cycle_rehearsal(result)
        result["_export_path"] = str(export_path)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print_cycle_rehearsal(result)
        if args.export:
            print(f"\n  Export written: {result.get('_export_path', '?')}")
    sys.exit(2 if result["verdict"] == "NO-GO" else 0)


def command_10(args, parser):
    result = _run_candidate_dryrun(args.symbol, args.side)
    if args.export:
        export_path = export_candidate_dryrun(result)
        result["_export_path"] = str(export_path)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print_candidate_dryrun(result)
        if args.export:
            print(f"  Export written: {result.get('_export_path', '?')}")
    exit_code = 2 if result["verdict"] == "NO-GO" else (0 if result["verdict"] == "READY_DRYRUN" else 1)
    sys.exit(exit_code)


def command_11(args, parser):
    result = _run_evidence_cycle(args.symbol, args.side, record=args.record)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_evidence_cycle(result)
    exit_code = 0 if result["clean"] else 1
    sys.exit(exit_code)


def command_12(args, parser):
    refresh = getattr(args, "refresh_evidence", False)
    result = _run_autonomy_status(refresh_evidence=refresh)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print_autonomy_status(result)
    if args.export:
        exports = result.get("evidence_exports", [])
        if exports:
            print(f"  Export written: {exports[0]}", file=sys.stderr)
    exit_code = 0 if result["recommendation"] == "READY_FOR_MANUAL_REVIEW" else 1
    sys.exit(exit_code)


def command_13(args, parser):
    refresh = getattr(args, "refresh_evidence", False)
    result = _run_autonomy_review(target_level=args.target_level, refresh_evidence=refresh)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print_autonomy_review(result)
    if args.export:
        ep = result.get("_export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result["review_status"] == "READY_FOR_OPERATOR_REVIEW" else 1
    sys.exit(exit_code)


def command_15(args, parser):
    apply_flag = getattr(args, "apply", False)
    confirm_flag = getattr(args, "confirm_local_state_repair", False)
    result = _run_guard_state_reconcile(
        apply_repair=apply_flag,
        confirm_local_state_repair=confirm_flag,
    )
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_guard_state_reconcile(result)
    if args.export:
        ep = result.get("_export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("repair_recommended") or result.get("repair_applied") else 1
    sys.exit(exit_code)


def command_16(args, parser):
    apply_flag = getattr(args, "apply", False)
    confirm_flag = getattr(args, "confirm_local_state_repair", False)
    symbol_flag = getattr(args, "symbol", None)
    result = _run_position_drift_reconcile(
        apply_repair=apply_flag,
        confirm_local_state_repair=confirm_flag,
        symbol_filter=symbol_flag,
    )
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_position_drift_reconcile(result)
    if args.export:
        ep = result.get("_export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("repair_recommended") or result.get("repair_applied") else 1
    sys.exit(exit_code)


def command_17(args, parser):
    result = _run_prereg_pin_verify(doc_path=getattr(args, "doc", None))
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_prereg_pin_verify(result)
    sys.exit(0 if result.get("pass") else 1)


def command_18(args, parser):
    symbol = getattr(args, "symbol", "AAPL")
    result = _run_market_data_diagnostics(symbol=symbol)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_market_data_diagnostics(result)
    if args.export:
        ep = result.get("_export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result["severity"] in ("OK", "HOLD") else 1
    sys.exit(exit_code)


def command_19(args, parser):
    symbol = getattr(args, "symbol", "AAPL")
    attempts = getattr(args, "attempts", 3)
    sleep_seconds = getattr(args, "sleep_seconds", 10.0)
    connect_if_needed = getattr(args, "connect_if_needed", True)
    try:
        result = _run_market_data_recovery_drill(
            symbol=symbol,
            attempts=attempts,
            sleep_seconds=sleep_seconds,
            connect_if_needed=connect_if_needed,
        )
    except Exception as exc:
        result = _make_recovery_drill_error_result(exc, symbol=symbol)
        # Log traceback to stderr only (stdout stays pure JSON)
        import traceback
        print(f"Recovery drill internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    # Pure JSON stdout
    print(json.dumps(result, indent=2, default=str))
    # Export messages to stderr
    if args.export:
        ep = result.get("_export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result["final_severity"] in ("OK", "HOLD") else 1
    sys.exit(exit_code)


def command_20(args, parser):
    observe_seconds = getattr(args, "observe_seconds", 15)
    poll_seconds = getattr(args, "poll_seconds", 3)
    include_endpoint_probes = getattr(args, "include_endpoint_probes", True)
    symbol = getattr(args, "symbol", "AAPL")
    try:
        result = _run_backpressure_drain_drill(
            observe_seconds=observe_seconds,
            poll_seconds=poll_seconds,
            include_endpoint_probes=include_endpoint_probes,
            symbol=symbol,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
        result = {
            "command": "ibkr-operator backpressure-drain-drill",
            "timestamp": ts_str,
            "drill_id": f"bp-drain-drill-{ts_file}",
            "diagnosis": "bridge_unreachable",
            "severity": "NO_GO",
            "internal_exception": True,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "_export_path": None,
        }
        print(f"Backpressure drain drill internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    # Pure JSON stdout
    print(json.dumps(result, indent=2, default=str))
    if args.export:
        ep = result.get("_export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("severity") in ("OK", "HOLD") else 1
    sys.exit(exit_code)


def command_21(args, parser):
    observe_seconds = getattr(args, "observe_seconds", 15)
    poll_seconds = getattr(args, "poll_seconds", 3)
    include_readonly_probes = getattr(args, "include_readonly_probes", True)
    fail_on_drift = getattr(args, "fail_on_drift", False)
    include_process_scan = getattr(args, "include_process_scan", True)
    try:
        result = _run_guard_state_drift_sentinel(
            observe_seconds=observe_seconds,
            poll_seconds=poll_seconds,
            include_readonly_probes=include_readonly_probes,
            fail_on_drift=fail_on_drift,
            include_process_scan=include_process_scan,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
        result = {
            "command": "ibkr-operator guard-state-drift-sentinel",
            "timestamp": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sentinel_id": f"gs-drift-sentinel-{ts_file}",
            "diagnosis": "unknown",
            "severity": "NO_GO",
            "internal_exception": True,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "_export_path": None,
        }
        print(f"Guard-state drift sentinel internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    print(json.dumps(result, indent=2, default=str))
    if args.export:
        ep = result.get("_export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("severity") in ("OK", "HOLD") else 1
    sys.exit(exit_code)


def command_22(args, parser):
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 4002)
    client_id = getattr(args, "client_id", 777)
    socket_timeout = getattr(args, "socket_timeout", 2)
    attempt_connect = getattr(args, "attempt_connect", False)
    try:
        result = _run_reconnect_readiness_drill(
            host=host,
            port=port,
            client_id=client_id,
            socket_timeout=socket_timeout,
            attempt_connect=attempt_connect,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
        result = {
            "command": "ibkr-operator reconnect-readiness-drill",
            "timestamp": ts_str,
            "drill_id": f"reconnect-readiness-drill-{ts_file}",
            "diagnosis": "unknown",
            "severity": "NO_GO",
            "internal_exception": True,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "_export_path": None,
        }
        print(f"Reconnect readiness drill internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    # Pure JSON stdout
    print(json.dumps(result, indent=2, default=str))
    if args.export:
        ep = result.get("_export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("severity") in ("OK", "HOLD") else 1
    sys.exit(exit_code)


def command_23(args, parser):
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 4002)
    client_id = getattr(args, "client_id", 777)
    socket_timeout = getattr(args, "socket_timeout", 2)
    attempt_connect = getattr(args, "attempt_connect", False)
    refresh_evidence = getattr(args, "refresh_evidence", True)
    symbol = getattr(args, "symbol", "AAPL")
    try:
        result = _run_post_gateway_reconnect_proof(
            host=host,
            port=port,
            client_id=client_id,
            socket_timeout=socket_timeout,
            attempt_connect=attempt_connect,
            refresh_evidence=refresh_evidence,
            symbol=symbol,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
        result = {
            "command": "ibkr-operator post-gateway-reconnect-proof",
            "timestamp": ts_str,
            "proof_id": f"post-gateway-reconnect-proof-{ts_file}",
            "diagnosis": "unknown",
            "severity": "NO_GO",
            "internal_exception": True,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "_export_path": None,
        }
        print(f"Post-gateway reconnect proof internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    # Pure JSON stdout
    print(json.dumps(result, indent=2, default=str))
    if args.export:
        ep = result.get("_export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("severity") in ("OK", "HOLD") else 1
    sys.exit(exit_code)


def command_24(args, parser):
    timeout_val = getattr(args, "timeout", 8)
    include_connected_only = getattr(args, "include_connected_only", True)
    strict = getattr(args, "strict", False)
    symbol = getattr(args, "symbol", "AAPL")
    try:
        result = _run_connected_endpoint_evidence_drill(
            timeout=timeout_val,
            include_connected_only=include_connected_only,
            strict=strict,
            symbol=symbol,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
        result = {
            "command": "ibkr-operator connected-endpoint-evidence-drill",
            "timestamp": ts_str,
            "drill_id": f"connected-endpoint-evidence-drill-{ts_file}",
            "diagnosis": "unknown",
            "severity": "NO_GO",
            "internal_exception": True,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "_export_path": None,
        }
        print(f"Endpoint evidence drill internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    print(json.dumps(result, indent=2, default=str))
    if args.export:
        ep = result.get("_export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("severity") in ("OK", "HOLD") else 1
    sys.exit(exit_code)


def command_25(args, parser):
    samples_n = getattr(args, "samples", 5)
    interval = getattr(args, "interval_seconds", 3)
    timeout_val = getattr(args, "timeout", 8)
    strict = getattr(args, "strict", False)
    try:
        result = _run_connected_readonly_stability_drill(
            samples=samples_n,
            interval_seconds=interval,
            timeout=timeout_val,
            strict=strict,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
        result = {
            "command": "ibkr-operator connected-readonly-stability-drill",
            "timestamp": ts_str,
            "drill_id": f"connected-readonly-stability-drill-{ts_file}",
            "diagnosis": "unknown",
            "severity": "NO_GO",
            "internal_exception": True,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "_export_path": None,
        }
        print(f"Stability drill internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    print(json.dumps(result, indent=2, default=str))
    if args.export:
        ep = result.get("_export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("severity") in ("OK", "HOLD") else 1
    sys.exit(exit_code)


def command_26(args, parser):
    symbol = getattr(args, "symbol", "AAPL")
    action = getattr(args, "action", "BUY")
    quantity = getattr(args, "quantity", 1)
    order_type = getattr(args, "order_type", "MKT")
    timeout_val = getattr(args, "timeout", 8)
    samples_n = getattr(args, "samples", 1)
    strict = getattr(args, "strict", False)
    try:
        result = _run_locked_preflight_proof(
            symbol=symbol,
            action=action,
            quantity=quantity,
            order_type=order_type,
            timeout=timeout_val,
            samples=samples_n,
            strict=strict,
        )
    except Exception as exc:
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
        result = {
            "command": "ibkr-operator locked-preflight-proof",
            "timestamp": ts_str,
            "proof_id": f"locked-preflight-proof-{ts_file}",
            "diagnosis": "unknown",
            "severity": "NO_GO",
            "internal_exception": True,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "_export_path": None,
        }
        print(f"Preflight proof internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    print(json.dumps(result, indent=2, default=str))
    if args.export:
        ep = result.get("_export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("severity") in ("OK", "HOLD") else 1
    sys.exit(exit_code)


def command_27(args, parser):
    symbol = getattr(args, "symbol", "AAPL")
    sec_type = getattr(args, "sec_type", "STK")
    currency = getattr(args, "currency", "USD")
    exchange = getattr(args, "exchange", "SMART")
    primary_exchange = getattr(args, "primary_exchange", "")
    attempt_alternates = getattr(args, "attempt_alternates", True)
    max_attempts = getattr(args, "max_attempts", 5)
    try:
        result = _run_contract_qualification_drill(
            symbol=symbol,
            sec_type=sec_type,
            currency=currency,
            exchange=exchange,
            primary_exchange=primary_exchange,
            attempt_alternates=attempt_alternates,
            max_attempts=max_attempts,
        )
    except Exception as exc:
        # Build a safe error result (same contract as recovery drill errors)
        import traceback
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
        result = {
            "command": "ibkr-operator contract-qualification-drill",
            "timestamp": ts_str,
            "drill_id": f"cq-drill-{symbol}-{ts_file}",
            "symbol": symbol.upper().strip(),
            "contract_qualified": False,
            "root_cause": "bridge_runtime_error",
            "severity": "NO_GO",
            "internal_exception": True,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "_export_path": None,
        }
        print(f"CQ drill internal exception: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    # Pure JSON stdout
    print(json.dumps(result, indent=2, default=str))
    if args.export:
        ep = result.get("_export_path")
        if ep:
            print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("severity") in ("OK", "HOLD") else 1
    sys.exit(exit_code)


def command_69(args, parser):
    result = _run_openclaw_route_decide(args.input_file)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if result.get("adapter_state") == "HOLD":
        sys.exit(1)
    sys.exit(0)


def checklist(args, parser):
    raw_state = args.state
    state = None
    if raw_state:
        if raw_state in STATE_ALIASES:
            state = STATE_ALIASES[raw_state]
        elif raw_state in VALID_STATES:
            state = raw_state
        else:
            print(f"Error: Unknown state '{raw_state}'", file=sys.stderr)
            print(f"Valid: {', '.join(sorted(VALID_STATES))}", file=sys.stderr)
            sys.exit(1)
    if args.offline and state != "end-of-day":
        print("Warning: --offline only supported for end-of-day state. Ignoring.",
              file=sys.stderr)
    result = run_checklist(state_override=state)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print_checklist(result, explain=args.explain)
    has_block = any(b["status"] == "BLOCK" for b in result["blocks"])
    is_error = result["verdict"] in ("STOP", "ERROR")
    if has_block or is_error:
        sys.exit(2)
