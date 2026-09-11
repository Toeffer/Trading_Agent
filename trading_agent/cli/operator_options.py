from trading_agent.cli.operator_legacy import (VALID_STATES)

def configure(sub):
    cp = sub.add_parser("checklist", help="Run operator daily checklist")
    cp.add_argument("state", nargs="?", default=None,
                    help=f"Workflow state: {', '.join(sorted(VALID_STATES))}")
    cp.add_argument("--json", action="store_true", help="Output raw JSON only")
    cp.add_argument("--explain", action="store_true", help="Include rationale for checks")
    cp.add_argument("--offline", action="store_true",
                    help="End-of-day: file-based only, no bridge (subset of checks)")
    drp = sub.add_parser("daily-report", help="Consolidated daily operator report")
    drp.add_argument("--json", action="store_true",
                     help="Output raw JSON only")
    ep = sub.add_parser("export", help="Read-only evidence export")
    ep.add_argument("--json", action="store_true",
                    help="Output raw JSON only")
    ep.add_argument("--save", action="store_true",
                    help="Write export to ~/.openclaw/exports/ and print path")
    ep.add_argument("--verify", type=str, default=None, nargs="?", const="latest",
                    help="Verify an export file (default: latest)")
    docp = sub.add_parser("doctor", help="Operator self-test / environment diagnostics")
    docp.add_argument("--json", action="store_true",
                       help="Output raw JSON only")
    fp = sub.add_parser("freeze", help="Release freeze / full CLI evidence snapshot")
    fp.add_argument("--json", action="store_true",
                     help="Output raw JSON only")
    hp = sub.add_parser("hermes-proposal",
                         help="Generate Hermes-advised trade proposal (advisory only)")
    hp.add_argument("--json", action="store_true",
                    help="Output raw JSON only")
    hp.add_argument("--canary", action="store_true",
                    help="Test Hermes invocation and show evidence block")
    hp.add_argument("--symbol", type=str, default="AAPL",
                    help="Symbol for proposal (default: AAPL)")
    hp.add_argument("--side", type=str, default="BUY",
                    help="Side for proposal (default: BUY)")
    hp.add_argument("--qty", type=int, default=1,
                    help="Quantity for proposal (default: 1)")
    hp.add_argument("--output", type=str, default=None,
                    help="Save output to file")
    mp = sub.add_parser("maintenance", help="Audit/release artifact maintenance")
    mp.add_argument("--json", action="store_true",
                    help="Output raw JSON only")
    mp.add_argument("--dry-run", action="store_true",
                    help="Show what would be deleted without deleting anything")
    mp.add_argument("--prune-audit", action="store_true",
                    help="Prune old audit bundles (requires --keep-audit)")
    mp.add_argument("--prune-releases", action="store_true",
                    help="Prune old release tags (requires --keep-releases)")
    mp.add_argument("--keep-audit", type=int, default=None,
                    help="Number of audit bundles to keep (default: 20)")
    mp.add_argument("--keep-releases", type=int, default=None,
                    help="Number of release tags to keep (default: 20)")
    mp.add_argument("--prune-exports", action="store_true",
                    help="Prune old export files (requires --keep-exports)")
    mp.add_argument("--keep-exports", type=int, default=None,
                    help="Number of exports to keep (default: 20)")
    kpp = sub.add_parser("kpi", help="KPI / evidence dashboard with GO/HOLD/NO-GO verdict")
    kpp.add_argument("--json", action="store_true",
                     help="Output raw JSON only")
    kpp.add_argument("--export", action="store_true",
                     help="Write output to ~/.openclaw/exports/")
    krp = sub.add_parser("kpi-repair",
                         help="Repair proven-stale KPI alerts (orphans, trade count). No broker mutation.")
    krp.add_argument("--json", action="store_true",
                     help="Output raw JSON only")
    krp.add_argument("--live", action="store_true",
                     help="Execute the repair (default: dry-run only)")
    hbp = sub.add_parser("heartbeat", help="Run read-only bridge heartbeat")
    hbp.add_argument("--json", action="store_true",
                     help="Output raw JSON only")
    hbp.add_argument("--quiet", action="store_true",
                     help="Suppress human-readable output")
    crp = sub.add_parser("cycle-rehearsal", help="Run read-only autonomy cycle rehearsal")
    crp.add_argument("--json", action="store_true",
                     help="Output raw JSON only")
    crp.add_argument("--export", action="store_true",
                     help="Write output to ~/.openclaw/autonomy-cycles/")
    canp = sub.add_parser("candidate-dryrun",
                          help="Evidence-only paper-trade candidate dry-run")
    canp.add_argument("--symbol", required=True, type=str, help="Ticker symbol")
    canp.add_argument("--side", required=True, choices=["BUY", "SELL"],
                      help="Order side: BUY or SELL")
    canp.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    canp.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/candidate-dryruns/")
    ecp = sub.add_parser("evidence-cycle",
                         help="Read-only evidence bundle + clean-cycle ledger entry")
    ecp.add_argument("--symbol", required=True, type=str, help="Ticker symbol")
    ecp.add_argument("--side", required=True, choices=["BUY", "SELL"],
                      help="Order side: BUY or SELL")
    ecp.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    ecp.add_argument("--export", action="store_true",
                      help="Write candidate export to ~/.openclaw/candidate-dryruns/")
    ecp.add_argument("--record", action="store_true",
                      help="Append clean-cycle entry to ~/.openclaw/autonomy-cycles/clean-cycle-ledger.jsonl")
    asp = sub.add_parser("autonomy-status",
                         help="Autonomy readiness evaluator / promotion proposal")
    asp.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    asp.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/autonomy-status/")
    asp.add_argument("--refresh-evidence", "--refresh-connected-evidence",
                      action="store_true", dest="refresh_evidence",
                      help="Run fresh connected checks: doctor, KPI, candidate dry-run, market/FX snapshot")
    arp = sub.add_parser("autonomy-readiness",
                         help="Alias for autonomy-status")
    arp.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    arp.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/autonomy-status/")
    arp.add_argument("--refresh-evidence", "--refresh-connected-evidence",
                      action="store_true", dest="refresh_evidence",
                      help="Run fresh connected checks: doctor, KPI, candidate dry-run, market/FX snapshot")
    avp = sub.add_parser("autonomy-review",
                         help="Manual autonomy-promotion review package")
    avp.add_argument("--target-level", type=str, default="1",
                      help="Target autonomy level (default: 1)")
    avp.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    avp.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/autonomy-review/")
    pvp = sub.add_parser("promotion-review",
                         help="Alias for autonomy-review")
    pvp.add_argument("--target-level", type=str, default="1",
                      help="Target autonomy level (default: 1)")
    pvp.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    pvp.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/autonomy-review/")
    app = sub.add_parser("autonomy-promotion-plan",
                         help="Manual level-1 promotion procedure/spec (Step 15M)")
    app.add_argument("--target-level", type=str, default="1",
                      help="Target autonomy level (default: 1)")
    app.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    app.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/autonomy-promotion-plans/")
    ppp = sub.add_parser("promotion-plan",
                         help="Alias for autonomy-promotion-plan")
    ppp.add_argument("--target-level", type=str, default="1",
                      help="Target autonomy level (default: 1)")
    ppp.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    ppp.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/autonomy-promotion-plans/")
    l1p = sub.add_parser("level1-promotion-plan",
                         help="Alias for autonomy-promotion-plan")
    l1p.add_argument("--target-level", type=str, default="1",
                      help="Target autonomy level (default: 1)")
    l1p.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    l1p.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/autonomy-promotion-plans/")
    gsr = sub.add_parser("guard-state-reconcile",
                         help="Reconcile guard-state trade count against confirmed events")
    gsr.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    gsr.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/guard-state-repairs/")
    gsr.add_argument("--apply", action="store_true",
                      help="Apply the repair (requires --confirm-local-state-repair)")
    gsr.add_argument("--confirm-local-state-repair", action="store_true",
                      help="Explicit confirmation for local state repair")
    tcr = sub.add_parser("trade-count-reconcile",
                         help="Alias for guard-state-reconcile")
    tcr.add_argument("--json", action="store_true")
    tcr.add_argument("--export", action="store_true")
    tcr.add_argument("--apply", action="store_true")
    tcr.add_argument("--confirm-local-state-repair", action="store_true")
    rtc = sub.add_parser("repair-trade-count",
                         help="Alias for guard-state-reconcile")
    rtc.add_argument("--json", action="store_true")
    rtc.add_argument("--export", action="store_true")
    rtc.add_argument("--apply", action="store_true")
    rtc.add_argument("--confirm-local-state-repair", action="store_true")
    pdr = sub.add_parser("position-drift-reconcile",
                         help="Reconcile position-drift mismatches against unconfirmed-order evidence")
    pdr.add_argument("--json", action="store_true")
    pdr.add_argument("--export", action="store_true")
    pdr.add_argument("--apply", action="store_true")
    pdr.add_argument("--confirm-local-state-repair", action="store_true")
    pdr.add_argument("--symbol", type=str, default=None,
                      help="Restrict repair evaluation to a single symbol")
    pdr_a1 = sub.add_parser("position-drift-repair",
                            help="Alias for position-drift-reconcile")
    pdr_a1.add_argument("--json", action="store_true")
    pdr_a1.add_argument("--export", action="store_true")
    pdr_a1.add_argument("--apply", action="store_true")
    pdr_a1.add_argument("--confirm-local-state-repair", action="store_true")
    pdr_a1.add_argument("--symbol", type=str, default=None)
    pdr_a2 = sub.add_parser("reconcile-position-drift",
                            help="Alias for position-drift-reconcile")
    pdr_a2.add_argument("--json", action="store_true")
    pdr_a2.add_argument("--export", action="store_true")
    pdr_a2.add_argument("--apply", action="store_true")
    pdr_a2.add_argument("--confirm-local-state-repair", action="store_true")
    pdr_a2.add_argument("--symbol", type=str, default=None)
    ppv = sub.add_parser("preregistration-pin-verify",
                         help="Verify a paper-run pre-registration document's §2 pins against live state")
    ppv.add_argument("--doc", type=str, default=None,
                      help="Path to a <run-id>-preregistration.md to compare against; omit to just print live pins")
    ppv.add_argument("--json", action="store_true")
    ppv_a1 = sub.add_parser("prereg-pin-verify",
                            help="Alias for preregistration-pin-verify")
    ppv_a1.add_argument("--doc", type=str, default=None)
    ppv_a1.add_argument("--json", action="store_true")
    mdd = sub.add_parser("market-data-diagnostics",
                         help="Diagnose market-data entitlement/subscription issues")
    mdd.add_argument("--symbol", type=str, default="AAPL",
                      help="Symbol to diagnose (default: AAPL)")
    mdd.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    mdd.add_argument("--export", action="store_true",
                      help="Write JSON export to ~/.openclaw/market-data-diagnostics/")
    md_doctor = sub.add_parser("market-data-doctor",
                               help="Alias for market-data-diagnostics")
    md_doctor.add_argument("--symbol", type=str, default="AAPL")
    md_doctor.add_argument("--json", action="store_true")
    md_doctor.add_argument("--export", action="store_true")
    md_diag = sub.add_parser("md-diagnostics",
                             help="Alias for market-data-diagnostics")
    md_diag.add_argument("--symbol", type=str, default="AAPL")
    md_diag.add_argument("--json", action="store_true")
    md_diag.add_argument("--export", action="store_true")
    mdr = sub.add_parser("market-data-recovery-drill",
                         help="Recovery drill: connect + diagnostics + readiness refresh")
    mdr.add_argument("--symbol", type=str, default="AAPL",
                      help="Symbol to recover (default: AAPL)")
    mdr.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    mdr.add_argument("--export", action="store_true",
                      help="Write JSON export to ~/.openclaw/market-data-drills/")
    mdr.add_argument("--attempts", type=int, default=3,
                      help="Maximum diagnostic attempts (1-5, default 3)")
    mdr.add_argument("--sleep-seconds", type=float, default=10.0,
                      help="Seconds between retry attempts (1-60, default 10)")
    mdr.add_argument("--connect-if-needed", action="store_true", dest="connect_if_needed",
                      default=True, help="Call /connect if disconnected (default)")
    mdr.add_argument("--no-connect", action="store_false", dest="connect_if_needed",
                      help="Do not call /connect — diagnose only")
    md_rec1 = sub.add_parser("md-recovery-drill",
                             help="Alias for market-data-recovery-drill")
    md_rec1.add_argument("--symbol", type=str, default="AAPL")
    md_rec1.add_argument("--json", action="store_true")
    md_rec1.add_argument("--export", action="store_true")
    md_rec1.add_argument("--attempts", type=int, default=3)
    md_rec1.add_argument("--sleep-seconds", type=float, default=10.0)
    md_rec1.add_argument("--connect-if-needed", action="store_true", default=True)
    md_rec1.add_argument("--no-connect", action="store_false", dest="connect_if_needed")
    md_rec2 = sub.add_parser("market-recovery",
                             help="Alias for market-data-recovery-drill")
    md_rec2.add_argument("--symbol", type=str, default="AAPL")
    md_rec2.add_argument("--json", action="store_true")
    md_rec2.add_argument("--export", action="store_true")
    md_rec2.add_argument("--attempts", type=int, default=3)
    md_rec2.add_argument("--sleep-seconds", type=float, default=10.0)
    md_rec2.add_argument("--connect-if-needed", action="store_true", default=True)
    md_rec2.add_argument("--no-connect", action="store_false", dest="connect_if_needed")
    rrd = sub.add_parser("reconnect-readiness-drill",
                         help="Disconnected-safe reconnect readiness drill (Step 15V)")
    rrd.add_argument("--json", action="store_true",
                     help="Output raw JSON only")
    rrd.add_argument("--export", action="store_true",
                     help="Write output to ~/.openclaw/reconnect-readiness-drills/")
    rrd.add_argument("--host", type=str, default="127.0.0.1",
                     help="IB Gateway host (default: 127.0.0.1)")
    rrd.add_argument("--port", type=int, default=4002,
                     help="IB Gateway port (default: 4002)")
    rrd.add_argument("--client-id", type=int, default=777,
                     help="IB Gateway client ID (default: 777)")
    rrd.add_argument("--socket-timeout", type=int, default=2,
                     help="Socket probe timeout seconds (1-10, default: 2)")
    rrd.add_argument("--attempt-connect", "--connect-if-needed",
                     action="store_true", dest="attempt_connect", default=False,
                     help="Explicit opt-in to call bridge /connect (default: off)")
    rrd.add_argument("--no-connect", action="store_false", dest="attempt_connect",
                     help="Do not call /connect (default)")
    rrd_alias1 = sub.add_parser("ibkr-reconnect-drill",
                                help="Alias for reconnect-readiness-drill")
    rrd_alias1.add_argument("--json", action="store_true")
    rrd_alias1.add_argument("--export", action="store_true")
    rrd_alias1.add_argument("--host", type=str, default="127.0.0.1")
    rrd_alias1.add_argument("--port", type=int, default=4002)
    rrd_alias1.add_argument("--client-id", type=int, default=777)
    rrd_alias1.add_argument("--socket-timeout", type=int, default=2)
    rrd_alias1.add_argument("--attempt-connect", "--connect-if-needed",
                            action="store_true", dest="attempt_connect", default=False)
    rrd_alias1.add_argument("--no-connect", action="store_false", dest="attempt_connect")
    rrd_alias2 = sub.add_parser("disconnected-readiness",
                                help="Alias for reconnect-readiness-drill")
    rrd_alias2.add_argument("--json", action="store_true")
    rrd_alias2.add_argument("--export", action="store_true")
    rrd_alias2.add_argument("--host", type=str, default="127.0.0.1")
    rrd_alias2.add_argument("--port", type=int, default=4002)
    rrd_alias2.add_argument("--client-id", type=int, default=777)
    rrd_alias2.add_argument("--socket-timeout", type=int, default=2)
    rrd_alias2.add_argument("--attempt-connect", "--connect-if-needed",
                            action="store_true", dest="attempt_connect", default=False)
    rrd_alias2.add_argument("--no-connect", action="store_false", dest="attempt_connect")
    pgp = sub.add_parser("post-gateway-reconnect-proof",
                         help="Post-Gateway-start reconnect proof (Step 15W)")
    pgp.add_argument("--json", action="store_true",
                     help="Output raw JSON only")
    pgp.add_argument("--export", action="store_true",
                     help="Write output to ~/.openclaw/post-gateway-reconnect-proofs/")
    pgp.add_argument("--host", type=str, default="127.0.0.1",
                     help="IB Gateway host (default: 127.0.0.1)")
    pgp.add_argument("--port", type=int, default=4002,
                     help="IB Gateway port (default: 4002)")
    pgp.add_argument("--client-id", type=int, default=777,
                     help="IB Gateway client ID (default: 777)")
    pgp.add_argument("--socket-timeout", type=int, default=2,
                     help="Socket probe timeout seconds (1-10, default: 2)")
    pgp.add_argument("--attempt-connect", "--connect-if-needed",
                     action="store_true", dest="attempt_connect", default=False,
                     help="Explicit opt-in to call bridge /connect (default: off)")
    pgp.add_argument("--no-connect", action="store_false", dest="attempt_connect",
                     help="Do not call /connect (default)")
    pgp.add_argument("--refresh-evidence", action="store_true", default=True,
                     help="Gather post-connect read-only evidence (default: on)")
    pgp.add_argument("--no-refresh-evidence", action="store_false", dest="refresh_evidence",
                     help="Skip post-connect evidence gathering")
    pgp.add_argument("--symbol", type=str, default="AAPL",
                     help="Context symbol for post-connect checks (default: AAPL)")
    pgp_a1 = sub.add_parser("reconnect-proof",
                            help="Alias for post-gateway-reconnect-proof")
    pgp_a1.add_argument("--json", action="store_true")
    pgp_a1.add_argument("--export", action="store_true")
    pgp_a1.add_argument("--host", type=str, default="127.0.0.1")
    pgp_a1.add_argument("--port", type=int, default=4002)
    pgp_a1.add_argument("--client-id", type=int, default=777)
    pgp_a1.add_argument("--socket-timeout", type=int, default=2)
    pgp_a1.add_argument("--attempt-connect", "--connect-if-needed",
                        action="store_true", dest="attempt_connect", default=False)
    pgp_a1.add_argument("--no-connect", action="store_false", dest="attempt_connect")
    pgp_a1.add_argument("--refresh-evidence", action="store_true", default=True)
    pgp_a1.add_argument("--no-refresh-evidence", action="store_false", dest="refresh_evidence")
    pgp_a1.add_argument("--symbol", type=str, default="AAPL")
    pgp_a2 = sub.add_parser("gateway-connect-proof",
                            help="Alias for post-gateway-reconnect-proof")
    pgp_a2.add_argument("--json", action="store_true")
    pgp_a2.add_argument("--export", action="store_true")
    pgp_a2.add_argument("--host", type=str, default="127.0.0.1")
    pgp_a2.add_argument("--port", type=int, default=4002)
    pgp_a2.add_argument("--client-id", type=int, default=777)
    pgp_a2.add_argument("--socket-timeout", type=int, default=2)
    pgp_a2.add_argument("--attempt-connect", "--connect-if-needed",
                        action="store_true", dest="attempt_connect", default=False)
    pgp_a2.add_argument("--no-connect", action="store_false", dest="attempt_connect")
    pgp_a2.add_argument("--refresh-evidence", action="store_true", default=True)
    pgp_a2.add_argument("--no-refresh-evidence", action="store_false", dest="refresh_evidence")
    pgp_a2.add_argument("--symbol", type=str, default="AAPL")
    cq_drill = sub.add_parser("contract-qualification-drill",
                               help="Run contract qualification root-cause drill (Step 15S)")
    cq_drill.add_argument("--symbol", type=str, default="AAPL")
    cq_drill.add_argument("--json", action="store_true")
    cq_drill.add_argument("--export", action="store_true")
    cq_drill.add_argument("--sec-type", type=str, default="STK")
    cq_drill.add_argument("--currency", type=str, default="USD")
    cq_drill.add_argument("--exchange", type=str, default="SMART")
    cq_drill.add_argument("--primary-exchange", type=str, default="")
    cq_drill.add_argument("--attempt-alternates", action="store_true", default=True)
    cq_drill.add_argument("--no-attempt-alternates", action="store_false", dest="attempt_alternates")
    cq_drill.add_argument("--max-attempts", type=int, default=5)
    cq_d2 = sub.add_parser("contract-diagnostics",
                            help="Alias for contract-qualification-drill")
    cq_d2.add_argument("--symbol", type=str, default="AAPL")
    cq_d2.add_argument("--json", action="store_true")
    cq_d2.add_argument("--export", action="store_true")
    cq_d2.add_argument("--sec-type", type=str, default="STK")
    cq_d2.add_argument("--currency", type=str, default="USD")
    cq_d2.add_argument("--exchange", type=str, default="SMART")
    cq_d2.add_argument("--primary-exchange", type=str, default="")
    cq_d2.add_argument("--attempt-alternates", action="store_true", default=True)
    cq_d2.add_argument("--no-attempt-alternates", action="store_false", dest="attempt_alternates")
    cq_d2.add_argument("--max-attempts", type=int, default=5)
    cq_d3 = sub.add_parser("cq-drill",
                            help="Alias for contract-qualification-drill")
    cq_d3.add_argument("--symbol", type=str, default="AAPL")
    cq_d3.add_argument("--json", action="store_true")
    cq_d3.add_argument("--export", action="store_true")
    cq_d3.add_argument("--sec-type", type=str, default="STK")
    cq_d3.add_argument("--currency", type=str, default="USD")
    cq_d3.add_argument("--exchange", type=str, default="SMART")
    cq_d3.add_argument("--primary-exchange", type=str, default="")
    cq_d3.add_argument("--attempt-alternates", action="store_true", default=True)
    cq_d3.add_argument("--no-attempt-alternates", action="store_false", dest="attempt_alternates")
    cq_d3.add_argument("--max-attempts", type=int, default=5)
    ced = sub.add_parser("connected-endpoint-evidence-drill",
                         help="Connected read-only endpoint evidence normalization (Step 15X)")
    ced.add_argument("--json", action="store_true", help="Output raw JSON only")
    ced.add_argument("--export", action="store_true",
                     help="Write output to ~/.openclaw/connected-endpoint-evidence-drills/")
    ced.add_argument("--timeout", type=int, default=8,
                     help="Endpoint probe timeout seconds (1-20, default: 8)")
    ced.add_argument("--include-connected-only", action="store_true", default=True,
                     dest="include_connected_only", help="Include connected-only endpoints (default)")
    ced.add_argument("--no-connected-only", action="store_false",
                     dest="include_connected_only", help="Skip connected-only endpoints")
    ced.add_argument("--strict", action="store_true", default=False,
                     help="Any failed applicable endpoint => NO_GO")
    ced.add_argument("--symbol", type=str, default="AAPL",
                     help="Context symbol (default: AAPL)")
    ced_a1 = sub.add_parser("endpoint-evidence-drill",
                            help="Alias for connected-endpoint-evidence-drill")
    ced_a1.add_argument("--json", action="store_true")
    ced_a1.add_argument("--export", action="store_true")
    ced_a1.add_argument("--timeout", type=int, default=8)
    ced_a1.add_argument("--include-connected-only", action="store_true", default=True)
    ced_a1.add_argument("--no-connected-only", action="store_false", dest="include_connected_only")
    ced_a1.add_argument("--strict", action="store_true", default=False)
    ced_a1.add_argument("--symbol", type=str, default="AAPL")
    ced_a2 = sub.add_parser("read-only-endpoint-proof",
                            help="Alias for connected-endpoint-evidence-drill")
    ced_a2.add_argument("--json", action="store_true")
    ced_a2.add_argument("--export", action="store_true")
    ced_a2.add_argument("--timeout", type=int, default=8)
    ced_a2.add_argument("--include-connected-only", action="store_true", default=True)
    ced_a2.add_argument("--no-connected-only", action="store_false", dest="include_connected_only")
    ced_a2.add_argument("--strict", action="store_true", default=False)
    ced_a2.add_argument("--symbol", type=str, default="AAPL")
    ced_a3 = sub.add_parser("endpoint-normalization-drill",
                            help="Alias for connected-endpoint-evidence-drill")
    ced_a3.add_argument("--json", action="store_true")
    ced_a3.add_argument("--export", action="store_true")
    ced_a3.add_argument("--timeout", type=int, default=8)
    ced_a3.add_argument("--include-connected-only", action="store_true", default=True)
    ced_a3.add_argument("--no-connected-only", action="store_false", dest="include_connected_only")
    ced_a3.add_argument("--strict", action="store_true", default=False)
    ced_a3.add_argument("--symbol", type=str, default="AAPL")
    csd = sub.add_parser("connected-readonly-stability-drill",
                         help="Connected read-only account/position stability drill (Step 15Y)")
    csd.add_argument("--json", action="store_true", help="Output raw JSON only")
    csd.add_argument("--export", action="store_true",
                     help="Write output to ~/.openclaw/connected-readonly-stability-drills/")
    csd.add_argument("--samples", type=int, default=5,
                     help="Number of repeated samples (2-10, default: 5)")
    csd.add_argument("--interval-seconds", type=int, default=3,
                     help="Seconds between samples (1-15, default: 3)")
    csd.add_argument("--timeout", type=int, default=8,
                     help="Endpoint probe timeout seconds (1-20, default: 8)")
    csd.add_argument("--strict", action="store_true", default=False,
                     help="Endpoint degradation => NO_GO")
    csd_a1 = sub.add_parser("readonly-stability-drill",
                            help="Alias for connected-readonly-stability-drill")
    csd_a1.add_argument("--json", action="store_true")
    csd_a1.add_argument("--export", action="store_true")
    csd_a1.add_argument("--samples", type=int, default=5)
    csd_a1.add_argument("--interval-seconds", type=int, default=3)
    csd_a1.add_argument("--timeout", type=int, default=8)
    csd_a1.add_argument("--strict", action="store_true", default=False)
    csd_a2 = sub.add_parser("account-position-stability-drill",
                            help="Alias for connected-readonly-stability-drill")
    csd_a2.add_argument("--json", action="store_true")
    csd_a2.add_argument("--export", action="store_true")
    csd_a2.add_argument("--samples", type=int, default=5)
    csd_a2.add_argument("--interval-seconds", type=int, default=3)
    csd_a2.add_argument("--timeout", type=int, default=8)
    csd_a2.add_argument("--strict", action="store_true", default=False)
    csd_a3 = sub.add_parser("connected-evidence-stability-drill",
                            help="Alias for connected-readonly-stability-drill")
    csd_a3.add_argument("--json", action="store_true")
    csd_a3.add_argument("--export", action="store_true")
    csd_a3.add_argument("--samples", type=int, default=5)
    csd_a3.add_argument("--interval-seconds", type=int, default=3)
    csd_a3.add_argument("--timeout", type=int, default=8)
    csd_a3.add_argument("--strict", action="store_true", default=False)
    lpp = sub.add_parser("locked-preflight-proof",
                         help="Level-0 locked connected preflight-only proof (Step 15Z)")
    lpp.add_argument("--json", action="store_true", help="Output raw JSON only")
    lpp.add_argument("--export", action="store_true",
                     help="Write output to ~/.openclaw/locked-preflight-proofs/")
    lpp.add_argument("--symbol", type=str, default="AAPL",
                     help="Stock symbol (default: AAPL)")
    lpp.add_argument("--action", type=str, default="BUY",
                     help="Order action (default: BUY)")
    lpp.add_argument("--quantity", type=int, default=1,
                     help="Order quantity (default: 1)")
    lpp.add_argument("--order-type", type=str, default="MKT",
                     help="Order type (default: MKT)")
    lpp.add_argument("--timeout", type=int, default=8,
                     help="Preflight probe timeout seconds (1-20, default: 8)")
    lpp.add_argument("--samples", type=int, default=1,
                     help="Number of preflight samples (1-3, default: 1)")
    lpp.add_argument("--strict", action="store_true", default=False,
                     help="Any unexpected behavior => NO_GO")
    lpp_a1 = sub.add_parser("preflight-lock-proof",
                            help="Alias for locked-preflight-proof")
    lpp_a1.add_argument("--json", action="store_true")
    lpp_a1.add_argument("--export", action="store_true")
    lpp_a1.add_argument("--symbol", type=str, default="AAPL")
    lpp_a1.add_argument("--action", type=str, default="BUY")
    lpp_a1.add_argument("--quantity", type=int, default=1)
    lpp_a1.add_argument("--order-type", type=str, default="MKT")
    lpp_a1.add_argument("--timeout", type=int, default=8)
    lpp_a1.add_argument("--samples", type=int, default=1)
    lpp_a1.add_argument("--strict", action="store_true", default=False)
    lpp_a2 = sub.add_parser("level0-preflight-proof",
                            help="Alias for locked-preflight-proof")
    lpp_a2.add_argument("--json", action="store_true")
    lpp_a2.add_argument("--export", action="store_true")
    lpp_a2.add_argument("--symbol", type=str, default="AAPL")
    lpp_a2.add_argument("--action", type=str, default="BUY")
    lpp_a2.add_argument("--quantity", type=int, default=1)
    lpp_a2.add_argument("--order-type", type=str, default="MKT")
    lpp_a2.add_argument("--timeout", type=int, default=8)
    lpp_a2.add_argument("--samples", type=int, default=1)
    lpp_a2.add_argument("--strict", action="store_true", default=False)
    lpp_a3 = sub.add_parser("safe-preflight-proof",
                            help="Alias for locked-preflight-proof")
    lpp_a3.add_argument("--json", action="store_true")
    lpp_a3.add_argument("--export", action="store_true")
    lpp_a3.add_argument("--symbol", type=str, default="AAPL")
    lpp_a3.add_argument("--action", type=str, default="BUY")
    lpp_a3.add_argument("--quantity", type=int, default=1)
    lpp_a3.add_argument("--order-type", type=str, default="MKT")
    lpp_a3.add_argument("--timeout", type=int, default=8)
    lpp_a3.add_argument("--samples", type=int, default=1)
    lpp_a3.add_argument("--strict", action="store_true", default=False)
    bp_drain = sub.add_parser("backpressure-drain-drill",
                               help="Run bridge saturation / backpressure drain drill (Step 15T)")
    bp_drain.add_argument("--json", action="store_true")
    bp_drain.add_argument("--export", action="store_true")
    bp_drain.add_argument("--observe-seconds", type=int, default=15)
    bp_drain.add_argument("--poll-seconds", type=int, default=3)
    bp_drain.add_argument("--include-endpoint-probes", action="store_true", default=True)
    bp_drain.add_argument("--no-endpoint-probes", action="store_false", dest="include_endpoint_probes")
    bp_drain.add_argument("--symbol", type=str, default="AAPL")
    bp_d2 = sub.add_parser("bridge-drain-drill",
                            help="Alias for backpressure-drain-drill")
    bp_d2.add_argument("--json", action="store_true")
    bp_d2.add_argument("--export", action="store_true")
    bp_d2.add_argument("--observe-seconds", type=int, default=15)
    bp_d2.add_argument("--poll-seconds", type=int, default=3)
    bp_d2.add_argument("--include-endpoint-probes", action="store_true", default=True)
    bp_d2.add_argument("--no-endpoint-probes", action="store_false", dest="include_endpoint_probes")
    bp_d2.add_argument("--symbol", type=str, default="AAPL")
    bp_d3 = sub.add_parser("backpressure-doctor",
                            help="Alias for backpressure-drain-drill")
    bp_d3.add_argument("--json", action="store_true")
    bp_d3.add_argument("--export", action="store_true")
    bp_d3.add_argument("--observe-seconds", type=int, default=15)
    bp_d3.add_argument("--poll-seconds", type=int, default=3)
    bp_d3.add_argument("--include-endpoint-probes", action="store_true", default=True)
    bp_d3.add_argument("--no-endpoint-probes", action="store_false", dest="include_endpoint_probes")
    bp_d3.add_argument("--symbol", type=str, default="AAPL")
    gs_drift = sub.add_parser("guard-state-drift-sentinel",
                               help="Run guard-state drift attribution sentinel (Step 15U)")
    gs_drift.add_argument("--json", action="store_true")
    gs_drift.add_argument("--export", action="store_true")
    gs_drift.add_argument("--observe-seconds", type=int, default=15)
    gs_drift.add_argument("--poll-seconds", type=int, default=3)
    gs_drift.add_argument("--include-readonly-probes", action="store_true", default=True)
    gs_drift.add_argument("--no-readonly-probes", action="store_false", dest="include_readonly_probes")
    gs_drift.add_argument("--fail-on-drift", action="store_true", default=False)
    gs_drift.add_argument("--include-process-scan", action="store_true", default=True)
    gs_drift.add_argument("--no-process-scan", action="store_false", dest="include_process_scan")
    gs_d2 = sub.add_parser("guard-drift-sentinel",
                            help="Alias for guard-state-drift-sentinel")
    gs_d2.add_argument("--json", action="store_true")
    gs_d2.add_argument("--export", action="store_true")
    gs_d2.add_argument("--observe-seconds", type=int, default=15)
    gs_d2.add_argument("--poll-seconds", type=int, default=3)
    gs_d2.add_argument("--include-readonly-probes", action="store_true", default=True)
    gs_d2.add_argument("--no-readonly-probes", action="store_false", dest="include_readonly_probes")
    gs_d2.add_argument("--fail-on-drift", action="store_true", default=False)
    gs_d2.add_argument("--include-process-scan", action="store_true", default=True)
    gs_d2.add_argument("--no-process-scan", action="store_false", dest="include_process_scan")
    gs_d3 = sub.add_parser("guard-state-audit",
                            help="Alias for guard-state-drift-sentinel")
    gs_d3.add_argument("--json", action="store_true")
    gs_d3.add_argument("--export", action="store_true")
    gs_d3.add_argument("--observe-seconds", type=int, default=15)
    gs_d3.add_argument("--poll-seconds", type=int, default=3)
    gs_d3.add_argument("--include-readonly-probes", action="store_true", default=True)
    gs_d3.add_argument("--no-readonly-probes", action="store_false", dest="include_readonly_probes")
    gs_d3.add_argument("--fail-on-drift", action="store_true", default=False)
    gs_d3.add_argument("--include-process-scan", action="store_true", default=True)
    gs_d3.add_argument("--no-process-scan", action="store_false", dest="include_process_scan")
    p16a = sub.add_parser("phase15-completion-checkpoint",
                          help="Phase-15 completion audit / promotion readiness dossier")
    p16a.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16a.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/phase15-checkpoints/")
    p16a_a1 = sub.add_parser("phase-readiness-dossier",
                             help="Alias for phase15-completion-checkpoint")
    p16a_a1.add_argument("--json", action="store_true")
    p16a_a1.add_argument("--export", action="store_true")
    p16a_a2 = sub.add_parser("promotion-readiness-checkpoint",
                             help="Alias for phase15-completion-checkpoint")
    p16a_a2.add_argument("--json", action="store_true")
    p16a_a2.add_argument("--export", action="store_true")
    p16a_a3 = sub.add_parser("level1-readiness-dossier",
                             help="Alias for phase15-completion-checkpoint")
    p16a_a3.add_argument("--json", action="store_true")
    p16a_a3.add_argument("--export", action="store_true")
    p16b = sub.add_parser("manual-level1-promotion-review",
                          help="Manual Level-1 promotion procedure review (Phase 16B)")
    p16b.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16b.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-promotion-reviews/")
    p16b_a1 = sub.add_parser("level1-promotion-review",
                             help="Alias for manual-level1-promotion-review")
    p16b_a1.add_argument("--json", action="store_true")
    p16b_a1.add_argument("--export", action="store_true")
    p16b_a2 = sub.add_parser("promotion-procedure-review",
                             help="Alias for manual-level1-promotion-review")
    p16b_a2.add_argument("--json", action="store_true")
    p16b_a2.add_argument("--export", action="store_true")
    p16b_a3 = sub.add_parser("phase16b-promotion-review",
                             help="Alias for manual-level1-promotion-review")
    p16b_a3.add_argument("--json", action="store_true")
    p16b_a3.add_argument("--export", action="store_true")
    p16c = sub.add_parser("level1-promotion-dry-run-gate",
                          help="Level-1 promotion dry-run gate (Phase 16C)")
    p16c.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16c.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-dry-run-gates/")
    p16c_a1 = sub.add_parser("manual-level1-dry-run-gate",
                             help="Alias for level1-promotion-dry-run-gate")
    p16c_a1.add_argument("--json", action="store_true")
    p16c_a1.add_argument("--export", action="store_true")
    p16c_a2 = sub.add_parser("phase16c-promotion-dry-run",
                             help="Alias for level1-promotion-dry-run-gate")
    p16c_a2.add_argument("--json", action="store_true")
    p16c_a2.add_argument("--export", action="store_true")
    p16c_a3 = sub.add_parser("level1-gate-dossier",
                             help="Alias for level1-promotion-dry-run-gate")
    p16c_a3.add_argument("--json", action="store_true")
    p16c_a3.add_argument("--export", action="store_true")
    p16d = sub.add_parser("level1-apply-gate",
                          help="Explicit human-signed Level-1 apply gate (Phase 16D)")
    p16d.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16d.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-apply-gates/")
    p16d.add_argument("--apply", action="store_true",
                      help="Apply Level-1 promotion (requires all ack flags)")
    p16d.add_argument("--confirm-level1", action="store_true",
                      help="Confirm Level-1 promotion target")
    p16d.add_argument("--human-signed-apply", action="store_true",
                      help="Explicit human signoff for apply")
    p16d.add_argument("--ack-no-order-enablement", action="store_true",
                      help="Acknowledge orders will NOT be enabled")
    p16d.add_argument("--ack-manual-approval-required", action="store_true",
                      help="Acknowledge manual approval is still required")
    p16d.add_argument("--ack-relock-required", action="store_true",
                      help="Acknowledge relock is required post-promotion")
    p16d_a1 = sub.add_parser("human-signed-level1-apply-gate",
                             help="Alias for level1-apply-gate")
    p16d_a1.add_argument("--json", action="store_true")
    p16d_a1.add_argument("--export", action="store_true")
    p16d_a1.add_argument("--apply", action="store_true")
    p16d_a1.add_argument("--confirm-level1", action="store_true")
    p16d_a1.add_argument("--human-signed-apply", action="store_true")
    p16d_a1.add_argument("--ack-no-order-enablement", action="store_true")
    p16d_a1.add_argument("--ack-manual-approval-required", action="store_true")
    p16d_a1.add_argument("--ack-relock-required", action="store_true")
    p16d_a2 = sub.add_parser("phase16d-level1-apply-gate",
                             help="Alias for level1-apply-gate")
    p16d_a2.add_argument("--json", action="store_true")
    p16d_a2.add_argument("--export", action="store_true")
    p16d_a2.add_argument("--apply", action="store_true")
    p16d_a2.add_argument("--confirm-level1", action="store_true")
    p16d_a2.add_argument("--human-signed-apply", action="store_true")
    p16d_a2.add_argument("--ack-no-order-enablement", action="store_true")
    p16d_a2.add_argument("--ack-manual-approval-required", action="store_true")
    p16d_a2.add_argument("--ack-relock-required", action="store_true")
    p16d_a3 = sub.add_parser("level1-human-apply",
                             help="Alias for level1-apply-gate")
    p16d_a3.add_argument("--json", action="store_true")
    p16d_a3.add_argument("--export", action="store_true")
    p16d_a3.add_argument("--apply", action="store_true")
    p16d_a3.add_argument("--confirm-level1", action="store_true")
    p16d_a3.add_argument("--human-signed-apply", action="store_true")
    p16d_a3.add_argument("--ack-no-order-enablement", action="store_true")
    p16d_a3.add_argument("--ack-manual-approval-required", action="store_true")
    p16d_a3.add_argument("--ack-relock-required", action="store_true")
    p16e = sub.add_parser("level1-post-promotion-stability-drill",
                          help="Level 1 post-promotion stability drill (Phase 16E)")
    p16e.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16e.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-stability-drills/")
    p16e.add_argument("--samples", type=int, default=5,
                      help="Number of samples (default 5, min 2, max 30)")
    p16e.add_argument("--interval", type=int, default=10,
                      help="Seconds between samples (default 10, min 1, max 300)")
    p16e_a1 = sub.add_parser("phase16e-level1-stability-drill",
                             help="Alias for level1-post-promotion-stability-drill")
    p16e_a1.add_argument("--json", action="store_true")
    p16e_a1.add_argument("--export", action="store_true")
    p16e_a1.add_argument("--samples", type=int, default=5)
    p16e_a1.add_argument("--interval", type=int, default=10)
    p16e_a2 = sub.add_parser("level1-stability-drill",
                             help="Alias for level1-post-promotion-stability-drill")
    p16e_a2.add_argument("--json", action="store_true")
    p16e_a2.add_argument("--export", action="store_true")
    p16e_a2.add_argument("--samples", type=int, default=5)
    p16e_a2.add_argument("--interval", type=int, default=10)
    p16e_a3 = sub.add_parser("post-level1-stability",
                             help="Alias for level1-post-promotion-stability-drill")
    p16e_a3.add_argument("--json", action="store_true")
    p16e_a3.add_argument("--export", action="store_true")
    p16e_a3.add_argument("--samples", type=int, default=5)
    p16e_a3.add_argument("--interval", type=int, default=10)
    p16f = sub.add_parser("level1-evidence-normalization-check",
                          help="Level 1 evidence normalization / clean-cycle consistency check (Phase 16F)")
    p16f.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16f.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/evidence-normalization-checks/")
    p16f_a1 = sub.add_parser("phase16f-evidence-normalization",
                             help="Alias for level1-evidence-normalization-check")
    p16f_a1.add_argument("--json", action="store_true")
    p16f_a1.add_argument("--export", action="store_true")
    p16f_a2 = sub.add_parser("clean-cycle-consistency-check",
                             help="Alias for level1-evidence-normalization-check")
    p16f_a2.add_argument("--json", action="store_true")
    p16f_a2.add_argument("--export", action="store_true")
    p16f_a3 = sub.add_parser("level1-clean-cycle-check",
                             help="Alias for level1-evidence-normalization-check")
    p16f_a3.add_argument("--json", action="store_true")
    p16f_a3.add_argument("--export", action="store_true")
    p16g = sub.add_parser("level1-proposal-workflow-drill",
                          help="Level 1 proposal-only workflow drill (Phase 16G)")
    p16g.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16g.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-proposal-drills/")
    p16g.add_argument("--demo-candidates", type=int, default=2,
                      help="Number of demo proposal candidates (0-5, default 2)")
    p16g.add_argument("--proposal-source", type=str, default="synthetic_readonly_demo",
                      help="Proposal source label")
    p16g_a1 = sub.add_parser("phase16g-proposal-workflow-drill",
                             help="Alias for level1-proposal-workflow-drill")
    p16g_a1.add_argument("--json", action="store_true")
    p16g_a1.add_argument("--export", action="store_true")
    p16g_a1.add_argument("--demo-candidates", type=int, default=2)
    p16g_a1.add_argument("--proposal-source", type=str, default="synthetic_readonly_demo")
    p16g_a2 = sub.add_parser("level1-proposal-only-drill",
                             help="Alias for level1-proposal-workflow-drill")
    p16g_a2.add_argument("--json", action="store_true")
    p16g_a2.add_argument("--export", action="store_true")
    p16g_a2.add_argument("--demo-candidates", type=int, default=2)
    p16g_a2.add_argument("--proposal-source", type=str, default="synthetic_readonly_demo")
    p16g_a3 = sub.add_parser("proposal-only-workflow-drill",
                             help="Alias for level1-proposal-workflow-drill")
    p16g_a3.add_argument("--json", action="store_true")
    p16g_a3.add_argument("--export", action="store_true")
    p16g_a3.add_argument("--demo-candidates", type=int, default=2)
    p16g_a3.add_argument("--proposal-source", type=str, default="synthetic_readonly_demo")
    p16h = sub.add_parser("level1-human-review-package-drill",
                          help="Level 1 human review package drill (Phase 16H)")
    p16h.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16h.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-review-packages/")
    p16h.add_argument("--demo-candidates", type=int, default=2,
                      help="Number of demo review candidates (0-5, default 2)")
    p16h_a1 = sub.add_parser("phase16h-human-review-package-drill",
                             help="Alias for level1-human-review-package-drill")
    p16h_a1.add_argument("--json", action="store_true")
    p16h_a1.add_argument("--export", action="store_true")
    p16h_a1.add_argument("--demo-candidates", type=int, default=2)
    p16h_a2 = sub.add_parser("level1-review-package-drill",
                             help="Alias for level1-human-review-package-drill")
    p16h_a2.add_argument("--json", action="store_true")
    p16h_a2.add_argument("--export", action="store_true")
    p16h_a2.add_argument("--demo-candidates", type=int, default=2)
    p16h_a3 = sub.add_parser("human-review-package-drill",
                             help="Alias for level1-human-review-package-drill")
    p16h_a3.add_argument("--json", action="store_true")
    p16h_a3.add_argument("--export", action="store_true")
    p16h_a3.add_argument("--demo-candidates", type=int, default=2)
    p16i = sub.add_parser("level1-review-decision-drill",
                          help="Level 1 review decision drill (Phase 16I)")
    p16i.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16i.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-review-decisions/")
    p16i.add_argument("--demo-candidates", type=int, default=2,
                      help="Number of demo review candidates (0-5, default 2)")
    p16i.add_argument("--decision-mode", type=str, default="mixed_demo",
                      help="Decision mode: mixed_demo, accept_all_demo, reject_all_demo, defer_all_demo")
    p16i.add_argument("--review-package", type=str, default=None,
                      help="Optional path to a prior 16H review package artifact")
    p16i_a1 = sub.add_parser("phase16i-review-decision-drill",
                             help="Alias for level1-review-decision-drill")
    p16i_a1.add_argument("--json", action="store_true")
    p16i_a1.add_argument("--export", action="store_true")
    p16i_a1.add_argument("--demo-candidates", type=int, default=2)
    p16i_a1.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16i_a1.add_argument("--review-package", type=str, default=None)
    p16i_a2 = sub.add_parser("level1-accept-reject-drill",
                             help="Alias for level1-review-decision-drill")
    p16i_a2.add_argument("--json", action="store_true")
    p16i_a2.add_argument("--export", action="store_true")
    p16i_a2.add_argument("--demo-candidates", type=int, default=2)
    p16i_a2.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16i_a2.add_argument("--review-package", type=str, default=None)
    p16i_a3 = sub.add_parser("review-decision-drill",
                             help="Alias for level1-review-decision-drill")
    p16i_a3.add_argument("--json", action="store_true")
    p16i_a3.add_argument("--export", action="store_true")
    p16i_a3.add_argument("--demo-candidates", type=int, default=2)
    p16i_a3.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16i_a3.add_argument("--review-package", type=str, default=None)
    p16j = sub.add_parser("level1-order-plan-draft-drill",
                          help="Level 1 order-plan draft drill (Phase 16J)")
    p16j.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16j.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-order-plan-drafts/")
    p16j.add_argument("--demo-candidates", type=int, default=3,
                      help="Number of demo candidates (0-5, default 3)")
    p16j.add_argument("--decision-mode", type=str, default="mixed_demo",
                      help="Decision mode: mixed_demo, accept_all_demo, reject_all_demo, defer_all_demo")
    p16j.add_argument("--decision-artifact", type=str, default=None,
                      help="Optional path to a prior 16I decision artifact")
    p16j_a1 = sub.add_parser("phase16j-order-plan-draft-drill",
                             help="Alias for level1-order-plan-draft-drill")
    p16j_a1.add_argument("--json", action="store_true")
    p16j_a1.add_argument("--export", action="store_true")
    p16j_a1.add_argument("--demo-candidates", type=int, default=3)
    p16j_a1.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16j_a1.add_argument("--decision-artifact", type=str, default=None)
    p16j_a2 = sub.add_parser("level1-approved-plan-drill",
                             help="Alias for level1-order-plan-draft-drill")
    p16j_a2.add_argument("--json", action="store_true")
    p16j_a2.add_argument("--export", action="store_true")
    p16j_a2.add_argument("--demo-candidates", type=int, default=3)
    p16j_a2.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16j_a2.add_argument("--decision-artifact", type=str, default=None)
    p16j_a3 = sub.add_parser("order-plan-draft-drill",
                             help="Alias for level1-order-plan-draft-drill")
    p16j_a3.add_argument("--json", action="store_true")
    p16j_a3.add_argument("--export", action="store_true")
    p16j_a3.add_argument("--demo-candidates", type=int, default=3)
    p16j_a3.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16j_a3.add_argument("--decision-artifact", type=str, default=None)
    p16k = sub.add_parser("level1-preflight-simulation-dossier",
                          help="Level 1 preflight simulation dossier drill (Phase 16K)")
    p16k.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16k.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-preflight-simulation-dossiers/")
    p16k.add_argument("--demo-candidates", type=int, default=3,
                      help="Number of demo candidates (0-5, default 3)")
    p16k.add_argument("--decision-mode", type=str, default="mixed_demo",
                      help="Decision mode: mixed_demo, accept_all_demo, reject_all_demo, defer_all_demo")
    p16k.add_argument("--order-plan", type=str, default=None,
                      help="Optional path to a prior 16J order-plan draft artifact")
    p16k.add_argument("--simulation-source", type=str, default="synthetic_readonly_demo",
                      help="Simulation source label (default: synthetic_readonly_demo)")
    p16k_a1 = sub.add_parser("phase16k-preflight-simulation-dossier",
                             help="Alias for level1-preflight-simulation-dossier")
    p16k_a1.add_argument("--json", action="store_true")
    p16k_a1.add_argument("--export", action="store_true")
    p16k_a1.add_argument("--demo-candidates", type=int, default=3)
    p16k_a1.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16k_a1.add_argument("--order-plan", type=str, default=None)
    p16k_a1.add_argument("--simulation-source", type=str, default="synthetic_readonly_demo")
    p16k_a2 = sub.add_parser("level1-simulated-preflight-drill",
                             help="Alias for level1-preflight-simulation-dossier")
    p16k_a2.add_argument("--json", action="store_true")
    p16k_a2.add_argument("--export", action="store_true")
    p16k_a2.add_argument("--demo-candidates", type=int, default=3)
    p16k_a2.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16k_a2.add_argument("--order-plan", type=str, default=None)
    p16k_a2.add_argument("--simulation-source", type=str, default="synthetic_readonly_demo")
    p16k_a3 = sub.add_parser("preflight-simulation-dossier",
                             help="Alias for level1-preflight-simulation-dossier")
    p16k_a3.add_argument("--json", action="store_true")
    p16k_a3.add_argument("--export", action="store_true")
    p16k_a3.add_argument("--demo-candidates", type=int, default=3)
    p16k_a3.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16k_a3.add_argument("--order-plan", type=str, default=None)
    p16k_a3.add_argument("--simulation-source", type=str, default="synthetic_readonly_demo")
    p16l = sub.add_parser("level1-human-approval-packet-drill",
                          help="Level 1 human approval packet drill (Phase 16L)")
    p16l.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16l.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-human-approval-packets/")
    p16l.add_argument("--demo-candidates", type=int, default=3,
                      help="Number of demo candidates (0-5, default 3)")
    p16l.add_argument("--decision-mode", type=str, default="mixed_demo",
                      help="Decision mode: mixed_demo, accept_all_demo, reject_all_demo, defer_all_demo")
    p16l.add_argument("--preflight-dossier", type=str, default=None,
                      help="Optional path to a prior 16K preflight simulation dossier artifact")
    p16l.add_argument("--packet-source", type=str, default="synthetic_readonly_demo",
                      help="Packet source label (default: synthetic_readonly_demo)")
    p16l.add_argument("--reviewer", type=str, default="Chris",
                      help="Reviewer name (default: Chris)")
    p16l_a1 = sub.add_parser("phase16l-human-approval-packet-drill",
                             help="Alias for level1-human-approval-packet-drill")
    p16l_a1.add_argument("--json", action="store_true")
    p16l_a1.add_argument("--export", action="store_true")
    p16l_a1.add_argument("--demo-candidates", type=int, default=3)
    p16l_a1.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16l_a1.add_argument("--preflight-dossier", type=str, default=None)
    p16l_a1.add_argument("--packet-source", type=str, default="synthetic_readonly_demo")
    p16l_a1.add_argument("--reviewer", type=str, default="Chris")
    p16l_a2 = sub.add_parser("level1-approval-packet-drill",
                             help="Alias for level1-human-approval-packet-drill")
    p16l_a2.add_argument("--json", action="store_true")
    p16l_a2.add_argument("--export", action="store_true")
    p16l_a2.add_argument("--demo-candidates", type=int, default=3)
    p16l_a2.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16l_a2.add_argument("--preflight-dossier", type=str, default=None)
    p16l_a2.add_argument("--packet-source", type=str, default="synthetic_readonly_demo")
    p16l_a2.add_argument("--reviewer", type=str, default="Chris")
    p16l_a3 = sub.add_parser("human-approval-packet-drill",
                             help="Alias for level1-human-approval-packet-drill")
    p16l_a3.add_argument("--json", action="store_true")
    p16l_a3.add_argument("--export", action="store_true")
    p16l_a3.add_argument("--demo-candidates", type=int, default=3)
    p16l_a3.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16l_a3.add_argument("--preflight-dossier", type=str, default=None)
    p16l_a3.add_argument("--packet-source", type=str, default="synthetic_readonly_demo")
    p16l_a3.add_argument("--reviewer", type=str, default="Chris")
    p16m = sub.add_parser("level1-execution-readiness-packet-drill",
                          help="Level 1 execution-readiness packet drill (Phase 16M)")
    p16m.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16m.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-execution-readiness-packets/")
    p16m.add_argument("--demo-candidates", type=int, default=3,
                      help="Number of demo candidates (0-5, default 3)")
    p16m.add_argument("--decision-mode", type=str, default="mixed_demo",
                      help="Decision mode: mixed_demo, accept_all_demo, reject_all_demo, defer_all_demo")
    p16m.add_argument("--approval-packet", type=str, default=None,
                      help="Optional path to a prior 16L human approval packet artifact")
    p16m.add_argument("--packet-source", type=str, default="synthetic_readonly_demo",
                      help="Packet source label (default: synthetic_readonly_demo)")
    p16m.add_argument("--reviewer", type=str, default="Chris",
                      help="Reviewer name (default: Chris)")
    p16m_a1 = sub.add_parser("phase16m-execution-readiness-packet-drill",
                             help="Alias for level1-execution-readiness-packet-drill")
    p16m_a1.add_argument("--json", action="store_true")
    p16m_a1.add_argument("--export", action="store_true")
    p16m_a1.add_argument("--demo-candidates", type=int, default=3)
    p16m_a1.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16m_a1.add_argument("--approval-packet", type=str, default=None)
    p16m_a1.add_argument("--packet-source", type=str, default="synthetic_readonly_demo")
    p16m_a1.add_argument("--reviewer", type=str, default="Chris")
    p16m_a2 = sub.add_parser("level1-execution-readiness-drill",
                             help="Alias for level1-execution-readiness-packet-drill")
    p16m_a2.add_argument("--json", action="store_true")
    p16m_a2.add_argument("--export", action="store_true")
    p16m_a2.add_argument("--demo-candidates", type=int, default=3)
    p16m_a2.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16m_a2.add_argument("--approval-packet", type=str, default=None)
    p16m_a2.add_argument("--packet-source", type=str, default="synthetic_readonly_demo")
    p16m_a2.add_argument("--reviewer", type=str, default="Chris")
    p16m_a3 = sub.add_parser("execution-readiness-packet-drill",
                             help="Alias for level1-execution-readiness-packet-drill")
    p16m_a3.add_argument("--json", action="store_true")
    p16m_a3.add_argument("--export", action="store_true")
    p16m_a3.add_argument("--demo-candidates", type=int, default=3)
    p16m_a3.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16m_a3.add_argument("--approval-packet", type=str, default=None)
    p16m_a3.add_argument("--packet-source", type=str, default="synthetic_readonly_demo")
    p16m_a3.add_argument("--reviewer", type=str, default="Chris")
    p16n = sub.add_parser("level1-readiness-chain-integrity-checkpoint",
                          help="Level 1 readiness-chain integrity checkpoint (Phase 16N)")
    p16n.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16n.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-readiness-chain-checkpoints/")
    p16n.add_argument("--demo-candidates", type=int, default=3,
                      help="Number of demo candidates (0-5, default 3)")
    p16n.add_argument("--decision-mode", type=str, default="mixed_demo",
                      help="Decision mode: mixed_demo, accept_all_demo, reject_all_demo, defer_all_demo")
    p16n.add_argument("--chain-source", type=str, default="synthetic_readonly_demo",
                      help="Chain source label (default: synthetic_readonly_demo)")
    p16n_a1 = sub.add_parser("phase16n-readiness-chain-integrity-checkpoint",
                             help="Alias for level1-readiness-chain-integrity-checkpoint")
    p16n_a1.add_argument("--json", action="store_true")
    p16n_a1.add_argument("--export", action="store_true")
    p16n_a1.add_argument("--demo-candidates", type=int, default=3)
    p16n_a1.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16n_a1.add_argument("--chain-source", type=str, default="synthetic_readonly_demo")
    p16n_a2 = sub.add_parser("level1-readiness-chain-checkpoint",
                             help="Alias for level1-readiness-chain-integrity-checkpoint")
    p16n_a2.add_argument("--json", action="store_true")
    p16n_a2.add_argument("--export", action="store_true")
    p16n_a2.add_argument("--demo-candidates", type=int, default=3)
    p16n_a2.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16n_a2.add_argument("--chain-source", type=str, default="synthetic_readonly_demo")
    p16n_a3 = sub.add_parser("readiness-chain-integrity-checkpoint",
                             help="Alias for level1-readiness-chain-integrity-checkpoint")
    p16n_a3.add_argument("--json", action="store_true")
    p16n_a3.add_argument("--export", action="store_true")
    p16n_a3.add_argument("--demo-candidates", type=int, default=3)
    p16n_a3.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16n_a3.add_argument("--chain-source", type=str, default="synthetic_readonly_demo")
    p16o = sub.add_parser("level1-execution-gate-negative-control-drill",
                          help="Level 1 execution gate negative-control drill (Phase 16O)")
    p16o.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16o.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-execution-gate-negative-controls/")
    p16o.add_argument("--demo-candidates", type=int, default=3,
                      help="Number of demo intents (0-5, default 3)")
    p16o.add_argument("--decision-mode", type=str, default="mixed_demo",
                      help="Decision mode: mixed_demo, accept_all_demo, reject_all_demo, defer_all_demo")
    p16o.add_argument("--chain-source", type=str, default="synthetic_readonly_demo",
                      help="Chain source label (default: synthetic_readonly_demo)")
    p16o_a1 = sub.add_parser("phase16o-execution-gate-negative-control-drill",
                             help="Alias for level1-execution-gate-negative-control-drill")
    p16o_a1.add_argument("--json", action="store_true")
    p16o_a1.add_argument("--export", action="store_true")
    p16o_a1.add_argument("--demo-candidates", type=int, default=3)
    p16o_a1.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16o_a1.add_argument("--chain-source", type=str, default="synthetic_readonly_demo")
    p16o_a2 = sub.add_parser("level1-execution-negative-control-drill",
                             help="Alias for level1-execution-gate-negative-control-drill")
    p16o_a2.add_argument("--json", action="store_true")
    p16o_a2.add_argument("--export", action="store_true")
    p16o_a2.add_argument("--demo-candidates", type=int, default=3)
    p16o_a2.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16o_a2.add_argument("--chain-source", type=str, default="synthetic_readonly_demo")
    p16o_a3 = sub.add_parser("execution-gate-negative-control-drill",
                             help="Alias for level1-execution-gate-negative-control-drill")
    p16o_a3.add_argument("--json", action="store_true")
    p16o_a3.add_argument("--export", action="store_true")
    p16o_a3.add_argument("--demo-candidates", type=int, default=3)
    p16o_a3.add_argument("--decision-mode", type=str, default="mixed_demo")
    p16o_a3.add_argument("--chain-source", type=str, default="synthetic_readonly_demo")
    p16p = sub.add_parser("level1-order-window-canary-negative-control-drill",
                          help="Level 1 order-window canary negative-control drill (Phase 16P)")
    p16p.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16p.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-order-window-canary-negative-controls/")
    p16p.add_argument("--demo-candidates", type=int, default=3,
                      help="Number of demo canaries (0-5, default 3)")
    p16p.add_argument("--chain-source", type=str, default="synthetic_readonly_demo",
                      help="Chain source label (default: synthetic_readonly_demo)")
    p16p_a1 = sub.add_parser("phase16p-order-window-canary-negative-control-drill",
                             help="Alias for level1-order-window-canary-negative-control-drill")
    p16p_a1.add_argument("--json", action="store_true")
    p16p_a1.add_argument("--export", action="store_true")
    p16p_a1.add_argument("--demo-candidates", type=int, default=3)
    p16p_a1.add_argument("--chain-source", type=str, default="synthetic_readonly_demo")
    p16p_a2 = sub.add_parser("level1-order-window-negative-control-drill",
                             help="Alias for level1-order-window-canary-negative-control-drill")
    p16p_a2.add_argument("--json", action="store_true")
    p16p_a2.add_argument("--export", action="store_true")
    p16p_a2.add_argument("--demo-candidates", type=int, default=3)
    p16p_a2.add_argument("--chain-source", type=str, default="synthetic_readonly_demo")
    p16p_a3 = sub.add_parser("order-window-canary-negative-control-drill",
                             help="Alias for level1-order-window-canary-negative-control-drill")
    p16p_a3.add_argument("--json", action="store_true")
    p16p_a3.add_argument("--export", action="store_true")
    p16p_a3.add_argument("--demo-candidates", type=int, default=3)
    p16p_a3.add_argument("--chain-source", type=str, default="synthetic_readonly_demo")
    p16q = sub.add_parser("level1-h1-boundary-audit-checkpoint",
                          help="Level 1 H1 boundary audit checkpoint (Phase 16Q)")
    p16q.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16q.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-h1-boundary-audits/")
    p16q.add_argument("--demo-candidates", type=int, default=3,
                      help="Number of demo canaries (0-5, default 3)")
    p16q.add_argument("--audit-source", type=str, default="synthetic_readonly_demo",
                      help="Audit source label (default: synthetic_readonly_demo)")
    p16q_a1 = sub.add_parser("phase16q-h1-boundary-audit-checkpoint",
                             help="Alias for level1-h1-boundary-audit-checkpoint")
    p16q_a1.add_argument("--json", action="store_true")
    p16q_a1.add_argument("--export", action="store_true")
    p16q_a1.add_argument("--demo-candidates", type=int, default=3)
    p16q_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16q_a2 = sub.add_parser("level1-h1-boundary-checkpoint",
                             help="Alias for level1-h1-boundary-audit-checkpoint")
    p16q_a2.add_argument("--json", action="store_true")
    p16q_a2.add_argument("--export", action="store_true")
    p16q_a2.add_argument("--demo-candidates", type=int, default=3)
    p16q_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16q_a3 = sub.add_parser("h1-boundary-audit-checkpoint",
                             help="Alias for level1-h1-boundary-audit-checkpoint")
    p16q_a3.add_argument("--json", action="store_true")
    p16q_a3.add_argument("--export", action="store_true")
    p16q_a3.add_argument("--demo-candidates", type=int, default=3)
    p16q_a3.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16r = sub.add_parser("level1-broker-mutation-firewall-audit-checkpoint",
                          help="Level 1 broker-mutation firewall audit checkpoint (Phase 16R)")
    p16r.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16r.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-broker-mutation-firewall-audits/")
    p16r.add_argument("--demo-candidates", type=int, default=3,
                      help="Number of demo canaries (0-5, default 3)")
    p16r.add_argument("--audit-source", type=str, default="synthetic_readonly_demo",
                      help="Audit source label (default: synthetic_readonly_demo)")
    p16r_a1 = sub.add_parser("phase16r-broker-mutation-firewall-audit-checkpoint",
                             help="Alias for level1-broker-mutation-firewall-audit-checkpoint")
    p16r_a1.add_argument("--json", action="store_true")
    p16r_a1.add_argument("--export", action="store_true")
    p16r_a1.add_argument("--demo-candidates", type=int, default=3)
    p16r_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16r_a2 = sub.add_parser("level1-broker-mutation-firewall-checkpoint",
                             help="Alias for level1-broker-mutation-firewall-audit-checkpoint")
    p16r_a2.add_argument("--json", action="store_true")
    p16r_a2.add_argument("--export", action="store_true")
    p16r_a2.add_argument("--demo-candidates", type=int, default=3)
    p16r_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16r_a3 = sub.add_parser("broker-mutation-firewall-audit-checkpoint",
                             help="Alias for level1-broker-mutation-firewall-audit-checkpoint")
    p16r_a3.add_argument("--json", action="store_true")
    p16r_a3.add_argument("--export", action="store_true")
    p16r_a3.add_argument("--demo-candidates", type=int, default=3)
    p16r_a3.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16s = sub.add_parser("level1-end-to-end-safety-invariant-checkpoint",
                          help="Level 1 end-to-end safety invariant checkpoint (Phase 16S)")
    p16s.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16s.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-end-to-end-safety-invariant-checkpoints/")
    p16s.add_argument("--audit-source", type=str, default="synthetic_readonly_demo",
                      help="Audit source label (default: synthetic_readonly_demo)")
    p16s_a1 = sub.add_parser("phase16s-end-to-end-safety-invariant-checkpoint",
                             help="Alias for level1-end-to-end-safety-invariant-checkpoint")
    p16s_a1.add_argument("--json", action="store_true")
    p16s_a1.add_argument("--export", action="store_true")
    p16s_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16s_a2 = sub.add_parser("level1-safety-invariant-checkpoint",
                             help="Alias for level1-end-to-end-safety-invariant-checkpoint")
    p16s_a2.add_argument("--json", action="store_true")
    p16s_a2.add_argument("--export", action="store_true")
    p16s_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16s_a3 = sub.add_parser("end-to-end-safety-invariant-checkpoint",
                             help="Alias for level1-end-to-end-safety-invariant-checkpoint")
    p16s_a3.add_argument("--json", action="store_true")
    p16s_a3.add_argument("--export", action="store_true")
    p16s_a3.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16t = sub.add_parser("level1-restart-persistence-safety-checkpoint",
                          help="Level 1 restart-persistence safety checkpoint (Phase 16T)")
    p16t.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16t.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-restart-persistence-safety-checkpoints/")
    p16t.add_argument("--audit-source", type=str, default="synthetic_readonly_demo",
                      help="Audit source label (default: synthetic_readonly_demo)")
    p16t_a1 = sub.add_parser("phase16t-restart-persistence-safety-checkpoint",
                             help="Alias for level1-restart-persistence-safety-checkpoint")
    p16t_a1.add_argument("--json", action="store_true")
    p16t_a1.add_argument("--export", action="store_true")
    p16t_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16t_a2 = sub.add_parser("level1-restart-safety-checkpoint",
                             help="Alias for level1-restart-persistence-safety-checkpoint")
    p16t_a2.add_argument("--json", action="store_true")
    p16t_a2.add_argument("--export", action="store_true")
    p16t_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16t_a3 = sub.add_parser("restart-persistence-safety-checkpoint",
                             help="Alias for level1-restart-persistence-safety-checkpoint")
    p16t_a3.add_argument("--json", action="store_true")
    p16t_a3.add_argument("--export", action="store_true")
    p16t_a3.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16u = sub.add_parser("level1-startup-autoconnect-resilience-checkpoint",
                          help="Level 1 startup auto-connect resilience checkpoint (Phase 16U)")
    p16u.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16u.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-startup-autoconnect-resilience-checkpoints/")
    p16u.add_argument("--audit-source", type=str, default="synthetic_readonly_demo",
                      help="Audit source label (default: synthetic_readonly_demo)")
    p16u_a1 = sub.add_parser("phase16u-startup-autoconnect-resilience-checkpoint",
                             help="Alias for level1-startup-autoconnect-resilience-checkpoint")
    p16u_a1.add_argument("--json", action="store_true")
    p16u_a1.add_argument("--export", action="store_true")
    p16u_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16u_a2 = sub.add_parser("level1-autoconnect-resilience",
                             help="Alias for level1-startup-autoconnect-resilience-checkpoint")
    p16u_a2.add_argument("--json", action="store_true")
    p16u_a2.add_argument("--export", action="store_true")
    p16u_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16u_a3 = sub.add_parser("startup-autoconnect-resilience-checkpoint",
                             help="Alias for level1-startup-autoconnect-resilience-checkpoint")
    p16u_a3.add_argument("--json", action="store_true")
    p16u_a3.add_argument("--export", action="store_true")
    p16u_a3.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16v = sub.add_parser("level1-guard-state-rollover-resilience-checkpoint",
                          help="Level 1 guard-state rollover resilience checkpoint (Phase 16V)")
    p16v.add_argument("--json", action="store_true", help="Output raw JSON only")
    p16v.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-guard-state-rollover-resilience-checkpoints/")
    p16v.add_argument("--audit-source", type=str, default="synthetic_readonly_demo",
                      help="Audit source label (default: synthetic_readonly_demo)")
    p16v_a1 = sub.add_parser("phase16v-guard-state-rollover-resilience-checkpoint",
                             help="Alias for level1-guard-state-rollover-resilience-checkpoint")
    p16v_a1.add_argument("--json", action="store_true")
    p16v_a1.add_argument("--export", action="store_true")
    p16v_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16v_a2 = sub.add_parser("level1-guard-state-rollover-resilience",
                             help="Alias for level1-guard-state-rollover-resilience-checkpoint")
    p16v_a2.add_argument("--json", action="store_true")
    p16v_a2.add_argument("--export", action="store_true")
    p16v_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16v_a3 = sub.add_parser("guard-state-rollover-resilience-checkpoint",
                             help="Alias for level1-guard-state-rollover-resilience-checkpoint")
    p16v_a3.add_argument("--json", action="store_true")
    p16v_a3.add_argument("--export", action="store_true")
    p16v_a3.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16w = sub.add_parser("level1-scheduled-heartbeat-alerting-resilience-checkpoint",
                          help="Level 1 scheduled heartbeat & alerting resilience checkpoint (Phase 16W)")
    p16w.add_argument("--json", action="store_true")
    p16w.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-scheduled-heartbeat-alerting-resilience-checkpoints/")
    p16w.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16w_a1 = sub.add_parser("phase16w-scheduled-heartbeat-alerting-resilience-checkpoint",
                             help="Alias for level1-scheduled-heartbeat-alerting-resilience-checkpoint")
    p16w_a1.add_argument("--json", action="store_true")
    p16w_a1.add_argument("--export", action="store_true")
    p16w_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16w_a2 = sub.add_parser("level1-heartbeat-alerting-resilience",
                             help="Alias for level1-scheduled-heartbeat-alerting-resilience-checkpoint")
    p16w_a2.add_argument("--json", action="store_true")
    p16w_a2.add_argument("--export", action="store_true")
    p16w_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16w_a3 = sub.add_parser("scheduled-heartbeat-alerting-resilience-checkpoint",
                             help="Alias for level1-scheduled-heartbeat-alerting-resilience-checkpoint")
    p16w_a3.add_argument("--json", action="store_true")
    p16w_a3.add_argument("--export", action="store_true")
    p16w_a3.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16x = sub.add_parser("level1-os-boundary-h1-isolation-checkpoint",
                          help="Level 1 OS boundary & H1 isolation checkpoint (Phase 16X)")
    p16x.add_argument("--json", action="store_true")
    p16x.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-os-boundary-h1-isolation-checkpoints/")
    p16x.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16x_a1 = sub.add_parser("phase16x-os-boundary-h1-isolation-checkpoint",
                             help="Alias for level1-os-boundary-h1-isolation-checkpoint")
    p16x_a1.add_argument("--json", action="store_true")
    p16x_a1.add_argument("--export", action="store_true")
    p16x_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16x_a2 = sub.add_parser("level1-os-boundary-h1-isolation",
                             help="Alias for level1-os-boundary-h1-isolation-checkpoint")
    p16x_a2.add_argument("--json", action="store_true")
    p16x_a2.add_argument("--export", action="store_true")
    p16x_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16x_a3 = sub.add_parser("os-boundary-h1-isolation-checkpoint",
                             help="Alias for level1-os-boundary-h1-isolation-checkpoint")
    p16x_a3.add_argument("--json", action="store_true")
    p16x_a3.add_argument("--export", action="store_true")
    p16x_a3.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16y = sub.add_parser("level1-portable-tests-ci-readiness-checkpoint",
                          help="Level 1 portable tests & CI readiness checkpoint (Phase 16Y)")
    p16y.add_argument("--json", action="store_true")
    p16y.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-portable-tests-ci-readiness-checkpoints/")
    p16y.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16y_a1 = sub.add_parser("phase16y-portable-tests-ci-readiness-checkpoint",
                             help="Alias for level1-portable-tests-ci-readiness-checkpoint")
    p16y_a1.add_argument("--json", action="store_true")
    p16y_a1.add_argument("--export", action="store_true")
    p16y_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16y_a2 = sub.add_parser("level1-portable-tests-ci-readiness",
                             help="Alias for level1-portable-tests-ci-readiness-checkpoint")
    p16y_a2.add_argument("--json", action="store_true")
    p16y_a2.add_argument("--export", action="store_true")
    p16y_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16y_a3 = sub.add_parser("portable-tests-ci-readiness-checkpoint",
                             help="Alias for level1-portable-tests-ci-readiness-checkpoint")
    p16y_a3.add_argument("--json", action="store_true")
    p16y_a3.add_argument("--export", action="store_true")
    p16y_a3.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16z = sub.add_parser("level1-fresh-clone-ci-workflow-checkpoint",
                          help="Level 1 fresh-clone CI workflow checkpoint (Phase 16Z)")
    p16z.add_argument("--json", action="store_true")
    p16z.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-fresh-clone-ci-workflow-checkpoints/")
    p16z.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16z_a1 = sub.add_parser("phase16z-fresh-clone-ci-workflow-checkpoint",
                             help="Alias for level1-fresh-clone-ci-workflow-checkpoint")
    p16z_a1.add_argument("--json", action="store_true")
    p16z_a1.add_argument("--export", action="store_true")
    p16z_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p16z_a2 = sub.add_parser("fresh-clone-ci-workflow-checkpoint",
                             help="Alias for level1-fresh-clone-ci-workflow-checkpoint")
    p16z_a2.add_argument("--json", action="store_true")
    p16z_a2.add_argument("--export", action="store_true")
    p16z_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17a = sub.add_parser("level1-strategy-v1-governance-checkpoint",
                          help="Level 1 strategy v1 governance checkpoint (Phase 17A)")
    p17a.add_argument("--json", action="store_true")
    p17a.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-strategy-v1-governance-checkpoints/")
    p17a.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17a_a1 = sub.add_parser("phase17a-strategy-v1-governance-checkpoint",
                             help="Alias for level1-strategy-v1-governance-checkpoint")
    p17a_a1.add_argument("--json", action="store_true")
    p17a_a1.add_argument("--export", action="store_true")
    p17a_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17a_a2 = sub.add_parser("strategy-v1-governance-checkpoint",
                             help="Alias for level1-strategy-v1-governance-checkpoint")
    p17a_a2.add_argument("--json", action="store_true")
    p17a_a2.add_argument("--export", action="store_true")
    p17a_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17b = sub.add_parser("level1-strategy-v1-proposal-packet-schema-checkpoint",
                          help="Level 1 strategy v1 proposal packet schema checkpoint (Phase 17B)")
    p17b.add_argument("--json", action="store_true")
    p17b.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-strategy-v1-proposal-packet-schema-checkpoints/")
    p17b.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17b_a1 = sub.add_parser("phase17b-strategy-v1-proposal-packet-schema-checkpoint",
                             help="Alias for level1-strategy-v1-proposal-packet-schema-checkpoint")
    p17b_a1.add_argument("--json", action="store_true")
    p17b_a1.add_argument("--export", action="store_true")
    p17b_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17b_a2 = sub.add_parser("proposal-packet-schema-checkpoint",
                             help="Alias for level1-strategy-v1-proposal-packet-schema-checkpoint")
    p17b_a2.add_argument("--json", action="store_true")
    p17b_a2.add_argument("--export", action="store_true")
    p17b_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17c = sub.add_parser("level1-strategy-v1-dry-run-proposal-generation-checkpoint",
                          help="Level 1 strategy v1 dry-run proposal generation checkpoint (Phase 17C)")
    p17c.add_argument("--json", action="store_true")
    p17c.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-strategy-v1-dry-run-proposal-generation-checkpoints/")
    p17c.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17c_a1 = sub.add_parser("phase17c-strategy-v1-dry-run-proposal-generation-checkpoint",
                             help="Alias for level1-strategy-v1-dry-run-proposal-generation-checkpoint")
    p17c_a1.add_argument("--json", action="store_true")
    p17c_a1.add_argument("--export", action="store_true")
    p17c_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17c_a2 = sub.add_parser("dry-run-proposal-generation-checkpoint",
                             help="Alias for level1-strategy-v1-dry-run-proposal-generation-checkpoint")
    p17c_a2.add_argument("--json", action="store_true")
    p17c_a2.add_argument("--export", action="store_true")
    p17c_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17d = sub.add_parser("level1-proposal-review-rejection-dossier-checkpoint",
                          help="Level 1 proposal review and rejection dossier checkpoint (Phase 17D)")
    p17d.add_argument("--json", action="store_true")
    p17d.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-proposal-review-rejection-dossier-checkpoints/")
    p17d.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17d_a1 = sub.add_parser("phase17d-proposal-review-rejection-dossier-checkpoint",
                             help="Alias for level1-proposal-review-rejection-dossier-checkpoint")
    p17d_a1.add_argument("--json", action="store_true")
    p17d_a1.add_argument("--export", action="store_true")
    p17d_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17d_a2 = sub.add_parser("proposal-review-rejection-dossier-checkpoint",
                             help="Alias for level1-proposal-review-rejection-dossier-checkpoint")
    p17d_a2.add_argument("--json", action="store_true")
    p17d_a2.add_argument("--export", action="store_true")
    p17d_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17e = sub.add_parser("level1-human-review-decision-record-checkpoint",
                          help="Level 1 human review decision record checkpoint (Phase 17E)")
    p17e.add_argument("--json", action="store_true")
    p17e.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-human-review-decision-record-checkpoints/")
    p17e.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17e_a1 = sub.add_parser("phase17e-human-review-decision-record-checkpoint",
                             help="Alias for level1-human-review-decision-record-checkpoint")
    p17e_a1.add_argument("--json", action="store_true")
    p17e_a1.add_argument("--export", action="store_true")
    p17e_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17e_a2 = sub.add_parser("human-review-decision-record-checkpoint",
                             help="Alias for level1-human-review-decision-record-checkpoint")
    p17e_a2.add_argument("--json", action="store_true")
    p17e_a2.add_argument("--export", action="store_true")
    p17e_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17f = sub.add_parser("level1-planning-only-order-plan-draft-checkpoint",
                          help="Level 1 planning-only order plan draft checkpoint (Phase 17F)")
    p17f.add_argument("--json", action="store_true")
    p17f.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-planning-only-order-plan-draft-checkpoints/")
    p17f.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17f_a1 = sub.add_parser("phase17f-planning-only-order-plan-draft-checkpoint",
                             help="Alias for level1-planning-only-order-plan-draft-checkpoint")
    p17f_a1.add_argument("--json", action="store_true")
    p17f_a1.add_argument("--export", action="store_true")
    p17f_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17f_a2 = sub.add_parser("planning-only-order-plan-draft-checkpoint",
                             help="Alias for level1-planning-only-order-plan-draft-checkpoint")
    p17f_a2.add_argument("--json", action="store_true")
    p17f_a2.add_argument("--export", action="store_true")
    p17f_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17g = sub.add_parser("level1-planning-only-preflight-simulation-dossier-checkpoint",
                          help="Level 1 planning-only preflight simulation dossier checkpoint (Phase 17G)")
    p17g.add_argument("--json", action="store_true")
    p17g.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-planning-only-preflight-simulation-dossier-checkpoints/")
    p17g.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17g_a1 = sub.add_parser("phase17g-planning-only-preflight-simulation-dossier-checkpoint",
                             help="Alias for level1-planning-only-preflight-simulation-dossier-checkpoint")
    p17g_a1.add_argument("--json", action="store_true")
    p17g_a1.add_argument("--export", action="store_true")
    p17g_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17g_a2 = sub.add_parser("preflight-simulation-dossier-checkpoint",
                             help="Alias for level1-planning-only-preflight-simulation-dossier-checkpoint")
    p17g_a2.add_argument("--json", action="store_true")
    p17g_a2.add_argument("--export", action="store_true")
    p17g_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17h = sub.add_parser("level1-human-simulation-review-decision-record-checkpoint",
                          help="Level 1 human simulation review decision record checkpoint (Phase 17H)")
    p17h.add_argument("--json", action="store_true")
    p17h.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-human-simulation-review-decision-record-checkpoints/")
    p17h.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17h_a1 = sub.add_parser("phase17h-human-simulation-review-decision-record-checkpoint",
                             help="Alias for level1-human-simulation-review-decision-record-checkpoint")
    p17h_a1.add_argument("--json", action="store_true")
    p17h_a1.add_argument("--export", action="store_true")
    p17h_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17h_a2 = sub.add_parser("human-simulation-review-decision-record-checkpoint",
                             help="Alias for level1-human-simulation-review-decision-record-checkpoint")
    p17h_a2.add_argument("--json", action="store_true")
    p17h_a2.add_argument("--export", action="store_true")
    p17h_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17i = sub.add_parser("level1-planning-only-candidate-package-checkpoint",
                          help="Level 1 planning-only candidate package checkpoint (Phase 17I)")
    p17i.add_argument("--json", action="store_true")
    p17i.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-planning-only-candidate-package-checkpoints/")
    p17i.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17i_a1 = sub.add_parser("phase17i-planning-only-candidate-package-checkpoint",
                             help="Alias for level1-planning-only-candidate-package-checkpoint")
    p17i_a1.add_argument("--json", action="store_true")
    p17i_a1.add_argument("--export", action="store_true")
    p17i_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17i_a2 = sub.add_parser("candidate-package-checkpoint",
                             help="Alias for level1-planning-only-candidate-package-checkpoint")
    p17i_a2.add_argument("--json", action="store_true")
    p17i_a2.add_argument("--export", action="store_true")
    p17i_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17j = sub.add_parser("level1-human-candidate-package-review-decision-record-checkpoint",
                          help="Level 1 human candidate-package review decision-record checkpoint (Phase 17J)")
    p17j.add_argument("--json", action="store_true")
    p17j.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-human-candidate-package-review-decision-records/")
    p17j.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17j.add_argument("--reviewer", type=str, default="", help="Human reviewer identifier")
    p17j.add_argument("--decision", type=str, default="", help="ACCEPT, REJECT, or DEFER")
    p17j.add_argument("--reason", type=str, default="", help="Decision reason (required for REJECT/DEFER)")
    p17j_a1 = sub.add_parser("phase17j-human-candidate-package-review-decision-record-checkpoint",
                             help="Alias for level1-human-candidate-package-review-decision-record-checkpoint")
    p17j_a1.add_argument("--json", action="store_true")
    p17j_a1.add_argument("--export", action="store_true")
    p17j_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17j_a1.add_argument("--reviewer", type=str, default="")
    p17j_a1.add_argument("--decision", type=str, default="")
    p17j_a1.add_argument("--reason", type=str, default="")
    p17j_a2 = sub.add_parser("candidate-package-review-checkpoint",
                             help="Alias for level1-human-candidate-package-review-decision-record-checkpoint")
    p17j_a2.add_argument("--json", action="store_true")
    p17j_a2.add_argument("--export", action="store_true")
    p17j_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17j_a2.add_argument("--reviewer", type=str, default="")
    p17j_a2.add_argument("--decision", type=str, default="")
    p17j_a2.add_argument("--reason", type=str, default="")
    p17k = sub.add_parser("level1-guarded-preflight-request-draft-checkpoint",
                          help="Level 1 guarded preflight request draft checkpoint (Phase 17K)")
    p17k.add_argument("--json", action="store_true")
    p17k.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-guarded-preflight-request-draft-checkpoints/")
    p17k.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17k.add_argument("--reviewer", type=str, default="", help="Human drafter identifier")
    p17k.add_argument("--decision", type=str, default="", help="ACCEPT (must match review)")
    p17k.add_argument("--reason", type=str, default="", help="Draft reason")
    p17k_a1 = sub.add_parser("phase17k-guarded-preflight-request-draft-checkpoint",
                             help="Alias for level1-guarded-preflight-request-draft-checkpoint")
    p17k_a1.add_argument("--json", action="store_true")
    p17k_a1.add_argument("--export", action="store_true")
    p17k_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17k_a1.add_argument("--reviewer", type=str, default="")
    p17k_a1.add_argument("--decision", type=str, default="")
    p17k_a1.add_argument("--reason", type=str, default="")
    p17k_a2 = sub.add_parser("preflight-request-draft-checkpoint",
                             help="Alias for level1-guarded-preflight-request-draft-checkpoint")
    p17k_a2.add_argument("--json", action="store_true")
    p17k_a2.add_argument("--export", action="store_true")
    p17k_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17k_a2.add_argument("--reviewer", type=str, default="")
    p17k_a2.add_argument("--decision", type=str, default="")
    p17k_a2.add_argument("--reason", type=str, default="")
    p18a = sub.add_parser("level1-mstr-btc-research-proposal-governance-checkpoint",
                          help="Level 1 MSTR/BTC research proposal governance checkpoint (Phase 18A)")
    p18a.add_argument("--json", action="store_true")
    p18a.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-mstr-btc-research-proposal-governance-checkpoints/")
    p18a_a1 = sub.add_parser("phase18a",
                             help="Alias for level1-mstr-btc-research-proposal-governance-checkpoint")
    p18a_a1.add_argument("--json", action="store_true")
    p18a_a1.add_argument("--export", action="store_true")
    p18a_a2 = sub.add_parser("mstr-btc-research-proposal",
                             help="Alias for level1-mstr-btc-research-proposal-governance-checkpoint")
    p18a_a2.add_argument("--json", action="store_true")
    p18a_a2.add_argument("--export", action="store_true")
    p18b = sub.add_parser("level1-data-schema-provider-governance-checkpoint",
                          help="Level 1 data schema and provider governance checkpoint (Phase 18B)")
    p18b.add_argument("--json", action="store_true")
    p18b_a1 = sub.add_parser("phase18b",
                             help="Alias for level1-data-schema-provider-governance-checkpoint")
    p18b_a1.add_argument("--json", action="store_true")
    p18b_a2 = sub.add_parser("data-schema-provider-governance",
                             help="Alias for level1-data-schema-provider-governance-checkpoint")
    p18b_a2.add_argument("--json", action="store_true")
    p18r1 = sub.add_parser("level1-model-routing-governance-checkpoint",
                           help="Level 1 model-routing governance checkpoint (Phase 18R1)")
    p18r1.add_argument("--json", action="store_true")
    p18r1_a1 = sub.add_parser("phase18r1",
                              help="Alias for level1-model-routing-governance-checkpoint")
    p18r1_a1.add_argument("--json", action="store_true")
    p18r1_a2 = sub.add_parser("model-routing-governance",
                              help="Alias for level1-model-routing-governance-checkpoint")
    p18r1_a2.add_argument("--json", action="store_true")
    mrd = sub.add_parser("model-routing-decision",
                         help="Run Phase 18R1 model-routing decision (dry-run, advisory only)")
    mrd.add_argument("--input-file", type=str, required=True,
                     help="Path to routing request JSON file (use - for stdin)")
    mrd.add_argument("--json", action="store_true")
    p18r2 = sub.add_parser("level1-openclaw-routing-adapter-checkpoint",
                           help="Level 1 OpenClaw routing adapter checkpoint (Phase 18R2)")
    p18r2.add_argument("--json", action="store_true")
    p18r2_a1 = sub.add_parser("phase18r2",
                              help="Alias for level1-openclaw-routing-adapter-checkpoint")
    p18r2_a1.add_argument("--json", action="store_true")
    p18r2_a2 = sub.add_parser("openclaw-routing-adapter",
                              help="Alias for level1-openclaw-routing-adapter-checkpoint")
    p18r2_a2.add_argument("--json", action="store_true")
    ord_p = sub.add_parser("openclaw-route-decide",
                           help="Run full Phase 18R1+18R2 routing pipeline (SHADOW_ONLY)")
    ord_p.add_argument("--input-file", type=str, required=True,
                       help="Path to routing request JSON file (use - for stdin)")
    ord_p.add_argument("--json", action="store_true")
    mrad = sub.add_parser("model-routing-adapter-decision",
                           help="Resolve transport from existing Phase 18R1 request+decision pair (SHADOW_ONLY)")
    mrad.add_argument("--routing-request-file", type=str, required=True,
                       help="Path to Phase 18R1 routing request JSON (use - for stdin)")
    mrad.add_argument("--routing-decision-file", type=str, required=True,
                       help="Path to Phase 18R1 routing decision JSON (use - for stdin)")
    mrad.add_argument("--json", action="store_true")
    mrap = sub.add_parser("model-routing-activation-plan",
                           help="Print deterministic activation plan from repository governance (read-only)")
    mrap.add_argument("--json", action="store_true")
    p17l = sub.add_parser("level1-phase17-chain-closure-checkpoint",
                          help="Level 1 Phase 17 chain closure checkpoint (Phase 17L)")
    p17l.add_argument("--json", action="store_true")
    p17l.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/level1-phase17-chain-closure-checkpoints/")
    p17l.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17l_a1 = sub.add_parser("phase17l-chain-closure-checkpoint",
                             help="Alias for level1-phase17-chain-closure-checkpoint")
    p17l_a1.add_argument("--json", action="store_true")
    p17l_a1.add_argument("--export", action="store_true")
    p17l_a1.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
    p17l_a2 = sub.add_parser("phase17-chain-closure",
                             help="Alias for level1-phase17-chain-closure-checkpoint")
    p17l_a2.add_argument("--json", action="store_true")
    p17l_a2.add_argument("--export", action="store_true")
    p17l_a2.add_argument("--audit-source", type=str, default="synthetic_readonly_demo")
