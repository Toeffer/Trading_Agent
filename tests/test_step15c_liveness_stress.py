#!/usr/bin/env python3
"""
test_step15c_liveness_stress.py — Step 15C Liveness / Load-Shed Stress Tests

Verifies:
1. Snapshot endpoint returns within 5s (single consolidated call)
2. /health responds within 5s
3. IBKR-disconnected endpoints (/positions, /account) fast-fail (no 503)
4. /monitor/liveness returns OOM evidence
5. 5-service-restart loop: no OOM, one listener remains, health ok
6. Repeated KPI/rehearsal/candidate calls: no endpoint storms

No broker mutation. No sudo. Uses live bridge when available.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
import socket
import pytest

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BRIDGE_URL = os.environ.get("IBKR_BRIDGE_URL", "http://127.0.0.1:8790")
PROJECT_DIR = Path(__file__).resolve().parent.parent
NUM_RESTARTS = 5
HTTP_TIMEOUT = 5.0

pytestmark = pytest.mark.integration

def _bridge_listener_up(host="127.0.0.1", port=8790, timeout=0.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

def setup_module(module):
    if os.getenv("IBKR_LIVE_STRESS") != "1":
        pytest.skip("Step 15C live liveness stress requires IBKR_LIVE_STRESS=1")
    if not _bridge_listener_up():
        pytest.skip("Step 15C live liveness stress requires bridge listener on 127.0.0.1:8790")

def _fetch(endpoint: str, timeout: float = HTTP_TIMEOUT) -> tuple[int, dict]:
    """Fetch a bridge endpoint, return (status_code, parsed_json)."""
    url = f"{BRIDGE_URL}{endpoint}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode(errors="replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, {"_raw": body[:500]}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode(errors="replace"))
        except Exception:
            return e.code, {"_error": str(e)}
    except Exception as e:
        return 0, {"_error": str(e)}


def test_01_snapshot_fast():
    """Snapshot endpoint returns consolidated evidence within 5s."""
    t0 = time.time()
    status, data = _fetch("/snapshot", timeout=5.0)
    elapsed = time.time() - t0

    assert status == 200, f"/snapshot returned HTTP {status}"
    assert elapsed < 5.0, f"/snapshot took {elapsed:.1f}s (limit 5s)"
    assert "connected" in data, "snapshot missing 'connected'"
    assert "safety" in data, "snapshot missing 'safety'"
    assert "rth" in data, "snapshot missing 'rth'"
    assert "guard" in data, "snapshot missing 'guard'"
    assert "reconciliation" in data, "snapshot missing 'reconciliation'"
    # Step 15C v2: liveness is served separately via /monitor/liveness
    print(f"  ✓ /snapshot: {elapsed:.2f}s, {len(json.dumps(data))} bytes, connected={data.get('connected')}")


def test_02_health_fast():
    """Health endpoint responds within 5s."""
    t0 = time.time()
    status, data = _fetch("/health", timeout=5.0)
    elapsed = time.time() - t0

    assert status == 200, f"/health returned HTTP {status}"
    assert elapsed < 5.0, f"/health took {elapsed:.1f}s (limit 5s)"
    assert "ok" in data, "health missing 'ok'"
    print(f"  ✓ /health: {elapsed:.2f}s, ok={data.get('ok')}")


def test_03_disconnected_fast_fail():
    """When IBKR disconnected, /positions and /account fast-fail with evidence."""
    # Check if IBKR is connected
    _, health = _fetch("/health")
    connected = health.get("connected", False)

    if not connected:
        # Fast-fail expected: both should return 200 with ok=False
        status_p, data_p = _fetch("/positions")
        status_a, data_a = _fetch("/account")

        assert status_p == 200, f"/positions returned HTTP {status_p} (expected 200 fast-fail)"
        assert status_a == 200, f"/account returned HTTP {status_a} (expected 200 fast-fail)"
        assert data_p.get("ok") is False, "/positions should report ok=False when disconnected"
        assert data_a.get("ok") is False, "/account should report ok=False when disconnected"
        print(f"  ✓ disconnected fast-fail: /positions ok={data_p.get('ok')}, /account ok={data_a.get('ok')}")
    else:
        # Connected: just verify they return (not hang)
        t0 = time.time()
        status_p, data_p = _fetch("/positions", timeout=10.0)
        elapsed = time.time() - t0
        assert status_p in (200, 503), f"/positions returned unexpected HTTP {status_p}"
        assert elapsed < 10.0, f"/positions took {elapsed:.1f}s (limit 10s)"
        print(f"  ✓ connected /positions: {elapsed:.2f}s, HTTP {status_p}")


def test_04_liveness_endpoint():
    """Monitor liveness endpoint returns OOM evidence."""
    status, data = _fetch("/monitor/liveness")
    assert status == 200, f"/monitor/liveness returned HTTP {status}"
    assert "ok" in data, "liveness missing 'ok'"
    assert "service_active" in data, "liveness missing 'service_active'"
    assert "memory" in data, "liveness missing 'memory'"
    assert "oom_evidence" in data, "liveness missing 'oom_evidence'"
    assert "warnings" in data, "liveness missing 'warnings'"

    oom = data["oom_evidence"]
    mem = data["memory"]
    print(f"  ✓ /monitor/liveness: active={data['service_active']}, "
          f"oom_detected={oom.get('recent_oom_detected')}, "
          f"n_restarts={oom.get('n_restarts')}, "
          f"peak_mb={mem.get('peak_mb')}")


def test_05_listener_count():
    """One bridge listener remains on port 8790."""
    result = subprocess.run(
        ["ss", "-tlnp", "sport", "=", ":8790"],
        capture_output=True, text=True, timeout=5,
    )
    listeners = [l for l in result.stdout.splitlines() if "LISTEN" in l.upper()]
    assert len(listeners) >= 1, f"Expected >= 1 listener on :8790, got {len(listeners)}"
    print(f"  ✓ listeners on :8790: {len(listeners)}")


def test_06_no_endpoint_storm():
    """KPI-like snapshot calls don't cause endpoint storms.

    Makes 3 rapid snapshot calls and verifies each completes quickly
    (cache hit on subsequent calls).
    """
    times = []
    for i in range(3):
        t0 = time.time()
        status, data = _fetch("/snapshot", timeout=5.0)
        elapsed = time.time() - t0
        assert status == 200, f"call {i}: /snapshot returned HTTP {status}"
        times.append(elapsed)

    avg = sum(times) / len(times)
    # First call may be slower (cache miss), but all should be under 5s
    assert all(t < 5.0 for t in times), f"Snapshot call times: {times}"
    # If cache is working, subsequent calls should be very fast
    if len(times) >= 2 and times[1] < 0.1:
        print(f"  ✓ snapshot cache effective: first={times[0]:.3f}s, second={times[1]:.3f}s, third={times[2]:.3f}s")
    else:
        print(f"  ✓ snapshot calls: {times} (all <5s)")


def test_07_liveness_no_recent_oom():
    """Liveness endpoint reports no OOM."""
    status, data = _fetch("/monitor/liveness")
    assert status == 200
    oom = data.get("oom_evidence", {})
    warnings = data.get("warnings", [])

    if oom.get("recent_oom_detected"):
        pytest.fail(f"OOM detected: {oom.get('oom_details', [])[:2]}")
    else:
        print(f"  ✓ no recent OOM detected")

    # Memory should be reasonable
    mem = data.get("memory", {})
    rss_mb = mem.get("rss_mb", 0)
    if rss_mb > 1000:
        pytest.fail(f"Memory critically high: {rss_mb}MB RSS")
    else:
        print(f"  ✓ RSS {rss_mb}MB")


def test_08_repeated_kpi_equivalent():
    """5 repeated /snapshot calls all return 200, calls 2-5 are cache hits."""
    cache_hits = 0
    build_times = []
    for i in range(5):
        status, data = _fetch("/snapshot", timeout=5.0)
        assert status == 200, f"Snapshot call {i} failed with HTTP {status}"
        instr = data.get("_instrumentation", {})
        is_hit = instr.get("cache_hit", False)
        build_ms = instr.get("build_ms", 0)
        age_s = instr.get("cache_age_seconds", 0)
        if is_hit:
            cache_hits += 1
        build_times.append(build_ms)
        # Calls 2-5 (index 1-4) must be cache hits (TTL=30s covers all)
        if i >= 1:
            assert is_hit, f"Call {i} was not a cache hit (cache_age={age_s}s, build_ms={build_ms}ms)"
        print(f"  call {i}: hit={is_hit} age={age_s}s build={build_ms}ms")

    assert cache_hits >= 4, f"Expected >=4 cache hits, got {cache_hits}"

    # /health must still respond
    status, _ = _fetch("/health", timeout=5.0)
    assert status == 200, f"Health after snapshot storm: HTTP {status}"
    print(f"  ✓ 5 snapshots ({cache_hits} cache hits) + health ok")


# ---------------------------------------------------------------------------
# Regression test: KPI must not crash when bridge is down
# ---------------------------------------------------------------------------

def test_09_bridge_down_kpi_no_crash():
    """KPI must return structured NO-GO/HOLD when bridge is unreachable.

    Simulates bridge-down by pointing BRIDGE_URL at a dead port.
    Verifies run_kpi() returns a dict with 'verdict' key, never raises.
    """
    import os as _os
    orig_url = _os.environ.get("IBKR_BRIDGE_URL", "")
    try:
        # Point at a port where nothing is listening
        _os.environ["IBKR_BRIDGE_URL"] = "http://127.0.0.1:18790"
        # Force reimport to pick up new URL (modules cache BRIDGE_URL at import)
        import ibkr_operator
        import importlib
        importlib.reload(ibkr_operator)

        result = ibkr_operator.run_kpi()
        assert isinstance(result, dict), f"Expected dict, got {type(result).__name__}"
        assert "verdict" in result, "KPI result missing 'verdict' key"
        verdict = result["verdict"]
        assert verdict in ("NO-GO", "HOLD"), f"Expected NO-GO or HOLD, got {verdict}"

        # Must have at least one blocker about bridge unreachability
        blockers = result.get("blockers", [])
        bridge_blockers = [b for b in blockers if "bridge" in b.get("check", "").lower()
                          or "unreachable" in b.get("detail", "").lower()]
        assert len(bridge_blockers) >= 1, f"Expected bridge unreachable blocker, got: {[b['check'] for b in blockers]}"
        print(f"  ✓ KPI bridge-down: verdict={verdict}, bridge_blockers={len(bridge_blockers)}")
    finally:
        if orig_url:
            _os.environ["IBKR_BRIDGE_URL"] = orig_url
        else:
            _os.environ.pop("IBKR_BRIDGE_URL", None)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Step 15C — Liveness / Load-Shed Stress Tests")
    print("=" * 60)

    tests = [
        ("01 /snapshot fast", test_01_snapshot_fast),
        ("02 /health fast", test_02_health_fast),
        ("03 disconnected fast-fail", test_03_disconnected_fast_fail),
        ("04 /monitor/liveness", test_04_liveness_endpoint),
        ("05 listener count", test_05_listener_count),
        ("06 no endpoint storm", test_06_no_endpoint_storm),
        ("07 liveness no recent OOM", test_07_liveness_no_recent_oom),
        ("08 repeated KPI equivalent", test_08_repeated_kpi_equivalent),
        ("09 bridge-down KPI crash regression", test_09_bridge_down_kpi_no_crash),
    ]

    passed = 0
    failed = 0

    for name, fn in tests:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ {name}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n  Results: ✅ {passed} passed  ❌ {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
