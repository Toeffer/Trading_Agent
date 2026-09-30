"""Full-cycle rehearsal against the IB Gateway simulator — SIMULATION ONLY.

Runs the real bridge (uvicorn bridge:app) and the real guard against
sim/ib_gateway.py, in a throwaway sandbox: its own HOME, its own rules file and
state files, its own bridge port, a random per-run H1 test token, and the
simulator's account DUSIM0001. Nothing touches ~/.openclaw, the host .env, IB
Gateway or the production bridge on 8790. Per CLAUDE.md §8 (Simulation), the
result is test evidence only.

Locked phase (always): kill switches at their safe defaults.
    connect → IBKR sizing preview → proposal (deterministic Hermes stand-in)
    → preflight → approve (sandbox H1 token) → submit must be ORDERS_BLOCKED.
Unlocked phase (--submit): RUNBOOK §L8 steps 1–5, inside the sandbox only.
    enforced=true in the sandbox rules, IBKR_ALLOW_ORDERS=true for the sandbox
    bridge, restart → the locked phase's approval must be dead (invariant #12)
    → fresh preflight → approve → submit → expected broker outcome → positions
    → monitor reconciliation.

Usage:
    scripts/sim-cycle                          # locked phase only
    scripts/sim-cycle --submit                 # + sandbox submit, filled at the ask
    scripts/sim-cycle --submit --mode partial  # half fills
    scripts/sim-cycle --submit --mode reject   # broker rejects: submit must fail
    scripts/sim-cycle --submit --mode no_ack   # gateway silent: submit must fail
    scripts/sim-cycle --json | --keep
Exit code 0 only when every step met its expectation.
"""

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from sim.ib_gateway import ACCOUNT as SIM_ACCOUNT
from sim.ib_gateway import ORDER_MODES, SimGateway

REPO = Path(__file__).resolve().parent.parent
SANDBOX_MARKER = ".ibkr-sim-sandbox"
PRODUCTION_BRIDGE_PORT = 8790

# Every state/config path the bridge, guard and monitor resolve, pinned into
# the sandbox. Set explicitly because bridge.py's load_dotenv() reads the
# checkout's .env, which on the host holds production values.
SANDBOX_PATHS = {
    "IBKR_RULES_PATH": ".openclaw/risk-rules/paper-trading-rules.yaml",
    "IBKR_GUARD_STATE_PATH": ".openclaw/guard-state.json",
    "IBKR_GUARD_EVENTS_PATH": ".openclaw/guard-events.jsonl",
    "IBKR_PROPOSALS_PATH": ".openclaw/proposals",
    "IBKR_APPROVAL_RECORDS_PATH": ".openclaw/approval-records.jsonl",
    "IBKR_ACTIVE_APPROVALS_PATH": ".openclaw/active-approvals.json",
    "IBKR_SUBMITTED_APPROVALS_PATH": ".openclaw/submitted-approvals.json",
    "IBKR_MONITOR_STATE_PATH": ".openclaw/monitor-state.json",
    "IBKR_MANUAL_ORDER_RECON_PATH": ".openclaw/manual-order-reconciliations.jsonl",
    "IBKR_POSITION_RECONCILIATIONS_PATH": ".openclaw/position-reconciliations.json",
}

RULES = {
    "rules_version": "1.3-draft",
    "enforced": False,
    "max_position_notional": {"value": 5},
    "max_risk_per_trade": {"value": 2},
    "max_total_exposure": {"value": 30},
    "max_trades_per_day": {"value": 2},
    "loss_halts": {"daily": {"value": 1.0}, "weekly": {"value": 3.0}},
    "initial_stop_loss": {"atr_multiplier": 2, "atr_period": 14, "absolute_floor_percent": 5},
    "symbol_allowlist": {"mode": "explicit_list", "allow": ["AAPL", "MSFT"]},
    "symbol_sectors": {"AAPL": "INFORMATION_TECHNOLOGY", "MSFT": "INFORMATION_TECHNOLOGY"},
    "max_positions_per_sector": {"value": 1},
    "manual_approval": {"enabled": True, "timeout_seconds": 300},
    "order_endpoint_gate": {},
    "guard_state": {"file": "guard-state.json"},
    "preflight": {"strict_mode": True, "response_type": "validation_results_only"},
    "logging": {"file": "guard-events.jsonl"},
}


# ── sandbox guards ──────────────────────────────────────────────────────────

class SandboxError(RuntimeError):
    pass


def _assert_sandbox() -> Path:
    """Refuse to go on unless HOME is this run's throwaway sandbox."""
    home = Path.home()
    real_home = Path(os.environ.get("_IBKR_SIM_REAL_HOME", "/nonexistent"))
    if not (home / SANDBOX_MARKER).is_file():
        raise SandboxError(f"HOME {home} is not a sim sandbox (no {SANDBOX_MARKER})")
    if home.resolve() == real_home.resolve():
        raise SandboxError("HOME is the real home directory")
    for var, rel in SANDBOX_PATHS.items():
        if Path(os.environ.get(var, "")) != home / rel:
            raise SandboxError(f"{var} does not point into the sandbox")
    return home


def _sandbox_bridge_env(sim_port: int, bridge_url: str, token_hash: str, unlocked: bool) -> dict:
    """The sandbox bridge's environment -- the only place switches are turned on.

    Every variable the bridge reads is set here, so nothing is inherited from
    the host .env. unlocked=True turns IBKR_ALLOW_ORDERS on for this process
    alone, after the sandbox has been verified.
    """
    _assert_sandbox()
    return {
        **os.environ,
        "IBKR_MODE": "paper",
        "IBKR_HOST": "127.0.0.1",
        "IBKR_PORT": str(sim_port),
        "IBKR_CLIENT_ID": "777",
        "IBKR_ACCOUNT": SIM_ACCOUNT,
        "IBKR_READ_ONLY": "false",
        "IBKR_BRIDGE_URL": bridge_url,
        "IBKR_BRIDGE_DEBUG": "false",
        "H1_APPROVAL_TOKEN_HASH": token_hash,
        "IBKR_ALLOW_ORDERS": "true" if unlocked else "false",
    }


def _write_rules(enforced: bool) -> None:
    home = _assert_sandbox()
    path = home / SANDBOX_PATHS["IBKR_RULES_PATH"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({**RULES, "enforced": enforced}, sort_keys=False))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── bridge process ──────────────────────────────────────────────────────────

class SandboxBridge:
    def __init__(self, sim_port: int, token_hash: str, unlocked: bool, log_path: Path):
        self.port = _free_port()
        if self.port == PRODUCTION_BRIDGE_PORT:
            raise SandboxError("refusing the production bridge port")
        self.url = f"http://127.0.0.1:{self.port}"
        self.env = _sandbox_bridge_env(sim_port, self.url, token_hash, unlocked)
        self.log_path = log_path
        self.proc = None

    def start(self) -> None:
        log = open(self.log_path, "ab")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "bridge:app", "--host", "127.0.0.1",
             "--port", str(self.port), "--app-dir", str(REPO)],
            env=self.env, cwd=str(Path.home()), stdout=log, stderr=log)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"bridge exited with {self.proc.returncode}; see {self.log_path}")
            try:
                self.get("/health", timeout=2)
                return
            except (urllib.error.URLError, OSError):
                time.sleep(0.3)
        raise RuntimeError(f"bridge did not start; see {self.log_path}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def _call(self, method: str, path: str, body=None, token=None, timeout=90):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("X-H1-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return {"_http_status": e.code, "_body": e.read().decode()[:500]}

    def get(self, path, **kw):
        return self._call("GET", path, **kw)

    def post(self, path, body, token=None):
        return self._call("POST", path, body, token)


# ── the rehearsal ───────────────────────────────────────────────────────────

# Known, documented defects the rehearsal reproduces. A step that hits one is
# reported as OPEN (not PASS, not a regression); --strict fails the run on it.
OPEN_FINDINGS = {
    "ACK-PENDINGSUBMIT": (
        "ib_insync sets PendingSubmit locally on every new order and the bridge's ack "
        "check counts it as IBKR acknowledgment, so a gateway that never answers still "
        "yields submitted=true and a counted trade. Fix needs Chris's decision: a held "
        "bracket parent gets no broker status until its stop transmits."),
    "FILL-NOT-RECORDED": (
        "The guard records filled quantity only at ack time (a bracket parent is acked "
        "while held, so filled=0); later fills are never recorded, so the drift monitor "
        "reports every filled BUY as drift until reconciled by hand (Phase 19F tool)."),
}


class Report:
    def __init__(self, mode: str, strict: bool = False):
        self.mode = mode
        self.strict = strict
        self.steps: list[dict] = []

    def step(self, name: str, ok: bool, detail, open_finding: str | None = None) -> bool:
        status = "PASS" if ok else ("OPEN" if open_finding else "FAIL")
        entry = {"step": name, "status": status, "ok": status != "FAIL", "detail": detail}
        if status == "OPEN":
            entry["finding"] = open_finding
        self.steps.append(entry)
        return bool(ok)

    @property
    def ok(self) -> bool:
        bad = ("FAIL", "OPEN") if self.strict else ("FAIL",)
        return not any(s["status"] in bad for s in self.steps)


def _stand_in_proposal(preview: dict, qty: int) -> dict:
    """What Hermes must produce from the sizing preview -- deterministic here.

    Uses a stop tighter than the guard's (halfway to the entry), which Hermes
    may choose since 2026-09-30, so the rehearsal proves such a stop travels
    through preflight into the bracket order.
    """
    ask = preview["quote"]["ask"]
    stop_price = round((preview["stop"]["stop_price"] + ask) / 2, 2)
    nl = preview["account"]["net_liquidation_eur"]
    fx = preview["account"]["eur_usd"]
    notional_eur = qty * ask / fx
    loss_eur = qty * (ask - stop_price) / fx
    return {
        "simulation": True,
        "symbol": preview["symbol"],
        "side": "BUY",
        "quantity": qty,
        "entry_reference": f"MKT near ask {ask} [bridge/preflight] SIMULATION",
        "stop_loss_invalidation": f"Stop {stop_price} (tighter than guard) SIMULATION",
        "max_loss_eur": round(loss_eur, 2),
        "max_loss_pct": round(100 * loss_eur / nl, 4),
        "position_notional_eur": round(notional_eur, 2),
        "position_notional_pct": round(100 * notional_eur / nl, 4),
        "portfolio_exposure_after_pct": round(100 * notional_eur / nl, 4),
        "daily_drawdown_status": "none [SIMULATION]",
        "weekly_drawdown_status": "none [SIMULATION]",
        "reason_to_trade": "SIMULATION rehearsal -- no market view",
        "reason_not_to_trade": "SIMULATION rehearsal -- no market view",
        "preflight_command": "POST /order/preflight (sim-cycle)",
        "position_sizing": {"method": "guard sizing preview, tighter stop",
                            "stop_price": stop_price, "final_shares": qty},
        "awaiting_chris_approval": True,
        "advisory_only": True,
    }


def _connect(bridge: SandboxBridge, report: Report, label: str) -> bool:
    res = bridge.post("/connect", {})
    accounts = res.get("managed_accounts")
    return report.step(f"{label}: connect to the simulator (account {SIM_ACCOUNT} only)",
                       res.get("connected") and accounts == [SIM_ACCOUNT], res)


def _cycle_to_approval(bridge, report, label, request, token) -> str | None:
    pf = bridge.post("/order/preflight", request)
    summary = {k: pf[k] for k in ("passed", "error", "approval_id", "entry_price",
                                  "stop_price", "final_max_shares", "gates") if k in pf}
    if not report.step(f"{label}: preflight passes all gates",
                       pf.get("passed") is True and pf.get("approval_id"), summary or pf):
        return None
    ap = bridge.post("/order/approve", {"approval_id": pf["approval_id"],
                                        "decision": "approve", "ruled_by": "sim-cycle"}, token)
    ok = report.step(f"{label}: approve with the sandbox H1 token",
                     ap.get("status") == "approved" or ap.get("approved") is True, ap)
    return pf["approval_id"] if ok else None


def _position(bridge: SandboxBridge, symbol: str) -> float:
    for p in bridge.get("/positions").get("positions", []):
        if p.get("symbol") == symbol:
            return float(p.get("position") or 0)
    return 0.0


def run(mode: str, submit: bool, symbol: str, qty: int, strict: bool = False) -> Report:
    home = _assert_sandbox()
    report = Report(mode, strict)
    gw = SimGateway(order_mode=mode)
    token = secrets.token_hex(16)                 # sandbox-only, discarded after the run
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    log_path = home / "bridge.log"
    _write_rules(enforced=False)

    bridge = SandboxBridge(gw.port, token_hash, unlocked=False, log_path=log_path)
    os.environ["IBKR_BRIDGE_URL"] = bridge.url    # guard/operator in this process -> sandbox bridge
    import guard
    import ibkr_operator
    with guard.h1_authorized_scope():
        guard.initialize_guard_state_if_missing()

    try:
        bridge.start()
        if not _connect(bridge, report, "locked"):
            return report
        preview = ibkr_operator._sizing_preview(symbol, "BUY", qty)
        if not report.step("sizing preview from bridge data", preview.get("ok"), preview):
            return report
        qty = min(qty, preview["sizing"]["final_max_shares"])
        proposal = _stand_in_proposal(preview, qty)
        check = ibkr_operator._check_hermes_sizing(proposal, preview)
        report.step("proposal agrees with the preview", check["ok"], check)
        proposal_path = str(guard.save_proposal_file(proposal))
        request = ibkr_operator._preflight_request(proposal, preview, proposal_path)
        report.step("preflight request carries the proposal's tighter stop",
                    request.get("stopPrice") == proposal["position_sizing"]["stop_price"], request)

        approval = _cycle_to_approval(bridge, report, "locked", request, token)
        if approval is None:
            return report
        sub = bridge.post("/order/submit", {"approval_id": approval}, token)
        report.step("locked: submit is ORDERS_BLOCKED (switches off)",
                    sub.get("code") == "ORDERS_BLOCKED" and not sub.get("submitted"), sub)
        report.step("locked: the simulator received no order",
                    not any(m == 3 for m, _ in gw.requests), f"{len(gw.orders)} order(s)")
        if not submit:
            return report

        # RUNBOOK §L8, sandbox only: both switches on, restart.
        bridge.stop()
        _write_rules(enforced=True)
        bridge = SandboxBridge(gw.port, token_hash, unlocked=True, log_path=log_path)
        os.environ["IBKR_BRIDGE_URL"] = bridge.url
        guard.BRIDGE_BASE = bridge.url
        bridge.start()
        if not _connect(bridge, report, "unlocked"):
            return report
        stale = bridge.post("/order/submit", {"approval_id": approval}, token)
        report.step("unlocked: the pre-restart approval is dead (invariant #12)",
                    not stale.get("submitted"), stale)

        before = _position(bridge, symbol)
        approval = _cycle_to_approval(bridge, report, "unlocked", request, token)
        if approval is None:
            return report
        sub = bridge.post("/order/submit", {"approval_id": approval}, token)
        expected_fill = {"fill": qty, "partial": max(1, qty // 2), "reject": 0, "no_ack": 0}[mode]
        if mode in ("fill", "partial"):
            report.step(f"unlocked: submit succeeds ({mode})", sub.get("submitted") is True, sub)
            placed_stop = next((o["aux_price"] for o in gw.orders.values()
                                if o["order_type"] == "STP"), None)
            report.step("unlocked: the bracket stop is the proposal's stop",
                        placed_stop == request.get("stopPrice"),
                        {"placed": placed_stop, "proposed": request.get("stopPrice")})
        else:
            report.step(f"unlocked: submit must NOT report success ({mode})",
                        not sub.get("submitted"), {
                            **sub, "simulator_orders": {i: o["status"] for i, o in gw.orders.items()}},
                        open_finding="ACK-PENDINGSUBMIT" if mode == "no_ack" else None)
        deadline = time.monotonic() + 10
        while _position(bridge, symbol) - before != expected_fill and time.monotonic() < deadline:
            time.sleep(0.3)
        delta = _position(bridge, symbol) - before
        report.step(f"unlocked: position change is {expected_fill} (bridge /positions)",
                    delta == expected_fill, {"before": before, "after": before + delta,
                                             "simulator_executions": gw.executions})
        recon = bridge.get("/monitor/reconciliation")
        report.step("unlocked: monitor reconciliation runs", "passed" in recon,
                    {k: recon.get(k) for k in ("passed", "alerts", "checks")})
        drift = bridge.get("/monitor/positions/drift")
        unrecorded_fill = any(m.get("symbol") == symbol and m.get("expected_qty") == before
                              and m.get("actual_qty") == before + delta != before
                              for m in drift.get("mismatches") or [])
        report.step("unlocked: position drift monitor agrees with the broker",
                    drift.get("drift_detected") is False,
                    {k: drift.get(k) for k in ("drift_detected", "mismatches") if k in drift} or drift,
                    open_finding="FILL-NOT-RECORDED" if unrecorded_fill else None)
        return report
    finally:
        bridge.stop()
        gw.close()


# ── entry points ────────────────────────────────────────────────────────────

def _print(report: Report, as_json: bool) -> None:
    found = sorted({s["finding"] for s in report.steps if s["status"] == "OPEN"})
    if as_json:
        print(json.dumps({"simulation": True, "account": SIM_ACCOUNT, "mode": report.mode,
                          "ok": report.ok, "steps": report.steps,
                          "open_findings": {f: OPEN_FINDINGS[f] for f in found}},
                         indent=2, default=str))
        return
    print(f"=== SIMULATION — account {SIM_ACCOUNT} — mode {report.mode} — not IBKR evidence ===")
    for s in report.steps:
        print(f"  {s['status']}  {s['step']}" + (f"  [{s['finding']}]" if "finding" in s else ""))
        if s["status"] == "FAIL":
            print(f"        {json.dumps(s['detail'], default=str)[:600]}")
    for f in found:
        print(f"  OPEN FINDING {f}: {OPEN_FINDINGS[f]}")
    verdict = ("FAILED" if not report.ok else
               "PASSED with open findings" if found else "ALL STEPS PASSED")
    print(f"=== {verdict} ===")


def _parse(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--submit", action="store_true",
                    help="also run the unlocked phase (sandbox-only switches, RUNBOOK §L8)")
    ap.add_argument("--mode", choices=ORDER_MODES, default="fill")
    ap.add_argument("--symbol", default="AAPL")
    ap.add_argument("--qty", type=int, default=10)
    ap.add_argument("--strict", action="store_true", help="open findings fail the run")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the sandbox directory")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parse(argv)
    if os.environ.get("_IBKR_SIM_INNER") == "1":
        report = run(args.mode, args.submit, args.symbol.upper(), args.qty, args.strict)
        _print(report, args.json)
        return 0 if report.ok else 1

    # Outer process: build the sandbox, then re-run inside it with HOME and
    # every state path pointed there.
    sandbox = Path(tempfile.mkdtemp(prefix="ibkr-sim-"))
    (sandbox / SANDBOX_MARKER).write_text("IB Gateway simulator sandbox -- SIMULATION ONLY\n")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("IBKR_") and k != "H1_APPROVAL_TOKEN_HASH"}
    env.update({"HOME": str(sandbox), "_IBKR_SIM_INNER": "1",
                "_IBKR_SIM_REAL_HOME": str(Path.home()),
                "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO), env.get("PYTHONPATH")]))})
    env.update({var: str(sandbox / rel) for var, rel in SANDBOX_PATHS.items()})
    try:
        return subprocess.run([sys.executable, "-m", "sim.cycle", *argv],
                              env=env, cwd=str(sandbox)).returncode
    finally:
        if args.keep:
            print(f"sandbox kept: {sandbox}", file=sys.stderr)
        else:
            shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
