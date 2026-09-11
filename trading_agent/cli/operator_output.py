"""Extracted operator helpers; historical behavior and command contracts retained."""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from typing import Any


def _color_verdict(v: str) -> str:
    from trading_agent.cli.operator_common import GREEN, RED, RESET, YELLOW
    green_vals = {"PASS", "RECONCILE-OK", "NO-OP", "BASELINE-LOCKED"}
    yellow_vals = {"HOLD", "NO-GO"}
    red_vals = {"STOP", "ERROR", "MANUAL-REQUIRED"}
    if v in green_vals:
        return f"{GREEN}{v}{RESET}"
    if v in yellow_vals:
        return f"{YELLOW}{v}{RESET}"
    if v in red_vals:
        return f"{RED}{v}{RESET}"
    return v


def _color_block_status(s: str) -> str:
    from trading_agent.cli.operator_common import GREEN, RED, RESET, YELLOW
    if s == "PASS":
        return f"{GREEN}PASS{RESET}"
    if s == "WARN":
        return f"{YELLOW}WARN{RESET}"
    if s == "BLOCK":
        return f"{RED}BLOCK{RESET}"
    return s


def _bool_icon(val: Any) -> str:
    from trading_agent.cli.operator_common import Any, GREEN, RED, RESET, YELLOW
    if val is True:
        return f"{GREEN}\u2713{RESET}"
    if val is False:
        return f"{RED}\u2717{RESET}"
    return f"{YELLOW}?{RESET}"


def _value_color(val: Any, ok_vals=(True, "up", "paper", "10/10", "true")) -> str:
    from trading_agent.cli.operator_common import Any, GREEN, RED, RESET
    s = str(val) if val is not None else "\u2014"
    if val in ok_vals:
        return f"{GREEN}{s}{RESET}"
    if val is False or val == "false" or val == "down":
        return f"{RED}{s}{RESET}"
    return s


def print_checklist(result: dict, explain: bool = False) -> None:
    """Print checklist result as human-readable table."""
    from trading_agent.cli.operator_common import BOLD, CYAN, GREEN, RESET, YELLOW, datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    state_label = result["state"].replace("-", " ").title()
    auto_tag = " (auto-detected)" if result["auto_detected"] else ""

    print(f"{BOLD}\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557{RESET}")
    print(f"{BOLD}\u2551       Operator Daily Checklist           \u2551{RESET}")
    print(f"{BOLD}\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d{RESET}")
    print(f"  Time:     {now}")
    print(f"  State:    {CYAN}{state_label}{RESET}{auto_tag}")
    print(f"  Verdict:  {_color_verdict(result['verdict'])}")
    print()

    if result["blocks"]:
        print(f"{BOLD}Blocks{RESET}")
        for b in result["blocks"]:
            print(f"  [{_color_block_status(b['status'])}] {b['check']}: {b['detail']}")
        print()
    else:
        print(f"{BOLD}Blocks{RESET}  {GREEN}None \u2014 all checks pass{RESET}")
        print()

    if result["warnings"]:
        print(f"{BOLD}Warnings{RESET}")
        for w in result["warnings"]:
            print(f"  {YELLOW}\u26a0{RESET} {w}")
        print()

    s = result["summary"]
    print(f"{BOLD}Runtime{RESET}")
    print(f"  Bridge:   {_value_color(s['runtime']['bridge'])}")
    print(f"  IBKR:     {_bool_icon(s['runtime']['ibkr_connected'])}  connected={s['runtime']['ibkr_connected']}")
    print(f"  Mode:     {_value_color(s['runtime']['mode'], ok_vals=('paper',))}")
    print(f"  Account:  {s['runtime']['account']}")
    print()
    print(f"{BOLD}Safety{RESET}")
    print(f"  Locked:   {_bool_icon(s['safety']['system_locked'])}  system_locked={s['safety']['system_locked']}")
    print(f"  Allow:    {_value_color(s['safety']['allow_orders'], ok_vals=(False, 'false'))}")
    print(f"  Enforce:  {_value_color(s['safety']['enforced'], ok_vals=(False, 'false'))}")
    print(f"  Startup:  {_value_color(s['safety']['startup_safety'], ok_vals=('10/10',))}")
    print()
    print(f"{BOLD}Calendar{RESET}")
    print(f"  Date:     {s['calendar']['market_date_et']} ({s['calendar']['day_name']})")
    print(f"  RTH:      {_bool_icon(s['calendar']['in_rth'])}  {s['calendar']['reason']}")
    print()
    print(f"{BOLD}Portfolio{RESET}")
    print(f"  Positions: {s['portfolio']['positions']}")
    print(f"  Expected:  {s['portfolio']['expected_positions']}")
    print(f"  Net Liq:   {s['portfolio']['net_liq_eur'] or '?'} EUR")
    print(f"  Cash:      {s['portfolio']['cash_eur'] or '?'} EUR")
    print(f"  Open Ord:  {s['portfolio']['open_orders_count']}")
    print()
    print(f"{BOLD}Monitoring{RESET}")
    print(f"  Drift:     {_bool_icon(not s['monitoring']['drift_detected'])}  detected={s['monitoring']['drift_detected']}")
    print(f"  Alerts:    {s['monitoring']['total_alerts']} total, {s['monitoring']['live_alerts']} requiring action")
    print(f"  Recon:     {_bool_icon(s['monitoring']['reconciliation_pass'])}")
    print()
    print(f"{BOLD}Release{RESET}")
    print(f"  Git Tag:   {s['release']['git_tag']}")
    print(f"  Release:   {s['release']['latest_release']}")
    print(f"  Regress:   {s['release']['regression']}")
    print(f"  Bundle:    {s['release']['latest_bundle']}")
    print(f"  Verify:    {_bool_icon(s['release']['audit_verify'])}  {s['release']['audit_verify_score']}")
    print()

    if result["required_manual_confirmations"]:
        print(f"{BOLD}Required Manual Confirmations{RESET}")
        for i, c in enumerate(result["required_manual_confirmations"], 1):
            print(f"  {i}. {c}")
        print()

    nsa = result["next_safe_action"]
    print(f"{BOLD}Next Safe Action{RESET}")
    print(f"  {CYAN}{nsa['action']}{RESET}")
    print(f"  {nsa['rationale']}")
    print()

    if explain:
        print(f"{BOLD}Explanation{RESET}")
        print(f"  State '{result['state']}' was determined by evaluating:")
        print(f"    - Calendar: tradable_day={s['calendar']['is_tradable_day']}, in_rth={s['calendar']['in_rth']}")
        print(f"    - Safety: system_locked={s['safety']['system_locked']}")
        print(f"    - Trade count from readiness endpoint")
        if result["blocks"]:
            print(f"  {len(result['blocks'])} block(s) found:")
            for b in result["blocks"]:
                print(f"    - {b['check']}: {b['detail']}")
        print(f"  Verdict '{result['verdict']}' is derived from state + block analysis.")
        print(f"  Next safe action follows the Phase 3D runbook.")
        print()

    print(f"{BOLD}Advisory{RESET}")
    print(f"  Read-only. No trading. No order automation.")


def print_daily_report(report: dict) -> None:
    """Print the daily report in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, CYAN, GREEN, RESET, YELLOW
    ts = report["timestamp_utc"]
    cl = report["checklist"]
    ks = report["kill_switches"]
    rt = report["runtime"]
    cal = report["calendar"]
    port = report["portfolio"]
    mon = report["monitoring"]
    rel = report["release"]
    ar = report["audit_retention"]
    rs = report["resources"]

    state_label = cl["state"].replace("-", " ").title()

    # ──────────────────────────────────────────────────
    # Header
    # ──────────────────────────────────────────────────
    print(f"{BOLD}Daily Operator Report{RESET}")
    print(f"{BOLD}{'=' * 50}{RESET}")
    print(f"  Time:     {ts}")
    print(f"  State:    {CYAN}{state_label}{RESET}")
    print(f"  Verdict:  {_color_verdict(cl['verdict'])}")
    print()

    # ──────────────────────────────────────────────────
    # Blocks & Warnings
    # ──────────────────────────────────────────────────
    if cl["blocks"]:
        print(f"{BOLD}Blocks{RESET}")
        for b in cl["blocks"]:
            print(f"  [{_color_block_status(b['status'])}] {b['check']}: {b['detail']}")
        print()
    else:
        print(f"{BOLD}Blocks{RESET}  {GREEN}None \u2014 all checks pass{RESET}")
        print()

    if cl["warnings"]:
        print(f"{BOLD}Warnings{RESET}")
        for w in cl["warnings"]:
            print(f"  {YELLOW}\u26a0{RESET} {w}")
        print()

    # ──────────────────────────────────────────────────
    # Kill Switches & Safety
    # ──────────────────────────────────────────────────
    print(f"{BOLD}Kill Switches / Safety{RESET}")
    print(f"  System locked: {_bool_icon(ks['system_locked'])}  {ks['system_locked']}")
    print(f"  Allow orders:  {_bool_icon(not ks['IBKR_ALLOW_ORDERS'])}  IBKR_ALLOW_ORDERS={ks['IBKR_ALLOW_ORDERS']}")
    print(f"  Rules enforcd: {_bool_icon(not ks['rules_enforced'])}  rules.enforced={ks['rules_enforced']}")
    print(f"  Startup safet: {_value_color(ks['startup_safety'], ok_vals=('10/10',))}")
    print(f"  Orders blckd:  {_bool_icon(ks['order_blocked'])}")
    print()

    # ──────────────────────────────────────────────────
    # Runtime / Bridge
    # ──────────────────────────────────────────────────
    print(f"{BOLD}Runtime / Bridge{RESET}")
    print(f"  Bridge:   {_value_color(rt['bridge'])}")
    print(f"  IBKR:     {_bool_icon(rt['ibkr_connected'])}  connected={rt['ibkr_connected']}")
    print(f"  Mode:     {_value_color(rt['mode'], ok_vals=('paper',))}")
    print(f"  Account:  {rt['account']}")
    print()

    # ──────────────────────────────────────────────────
    # Calendar / RTH
    # ──────────────────────────────────────────────────
    print(f"{BOLD}Calendar / RTH{RESET}")
    print(f"  Date: {cal['market_date_et']} ({cal['day_name']})")
    print(f"  RTH:  {_bool_icon(cal['in_rth'])}  {cal['reason']}")
    print(f"  Open: {cal['rth_open_et']} ET  Close: {cal['rth_close_et']} ET")
    print()

    # ──────────────────────────────────────────────────
    # Trading Baseline (Portfolio)
    # ──────────────────────────────────────────────────
    print(f"{BOLD}Trading Baseline{RESET}")
    print(f"  Net Liq:  {port['net_liq_eur'] or '\u2014'} EUR")
    print(f"  Cash:     {port['cash_eur'] or '\u2014'} EUR")
    print(f"  Positions: {port['positions'] or '\u2014'}")
    print(f"  Expected:  {port['expected_positions'] or '\u2014'}")
    print(f"  Open Ord:  {port['open_orders_count']}")
    print()

    # ──────────────────────────────────────────────────
    # Monitoring (Drift / Alerts / Recon)
    # ──────────────────────────────────────────────────
    print(f"{BOLD}Monitoring{RESET}")
    print(f"  Drift:     {_bool_icon(not mon['drift_detected'])}  detected={mon['drift_detected']}")
    print(f"  Mismatch:  {mon['drift_mismatches']}")
    print(f"  Alerts:    {mon['total_alerts']} total, {mon['live_alerts']} requiring action")
    print(f"  Recon:     {_bool_icon(mon['reconciliation_pass'])}")
    print()

    # ──────────────────────────────────────────────────
    # Release / Audit
    # ──────────────────────────────────────────────────
    print(f"{BOLD}Release / Audit{RESET}")
    print(f"  Git tag:    {rel['git_tag']}")
    print(f"  Release:    {rel['latest_release']}")
    print(f"  Regression: {rel['regression']}")
    print(f"  Bundle:     {rel['latest_bundle']}")
    print(f"  Audit ver:  {_bool_icon(rel['audit_verify'])}  {rel['audit_verify_score']}")

    ab = ar.get("bundles", {})
    print(f"  Bundles:    {ab.get('count', 0)} ({ab.get('size_mb', 0)} MB)  keep={ab.get('retention_limit', '?')}")
    rt_tags = ar.get("release_tags", {})
    print(f"  Releases:   {rt_tags.get('count', 0)} ({rt_tags.get('size_mb', 0)} MB)  keep={rt_tags.get('retention_limit', '?')}")
    print()

    # ──────────────────────────────────────────────────
    # System Resources
    # ──────────────────────────────────────────────────
    if rs:
        mem = rs.get("memory", {})
        swap = rs.get("swap", {})
        procs = rs.get("processes", {})
        print(f"{BOLD}System Resources{RESET}")
        print(f"  RAM:    {mem.get('used_mb', '?')}MB / {mem.get('total_mb', '?')}MB ({mem.get('used_pct', '?')}% used)")
        print(f"  Swap:   {swap.get('used_mb', '?')}MB / {swap.get('total_mb', '?')}MB")
        bw = procs.get("ibkr_bridge", {})
        gw = procs.get("ib_gateway", {})
        bridge_rss = bw.get("rss_mb", None)
        gateway_rss = gw.get("rss_mb", None)
        print(f"  Bridge:  {_bool_icon(bw.get('running'))}  RSS={f'{bridge_rss:.0f}MB' if bridge_rss else '\u2014'}")
        print(f"  Gateway: {_bool_icon(gw.get('running'))}  RSS={f'{gateway_rss:.0f}MB' if gateway_rss else '\u2014'}")

        rsw = rs.get("warnings", [])
        if rsw:
            print(f"  Warnings:")
            for w in rsw:
                print(f"    {YELLOW}\u26a0{RESET} {w}")
            print(f"  Next: {rs.get('next_safe_action', '\u2014')}")
        print()

    # ──────────────────────────────────────────────────
    # Next Safe Action
    # ──────────────────────────────────────────────────
    nsa = cl["next_safe_action"]
    print(f"{BOLD}Next Safe Action{RESET}")
    print(f"  {CYAN}{nsa['action']}{RESET}")
    print(f"  {nsa['rationale']}")
    print()

    # ──────────────────────────────────────────────────
    # Required Confirmations
    # ──────────────────────────────────────────────────
    if cl["required_manual_confirmations"]:
        print(f"{BOLD}Required Manual Confirmations{RESET}")
        for i, c in enumerate(cl["required_manual_confirmations"], 1):
            print(f"  {i}. {c}")
        print()

    print(f"{BOLD}Advisory{RESET}")
    print(f"  {report['advisory']}")


def print_doctor(result: dict) -> None:
    """Print doctor results in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW
    ts = result.get("timestamp_utc", "?")
    passed = result.get("passed", 0)
    total = result.get("total", 0)
    ok = result.get("pass", False)

    verdict_color = GREEN if ok else RED
    print(f"{BOLD}Operator Doctor{RESET}  ({ts})")
    print(f"{BOLD}{'=' * 40}{RESET}")

    for c in result.get("checks", []):
        status = c.get("status", "")
        if status == "MANUAL_REQUIRED":
            status_str = f"{YELLOW}MANUAL{RESET}"
        elif c["ok"]:
            status_str = f"{GREEN}PASS{RESET}"
        else:
            status_str = f"{RED}FAIL{RESET}"
        print(f"  {status_str}  {c['check']}: {c['detail']}")

    print()
    print(f"  {BOLD}Result:{RESET} {verdict_color}{'PASS' if ok else 'FAIL'}{RESET}  ({passed}/{total})")

    if not ok:
        print(f"{YELLOW}  Some checks failed. Review above for details.{RESET}")


def print_freeze(result: dict) -> None:
    """Print release freeze snapshot in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET
    ts = result.get("timestamp_utc", "?")
    verdict = result.get("verdict", "?")
    verdict_color = GREEN if verdict == "PASS" else RED
    sections = result.get("sections", {})

    print(f"{BOLD}Operator Release Freeze Snapshot{RESET}")
    print(f"{BOLD}{'=' * 50}{RESET}")
    print(f"  Timestamp:     {ts}")
    print(f"  Verdict:       {verdict_color}{verdict}{RESET}")
    print()

    # L2: doctor
    doc = sections.get("doctor", {})
    doc_ok = doc.get("pass", False)
    doc_color = GREEN if doc_ok else RED
    print(f"  {doc_color}{'PASS' if doc_ok else 'FAIL'}{RESET}  doctor: "
          f"{doc.get('passed', 0)}/{doc.get('total', 0)} checks passed")

    # L3: checklist
    ck = sections.get("checklist", {})
    ck_ok = ck.get("verdict") not in ("STOP", "ERROR")
    ck_color = GREEN if ck_ok else RED
    print(f"  {ck_color}{'PASS' if ck_ok else 'FAIL'}{RESET}  checklist: "
          f"verdict={ck.get('verdict', '?')}, {len(ck.get('blocks', []))} blocks")

    # L4: daily-report
    dr = sections.get("daily_report", {})
    dr_ok = "checklist" in dr
    dr_color = GREEN if dr_ok else RED
    print(f"  {dr_color}{'PASS' if dr_ok else 'FAIL'}{RESET}  daily-report: "
          f"{'present' if dr_ok else 'MISSING'}")

    # L5: export verify
    ev = sections.get("export_verify", {})
    ev_ok = ev.get("pass", False)
    ev_color = GREEN if ev_ok else RED
    print(f"  {ev_color}{'PASS' if ev_ok else 'FAIL'}{RESET}  export-verify: "
          f"{ev.get('passed_count', 0)}/{ev.get('check_count', 0)} checks")

    # L6: maintenance
    mr = sections.get("maintenance", {})
    mr_ok = mr.get("mode") != "error"
    mr_color = GREEN if mr_ok else RED
    bundles = mr.get("audit_bundles", {})
    releases = mr.get("release_tags", {})
    print(f"  {mr_color}{'PASS' if mr_ok else 'FAIL'}{RESET}  maintenance: "
          f"{bundles.get('count', '?')} bundles, {releases.get('count', '?')} tags")

    # L7: runbook
    rb = sections.get("runbook", {})
    rb_ok = rb.get("exists", False)
    rb_color = GREEN if rb_ok else RED
    print(f"  {rb_color}{'PASS' if rb_ok else 'FAIL'}{RESET}  runbook: "
          f"{rb.get('size_bytes', 0)} bytes" if rb_ok else "  FAIL  runbook: MISSING")

    # L8: git
    gt = sections.get("git_timeline", {})
    print(f"  {'INFO':<8} git: {gt.get('branch', '?')} @ {gt.get('commit', '?')}"
          f" ({gt.get('tag_count', 0)} tags)")

    # L9 + L10: safety
    sc = sections.get("safety_confirmation", {})
    sc_ok = sc.get("all_read_only", False) and sc.get("protected_files_untouched", False)
    sc_color = GREEN if sc_ok else RED
    print(f"  {sc_color}{'PASS' if sc_ok else 'FAIL'}{RESET}  safety: "
          f"read_only={sc.get('all_read_only')}, protected_untouched={sc.get('protected_files_untouched')}")

    # L11: regression
    rg = sections.get("regression", {})
    rg_ok = rg.get("pass", False)
    rg_color = GREEN if rg_ok else RED
    print(f"  {rg_color}{'PASS' if rg_ok else 'FAIL'}{RESET}  regression: "
          f"{rg.get('passed', '?')}/{rg.get('total', '?')}")

    print()
    print(f"  {BOLD}Overall:{RESET} {verdict_color}{verdict}{RESET}")


def print_export(export: dict) -> None:
    """Print evidence export in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, CYAN, RESET, YELLOW
    eid = export.get("export_id", "?")
    ts = export.get("generated_at_utc", "?")

    print(f"{BOLD}Operator Evidence Export{RESET}")
    """Print evidence export in human-readable format."""
    eid = export.get("export_id", "?")
    ts = export.get("generated_at_utc", "?")

    print(f"{BOLD}Operator Evidence Export{RESET}")
    print(f"{BOLD}{'=' * 50}{RESET}")
    print(f"  ID:       {eid}")
    print(f"  Time:     {ts}")
    print(f"  Verbose:  {export.get('sections_included', [])}")
    print()

    # Daily report snapshot
    drs = export.get("daily_report_snapshot", {})
    if drs:
        print(f"{BOLD}Daily Report Snapshot{RESET}")
        cl = drs.get("checklist", {})
        print(f"  State:    {cl.get('state', '?')}")
        print(f"  Verdict:  {_color_verdict(cl.get('verdict', '?'))}")
        nsa = cl.get("next_safe_action", {})
        print(f"  Next:     {CYAN}{nsa.get('action', '?')}{RESET}")
        ks = drs.get("kill_switches", {})
        print(f"  Locked:   {_bool_icon(ks.get('system_locked'))}")
        print(f"  Allow:    {_bool_icon(not ks.get('IBKR_ALLOW_ORDERS', True))}")
        tb = drs.get("trading_baseline", {})
        print(f"  Net Liq:  {tb.get('net_liq_eur') or '\u2014'} EUR")
        print(f"  Positions:{tb.get('positions_count', '?')}  Drift: {_bool_icon(not drs.get('monitoring',{}).get('drift_detected'))}")
        print()

    # Checklist snapshot
    cs = export.get("checklist_snapshot", {})
    if cs and isinstance(cs, dict):
        print(f"{BOLD}Checklist Snapshot{RESET}")
        ss = cs.get("summary_safety", {})
        print(f"  Safety:   allow={ss.get('allow_orders')} enforced={ss.get('enforced')} locked={ss.get('system_locked')}")
        sr = cs.get("summary_release", {})
        print(f"  Release:  {sr.get('latest_release', '?')}  Bundle: {sr.get('latest_bundle', '?')}")
        print()

    # Maintenance snapshot
    ms = export.get("maintenance_snapshot", {})
    if ms:
        print(f"{BOLD}Maintenance / Retention{RESET}")
        ab = ms.get("audit_bundles", {})
        rt = ms.get("release_tags", {})
        print(f"  Bundles:  {ab.get('count', 0)} ({ab.get('size_mb', 0)} MB)  keep={ab.get('retention_limit', '?')}")
        print(f"  Releases: {rt.get('count', 0)} ({rt.get('size_mb', 0)} MB)  keep={rt.get('retention_limit', '?')}")
        print()

    # Resources
    rs = export.get("resources_snapshot", {})
    if rs:
        mem = rs.get("memory", {})
        procs = rs.get("processes", {})
        print(f"{BOLD}System Resources{RESET}")
        print(f"  RAM:  {mem.get('used_pct', '?')}% used")
        bw = procs.get("ibkr_bridge", {})
        gw = procs.get("ib_gateway", {})
        print(f"  Bridge:  {_bool_icon(bw.get('running'))}  RSS={f'{bw.get("rss_mb"):.0f}MB' if bw.get("rss_mb") else '\u2014'}")
        print(f"  Gateway: {_bool_icon(gw.get('running'))}  RSS={f'{gw.get("rss_mb"):.0f}MB' if gw.get("rss_mb") else '\u2014'}")
        print()

    # Latest identifiers
    li = export.get("latest_identifiers", {})
    if li:
        print(f"{BOLD}Latest Identifiers{RESET}")
        b = li.get("audit_bundle", {})
        r = li.get("release_tag", {})
        print(f"  Bundle:  {b.get('bundle_id', '\u2014')} ({b.get('created_at_utc', '')})")
        print(f"  Release: {r.get('tag_id', '\u2014')} ({r.get('phase_label', '')})")
        print()

    # Git info
    gi = export.get("git_info")
    if gi:
        print(f"{BOLD}Git / Provenance{RESET}")
        print(f"  Commit:  {gi.get('commit', '?')[:16]}...")
        print(f"  Tag:     {gi.get('tag', '?')}")
        print(f"  Dirty:   {_bool_icon(not gi.get('dirty', True))}")
        print()

    # Locked baseline
    lb = export.get("locked_baseline")
    if lb:
        print(f"{BOLD}Locked Baseline{RESET}")
        print(f"  Confirmed: {_bool_icon(lb.get('confirmed', False))}")
        print(f"  Source:    {lb.get('source', '?')}")
        _safe_str = f"allow={lb.get('allow_orders')} enforced={lb.get('enforced')}" if lb.get("allow_orders") is not None else f"locked={lb.get('system_locked')}"
        print(f"  Details:   {_safe_str}")
        print()

    if export.get("_size_trimmed"):
        print(f"  {YELLOW}Note: export was size-trimmed (some sections truncated){RESET}")
        print()

    print(f"{BOLD}Advisory{RESET}")
    print(f"  {export['advisory']}")


def _print_maintenance(result: dict) -> None:
    """Pretty-print maintenance report or prune result."""
    mode = result.get("mode", "read-only")
    print(f"Mode: {mode}")
    print()

    if mode in ("dry-run",):
        # Dry-run plan
        wd = result.get("would_delete", {})
        print(f"Would delete: {wd.get('total', 0)} files total")

        ab = result.get("audit_bundles", {})
        if ab.get("count", 0) > 0:
            print(f"\n  Audit bundles to delete: {ab['count']}")
            print(f"    by age:  {ab.get('by_age', 0)}")
            print(f"    by limit: {ab.get('by_limit', 0)}")
            for p in ab.get("paths", [])[:5]:
                print(f"    - {p}")
            if len(ab.get("paths", [])) > 5:
                print(f"    ... and {len(ab['paths']) - 5} more")

        rt = result.get("release_tags", {})
        if rt.get("count", 0) > 0:
            print(f"\n  Release tags to delete: {rt['count']}")
            print(f"    by age:  {rt.get('by_age', 0)}")
            print(f"    by limit: {rt.get('by_limit', 0)}")
            for p in rt.get("paths", [])[:5]:
                print(f"    - {p}")
            if len(rt.get("paths", [])) > 5:
                print(f"    ... and {len(rt['paths']) - 5} more")

        ex = result.get("exports", {})
        if ex.get("count", 0) > 0:
            print(f"\n  Exports to delete: {ex['count']}")
            print(f"    by age:  {ex.get('by_age', 0)}")
            print(f"    by limit: {ex.get('by_limit', 0)}")
            for p in ex.get("paths", [])[:5]:
                print(f"    - {p}")
            if len(ex.get("paths", [])) > 5:
                print(f"    ... and {len(ex['paths']) - 5} more")

        if wd.get("total", 0) == 0:
            print("  Nothing to delete.")
        return

    if mode == "prune":
        ab = result.get("audit_bundles", {})
        rt = result.get("release_tags", {})
        ex = result.get("exports", {})
        print(f"  Audit bundles: removed {ab.get('total_removed', 0)}"
              f" (age={ab.get('by_age', 0)}, count={ab.get('by_count', 0)})")
        print(f"  Release tags:  removed {rt.get('total_removed', 0)}"
              f" (age={rt.get('by_age', 0)}, count={rt.get('by_count', 0)})")
        print(f"  Exports:       removed {ex.get('total_removed', 0)}"
              f" (age={ex.get('by_age', 0)}, count={ex.get('by_count', 0)})")
        print(f"  Total removed: {result.get('total_removed', 0)}")
        return

    # Read-only report
    ab = result.get("audit_bundles", {})
    print("Audit Bundles")
    print(f"  Count:      {ab.get('count', 0)}")
    print(f"  Size:       {ab.get('size_mb', 0)} MB")
    print(f"  Newest:     {ab.get('newest', '-')}")
    print(f"  Oldest:     {ab.get('oldest', '-')}")
    print(f"  Retention:  {ab.get('retention_limit', '?')} max")

    rt = result.get("release_tags", {})
    print()
    print("Release Tags")
    print(f"  Count:      {rt.get('count', 0)}")
    print(f"  Size:       {rt.get('size_mb', 0)} MB")
    print(f"  Newest:     {rt.get('newest', '-')}")
    print(f"  Oldest:     {rt.get('oldest', '-')}")
    print(f"  Retention:  {rt.get('retention_limit', '?')} max")

    ex = result.get("exports", {})
    if ex:
        print()
        print("Exports")
        print(f"  Count:      {ex.get('count', 0)}")
        print(f"  Size:       {ex.get('size_mb', 0)} MB")
        print(f"  Newest:     {ex.get('newest', '-')}")
        print(f"  Oldest:     {ex.get('oldest', '-')}")
        print(f"  Retention:  {ex.get('retention_limit', '?')} max")

    pf = result.get("protected_files", [])
    if pf:
        print()
        print("Protected Files (never deleted)")
        for f in pf:
            status = "✓" if f["exists"] else "✗"
            print(f"  {status} {f['name']}")

    # Phase 4E — Resource health
    rs = result.get("resources", {})
    if rs:
        mem = rs.get("memory", {})
        swap = rs.get("swap", {})
        procs = rs.get("processes", {})
        print()
        print("System Resources")
        print(f"  RAM:    {mem.get('used_mb', '?')}MB / {mem.get('total_mb', '?')}MB ({mem.get('used_pct', '?')}% used)")
        print(f"  Swap:   {swap.get('used_mb', '?')}MB / {swap.get('total_mb', '?')}MB")

        bw = procs.get("ibkr_bridge", {})
        gw = procs.get("ib_gateway", {})
        bridge_rss = bw.get("rss_mb", None)
        gateway_rss = gw.get("rss_mb", None)
        bridge_status = "✓" if bw.get("running") else "✗"
        gateway_status = "✓" if gw.get("running") else "✗"
        bridge_mem = f"{bridge_rss:.0f}MB" if bridge_rss else "-"
        gateway_mem = f"{gateway_rss:.0f}MB" if gateway_rss else "-"
        print(f"  Bridge:  {bridge_status}  RSS={bridge_mem}")
        print(f"  Gateway: {gateway_status}  RSS={gateway_mem}")

        warnings = rs.get("warnings", [])
        if warnings:
            print()
            print("Warnings")
            for w in warnings:
                print(f"  ⚠ {w}")
            print()
            print(f"  Next: {rs.get('next_safe_action', '-')}")

    print()
    print("Run with --dry-run to see what would be pruned.")
    print("Run with --prune-audit --keep-audit N to prune audit bundles.")
    print("Run with --prune-releases --keep-releases N to prune release tags.")
    print("Run with --prune-exports --keep-exports N to prune exports.")


def print_kpi(result: dict) -> None:
    """Print human-readable KPI dashboard."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW
    v = result["verdict"]
    v_color = GREEN if v == "GO" else YELLOW if v == "HOLD" else RED

    print(f"\n{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  IBKR KPI / Evidence Dashboard{RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Timestamp:     {result['timestamp']}")
    print(f"  Git:           {result['git']['branch']} @ {result['git']['commit_short']}  (tag: {result['git']['tag']})")
    print()

    # Verdict
    print(f"  {BOLD}Verdict: {v_color}{v}{RESET}\n")

    # Bridge
    b = result["bridge"]
    conn_str = f"{GREEN}connected{RESET}" if b["connected"] else f"{RED}disconnected{RESET}"
    print(f"  {BOLD}Bridge{RESET}")
    print(f"    Reachable:    {b['reachable']}")
    print(f"    Connected:    {conn_str}")
    print(f"    Mode:         {b['mode']}")
    print(f"    Read-only:    {b['read_only']}")
    print(f"    Positions:    {b['positions_count']}")
    if b["net_liquidation"] is not None:
        print(f"    Net Liq:      {b['net_liquidation']:,.2f} EUR")
    print(f"    Endpoints:    {b['endpoints_ok']}/{b['endpoints_total']} OK", end="")
    if b.get("endpoints_skipped_disconnected", 0) > 0:
        print(f", {b['endpoints_skipped_disconnected']} skipped (disconnected)", end="")
    elif b.get("endpoints_raw_total", 0) != b.get("endpoints_total", 0):
        print(f" (raw: {b.get('endpoints_raw_ok', '?')}/{b.get('endpoints_raw_total', '?')})", end="")
    print()
    if b["endpoint_failures"]:
        for f in b["endpoint_failures"]:
            print(f"      {RED}✗{RESET} {f}")
    print()

    # Safety Flags
    sf = result["safety_flags"]
    print(f"  {BOLD}Safety Flags{RESET}")
    ao_s = f"{GREEN}{sf['bridge_allow_orders']}{RESET}" if sf['bridge_allow_orders'] in (False, "false") else f"{RED}{sf['bridge_allow_orders']}{RESET}"
    env_s = f"{GREEN}{sf['env_IBKR_ALLOW_ORDERS']}{RESET}" if sf['env_IBKR_ALLOW_ORDERS'] in ("false", "?") else f"{RED}{sf['env_IBKR_ALLOW_ORDERS']}{RESET}"
    re_s = f"{GREEN}{sf['rules_enforced']}{RESET}" if sf['rules_enforced'] in ("false", "?") else f"{RED}{sf['rules_enforced']}{RESET}"
    print(f"    Read-only:               {sf['read_only']}")
    print(f"    Bridge allow_orders:     {ao_s}")
    print(f"    .env IBKR_ALLOW_ORDERS:  {env_s}")
    print(f"    rules.enforced:          {re_s}")
    print(f"    System locked:           {sf['system_locked']}")
    print()

    # Monitoring
    m = result["monitoring"]
    recon_s = f"{GREEN}PASS{RESET}" if m["reconciliation_passed"] else f"{RED}FAIL{RESET}" if m["reconciliation_passed"] is False else "N/A"
    alert_s = f"{RED}{m['active_alert_count']} active{RESET}" if m["active_alert_count"] > 0 else f"{GREEN}0{RESET}"
    print(f"  {BOLD}Monitoring{RESET}")
    print(f"    Reconciliation:  {recon_s}")
    print(f"    Active Alerts:   {alert_s}")
    for a in m["live_alerts"]:
        print(f"      {RED}⚠{RESET} [{a['severity']}] {a['type']}: {a['detail']}")
    print()

    # Events
    ev = result["events"]
    print(f"  {BOLD}Latest Events{RESET}")
    if ev["latest"]:
        for e in ev["latest"]:
            e_color = GREEN if e.get("passed") else RED
            print(f"    {e_color}{e['type']}{RESET}  gate={e['gate']}  {e['ts']}")
    else:
        print(f"    (none)")
    print()

    # Autonomy
    au = result["autonomy"]
    print(f"  {BOLD}Autonomy{RESET}")
    print(f"    Current Level:  {au['current_level']}")
    print(f"    Clean Cycles:   {au['clean_cycles']}")
    print()

    # Heartbeat
    hb = result["heartbeat"]
    hb_recent = f"{GREEN}{hb['age_human']}{RESET}" if hb["recent"] else f"{YELLOW}{hb['age_human']}{RESET}"
    print(f"  {BOLD}Heartbeat{RESET}")
    print(f"    Age:            {hb_recent}")
    print()

    # Doctor
    d = result["doctor"]
    doc_ok = f"{GREEN}PASS{RESET}" if d["non_canary_ok"] else f"{RED}FAIL{RESET}"
    print(f"  {BOLD}Doctor{RESET}")
    print(f"    Non-canary:     {doc_ok}  ({d['passed_count']}/{d['check_count']} checks)")
    if d["non_canary_failures"]:
        for f in d["non_canary_failures"]:
            print(f"      {RED}✗{RESET} {f}")
    print()

    # Blockers
    print(f"  {BOLD}Blocker List ({result['blocker_count']}){RESET}")
    for blk in result["blockers"]:
        sev_color = RED if blk["severity"] == "NO-GO" else YELLOW
        print(f"    {sev_color}[{blk['severity']}]{RESET} {blk['check']}: {blk['detail']}")
    print()

    print(f"  {BOLD}Final Verdict: {v_color}{v}{RESET}")
    print()


def print_repair_evidence(evidence: dict) -> None:
    """Print human-readable repair evidence."""
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"
    DRY = evidence.get("dry_run", True)
    label = f"{YELLOW}DRY-RUN{RESET}" if DRY else f"{GREEN}LIVE{RESET}"

    print(f"{BOLD}KPI Alert Repair{ RESET}  [{label}]")
    print(f"  Repair ID:   {evidence['repair_id']}")
    print(f"  Timestamp:   {evidence['timestamp_utc']}")
    print()

    for act in evidence["actions"]:
        action = act["action"]
        if action == "orphan_approvals_identified":
            print(f"  Orphan approvals identified: {act['count']}")
        elif action == "orphan_approvals_cleared":
            print(f"  {GREEN}Cleared{RESET} {act['count']} orphan approvals ({act['remaining']} remain)")
        elif action == "backup_created":
            print(f"  Backup: {act['path']}")
        elif action == "trade_count_analysed":
            print(f"  Trade count: guard={act['current_guard_count']}, "
                  f"real={act['authoritative_count']} "
                  f"(excluded {act['test_events_excluded']} test events)")
        elif action == "trade_count_corrected":
            print(f"  {GREEN}Corrected{RESET} daily_trade_count: {act['from']} → {act['to']}")
        elif action == "trade_count_no_repair_needed":
            print(f"  Trade count: no correction needed ({act['reason']})")

    print()
    if evidence["audit_events"]:
        print(f"  {BOLD}Audit events:{RESET} {len(evidence['audit_events'])}")
        for ae in evidence["audit_events"]:
            print(f"    - [{ae['alert_type']}] {ae['action']}")


def _print_guard_state_reconcile(result: dict) -> None:
    """Print guard-state reconciliation result in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW
    mode = result.get("mode", "dry_run")
    if mode == "apply":
        mode_label = f"{GREEN}APPLY{RESET}"
    else:
        mode_label = f"{YELLOW}DRY-RUN{RESET}"

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Guard-State Trade-Count Reconciliation (Step 15O){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Repair ID:         {result.get('repair_id', '?')}")
    print(f"  Timestamp:         {result.get('timestamp', '?')}")
    print(f"  Mode:              {mode_label}")
    print(f"  Trade Date:        {result.get('trade_date', '?')}")
    td_stale = result.get('trade_date_stale', False)
    stale_str = f"{YELLOW}stale{RESET}" if td_stale else f"{GREEN}current{RESET}"
    print(f"  Trade Date Stale:  {stale_str}")
    if result.get("stale_trade_date_repair"):
        print(f"  Stale Date Repair: {GREEN}YES{RESET}  reason={result.get('repair_reason', '?')}")
        print(f"    trade_date_before: {result.get('trade_date_before', '?')}")
        print(f"    trade_date_after:  {result.get('trade_date_after', '?')}")
    print()

    print(f"  {BOLD}Trade Count{RESET}")
    print(f"    Guard (before):   {result.get('guard_daily_trade_count_before', 0)}")
    print(f"    Confirmed events: {result.get('confirmed_event_trade_count', 0)}")
    if result.get("repair_applied"):
        print(f"    Guard (after):    {GREEN}{result.get('guard_daily_trade_count_after', 0)}{RESET}")
    print()

    mismatch = result.get("mismatch_detected", False)
    print(f"  Mismatch:          {'YES' if mismatch else 'NO'}")
    print(f"  Repair Recommended:{'YES' if result.get('repair_recommended') else 'NO'}")
    print(f"  Repair Applied:    {'YES' if result.get('repair_applied') else 'NO'}")
    print()

    sf = result.get("safety_flags", {})
    print(f"  {BOLD}Safety{RESET}")
    print(f"    Locked:           {sf.get('safety_locked', '?')}")
    print(f"    IBKR_ALLOW_ORDERS:{sf.get('env_IBKR_ALLOW_ORDERS', '?')}")
    print(f"    rules.enforced:   {sf.get('rules_enforced', '?')}")
    print()

    if result.get("ibkr_connected"):
        print(f"  {BOLD}IBKR State{RESET}")
        print(f"    Live orders:      {result.get('ibkr_live_order_count', '?')}")
        print(f"    Open orders:      {result.get('open_order_count', '?')}")
        print(f"    Positions:        {result.get('positions_count', '?')}")
        print(f"    Positions flat:   {result.get('positions_flat', '?')}")
        print()

    blockers = result.get("blockers", [])
    if blockers:
        print(f"  {BOLD}Blockers ({len(blockers)}){RESET}")
        for b in blockers:
            sev = b["severity"]
            sev_color = RED if sev == "NO-GO" else RESET
            print(f"    {sev_color}{sev:<6}{RESET} {b['check']}: {b.get('detail', '?')}")
        print()

    na = result.get("explicit_non_actions", [])
    if na:
        print(f"  {BOLD}Explicit Non-Actions{RESET}")
        for a in na:
            print(f"    ✗  {a}")
        print()

    print(f"  Evidence Hash:     {result.get('evidence_hash', '?')[:16]}...")
    print()
    print(f"  {BOLD}══════════════════════════════════════════════════{RESET}")


def _print_position_drift_reconcile(result: dict) -> None:
    """Print position-drift reconciliation result in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW
    mode = result.get("mode", "dry_run")
    mode_label = f"{GREEN}APPLY{RESET}" if mode == "apply" else f"{YELLOW}DRY-RUN{RESET}"

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Position-Drift Reconciliation (Phase 19F){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Repair ID:   {result.get('repair_id', '?')}")
    print(f"  Timestamp:   {result.get('timestamp', '?')}")
    print(f"  Mode:        {mode_label}")
    print(f"  Drift:       {'YES' if result.get('drift_detected') else 'NO'}"
          f"  ({result.get('mismatch_count', 0)} mismatch(es))")
    print()

    per_symbol = result.get("per_symbol_results", [])
    if not per_symbol:
        print(f"  {GREEN}No mismatches to evaluate.{RESET}\n")
    for r in per_symbol:
        print(f"  {BOLD}{r['symbol']}{RESET}")
        print(f"    Expected (before): {r.get('expected_qty_before')}")
        print(f"    Actual (live):     {r.get('actual_qty')}")
        print(f"    Delta:             {r.get('qty_delta')}")
        print(f"    Candidate unconfirmed approval_ids: "
              f"{r.get('candidate_unconfirmed_approval_ids') or '(none)'}")
        rec_str = f"{GREEN}YES{RESET}" if r.get("repair_recommended") else "NO"
        app_str = f"{GREEN}YES{RESET}" if r.get("repair_applied") else "NO"
        print(f"    Repair Recommended: {rec_str}   Repair Applied: {app_str}")
        if r.get("repair_applied"):
            print(f"    Expected (after):   {r.get('expected_qty_after')}"
                  f"  verified={r.get('repair_verified')}")
        for b in r.get("blockers", []):
            sev_color = RED if b["severity"] == "NO-GO" else RESET
            print(f"    {sev_color}{b['severity']:<6}{RESET} {b['check']}: {b.get('detail', '?')}")
        print()

    sf = result.get("safety_flags", {})
    print(f"  {BOLD}Safety{RESET}")
    print(f"    Locked:           {sf.get('safety_locked', '?')}")
    print(f"    IBKR_ALLOW_ORDERS:{sf.get('env_IBKR_ALLOW_ORDERS', '?')}")
    print(f"    rules.enforced:   {sf.get('rules_enforced', '?')}")
    print(f"    IBKR connected:   {result.get('ibkr_connected', '?')}")
    print()

    na = result.get("explicit_non_actions", [])
    if na:
        print(f"  {BOLD}Explicit Non-Actions{RESET}")
        for a in na:
            print(f"    ✗  {a}")
        print()

    print(f"  Evidence Hash:     {result.get('evidence_hash', '?')[:16]}...")
    print()
    print(f"  {BOLD}══════════════════════════════════════════════════{RESET}")


def _print_prereg_pin_verify(result: dict) -> None:
    """Print pre-registration pin verification result in human-readable form."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Pre-Registration Pin Verification (Phase 19J){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    live = result["live"]
    print(f"  {BOLD}Live pins{RESET}")
    if live.get("git_runtime_safety_pin"):
        print(f"    Git runtime-safety pin:  {live['git_runtime_safety_pin']}")
    else:
        print(f"    {RED}Git runtime-safety pin:  ERROR — {live.get('git_runtime_safety_pin_error')}{RESET}")
    if live.get("yaml_normalized_sha256"):
        print(f"    YAML normalized SHA-256: {live['yaml_normalized_sha256']}")
    else:
        print(f"    {RED}YAML normalized SHA-256: ERROR — {live.get('yaml_normalized_sha256_error')}{RESET}")
    print()

    if result.get("doc_path"):
        print(f"  {BOLD}Compared against{RESET}: {result['doc_path']}")
        comparisons = result.get("comparisons") or {}
        for key, c in comparisons.items():
            status = c["status"]
            color = GREEN if status == "MATCH" else RED
            print(f"    {color}{status:<16}{RESET} {key}")
            if status == "MISMATCH":
                print(f"      recorded: {c['recorded']}")
                print(f"      live:     {c['live']}")
        print()

    pass_str = f"{GREEN}PASS{RESET}" if result.get("pass") else f"{RED}FAIL{RESET}"
    print(f"  Overall: {pass_str}")
    if result.get("fail_reason"):
        print(f"  Reason:  {result['fail_reason']}")
    print()
    print(f"  {BOLD}══════════════════════════════════════════════════{RESET}")


def print_cycle_rehearsal(result: dict) -> None:
    """Print cycle rehearsal result in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET
    verdict = result["verdict"]
    v_color = {"CLEAN": GREEN, "HOLD": RESET, "NO-GO": RED}.get(verdict, RESET)

    print(f"{BOLD}Autonomy Cycle Rehearsal{RESET}  [{v_color}{verdict}{RESET}]")
    print(f"  Timestamp:  {result['timestamp']}")
    print(f"  KPI:        {result['kpi_verdict']}")
    print(f"  Blockers:   {result['blocker_count']}")

    safety = result["safety_flags"]
    locked = (
        safety.get("read_only") is True
        and safety.get("bridge_allow_orders") is False
        and safety.get("env_IBKR_ALLOW_ORDERS") == "false"
        and safety.get("rules_enforced") == "false"
    )
    print(f"  Safety:     {'LOCKED' if locked else f'{RED}UNLOCKED{RESET}'}")
    print(f"  Docs:       STRATEGY={'✓' if result['docs']['strategy_exists'] else '✗'} "
          f"AUTONOMY={'✓' if result['docs']['autonomy_exists'] else '✗'}")
    print(f"  Heartbeat:  {result['heartbeat'].get('age_human', 'none')}")
    print(f"  Bridge:     {'reachable' if result['bridge'].get('reachable') else 'unreachable'}, "
          f"{'connected' if result['bridge'].get('connected') else 'disconnected'}")
    print(f"  Recon:      {'PASS' if result['monitoring']['reconciliation_passed'] else 'N/A'}")
    print(f"  Alerts:     {result['monitoring']['active_alert_count']}")
    print(f"  Gate H:     {'✓' if result['gate_h_mock'].get('ok') else '✗'}")
    print(f"  P5 Bracket: {'✓' if result['p5_bracket_mock'].get('ok') else '✗'}")
    print(f"  EP Scan:    {'✓' if result['forbidden_endpoint_scan'].get('ok') else '✗'}")

    if result["blockers"]:
        print(f"\n  {BOLD}Blockers:{RESET}")
        for b in result["blockers"]:
            sev_color = {"NO-GO": RED, "HOLD": RESET, "CLEAN": GREEN}.get(
                b["severity"], RESET)
            print(f"    [{sev_color}{b['severity']}{RESET}] {b['check']}: {b['detail']}")


def _print_market_data_diagnostics(result: dict) -> None:
    """Print market data diagnostics in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET
    diag = result.get("diagnosis", "unknown")
    sev = result.get("severity", "HOLD")

    if sev == "OK":
        sev_color = GREEN
    elif sev == "NO_GO":
        sev_color = RED
    else:
        sev_color = RESET

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Market Data Diagnostics (Step 15Q){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Diagnostic ID:     {result.get('diagnostic_id', '?')}")
    print(f"  Timestamp:         {result.get('timestamp', '?')}")
    print(f"  Symbol:            {result.get('symbol', '?')}")
    print()

    print(f"  {BOLD}Diagnosis:{RESET}      {diag}")
    print(f"  {BOLD}Severity:{RESET}       {sev_color}{sev}{RESET}")
    print()

    print(f"  {BOLD}Connection{RESET}")
    print(f"    IBKR connected:   {result.get('ibkr_connected', '?')}")
    print(f"    Bridge reachable: {result.get('bridge_reachable', '?')}")
    print(f"    Bridge runtime:   {'OK' if result.get('bridge_runtime_ok') else 'ERROR'}")
    print()

    print(f"  {BOLD}Contract{RESET}")
    print(f"    Qualified:        {result.get('contract_qualified', '?')}")
    qc = result.get("qualified_contract", {})
    if qc:
        print(f"    Symbol/Exch:      {qc.get('symbol', '?')}/{qc.get('exchange', '?')}")
        print(f"    Conid:            {qc.get('conid', '?')}")
    print()

    print(f"  {BOLD}Market Data{RESET}")
    print(f"    Live available:   {result.get('live_market_data_available', '?')}")
    print(f"    Delayed avail:    {result.get('delayed_market_data_available', '?')}")
    print(f"    Unavailability:   {result.get('market_data_unavailable_reason', '?')}")
    print()

    session = result.get("market_session_status", {})
    print(f"  {BOLD}Session{RESET}")
    print(f"    Status:           {session.get('session', '?')}")
    print(f"    Reason:           {session.get('reason', '?')}")
    print()

    print(f"  {BOLD}Impacts{RESET}")
    print(f"    Readiness:        {result.get('readiness_impact', '?')}")
    print(f"    Promotion:        {result.get('promotion_impact', '?')}")
    print()

    errors = result.get("observed_ibkr_errors", [])
    if errors:
        print(f"  {BOLD}IBKR Errors ({len(errors)}){RESET}")
        for e in errors:
            print(f"    [{e.get('source', '?')}] {e.get('message', '?')}")
        print()

    actions = result.get("suggested_operator_actions", [])
    if actions:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in actions:
            print(f"    →  {a}")
        print()

    # Explicit non-actions
    na = result.get("explicit_non_actions", [])
    if na:
        print(f"  {BOLD}Explicit Non-Actions{RESET}")
        for a in na:
            print(f"    ✗  {a}")
        print()

    print(f"  Evidence Hash:     {result.get('evidence_hash', '?')[:16]}...")
    print()
    print(f"  {BOLD}══════════════════════════════════════════════════{RESET}")


def print_candidate_dryrun(result: dict) -> None:
    """Print candidate dry-run result in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET
    verdict = result.get("verdict", "ERROR")
    v_color = {"READY_DRYRUN": GREEN, "HOLD": RESET, "NO-GO": RED, "ERROR": RED}.get(verdict, RESET)

    print(f"{BOLD}Candidate Dry-Run{RESET}  [{v_color}{verdict}{RESET}]")
    print(f"  Timestamp:  {result.get('timestamp', '?')}")
    print(f"  Symbol:     {result.get('symbol', '?')}")
    print(f"  Side:       {result.get('side', '?')}")
    print(f"  Quantity:   {result.get('quantity', '?')}")
    base_cur = result.get('account_evidence', {}).get('base_currency', 'EUR')
    print(f"  Notional:   {result.get('notional_eur', '?')} {base_cur}")
    print(f"  Git:        {result.get('git', {}).get('describe', '?')}"[:120])
    print()

    # Doctor
    doc = result.get("doctor", {})
    doc_pass = doc.get("pass", False)
    doc_color = GREEN if doc_pass else RED
    print(f"  Doctor:     {doc_color}{'PASS' if doc_pass else 'FAIL'}{RESET}  ({doc.get('passed', 0)}/{doc.get('total', 0)})")

    # KPI
    kpi = result.get("kpi", {})
    kpi_v = kpi.get("verdict", "?")
    kpi_color = {"GO": GREEN, "HOLD": RESET, "NO-GO": RED}.get(kpi_v, RESET)
    print(f"  KPI:        {kpi_color}{kpi_v}{RESET}")

    # Rehearsal
    rh = result.get("rehearsal", {})
    rh_v = rh.get("verdict", "?")
    rh_color = {"CLEAN": GREEN, "HOLD": RESET, "NO-GO": RED}.get(rh_v, RESET)
    print(f"  Rehearsal:  {rh_color}{rh_v}{RESET}")

    # IBKR connection
    ibkr = result.get("ibkr_connection", {})
    ibkr_color = GREEN if ibkr.get("connected") else RESET
    print(f"  IBKR:       {ibkr_color}{'connected' if ibkr.get('connected') else 'disconnected'}{RESET}")

    # Safety
    sf = result.get("bridge_safety_flags", {})
    safety_locked = (
        sf.get("env_IBKR_ALLOW_ORDERS") == "false"
        and sf.get("rules_enforced") == "false"
        and sf.get("system_locked") is True
    )
    print(f"  Safety:     {'LOCKED' if safety_locked else f'{RED}UNLOCKED{RESET}'}")

    # Gate H
    gh = result.get("gate_h", {})
    print(f"  Gate H:     {'✓' if gh.get('ok') else '✗'}  proposal={gh.get('proposal_id', '?')}")

    # P5
    p5 = result.get("p5_bracket", {})
    print(f"  P5 Bracket: {'✓' if p5.get('valid') else '✗'}")

    # EP Scan
    scan = result.get("forbidden_endpoint_scan", {})
    print(f"  EP Scan:    {'✓' if scan.get('ok') else '✗'}")

    # Stop
    stop = result.get("stop", {})
    if stop.get("price"):
        print(f"  Stop:       {stop['price']} ({stop.get('pct', '?')*100:.0f}%)")
    else:
        print(f"  Stop:       {stop.get('rationale', 'N/A')}")

    # Blockers
    blockers = result.get("blockers", [])
    if blockers:
        print(f"\n  {BOLD}Blockers:{RESET}")
        for b in blockers:
            sev_color = {"NO-GO": RED, "HOLD": RESET}.get(b["severity"], RESET)
            print(f"    [{sev_color}{b['severity']}{RESET}] {b['check']}: {b.get('detail', '')}"[:200])
    print()


def _print_evidence_cycle(result: dict) -> None:
    """Print evidence cycle result in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET
    clean = result.get("clean", False)
    status_text = f"{GREEN}CLEAN{RESET}" if clean else f"{RED}DIRTY{RESET}"

    print(f"{BOLD}Evidence Cycle{RESET}  [{status_text}]")
    print(f"  Timestamp:       {result.get('timestamp', '?')}")
    print(f"  Cycle ID:        {result.get('cycle_id', '?')}")
    print(f"  Symbol/Side:     {result.get('symbol', '?')} {result.get('side', '?')}")
    print(f"  Recorded:        {'✓' if result.get('recorded') else '✗'}")
    if result.get("ledger_path"):
        print(f"  Ledger:          {result['ledger_path']}")
    print(f"  Doctor:          {result.get('doctor_verdict', '?')}")
    print(f"  KPI:             {result.get('kpi_verdict', '?')}")
    print(f"  Rehearsal:       {result.get('rehearsal_verdict', '?')}")
    print(f"  Candidate:       {result.get('candidate_verdict', '?')}")
    print(f"  IBKR connected:  {result.get('ibkr_connected', False)}")
    print(f"  Market data:     {'available' if result.get('market_data_available') else 'missing'}")
    print(f"  FX available:    {result.get('fx_available')}  (required={result.get('fx_required')})")
    print(f"  EP scan clean:   {result.get('no_forbidden_endpoints', False)}")
    print(f"  Entry hash:      {result.get('entry_hash', '?')[:16]}...")

    blockers = result.get("blockers", [])
    dirty_reasons = result.get("dirty_reasons", [])
    if blockers or dirty_reasons:
        print(f"\n  {BOLD}Blocker details:{RESET}")
        for b in blockers:
            if isinstance(b, dict):
                sev_color = RED if b.get("severity") == "NO-GO" else RESET
                print(f"    [{sev_color}{b.get('severity', '?')}{RESET}] {b.get('check', '?')}: {b.get('detail', '')}")
            else:
                print(f"    - {b}")
        if dirty_reasons and not blockers:
            for r in dirty_reasons:
                print(f"    - {r}")
    print()


def _print_hermes_result(result: dict) -> None:
    """Print Hermes proposal result in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, RESET
    if not result.get("ok"):
        print(f"Hermes proposal FAILED: {result.get('error', 'unknown')}")
        print()
    else:
        print(f"{BOLD}Hermes-Advised Proposal{RESET}")
        print(f"{'=' * 40}")
        print()

    # Print evidence
    ev = result.get("evidence", {})
    print(f"{BOLD}Hermes Evidence Block{RESET}")
    print(f"  hermes_invoked: {ev.get('hermes_invoked', '?')}")
    print(f"  hermes_provider: {ev.get('hermes_provider', '?')}")
    print(f"  hermes_model: {ev.get('hermes_model', '?')}")
    print(f"  resolved_model: {ev.get('resolved_model', '?')}")
    print(f"  hermes_session_id: {ev.get('hermes_session_id', '?')}")
    print(f"  request: {ev.get('hermes_request_timestamp_utc', '?')}")
    print(f"  response: {ev.get('hermes_response_timestamp_utc', '?')}")
    print(f"  elapsed: {ev.get('elapsed_seconds', '?')}s")
    print(f"  source: {ev.get('final_proposal_source', '?')}")
    print()

    if result.get("ok") and result.get("proposal"):
        p = result["proposal"]
        print(f"{BOLD}Proposal{RESET}")
        print(f"  Symbol:          {p.get('symbol', '?')}")
        print(f"  Side:            {p.get('side', '?')}")
        print(f"  Quantity:        {p.get('quantity', '?')}")
        print(f"  Entry:           {p.get('entry_reference', '?')}")
        print(f"  Stop/Invalid:    {p.get('stop_loss_invalidation', '?')}")
        print(f"  Max Loss:        {p.get('max_loss_eur', '?')} EUR / {p.get('max_loss_pct', '?')}%")
        print(f"  Notional:        {p.get('position_notional_eur', '?')} EUR / {p.get('position_notional_pct', '?')}%")
        print(f"  Exposure after:  {p.get('portfolio_exposure_after_pct', '?')}%")
        print(f"  Daily drawdown:  {p.get('daily_drawdown_status', '?')}")
        print(f"  Weekly drawdown: {p.get('weekly_drawdown_status', '?')}")
        print(f"  Reason to trade: {p.get('reason_to_trade', '?')}")
        print(f"  Reason not to:   {p.get('reason_not_to_trade', '?')}")
        print()
        print(f"  Preflight cmd:")
        print(f"    {p.get('preflight_command', '?')}")
        print()
        if p.get("facts"):
            print(f"{BOLD}Facts{RESET}")
            for f in p["facts"]:
                print(f"  \u2022 {f}")
        if p.get("assumptions"):
            print(f"{BOLD}Assumptions{RESET}")
            for a in p["assumptions"]:
                print(f"  \u2022 {a}")
        if p.get("unknowns"):
            print(f"{BOLD}Unknowns{RESET}")
            for u in p["unknowns"]:
                print(f"  \u2022 {u}")
        print()
        print(f"  {BOLD}Awaiting Chris approval{RESET} \u2014 {p.get('awaiting_chris_approval', False)}")
        print(f"  {BOLD}Advisory only{RESET} \u2014 {p.get('advisory_only', False)}")
        print()
        if result.get("proposal_path"):
            print(f"  {BOLD}Persisted{RESET} \u2014 {result['proposal_path']}")
            print(f"  (pass this path as proposal_path to /order/preflight for Gate H)")
        elif result.get("proposal_persist_error"):
            print(f"  {BOLD}NOT persisted{RESET} \u2014 {result['proposal_persist_error']}")

    print()
    print(f"{BOLD}Advisory only. No order enabled or submitted. No state mutated.{RESET}")


def print_autonomy_status(result: dict) -> None:
    """Print autonomy status in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _CLEAN_CYCLES_REQUIRED, _CLEAN_CYCLES_WINDOW_DAYS
    rec = result.get("recommendation", "HOLD")
    if rec == "READY_FOR_MANUAL_REVIEW":
        rec_color = GREEN
        rec_text = f"{GREEN}READY_FOR_MANUAL_REVIEW{RESET}"
    elif rec == "NO_GO":
        rec_color = RED
        rec_text = f"{RED}NO_GO{RESET}"
    else:
        rec_color = RESET
        rec_text = f"{RESET}HOLD{RESET}"

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Autonomy Readiness Evaluator{RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Timestamp:          {result.get('timestamp', '?')}")
    print(f"  Git:                {result['git'].get('branch', '?')} @ {result['git'].get('commit', '?')}  (tag: {result['git'].get('tag', '?')})")
    print()

    print(f"  {BOLD}Recommendation: {rec_text}{RESET}\n")

    print(f"  {BOLD}Autonomy Levels{RESET}")
    print(f"    Current: {result.get('current_autonomy_level', '?')}")
    print(f"    Target:  {result.get('target_autonomy_level', '?')}")
    print()

    print(f"  {BOLD}Clean Cycles{RESET}")
    print(f"    Observed:  {result.get('clean_cycles_observed', 0)}")
    print(f"    Required:  {result.get('clean_cycles_required', _CLEAN_CYCLES_REQUIRED)}")
    print(f"    Window:    {result.get('clean_cycles_window_days', _CLEAN_CYCLES_WINDOW_DAYS)} days")
    print(f"    Latest:    {result.get('latest_clean_cycle_timestamp', 'none')}")
    print(f"    Ledger:    {result.get('ledger_path', '?')}")
    print()

    print(f"  {BOLD}Bridge{RESET}")
    print(f"    Reachable: {result.get('bridge_reachable', False)}")
    print(f"    Connected: {result.get('ibkr_connected', False)}")
    print()

    print(f"  {BOLD}Safety{RESET}")
    print(f"    Locked:    {result.get('safety_locked', False)}")
    print(f"    Allow Ord: {result.get('env_IBKR_ALLOW_ORDERS', '?')}")
    print(f"    Enforced:  {result.get('rules_enforced', '?')}")
    print()

    print(f"  {BOLD}Verdicts{RESET}")
    print(f"    Doctor:    {result.get('doctor_verdict', '?')}")
    print(f"    KPI:       {result.get('kpi_verdict', '?')}")
    print(f"    Candidate: {result.get('latest_candidate_verdict', '?')}")
    print()

    print(f"  {BOLD}Monitoring{RESET}")
    print(f"    Alerts:    {result.get('active_alert_count', 0)}")
    print(f"    Recon:     {'PASS' if result.get('reconciliation_passed') else 'N/A'}")
    print()

    print(f"  {BOLD}Data Status{RESET}")
    print(f"    Market:    {result.get('market_data_status', '?')}")
    print(f"    FX:        {result.get('fx_status', '?')}")
    print()

    blockers = result.get("blockers", [])
    if blockers:
        print(f"  {BOLD}Blockers ({len(blockers)}){RESET}")
        for b in blockers:
            sev_color = RED if b["severity"] == "NO-GO" else RESET
            print(f"    [{sev_color}{b['severity']}{RESET}] {b['check']}: {b.get('detail', '')}"[:200])
        print()

    exports = result.get("evidence_exports", [])
    if exports:
        print(f"  {BOLD}Evidence Exports{RESET}")
        for e in exports:
            print(f"    {e}")
        print()

    print(f"  no_broker_mutation: {result.get('no_broker_mutation', True)}")
    print()


def _print_promotion_plan(result: dict) -> None:
    """Print autonomy promotion plan in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET
    ps = result.get("plan_status", "HOLD")
    if ps == "READY_FOR_MANUAL_DECISION":
        ps_color = GREEN
        ps_text = f"{GREEN}READY_FOR_MANUAL_DECISION{RESET}"
    elif ps == "NO_GO":
        ps_color = RED
        ps_text = f"{RED}NO_GO{RESET}"
    else:
        ps_color = RESET
        ps_text = f"{RESET}HOLD{RESET}"

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Autonomy Level 0 → 1 Promotion Plan (Step 15M){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Plan ID:           {result.get('plan_id', '?')}")
    print(f"  Timestamp:         {result.get('timestamp', '?')}")
    print(f"  Git:               {result['git'].get('branch', '?')} @ "
          f"{result['git'].get('commit', '?')}")
    print()

    print(f"  {BOLD}Plan Status: {ps_text}{RESET}\n")

    print(f"  {BOLD}Autonomy Levels{RESET}")
    print(f"    Current:          {result.get('current_autonomy_level', '?')}")
    print(f"    Target:           {result.get('target_autonomy_level', '?')}")
    print()

    print(f"  {BOLD}Evidence{RESET}")
    print(f"    Clean Cycles:     {result.get('clean_cycles_observed', 0)}/"
          f"{result.get('clean_cycles_required', 5)}")
    print(f"    Doctor:           {result.get('doctor_verdict', '?')}")
    print(f"    KPI:              {result.get('kpi_verdict', '?')}")
    print(f"    Autonomy-Status:  {result.get('autonomy_status_recommendation', '?')}")
    print(f"    Autonomy-Review:  {result.get('autonomy_review_status', '?')}")
    print()

    sf = result.get("safety_flags", {})
    print(f"  {BOLD}Safety{RESET}")
    print(f"    Locked:           {sf.get('safety_locked', '?')}")
    print(f"    IBKR_ALLOW_ORDERS:{sf.get('env_IBKR_ALLOW_ORDERS', '?')}")
    print(f"    rules.enforced:   {sf.get('rules_enforced', '?')}")
    print()

    print(f"  {BOLD}Connection{RESET}")
    print(f"    Bridge Connected: {result.get('bridge_connected', '?')}")
    print(f"    Market Data:      {result.get('market_data_status', '?')}")
    print(f"    FX:               {result.get('fx_status', '?')}")
    print()

    print(f"  {BOLD}Alerts{RESET}")
    print(f"    Active:           {result.get('active_alert_count', 0)}")
    print(f"    Reconciliation:   {result.get('reconciliation_passed', '?')}")
    print()

    blockers = result.get("blockers", [])
    if blockers:
        print(f"  {BOLD}Blockers ({len(blockers)}){RESET}")
        for b in blockers:
            sev = b["severity"]
            sev_color = RED if sev == "NO-GO" else RESET
            print(f"    {sev_color}{sev:<6}{RESET} {b['check']}: {b.get('detail', '?')}")
        print()

    print(f"  {BOLD}Operator Decision Required: YES{RESET}")
    print(f"  Auto-Promotion:    {result.get('auto_promotion_performed', False)}")
    print(f"  Config Changed:    {result.get('config_changed', False)}")
    print(f"  Broker Mutation:   {not result.get('no_broker_mutation', True)}")
    print()

    pre = result.get("manual_preconditions", [])
    if pre:
        print(f"  {BOLD}Manual Preconditions{RESET}")
        for p in pre:
            print(f"    [{p['step']}]  {p['precondition']}")
        print()

    steps = result.get("manual_promotion_steps", [])
    if steps:
        print(f"  {BOLD}Manual Promotion Steps{RESET}")
        for s in steps:
            print(f"    {s['action']}")
        print()

    rb = result.get("manual_rollback_steps", [])
    if rb:
        print(f"  {BOLD}Manual Rollback Steps{RESET}")
        for s in rb:
            print(f"    {s['action']}")
        print()

    na = result.get("explicit_non_actions", [])
    if na:
        print(f"  {BOLD}Explicit Non-Actions{RESET}")
        for a in na:
            print(f"    ✗  {a}")
        print()

    print(f"  Evidence Hash:     {result.get('evidence_hash', '?')[:16]}...")
    print()
    print(f"  {BOLD}══════════════════════════════════════════════════{RESET}")


def print_autonomy_review(result: dict) -> None:
    """Print autonomy review package in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _CLEAN_CYCLES_REQUIRED
    rs = result.get("review_status", "HOLD")
    if rs == "READY_FOR_OPERATOR_REVIEW":
        rs_color = GREEN
        rs_text = f"{GREEN}READY_FOR_OPERATOR_REVIEW{RESET}"
    elif rs == "NO_GO":
        rs_color = RED
        rs_text = f"{RED}NO_GO{RESET}"
    else:
        rs_color = RESET
        rs_text = f"{RESET}HOLD{RESET}"

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Autonomy Promotion Review Package{RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Review ID:         {result.get('review_id', '?')}")
    print(f"  Timestamp:         {result.get('timestamp', '?')}")
    print(f"  Git:               {result['git'].get('branch', '?')} @ {result['git'].get('commit', '?')}")
    print()

    print(f"  {BOLD}Review Status: {rs_text}{RESET}\n")

    print(f"  {BOLD}Autonomy Levels{RESET}")
    print(f"    Current:          {result.get('current_autonomy_level', '?')}")
    print(f"    Target:           {result.get('target_autonomy_level', '?')}")
    print()

    print(f"  {BOLD}Clean Cycles{RESET}")
    print(f"    Observed:         {result.get('clean_cycles_observed', 0)}")
    print(f"    Required:         {result.get('clean_cycles_required', _CLEAN_CYCLES_REQUIRED)}")
    print(f"    Ledger:           {result.get('clean_cycle_ledger_path', '?')}")
    entries = result.get('clean_cycle_entries_used', [])
    if entries:
        for e in entries[:5]:
            print(f"      {e.get('cycle_id', '?')}  {e.get('symbol', '?')}/{e.get('side', '?')}  {e.get('timestamp', '?')}")
        if len(entries) > 5:
            print(f"      ... and {len(entries) - 5} more")
    print()

    print(f"  {BOLD}Safety{RESET}")
    sf = result.get("safety_flags", {})
    print(f"    Locked:           {sf.get('safety_locked', False)}")
    print(f"    Allow Orders:     {sf.get('env_IBKR_ALLOW_ORDERS', '?')}")
    print(f"    Rules Enforced:   {sf.get('rules_enforced', '?')}")
    print()

    print(f"  {BOLD}Summaries{RESET}")
    aus = result.get("latest_autonomy_status_summary", {})
    print(f"    Autonomy-status:  {aus.get('recommendation', '?')}")
    kpi = result.get("latest_kpi_summary", {})
    print(f"    KPI:              {kpi.get('verdict', '?')}")
    cand = result.get("latest_candidate_summary", {})
    print(f"    Candidate:        {cand.get('verdict', '?')}  ({cand.get('symbol', '?')} {cand.get('side', '?')})")
    doc = result.get("doctor_summary", {})
    doc_pass = doc.get("pass")
    doc_label = "PASS" if doc_pass is True else ("FAIL" if doc_pass is False else "N/A")
    print(f"    Doctor:           {doc_label}  ({doc.get('passed', 0)}/{doc.get('total', 0)})")
    print()

    print(f"  {BOLD}Connection & Data{RESET}")
    print(f"    IBKR connected:   {result.get('ibkr_connected', False)}")
    print(f"    Market data:      {result.get('market_data_status', '?')}")
    print(f"    FX:               {result.get('fx_status', '?')}")
    print(f"    Active alerts:    {result.get('active_alert_count', 0)}")
    print(f"    Reconciliation:   {'PASS' if result.get('reconciliation_passed') else 'N/A'}")
    print()

    blockers = result.get("blockers", [])
    if blockers:
        print(f"  {BOLD}Blockers ({len(blockers)}){RESET}")
        for b in blockers:
            sev_color = RED if b["severity"] == "NO-GO" else RESET
            print(f"    [{sev_color}{b['severity']}{RESET}] {b['check']}: {b.get('detail', '')}"[:200])
        print()

    print(f"  {BOLD}Manual Review Checklist{RESET}")
    for item in result.get("manual_review_checklist", []):
        print(f"    [{item['item']}] {item['task']}")
    print()

    print(f"  Evidence hash:     {result.get('evidence_hash', '?')[:16]}...")
    print(f"  Export:            {result.get('_export_path', '?')}")
    print(f"  operator_decision_required: {result.get('operator_decision_required', True)}")
    print(f"  auto_promotion_performed:   {result.get('auto_promotion_performed', False)}")
    print(f"  no_broker_mutation:         {result.get('no_broker_mutation', True)}")
    print()


def _print_phase15_completion_checkpoint(result: dict) -> None:
    """Print Phase-15 completion checkpoint in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    ph15_complete = result.get("phase15_complete", False)
    diagnosis = result.get("diagnosis", "?")
    diag_color = GREEN if ph15_complete else RED

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Phase-15 Completion Checkpoint / Promotion Readiness{RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    sev = result.get('severity', '?')
    sev_color = GREEN if sev == 'OK' else (YELLOW if sev == 'HOLD' else RED)

    print(f"  Timestamp:       {result.get('timestamp', '?')}")
    print(f"  Checkpoint ID:   {result.get('checkpoint_id', '?')}")
    print(f"  Diagnosis:       {diag_color}{diagnosis}{RESET}")
    print(f"  Severity:        {sev_color}{sev}{RESET}")
    print(f"  Phase-15 done:   {diag_color}{result.get('phase15_complete', False)}{RESET}")
    if result.get('operator_action_required'):
        print(f"  Operator action: {RED}REQUIRED{RESET}")
    print()

    # Git
    g = result.get("git", {})
    print(f"  {BOLD}Git / Worktree{RESET}")
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Tag:           {g.get('tag', '?')}")
    print(f"    Origin/master: {g.get('origin_master_aligned', '?')}")
    wtc = g.get("worktree_clean")
    wtc_str = f"{GREEN}clean{RESET}" if wtc is True else (f"{RED}dirty{RESET}" if wtc is False else "?")
    print(f"    Worktree:      {wtc_str}")
    dirty = g.get("dirty_files", [])
    if dirty:
        for f in dirty[:10]:
            print(f"      {YELLOW}{f}{RESET}")
        if len(dirty) > 10:
            print(f"      ... and {len(dirty) - 10} more")
    print()

    # Phase-15 tags
    pt = result.get("phase15_tags", {})
    missing_tags = pt.get("missing", [])
    missing_count = len(missing_tags)
    tag_color = GREEN if missing_count == 0 else RED
    print(f"  {BOLD}Phase-15 Tags{RESET}")
    print(f"    Required:       {pt.get('required_count', 0)}")
    print(f"    Present:        {tag_color}{pt.get('present_count', 0)}{RESET}")
    for tag in missing_tags:
        print(f"      {RED}✗{RESET} {tag}")
    if missing_count == 0:
        print(f"      {GREEN}All tags present{RESET}")
    print()

    # Runtime
    rt = result.get("runtime", {})
    print(f"  {BOLD}Runtime / Bridge{RESET}")
    print(f"    Reachable:      {_bool_str(rt.get('bridge_reachable'))}")
    print(f"    Service active: {_bool_str(rt.get('bridge_service_active'))}")
    dup_procs = rt.get('duplicate_bridge_processes', False)
    dup_str = f"{RED}yes{RESET}" if dup_procs else f"{GREEN}no{RESET}"
    print(f"    Duplicate procs:{dup_str}")
    print(f"    Connected:      {_bool_str(rt.get('bridge_connected'))}")
    print(f"    Mode:           {rt.get('mode', '?')}")
    print(f"    Read-only:      {_bool_str(rt.get('read_only'))}")
    print(f"    Endpoints:      {rt.get('endpoints_display', '?')}")
    print(f"    Positions:      {rt.get('positions_count', '?')}  flat={_bool_str(rt.get('positions_flat'))}")
    print(f"    Active alerts:  {rt.get('active_alerts_count', '?')}")
    print()

    # Safety
    sf = result.get("safety", {})
    print(f"  {BOLD}Safety Flags{RESET}")
    print(f"    IBKR_ALLOW_ORDERS: {sf.get('env_IBKR_ALLOW_ORDERS', '?')}")
    print(f"    rules.enforced:    {sf.get('rules_enforced', '?')}")
    print(f"    system_locked:     {sf.get('system_locked', '?')}")
    print(f"    Autonomy level:    {sf.get('autonomy_level', '?')}")
    print(f"    Clean cycles:      {sf.get('clean_cycles', '?')}")
    print(f"    Safety expected:   {_bool_str(sf.get('safety_locked_expected'))}")
    print()

    # Guard state
    gs = result.get("guard_state", {})
    print(f"  {BOLD}Guard State{RESET}")
    print(f"    Daily trade count: {gs.get('daily_trade_count', '?')}")
    print(f"    Trade date:        {gs.get('trade_date', '?')}")
    print(f"    Canonical date:    {gs.get('canonical_trade_date', '?')}")
    print(f"    Stale:             {_bool_str(gs.get('trade_date_stale'))}")
    print(f"    Halt active:       {gs.get('halt_active', '?')}")
    gh = gs.get("hash")
    if gh:
        print(f"    Hash:              {gh[:16]}...")
    print()

    # Doctor
    doc = result.get("doctor_summary", {})
    doc_color = GREEN if doc.get("acceptable") else RED
    print(f"  {BOLD}Doctor{RESET}")
    print(f"    Result:     {doc.get('result', '?')}")
    print(f"    Score:      {doc.get('pass_count', '?')}/{doc.get('total_count', '?')}")
    print(f"    H1 canary:  {doc.get('h1_canary_status', '?')}")
    print(f"    Acceptable: {doc_color}{doc.get('acceptable', False)}{RESET}")
    print()

    # KPI
    kpi = result.get("kpi_summary", {})
    kpi_color = GREEN if kpi.get("acceptable_hold") else RED
    print(f"  {BOLD}KPI Dashboard{RESET}")
    print(f"    Verdict:         {kpi.get('verdict', '?')}")
    if kpi.get("blockers"):
        print(f"    Blockers:        {', '.join(kpi['blockers'][:10])}")
    print(f"    Acceptable HOLD: {kpi_color}{kpi.get('acceptable_hold', False)}{RESET}")
    print()

    # Policy
    pol = result.get("policy_summary", {})
    pol_color = GREEN if (pol.get("hermes_policy_exists") and pol.get("execution_path_ok")) else RED
    print(f"  {BOLD}Policy{RESET}")
    print(f"    Hermes policy:   {_bool_str(pol.get('hermes_policy_exists'))}")
    print(f"    Exec path OK:    {_bool_str(pol.get('execution_path_ok'))}")
    print(f"    Advisory OK:     {_bool_str(pol.get('advisory_boundary_ok'))}")
    print()

    # Readiness
    rs = result.get("readiness_summary", {})
    rs_color = GREEN if rs.get("phase15_complete") else RED
    print(f"  {BOLD}Readiness Summary{RESET}")
    print(f"    Phase-15 complete:          {rs_color}{rs.get('phase15_complete', False)}{RESET}")
    print(f"    Promotion review ready:     {rs.get('promotion_review_ready', False)}")
    print(f"    Promotion allowed now:      {rs.get('promotion_allowed_now', False)}")
    print(f"    Order enablement allowed:   {rs.get('order_enablement_allowed_now', False)}")
    print(f"    Required next step:         {rs.get('required_next_step', '?')}")
    print()

    # Suggested actions
    sa = result.get("suggested_operator_actions", [])
    if sa:
        print(f"  {BOLD}Suggested Operator Actions{RESET}")
        for a in sa:
            print(f"    {YELLOW}→{RESET} {a}")
        print()

    print(f"  {BOLD}Advisory{RESET}")
    print(f"    {result.get('advisory', '')}")

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"\n  Evidence hash: {eh[:16]}...")

    ep = result.get("export_path") or result.get("_export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_manual_level1_promotion_review(result: dict) -> None:
    """Print Phase 16B review in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16B_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    review_ready = (result.get("diagnosis") == _PHASE16B_DIAGNOSIS["ready"])
    diag_color = GREEN if review_ready else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else (YELLOW if sev == "HOLD" else RED)

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Manual Level-1 Promotion Procedure Review (16B){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Timestamp:       {result.get('timestamp', '?')}")
    print(f"  Review ID:       {result.get('review_id', '?')}")
    print(f"  Diagnosis:       {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:        {sev_color}{sev}{RESET}")
    if result.get("operator_action_required"):
        print(f"  Operator action: {RED}REQUIRED{RESET}")
    print()

    # Git
    g = result.get("git", {})
    print(f"  {BOLD}Git / Worktree{RESET}")
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Tag:           {g.get('tag', '?')}")
    print(f"    Origin/master: {g.get('origin_master_aligned', '?')}")
    wtc = g.get("worktree_clean")
    wtc_str = f"{GREEN}clean{RESET}" if wtc is True else (f"{RED}dirty{RESET}" if wtc is False else "?")
    print(f"    Worktree:      {wtc_str}")
    dirty = g.get("dirty_files", [])
    if dirty:
        for f in dirty[:10]:
            print(f"      {YELLOW}{f}{RESET}")
    print()

    # Required tags
    rt = result.get("required_tags", {})
    missing_tags = rt.get("missing", [])
    tag_color = GREEN if len(missing_tags) == 0 else RED
    print(f"  {BOLD}Required Tags (16A + 15Z){RESET}")
    print(f"    Required:       {rt.get('required_count', 0)}")
    print(f"    Present:        {tag_color}{rt.get('present_count', 0)}{RESET}")
    for tag in missing_tags:
        print(f"      {RED}✗{RESET} {tag}")
    if len(missing_tags) == 0:
        print(f"      {GREEN}All required tags present{RESET}")
    print()

    # Runtime
    rtr = result.get("runtime", {})
    print(f"  {BOLD}Runtime / Bridge{RESET}")
    print(f"    Reachable:      {_bool_str(rtr.get('bridge_reachable'))}")
    print(f"    Connected:      {_bool_str(rtr.get('bridge_connected'))}")
    print(f"    Mode:           {rtr.get('mode', '?')}")
    print(f"    Read-only:      {_bool_str(rtr.get('read_only'))}")
    print(f"    Endpoints:      {rtr.get('endpoints_display', '?')}")
    print(f"    Positions:      {rtr.get('positions_count', '?')}  flat={_bool_str(rtr.get('positions_flat'))}")
    print(f"    Active alerts:  {rtr.get('active_alerts_count', '?')}")
    print()

    # Safety
    sf = result.get("safety", {})
    print(f"  {BOLD}Safety Flags{RESET}")
    print(f"    IBKR_ALLOW_ORDERS:     {sf.get('env_IBKR_ALLOW_ORDERS', '?')}")
    print(f"    rules.enforced:        {sf.get('rules_enforced', '?')}")
    print(f"    system_locked:         {sf.get('system_locked', '?')}")
    print(f"    Autonomy current:      {sf.get('autonomy_level_current', '?')}")
    print(f"    Target level:          {sf.get('target_autonomy_level', '?')}")
    print(f"    State locked:          {_bool_str(sf.get('current_state_locked'))}")
    print()

    # Guard state
    gs = result.get("guard_state", {})
    print(f"  {BOLD}Guard State{RESET}")
    print(f"    Daily trade count: {gs.get('daily_trade_count', '?')}")
    print(f"    Trade date:        {gs.get('trade_date', '?')}")
    print(f"    Canonical date:    {gs.get('canonical_trade_date', '?')}")
    print(f"    Stale:             {_bool_str(gs.get('trade_date_stale'))}")
    gh = gs.get("hash")
    if gh:
        print(f"    Hash:              {gh[:16]}...")
    print()

    # Doctor / KPI
    doc = result.get("doctor_summary", {})
    doc_color = GREEN if doc.get("acceptable") else RED
    print(f"  {BOLD}Doctor / KPI{RESET}")
    print(f"    Doctor:     {doc.get('result', '?')}  H1={doc.get('h1_canary_status', '?')}  ok={doc_color}{doc.get('acceptable', False)}{RESET}")
    kpi = result.get("kpi_summary", {})
    kpi_color = GREEN if kpi.get("acceptable_hold") else RED
    print(f"    KPI:        {kpi.get('verdict', '?')}  blockers={kpi.get('blockers', [])}  ok={kpi_color}{kpi.get('acceptable_hold', False)}{RESET}")
    print()

    # Policy
    pol = result.get("policy_summary", {})
    print(f"  {BOLD}Policy{RESET}")
    print(f"    Hermes policy:   {_bool_str(pol.get('hermes_policy_exists'))}")
    print(f"    Exec path OK:    {_bool_str(pol.get('execution_path_ok'))}")
    print(f"    Advisory OK:     {_bool_str(pol.get('advisory_boundary_ok'))}")
    print()

    # Prerequisites
    pr = result.get("promotion_prerequisites", {})
    print(f"  {BOLD}Promotion Prerequisites{RESET}")
    for key, val in pr.items():
        print(f"    {key:<28} {_bool_str(val)}")
    print()

    # Promotion plan
    pp = result.get("promotion_plan", {})
    print(f"  {BOLD}Promotion Plan{RESET}")
    print(f"    Review only:              {pp.get('review_only', True)}")
    print(f"    Promotion allowed now:    {pp.get('promotion_allowed_now', False)}")
    print(f"    Order enablement allowed: {pp.get('order_enablement_allowed_now', False)}")
    print(f"    Proposed next step:       {pp.get('proposed_next_step', '?')}")
    if pp.get("required_human_approvals"):
        print(f"    Human approvals required:")
        for ha in pp["required_human_approvals"]:
            print(f"      • {ha}")
    if pp.get("required_future_controls"):
        print(f"    Future controls:")
        for fc in pp["required_future_controls"]:
            print(f"      • {fc}")
    print(f"    Rollback: {pp.get('rollback_plan_summary', '?')[:120]}...")
    print()

    # Dry-run procedure
    drp = result.get("dry_run_procedure", {})
    print(f"  {BOLD}Dry-Run Procedure ({drp.get('step_count', 0)} steps){RESET}")
    for step in drp.get("steps", []):
        print(f"    Step {step.get('step_number', '?')}: {step.get('title', '?')}")
        print(f"      Purpose:    {step.get('purpose', '?')}")
        print(f"      Command:    {step.get('command_or_action', '?')}")
        print(f"      Expected:   {step.get('expected_result', '?')}")
        print(f"      Risk:       {step.get('risk', '?')}")
        print(f"      Rollback:   {step.get('rollback', '?')}")
        print()

    # Suggested actions
    sa = result.get("suggested_operator_actions", [])
    if sa:
        print(f"  {BOLD}Suggested Operator Actions{RESET}")
        for a in sa:
            print(f"    {YELLOW}→{RESET} {a}")
        print()

    print(f"  {BOLD}Advisory{RESET}")
    print(f"    {result.get('advisory', '')}")

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"\n  Evidence hash: {eh[:16]}...")

    ep = result.get("export_path") or result.get("_export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_promotion_dry_run_gate(result: dict) -> None:
    """Print Phase 16C dry-run gate in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16C_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    gate_ready = (result.get("diagnosis") == _PHASE16C_DIAGNOSIS["ready"])
    diag_color = GREEN if gate_ready else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else (YELLOW if sev == "HOLD" else RED)

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level-1 Promotion Dry-Run Gate (Phase 16C){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Timestamp:       {result.get('timestamp', '?')}")
    print(f"  Gate ID:         {result.get('gate_id', '?')}")
    print(f"  Diagnosis:       {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:        {sev_color}{sev}{RESET}")
    if result.get("operator_action_required"):
        print(f"  Operator action: {RED}REQUIRED{RESET}")

    dg = result.get("dry_run_gate", {})
    print(f"  Gate ready:      {GREEN if dg.get('gate_ready') else RED}{dg.get('gate_ready', False)}{RESET}")
    print()

    # Git
    g = result.get("git", {})
    print(f"  {BOLD}Git / Worktree{RESET}")
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Tag:           {g.get('tag', '?')}")
    print(f"    Origin/master: {g.get('origin_master_aligned', '?')}")
    wtc = g.get("worktree_clean")
    wtc_str = f"{GREEN}clean{RESET}" if wtc is True else (f"{RED}dirty{RESET}" if wtc is False else "?")
    print(f"    Worktree:      {wtc_str}")
    dirty = g.get("dirty_files", [])
    if dirty:
        for f in dirty[:10]:
            print(f"      {YELLOW}{f}{RESET}")
    print()

    # Required tags
    rt = result.get("required_tags", {})
    missing_tags = rt.get("missing", [])
    tag_color = GREEN if len(missing_tags) == 0 else RED
    print(f"  {BOLD}Required Tags (16B + 16A + 15Z){RESET}")
    print(f"    Required:       {rt.get('required_count', 0)}")
    print(f"    Present:        {tag_color}{rt.get('present_count', 0)}{RESET}")
    for tag in missing_tags:
        print(f"      {RED}✗{RESET} {tag}")
    if len(missing_tags) == 0:
        print(f"      {GREEN}All required tags present{RESET}")
    print()

    # Runtime
    rtr = result.get("runtime", {})
    print(f"  {BOLD}Runtime / Bridge{RESET}")
    print(f"    Reachable:      {_bool_str(rtr.get('bridge_reachable'))}")
    print(f"    Connected:      {_bool_str(rtr.get('bridge_connected'))}")
    print(f"    Mode:           {rtr.get('mode', '?')}")
    print(f"    Read-only:      {_bool_str(rtr.get('read_only'))}")
    print(f"    Endpoints:      {rtr.get('endpoints_display', '?')}")
    print(f"    Positions:      {rtr.get('positions_count', '?')}  flat={_bool_str(rtr.get('positions_flat'))}")
    print(f"    Active alerts:  {rtr.get('active_alerts_count', '?')}")
    print()

    # Safety
    sf = result.get("safety", {})
    print(f"  {BOLD}Safety Flags{RESET}")
    print(f"    IBKR_ALLOW_ORDERS:     {sf.get('env_IBKR_ALLOW_ORDERS', '?')}")
    print(f"    rules.enforced:        {sf.get('rules_enforced', '?')}")
    print(f"    system_locked:         {sf.get('system_locked', '?')}")
    print(f"    Autonomy current:      {sf.get('autonomy_level_current', '?')}")
    print(f"    Target level:          {sf.get('target_autonomy_level', '?')}")
    print(f"    State locked:          {_bool_str(sf.get('current_state_locked'))}")
    print()

    # Guard state
    gs = result.get("guard_state", {})
    print(f"  {BOLD}Guard State{RESET}")
    print(f"    Daily trade count: {gs.get('daily_trade_count', '?')}")
    print(f"    Trade date:        {gs.get('trade_date', '?')}")
    print(f"    Canonical date:    {gs.get('canonical_trade_date', '?')}")
    print(f"    Stale:             {_bool_str(gs.get('trade_date_stale'))}")
    gh = gs.get("hash")
    if gh:
        print(f"    Hash:              {gh[:16]}...")
    print()

    # Doctor / KPI
    doc = result.get("doctor_summary", {})
    doc_color = GREEN if doc.get("acceptable") else RED
    print(f"  {BOLD}Doctor / KPI{RESET}")
    print(f"    Doctor:     {doc.get('result', '?')}  H1={doc.get('h1_canary_status', '?')}  ok={doc_color}{doc.get('acceptable', False)}{RESET}")
    kpi = result.get("kpi_summary", {})
    kpi_color = GREEN if kpi.get("acceptable_hold") else RED
    print(f"    KPI:        {kpi.get('verdict', '?')}  blockers={kpi.get('blockers', [])}  ok={kpi_color}{kpi.get('acceptable_hold', False)}{RESET}")
    print()

    # Dry-run gate
    print(f"  {BOLD}Dry-Run Gate{RESET}")
    print(f"    Gate ready:              {_bool_str(dg.get('gate_ready'))}")
    print(f"    Promotion performed:     {dg.get('promotion_performed', '?')}")
    print(f"    Order enablement:        {dg.get('order_enablement_performed', '?')}")
    print(f"    Requires human apply:    {dg.get('requires_future_explicit_human_apply', '?')}")
    print(f"    Proposed next step:      {dg.get('proposed_next_step', '?')}")
    print(f"    Future apply preview:    {dg.get('future_apply_command_preview', '?')[:100]}...")
    print(f"    Rollback preview:        {dg.get('rollback_command_preview', '?')[:100]}...")
    print(f"    Relock preview:          {dg.get('relock_command_preview', '?')[:100]}...")
    if dg.get("required_human_signoffs"):
        print(f"    Human signoffs required:")
        for s in dg["required_human_signoffs"]:
            print(f"      • {s}")
    print()

    # Future Level-1 controls
    flc = result.get("future_level1_controls", {})
    print(f"  {BOLD}Future Level-1 Controls{RESET}")
    print(f"    Max autonomy:            {flc.get('max_autonomy_level', '?')}")
    print(f"    Advisory-only Hermes:    {_bool_str(flc.get('advisory_only_hermes'))}")
    print(f"    Manual approval req'd:   {_bool_str(flc.get('manual_approval_required'))}")
    print(f"    Order window required:   {_bool_str(flc.get('order_window_required'))}")
    print(f"    H1 for approve/submit:   {_bool_str(flc.get('h1_required_for_approve_submit'))}")
    print(f"    Preflight required:      {_bool_str(flc.get('preflight_required'))}")
    print(f"    Submit path:             {flc.get('submit_path_only', '?')}")
    print(f"    Post-promo relock req'd: {_bool_str(flc.get('post_promotion_relock_required'))}")
    print()

    # Dry-run steps
    drs = result.get("dry_run_steps", {})
    print(f"  {BOLD}Dry-Run Steps ({drs.get('step_count', 0)} steps){RESET}")
    for step in drs.get("steps", []):
        print(f"    Step {step.get('step_number', '?')}: {step.get('title', '?')}")
        print(f"      Expected:   {step.get('expected_result', '?')}")
        print(f"      Risk:       {step.get('risk', '?')}")
        print()

    # Suggested actions
    sa = result.get("suggested_operator_actions", [])
    if sa:
        print(f"  {BOLD}Suggested Operator Actions{RESET}")
        for a in sa:
            print(f"    {YELLOW}→{RESET} {a}")
        print()

    print(f"  {BOLD}Advisory{RESET}")
    print(f"    {result.get('advisory', '')}")

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"\n  Evidence hash: {eh[:16]}...")

    ep = result.get("export_path") or result.get("_export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_apply_gate(result: dict) -> None:
    """Print Phase 16D apply gate in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    apply_performed = result.get("apply_gate", {}).get("apply_performed", False)
    apply_ready = result.get("apply_gate", {}).get("apply_ready", False)
    diag = result.get("diagnosis", "?")
    diag_color = GREEN if apply_performed else (GREEN if apply_ready else RED)
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else (YELLOW if sev == "HOLD" else RED)
    mode_label = result.get("mode", "?")

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level-1 Apply Gate — Phase 16D ({mode_label.upper()} mode){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Timestamp:       {result.get('timestamp', '?')}")
    print(f"  Apply Gate ID:   {result.get('apply_gate_id', '?')}")
    print(f"  Mode:            {mode_label}")
    print(f"  Diagnosis:       {diag_color}{diag}{RESET}")
    print(f"  Severity:        {sev_color}{sev}{RESET}")
    if result.get("operator_action_required"):
        print(f"  Operator action: {RED}REQUIRED{RESET}")

    ag = result.get("apply_gate", {})
    print(f"  Apply ready:     {GREEN if ag.get('apply_ready') else RED}{ag.get('apply_ready', False)}{RESET}")
    print(f"  Apply performed: {GREEN if ag.get('apply_performed') else RESET}{ag.get('apply_performed', False)}{RESET}")
    print(f"  Prior level:     {ag.get('prior_autonomy_level', '?')}")
    print(f"  Resulting level: {ag.get('resulting_autonomy_level', '?')}")
    print(f"  Order enablement: {ag.get('order_enablement_performed', '?')}")
    print()

    # Git
    g = result.get("git", {})
    print(f"  {BOLD}Git / Worktree{RESET}")
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Tag:           {g.get('tag', '?')}")
    wtc = g.get("worktree_clean")
    wtc_str = f"{GREEN}clean{RESET}" if wtc is True else (f"{RED}dirty{RESET}" if wtc is False else "?")
    print(f"    Worktree:      {wtc_str}")
    print()

    # Required tags
    rt = result.get("required_tags", {})
    missing_tags = rt.get("missing", [])
    tag_color = GREEN if len(missing_tags) == 0 else RED
    print(f"  {BOLD}Required Tags{RESET}")
    print(f"    Required:       {rt.get('required_count', 0)}")
    print(f"    Present:        {tag_color}{rt.get('present_count', 0)}{RESET}")
    for tag in missing_tags:
        print(f"      {RED}✗{RESET} {tag}")
    print()

    # Runtime
    rtr = result.get("runtime", {})
    print(f"  {BOLD}Runtime / Bridge{RESET}")
    print(f"    Reachable:      {_bool_str(rtr.get('bridge_reachable'))}")
    print(f"    Connected:      {_bool_str(rtr.get('bridge_connected'))}")
    print(f"    Mode:           {rtr.get('mode', '?')}")
    print(f"    Read-only:      {_bool_str(rtr.get('read_only'))}")
    print(f"    Positions:      {rtr.get('positions_count', '?')}  flat={_bool_str(rtr.get('positions_flat'))}")
    print(f"    Active alerts:  {rtr.get('active_alerts_count', '?')}")
    print()

    # Safety before
    sf = result.get("safety_before", {})
    print(f"  {BOLD}Safety (Before Apply){RESET}")
    print(f"    IBKR_ALLOW_ORDERS:     {sf.get('env_IBKR_ALLOW_ORDERS', '?')}")
    print(f"    rules.enforced:        {sf.get('rules_enforced', '?')}")
    print(f"    system_locked:         {sf.get('system_locked', '?')}")
    print(f"    Autonomy current:      {sf.get('autonomy_level_current', '?')}")
    print()

    # Safety after
    sa = result.get("safety_after", {})
    print(f"  {BOLD}Safety (After Apply){RESET}")
    print(f"    IBKR_ALLOW_ORDERS:     {sa.get('env_IBKR_ALLOW_ORDERS', '?')}")
    print(f"    rules.enforced:        {sa.get('rules_enforced', '?')}")
    print(f"    system_locked:         {sa.get('system_locked', '?')}")
    print(f"    Autonomy current:      {sa.get('autonomy_level_current', '?')}")
    print()

    # Guard state
    gs = result.get("guard_state", {})
    print(f"  {BOLD}Guard State{RESET}")
    print(f"    Daily trade count: {gs.get('daily_trade_count', '?')}")
    print(f"    Trade date:        {gs.get('trade_date', '?')}")
    print(f"    Stale:             {_bool_str(gs.get('trade_date_stale'))}")
    print()

    # Doctor / KPI
    doc = result.get("doctor_summary", {})
    doc_color = GREEN if doc.get("acceptable") else RED
    print(f"  {BOLD}Doctor / KPI{RESET}")
    print(f"    Doctor:     {doc.get('result', '?')}  H1={doc.get('h1_canary_status', '?')}  ok={doc_color}{doc.get('acceptable', False)}{RESET}")
    kpi = result.get("kpi_summary", {})
    kpi_color = GREEN if kpi.get("acceptable_hold") else RED
    print(f"    KPI:        {kpi.get('verdict', '?')}  ok={kpi_color}{kpi.get('acceptable_hold', False)}{RESET}")
    print()

    # Apply prerequisites
    pr = result.get("apply_prerequisites", {})
    print(f"  {BOLD}Apply Prerequisites{RESET}")
    for key, val in pr.items():
        print(f"    {key:<35} {_bool_str(val)}")
    print()

    # Next step
    print(f"  {BOLD}Next Step{RESET}")
    print(f"    {ag.get('next_step', '?')}")
    print()

    # Suggested actions
    sa = result.get("suggested_operator_actions", [])
    if sa:
        print(f"  {BOLD}Suggested Operator Actions{RESET}")
        for a in sa:
            print(f"    {YELLOW}→{RESET} {a}")
        print()

    print(f"  {BOLD}Advisory{RESET}")
    print(f"    {result.get('advisory', '')}")

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"\n  Evidence hash: {eh[:16]}...")

    ep = result.get("export_path") or result.get("_export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_post_promotion_stability_drill(result: dict) -> None:
    """Print Phase 16E stability drill in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16E_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    drill_ok = result.get("diagnosis") == _PHASE16E_DIAGNOSIS["ready"]
    diag_color = GREEN if drill_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else (YELLOW if sev == "HOLD" else RED)

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Post-Promotion Stability Drill (16E){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Drill ID:        {result.get('drill_id', '?')}")
    print(f"  Timestamp:       {result.get('timestamp', '?')}")
    print(f"  Samples:         {result.get('samples_collected', 0)}/{result.get('samples_requested', '?')}")
    print(f"  Interval:        {result.get('interval_seconds', '?')}s")
    print(f"  Diagnosis:       {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:        {sev_color}{sev}{RESET}")
    print()

    ss = result.get("stability_summary", {})
    if ss:
        print(f"  {BOLD}Stability Summary{RESET}")
        for key, val in ss.items():
            color = GREEN if val else RED
            print(f"    {key:<42} {color}{val}{RESET}")
        print()

    bl = result.get("baseline", {})
    if bl:
        print(f"  {BOLD}Baseline (Sample 1){RESET}")
        print(f"    Autonomy:          {bl.get('autonomy_level', '?')}")
        cc = bl.get('clean_cycles')
        cc_display = str(cc) if cc is not None else "null (unknown)"
        print(f"    Clean cycles:      {cc_display}  source={bl.get('clean_cycles_source', '?')}")
        print(f"    Bridge connected:  {_bool_str(bl.get('bridge_connected'))}")
        print(f"    Mode:              {bl.get('mode', '?')}")
        print(f"    Read-only:         {_bool_str(bl.get('read_only'))}")
        print(f"    Positions:         {bl.get('positions_count', '?')}  flat={_bool_str(bl.get('positions_flat'))}")
        print(f"    Alerts:            {bl.get('active_alerts_count', '?')}")
        print(f"    Guard count:       {bl.get('guard_daily_trade_count', '?')}")
        print(f"    Guard date stale:  {_bool_str(bl.get('guard_trade_date_stale'))}")
        print()

    samples = result.get("samples", [])
    if samples:
        print(f"  {BOLD}Samples Detail (first {min(3, len(samples))} of {len(samples)}){RESET}")
        for s in samples[:3]:
            print(f"    Sample {s.get('sample_number', '?')}: "
                  f"bridge={_bool_str(s.get('bridge_connected'))} "
                  f"mode={s.get('mode', '?')} "
                  f"ro={_bool_str(s.get('read_only'))} "
                  f"flat={_bool_str(s.get('positions_flat'))} "
                  f"alerts={s.get('active_alerts_count', '?')} "
                  f"autonomy={s.get('autonomy_level', '?')}")
        print()

    doc = result.get("doctor_summary", {})
    if doc:
        print(f"  {BOLD}Doctor / KPI{RESET}")
        print(f"    Doctor: {doc.get('result', '?')}  ok={_bool_str(doc.get('acceptable', False))}")
        kpi = result.get("kpi_summary", {})
        print(f"    KPI:    {kpi.get('verdict', '?')}  ok={_bool_str(kpi.get('acceptable_hold', False))}")
        print()

    sa = result.get("suggested_operator_actions", [])
    if sa:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in sa:
            print(f"    {YELLOW}→{RESET} {a}")
        print()

    print(f"  {BOLD}Advisory{RESET}")
    print(f"    {result.get('advisory', '')}")

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"\n  Evidence hash: {eh[:16]}...")

    ep = result.get("export_path") or result.get("_export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_evidence_normalization_check(result: dict) -> None:
    """Print Phase 16F evidence normalization check in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16F_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    check_ok = result.get("diagnosis") == _PHASE16F_DIAGNOSIS["ready"]
    diag_color = GREEN if check_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else (YELLOW if sev == "HOLD" else RED)

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Evidence Normalization Check (16F){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Check ID:        {result.get('check_id', '?')}")
    print(f"  Timestamp:       {result.get('timestamp', '?')}")
    print(f"  Diagnosis:       {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:        {sev_color}{sev}{RESET}")
    print()

    auto = result.get("autonomy", {})
    if auto:
        print(f"  {BOLD}Autonomy{RESET}")
        print(f"    Current Level:          {auto.get('current_level', '?')}")
        cc = auto.get('clean_cycles')
        cc_display = str(cc) if cc is not None else "null (unknown)"
        print(f"    Clean Cycles:           {cc_display}")
        print(f"    Source:                 {auto.get('clean_cycles_source', '?')}")
        match_ok = auto.get('clean_cycles_matches_kpi')
        print(f"    Matches KPI:            {GREEN if match_ok else RED}{match_ok}{RESET}")
        print(f"    KPI clean_cycles:       {auto.get('kpi_clean_cycles', '?')}")
        print()

    safety = result.get("safety", {})
    if safety:
        print(f"  {BOLD}Safety{RESET}")
        print(f"    IBKR_ALLOW_ORDERS:      {safety.get('env_IBKR_ALLOW_ORDERS', '?')}")
        print(f"    rules.enforced:         {safety.get('rules_enforced', '?')}")
        print(f"    system_locked:          {_bool_str(safety.get('system_locked'))}")
        print()

    ns = result.get("normalization_summary", {})
    if ns:
        print(f"  {BOLD}Normalization Summary{RESET}")
        for key, val in ns.items():
            color = GREEN if val else RED
            print(f"    {key:<42} {color}{val}{RESET}")
        print()

    runtime = result.get("runtime", {})
    if runtime:
        print(f"  {BOLD}Runtime{RESET}")
        print(f"    Bridge:         connected={_bool_str(runtime.get('bridge_connected'))} mode={runtime.get('mode', '?')}")
        print(f"    Endpoints:      {runtime.get('endpoints_display', '?')}")
        print(f"    Positions:      {runtime.get('positions_count', 0)}  flat={_bool_str(runtime.get('positions_flat'))}")
        print(f"    Alerts:         {runtime.get('active_alerts_count', 0)}")
        print()

    guard = result.get("guard_state", {})
    if guard:
        print(f"  {BOLD}Guard State{RESET}")
        print(f"    Trade count:    {guard.get('daily_trade_count', '?')}")
        print(f"    Trade date:     {guard.get('trade_date', '?')}")
        print(f"    Canonical:      {guard.get('canonical_trade_date', '?')}")
        print(f"    Stale:          {_bool_str(guard.get('trade_date_stale'))}")
        print()

    sa = result.get("suggested_operator_actions", [])
    if sa:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in sa:
            print(f"    {YELLOW}→{RESET} {a}")
        print()

    print(f"  {BOLD}Advisory{RESET}")
    print(f"    {result.get('advisory', '')}")

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"\n  Evidence hash: {eh[:16]}...")

    ep = result.get("export_path") or result.get("_export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_proposal_workflow_drill(result: dict) -> None:
    """Print Phase 16G proposal workflow drill in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16G_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    drill_ok = result.get("diagnosis") == _PHASE16G_DIAGNOSIS["ready"]
    diag_color = GREEN if drill_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else (YELLOW if sev == "HOLD" else RED)

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Proposal-Only Workflow Drill (16G){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Drill ID:        {result.get('drill_id', '?')}")
    print(f"  Timestamp:       {result.get('timestamp', '?')}")
    print(f"  Diagnosis:       {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:        {sev_color}{sev}{RESET}")
    print()

    pw = result.get("proposal_workflow", {})
    if pw:
        print(f"  {BOLD}Proposal Workflow{RESET}")
        print(f"    Proposal-only:          {pw.get('proposal_only')}")
        print(f"    Source:                 {pw.get('proposal_source', '?')}")
        print(f"    Candidates requested:   {pw.get('demo_candidates_requested', 0)}")
        print(f"    Proposals created:      {pw.get('proposals_created', 0)}")
        print(f"    Marked executable:      {RED}{pw.get('proposals_marked_executable')}{RESET}")
        print(f"    Requires Chris review:  {GREEN}{pw.get('proposals_require_chris_review')}{RESET}")
        print(f"    Broker submission:      {RED}{pw.get('broker_submission_performed')}{RESET}")
        print()

    wf = result.get("workflow_summary", {})
    if wf:
        print(f"  {BOLD}Workflow Summary{RESET}")
        for key, val in wf.items():
            color = GREEN if val else RED
            print(f"    {key:<42} {color}{val}{RESET}")
        print()

    pb = result.get("proposal_batch", {})
    if pb:
        print(f"  {BOLD}Proposal Batch{RESET}")
        print(f"    Batch ID:      {pb.get('batch_id', '?')}")
        print(f"    Status:        {pb.get('status', '?')}")
        items = pb.get("items", [])
        print(f"    Items:         {len(items)}")
        for item in items:
            side_color = GREEN if item.get('side') == 'BUY' else RED
            print(f"      {item.get('proposal_id', '?')}: {item.get('symbol', '?')} "
                  f"{side_color}{item.get('side', '?')}{RESET} "
                  f"qty={item.get('quantity', 0)} "
                  f"exec={RED}{item.get('executable')}{RESET}")
        print()

    auto = result.get("autonomy", {})
    if auto:
        print(f"  {BOLD}Autonomy{RESET}")
        print(f"    Level:          {auto.get('current_level', '?')}")
        cc = auto.get('clean_cycles')
        print(f"    Clean cycles:   {cc if cc is not None else 'null'}")
        print(f"    Matches KPI:    {auto.get('clean_cycles_matches_kpi')}")
        print()

    safety = result.get("safety", {})
    if safety:
        print(f"  {BOLD}Safety{RESET}")
        print(f"    ALLOW_ORDERS:   {safety.get('env_IBKR_ALLOW_ORDERS', '?')}")
        print(f"    rules.enforced: {safety.get('rules_enforced', '?')}")
        print(f"    system_locked:  {_bool_str(safety.get('system_locked'))}")
        print()

    runtime = result.get("runtime", {})
    if runtime:
        print(f"  {BOLD}Runtime{RESET}")
        print(f"    Bridge:         connected={_bool_str(runtime.get('bridge_connected'))} mode={runtime.get('mode', '?')}")
        print(f"    Endpoints:      {runtime.get('endpoints_display', '?')}")
        print(f"    Positions:      {runtime.get('positions_count', 0)}  flat={_bool_str(runtime.get('positions_flat'))}")
        print(f"    Alerts:         {runtime.get('active_alerts_count', 0)}")
        print()

    guard = result.get("guard_state", {})
    if guard:
        print(f"  {BOLD}Guard State{RESET}")
        print(f"    Trade count:    {guard.get('daily_trade_count', '?')}")
        print(f"    Trade date:     {guard.get('trade_date', '?')}")
        print(f"    Stale:          {_bool_str(guard.get('trade_date_stale'))}")
        print(f"    Clean:          {_bool_str(guard.get('guard_state_clean'))}")
        print()

    sa = result.get("suggested_operator_actions", [])
    if sa:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in sa:
            print(f"    {YELLOW}→{RESET} {a}")
        print()

    print(f"  {BOLD}Advisory{RESET}")
    print(f"    {result.get('advisory', '')}")

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"\n  Evidence hash: {eh[:16]}...")

    ep = result.get("export_path") or result.get("_export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_human_review_package_drill(result: dict) -> None:
    """Print Phase 16H human review package drill in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16H_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    drill_ok = result.get("diagnosis") == _PHASE16H_DIAGNOSIS["ready"]
    diag_color = GREEN if drill_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else (YELLOW if sev == "HOLD" else RED)

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Human Review Package Drill (16H){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Drill ID:        {result.get('drill_id', '?')}")
    print(f"  Timestamp:       {result.get('timestamp', '?')}")
    print(f"  Diagnosis:       {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:        {sev_color}{sev}{RESET}")
    print()

    rw = result.get("review_workflow", {})
    if rw:
        print(f"  {BOLD}Review Workflow{RESET}")
        print(f"    Review-only:            {rw.get('review_only')}")
        print(f"    Candidates requested:   {rw.get('demo_candidates_requested', 0)}")
        print(f"    Items created:          {rw.get('items_created', 0)}")
        print(f"    Marked executable:      {RED}{rw.get('items_marked_executable')}{RESET}")
        print(f"    Requires Chris review:  {GREEN}{rw.get('all_items_require_chris_review')}{RESET}")
        print(f"    Broker submission:      {RED}{rw.get('broker_submission_performed')}{RESET}")
        print()

    wf = result.get("workflow_summary", {})
    if wf:
        print(f"  {BOLD}Workflow Summary{RESET}")
        for key, val in wf.items():
            color = GREEN if val else RED
            print(f"    {key:<42} {color}{val}{RESET}")
        print()

    rp = result.get("review_package", {})
    if rp:
        print(f"  {BOLD}Review Package{RESET}")
        print(f"    Package ID:    {rp.get('package_id', '?')}")
        print(f"    Status:        {rp.get('status', '?')}")
        items = rp.get("items", [])
        print(f"    Items:         {len(items)}")
        for item in items:
            side_color = GREEN if item.get('side') == 'BUY' else RED
            print(f"      {item.get('review_id', '?')}: {item.get('symbol', '?')} "
                  f"{side_color}{item.get('side', '?')}{RESET} "
                  f"qty={item.get('quantity', 0)} "
                  f"status={item.get('review_status', '?')} "
                  f"exec={RED}{item.get('executable')}{RESET}")
        summary = rp.get("summary", {})
        if summary:
            print(f"    Summary:       total={summary.get('total_items', 0)} "
                  f"exec={summary.get('executable_items', 0)} "
                  f"pending={summary.get('pending_review_items', 0)}")
        print()

    auto = result.get("autonomy", {})
    if auto:
        print(f"  {BOLD}Autonomy{RESET}")
        print(f"    Level:          {auto.get('current_level', '?')}")
        cc = auto.get('clean_cycles')
        print(f"    Clean cycles:   {cc if cc is not None else 'null'}")
        print(f"    Matches KPI:    {auto.get('clean_cycles_matches_kpi')}")
        print()

    safety = result.get("safety", {})
    if safety:
        print(f"  {BOLD}Safety{RESET}")
        print(f"    ALLOW_ORDERS:   {safety.get('env_IBKR_ALLOW_ORDERS', '?')}")
        print(f"    rules.enforced: {safety.get('rules_enforced', '?')}")
        print(f"    system_locked:  {_bool_str(safety.get('system_locked'))}")
        print()

    runtime = result.get("runtime", {})
    if runtime:
        print(f"  {BOLD}Runtime{RESET}")
        print(f"    Bridge:         connected={_bool_str(runtime.get('bridge_connected'))} mode={runtime.get('mode', '?')}")
        print(f"    Endpoints:      {runtime.get('endpoints_display', '?')}")
        print(f"    Positions:      {runtime.get('positions_count', 0)}  flat={_bool_str(runtime.get('positions_flat'))}")
        print(f"    Alerts:         {runtime.get('active_alerts_count', 0)}")
        print()

    guard = result.get("guard_state", {})
    if guard:
        print(f"  {BOLD}Guard State{RESET}")
        print(f"    Trade count:    {guard.get('daily_trade_count', '?')}")
        print(f"    Trade date:     {guard.get('trade_date', '?')}")
        print(f"    Stale:          {_bool_str(guard.get('trade_date_stale'))}")
        print(f"    Clean:          {_bool_str(guard.get('guard_state_clean'))}")
        print()

    sa = result.get("suggested_operator_actions", [])
    if sa:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in sa:
            print(f"    {YELLOW}→{RESET} {a}")
        print()

    print(f"  {BOLD}Advisory{RESET}")
    print(f"    {result.get('advisory', '')}")

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"\n  Evidence hash: {eh[:16]}...")

    ep = result.get("export_path") or result.get("_export_path")
    if ep:
        print(f"  Export: {ep}")
    rp_path = result.get("review_package_path")
    if rp_path:
        print(f"  Review package: {rp_path}")
    print()


def _print_level1_review_decision_drill(result: dict) -> None:
    """Print Phase 16I review decision drill in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16I_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    drill_ok = result.get("diagnosis") == _PHASE16I_DIAGNOSIS["ready"]
    diag_color = GREEN if drill_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else (YELLOW if sev == "HOLD" else RED)

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Review Decision Drill (16I){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\\n")
    print(f"  Drill ID:           {result.get('drill_id', '?')}")
    print(f"  Timestamp:          {result.get('timestamp', '?')}")
    print(f"  Diagnosis:          {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:           {sev_color}{sev}{RESET}")
    print()

    irp = result.get("input_review_package", {})
    if irp:
        print(f"  {BOLD}Input Review Package{RESET}")
        print(f"    Source:           {irp.get('source', '?')}")
        print(f"    Package ID:       {irp.get('package_id', '?')}")
        print(f"    Items count:      {irp.get('items_count', 0)}")
        pph = irp.get("package_hash", "")
        if pph:
            print(f"    Package hash:     {pph[:16]}...")
        print()

    rd = result.get("review_decision", {})
    if rd:
        print(f"  {BOLD}Review Decision{RESET}")
        print(f"    Decision ID:      {rd.get('decision_id', '?')}")
        print(f"    Reviewer:         {rd.get('reviewer', '?')}")
        print(f"    Mode:             {rd.get('decision_mode', '?')}")
        print(f"    Status:           {rd.get('status', '?')}")
        print(f"    Total decisions:  {rd.get('decisions_count', 0)}")
        print(f"    Accepted:         {GREEN}{rd.get('accepted_count', 0)}{RESET}")
        print(f"    Rejected:         {RED}{rd.get('rejected_count', 0)}{RESET}")
        print(f"    Deferred:         {YELLOW}{rd.get('deferred_count', 0)}{RESET}")
        print(f"    Executable:        {RED}{rd.get('executable', '?')}{RESET}")
        print(f"    Accepted exec:     {RED}{rd.get('accepted_items_executable', '?')}{RESET}")
        print()

        decisions = rd.get("decision_items", [])
        if decisions:
            print(f"  {BOLD}Decision Details{RESET}")
            for d in decisions:
                d_verdict = d.get("decision", "?")
                v_color = GREEN if d_verdict == "accept" else (RED if d_verdict == "reject" else YELLOW)
                print(f"    {d.get('proposal_id', '?')}: {d.get('symbol', '?')} "
                      f"{v_color}{d_verdict.upper()}{RESET} "
                      f"qty={d.get('quantity', 0)} exec={RED}{d.get('executable')}{RESET}")
            print()

    rw = result.get("review_workflow", {})
    if rw:
        print(f"  {BOLD}Review Workflow{RESET}")
        print(f"    Decision-only:         {rw.get('decision_only')}")
        print(f"    Items examined:        {rw.get('items_examined', 0)}")
        print(f"    Decisions applied:     {rw.get('decisions_applied', 0)}")
        print(f"    Accepted exec:         {RED}{rw.get('accepted_items_executable')}{RESET}")
        print(f"    Broker submission:     {RED}{rw.get('broker_submission_performed')}{RESET}")
        print()

    ws = result.get("workflow_summary", {})
    if ws:
        print(f"  {BOLD}Workflow Summary{RESET}")
        for key, val in ws.items():
            color = GREEN if val else RED
            print(f"    {key:<42} {color}{val}{RESET}")
        print()

    auto = result.get("autonomy", {})
    if auto:
        print(f"  {BOLD}Autonomy{RESET}")
        print(f"    Level:          {auto.get('current_level', '?')}")
        cc = auto.get('clean_cycles')
        print(f"    Clean cycles:   {cc if cc is not None else 'null'}")
        print(f"    Matches KPI:    {auto.get('clean_cycles_matches_kpi')}")
        print()

    safety = result.get("safety", {})
    if safety:
        print(f"  {BOLD}Safety{RESET}")
        print(f"    ALLOW_ORDERS:   {safety.get('env_IBKR_ALLOW_ORDERS', '?')}")
        print(f"    rules.enforced: {safety.get('rules_enforced', '?')}")
        print(f"    system_locked:  {_bool_str(safety.get('system_locked'))}")
        print()

    runtime = result.get("runtime", {})
    if runtime:
        print(f"  {BOLD}Runtime{RESET}")
        print(f"    Bridge:         connected={_bool_str(runtime.get('bridge_connected'))} mode={runtime.get('mode', '?')}")
        print(f"    Endpoints:      {runtime.get('endpoints_display', '?')}")
        print(f"    Positions:      {runtime.get('positions_count', 0)}  flat={_bool_str(runtime.get('positions_flat'))}")
        print(f"    Alerts:         {runtime.get('active_alerts_count', 0)}")
        print()

    guard = result.get("guard_state", {})
    if guard:
        print(f"  {BOLD}Guard State{RESET}")
        print(f"    Trade count:    {guard.get('daily_trade_count', '?')}")
        print(f"    Trade date:     {guard.get('trade_date', '?')}")
        print(f"    Stale:          {_bool_str(guard.get('trade_date_stale'))}")
        print(f"    Clean:          {_bool_str(guard.get('guard_state_clean'))}")
        print()

    sa = result.get("suggested_operator_actions", [])
    if sa:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in sa:
            print(f"    {YELLOW}→{RESET} {a}")
        print()

    print(f"  {BOLD}Advisory{RESET}")
    print(f"    {result.get('advisory', '')}")

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"\n  Evidence hash: {eh[:16]}...")

    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    da = result.get("decision_artifact_path")
    if da:
        print(f"  Decision artifact: {da}")
    dah = result.get("decision_artifact_hash", "")
    if dah:
        print(f"  Decision artifact hash: {dah[:16]}...")
    print()


def _print_level1_order_plan_draft_drill(result: dict) -> None:
    """Print Phase 16J order-plan draft drill in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16J_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    drill_ok = result.get("diagnosis") == _PHASE16J_DIAGNOSIS["ready"]
    diag_color = GREEN if drill_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else (YELLOW if sev == "HOLD" else RED)

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Order-Plan Draft Drill (16J){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\\n")
    print(f"  Drill ID:              {result.get('drill_id', '?')}")
    print(f"  Timestamp:             {result.get('timestamp', '?')}")
    print(f"  Diagnosis:             {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:              {sev_color}{sev}{RESET}")
    print()

    ida = result.get("input_decision_artifact", {})
    if ida:
        print(f"  {BOLD}Input Decision Artifact{RESET}")
        print(f"    Source:              {ida.get('source', '?')}")
        print(f"    Decision ID:         {ida.get('decision_id', '?')}")
        print(f"    Status:              {ida.get('status', '?')}")
        print(f"    Decisions count:     {ida.get('decisions_count', 0)}")
        print(f"    Accepted:            {GREEN}{ida.get('accepted_count', 0)}{RESET}")
        print(f"    Rejected:            {RED}{ida.get('rejected_count', 0)}{RESET}")
        print(f"    Deferred:            {YELLOW}{ida.get('deferred_count', 0)}{RESET}")
        ah = ida.get("artifact_hash", "")
        if ah:
            print(f"    Artifact hash:       {ah[:16]}...")
        print()

    opd = result.get("order_plan_draft", {})
    if opd:
        print(f"  {BOLD}Order-Plan Draft{RESET}")
        print(f"    Plan ID:             {opd.get('plan_id', '?')}")
        print(f"    Status:              {opd.get('status', '?')}")
        print(f"    Executable:           {RED}{opd.get('executable', '?')}{RESET}")
        print(f"    Broker order:         {RED}{opd.get('broker_order_created', '?')}{RESET}")
        print(f"    Preflight:            {RED}{opd.get('preflight_performed', '?')}{RESET}")
        print(f"    Approve:              {RED}{opd.get('approval_performed', '?')}{RESET}")
        print(f"    Submit:               {RED}{opd.get('submit_performed', '?')}{RESET}")
        print(f"    Draft items:          {opd.get('draft_items_count', 0)}")
        print(f"    Rejected skipped:    {RED}{opd.get('skipped_rejected_count', 0)}{RESET}")
        print(f"    Deferred skipped:    {YELLOW}{opd.get('skipped_deferred_count', 0)}{RESET}")
        print()

        di = opd.get("draft_items", [])
        if di:
            print(f"  {BOLD}Draft Items{RESET}")
            for d in di:
                print(f"    {d.get('plan_item_id', '?')}: {d.get('symbol', '?')} "
                      f"{GREEN}{d.get('side', '?')}{RESET} "
                      f"qty={d.get('quantity', 0)} exec={RED}{d.get('executable')}{RESET}")
            print()

        si = opd.get("skipped_items", [])
        if si:
            print(f"  {BOLD}Skipped Items{RESET}")
            for s in si:
                print(f"    {s.get('source_proposal_id', '?')}: {RED}{s.get('decision', '?').upper()}{RESET} "
                      f"— {s.get('skip_reason', '')}")
            print()

    ws = result.get("workflow_summary", {})
    if ws:
        print(f"  {BOLD}Workflow Summary{RESET}")
        for key, val in ws.items():
            color = GREEN if val else RED
            print(f"    {key:<46} {color}{val}{RESET}")
        print()

    auto = result.get("autonomy", {})
    if auto:
        print(f"  {BOLD}Autonomy{RESET}")
        print(f"    Level:          {auto.get('current_level', '?')}")
        cc = auto.get('clean_cycles')
        print(f"    Clean cycles:   {cc if cc is not None else 'null'}")
        print()

    safety = result.get("safety", {})
    if safety:
        print(f"  {BOLD}Safety{RESET}")
        print(f"    ALLOW_ORDERS:   {safety.get('env_IBKR_ALLOW_ORDERS', '?')}")
        print(f"    rules.enforced: {safety.get('rules_enforced', '?')}")
        print(f"    system_locked:  {_bool_str(safety.get('system_locked'))}")
        print()

    runtime = result.get("runtime", {})
    if runtime:
        print(f"  {BOLD}Runtime{RESET}")
        print(f"    Bridge:         connected={_bool_str(runtime.get('bridge_connected'))} mode={runtime.get('mode', '?')}")
        print(f"    Positions:      {runtime.get('positions_count', 0)}  flat={_bool_str(runtime.get('positions_flat'))}")
        print(f"    Alerts:         {runtime.get('active_alerts_count', 0)}")
        print()

    guard = result.get("guard_state", {})
    if guard:
        print(f"  {BOLD}Guard State{RESET}")
        print(f"    Trade count:    {guard.get('daily_trade_count', '?')}")
        print(f"    Trade date:     {guard.get('trade_date', '?')}")
        print(f"    Stale:          {_bool_str(guard.get('trade_date_stale'))}")
        print(f"    Clean:          {_bool_str(guard.get('guard_state_clean'))}")
        print()

    sa = result.get("suggested_operator_actions", [])
    if sa:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in sa:
            print(f"    {YELLOW}→{RESET} {a}")
        print()

    print(f"  {BOLD}Advisory{RESET}")
    print(f"    {result.get('advisory', '')}")

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"\n  Evidence hash: {eh[:16]}...")

    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    pa = result.get("plan_artifact_path")
    if pa:
        print(f"  Plan artifact: {pa}")
    pah = result.get("plan_artifact_hash", "")
    if pah:
        print(f"  Plan artifact hash: {pah[:16]}...")
    print()


def _print_level1_preflight_simulation_dossier(result: dict) -> None:
    """Print Phase 16K preflight simulation dossier in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16K_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    drill_ok = result.get("diagnosis") in (_PHASE16K_DIAGNOSIS["ready"], _PHASE16K_DIAGNOSIS["no_draft_items_to_simulate"])
    diag_color = GREEN if drill_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else (YELLOW if sev == "HOLD" else RED)

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Preflight Simulation Dossier (16K){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Dossier ID:            {result.get('dossier_id', '?')}")
    print(f"  Timestamp:             {result.get('timestamp', '?')}")
    print(f"  Diagnosis:             {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:              {sev_color}{sev}{RESET}")
    print()

    iop = result.get("input_order_plan", {})
    if iop:
        print(f"  {BOLD}Input Order-Plan{RESET}")
        print(f"    Source:              {iop.get('source', '?')}")
        print(f"    Plan ID:             {iop.get('plan_id', '?')}")
        print(f"    Status:              {iop.get('status', '?')}")
        print(f"    Draft-only:           {_bool_str(iop.get('draft_only'))}")
        print(f"    Draft items count:   {iop.get('draft_items_count', 0)}")
        ah = iop.get("artifact_hash", "")
        if ah:
            print(f"    Artifact hash:       {ah[:16]}...")
        print()

    ps = result.get("preflight_simulation", {})
    if ps:
        print(f"  {BOLD}Preflight Simulation{RESET}")
        print(f"    Simulation ID:       {ps.get('simulation_id', '?')}")
        print(f"    Status:              {ps.get('status', '?')}")
        print(f"    Source:              {ps.get('simulation_source', '?')}")
        print(f"    Simulated only:       {GREEN}{ps.get('simulated_preflight_only')}{RESET}")
        print(f"    Real preflight:       {RED}{ps.get('real_preflight_performed')}{RESET}")
        print(f"    Endpoint called:      {RED}{ps.get('preflight_endpoint_called')}{RESET}")
        print(f"    Broker validation:    {RED}{ps.get('broker_validation_performed')}{RESET}")
        print(f"    Simulated items:     {ps.get('simulated_items_count', 0)}")
        print()

        si = ps.get("simulated_items", [])
        if si:
            print(f"  {BOLD}Simulated Items{RESET}")
            for s in si:
                print(f"    {s.get('simulation_item_id', '?')}: {s.get('symbol', '?')} "
                      f"{GREEN}{s.get('side', '?')}{RESET} "
                      f"qty={s.get('quantity', 0)}")
                print(f"      sim-only={GREEN}{s.get('simulated_preflight_only')}{RESET} "
                      f"real-pf={RED}{s.get('real_preflight_performed')}{RESET} "
                      f"margin={s.get('simulated_margin_check', '?')}")
            print()

    ws = result.get("workflow_summary", {})
    if ws:
        print(f"  {BOLD}Workflow Summary{RESET}")
        for key, val in ws.items():
            color = GREEN if val else RED
            print(f"    {key:<46} {color}{val}{RESET}")
        print()

    auto = result.get("autonomy", {})
    if auto:
        print(f"  {BOLD}Autonomy{RESET}")
        print(f"    Level:          {auto.get('current_level', '?')}")
        cc = auto.get('clean_cycles')
        print(f"    Clean cycles:   {cc if cc is not None else 'null'}")
        print()

    safety = result.get("safety", {})
    if safety:
        print(f"  {BOLD}Safety{RESET}")
        print(f"    ALLOW_ORDERS:   {safety.get('env_IBKR_ALLOW_ORDERS', '?')}")
        print(f"    rules.enforced: {safety.get('rules_enforced', '?')}")
        print(f"    system_locked:  {_bool_str(safety.get('system_locked'))}")
        print()

    guard = result.get("guard_state", {})
    if guard:
        print(f"  {BOLD}Guard State{RESET}")
        print(f"    Trade count:    {guard.get('daily_trade_count', '?')}")
        print(f"    Trade date:     {guard.get('trade_date', '?')}")
        print(f"    Clean:          {_bool_str(guard.get('guard_state_clean'))}")
        print()

    sa = result.get("suggested_operator_actions", [])
    if sa:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in sa:
            print(f"    {YELLOW}→{RESET} {a}")
        print()

    print(f"  {BOLD}Advisory{RESET}")
    print(f"    {result.get('advisory', '')}")

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"\n  Evidence hash: {eh[:16]}...")

    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    da = result.get("dossier_artifact_path")
    if da:
        print(f"  Dossier artifact: {da}")
    dah = result.get("dossier_artifact_hash", "")
    if dah:
        print(f"  Dossier artifact hash: {dah[:16]}...")
    print()


def _print_level1_human_approval_packet_drill(result: dict) -> None:
    """Print Phase 16L human approval packet drill in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16L_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    drill_ok = result.get("diagnosis") in (_PHASE16L_DIAGNOSIS["ready"], _PHASE16L_DIAGNOSIS["no_items_to_approve"])
    diag_color = GREEN if drill_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else (YELLOW if sev == "HOLD" else RED)

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Human Approval Packet Drill (16L){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Packet ID:             {result.get('packet_id', '?')}")
    print(f"  Timestamp:             {result.get('timestamp', '?')}")
    print(f"  Diagnosis:             {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:              {sev_color}{sev}{RESET}")
    print()

    ipd = result.get("input_preflight_dossier", {})
    if ipd:
        print(f"  {BOLD}Input Preflight Dossier{RESET}")
        print(f"    Source:              {ipd.get('source', '?')}")
        print(f"    Dossier ID:          {ipd.get('dossier_id', '?')}")
        print(f"    Status:              {ipd.get('status', '?')}")
        print(f"    Sim-only:             {_bool_str(ipd.get('simulation_only'))}")
        print(f"    Real preflight:       {RED}{ipd.get('real_preflight_performed')}{RESET}")
        print(f"    Items count:         {ipd.get('simulated_items_count', 0)}")
        ah = ipd.get("artifact_hash", "")
        if ah:
            print(f"    Artifact hash:       {ah[:16]}...")
        print()

    hap = result.get("human_approval_packet", {})
    if hap:
        print(f"  {BOLD}Human Approval Packet{RESET}")
        print(f"    Packet ID:           {hap.get('packet_id', '?')}")
        print(f"    Status:              {hap.get('status', '?')}")
        print(f"    Reviewer:            {hap.get('reviewer', '?')}")
        print(f"    Human packet only:    {GREEN}{hap.get('human_packet_only')}{RESET}")
        print(f"    Broker approval:      {RED}{hap.get('broker_approval_performed')}{RESET}")
        print(f"    H1 token used:        {RED}{hap.get('h1_token_used')}{RESET}")
        print(f"    Endpoint called:      {RED}{hap.get('approval_endpoint_called')}{RESET}")
        print(f"    Sig required:        {hap.get('requires_chris_signature')}")
        print(f"    Packet items:        {hap.get('packet_items_count', 0)}")
        print(f"    Blocked:              {hap.get('blocked_items_count', 0)}")
        print()

        pi = hap.get("packet_items", [])
        if pi:
            print(f"  {BOLD}Packet Items (pending Chris review){RESET}")
            for p in pi:
                print(f"    {p.get('packet_item_id', '?')}: {p.get('symbol', '?')} "
                      f"{GREEN}{p.get('side', '?')}{RESET} "
                      f"qty={p.get('quantity', 0)}")
                print(f"      packet-only={GREEN}{p.get('human_packet_only')}{RESET}")
            print()

    ws = result.get("workflow_summary", {})
    if ws:
        print(f"  {BOLD}Workflow Summary{RESET}")
        for key, val in ws.items():
            color = GREEN if val else RED
            print(f"    {key:<46} {color}{val}{RESET}")
        print()

    auto = result.get("autonomy", {})
    if auto:
        print(f"  {BOLD}Autonomy{RESET}")
        print(f"    Level:          {auto.get('current_level', '?')}")
        cc = auto.get('clean_cycles')
        print(f"    Clean cycles:   {cc if cc is not None else 'null'}")
        print()

    safety = result.get("safety", {})
    if safety:
        print(f"  {BOLD}Safety{RESET}")
        print(f"    ALLOW_ORDERS:   {safety.get('env_IBKR_ALLOW_ORDERS', '?')}")
        print(f"    rules.enforced: {safety.get('rules_enforced', '?')}")
        print(f"    system_locked:  {_bool_str(safety.get('system_locked'))}")
        print()

    guard = result.get("guard_state", {})
    if guard:
        print(f"  {BOLD}Guard State{RESET}")
        print(f"    Trade count:    {guard.get('daily_trade_count', '?')}")
        print(f"    Trade date:     {guard.get('trade_date', '?')}")
        print(f"    Clean:          {_bool_str(guard.get('guard_state_clean'))}")
        print()

    sa = result.get("suggested_operator_actions", [])
    if sa:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in sa:
            print(f"    {YELLOW}→{RESET} {a}")
        print()

    print(f"  {BOLD}Advisory{RESET}")
    print(f"    {result.get('advisory', '')}")

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"\n  Evidence hash: {eh[:16]}...")

    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    pp = result.get("packet_artifact_path")
    if pp:
        print(f"  Packet artifact: {pp}")
    ph = result.get("packet_artifact_hash", "")
    if ph:
        print(f"  Packet artifact hash: {ph[:16]}...")
    print()


def _print_level1_execution_readiness_packet_drill(result: dict) -> None:
    """Print Phase 16M execution-readiness packet drill in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16M_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    drill_ok = result.get("diagnosis") in (_PHASE16M_DIAGNOSIS["ready"], _PHASE16M_DIAGNOSIS["no_items_to_assess"])
    diag_color = GREEN if drill_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else (YELLOW if sev == "HOLD" else RED)

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Execution-Readiness Packet Drill (16M){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Packet ID:             {result.get('packet_id', '?')}")
    print(f"  Timestamp:             {result.get('timestamp', '?')}")
    print(f"  Diagnosis:             {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:              {sev_color}{sev}{RESET}")
    print()

    iap = result.get("input_approval_packet", {})
    if iap:
        print(f"  {BOLD}Input Approval Packet{RESET}")
        print(f"    Source:              {iap.get('source', '?')}")
        print(f"    Approval Packet ID:  {iap.get('approval_packet_id', '?')}")
        print(f"    Status:              {iap.get('status', '?')}")
        print(f"    Human packet only:    {_bool_str(iap.get('human_packet_only'))}")
        print(f"    Broker approval:      {RED}{iap.get('broker_approval_performed')}{RESET}")
        print(f"    Endpoint called:      {RED}{iap.get('approval_endpoint_called')}{RESET}")
        print(f"    Items count:         {iap.get('packet_items_count', 0)}")
        ah = iap.get("artifact_hash", "")
        if ah:
            print(f"    Artifact hash:       {ah[:16]}...")
        print()

    er = result.get("execution_readiness_packet", {})
    if er:
        print(f"  {BOLD}Execution Readiness Packet{RESET}")
        print(f"    Packet ID:           {er.get('packet_id', '?')}")
        print(f"    Status:              {er.get('status', '?')}")
        print(f"    Reviewer:            {er.get('reviewer', '?')}")
        print(f"    Readiness only:       {GREEN}{er.get('readiness_packet_only')}{RESET}")
        print(f"    Exec authorized:      {RED}{er.get('execution_authorized_now')}{RESET}")
        print(f"    Order enable req:    {er.get('order_enablement_required')}")
        print(f"    Preflight performed:  {RED}{er.get('preflight_performed')}{RESET}")
        print(f"    Approval performed:   {RED}{er.get('approval_performed')}{RESET}")
        print(f"    Submit performed:     {RED}{er.get('submit_performed')}{RESET}")
        print(f"    H1 token used:        {RED}{er.get('h1_token_used')}{RESET}")
        print(f"    Order window opened: {er.get('order_window_opened')}")
        print(f"    Broker order created:{er.get('broker_order_created')}")
        print(f"    Readiness items:     {er.get('readiness_items_count', 0)}")
        print()

        rc = er.get("readiness_checklist", {})
        if rc:
            print(f"  {BOLD}Readiness Checklist{RESET}")
            for key, val in rc.items():
                color = GREEN if val else RED
                print(f"    {key:<56} {color}{val}{RESET}")
            print()

        ri = er.get("readiness_items", [])
        if ri:
            print(f"  {BOLD}Readiness Items (execution NOT authorized){RESET}")
            for r in ri:
                print(f"    {r.get('readiness_item_id', '?')}: {r.get('symbol', '?')} "
                      f"{GREEN}{r.get('side', '?')}{RESET} "
                      f"qty={r.get('quantity', 0)}")
                print(f"      readiness-only={GREEN}{r.get('readiness_packet_only')}{RESET}  "
                      f"exec-authorized={RED}{r.get('execution_authorized_now')}{RESET}")
            print()

    ws = result.get("workflow_summary", {})
    if ws:
        print(f"  {BOLD}Workflow Summary{RESET}")
        for key, val in ws.items():
            color = GREEN if val else RED
            print(f"    {key:<46} {color}{val}{RESET}")
        print()

    auto = result.get("autonomy", {})
    if auto:
        print(f"  {BOLD}Autonomy{RESET}")
        print(f"    Level:          {auto.get('current_level', '?')}")
        cc = auto.get('clean_cycles')
        print(f"    Clean cycles:   {cc if cc is not None else 'null'}")
        print()

    safety = result.get("safety", {})
    if safety:
        print(f"  {BOLD}Safety{RESET}")
        print(f"    ALLOW_ORDERS:   {safety.get('env_IBKR_ALLOW_ORDERS', '?')}")
        print(f"    rules.enforced: {safety.get('rules_enforced', '?')}")
        print(f"    system_locked:  {_bool_str(safety.get('system_locked'))}")
        print()

    guard = result.get("guard_state", {})
    if guard:
        print(f"  {BOLD}Guard State{RESET}")
        print(f"    Trade count:    {guard.get('daily_trade_count', '?')}")
        print(f"    Trade date:     {guard.get('trade_date', '?')}")
        print(f"    Clean:          {_bool_str(guard.get('guard_state_clean'))}")
        print()

    sa = result.get("suggested_operator_actions", [])
    if sa:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in sa:
            print(f"    {YELLOW}→{RESET} {a}")
        print()

    print(f"  {BOLD}Advisory{RESET}")
    print(f"    {result.get('advisory', '')}")

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"\n  Evidence hash: {eh[:16]}...")

    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    rp = result.get("readiness_artifact_path")
    if rp:
        print(f"  Readiness artifact: {rp}")
    rh = result.get("readiness_artifact_hash", "")
    if rh:
        print(f"  Readiness artifact hash: {rh[:16]}...")
    print()


def _print_level1_readiness_chain_integrity_checkpoint(result: dict) -> None:
    """Print Phase 16N chain integrity checkpoint in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16N_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    drill_ok = result.get("diagnosis") == _PHASE16N_DIAGNOSIS["ready"]
    diag_color = GREEN if drill_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else (YELLOW if sev == "HOLD" else RED)

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Readiness-Chain Integrity Checkpoint (16N){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:         {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:             {result.get('timestamp', '?')}")
    print(f"  Diagnosis:             {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:              {sev_color}{sev}{RESET}")
    print()

    ci = result.get("chain_integrity", {})
    if ci:
        print(f"  {BOLD}Chain Integrity (16G → 16M){RESET}")
        print(f"    Chain source:        {ci.get('chain_source', '?')}")
        print(f"    Stages expected:     {ci.get('stages_expected_count', 0)}")
        print(f"    Stages verified:     {GREEN}{ci.get('stages_verified_count', 0)}{RESET}")
        print(f"    Stages missing:      {ci.get('stages_missing', [])}")
        print(f"    Chain complete:      {_bool_str(ci.get('chain_complete'))}")
        print(f"    Chain order valid:   {_bool_str(ci.get('chain_order_valid'))}")
        print(f"    All non-executable:  {_bool_str(ci.get('all_stages_non_executable'))}")
        print(f"    All advisory-only:   {_bool_str(ci.get('all_stages_advisory_or_readiness_only'))}")
        print(f"    Broker activity:     {RED if ci.get('any_broker_activity_detected') else GREEN}{ci.get('any_broker_activity_detected')}{RESET}")
        print(f"    Chain intact:        {GREEN if ci.get('chain_intact') else RED}{_bool_str(ci.get('chain_intact'))}{RESET}")
        ver = ci.get("verdict", "?")
        v_color = GREEN if ver == "CHAIN_INTACT" else RED
        print(f"    Verdict:             {v_color}{ver}{RESET}")
        print()

        stages = ci.get("stages", [])
        if stages:
            print(f"  {BOLD}Pipeline Stages{RESET}")
            for s in stages:
                st = s.get("status", "?")
                st_color = GREEN if st == "verified_non_executable" else RED
                print(f"    {s.get('stage', '?'):<35} {st_color}{st}{RESET}")
                print(f"      artifact={s.get('artifact_type', '?')}  "
                      f"non_exec={_bool_str(s.get('non_executable'))}  "
                      f"advisory={_bool_str(s.get('advisory_or_readiness_only'))}  "
                      f"broker_mut={_bool_str(s.get('broker_mutation'))}")
                print(f"      order_win={_bool_str(s.get('order_window_opened'))}  "
                      f"h1={_bool_str(s.get('h1_token_used'))}  "
                      f"order_ep={_bool_str(s.get('no_order_endpoint_called'))}  "
                      f"exec={_bool_str(s.get('executable'))}")
                print(f"      exec_auth_now={_bool_str(s.get('execution_authorized_now'))}  "
                      f"trade_win_helper={_bool_str(s.get('trade_window_helper_called'))}  "
                      f"broker_mut={_bool_str(s.get('broker_mutation'))}")
            print()

    # Readiness chain checkpoint section
    rcc = result.get("readiness_chain_checkpoint", {})
    if rcc:
        print(f"  {BOLD}Readiness Chain Checkpoint{RESET}")
        print(f"    Status:                       {rcc.get('status', '?')}")
        print(f"    Executable:                   {_bool_str(rcc.get('executable'))}")
        print(f"    Execution authorized now:     {_bool_str(rcc.get('execution_authorized_now'))}")
        print(f"    Order enablement required:    {_bool_str(rcc.get('order_enablement_required'))}")
        print(f"    Future order window:          {_bool_str(rcc.get('future_order_window_required'))}")
        print(f"    Future H1 required:           {_bool_str(rcc.get('future_h1_required'))}")
        print(f"    Future path:                  {rcc.get('future_required_path', '?')}")
        ch = rcc.get('checkpoint_hash', '')
        if ch:
            print(f"    Checkpoint hash:              {ch[:16]}...")
        print()

    # Integrity checklist
    cl = result.get("integrity_checklist", [])
    if cl:
        print(f"  {BOLD}Integrity Checklist{RESET}")
        pc = sum(1 for c in cl if c.get("status") == "PASS")
        fc = sum(1 for c in cl if c.get("status") == "FAIL")
        sc = sum(1 for c in cl if c.get("status") == "SKIP")
        print(f"    Pass: {pc}  Fail: {fc}  Skip: {sc}  Total: {len(cl)}")
        for c in cl:
            cs = c.get("status", "?")
            c_color = GREEN if cs == "PASS" else (RED if cs == "FAIL" else YELLOW)
            print(f"    {c_color}{cs:<6}{RESET} {c.get('check', '?')}")
        print()

    # Workflow summary
    wf = result.get("workflow_summary", {})
    if wf:
        print(f"  {BOLD}Workflow Summary{RESET}")
        print(f"    Chain integrity ready:      {_bool_str(wf.get('readiness_chain_integrity_ready'))}")
        print(f"    Checkpoint created:         {_bool_str(wf.get('readiness_chain_checkpoint_created'))}")
        print(f"    Full chain verified:        {_bool_str(wf.get('full_chain_verified'))}")
        print(f"    Exec authorized now false:  {_bool_str(wf.get('execution_authorized_now_false'))}")
        print(f"    Checklist complete:         {_bool_str(wf.get('checklist_complete'))}")
        print()

    # Top-level chain booleans
    print(f"  {BOLD}Top-Level Chain Assertions{RESET}")
    print(f"    no_stage_authorizes_execution:    {_bool_str(result.get('no_stage_authorizes_execution'))}")
    print(f"    no_stage_calls_order_path:        {_bool_str(result.get('no_stage_calls_order_path'))}")
    print(f"    no_stage_uses_h1:                 {_bool_str(result.get('no_stage_uses_h1'))}")
    print(f"    no_stage_opens_order_window:      {_bool_str(result.get('no_stage_opens_order_window'))}")
    print(f"    no_stage_creates_broker_order:    {_bool_str(result.get('no_stage_creates_broker_order'))}")
    print(f"    no_stage_mutates_broker:          {_bool_str(result.get('no_stage_mutates_broker'))}")
    print(f"    no_stage_calls_trade_window_helper: {_bool_str(result.get('no_stage_calls_trade_window_helper'))}")
    print(f"    final_stage_readiness_only:       {_bool_str(result.get('final_stage_readiness_only'))}")
    print()

    auto = result.get("autonomy", {})
    if auto:
        print(f"  {BOLD}Autonomy{RESET}")
        print(f"    Level:          {auto.get('current_level', '?')}")
        cc = auto.get('clean_cycles')
        print(f"    Clean cycles:   {cc if cc is not None else 'null'}")
        print()

    guard = result.get("guard_state", {})
    if guard:
        print(f"  {BOLD}Guard State{RESET}")
        print(f"    Trade count:    {guard.get('daily_trade_count', '?')}")
        print(f"    Trade date:     {guard.get('trade_date', '?')}")
        print(f"    Clean:          {_bool_str(guard.get('guard_state_clean'))}")
        print()

    sa = result.get("suggested_operator_actions", [])
    if sa:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in sa:
            print(f"    {YELLOW}→{RESET} {a}")
        print()

    print(f"  {BOLD}Advisory{RESET}")
    print(f"    {result.get('advisory', '')}")

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"\n  Evidence hash: {eh[:16]}...")

    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_order_window_canary_negative_control_drill(result: dict) -> None:
    """Print Phase 16P order-window canary drill in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16P_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    drill_ok = result.get("diagnosis") == _PHASE16P_DIAGNOSIS["ready"]
    diag_color = GREEN if drill_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Order-Window Canary Negative-Control Drill (16P){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Drill ID:              {result.get('drill_id', '?')}")
    print(f"  Timestamp:             {result.get('timestamp', '?')}")
    print(f"  Diagnosis:             {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:              {sev_color}{sev}{RESET}")
    print(f"  Window closed:         {GREEN if result.get('order_window_closed_as_expected') else RED}{_bool_str(result.get('order_window_closed_as_expected'))}{RESET}")
    print()

    # Order window canary
    owc = result.get("order_window_canary", {})
    if owc:
        print(f"  {BOLD}Order Window Canary{RESET}")
        print(f"    Status:                     {GREEN if owc.get('status') == 'closed_as_expected' else RED}{owc.get('status', '?')}{RESET}")
        print(f"    Canary type:                {owc.get('canary_type', '?')}")
        print(f"    Negative-control only:      {_bool_str(owc.get('negative_control_only'))}")
        print(f"    Order window open:          {_bool_str(owc.get('order_window_open'))}")
        print(f"    Opened by drill:            {_bool_str(owc.get('order_window_opened_by_drill'))}")
        print(f"    H1 token read:              {_bool_str(owc.get('h1_token_read'))}")
        print(f"    H1 token used:              {_bool_str(owc.get('h1_token_used'))}")
        print(f"    Trade-window helper called: {_bool_str(owc.get('trade_window_helper_called'))}")
        print(f"    Canary block reason:        {owc.get('canary_block_reason', '?')}")
        print(f"    Canaries: {owc.get('canaries_blocked_count', 0)} blocked / {owc.get('canaries_count', 0)} total")
        print(f"    Future path:                {owc.get('future_required_path', '?')}")
        print()

    # H1 boundary probe
    h1bp = result.get("h1_boundary_probe", {})
    if h1bp:
        print(f"  {BOLD}H1 Boundary Probe{RESET}")
        print(f"    Probe only:                 {_bool_str(h1bp.get('probe_only'))}")
        print(f"    Raw token read:             {_bool_str(h1bp.get('raw_token_read'))}")
        print(f"    H1 header sent:             {_bool_str(h1bp.get('h1_header_sent'))}")
        print(f"    Manual canary required:     {_bool_str(h1bp.get('manual_canary_required'))}")
        print()

    # Order window matrix
    owm = result.get("order_window_matrix", {})
    if owm:
        print(f"  {BOLD}Order Window Matrix{RESET}")
        print(f"    Level1 exec allowed:        {_bool_str(owm.get('level1_execution_allowed'))}")
        print(f"    Order window open:          {_bool_str(owm.get('order_window_open'))}")
        print(f"    Orders enabled:             {_bool_str(owm.get('orders_enabled'))}")
        print(f"    System locked:              {_bool_str(owm.get('system_locked'))}")
        print(f"    H1 available:               {_bool_str(owm.get('h1_available_to_drill'))}")
        print()

    # Canary intents
    canaries = result.get("canary_intents", [])
    if canaries:
        print(f"  {BOLD}Canary Intents (all locally blocked){RESET}")
        for c in canaries:
            print(f"    {c.get('canary_id', '?')}")
            print(f"      type={c.get('canary_type', '?')}  "
                  f"{c.get('side', c.get('action', '?'))} {c.get('quantity', '?')}x "
                  f"{c.get('symbol', '?')} ({c.get('order_type', '?')})")
            print(f"      simulated_only={_bool_str(c.get('simulated_canary_only'))}  "
                  f"blocked={_bool_str(c.get('blocked'))}  "
                  f"requires_h1={_bool_str(c.get('requires_h1'))}  "
                  f"requires_ow={_bool_str(c.get('requires_order_window'))}")
            reasons = c.get("blocking_reasons", [])
            if reasons:
                print(f"      Reasons ({len(reasons)}): {', '.join(reasons[:3])}")
        print()

    # Canary negative controls
    cnc = result.get("canary_negative_controls", {})
    if cnc:
        print(f"  {BOLD}Canary Negative Controls{RESET}")
        print(f"    Controls: {cnc.get('controls_passed_count', 0)}P / "
              f"{cnc.get('controls_failed_count', 0)}F / {cnc.get('controls_count', 0)}T")
        print()

    # Order-window checklist
    ncl = result.get("order_window_checklist", [])
    if ncl:
        print(f"  {BOLD}Order-Window Checklist{RESET}")
        pc = sum(1 for c in ncl if c.get("status") == "PASS")
        fc = sum(1 for c in ncl if c.get("status") == "FAIL")
        sc = sum(1 for c in ncl if c.get("status") == "SKIP")
        print(f"    Pass: {pc}  Fail: {fc}  Skip: {sc}  Total: {len(ncl)}")
        for c in ncl[:5]:
            cs = c.get("status", "?")
            c_color = GREEN if cs == "PASS" else (RED if cs == "FAIL" else YELLOW)
            print(f"    {c_color}{cs:<6}{RESET} {c.get('check', '?')}")
        if len(ncl) > 5:
            print(f"    ... and {len(ncl)-5} more checks")
        print()

    # Workflow summary
    wf = result.get("workflow_summary", {})
    if wf:
        print(f"  {BOLD}Workflow Summary{RESET}")
        print(f"    Canary NC ready:            {_bool_str(wf.get('order_window_canary_negative_control_ready'))}")
        print(f"    Artifact created:           {_bool_str(wf.get('order_window_canary_artifact_created'))}")
        print(f"    Window confirmed closed:    {_bool_str(wf.get('order_window_closed_as_expected'))}")
        print(f"    All controls blocked:       {_bool_str(wf.get('all_controls_blocked'))}")
        print(f"    H1 boundary preserved:      {_bool_str(wf.get('h1_boundary_preserved'))}")
        print(f"    Checklist complete:         {_bool_str(wf.get('checklist_complete'))}")
        print()

    print(f"  {BOLD}Non-Mutation Guarantees{RESET}")
    print(f"    no_broker_mutation:            {_bool_str(result.get('no_broker_mutation'))}")
    print(f"    no_order_endpoint_called:      {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    no_trade_window_helper_called: {_bool_str(result.get('no_trade_window_helper_called'))}")
    print(f"    no_h1_seen:                    {_bool_str(result.get('no_h1_seen'))}")
    print(f"    h1_token_not_used:             {_bool_str(result.get('h1_token_not_used'))}")
    print()

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"  Evidence hash: {eh[:16]}...")
    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_h1_boundary_audit_checkpoint(result: dict) -> None:
    """Print Phase 16Q H1 boundary audit in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16Q_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE16Q_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 H1 Boundary Audit Checkpoint (16Q){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:         {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:             {result.get('timestamp', '?')}")
    print(f"  Canonical trade date:  {result.get('canonical_trade_date', '?')}")
    print(f"  Trade date stale:      {_bool_str(result.get('trade_date_stale', False))}")
    print(f"  Halt active:           {_bool_str(result.get('halt_active', False))}")
    print(f"  Guard state clean:     {_bool_str(result.get('guard_state_clean', False))}")
    print(f"  Diagnosis:             {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:              {sev_color}{sev}{RESET}")
    print(f"  H1 boundary intact:    {GREEN if result.get('h1_boundary_intact') else RED}{_bool_str(result.get('h1_boundary_intact'))}{RESET}")
    print()

    # H1 boundary audit
    hba = result.get("h1_boundary_audit", {})
    if hba:
        print(f"  {BOLD}H1 Boundary Audit{RESET}")
        print(f"    Status:                     {GREEN if hba.get('status') == 'boundary_intact' else RED}{hba.get('status', '?')}{RESET}")
        print(f"    Audit only:                 {_bool_str(hba.get('audit_only'))}")
        print(f"    Raw token value seen:       {_bool_str(hba.get('raw_token_value_seen'))}")
        print(f"    Raw token logged:           {_bool_str(hba.get('raw_token_logged'))}")
        print(f"    Env hash only:              {_bool_str(hba.get('env_hash_only'))}")
        print(f"    H1 header constructed:      {_bool_str(hba.get('x_h1_token_header_constructed'))}")
        print(f"    H1 header sent:             {_bool_str(hba.get('x_h1_token_header_sent'))}")
        print(f"    Trade-window helper called: {_bool_str(hba.get('trade_window_helper_called'))}")
        print(f"    Manual canary required:     {_bool_str(hba.get('manual_canary_required'))}")
        print(f"    Canaries: {hba.get('canaries_blocked_count', 0)} blocked / {hba.get('canaries_count', 0)} total")
        print(f"    Future path:                {hba.get('future_required_path', '?')}")
        print()

    # H1 probe matrix
    hpm = result.get("h1_probe_matrix", {})
    if hpm:
        print(f"  {BOLD}H1 Probe Matrix{RESET}")
        print(f"    Raw token read allowed:     {_bool_str(hpm.get('raw_token_read_allowed'))}")
        print(f"    Raw token read performed:   {_bool_str(hpm.get('raw_token_read_performed'))}")
        print(f"    Env hash present:           {_bool_str(hpm.get('env_hash_present'))}")
        print(f"    H1 header constructed:      {_bool_str(hpm.get('h1_header_constructed'))}")
        print(f"    H1 header sent:             {_bool_str(hpm.get('h1_header_sent'))}")
        print(f"    Manual canary status:       {hpm.get('manual_canary_status', '?')}")
        print()

    # Canary intents
    canaries = result.get("canary_intents", [])
    if canaries:
        print(f"  {BOLD}H1 Boundary Canary Intents (all locally blocked){RESET}")
        for c in canaries:
            print(f"    {c.get('canary_id', '?')}")
            print(f"      type={c.get('canary_type', '?')}  "
                  f"{c.get('side', c.get('action', '?'))} {c.get('quantity', '?')}x "
                  f"{c.get('symbol', '?')} ({c.get('order_type', '?')})")
            print(f"      simulated_only={_bool_str(c.get('simulated_canary_only'))}  "
                  f"blocked={_bool_str(c.get('blocked'))}  "
                  f"requires_h1={_bool_str(c.get('requires_h1'))}")
            reasons = c.get("blocking_reasons", [])
            if reasons:
                print(f"      Reasons ({len(reasons)}): {', '.join(reasons[:3])}")
        print()

    # H1 boundary checklist
    ncl = result.get("h1_boundary_checklist", [])
    if ncl:
        print(f"  {BOLD}H1 Boundary Checklist{RESET}")
        pc = sum(1 for c in ncl if c.get("status") == "PASS")
        fc = sum(1 for c in ncl if c.get("status") == "FAIL")
        sc = sum(1 for c in ncl if c.get("status") == "SKIP")
        print(f"    Pass: {pc}  Fail: {fc}  Skip: {sc}  Total: {len(ncl)}")
        for c in ncl[:5]:
            cs = c.get("status", "?")
            c_color = GREEN if cs == "PASS" else (RED if cs == "FAIL" else YELLOW)
            print(f"    {c_color}{cs:<6}{RESET} {c.get('check', '?')}")
        if len(ncl) > 5:
            print(f"    ... and {len(ncl)-5} more checks")
        print()

    # Workflow summary
    wf = result.get("workflow_summary", {})
    if wf:
        print(f"  {BOLD}Workflow Summary{RESET}")
        print(f"    H1 boundary audit ready:    {_bool_str(wf.get('h1_boundary_audit_ready'))}")
        print(f"    H1 boundary intact:         {_bool_str(wf.get('h1_boundary_intact'))}")
        print(f"    Raw token unread:           {_bool_str(wf.get('raw_token_unread'))}")
        print(f"    Hash only configured:       {_bool_str(wf.get('hash_only_configured'))}")
        print(f"    H1 header never sent:       {_bool_str(wf.get('h1_header_never_sent'))}")
        print(f"    All H1 controls blocked:    {_bool_str(wf.get('all_h1_controls_blocked'))}")
        print(f"    Checklist complete:         {_bool_str(wf.get('checklist_complete'))}")
        print()

    print(f"  {BOLD}Non-Mutation Guarantees{RESET}")
    print(f"    no_broker_mutation:            {_bool_str(result.get('no_broker_mutation'))}")
    print(f"    no_order_window_opened:        {_bool_str(result.get('no_order_window_opened'))}")
    print(f"    h1_token_not_used:             {_bool_str(result.get('h1_token_not_used'))}")
    print(f"    h1_token_not_read:             {_bool_str(result.get('h1_token_not_read'))}")
    print(f"    no_raw_token_read:             {_bool_str(result.get('no_raw_token_read'))}")
    print(f"    no_raw_token_value_seen:       {_bool_str(result.get('no_raw_token_value_seen'))}")
    print(f"    no_h1_header_constructed:      {_bool_str(result.get('no_h1_header_constructed'))}")
    print(f"    no_h1_header_sent:             {_bool_str(result.get('no_h1_header_sent'))}")
    print(f"    no_approval_endpoint_called:   {_bool_str(result.get('no_approval_endpoint_called'))}")
    print(f"    execution_authorized_now:      {_bool_str(result.get('execution_authorized_now'))}")
    print(f"    execution_performed:           {_bool_str(result.get('execution_performed'))}")
    print()

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"  Evidence hash: {eh[:16]}...")
    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_broker_mutation_firewall_audit_checkpoint(result: dict) -> None:
    """Print Phase 16R broker-mutation firewall audit checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16R_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE16R_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Broker-Mutation Firewall Audit Checkpoint (16R){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Canonical trade date:        {result.get('canonical_trade_date', '?')}")
    print(f"  Guard state clean:           {_bool_str(result.get('guard_state_clean', False))}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print(f"  Current level:               {result.get('current_level', '?')}")
    print(f"  Firewall intact:             {GREEN if result.get('broker_mutation_firewall_intact') else RED}{_bool_str(result.get('broker_mutation_firewall_intact'))}{RESET}")
    print(f"  All surfaces blocked:        {GREEN if result.get('all_mutation_surfaces_blocked') else RED}{_bool_str(result.get('all_mutation_surfaces_blocked'))}{RESET}")
    print(f"  All blocks expected:         {GREEN if result.get('all_blocks_expected') else RED}{_bool_str(result.get('all_blocks_expected'))}{RESET}")
    print()

    # Broker-mutation firewall
    fw = result.get("broker_mutation_firewall", {})
    if fw:
        print(f"  {BOLD}Broker-Mutation Firewall{RESET}")
        print(f"    Status:                     {GREEN if fw.get('status') == 'firewall_intact' else RED}{fw.get('status', '?')}{RESET}")
        print(f"    Audit only:                 {_bool_str(fw.get('audit_only'))}")
        print(f"    Read-only mode:             {_bool_str(fw.get('read_only_mode'))}")
        print(f"    Positions flat:             {_bool_str(fw.get('positions_flat'))}")
        print(f"    /order called:              {_bool_str(fw.get('order_endpoint_called'))}")
        print(f"    /order/preflight called:    {_bool_str(fw.get('preflight_endpoint_called'))}")
        print(f"    /order/approve called:      {_bool_str(fw.get('approval_endpoint_called'))}")
        print(f"    /order/submit called:       {_bool_str(fw.get('submit_endpoint_called'))}")
        print(f"    Broker order created:       {_bool_str(fw.get('broker_order_created'))}")
        print(f"    Broker submission:          {_bool_str(fw.get('broker_submission_performed'))}")
        print(f"    Canaries: {fw.get('canaries_blocked_count', 0)} blocked / {fw.get('canaries_count', 0)} total")
        print(f"    Future path:                {fw.get('future_required_path', '?')}")
        print()

    # Mutation surface audit
    msa = result.get("mutation_surface_audit", {})
    if msa:
        print(f"  {BOLD}Mutation Surface Audit{RESET}")
        print(f"    Surfaces: {msa.get('surfaces_passed_count', 0)} passed / {msa.get('surfaces_count', 0)} total")
        sf = msa.get("surfaces", [])
        for s in sf[:3]:
            print(f"    - {s.get('surface', '?')}: blocked={_bool_str(s.get('blocked'))}")
        if len(sf) > 3:
            print(f"    ... and {len(sf)-3} more")
        print()

    # Broker-mutation checklist
    ncl = result.get("broker_mutation_checklist", [])
    if ncl:
        print(f"  {BOLD}Broker-Mutation Checklist{RESET}")
        pc = sum(1 for c in ncl if c.get("status") == "PASS")
        fc = sum(1 for c in ncl if c.get("status") == "FAIL")
        sc = sum(1 for c in ncl if c.get("status") == "SKIP")
        print(f"    Pass: {pc}  Fail: {fc}  Skip: {sc}  Total: {len(ncl)}")
        for c in ncl[:5]:
            cs = c.get("status", "?")
            c_color = GREEN if cs == "PASS" else (RED if cs == "FAIL" else YELLOW)
            print(f"    {c_color}{cs:<6}{RESET} {c.get('check', '?')}")
        if len(ncl) > 5:
            print(f"    ... and {len(ncl)-5} more checks")
        print()

    print(f"  {BOLD}Non-Mutation Guarantees{RESET}")
    print(f"    no_broker_mutation:           {_bool_str(result.get('no_broker_mutation'))}")
    print(f"    no_broker_order_created:      {_bool_str(result.get('no_broker_order_created'))}")
    print(f"    no_broker_submission:         {_bool_str(result.get('no_broker_submission'))}")
    print(f"    no_account_mutation:          {_bool_str(result.get('no_account_mutation'))}")
    print(f"    no_position_mutation:         {_bool_str(result.get('no_position_mutation'))}")
    print(f"    no_order_endpoint_called:     {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    no_preflight_endpoint_called: {_bool_str(result.get('no_preflight_endpoint_called'))}")
    print(f"    no_approve_endpoint_called:   {_bool_str(result.get('no_approve_endpoint_called'))}")
    print(f"    no_submit_endpoint_called:    {_bool_str(result.get('no_submit_endpoint_called'))}")
    print()

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"  Evidence hash: {eh[:16]}...")
    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_end_to_end_safety_invariant_checkpoint(result: dict) -> None:
    """Print Phase 16S end-to-end safety invariant checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16S_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE16S_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 End-to-End Safety Invariant Checkpoint (16S){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Current level:               {result.get('current_level', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")

    invariant = result.get("end_to_end_safety_invariant", {})
    inv_intact = invariant.get("status") == "invariant_intact"
    print(f"  Invariant status:            {GREEN if inv_intact else RED}{invariant.get('status', '?')}{RESET}")
    print(f"  All boundaries intact:       {GREEN if inv_intact else RED}{_bool_str(inv_intact)}{RESET}")
    print()

    print(f"  {BOLD}Boundary Checks{RESET}")
    print(f"    KPI boundary:               {GREEN if result.get('kpi_acceptable') else RED}{_bool_str(result.get('kpi_acceptable'))}{RESET}")
    print(f"    Doctor boundary:            {GREEN if result.get('doctor_acceptable') else RED}{_bool_str(result.get('doctor_acceptable'))}{RESET}")
    print(f"    Policy boundary:            {GREEN if result.get('policy_boundary_ok') else RED}{_bool_str(result.get('policy_boundary_ok'))}{RESET}")
    print(f"    Mutation boundary:          {GREEN if result.get('mutation_boundary_ok') else RED}{_bool_str(result.get('mutation_boundary_ok'))}{RESET}")
    print(f"    H1 boundary:                {GREEN if result.get('h1_boundary_ok') else RED}{_bool_str(result.get('h1_boundary_ok'))}{RESET}")
    print(f"    Order-window boundary:      {GREEN if result.get('order_window_boundary_ok') else RED}{_bool_str(result.get('order_window_boundary_ok'))}{RESET}")
    print(f"    Execution-gate boundary:    {GREEN if result.get('execution_gate_boundary_ok') else RED}{_bool_str(result.get('execution_gate_boundary_ok'))}{RESET}")
    print()

    print(f"  {BOLD}Safety Segments{RESET}")
    ri = invariant.get("readiness_chain_intact", False)
    eg = invariant.get("execution_gate_closed", False)
    ow = invariant.get("order_window_closed", False)
    h1 = invariant.get("h1_boundary_intact", False)
    bm = invariant.get("broker_mutation_firewall_intact", False)
    print(f"    Readiness chain:            {GREEN if ri else RED}{_bool_str(ri)}{RESET}")
    print(f"    Execution gate:             {GREEN if eg else RED}{_bool_str(eg)}{RESET}")
    print(f"    Order window:               {GREEN if ow else RED}{_bool_str(ow)}{RESET}")
    print(f"    H1 boundary:                {GREEN if h1 else RED}{_bool_str(h1)}{RESET}")
    print(f"    Broker-mutation firewall:   {GREEN if bm else RED}{_bool_str(bm)}{RESET}")
    print(f"    Orders disabled:            {_bool_str(invariant.get('orders_disabled'))}")
    print(f"    Rules not enforced:         {_bool_str(invariant.get('rules_not_enforced'))}")
    print(f"    System locked:              {_bool_str(invariant.get('system_locked'))}")
    print()

    matrix = result.get("invariant_matrix", {})
    if matrix:
        print(f"  {BOLD}Invariant Matrix{RESET}")
        all_ok = matrix.get("all_required_tags_present")
        print(f"    All tags:                   {GREEN if all_ok else RED}{_bool_str(all_ok)}{RESET}")
        print(f"    Runtime safe:               {_bool_str(matrix.get('runtime_safe'))}")
        print(f"    Autonomy safe:              {_bool_str(matrix.get('autonomy_safe'))}")
        print(f"    Guard state clean:          {_bool_str(matrix.get('guard_state_clean'))}")
        print(f"    Safety locked:              {_bool_str(matrix.get('safety_flags_locked'))}")
        print(f"    Positions flat:             {_bool_str(matrix.get('positions_flat'))}")
        print()

    print(f"  {BOLD}Non-Mutation Guarantees{RESET}")
    print(f"    no_order_endpoint_called:    {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    no_broker_mutation:          {_bool_str(result.get('no_broker_mutation'))}")
    print(f"    no_h1_token_used:            {_bool_str(result.get('no_h1_token_used'))}")
    print(f"    no_order_window_opened:      {_bool_str(result.get('no_order_window_opened'))}")
    print(f"    execution_authorized_now:    {_bool_str(result.get('execution_authorized_now'))}")
    print()

    ncl = result.get("invariant_checklist", [])
    if ncl:
        print(f"  {BOLD}Invariant Checklist{RESET}")
        pc = sum(1 for c in ncl if c.get("status") == "PASS")
        fc = sum(1 for c in ncl if c.get("status") == "FAIL")
        sc = sum(1 for c in ncl if c.get("status") == "SKIP")
        print(f"    Pass: {pc}  Fail: {fc}  Skip: {sc}  Total: {len(ncl)}")
        for c in ncl[:5]:
            cs = c.get("status", "?")
            c_color = GREEN if cs == "PASS" else (RED if cs == "FAIL" else YELLOW)
            print(f"    {c_color}{cs:<6}{RESET} {c.get('check', '?')}")
        if len(ncl) > 5:
            print(f"    ... and {len(ncl)-5} more checks")
        print()

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"  Evidence hash: {eh[:16]}...")
    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_restart_persistence_safety_checkpoint(result: dict) -> None:
    """Print Phase 16T restart-persistence safety checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE16T_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE16T_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Restart-Persistence Safety Checkpoint (16T){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")

    audit = result.get("restart_persistence_audit", {})
    inv_surv = audit.get("invariant_survived", False)
    print(f"  Invariant survived:          {GREEN if inv_surv else RED}{_bool_str(inv_surv)}{RESET}")
    print(f"  Restart attempted:           {_bool_str(result.get('restart_attempted', False))}")
    print(f"  Restart performed:           {_bool_str(audit.get('restart_performed', False))}")
    print(f"  Restart cmd timed out:       {_bool_str(result.get('restart_command_timed_out', False))}")
    print(f"  Restart target:              {audit.get('restart_target', '?')}")
    print()

    print(f"  {BOLD}Before Restart{RESET}")
    before = result.get("before", {})
    print(f"    Bridge connected:           {_bool_str(before.get('connected', False))}")
    print(f"    Mode:                       {before.get('mode', '?')}")
    print(f"    Read-only:                  {_bool_str(before.get('read_only', False))}")
    print(f"    Endpoints OK:               {_bool_str(before.get('endpoints_ok', False))}")
    print(f"    16S invariant OK:           {_bool_str(before.get('sixteen_s_ok', False))}")
    print()

    print(f"  {BOLD}After Restart{RESET}")
    after = result.get("after", {})
    aconn = after.get("connected", False)
    amode = after.get("mode", "?")
    aro = after.get("read_only", False)
    aao = after.get("allow_orders", None)
    aeok = after.get("endpoints_ok", False)
    apf = after.get("positions_flat", None)
    print(f"    Bridge connected:           {GREEN if aconn else RED}{_bool_str(aconn)}{RESET}")
    print(f"    Mode:                       {GREEN if amode == 'paper' else RED}{amode}{RESET}")
    print(f"    Read-only:                  {GREEN if aro else RED}{_bool_str(aro)}{RESET}")
    print(f"    Allow orders:               {GREEN if aao is False else RED}{aao}{RESET}")
    print(f"    Endpoints OK:               {GREEN if aeok else RED}{_bool_str(aeok)}{RESET}")
    endpoints_display = f"{after.get('endpoints_ok_count', 0)}/{after.get('endpoints_total_count', 0)}"
    print(f"    Endpoints:                  {endpoints_display}")
    print(f"    Positions flat:             {_bool_str(apf)}")
    print(f"    System locked:              {_bool_str(after.get('system_locked', None))}")
    print()

    print(f"  {BOLD}Safety Survivals{RESET}")
    print(f"    Bridge survived:            {_bool_str(audit.get('bridge_survived', False))}")
    print(f"    Mode survived:              {_bool_str(audit.get('mode_survived', False))}")
    print(f"    Read-only survived:         {_bool_str(audit.get('read_only_survived', False))}")
    print(f"    Allow-orders survived:      {_bool_str(audit.get('allow_orders_survived', False))}")
    print(f"    Endpoints survived:         {_bool_str(audit.get('endpoints_survived', False))}")
    print(f"    Positions survived:         {_bool_str(audit.get('positions_survived', False))}")
    print(f"    Guard state survived:       {_bool_str(audit.get('guard_state_survived', False))}")
    print(f"    16S invariant survived:     {_bool_str(audit.get('safety_invariant_survived', False))}")
    print()

    a_16s = result.get("sixteen_s_after_summary", {})
    b_16s = result.get("sixteen_s_before_summary", {})
    print(f"  {BOLD}16S Invariant{RESET}")
    print(f"    Before:  {b_16s.get('diagnosis', '?')} ({b_16s.get('severity', '?')})")
    print(f"    Before exit:                 {result.get('sixteen_s_before_exit', '?')}")
    print(f"    Before connected:            {_bool_str(b_16s.get('runtime_connected', False))}")
    print(f"    Before guard clean:          {_bool_str(b_16s.get('guard_state_clean', False))}")
    print(f"    Before invariant intact:     {_bool_str(b_16s.get('invariant_intact', False))}")
    print(f"    Before all boundaries:       {_bool_str(b_16s.get('all_boundaries_intact', False))}")
    print(f"    After:   {a_16s.get('diagnosis', '?')} ({a_16s.get('severity', '?')})")
    sixteen_s_after_exit = result.get('sixteen_s_after_exit')
    if sixteen_s_after_exit is not None:
        print(f"    16S after exit:              {sixteen_s_after_exit}")
    print()

    print(f"  {BOLD}Recovery Timing{RESET}")
    rps = result.get('recovery_poll_seconds')
    print(f"    Recovery poll:               {rps}s" if rps is not None else f"    Recovery poll:               N/A")
    sas = result.get('service_active_after_seconds')
    print(f"    Service active after:        {sas}s" if sas is not None else f"    Service active after:        N/A")
    hra = result.get('health_reachable_after_seconds')
    print(f"    Health reachable after:      {hra}s" if hra is not None else f"    Health reachable after:      N/A")
    cas = result.get('connected_after_seconds')
    print(f"    Connected after:             {cas}s" if cas is not None else f"    Connected after:             N/A")
    kha = result.get('kpi_healthy_after_seconds')
    print(f"    KPI healthy after:           {kha}s" if kha is not None else f"    KPI healthy after:           N/A")
    print()

    print(f"  {BOLD}Non-Mutation Guarantees{RESET}")
    print(f"    no_order_endpoint_called:    {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    no_broker_mutation:          {_bool_str(result.get('no_broker_mutation'))}")
    print(f"    no_h1_token_used:            {_bool_str(result.get('no_h1_token_used'))}")
    print(f"    no_order_window_opened:      {_bool_str(result.get('no_order_window_opened'))}")
    print(f"    execution_authorized_now:    {_bool_str(result.get('execution_authorized_now'))}")
    print()

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"  Evidence hash: {eh[:16]}...")
    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_startup_autoconnect_resilience_checkpoint(result: dict) -> None:
    """Print Phase 16U startup auto-connect resilience checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE16U_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE16U_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Startup Auto-Connect Resilience Chkpt (16U){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()

    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit', '?')[:12] if g.get('commit') else '?'}")
    print(f"    Tag:           {g.get('tag', '?')}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()

    print(f"  {BOLD}Runtime State{RESET}")
    rt = result.get("runtime", {})
    print(f"    Connected:     {GREEN if rt.get('connected') else RED}{_bool_str(rt.get('connected'))}{RESET}")
    print(f"    Mode:          {GREEN if rt.get('mode') == 'paper' else RED}{rt.get('mode', '?')}{RESET}")
    print(f"    Read-only:     {GREEN if rt.get('read_only') else RED}{_bool_str(rt.get('read_only'))}{RESET}")
    print(f"    Allow orders:  {GREEN if rt.get('allow_orders') is False else RED}{rt.get('allow_orders')}{RESET}")
    print(f"    Endpoints OK:  {GREEN if rt.get('endpoints_ok') else RED}{_bool_str(rt.get('endpoints_ok'))}{RESET}")
    print(f"    Endpoints:     {rt.get('endpoints_display', '?')}")
    print(f"    System locked: {_bool_str(rt.get('system_locked', None))}")
    print()

    print(f"  {BOLD}Startup Auto-Connect Config{RESET}")
    cfg = result.get("startup_autoconnect_config", {})
    print(f"    Config found:  {_bool_str(result.get('startup_autoconnect_config_found', False))}")
    print(f"    Source:        {cfg.get('source_file', '?')}")
    print(f"    Max attempts:  {result.get('startup_autoconnect_attempts', 0)}")
    print(f"    Retry delay:   {cfg.get('retry_delay_seconds', 0)}s")
    print(f"    Retry window:  {result.get('startup_autoconnect_retry_window_seconds', 0)}s")
    print(f"    Window >= 300s: {_bool_str(result.get('startup_autoconnect_retry_window_ge_300', False))}")
    print(f"    Attempts >= 60: {_bool_str(result.get('startup_autoconnect_attempts_ge_60', False))}")
    print(f"    Local connect: {_bool_str(result.get('startup_autoconnect_uses_local_connect', False))}")
    print(f"    Connect only:  {_bool_str(result.get('connect_path_only', False))}")
    print()

    print(f"  {BOLD}Journal Evidence{RESET}")
    jrn = result.get("startup_autoconnect_journal", {})
    print(f"    Lines found:   {jrn.get('line_count', 0)}")
    if jrn.get("last_ok"):
        print(f"    Last OK:       {jrn['last_ok'][:120]}")
    if jrn.get("last_failed"):
        print(f"    Last FAILED:   {jrn['last_failed'][:120]}")
    if not jrn.get("last_ok") and not jrn.get("last_failed"):
        print(f"    (no recent startup_auto_connect entries)")
    print()

    print(f"  {BOLD}Safety{RESET}")
    print(f"    Guard state clean:          {_bool_str(result.get('guard_state_clean', False))}")
    print(f"    No /order* called:          {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    No preflight called:        {_bool_str(result.get('no_preflight_endpoint_called'))}")
    print(f"    No approval called:         {_bool_str(result.get('no_approval_endpoint_called'))}")
    print(f"    No submit called:           {_bool_str(result.get('no_submit_endpoint_called'))}")
    print(f"    No H1 token used:           {_bool_str(result.get('no_h1_token_used'))}")
    print(f"    No trade window:            {_bool_str(result.get('no_trade_window_helper_called'))}")
    print(f"    No broker mutation:         {_bool_str(result.get('no_broker_mutation'))}")
    print(f"    Artifact created:           {_bool_str(result.get('artifact_created', False))}")
    print()

    if not checkpoint_ok:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in result.get("suggested_operator_actions", []):
            print(f"    {RED}✗{RESET} {a}")
        print()

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"  Evidence hash: {eh[:16]}...")
    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_guard_state_rollover_resilience_checkpoint(result: dict) -> None:
    """Print Phase 16V guard-state rollover resilience checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE16V_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE16V_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Guard-State Rollover Resilience Chkpt (16V){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()

    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit', '?')[:12] if g.get('commit') else '?'}")
    print(f"    Tag:           {g.get('tag', '?')}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()

    print(f"  {BOLD}Runtime State{RESET}")
    rt = result.get("runtime", {})
    print(f"    Connected:     {GREEN if rt.get('connected') else RED}{_bool_str(rt.get('connected'))}{RESET}")
    print(f"    Mode:          {GREEN if rt.get('mode') == 'paper' else RED}{rt.get('mode', '?')}{RESET}")
    print(f"    Read-only:     {GREEN if rt.get('read_only') else RED}{_bool_str(rt.get('read_only'))}{RESET}")
    print(f"    Allow orders:  {GREEN if rt.get('allow_orders') is False else RED}{rt.get('allow_orders')}{RESET}")
    print(f"    Endpoints OK:  {GREEN if rt.get('endpoints_ok') else RED}{_bool_str(rt.get('endpoints_ok'))}{RESET}")
    print()

    print(f"  {BOLD}Current Guard State{RESET}")
    print(f"    Clean:         {GREEN if result.get('current_guard_state_clean') else RED}{_bool_str(result.get('current_guard_state_clean'))}{RESET}")
    gs = result.get("guard_state_section", {})
    print(f"    Trade date:    {gs.get('trade_date', '?')}")
    print(f"    Canonical:     {gs.get('canonical_trade_date', '?')}")
    print(f"    Date stale:    {_bool_str(gs.get('trade_date_stale', '?'))}")
    print(f"    Trade count:   {gs.get('daily_trade_count', '?')}")
    print(f"    Halt active:   {_bool_str(gs.get('halt_active', None))}")
    print()

    print(f"  {BOLD}Reconcile Dry-Run{RESET}")
    print(f"    Exit:          {GREEN if result.get('reconcile_dry_run_exit') == 0 else RED}{result.get('reconcile_dry_run_exit', '?')}{RESET}")
    print(f"    Repair applied: {GREEN if result.get('reconcile_repair_applied') is False else RED}{_bool_str(result.get('reconcile_repair_applied'))}{RESET}")
    rd = result.get("reconcile_dry_run", {})
    if rd:
        print(f"    Mismatch:      {_bool_str(rd.get('mismatch_detected', False))}")
        print(f"    Recommended:   {_bool_str(rd.get('repair_recommended', False))}")
        print(f"    Reason:        {rd.get('repair_reason', 'none')}")
        blk = rd.get("blockers", [])
        if blk:
            for b in blk:
                print(f"    Blocker:       {b.get('check', '?')}: {b.get('detail', '')}")
    print()

    print(f"  {BOLD}Synthetic Fixture Tests (temp files only){RESET}")
    syn = result.get("synthetic_cases", {})
    for case_key, label in [("stale_trade_date", "Stale trade-date rollover"),
                              ("false_trade_count", "False trade count > 0"),
                              ("already_clean", "Already-clean guard state"),
                              ("blocked_repair", "Blocked repair (live orders)")]:
        c = syn.get(case_key, {})
        ok = c.get("passed", False)
        print(f"    {label:30s} {GREEN if ok else RED}{'PASS' if ok else 'FAIL'}{RESET}")
    print()

    print(f"  {BOLD}Safety{RESET}")
    print(f"    No /order* called:          {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    No preflight called:        {_bool_str(result.get('no_preflight_endpoint_called'))}")
    print(f"    No approval called:         {_bool_str(result.get('no_approval_endpoint_called'))}")
    print(f"    No submit called:           {_bool_str(result.get('no_submit_endpoint_called'))}")
    print(f"    No H1 token used:           {_bool_str(result.get('no_h1_token_used'))}")
    print(f"    No trade window:            {_bool_str(result.get('no_trade_window_helper_called'))}")
    print(f"    No broker mutation:         {_bool_str(result.get('no_broker_mutation'))}")
    print(f"    Artifact created:           {_bool_str(result.get('artifact_created', False))}")
    print()

    if not checkpoint_ok:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in result.get("suggested_operator_actions", []):
            print(f"    {RED}✗{RESET} {a}")
        print()

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"  Evidence hash: {eh[:16]}...")
    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_scheduled_heartbeat_alerting_resilience_checkpoint(result: dict) -> None:
    """Print Phase 16W scheduled heartbeat & alerting resilience checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE16W_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE16W_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Scheduled Heartbeat & Alerting Resilience (16W){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit', '?')[:12] if g.get('commit') else '?'}")
    print(f"    Tag:           {g.get('tag', '?')}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Runtime State{RESET}")
    rt = result.get("runtime", {})
    print(f"    Connected:     {GREEN if rt.get('connected') else RED}{_bool_str(rt.get('connected'))}{RESET}")
    print(f"    Mode:          {GREEN if rt.get('mode') == 'paper' else RED}{rt.get('mode', '?')}{RESET}")
    print(f"    Read-only:     {GREEN if rt.get('read_only') else RED}{_bool_str(rt.get('read_only'))}{RESET}")
    print(f"    Allow orders:  {GREEN if rt.get('allow_orders') is False else RED}{rt.get('allow_orders')}{RESET}")
    print(f"    Endpoints OK:  {GREEN if rt.get('endpoints_ok') else RED}{_bool_str(rt.get('endpoints_ok'))}{RESET}")
    print(f"    Positions flat: {GREEN if rt.get('positions_flat') else RED}{_bool_str(rt.get('positions_flat'))}{RESET}")
    print()
    print(f"  {BOLD}Guard State{RESET}")
    print(f"    Clean:         {GREEN if result.get('guard_state_clean') else RED}{_bool_str(result.get('guard_state_clean'))}{RESET}")
    print()
    print(f"  {BOLD}KPI{RESET}")
    print(f"    HOLD system_locked: {GREEN if result.get('kpi_hold_only_system_locked') else RED}{_bool_str(result.get('kpi_hold_only_system_locked'))}{RESET}")
    print()
    print(f"  {BOLD}Heartbeat{RESET}")
    print(f"    Present:       {GREEN if result.get('heartbeat_present') else RED}{_bool_str(result.get('heartbeat_present'))}{RESET}")
    print(f"    Fresh (<24h):  {GREEN if result.get('heartbeat_fresh') else RED}{_bool_str(result.get('heartbeat_fresh'))}{RESET}")
    print(f"    Age:           {result.get('heartbeat_age_human', 'none')}")
    print(f"    Artifacts:     {result.get('heartbeat_artifact_count', 0)}")
    print()
    print(f"  {BOLD}Scheduled Timer{RESET}")
    print(f"    Found:         {GREEN if result.get('scheduled_timer_found') else RED}{_bool_str(result.get('scheduled_timer_found'))}{RESET}")
    print(f"    Enabled:       {GREEN if result.get('scheduled_timer_enabled') else RED}{_bool_str(result.get('scheduled_timer_enabled'))}{RESET}")
    print(f"    Install plan:  {GREEN if result.get('timer_install_plan_present') else RED}{_bool_str(result.get('timer_install_plan_present'))}{RESET}")
    print()
    print(f"  {BOLD}Read-Only Verification{RESET}")
    print(f"    Heartbeat cmd: {GREEN if result.get('heartbeat_command_read_only') else RED}{_bool_str(result.get('heartbeat_command_read_only'))}{RESET}")
    print(f"    Monitor alert: {GREEN if result.get('monitor_alert_check_read_only') else RED}{_bool_str(result.get('monitor_alert_check_read_only'))}{RESET}")
    print()
    print(f"  {BOLD}Alert Channels{RESET}")
    print(f"    Configured:    {GREEN if result.get('alert_channel_configured') else RED}{_bool_str(result.get('alert_channel_configured'))}{RESET}")
    print(f"    Dry-run verified: {_bool_str(result.get('alert_channel_dry_run_verified'))}")
    print()
    print(f"  {BOLD}Synthetic Fixture Tests (temp files only){RESET}")
    syn = result.get("synthetic_cases", {})
    for case_key, label in [("fresh_heartbeat", "Fresh heartbeat passes"), ("stale_heartbeat", "Stale heartbeat fails"), ("missing_timer", "Missing timer fails"), ("dry_run_alert", "Dry-run alert event"), ("read_only_invariant", "Read-only invariant")]:
        c = syn.get(case_key, {})
        ok = c.get("passed", False)
        print(f"    {label:35s} {GREEN if ok else RED}{'PASS' if ok else 'FAIL'}{RESET}")
    print()
    print(f"  {BOLD}Safety{RESET}")
    print(f"    No /order* called:          {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    No preflight called:        {_bool_str(result.get('no_preflight_endpoint_called'))}")
    print(f"    No approval called:         {_bool_str(result.get('no_approval_endpoint_called'))}")
    print(f"    No submit called:           {_bool_str(result.get('no_submit_endpoint_called'))}")
    print(f"    No H1 token used:           {_bool_str(result.get('no_h1_token_used'))}")
    print(f"    No trade window:            {_bool_str(result.get('no_trade_window_helper_called'))}")
    print(f"    No broker mutation:         {_bool_str(result.get('no_broker_mutation'))}")
    print(f"    Artifact created:           {_bool_str(result.get('artifact_created', False))}")
    print()
    if not checkpoint_ok:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in result.get("suggested_operator_actions", []):
            print(f"    {RED}✗{RESET} {a}")
        print()
    eh = result.get("evidence_hash", "")
    if eh:
        print(f"  Evidence hash: {eh[:16]}...")
    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_os_boundary_h1_isolation_checkpoint(result: dict) -> None:
    """Print Phase 16X OS boundary & H1 isolation checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE16X_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE16X_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 OS Boundary & H1 Isolation Checkpoint (16X){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Tag:           {g.get('tag', '?')}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Runtime State{RESET}")
    rt = result.get("runtime", {})
    print(f"    Connected:     {_bool_str(rt.get('connected'))}")
    print(f"    Mode:          {rt.get('mode', '?')}")
    print(f"    Read-only:     {_bool_str(rt.get('read_only'))}")
    print(f"    Allow orders:  {rt.get('allow_orders')}")
    print(f"    Endpoints OK:  {_bool_str(rt.get('endpoints_ok'))}")
    print(f"    Positions flat: {_bool_str(rt.get('positions_flat'))}")
    print()
    print(f"  {BOLD}Guard State & KPI{RESET}")
    print(f"    Guard clean:   {_bool_str(result.get('guard_state_clean'))}")
    print(f"    KPI HOLD sys.locked: {_bool_str(result.get('kpi_hold_only_system_locked'))}")
    print()
    print(f"  {BOLD}OS Boundary — File Protection{RESET}")
    print(f"    .env protected:            {GREEN if result.get('env_file_protected') else RED}{_bool_str(result.get('env_file_protected'))}{RESET}")
    print(f"    rules.yaml protected:      {GREEN if result.get('rules_file_protected') else RED}{_bool_str(result.get('rules_file_protected'))}{RESET}")
    print(f"    guard-state protected:     {GREEN if result.get('guard_state_file_protected') else RED}{_bool_str(result.get('guard_state_file_protected'))}{RESET}")
    print(f"    H1 raw token protected:    {GREEN if result.get('h1_raw_token_file_protected') else RED}{_bool_str(result.get('h1_raw_token_file_protected'))}{RESET}")
    print()
    print(f"  {BOLD}H1 Isolation{RESET}")
    print(f"    H1 hash only in .env:      {GREEN if result.get('h1_hash_only_in_env') else RED}{_bool_str(result.get('h1_hash_only_in_env'))}{RESET}")
    print(f"    Raw H1 not leaked:         {GREEN if result.get('raw_h1_not_leaked') else RED}{_bool_str(result.get('raw_h1_not_leaked'))}{RESET}")
    print(f"    Non-owner write denied:    {GREEN if result.get('non_owner_write_denied') else RED}{_bool_str(result.get('non_owner_write_denied'))}{RESET}")
    print(f"    H1 request scope isolated: {GREEN if result.get('h1_request_scope_isolated') else RED}{_bool_str(result.get('h1_request_scope_isolated'))}{RESET}")
    print()
    print(f"  {BOLD}Bridge Service{RESET}")
    svc = result.get("service_user_check", {})
    print(f"    User verified:  {_bool_str(result.get('bridge_service_user_verified'))}")
    print(f"    Service user:   {svc.get('service_user', '?')}")
    print(f"    Note:           {svc.get('note', '?')}")
    print()
    print(f"  {BOLD}Synthetic Fixture Tests (temp files only){RESET}")
    syn = result.get("synthetic_cases", {})
    for case_key, label in [
        ("env_write_denied", "Env write denied"),
        ("rules_write_denied", "Rules write denied"),
        ("guard_state_write_denied", "Guard-state write denied"),
        ("h1_file_mode", "H1 file mode 0600"),
        ("raw_h1_leak_scan", "Raw H1 leak scan"),
        ("concurrent_h1_isolation", "Concurrent H1 isolation"),
        ("read_only_invariant", "Read-only invariant"),
    ]:
        c = syn.get(case_key, {})
        ok = c.get("passed", False)
        print(f"    {label:30s} {GREEN if ok else RED}{'PASS' if ok else 'FAIL'}{RESET}")
    print()
    print(f"  {BOLD}Safety{RESET}")
    print(f"    No /order* called:         {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    No H1 token used:          {_bool_str(result.get('no_h1_token_used'))}")
    print(f"    No trade window:           {_bool_str(result.get('no_trade_window_helper_called'))}")
    print(f"    No broker mutation:        {_bool_str(result.get('no_broker_mutation'))}")
    print(f"    Artifact created:          {_bool_str(result.get('artifact_created', False))}")
    print()
    if not checkpoint_ok:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in result.get("suggested_operator_actions", []):
            print(f"    {RED}✗{RESET} {a}")
        print()
    eh = result.get("evidence_hash", "")
    if eh:
        print(f"  Evidence hash: {eh[:16]}...")
    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_portable_tests_ci_readiness_checkpoint(result: dict) -> None:
    """Print Phase 16Y portable tests & CI readiness checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE16Y_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE16Y_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Portable Tests & CI Readiness Checkpoint (16Y){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Tag:           {g.get('tag', '?')}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Runtime State{RESET}")
    rt = result.get("runtime", {})
    print(f"    Connected:     {_bool_str(rt.get('connected'))}")
    print(f"    Mode:          {rt.get('mode', '?')}")
    print(f"    Read-only:     {_bool_str(rt.get('read_only'))}")
    print(f"    Allow orders:  {rt.get('allow_orders')}")
    print(f"    Endpoints OK:  {_bool_str(rt.get('endpoints_ok'))}")
    print(f"    Positions flat: {_bool_str(rt.get('positions_flat'))}")
    print()
    print(f"  {BOLD}Guard State & KPI{RESET}")
    print(f"    Guard clean:   {_bool_str(result.get('guard_state_clean'))}")
    print(f"    KPI HOLD sys.locked: {_bool_str(result.get('kpi_hold_only_system_locked'))}")
    print()
    print(f"  {BOLD}Pure Tests — Discovery & Separation{RESET}")
    print(f"    Pure tests discovered:            {GREEN if result.get('pure_tests_discovered') else RED}{_bool_str(result.get('pure_tests_discovered'))}{RESET}")
    print(f"    Host acceptance tests separated:   {GREEN if result.get('host_acceptance_tests_separated') else RED}{_bool_str(result.get('host_acceptance_tests_separated'))}{RESET}")
    print()
    print(f"  {BOLD}Pure Tests — Isolation from Host State{RESET}")
    print(f"    HOME isolated (no ~/.openclaw):   {GREEN if result.get('pure_tests_home_isolated') else RED}{_bool_str(result.get('pure_tests_home_isolated'))}{RESET}")
    print(f"    No real ~/.openclaw access:       {GREEN if result.get('pure_tests_no_real_openclaw_access') else RED}{_bool_str(result.get('pure_tests_no_real_openclaw_access'))}{RESET}")
    print(f"    No H1 file access:                {GREEN if result.get('pure_tests_no_h1_file_access') else RED}{_bool_str(result.get('pure_tests_no_h1_file_access'))}{RESET}")
    print(f"    No IBKR Gateway required:         {GREEN if result.get('pure_tests_no_ibkr_gateway_required') else RED}{_bool_str(result.get('pure_tests_no_ibkr_gateway_required'))}{RESET}")
    print(f"    No systemd required:              {GREEN if result.get('pure_tests_no_systemd_required') else RED}{_bool_str(result.get('pure_tests_no_systemd_required'))}{RESET}")
    print()
    print(f"  {BOLD}CI Readiness{RESET}")
    print(f"    GitHub Actions workflow present:  {GREEN if result.get('github_actions_workflow_present') else RED}{_bool_str(result.get('github_actions_workflow_present'))}{RESET}")
    print(f"    CI install plan present:          {GREEN if result.get('ci_install_plan_present') else RED}{_bool_str(result.get('ci_install_plan_present'))}{RESET}")
    print(f"    CI command documented:            {GREEN if result.get('ci_command_documented') else RED}{_bool_str(result.get('ci_command_documented'))}{RESET}")
    print(f"    Fresh clone command documented:   {GREEN if result.get('fresh_clone_unit_command_documented') else RED}{_bool_str(result.get('fresh_clone_unit_command_documented'))}{RESET}")
    print()
    print(f"  {BOLD}Synthetic Fixture Tests (temp files only){RESET}")
    syn = result.get("synthetic_cases", {})
    for case_key, label in [
        ("home_isolation", "Home isolation"),
        ("no_h1_file_access", "No H1 file access"),
        ("acceptance_marker", "Acceptance marker"),
        ("ci_workflow", "CI workflow"),
        ("read_only_invariant", "Read-only invariant"),
    ]:
        case = syn.get(case_key, {})
        ok = case.get("passed", False)
        print(f"    {GREEN if ok else RED}{'✓' if ok else '✗'}{RESET} {label}")
    print()
    print(f"  {BOLD}Mutation Safety{RESET}")
    print(f"    No /order called:     {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    No /preflight:        {_bool_str(result.get('no_preflight_endpoint_called'))}")
    print(f"    No /approve:          {_bool_str(result.get('no_approval_endpoint_called'))}")
    print(f"    No /submit:           {_bool_str(result.get('no_submit_endpoint_called'))}")
    print(f"    No H1 token used:     {_bool_str(result.get('no_h1_token_used'))}")
    print(f"    No trade window:      {_bool_str(result.get('no_trade_window_helper_called'))}")
    print(f"    No broker mutation:   {_bool_str(result.get('no_broker_mutation'))}")
    print()
    if checkpoint_ok:
        print(f"  {GREEN}{BOLD}✓ PASS — Level 1 portable tests and CI readiness confirmed{RESET}")
    else:
        print(f"  {RED}{BOLD}✗ FAIL — Issues found (see suggested actions){RESET}")
        for a in result.get("suggested_operator_actions", []):
            print(f"    {RED}✗{RESET} {a}")
        print()
    eh = result.get("evidence_hash", "")
    if eh:
        print(f"  Evidence hash: {eh[:16]}...")
    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_fresh_clone_ci_workflow_checkpoint(result: dict) -> None:
    """Print Phase 16Z fresh-clone CI workflow checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE16Z_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE16Z_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Fresh-Clone CI Workflow Checkpoint (16Z){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Tag:           {g.get('tag', '?')}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Runtime State{RESET}")
    rt = result.get("runtime", {})
    print(f"    Connected:     {_bool_str(rt.get('connected'))}")
    print(f"    Mode:          {rt.get('mode', '?')}")
    print(f"    Read-only:     {_bool_str(rt.get('read_only'))}")
    print(f"    Allow orders:  {rt.get('allow_orders')}")
    print(f"    Endpoints OK:  {_bool_str(rt.get('endpoints_ok'))}")
    print(f"    Positions flat: {_bool_str(rt.get('positions_flat'))}")
    print()
    print(f"  {BOLD}Guard State & KPI{RESET}")
    print(f"    Guard clean:   {_bool_str(result.get('guard_state_clean', False))}")
    print(f"    KPI HOLD only system_locked: {_bool_str(result.get('kpi_hold_only_system_locked', False))}")
    print()
    print(f"  {BOLD}CI / Fresh-Clone Checks{RESET}")
    print(f"    GA workflow present:   {_bool_str(result.get('github_actions_workflow_present', False))}")
    print(f"    GA workflow valid:     {_bool_str(result.get('github_actions_workflow_valid', False))}")
    print(f"    CI command documented: {_bool_str(result.get('ci_command_documented', False))}")
    print(f"    CI command exits 0:    {_bool_str(result.get('ci_command_exits_zero', False))}")
    print(f"    Fresh-clone documented:{_bool_str(result.get('fresh_clone_unit_command_documented', False))}")
    print(f"    Fresh-clone exits 0:   {_bool_str(result.get('fresh_clone_unit_command_exits_zero', False))}")
    print(f"    Acceptance excluded:   {_bool_str(result.get('host_acceptance_tests_excluded_from_ci', False))}")
    print()
    print(f"  {BOLD}Pure Test Isolation{RESET}")
    print(f"    Home isolated:         {_bool_str(result.get('pure_tests_home_isolated', False))}")
    print(f"    No real ~/.openclaw:   {_bool_str(result.get('pure_tests_no_real_openclaw_access', False))}")
    print(f"    No H1 file access:     {_bool_str(result.get('pure_tests_no_h1_file_access', False))}")
    print(f"    No IBKR Gateway:       {_bool_str(result.get('pure_tests_no_ibkr_gateway_required', False))}")
    print(f"    No systemd:            {_bool_str(result.get('pure_tests_no_systemd_required', False))}")
    print()
    print(f"  {BOLD}Synthetic Cases{RESET}")
    print(f"    Workflow parse:        {_bool_str(result.get('synthetic_workflow_parse_case_passed', False))}")
    print(f"    Marker exclusion:      {_bool_str(result.get('synthetic_marker_exclusion_case_passed', False))}")
    print(f"    Temp HOME CI:          {_bool_str(result.get('synthetic_temp_home_ci_case_passed', False))}")
    print(f"    Fresh clone:           {_bool_str(result.get('synthetic_fresh_clone_case_passed', False))}")
    print(f"    No real openclaw:      {_bool_str(result.get('synthetic_no_real_openclaw_case_passed', False))}")
    print(f"    No H1 file access:     {_bool_str(result.get('synthetic_no_h1_file_access_case_passed', False))}")
    print(f"    Read-only invariant:   {_bool_str(result.get('synthetic_read_only_invariant_case_passed', False))}")
    print()
    print(f"  {BOLD}Mutation Safety{RESET}")
    print(f"    No /order called:      {_bool_str(result.get('no_order_endpoint_called', True))}")
    print(f"    No H1 token used:      {_bool_str(result.get('no_h1_token_used', True))}")
    print(f"    No trade window:       {_bool_str(result.get('no_trade_window_helper_called', True))}")
    print(f"    No broker mutation:    {_bool_str(result.get('no_broker_mutation', True))}")
    print(f"    Artifact created:      {_bool_str(result.get('artifact_created', False))}")
    ep = result.get("export_path")
    if ep:
        print(f"    Export: {ep}")
    print()


def _print_level1_strategy_v1_governance_checkpoint(result: dict) -> None:
    """Print Phase 17A strategy v1 governance checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE17A_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE17A_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Strategy v1 Governance Checkpoint (17A){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Tag:           {g.get('tag', '?')}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Runtime State{RESET}")
    rt = result.get("runtime", {})
    print(f"    Connected:     {_bool_str(rt.get('connected'))}")
    print(f"    Mode:          {rt.get('mode', '?')}")
    print(f"    Read-only:     {_bool_str(rt.get('read_only'))}")
    print(f"    Allow orders:  {rt.get('allow_orders')}")
    print(f"    Endpoints OK:  {_bool_str(rt.get('endpoints_ok'))}")
    print(f"    Positions flat: {_bool_str(rt.get('positions_flat'))}")
    print()
    print(f"  {BOLD}Guard State & KPI{RESET}")
    print(f"    Guard clean:   {_bool_str(result.get('guard_state_clean', False))}")
    print(f"    KPI HOLD only system_locked: {_bool_str(result.get('kpi_hold_only_system_locked', False))}")
    print()
    print(f"  {BOLD}Strategy Document Checks{RESET}")
    print(f"    Doc present:              {_bool_str(result.get('strategy_doc_present', False))}")
    print(f"    Version declared:         {_bool_str(result.get('strategy_version_declared', False))}")
    print(f"    Allowed instruments:      {_bool_str(result.get('allowed_instruments_declared', False))}")
    print(f"    Excluded instruments:     {_bool_str(result.get('excluded_instruments_declared', False))}")
    print(f"    Signal inputs:            {_bool_str(result.get('signal_inputs_declared', False))}")
    print(f"    Data quality rules:       {_bool_str(result.get('data_quality_rules_declared', False))}")
    print(f"    No-trade rules:           {_bool_str(result.get('no_trade_rules_declared', False))}")
    print(f"    Risk envelope:            {_bool_str(result.get('risk_envelope_declared', False))}")
    print(f"    Sizing rule:              {_bool_str(result.get('sizing_rule_declared', False))}")
    print(f"    Daily trade limit:        {_bool_str(result.get('daily_trade_limit_declared', False))}")
    print(f"    Daily loss limit:         {_bool_str(result.get('daily_loss_limit_declared', False))}")
    print(f"    Stop/exit policy:         {_bool_str(result.get('stop_exit_policy_declared', False))}")
    print(f"    Bracket requirement:      {_bool_str(result.get('broker_side_bracket_requirement_declared', False))}")
    print(f"    Review checklist:         {_bool_str(result.get('review_checklist_declared', False))}")
    print(f"    Anti-overfit checklist:   {_bool_str(result.get('anti_overfit_checklist_declared', False))}")
    print(f"    Advisory-only boundary:   {_bool_str(result.get('advisory_only_boundary_declared', False))}")
    print(f"    Broker execution boundary:{_bool_str(result.get('broker_execution_boundary_declared', False))}")
    print()
    print(f"  {BOLD}Synthetic Cases{RESET}")
    print(f"    Valid strategy doc:       {_bool_str(result.get('synthetic_valid_strategy_doc_case_passed', False))}")
    print(f"    Missing risk envelope:    {_bool_str(result.get('synthetic_missing_risk_envelope_case_passed', False))}")
    print(f"    Missing no-trade rules:   {_bool_str(result.get('synthetic_missing_no_trade_rules_case_passed', False))}")
    print(f"    Missing advisory boundary:{_bool_str(result.get('synthetic_missing_advisory_boundary_case_passed', False))}")
    print(f"    Missing anti-overfit:     {_bool_str(result.get('synthetic_missing_anti_overfit_case_passed', False))}")
    print(f"    Missing bracket req:      {_bool_str(result.get('synthetic_missing_bracket_requirement_case_passed', False))}")
    print(f"    Read-only invariant:      {_bool_str(result.get('synthetic_read_only_invariant_case_passed', False))}")
    print()
    print(f"  {BOLD}Mutation Safety{RESET}")
    print(f"    No /order called:      {_bool_str(result.get('no_order_endpoint_called', True))}")
    print(f"    No H1 token used:      {_bool_str(result.get('no_h1_token_used', True))}")
    print(f"    No trade window:       {_bool_str(result.get('no_trade_window_helper_called', True))}")
    print(f"    No broker mutation:    {_bool_str(result.get('no_broker_mutation', True))}")
    print(f"    Artifact created:      {_bool_str(result.get('artifact_created', False))}")
    ep = result.get("export_path")
    if ep:
        print(f"    Export: {ep}")
    print()


def _print_level1_strategy_v1_proposal_packet_schema_checkpoint(result: dict) -> None:
    """Print Phase 17B proposal packet schema checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE17B_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE17B_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Proposal Packet Schema Checkpoint (17B){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Tag:           {g.get('tag', '?')}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Runtime State{RESET}")
    rt = result.get("runtime", {})
    print(f"    Connected:     {_bool_str(rt.get('connected'))}")
    print(f"    Mode:          {rt.get('mode', '?')}")
    print(f"    Read-only:     {_bool_str(rt.get('read_only'))}")
    print(f"    Allow orders:  {rt.get('allow_orders')}")
    print(f"    Endpoints OK:  {_bool_str(rt.get('endpoints_ok'))}")
    print(f"    Positions flat: {_bool_str(rt.get('positions_flat'))}")
    print()
    print(f"  {BOLD}Guard State & KPI{RESET}")
    print(f"    Guard clean:   {_bool_str(result.get('guard_state_clean', False))}")
    print(f"    KPI HOLD only system_locked: {_bool_str(result.get('kpi_hold_only_system_locked', False))}")
    print()
    print(f"  {BOLD}Proposal Packet Schema Checks{RESET}")
    for key in ["proposal_packet_doc_present", "proposal_packet_schema_present",
                 "strategy_v1_reference_required", "proposal_id_required",
                 "timestamp_required", "instrument_required",
                 "allowed_instrument_check_required", "signal_thesis_required",
                 "signal_inputs_required", "data_quality_evidence_required",
                 "no_trade_checklist_required", "risk_envelope_check_required",
                 "sizing_calculation_required", "daily_trade_count_check_required",
                 "daily_loss_check_required", "stop_exit_plan_required",
                 "bracket_simulation_required", "advisory_only_boundary_required",
                 "broker_execution_boundary_required", "human_review_checklist_required",
                 "rejection_reasons_required", "evidence_hash_required"]:
        label = key.replace("_", " ").replace("required", "").strip()
        print(f"    {label:35s} {_bool_str(result.get(key, False))}")
    print()
    print(f"  {BOLD}Synthetic Cases{RESET}")
    for key, label in [
        ("synthetic_valid_packet_case_passed", "Valid packet"),
        ("synthetic_missing_strategy_reference_case_passed", "Missing strategy ref"),
        ("synthetic_disallowed_instrument_case_passed", "Disallowed instrument"),
        ("synthetic_missing_data_quality_case_passed", "Missing data quality"),
        ("synthetic_missing_no_trade_checklist_case_passed", "Missing no-trade checklist"),
        ("synthetic_missing_risk_sizing_case_passed", "Missing risk/sizing"),
        ("synthetic_missing_stop_bracket_case_passed", "Missing stop/bracket"),
        ("synthetic_missing_advisory_boundary_case_passed", "Missing advisory boundary"),
        ("synthetic_read_only_invariant_case_passed", "Read-only invariant"),
    ]:
        print(f"    {label:30s} {_bool_str(result.get(key, False))}")
    print()
    print(f"  {BOLD}Mutation Safety{RESET}")
    print(f"    No /order called:      {_bool_str(result.get('no_order_endpoint_called', True))}")
    print(f"    No H1 token used:      {_bool_str(result.get('no_h1_token_used', True))}")
    print(f"    No trade window:       {_bool_str(result.get('no_trade_window_helper_called', True))}")
    print(f"    No broker mutation:    {_bool_str(result.get('no_broker_mutation', True))}")
    print(f"    Artifact created:      {_bool_str(result.get('artifact_created', False))}")
    ep = result.get("export_path")
    if ep:
        print(f"    Export: {ep}")
    print()


def _print_level1_strategy_v1_dry_run_proposal_generation_checkpoint(result: dict) -> None:
    """Print Phase 17C dry-run proposal generation checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE17C_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE17C_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Dry-Run Proposal Generation Checkpoint (17C){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Tag:           {g.get('tag', '?')}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Runtime State{RESET}")
    rt = result.get("runtime", {})
    print(f"    Connected:     {_bool_str(rt.get('connected'))}")
    print(f"    Mode:          {rt.get('mode', '?')}")
    print(f"    Read-only:     {_bool_str(rt.get('read_only'))}")
    print(f"    Allow orders:  {rt.get('allow_orders')}")
    print(f"    Endpoints OK:  {_bool_str(rt.get('endpoints_ok'))}")
    print(f"    Positions flat: {_bool_str(rt.get('positions_flat'))}")
    print()
    print(f"  {BOLD}Guard State & KPI{RESET}")
    print(f"    Guard clean:   {_bool_str(result.get('guard_state_clean', False))}")
    print(f"    KPI HOLD only system_locked: {_bool_str(result.get('kpi_hold_only_system_locked', False))}")
    print()
    print(f"  {BOLD}Governance Docs{RESET}")
    print(f"    Strategy v1 doc:  {_bool_str(result.get('strategy_doc_present', False))}")
    print(f"    Proposal doc:     {_bool_str(result.get('proposal_doc_present', False))}")
    print(f"    Schema:           {_bool_str(result.get('schema_present', False))}")
    print()
    print(f"  {BOLD}Synthetic Fixture Results{RESET}")
    print(f"    Generate valid proposal:             {_bool_str(result.get('synthetic_proposal_generation_case_passed', False))}")
    print(f"    Proposal schema compliance:          {_bool_str(result.get('synthetic_proposal_schema_compliance_case_passed', False))}")
    print(f"    Advisory boundary enforced:          {_bool_str(result.get('synthetic_advisory_boundary_enforced_case_passed', False))}")
    print(f"    Disallowed instrument fails:         {_bool_str(result.get('synthetic_disallowed_instrument_generation_case_passed', False))}")
    print(f"    Rejection blocker deterministic:     {_bool_str(result.get('synthetic_rejection_blocker_deterministic_case_passed', False))}")
    print(f"    Read-only invariant:                 {_bool_str(result.get('synthetic_read_only_invariant_case_passed', False))}")
    print()
    print(f"  {BOLD}Canonical Proposal Evidence{RESET}")
    cp = result.get("canonical_proposal")
    if cp:
        print(f"    Symbol:          {cp.get('symbol', '?')}")
        print(f"    Side:            {cp.get('side', '?')}")
        print(f"    Quantity:        {cp.get('quantity', '?')}")
        print(f"    Entry price:     {cp.get('entry_price', '?')}")
        print(f"    Evidence hash:   {cp.get('evidence_hash', '?')[:16]}...")
        print(f"    Fields count:    {result.get('proposal_fields_count', 0)}")
        print(f"    Rejection count: {len(cp.get('rejection_reasons', []))}")
    else:
        print(f"    {RED}No canonical proposal generated{RESET}")
    print()
    print(f"  {BOLD}Safety Invariants{RESET}")
    print(f"    No /order called:           {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    No /order/preflight called:  {_bool_str(result.get('no_preflight_endpoint_called'))}")
    print(f"    No /order/approve called:    {_bool_str(result.get('no_approval_endpoint_called'))}")
    print(f"    No /order/submit called:     {_bool_str(result.get('no_submit_endpoint_called'))}")
    print(f"    No H1 token used:            {_bool_str(result.get('no_h1_token_used'))}")
    print(f"    No /connect called:          {_bool_str(result.get('no_connect_called'))}")
    print(f"    No broker mutation:          {_bool_str(result.get('no_broker_mutation'))}")
    print(f"    No trade-window called:      {_bool_str(result.get('no_trade_window_helper_called'))}")
    print()
    if not checkpoint_ok:
        actions = result.get("suggested_operator_actions", [])
        if actions:
            print(f"  {RED}Suggested operator actions:{RESET}")
            for a in actions:
                print(f"    - {a}")
            print()
    ep = result.get("export_path")
    if ep:
        print(f"    Export: {ep}")
    print()


def _print_level1_proposal_review_rejection_dossier_checkpoint(result: dict) -> None:
    """Print Phase 17D proposal review dossier checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE17D_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE17D_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Proposal Review and Rejection Dossier (17D){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Tag:           {g.get('tag', '?')}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Runtime State{RESET}")
    rt = result.get("runtime", {})
    print(f"    Connected:     {_bool_str(rt.get('connected'))}")
    print(f"    Mode:          {rt.get('mode', '?')}")
    print(f"    Read-only:     {_bool_str(rt.get('read_only'))}")
    print(f"    Allow orders:  {rt.get('allow_orders')}")
    print(f"    Endpoints OK:  {_bool_str(rt.get('endpoints_ok'))}")
    print(f"    Positions flat: {_bool_str(rt.get('positions_flat'))}")
    print()
    print(f"  {BOLD}Guard State & KPI{RESET}")
    print(f"    Guard clean:   {_bool_str(result.get('guard_state_clean', False))}")
    print(f"    KPI HOLD only system_locked: {_bool_str(result.get('kpi_hold_only_system_locked', False))}")
    print()
    print(f"  {BOLD}Governance Docs{RESET}")
    print(f"    Strategy v1 doc:  {_bool_str(result.get('strategy_doc_present', False))}")
    print(f"    Proposal doc:     {_bool_str(result.get('proposal_doc_present', False))}")
    print(f"    Schema:           {_bool_str(result.get('schema_present', False))}")
    print()
    print(f"  {BOLD}Synthetic Fixture Results{RESET}")
    print(f"    Valid proposal → REVIEWABLE:           {_bool_str(result.get('reviewable_case_passed', False))}")
    print(f"    Invalid schema → REJECTED:             {_bool_str(result.get('invalid_schema_rejected_case_passed', False))}")
    print(f"    Disallowed instrument → REJECTED:      {_bool_str(result.get('disallowed_instrument_rejected_case_passed', False))}")
    print(f"    Data quality FAIL → REJECTED:          {_bool_str(result.get('data_quality_rejected_case_passed', False))}")
    print(f"    No-trade gate FAIL → REJECTED:         {_bool_str(result.get('no_trade_gate_rejected_case_passed', False))}")
    print(f"    Missing evidence hash → REJECTED:      {_bool_str(result.get('missing_evidence_hash_rejected_case_passed', False))}")
    print(f"    Read-only invariant:                   {_bool_str(result.get('read_only_invariant_case_passed', False))}")
    print(f"    Deterministic:                         {_bool_str(result.get('deterministic_case_passed', False))}")
    print(f"    Fresh-clone execution:                 {_bool_str(result.get('fresh_clone_case_passed', False))}")
    print()
    print(f"  {BOLD}Canonical Dossier Evidence{RESET}")
    cd = result.get("canonical_dossier")
    if cd:
        print(f"    Decision state:  {cd.get('human_decision_state', '?')}")
        print(f"    Rejection count: {cd.get('rejection_count', 0)}")
        print(f"    Dossier hash:    {cd.get('evidence_hash', '?')[:16]}...")
        pi = cd.get("proposal_identity", {})
        print(f"    Proposal:        {pi.get('proposal_id', '?')} ({pi.get('symbol', '?')} {pi.get('side', '?')})")
    else:
        print(f"    {RED}No canonical dossier generated{RESET}")
    print()
    print(f"  {BOLD}Safety Invariants{RESET}")
    print(f"    No /order called:           {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    No /order/preflight called:  {_bool_str(result.get('no_preflight_endpoint_called'))}")
    print(f"    No /order/approve called:    {_bool_str(result.get('no_approval_endpoint_called'))}")
    print(f"    No /order/submit called:     {_bool_str(result.get('no_submit_endpoint_called'))}")
    print(f"    No H1 token used:            {_bool_str(result.get('no_h1_token_used'))}")
    print(f"    No /connect called:          {_bool_str(result.get('no_connect_called'))}")
    print(f"    No broker mutation:          {_bool_str(result.get('no_broker_mutation'))}")
    print(f"    No trade-window called:      {_bool_str(result.get('no_trade_window_helper_called'))}")
    print()
    if not checkpoint_ok:
        actions = result.get("suggested_operator_actions", [])
        if actions:
            print(f"  {RED}Suggested operator actions:{RESET}")
            for a in actions:
                print(f"    - {a}")
            print()
    ep = result.get("export_path")
    if ep:
        print(f"    Export: {ep}")
    print()


def _print_level1_human_review_decision_record_checkpoint(result: dict) -> None:
    """Print Phase 17E human review decision record checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE17E_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE17E_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Human Review Decision Record Checkpoint (17E){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Tag:           {g.get('tag', '?')}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Runtime State{RESET}")
    rt = result.get("runtime", {})
    print(f"    Connected:     {_bool_str(rt.get('connected'))}")
    print(f"    Mode:          {rt.get('mode', '?')}")
    print(f"    Read-only:     {_bool_str(rt.get('read_only'))}")
    print(f"    Allow orders:  {rt.get('allow_orders')}")
    print(f"    Endpoints OK:  {_bool_str(rt.get('endpoints_ok'))}")
    print(f"    Positions flat: {_bool_str(rt.get('positions_flat'))}")
    print()
    print(f"  {BOLD}Guard State & KPI{RESET}")
    print(f"    Guard clean:   {_bool_str(result.get('guard_state_clean', False))}")
    print(f"    KPI HOLD only system_locked: {_bool_str(result.get('kpi_hold_only_system_locked', False))}")
    print()
    print(f"  {BOLD}Synthetic Fixture Results{RESET}")
    print(f"    Accept → ACCEPTED_FOR_PLANNING:        {_bool_str(result.get('accept_for_planning_case_passed', False))}")
    print(f"    Rejected dossier blocked from accept:   {_bool_str(result.get('rejected_dossier_accept_blocked_case_passed', False))}")
    print(f"    Missing decision → PENDING_REVIEW:      {_bool_str(result.get('missing_decision_pending_case_passed', False))}")
    print(f"    Explicit reject → REJECTED:             {_bool_str(result.get('explicit_reject_case_passed', False))}")
    print(f"    Explicit defer → DEFERRED:              {_bool_str(result.get('explicit_defer_case_passed', False))}")
    print(f"    Missing reviewer → fail closed:         {_bool_str(result.get('missing_reviewer_fail_closed_case_passed', False))}")
    print(f"    Missing reason → fail closed:           {_bool_str(result.get('missing_reason_fail_closed_case_passed', False))}")
    print(f"    Proposal hash mismatch → fail closed:   {_bool_str(result.get('proposal_hash_mismatch_case_passed', False))}")
    print(f"    Dossier hash mismatch → fail closed:    {_bool_str(result.get('dossier_hash_mismatch_case_passed', False))}")
    print(f"    Accepted → non-executable:              {_bool_str(result.get('accepted_non_executable_case_passed', False))}")
    print(f"    Deterministic:                          {_bool_str(result.get('deterministic_case_passed', False))}")
    print(f"    Read-only invariant:                    {_bool_str(result.get('read_only_invariant_case_passed', False))}")
    print(f"    Fresh-clone execution:                  {_bool_str(result.get('fresh_clone_case_passed', False))}")
    print()
    print(f"  {BOLD}Canonical Decision Record{RESET}")
    cr = result.get("canonical_decision_record")
    if cr:
        print(f"    Decision:       {cr.get('decision', '?')}")
        print(f"    Executable:     {cr.get('executable', '?')}")
        print(f"    Broker auth:    {cr.get('broker_authorized', '?')}")
        print(f"    Scope:          {cr.get('acceptance_scope', '?')}")
        print(f"    Record hash:    {cr.get('deterministic_record_hash', '?')[:16]}...")
    else:
        print(f"    {RED}No canonical decision record generated{RESET}")
    print()
    print(f"  {BOLD}Safety Invariants{RESET}")
    print(f"    No /order called:           {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    No /order/preflight called:  {_bool_str(result.get('no_preflight_endpoint_called'))}")
    print(f"    No /order/approve called:    {_bool_str(result.get('no_approval_endpoint_called'))}")
    print(f"    No /order/submit called:     {_bool_str(result.get('no_submit_endpoint_called'))}")
    print(f"    No H1 token used:            {_bool_str(result.get('no_h1_token_used'))}")
    print(f"    No /connect called:          {_bool_str(result.get('no_connect_called'))}")
    print(f"    No broker mutation:          {_bool_str(result.get('no_broker_mutation'))}")
    print(f"    No trade-window called:      {_bool_str(result.get('no_trade_window_helper_called'))}")
    print()
    if not checkpoint_ok:
        actions = result.get("suggested_operator_actions", [])
        if actions:
            print(f"  {RED}Suggested operator actions:{RESET}")
            for a in actions:
                print(f"    - {a}")
            print()
    ep = result.get("export_path")
    if ep:
        print(f"    Export: {ep}")
    print()


def _print_level1_planning_only_order_plan_draft_checkpoint(result: dict) -> None:
    """Print Phase 17F planning-only order-plan draft checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE17F_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE17F_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Planning-Only Order Plan Draft Checkpoint (17F){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Tag:           {g.get('tag', '?')}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Runtime State{RESET}")
    rt = result.get("runtime", {})
    print(f"    Connected:     {_bool_str(rt.get('connected'))}")
    print(f"    Mode:          {rt.get('mode', '?')}")
    print(f"    Read-only:     {_bool_str(rt.get('read_only'))}")
    print(f"    Allow orders:  {rt.get('allow_orders')}")
    print(f"    Endpoints OK:  {_bool_str(rt.get('endpoints_ok'))}")
    print(f"    Positions flat: {_bool_str(rt.get('positions_flat'))}")
    print()
    print(f"  {BOLD}Guard State & KPI{RESET}")
    print(f"    Guard clean:   {_bool_str(result.get('guard_state_clean', False))}")
    print(f"    KPI HOLD only system_locked: {_bool_str(result.get('kpi_hold_only_system_locked', False))}")
    print()
    print(f"  {BOLD}Synthetic Fixture Results{RESET}")
    print(f"    Planning draft ready (ACC → READY):      {_bool_str(result.get('planning_draft_ready_case_passed', False))}")
    print(f"    PENDING_REVIEW → BLOCKED:                 {_bool_str(result.get('pending_review_blocked_case_passed', False))}")
    print(f"    REJECTED → BLOCKED:                       {_bool_str(result.get('rejected_blocked_case_passed', False))}")
    print(f"    Ready plan executable=false:              {_bool_str(result.get('executable_false_case_passed', False))}")
    print(f"    Ready plan broker_authorized=false:       {_bool_str(result.get('broker_authorized_false_case_passed', False))}")
    print(f"    Ready plan preflight_authorized=false:    {_bool_str(result.get('preflight_authorized_false_case_passed', False))}")
    print(f"    Ready plan approval_authorized=false:     {_bool_str(result.get('approval_authorized_false_case_passed', False))}")
    print(f"    Ready plan submission_authorized=false:   {_bool_str(result.get('submission_authorized_false_case_passed', False))}")
    print(f"    Hash mismatch → BLOCKED:                  {_bool_str(result.get('hash_mismatch_blocked_case_passed', False))}")
    print(f"    Disallowed instrument → BLOCKED:          {_bool_str(result.get('disallowed_instrument_blocked_case_passed', False))}")
    print(f"    Deterministic:                            {_bool_str(result.get('deterministic_case_passed', False))}")
    print(f"    Read-only invariant:                      {_bool_str(result.get('read_only_invariant_case_passed', False))}")
    print(f"    Fresh-clone execution:                    {_bool_str(result.get('fresh_clone_case_passed', False))}")
    print()
    print(f"  {BOLD}Canonical Order-Plan Draft{RESET}")
    cp = result.get("canonical_order_plan_draft")
    if cp:
        print(f"    Plan state:        {cp.get('plan_state', '?')}")
        print(f"    Plan ID:           {cp.get('plan_id', '?')}")
        print(f"    Symbol/Side:       {cp.get('symbol', '?')} / {cp.get('side', '?')}")
        print(f"    Quantity:          {cp.get('quantity', '?')}")
        print(f"    Executable:        {cp.get('executable', '?')}")
        print(f"    Broker auth:       {cp.get('broker_authorized', '?')}")
        print(f"    Scope:             {cp.get('planning_scope', '?')}")
        print(f"    Plan hash:         {cp.get('deterministic_plan_hash', '?')[:16]}...")
    else:
        print(f"    {RED}No canonical order-plan draft generated{RESET}")
    print()
    print(f"  {BOLD}Safety Invariants{RESET}")
    print(f"    No /order called:           {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    No /order/preflight called:  {_bool_str(result.get('no_preflight_endpoint_called'))}")
    print(f"    No /order/approve called:    {_bool_str(result.get('no_approval_endpoint_called'))}")
    print(f"    No /order/submit called:     {_bool_str(result.get('no_submit_endpoint_called'))}")
    print(f"    No H1 token used:            {_bool_str(result.get('no_h1_token_used'))}")
    print(f"    No /connect called:          {_bool_str(result.get('no_connect_called'))}")
    print(f"    No broker mutation:          {_bool_str(result.get('no_broker_mutation'))}")
    print(f"    No trade-window called:      {_bool_str(result.get('no_trade_window_helper_called'))}")
    print()
    if not checkpoint_ok:
        actions = result.get("suggested_operator_actions", [])
        if actions:
            print(f"  {RED}Suggested operator actions:{RESET}")
            for a in actions:
                print(f"    - {a}")
            print()
    ep = result.get("export_path")
    if ep:
        print(f"    Export: {ep}")
    print()


def _print_level1_planning_only_preflight_simulation_dossier_checkpoint(result: dict) -> None:
    """Print Phase 17G planning-only preflight simulation dossier checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE17G_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE17G_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Planning-Only Preflight Simulation Dossier (17G){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Synthetic Fixture Results{RESET}")
    print(f"    Simulation ready (plan → SIM):          {_bool_str(result.get('simulation_ready_case_passed', False))}")
    print(f"    BLOCKED plan → BLOCKED:                 {_bool_str(result.get('blocked_plan_blocked_case_passed', False))}")
    print(f"    SIM executable=false:                    {_bool_str(result.get('executable_false_case_passed', False))}")
    print(f"    SIM broker_authorized=false:            {_bool_str(result.get('broker_authorized_false_case_passed', False))}")
    print(f"    SIM preflight_authorized=false:         {_bool_str(result.get('preflight_authorized_false_case_passed', False))}")
    print(f"    SIM approval_authorized=false:          {_bool_str(result.get('approval_authorized_false_case_passed', False))}")
    print(f"    SIM submission_authorized=false:        {_bool_str(result.get('submission_authorized_false_case_passed', False))}")
    print(f"    SIM broker_preflight_called=false:      {_bool_str(result.get('broker_preflight_called_false_case_passed', False))}")
    print(f"    Hash mismatch → BLOCKED:                 {_bool_str(result.get('hash_mismatch_blocked_case_passed', False))}")
    print(f"    Disallowed instrument → BLOCKED:         {_bool_str(result.get('disallowed_instrument_blocked_case_passed', False))}")
    print(f"    Invalid side → BLOCKED:                  {_bool_str(result.get('invalid_side_blocked_case_passed', False))}")
    print(f"    Invalid quantity → BLOCKED:              {_bool_str(result.get('invalid_quantity_blocked_case_passed', False))}")
    print(f"    Stop above entry → BLOCKED:              {_bool_str(result.get('stop_below_entry_blocked_case_passed', False))}")
    print(f"    Stop quantity mismatch → BLOCKED:        {_bool_str(result.get('stop_quantity_mismatch_blocked_case_passed', False))}")
    print(f"    Data quality fail → BLOCKED:             {_bool_str(result.get('data_quality_fail_blocked_case_passed', False))}")
    print(f"    No-trade fail → BLOCKED:                 {_bool_str(result.get('no_trade_fail_blocked_case_passed', False))}")
    print(f"    Deterministic:                           {_bool_str(result.get('deterministic_case_passed', False))}")
    print(f"    Read-only invariant:                     {_bool_str(result.get('read_only_invariant_case_passed', False))}")
    print(f"    Fresh-clone execution:                   {_bool_str(result.get('fresh_clone_case_passed', False))}")
    print(f"    Full chain non-executable:               {_bool_str(result.get('full_chain_case_passed', False))}")
    print()
    print(f"  {BOLD}Canonical Simulation Dossier{RESET}")
    cs = result.get("canonical_simulation_dossier")
    if cs:
        print(f"    Simulation state:  {cs.get('simulation_state', '?')}")
        print(f"    Symbol/Side:       {cs.get('symbol', '?')} / {cs.get('side', '?')}")
        print(f"    Quantity:          {cs.get('quantity', '?')}")
        print(f"    Executable:        {cs.get('executable', '?')}")
        print(f"    Preflight called:  {cs.get('broker_preflight_called', '?')}")
        print(f"    Sim hash:          {cs.get('deterministic_simulation_hash', '?')[:16]}...")
    else:
        print(f"    {RED}No canonical simulation dossier generated{RESET}")
    print()
    print(f"  {BOLD}Safety Invariants{RESET}")
    print(f"    No /order called:           {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    No /order/preflight called:  {_bool_str(result.get('no_preflight_endpoint_called'))}")
    print(f"    No /order/approve called:    {_bool_str(result.get('no_approval_endpoint_called'))}")
    print(f"    No /order/submit called:     {_bool_str(result.get('no_submit_endpoint_called'))}")
    print(f"    No H1 token used:            {_bool_str(result.get('no_h1_token_used'))}")
    print(f"    No /connect called:          {_bool_str(result.get('no_connect_called'))}")
    print(f"    No broker mutation:          {_bool_str(result.get('no_broker_mutation'))}")
    print()
    if not checkpoint_ok:
        actions = result.get("suggested_operator_actions", [])
        if actions:
            print(f"  {RED}Suggested operator actions:{RESET}")
            for a in actions:
                print(f"    - {a}")
            print()
    ep = result.get("export_path")
    if ep:
        print(f"    Export: {ep}")
    print()


def _print_level1_human_simulation_review_decision_record_checkpoint(result: dict) -> None:
    """Print Phase 17H human simulation review decision record checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE17H_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE17H_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Human Simulation Review Decision Record (17H){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Synthetic Fixture Results{RESET}")
    print(f"    Missing decision → PENDING:               {_bool_str(result.get('missing_decision_pending_case_passed', False))}")
    print(f"    ACCEPT → ACCEPTED_FOR_CANDIDATE_PKG:      {_bool_str(result.get('accept_case_passed', False))}")
    print(f"    Explicit REJECT:                           {_bool_str(result.get('explicit_reject_case_passed', False))}")
    print(f"    Explicit DEFER:                            {_bool_str(result.get('explicit_defer_case_passed', False))}")
    print(f"    Missing reason fail-closed:                {_bool_str(result.get('missing_reason_fail_closed_case_passed', False))}")
    print(f"    Missing reviewer fail-closed:              {_bool_str(result.get('missing_reviewer_fail_closed_case_passed', False))}")
    print(f"    BLOCKED sim accept blocked:                {_bool_str(result.get('blocked_sim_accept_blocked_case_passed', False))}")
    print(f"    Non-ready sim accept blocked:              {_bool_str(result.get('non_ready_sim_accept_blocked_case_passed', False))}")
    print(f"    Failed gate accept blocked:                {_bool_str(result.get('failed_gate_accept_blocked_case_passed', False))}")
    print(f"    Preflight=true accept blocked:             {_bool_str(result.get('broker_preflight_called_accept_blocked_case_passed', False))}")
    print(f"    Executable=true accept blocked:            {_bool_str(result.get('executable_true_accept_blocked_case_passed', False))}")
    print(f"    Broker auth=true accept blocked:           {_bool_str(result.get('broker_authorized_true_accept_blocked_case_passed', False))}")
    print(f"    Missing proposal hash → BLOCKED:           {_bool_str(result.get('missing_proposal_hash_blocked_case_passed', False))}")
    print(f"    Missing dossier hash → BLOCKED:             {_bool_str(result.get('missing_dossier_hash_blocked_case_passed', False))}")
    print(f"    Missing decision hash → BLOCKED:           {_bool_str(result.get('missing_decision_hash_blocked_case_passed', False))}")
    print(f"    Missing order-plan hash → BLOCKED:         {_bool_str(result.get('missing_order_plan_hash_blocked_case_passed', False))}")
    print(f"    Missing sim hash → BLOCKED:                {_bool_str(result.get('missing_simulation_hash_blocked_case_passed', False))}")
    print(f"    Proposal hash mismatch → BLOCKED:          {_bool_str(result.get('proposal_hash_mismatch_blocked_case_passed', False))}")
    print(f"    Dossier hash mismatch → BLOCKED:           {_bool_str(result.get('dossier_hash_mismatch_blocked_case_passed', False))}")
    print(f"    Decision hash mismatch → BLOCKED:          {_bool_str(result.get('decision_hash_mismatch_blocked_case_passed', False))}")
    print(f"    Order-plan hash mismatch → BLOCKED:        {_bool_str(result.get('order_plan_hash_mismatch_blocked_case_passed', False))}")
    print(f"    Tampered evidence ref → BLOCKED:           {_bool_str(result.get('tampered_evidence_ref_blocked_case_passed', False))}")
    print(f"    Blocker ordering deterministic:            {_bool_str(result.get('blocker_ordering_case_passed', False))}")
    print(f"    Deterministic review hash:                 {_bool_str(result.get('deterministic_case_passed', False))}")
    print(f"    No forbidden endpoints:                    {_bool_str(result.get('no_forbidden_endpoints_case_passed', False))}")
    print(f"    No broker identifiers:                     {_bool_str(result.get('no_broker_identifiers_case_passed', False))}")
    print(f"    Read-only invariant:                       {_bool_str(result.get('read_only_invariant_case_passed', False))}")
    print(f"    Fresh-clone execution:                     {_bool_str(result.get('fresh_clone_case_passed', False))}")
    print(f"    Full chain non-executable:                 {_bool_str(result.get('full_chain_case_passed', False))}")
    print()
    print(f"  {BOLD}Canonical Review Record{RESET}")
    cr = result.get("canonical_review_record")
    if cr:
        print(f"    Review state:                 {cr.get('review_state', '?')}")
        print(f"    Symbol/Side:                  {cr.get('symbol', '?')} / {cr.get('side', '?')}")
        print(f"    Acceptance scope:             {cr.get('acceptance_scope', '?')}")
        print(f"    Candidate pkg permitted:      {cr.get('candidate_packaging_permitted', '?')}")
        print(f"    Executable:                   {cr.get('executable', '?')}")
        print(f"    Preflight called:             {cr.get('broker_preflight_called', '?')}")
        print(f"    Review hash:                  {cr.get('deterministic_review_hash', '?')[:16]}...")
    else:
        print(f"    {RED}No canonical review record generated{RESET}")
    print()
    print(f"  {BOLD}Safety Invariants{RESET}")
    print(f"    No /order called:            {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    No /order/preflight called:   {_bool_str(result.get('no_preflight_endpoint_called'))}")
    print(f"    No /order/approve called:     {_bool_str(result.get('no_approval_endpoint_called'))}")
    print(f"    No /order/submit called:      {_bool_str(result.get('no_submit_endpoint_called'))}")
    print(f"    No H1 token used:             {_bool_str(result.get('no_h1_token_used'))}")
    print(f"    No /connect called:           {_bool_str(result.get('no_connect_called'))}")
    print(f"    No broker mutation:           {_bool_str(result.get('no_broker_mutation'))}")
    print()
    if not checkpoint_ok:
        actions = result.get("suggested_operator_actions", [])
        if actions:
            print(f"  {RED}Suggested operator actions:{RESET}")
            for a in actions:
                print(f"    - {a}")
            print()
    ep = result.get("export_path")
    if ep:
        print(f"    Export: {ep}")
    print()


def _print_level1_planning_only_candidate_package_checkpoint(result: dict) -> None:
    """Print Phase 17I planning-only candidate package checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE17I_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE17I_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Planning-Only Candidate Package (17I){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Synthetic Fixture Results{RESET}")
    print(f"    Ready package:                              {_bool_str(result.get('ready_package_case_passed', False))}")
    print(f"    Missing review → BLOCKED:                  {_bool_str(result.get('missing_review_decision_case_passed', False))}")
    print(f"    REJECTED review → BLOCKED:                  {_bool_str(result.get('rejected_review_blocked_case_passed', False))}")
    print(f"    DEFERRED review → BLOCKED:                  {_bool_str(result.get('deferred_review_blocked_case_passed', False))}")
    print(f"    BLOCKED review → BLOCKED:                   {_bool_str(result.get('blocked_review_blocked_case_passed', False))}")
    print(f"    Wrong scope → BLOCKED:                      {_bool_str(result.get('scope_not_candidate_case_passed', False))}")
    print(f"    executable=true → BLOCKED:                  {_bool_str(result.get('executable_true_blocked_case_passed', False))}")
    print(f"    broker_authorized=true → BLOCKED:           {_bool_str(result.get('broker_authorized_true_blocked_case_passed', False))}")
    print(f"    broker_preflight_called=true → BLOCKED:      {_bool_str(result.get('broker_preflight_called_true_blocked_case_passed', False))}")
    print(f"    Review has blockers → BLOCKED:               {_bool_str(result.get('review_has_blockers_case_passed', False))}")
    print(f"    Missing proposal hash → BLOCKED:             {_bool_str(result.get('missing_proposal_hash_case_passed', False))}")
    print(f"    Proposal hash mismatch → BLOCKED:            {_bool_str(result.get('proposal_hash_mismatch_case_passed', False))}")
    print(f"    Tampered evidence ref → BLOCKED:             {_bool_str(result.get('tampered_evidence_ref_case_passed', False))}")
    print(f"    Disallowed instrument → BLOCKED:             {_bool_str(result.get('disallowed_instrument_case_passed', False))}")
    print(f"    Invalid side → BLOCKED:                     {_bool_str(result.get('invalid_side_case_passed', False))}")
    print(f"    Invalid quantity → BLOCKED:                 {_bool_str(result.get('invalid_quantity_case_passed', False))}")
    print(f"    Missing stop → BLOCKED:                     {_bool_str(result.get('missing_stop_case_passed', False))}")
    print(f"    Stop qty mismatch → BLOCKED:                {_bool_str(result.get('stop_quantity_mismatch_case_passed', False))}")
    print(f"    Data quality fail → BLOCKED:                {_bool_str(result.get('data_quality_fail_case_passed', False))}")
    print(f"    No-trade fail → BLOCKED:                     {_bool_str(result.get('no_trade_fail_case_passed', False))}")
    print(f"    Gate fail → BLOCKED:                        {_bool_str(result.get('gate_fail_case_passed', False))}")
    print(f"    Deterministic:                               {_bool_str(result.get('deterministic_case_passed', False))}")
    print(f"    No forbidden endpoints:                      {_bool_str(result.get('no_forbidden_endpoints_case_passed', False))}")
    print(f"    No broker identifiers:                       {_bool_str(result.get('no_broker_identifiers_case_passed', False))}")
    print(f"    Read-only invariant:                         {_bool_str(result.get('read_only_invariant_case_passed', False))}")
    print(f"    Fresh-clone execution:                       {_bool_str(result.get('fresh_clone_case_passed', False))}")
    print(f"    Full chain non-executable:                   {_bool_str(result.get('full_chain_case_passed', False))}")
    print()
    print(f"  {BOLD}Canonical Candidate Package{RESET}")
    cp = result.get("canonical_candidate_package")
    if cp:
        print(f"    Package state:                {cp.get('package_state', '?')}")
        print(f"    Symbol/Side:                  {cp.get('symbol', '?')} / {cp.get('side', '?')}")
        print(f"    Candidate pkg permitted:      {cp.get('candidate_packaging_permitted', '?')}")
        print(f"    Actual preflight completed:   {cp.get('actual_preflight_completed', '?')}")
        print(f"    Actual order created:         {cp.get('actual_order_created', '?')}")
        print(f"    Package hash:                 {cp.get('deterministic_candidate_package_hash', '?')[:16]}...")
    else:
        print(f"    {RED}No canonical candidate package generated{RESET}")
    print()
    print(f"  {BOLD}Safety Invariants{RESET}")
    print(f"    No /order called:            {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    No /connect called:           {_bool_str(result.get('no_connect_called'))}")
    print(f"    No broker mutation:           {_bool_str(result.get('no_broker_mutation'))}")
    print()
    if not checkpoint_ok:
        actions = result.get("suggested_operator_actions", [])
        if actions:
            print(f"  {RED}Suggested operator actions:{RESET}")
            for a in actions:
                print(f"    - {a}")
            print()
    ep = result.get("export_path")
    if ep:
        print(f"    Export: {ep}")
    print()


def _print_level1_execution_gate_negative_control_drill(result: dict) -> None:
    """Print Phase 16O negative-control drill in human-readable format."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, YELLOW, _PHASE16O_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    drill_ok = result.get("diagnosis") == _PHASE16O_DIAGNOSIS["ready"]
    diag_color = GREEN if drill_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Level 1 Execution Gate Negative-Control Drill (16O){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Drill ID:              {result.get('drill_id', '?')}")
    print(f"  Timestamp:             {result.get('timestamp', '?')}")
    print(f"  Diagnosis:             {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:              {sev_color}{sev}{RESET}")
    print(f"  Execution blocked:     {GREEN if result.get('execution_blocked_as_expected') else RED}{_bool_str(result.get('execution_blocked_as_expected'))}{RESET}")
    print()

    # Execution gate negative controls
    egnc = result.get("execution_gate_negative_controls", {})
    if egnc:
        print(f"  {BOLD}Execution Gate Negative Controls{RESET}")
        print(f"    Status:                {GREEN if egnc.get('status') == 'blocked_as_expected' else RED}{egnc.get('status', '?')}{RESET}")
        print(f"    Negative-control only: {_bool_str(egnc.get('negative_control_only'))}")
        print(f"    Exec authorized now:   {_bool_str(egnc.get('execution_authorized_now'))}")
        print(f"    Controls: {egnc.get('controls_passed_count', 0)}P / {egnc.get('controls_failed_count', 0)}F / {egnc.get('controls_count', 0)}T")
        print(f"    Future path:           {egnc.get('future_required_path', '?')}")
        print()

    # Gate matrix
    gm = result.get("gate_matrix", {})
    if gm:
        print(f"  {BOLD}Gate Matrix{RESET}")
        print(f"    Level1 exec allowed:        {_bool_str(gm.get('level1_execution_allowed'))}")
        print(f"    Chain sufficient for exec:  {_bool_str(gm.get('readiness_chain_sufficient_for_execution'))}")
        print(f"    Orders enabled:             {_bool_str(gm.get('orders_enabled'))}")
        print(f"    System locked:              {_bool_str(gm.get('system_locked'))}")
        print(f"    Order window open:          {_bool_str(gm.get('order_window_open'))}")
        print(f"    H1 available:               {_bool_str(gm.get('h1_available_to_drill'))}")
        print()

    # Negative-control plan
    ncp = result.get("negative_control_plan", {})
    if ncp:
        print(f"  {BOLD}Negative-Control Plan{RESET}")
        print(f"    Source:              {ncp.get('source', '?')}")
        print(f"    Candidates:          {ncp.get('demo_candidates_requested', 0)}")
        print(f"    Intents count:       {ncp.get('execution_intents_count', 0)}")
        print(f"    All blocked:         {GREEN if ncp.get('all_intents_blocked') else RED}{_bool_str(ncp.get('all_intents_blocked'))}{RESET}")
        print()

        intents = ncp.get("execution_intents", [])
        if intents:
            print(f"  {BOLD}Execution Intents (all locally blocked){RESET}")
            for intent in intents:
                print(f"    {intent.get('intent_id', '?')}")
                print(f"      {intent.get('side', intent.get('action', '?'))} {intent.get('quantity', '?')}x "
                      f"{intent.get('symbol', '?')} ({intent.get('order_type', '?')}) "
                      f"TIF={intent.get('time_in_force', '?')}")
                print(f"      simulated_only={_bool_str(intent.get('simulated_intent_only'))}  "
                      f"expected={intent.get('expected_result', '?')}  "
                      f"blocked={_bool_str(intent.get('blocked'))}")
                reasons = intent.get("blocking_reasons", [])
                if reasons:
                    print(f"      Reasons ({len(reasons)}): {', '.join(reasons[:3])}")
            print()

    # Negative-control checklist
    ncl = result.get("negative_control_checklist", [])
    if ncl:
        print(f"  {BOLD}Negative-Control Checklist{RESET}")
        pc = sum(1 for c in ncl if c.get("status") == "PASS")
        fc = sum(1 for c in ncl if c.get("status") == "FAIL")
        sc = sum(1 for c in ncl if c.get("status") == "SKIP")
        print(f"    Pass: {pc}  Fail: {fc}  Skip: {sc}  Total: {len(ncl)}")
        for c in ncl[:5]:
            cs = c.get("status", "?")
            c_color = GREEN if cs == "PASS" else (RED if cs == "FAIL" else YELLOW)
            print(f"    {c_color}{cs:<6}{RESET} {c.get('check', '?')}")
        if len(ncl) > 5:
            print(f"    ... and {len(ncl)-5} more checks")
        print()

    # Workflow summary
    wf = result.get("workflow_summary", {})
    if wf:
        print(f"  {BOLD}Workflow Summary{RESET}")
        print(f"    Gate NC ready:              {_bool_str(wf.get('execution_gate_negative_control_ready'))}")
        print(f"    Controls created:           {_bool_str(wf.get('negative_controls_created'))}")
        print(f"    All intents blocked:        {_bool_str(wf.get('all_execution_intents_blocked'))}")
        print(f"    Chain not sufficient:       {_bool_str(wf.get('readiness_chain_not_sufficient_for_execution'))}")
        print(f"    Checklist complete:         {_bool_str(wf.get('checklist_complete'))}")
        print()

    print(f"  {BOLD}Non-Mutation Guarantees{RESET}")
    print(f"    no_broker_mutation:            {_bool_str(result.get('no_broker_mutation'))}")
    print(f"    no_order_endpoint_called:      {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    no_h1_seen:                    {_bool_str(result.get('no_h1_seen'))}")
    print(f"    execution_authorized_now:      {_bool_str(result.get('execution_authorized_now'))}")
    print()

    eh = result.get("evidence_hash", "")
    if eh:
        print(f"  Evidence hash: {eh[:16]}...")
    ep = result.get("export_path")
    if ep:
        print(f"  Export: {ep}")
    print()


def _print_level1_human_candidate_package_review_decision_record_checkpoint(result: dict) -> None:
    """Print Phase 17J human candidate-package review decision checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE17J_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE17J_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  L1 Human Candidate Pkg Review Decision Rec (17J){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Synthetic Fixture Results{RESET}")
    print(f"    Ready ACCEPT:                               {_bool_str(result.get('ready_accept_case_passed', False))}")
    print(f"    Missing decision → PENDING_REVIEW:           {_bool_str(result.get('missing_decision_case_passed', False))}")
    print(f"    REJECT → REJECTED:                          {_bool_str(result.get('rejected_decision_case_passed', False))}")
    print(f"    DEFER → DEFERRED:                           {_bool_str(result.get('deferred_decision_case_passed', False))}")
    print(f"    Invalid decision → BLOCKED:                  {_bool_str(result.get('invalid_decision_case_passed', False))}")
    print(f"    ACCEPT missing reviewer → BLOCKED:           {_bool_str(result.get('missing_reviewer_accept_case_passed', False))}")
    print(f"    REJECT missing reviewer → BLOCKED:           {_bool_str(result.get('missing_reviewer_reject_case_passed', False))}")
    print(f"    REJECT missing reason → BLOCKED:             {_bool_str(result.get('reject_missing_reason_case_passed', False))}")
    print(f"    DEFER missing reason → BLOCKED:              {_bool_str(result.get('defer_missing_reason_case_passed', False))}")
    print(f"    Package not ready → BLOCKED:                 {_bool_str(result.get('package_not_ready_case_passed', False))}")
    print(f"    Package BLOCKED → blocked:                   {_bool_str(result.get('package_blocked_case_passed', False))}")
    print(f"    Scope not PLANNING_ONLY → BLOCKED:           {_bool_str(result.get('scope_not_planning_only_case_passed', False))}")
    print(f"    executable=true → BLOCKED:                   {_bool_str(result.get('executable_true_case_passed', False))}")
    print(f"    broker_authorized=true → BLOCKED:            {_bool_str(result.get('broker_authorized_true_case_passed', False))}")
    print(f"    preflight_authorized=true → BLOCKED:          {_bool_str(result.get('preflight_authorized_true_case_passed', False))}")
    print(f"    approval_authorized=true → BLOCKED:           {_bool_str(result.get('approval_authorized_true_case_passed', False))}")
    print(f"    submission_authorized=true → BLOCKED:         {_bool_str(result.get('submission_authorized_true_case_passed', False))}")
    print(f"    broker_preflight_called=true → BLOCKED:       {_bool_str(result.get('broker_preflight_called_true_case_passed', False))}")
    print(f"    actual_preflight_completed=true → BLOCKED:     {_bool_str(result.get('actual_preflight_completed_true_case_passed', False))}")
    print(f"    actual_order_created=true → BLOCKED:          {_bool_str(result.get('actual_order_created_true_case_passed', False))}")
    print(f"    Package blockers → BLOCKED:                   {_bool_str(result.get('package_has_blockers_case_passed', False))}")
    print(f"    Disallowed symbol → BLOCKED:                  {_bool_str(result.get('disallowed_symbol_case_passed', False))}")
    print(f"    Invalid side → BLOCKED:                       {_bool_str(result.get('invalid_side_case_passed', False))}")
    print(f"    Invalid quantity → BLOCKED:                   {_bool_str(result.get('invalid_quantity_case_passed', False))}")
    print(f"    Negative quantity → BLOCKED:                  {_bool_str(result.get('negative_quantity_case_passed', False))}")
    print(f"    Stop above entry → BLOCKED:                   {_bool_str(result.get('stop_above_entry_case_passed', False))}")
    print(f"    Stop-qty mismatch → BLOCKED:                  {_bool_str(result.get('stop_quantity_mismatch_case_passed', False))}")
    print(f"    Data-quality fail → BLOCKED:                  {_bool_str(result.get('data_quality_fail_case_passed', False))}")
    print(f"    No-trade fail → BLOCKED:                       {_bool_str(result.get('no_trade_fail_case_passed', False))}")
    print(f"    Risk fail → BLOCKED:                          {_bool_str(result.get('risk_fail_case_passed', False))}")
    print(f"    Sizing fail → BLOCKED:                        {_bool_str(result.get('sizing_fail_case_passed', False))}")
    print(f"    Evidence-chain fail → BLOCKED:                 {_bool_str(result.get('evidence_chain_fail_case_passed', False))}")
    print(f"    Simulated-gate fail → BLOCKED:                 {_bool_str(result.get('simulated_gate_fail_case_passed', False))}")
    print(f"    Hash mismatch → BLOCKED:                      {_bool_str(result.get('hash_mismatch_case_passed', False))}")
    print(f"    Tampered evidence ref → BLOCKED:              {_bool_str(result.get('tampered_evidence_ref_case_passed', False))}")
    print(f"    Deterministic:                               {_bool_str(result.get('deterministic_case_passed', False))}")
    print(f"    No forbidden endpoints:                      {_bool_str(result.get('no_forbidden_endpoints_case_passed', False))}")
    print(f"    No broker identifiers:                       {_bool_str(result.get('no_broker_identifiers_case_passed', False))}")
    print(f"    Read-only invariant:                         {_bool_str(result.get('read_only_invariant_case_passed', False))}")
    print(f"    Fresh-clone:                                 {_bool_str(result.get('fresh_clone_case_passed', False))}")
    print(f"    Full chain non-executable:                   {_bool_str(result.get('full_chain_case_passed', False))}")
    print()
    print(f"  {BOLD}Canonical Review Record{RESET}")
    cr = result.get("canonical_review_record")
    if cr:
        print(f"    Review state:                 {cr.get('review_state', '?')}")
        print(f"    Decision:                     {cr.get('decision', '?')}")
        print(f"    Acceptance scope:             {cr.get('acceptance_scope', '?')}")
        print(f"    Preflight drafting permitted: {cr.get('preflight_request_drafting_permitted', '?')}")
        print(f"    Review hash:                  {cr.get('deterministic_candidate_review_hash', '?')[:16]}...")
        print(f"    Blockers:                     {cr.get('blocker_count', '?')}")
        labels = cr.get("output_labels", [])
        if labels:
            print(f"    Output labels:                {', '.join(labels)}")
    else:
        print(f"    {RED}No canonical review record generated{RESET}")
    print()
    print(f"  {BOLD}Safety Invariants{RESET}")
    print(f"    No /order called:            {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    No /connect called:           {_bool_str(result.get('no_connect_called'))}")
    print(f"    No broker mutation:           {_bool_str(result.get('no_broker_mutation'))}")
    print()
    if not checkpoint_ok:
        actions = result.get("suggested_operator_actions", [])
        if actions:
            print(f"  {RED}Suggested operator actions:{RESET}")
            for a in actions:
                print(f"    - {a}")
            print()
    ep = result.get("export_path")
    if ep:
        print(f"    Export: {ep}")
    print()


def _print_level1_guarded_preflight_request_draft_checkpoint(result: dict) -> None:
    """Print Phase 17K guarded preflight request draft checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE17K_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE17K_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  L1 Guarded Preflight Request Draft (17K){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Synthetic Fixture Results{RESET}")
    print(f"    Ready draft → PREFLIGHT_REQUEST_DRAFT_READY:    {_bool_str(result.get('ready_draft_case_passed', False))}")
    print(f"    Missing review → PENDING_INPUT:                  {_bool_str(result.get('missing_review_case_passed', False))}")
    print(f"    Rejected review → BLOCKED:                       {_bool_str(result.get('rejected_review_case_passed', False))}")
    print(f"    Deferred review → BLOCKED:                       {_bool_str(result.get('deferred_review_case_passed', False))}")
    print(f"    Blocked review → BLOCKED:                        {_bool_str(result.get('blocked_review_case_passed', False))}")
    print(f"    Wrong scope → BLOCKED:                           {_bool_str(result.get('scope_not_preflight_drafting_case_passed', False))}")
    print(f"    Drafting not permitted → BLOCKED:                {_bool_str(result.get('drafting_not_permitted_case_passed', False))}")
    print(f"    Package not PLANNING_ONLY → BLOCKED:             {_bool_str(result.get('package_not_planning_only_case_passed', False))}")
    print(f"    executable=true → BLOCKED:                       {_bool_str(result.get('executable_true_case_passed', False))}")
    print(f"    broker_authorized=true → BLOCKED:                {_bool_str(result.get('broker_authorized_true_case_passed', False))}")
    print(f"    preflight_authorized=true → BLOCKED:              {_bool_str(result.get('preflight_authorized_true_case_passed', False))}")
    print(f"    approval_authorized=true → BLOCKED:               {_bool_str(result.get('approval_authorized_true_case_passed', False))}")
    print(f"    submission_authorized=true → BLOCKED:             {_bool_str(result.get('submission_authorized_true_case_passed', False))}")
    print(f"    broker_preflight_called=true → BLOCKED:           {_bool_str(result.get('broker_preflight_called_true_case_passed', False))}")
    print(f"    actual_preflight_completed=true → BLOCKED:         {_bool_str(result.get('actual_preflight_completed_true_case_passed', False))}")
    print(f"    actual_order_created=true → BLOCKED:              {_bool_str(result.get('actual_order_created_true_case_passed', False))}")
    print(f"    Review has blockers → BLOCKED:                    {_bool_str(result.get('review_has_blockers_case_passed', False))}")
    print(f"    Missing evidence hashes → BLOCKED:                {_bool_str(result.get('missing_evidence_hashes_case_passed', False))}")
    print(f"    Hash mismatch → BLOCKED:                          {_bool_str(result.get('hash_mismatch_case_passed', False))}")
    print(f"    Tampered evidence ref → BLOCKED:                  {_bool_str(result.get('tampered_evidence_ref_case_passed', False))}")
    print(f"    Deterministic:                                   {_bool_str(result.get('deterministic_case_passed', False))}")
    print(f"    No forbidden endpoints:                          {_bool_str(result.get('no_forbidden_endpoints_case_passed', False))}")
    print(f"    No broker identifiers:                           {_bool_str(result.get('no_broker_identifiers_case_passed', False))}")
    print(f"    Read-only invariant:                             {_bool_str(result.get('read_only_invariant_case_passed', False))}")
    print(f"    Fresh-clone:                                     {_bool_str(result.get('fresh_clone_case_passed', False))}")
    print(f"    Full chain non-executable:                       {_bool_str(result.get('full_chain_case_passed', False))}")
    print(f"    Request body restrictions:                       {_bool_str(result.get('request_body_restrictions_case_passed', False))}")
    print(f"    Request headers restrictions:                    {_bool_str(result.get('request_headers_restrictions_case_passed', False))}")
    print(f"    Draft scope labels:                              {_bool_str(result.get('draft_scope_labels_case_passed', False))}")
    print()
    print(f"  {BOLD}Canonical Draft{RESET}")
    cd = result.get("canonical_draft")
    if cd:
        print(f"    Draft state:                   {cd.get('draft_state', '?')}")
        print(f"    Draft scope:                   {cd.get('draft_scope', '?')}")
        print(f"    Request delivery:              {cd.get('request_delivery_state', '?')}")
        print(f"    Draft hash:                    {cd.get('deterministic_preflight_request_draft_hash', '?')[:16]}...")
        print(f"    Blockers:                      {cd.get('blocker_count', '?')}")
        labels = cd.get("output_labels", [])
        if labels:
            print(f"    Output labels:                 {', '.join(labels)}")
    else:
        print(f"    {RED}No canonical draft generated{RESET}")
    print()
    print(f"  {BOLD}Safety Invariants{RESET}")
    print(f"    No /order called:            {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    No /connect called:           {_bool_str(result.get('no_connect_called'))}")
    print(f"    No broker mutation:           {_bool_str(result.get('no_broker_mutation'))}")
    print()
    if not checkpoint_ok:
        actions = result.get("suggested_operator_actions", [])
        if actions:
            print(f"  {RED}Suggested operator actions:{RESET}")
            for a in actions:
                print(f"    - {a}")
            print()
    ep = result.get("export_path")
    if ep:
        print(f"    Export: {ep}")
    print()


def _print_level1_phase17_chain_closure_checkpoint(result: dict) -> None:
    """Print Phase 17L chain closure checkpoint."""
    from trading_agent.cli.operator_common import BOLD, GREEN, RED, RESET, _PHASE17L_DIAGNOSIS
    from trading_agent.cli.operator_workflow_helpers import _bool_str
    checkpoint_ok = result.get("diagnosis") == _PHASE17L_DIAGNOSIS["ready"]
    diag_color = GREEN if checkpoint_ok else RED
    sev = result.get("severity", "?")
    sev_color = GREEN if sev == "OK" else RED
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  L1 Phase 17 Chain Closure (17L){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")
    print(f"  Checkpoint ID:               {result.get('checkpoint_id', '?')}")
    print(f"  Timestamp:                   {result.get('timestamp', '?')}")
    print(f"  Diagnosis:                   {diag_color}{result.get('diagnosis', '?')}{RESET}")
    print(f"  Severity:                    {sev_color}{sev}{RESET}")
    print()
    print(f"  {BOLD}Git{RESET}")
    g = result.get("git", {})
    print(f"    Branch:        {g.get('branch', '?')}")
    print(f"    Commit:        {g.get('commit_short', g.get('commit', '?'))}")
    print(f"    Worktree clean: {_bool_str(result.get('git_worktree_clean', False))}")
    print()
    print(f"  {BOLD}Synthetic Fixture Results{RESET}")
    print(f"    Ready closure → PHASE17_CLOSED:                {_bool_str(result.get('ready_closure_case_passed', False))}")
    print(f"    Missing draft → PENDING_INPUT:                  {_bool_str(result.get('missing_draft_case_passed', False))}")
    print(f"    Draft not ready → BLOCKED:                       {_bool_str(result.get('draft_not_ready_case_passed', False))}")
    print(f"    executable=true → BLOCKED:                       {_bool_str(result.get('executable_true_case_passed', False))}")
    print(f"    preflight_called=true → BLOCKED:                 {_bool_str(result.get('preflight_called_true_case_passed', False))}")
    print(f"    order_created=true → BLOCKED:                    {_bool_str(result.get('order_created_true_case_passed', False))}")
    print(f"    Missing governance → BLOCKED:                    {_bool_str(result.get('missing_governance_case_passed', False))}")
    print(f"    Missing schema → BLOCKED:                          {_bool_str(result.get('missing_schema_case_passed', False))}")
    print(f"    h1_accessed=true → BLOCKED:                        {_bool_str(result.get('h1_accessed_true_case_passed', False))}")
    print(f"    request_sent → BLOCKED:                             {_bool_str(result.get('request_sent_true_case_passed', False))}")
    print(f"    Disallowed symbol → BLOCKED:                        {_bool_str(result.get('disallowed_symbol_case_passed', False))}")
    print(f"    Invalid side → BLOCKED:                             {_bool_str(result.get('invalid_side_case_passed', False))}")
    print(f"    Invalid quantity → BLOCKED:                         {_bool_str(result.get('invalid_quantity_case_passed', False))}")
    print(f"    Hash mismatch → BLOCKED:                            {_bool_str(result.get('hash_mismatch_case_passed', False))}")
    print(f"    Deterministic:                                   {_bool_str(result.get('deterministic_case_passed', False))}")
    print(f"    Read-only invariant:                             {_bool_str(result.get('read_only_invariant_case_passed', False))}")
    print(f"    No forbidden endpoints:                          {_bool_str(result.get('no_forbidden_endpoints_case_passed', False))}")
    print(f"    No broker identifiers:                           {_bool_str(result.get('no_broker_identifiers_case_passed', False))}")
    print(f"    Full chain non-executable:                       {_bool_str(result.get('full_chain_case_passed', False))}")
    print(f"    Included phases complete:                        {_bool_str(result.get('included_phases_case_passed', False))}")
    print(f"    Closure labels:                                  {_bool_str(result.get('closure_labels_case_passed', False))}")
    print()
    print(f"  {BOLD}Canonical Closure{RESET}")
    cc = result.get("canonical_closure")
    if cc:
        print(f"    Closure state:                 {cc.get('closure_state', '?')}")
        print(f"    Closure scope:                 {cc.get('closure_scope', '?')}")
        print(f"    Included phases:               {cc.get('included_phases', [])}")
        print(f"    Closure hash:                  {cc.get('deterministic_phase17_closure_hash', '?')[:16]}...")
        print(f"    Blockers:                      {cc.get('blocker_count', '?')}")
        labels = cc.get("output_labels", [])
        if labels:
            print(f"    Output labels:                 {', '.join(labels)}")
    else:
        print(f"    {RED}No canonical closure generated{RESET}")
    print()
    print(f"  {BOLD}Safety Invariants{RESET}")
    print(f"    No /order called:            {_bool_str(result.get('no_order_endpoint_called'))}")
    print(f"    No /connect called:           {_bool_str(result.get('no_connect_called'))}")
    print(f"    No broker mutation:           {_bool_str(result.get('no_broker_mutation'))}")
    print()
    if not checkpoint_ok:
        actions = result.get("suggested_operator_actions", [])
        if actions:
            print(f"  {RED}Suggested operator actions:{RESET}")
            for a in actions:
                print(f"    - {a}")
            print()
    ep = result.get("export_path")
    if ep:
        print(f"    Export: {ep}")
    print()
