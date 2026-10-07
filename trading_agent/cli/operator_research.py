from trading_agent.cli.operator_common import (_PHASE18A_DIAGNOSIS, _PHASE18A_EXPORT_DIR, _PHASE18B_DIAGNOSIS, _PHASE18R1_DIAGNOSIS, _PHASE18R2_DIAGNOSIS, datetime, json, sys, timezone)
from trading_agent.cli.operator_research_helpers import (_phase18a_no_go, _phase18b_no_go, _phase18r1_no_go, _phase18r2_no_go, _run_level1_data_schema_provider_governance_checkpoint, _run_level1_model_routing_governance_checkpoint, _run_level1_mstr_btc_research_proposal_governance_checkpoint, _run_level1_openclaw_routing_adapter_checkpoint, _run_model_routing_activation_plan, _run_model_routing_adapter_decision, _run_model_routing_decision)

def command_64(args, parser):
    try:
        result = _run_level1_mstr_btc_research_proposal_governance_checkpoint()
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"18a-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase18a_no_go(
            checkpoint_id, ts_str,
            _PHASE18A_DIAGNOSIS["unknown"],
            [f"Internal error: {type(exc).__name__}"],
        )
    if args.export and not result.get("export_path"):
        try:
            _PHASE18A_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            ep = _PHASE18A_EXPORT_DIR / f"{result.get('checkpoint_id', 'error')}.json"
            with open(ep, "w", encoding="utf-8") as f:
                _json.dump(result, f, indent=2, default=str)
            result["export_path"] = str(ep)
            result["artifact_created"] = True
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        # Human-readable output
        print("=" * 60)
        print(f"Phase 18A: MSTR/BTC Research Proposal Governance")
        print(f"Version:       {result.get('checkpoint_version', '?')}")
        print(f"Checkpoint:    {result.get('checkpoint_id', '?')}")
        print(f"Timestamp:     {result.get('timestamp', '?')}")
        print(f"Diagnosis:     {result.get('diagnosis', '?')}")
        print(f"Severity:      {result.get('severity', '?')}")
        print("-" * 60)
        print(f"Proposal:      {result.get('proposal_id', '?')}")
        print(f"Status:        {result.get('proposal_status', '?')}")
        print(f"Governance:    {result.get('governance_state', '?')}")
        print(f"Readiness:     {result.get('strategy_readiness', '?')}")
        print(f"Autonomy:      Level {result.get('autonomy_level', '?')}")
        print(f"Exec Scope:    {result.get('execution_scope', '?')}")
        print(f"Options:       {result.get('options_scope', '?')}")
        print("-" * 60)
        di = result.get('document_integrity', {})
        for doc_key, doc_info in di.items():
            print(f"  {doc_key}: present={doc_info.get('present', '?')}")
        mi = result.get('manifest_integrity', {})
        print(f"  manifest:     valid={mi.get('valid_json', '?')} fields={mi.get('proposal_identity_fields_valid', '?')}")
        print(f"Evidence Hash: {result.get('deterministic_evidence_hash', '?')[:16]}...")
        print(f"Blockers:      {len(result.get('blockers', []))}")
        print("-" * 60)
        print(f"Labels: {', '.join(result.get('output_labels', ['?']))}")
        print(f"No broker mutation: {result.get('no_broker_mutation', '?')}")
        print(f"No network access:  {result.get('no_network_access', '?')}")
        print(f"No file mutation:   {result.get('no_file_mutation', '?')}")
        print("=" * 60)
        if args.export:
            ep = result.get("export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
    exit_code = 0 if result.get("diagnosis") == _PHASE18A_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_65(args, parser):
    try:
        result = _run_level1_data_schema_provider_governance_checkpoint()
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"18b-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase18b_no_go(checkpoint_id, ts_str, str(exc))
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print("=" * 60)
        print(f"Phase 18B: Data Schema & Provider Governance")
        print(f"Version:       {result.get('checkpoint_version', '?')}")
        print(f"Checkpoint:    {result.get('checkpoint_id', '?')}")
        print(f"Timestamp:     {result.get('timestamp', '?')}")
        print(f"Diagnosis:     {result.get('diagnosis', '?')}")
        print(f"Governance:    {result.get('governance_state', '?')}")
        print(f"Readiness:     {result.get('strategy_readiness', '?')}")
        print(f"Autonomy:      Level {result.get('autonomy_level', '?')}")
        print(f"Exec Scope:    {result.get('execution_scope', '?')}")
        print(f"Collection:    {result.get('collection_scope', '?')}")
        print(f"Provider:      {result.get('provider_binding_state', '?')}")
        print(f"Schema Count:  {result.get('schema_count', '?')}")
        print(f"Role Count:    {result.get('provider_role_count', '?')}")
        print(f"Evidence Hash: {result.get('deterministic_evidence_hash', '?')}")
        print("=" * 60)
        blockers = result.get('blockers', [])
        if blockers:
            print(f"Blockers ({len(blockers)}):")
            for b in blockers:
                print(f"  - {b}")
        else:
            print("Blockers:  0")
        print("=" * 60)
    exit_code = 0 if result.get("diagnosis", {}).get("ready") == _PHASE18B_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_66(args, parser):
    try:
        result = _run_level1_model_routing_governance_checkpoint()
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"18r1-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase18r1_no_go(checkpoint_id, ts_str, str(exc))
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print("=" * 60)
        print(f"Phase 18R1: Model-Routing Governance")
        print(f"Version:       {result.get('checkpoint_version', '?')}")
        print(f"Checkpoint:    {result.get('checkpoint_id', '?')}")
        print(f"Governance:    {result.get('governance_state', '?')}")
        print(f"Routing:       {result.get('routing_readiness', '?')}")
        print(f"Autonomy:      Level {result.get('autonomy_level', '?')}")
        print(f"Activation:    {result.get('routing_activation_scope', '?')}")
        print(f"Models:        {result.get('catalog_model_count', '?')}")
        print(f"Routes:        {result.get('approved_route_count', '?')}")
        print(f"Evidence Hash: {result.get('deterministic_evidence_hash', '?')}")
        print("=" * 60)
        blockers = result.get('blockers', [])
        if blockers:
            print(f"Blockers ({len(blockers)}):")
            for b in blockers:
                print(f"  - {b}")
        else:
            print("Blockers:  0")
        print("=" * 60)
    exit_code = 0 if result.get("diagnosis", {}).get("ready") == _PHASE18R1_DIAGNOSIS["ready"] else 1
    sys.exit(exit_code)


def command_67(args, parser):
    result = _run_model_routing_decision(args.input_file)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if result.get("routing_state") == "HOLD":
        sys.exit(1)
    sys.exit(0)


def command_68(args, parser):
    try:
        result = _run_level1_openclaw_routing_adapter_checkpoint()
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"18r2-error-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
        result = _phase18r2_no_go(checkpoint_id, ts_str, str(exc))
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print("=" * 60)
        print(f"Phase 18R2: OpenClaw Routing Adapter")
        print(f"Governance:    {result.get('governance_state', '?')}")
        print(f"Adapter:       {result.get('adapter_readiness', '?')}")
        print(f"Mode:          {result.get('adapter_mode', '?')}")
        print(f"Live Changed:  {result.get('live_routing_changed', '?')}")
        print(f"Evidence Hash: {result.get('deterministic_evidence_hash', '?')}")
        print("=" * 60)
        blockers = result.get('blockers', [])
        if blockers:
            print(f"Blockers ({len(blockers)}):")
            for b in blockers:
                print(f"  - {b}")
        else:
            print("Blockers:  0")
        print("=" * 60)
    diag = result.get("diagnosis", {})
    _ready_val = diag.get("ready")
    _status_val = diag.get("status", "")
    # exit 0: ready=True (all clear) or status is pending (PENDING_INPUT is still valid checkpoint)
    # exit 1: checkpoint_failed, internal_error, blocked, or unknown
    if _ready_val is True or _status_val == _PHASE18R2_DIAGNOSIS["pending"]:
        exit_code = 0
    else:
        exit_code = 1
    sys.exit(exit_code)


def command_70(args, parser):
    result = _run_model_routing_adapter_decision(
        args.routing_request_file, args.routing_decision_file
    )
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if result.get("adapter_state") == "HOLD":
        sys.exit(1)
    sys.exit(0)


def command_71(args, parser):
    result = _run_model_routing_activation_plan()
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if result.get("plan_state") == "BLOCKED":
        sys.exit(1)
    sys.exit(0)
