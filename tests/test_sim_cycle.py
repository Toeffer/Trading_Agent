"""IB Gateway simulator and full-cycle rehearsal (2026-09-28) — SIMULATION ONLY.

sim/ib_gateway.py speaks the TWS API; sim/cycle.py runs the real bridge and
guard against it in a throwaway sandbox (own HOME, rules, state, bridge port,
random H1 test token, account DUSIM0001):

  locked (default)  connect → sizing preview → proposal → preflight →
                    approve → submit must be ORDERS_BLOCKED
  --submit          RUNBOOK §L8 inside the sandbox: switches on, restart →
                    old approval dead (invariant #12) → fresh cycle → broker
                    outcome → positions → reconciliation → drift

Its first runs found two defects, fixed with it: a passing preflight 500'd
writing its H1-protected approval record, and every BUY submit failed with
BRACKET_STOP_REQUIRED (stop read from the wrong part of the record). Two more
are reproduced as OPEN findings awaiting Chris's decision (see
sim.cycle.OPEN_FINDINGS); the per-mode expectations below pin them, so a fix
flips them to PASS and this test says so.
"""

import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from sim import cycle  # noqa: E402
from sim.ib_gateway import ACCOUNT, ASK_PRICE, BID_PRICE, SimGateway  # noqa: E402


# ── simulator order handling, straight through ib_insync ────────────────────

@pytest.fixture
def connect():
    ib_insync = pytest.importorskip("ib_insync")
    made = []

    def _connect(mode="fill", positions=None):
        gw = SimGateway(order_mode=mode, positions=positions)
        ib = ib_insync.IB()
        ib.connect("127.0.0.1", gw.port, clientId=777, timeout=5, readonly=False)
        contract = ib.qualifyContracts(ib_insync.Stock("AAPL", "SMART", "USD"))[0]
        made.append((gw, ib))
        return gw, ib, contract, ib_insync.Order

    yield _connect
    for gw, ib in made:
        ib.disconnect()
        gw.close()


class TestSimulator:
    def test_reports_the_simulation_account(self, connect):
        _, ib, _, _ = connect()
        assert ib.managedAccounts() == [ACCOUNT] == ["DUSIM0001"]

    def test_market_order_fills_at_the_ask_and_updates_positions(self, connect):
        _, ib, c, Order = connect()
        t = ib.placeOrder(c, Order(action="BUY", totalQuantity=10, orderType="MKT"))
        ib.sleep(0.3)
        assert (t.orderStatus.status, t.orderStatus.filled) == ("Filled", 10)
        assert t.fills[0].execution.price == ASK_PRICE
        assert [(p.contract.symbol, p.position) for p in ib.positions()] == [("AAPL", 10)]

    def test_bracket_parent_is_held_until_the_stop_transmits(self, connect):
        gw, ib, c, Order = connect()
        parent = ib.placeOrder(c, Order(action="BUY", totalQuantity=5, orderType="MKT",
                                        transmit=False))
        ib.sleep(0.3)
        assert parent.orderStatus.status == "PendingSubmit" and not gw.orders
        stop = ib.placeOrder(c, Order(action="SELL", totalQuantity=5, orderType="STP",
                                      auxPrice=180.0, parentId=parent.order.orderId,
                                      transmit=True))
        ib.sleep(0.3)
        assert parent.orderStatus.status == "Filled"
        assert stop.orderStatus.status == "Submitted"
        ib.cancelOrder(stop.order)
        ib.sleep(0.3)
        assert stop.orderStatus.status == "Cancelled"

    def test_partial_fill(self, connect):
        _, ib, c, Order = connect("partial", {"AAPL": (10.0, 180.0)})
        t = ib.placeOrder(c, Order(action="SELL", totalQuantity=4, orderType="MKT"))
        ib.sleep(0.3)
        assert (t.orderStatus.status, t.orderStatus.filled) == ("Submitted", 2)
        assert t.fills[0].execution.price == BID_PRICE
        assert [p.position for p in ib.positions()] == [8]

    def test_no_ack_leaves_only_the_local_pending_submit(self, connect):
        _, ib, c, Order = connect("no_ack")
        t = ib.placeOrder(c, Order(action="BUY", totalQuantity=1, orderType="MKT"))
        ib.sleep(0.5)
        # ib_insync's own status; the broker said nothing and assigned no permId.
        assert (t.orderStatus.status, t.orderStatus.permId) == ("PendingSubmit", 0)

    def test_reject(self, connect):
        _, ib, c, Order = connect("reject")
        t = ib.placeOrder(c, Order(action="BUY", totalQuantity=1, orderType="MKT"))
        ib.sleep(0.3)
        assert t.orderStatus.status == "Cancelled" and not t.fills


# ── sandbox guards and switch confinement ───────────────────────────────────

class TestSandboxGuards:
    def test_refuses_outside_a_sandbox(self):
        with pytest.raises(cycle.SandboxError):
            cycle._assert_sandbox()

    def test_cannot_build_an_unlocked_bridge_env_outside_a_sandbox(self):
        with pytest.raises(cycle.SandboxError):
            cycle._sandbox_bridge_env(4999, "http://127.0.0.1:1", "0" * 64, unlocked=True)

    def test_cannot_write_rules_outside_a_sandbox(self):
        with pytest.raises(cycle.SandboxError):
            cycle._write_rules(enforced=True)

    def test_every_state_path_is_pinned(self):
        src = "\n".join(p.read_text() for p in
                        (REPO / "bridge.py", REPO / "guard.py", REPO / "monitor.py"))
        read = set(re.findall(r'"(IBKR_[A-Z_]+_PATH)"', src))
        assert read <= set(cycle.SANDBOX_PATHS), read - set(cycle.SANDBOX_PATHS)

    def test_every_bridge_env_var_is_set_explicitly(self):
        # bridge.py's load_dotenv() never overrides a variable that is already
        # set, so the sandbox must set every one it reads.
        read = set(re.findall(r'os\.getenv\("((?:IBKR|H1)_[A-Z_]+)"',
                              (REPO / "bridge.py").read_text()))
        src = (REPO / "sim" / "cycle.py").read_text()
        start = src.index("def _sandbox_bridge_env(")
        fn = src[start:src.index("\ndef ", start + 1)]
        missing = {v for v in read if f'"{v}":' not in fn}
        assert read and not missing, missing


_ENABLE = re.compile(r"""["']IBKR_ALLOW_ORDERS["']\s*[:\],]\s*=?\s*["']true""", re.I)


def test_order_switch_enabling_is_confined_to_the_sim_sandbox():
    """Outside tests/, the only code that sets IBKR_ALLOW_ORDERS to true for a
    process is sim.cycle._sandbox_bridge_env, which checks the sandbox first."""
    files = [p for p in REPO.rglob("*") if p.is_file() and ".git" not in p.parts
             and ".venv" not in p.parts and "tests" not in p.parts
             and p.suffix in ("", ".py", ".sh", ".yml", ".yaml")]
    hits = [str(p.relative_to(REPO)) for p in files
            if _ENABLE.search(p.read_text(errors="ignore"))]
    assert hits == ["sim/cycle.py"], hits
    src = (REPO / "sim" / "cycle.py").read_text()
    fn = src[src.index("def _sandbox_bridge_env("):src.index("\ndef ", src.index("def _sandbox_bridge_env(") + 1)]
    assert _ENABLE.search(fn) and len(_ENABLE.findall(src)) == 1
    assert fn.index("_assert_sandbox()") < _ENABLE.search(fn).start()


# ── the full rehearsal, every broker mode (parallel, isolated sandboxes) ────

SCENARIOS = {
    "locked": [],
    "fill": ["--submit", "--mode", "fill"],
    "partial": ["--submit", "--mode", "partial"],
    "reject": ["--submit", "--mode", "reject"],
    "no_ack": ["--submit", "--mode", "no_ack"],
}
# Steps expected to be OPEN (known findings) per scenario; everything else PASS.
EXPECTED_OPEN = {
    "locked": {},
    "fill": {"unlocked: position drift monitor agrees with the broker": "FILL-NOT-RECORDED"},
    "partial": {"unlocked: position drift monitor agrees with the broker": "FILL-NOT-RECORDED"},
    "reject": {},
    "no_ack": {"unlocked: submit must NOT report success (no_ack)": "ACK-PENDINGSUBMIT"},
}


@pytest.fixture(scope="module")
def runs():
    pytest.importorskip("fastapi")
    pytest.importorskip("ib_insync")
    env = {k: v for k, v in os.environ.items() if not k.startswith("IBKR_")}
    env["PYTHONPATH"] = str(REPO)

    def run(args):
        proc = subprocess.run([sys.executable, "-m", "sim.cycle", "--json", *args],
                              cwd=str(REPO), env=env, capture_output=True, text=True,
                              timeout=240)
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {"_error": proc.stdout[-2000:] + proc.stderr[-3000:]}

    with ThreadPoolExecutor(len(SCENARIOS)) as ex:
        return dict(zip(SCENARIOS, ex.map(run, SCENARIOS.values())))


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_rehearsal(runs, scenario):
    r = runs[scenario]
    assert "_error" not in r, r.get("_error")
    assert r["simulation"] is True and r["account"] == "DUSIM0001"
    statuses = {s["step"]: (s["status"], s.get("finding")) for s in r["steps"]}
    expected = {step: ("OPEN", f) for step, f in EXPECTED_OPEN[scenario].items()}
    unexpected = {step: st for step, st in statuses.items()
                  if st != expected.get(step, ("PASS", None))}
    assert not unexpected, json.dumps(
        {"unexpected": unexpected,
         "details": [s for s in r["steps"] if s["step"] in unexpected]}, default=str)[:3000]
    assert set(expected) <= set(statuses), set(expected) - set(statuses)
    assert r["ok"] is True


def test_locked_rehearsal_covers_the_whole_approval_path(runs):
    steps = [s["step"] for s in runs["locked"]["steps"]]
    assert steps == [
        "locked: connect to the simulator (account DUSIM0001 only)",
        "sizing preview from bridge data",
        "proposal agrees with the preview",
        "preflight request carries the proposal's tighter stop",
        "locked: preflight passes all gates",
        "locked: approve with the sandbox H1 token",
        "locked: submit is ORDERS_BLOCKED (switches off)",
        "locked: the simulator received no order",
    ]


def test_fill_rehearsal_places_a_real_bracket(runs):
    sub = next(s for s in runs["fill"]["steps"] if s["step"] == "unlocked: submit succeeds (fill)")
    assert sub["detail"]["bracket"] is True and sub["detail"]["stop_order_id"]
    placed = next(s for s in runs["fill"]["steps"]
                  if s["step"] == "unlocked: the bracket stop is the proposal's stop")
    assert placed["status"] == "PASS" and placed["detail"]["placed"] == sub["detail"]["stop_price"]
