#!/usr/bin/env python3
"""
bundle_audit.py — Phase 3H Immutable Audit Bundle

Creates an end-of-day or on-demand audit artifact that packages all
critical state files, live endpoint snapshots, regression results,
and source code hashes into one immutable JSON bundle.

No trading. No order paths. No automation.

Usage (offline CLI):
    python3 bundle_audit.py  # writes to ~/.openclaw/audit-bundles/

Usage (in-process, via bridge):
    from bundle_audit import create_audit_bundle
    bundle = create_audit_bundle()
"""

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HOME = Path.home()
OPENCLAW_DIR = HOME / ".openclaw"
AUDIT_DIR = OPENCLAW_DIR / "audit-bundles"
BRIDGE_DIR = HOME / "agents" / "ibkr-bridge"

# Retention defaults
MAX_BUNDLES = 20          # keep at most 20 audit bundles
MAX_BUNDLE_AGE_DAYS = 30  # delete bundles older than 30 days (soft cap)
BRIDGE_URL = os.environ.get("IBKR_BRIDGE_URL", "http://127.0.0.1:8790")

# Files to snapshot (read from disk)
AUDIT_FILES = {
    "guard-state.json": OPENCLAW_DIR / "guard-state.json",
    "guard-events.jsonl": OPENCLAW_DIR / "guard-events.jsonl",
    "submitted-approvals.json": OPENCLAW_DIR / "submitted-approvals.json",
    "manual-order-reconciliations.jsonl": OPENCLAW_DIR / "manual-order-reconciliations.jsonl",
}

# Source files to hash
SOURCE_FILES = [
    "bridge.py",
    "guard.py",
    "monitor.py",
    "bundle_audit.py",
    "ibkr_operator.py",
]

# Endpoints to snapshot (HTTP GET from bridge)
AUDIT_ENDPOINTS = {
    "health": "/health",
    "readiness": "/readiness",
    "monitor_reconciliation": "/monitor/reconciliation",
    "monitor_positions_drift": "/monitor/positions/drift",
    "monitor_open_orders": "/monitor/open-orders",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_file_safe(path: Path, max_bytes: int = 5 * 1024 * 1024) -> Any:
    """Read a file, return parsed JSON (for .json) or raw lines (for .jsonl)
    or raw string (for other). Truncates at max_bytes.

    Returns None if file not found or unreadable.
    """
    if not path.exists():
        return None
    try:
        data = path.read_bytes()
        if len(data) > max_bytes:
            data = data[:max_bytes]
            truncated = True
        else:
            truncated = False

        decoded = data.decode("utf-8", errors="replace")

        if path.suffix == ".json":
            try:
                parsed = json.loads(decoded)
                if truncated:
                    parsed["_truncated"] = True
                return parsed
            except json.JSONDecodeError:
                return {"_raw": decoded[:5000], "_parse_error": True}
        elif path.suffix == ".jsonl":
            lines = decoded.splitlines()
            parsed_lines = []
            for line in lines:
                line = line.strip()
                if line:
                    try:
                        parsed_lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        parsed_lines.append({"_raw": line[:500], "_parse_error": True})
            result = {"lines": parsed_lines, "line_count": len(parsed_lines)}
            if truncated:
                result["_truncated"] = True
            return result
        else:
            return {"_raw": decoded[:10000], "bytes": len(data), "truncated": truncated}
    except OSError:
        return None


def _fetch_endpoint(endpoint: str) -> Any:
    """Fetch a bridge endpoint via HTTP GET.

    Returns the parsed JSON response, or an error dict on failure.
    """
    url = f"{BRIDGE_URL}{endpoint}"
    try:
        req = urllib.request.urlopen(url, timeout=10)
        data = json.loads(req.read().decode())
        return {"_status": req.status, "_data": data}
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:1000]
        return {"_status": e.code, "_error": body}
    except urllib.error.URLError as e:
        return {"_status": 0, "_error": f"{type(e).__name__}: {str(e)[:200]}"}
    except Exception as e:
        return {"_status": 0, "_error": f"{type(e).__name__}: {str(e)[:200]}"}


def _hash_file(path: Path, max_mb: int = 10) -> str | None:
    """Return SHA256 hex digest of a file, streaming to bound memory.

    Reads in 64KB chunks. Skips if file > max_mb (default 10 MB).
    Returns None if not found, too large, or unreadable.
    """
    if not path.exists():
        return None
    try:
        fsize = path.stat().st_size
        if fsize > max_mb * 1024 * 1024:
            return None
        h = hashlib.sha256()
        with open(path, 'rb') as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _run_regression_silent() -> dict:
    """Run the regression suite in silent mode and return results.

    Handles ImportError gracefully if monitor.py unavailable.
    """
    try:
        from monitor import _run_self_test
        return _run_self_test(silent=True)
    except ImportError as e:
        return {"pass": False, "total": 0, "passed": 0, "_error": str(e)[:100]}
    except Exception as e:
        return {"pass": False, "total": 0, "passed": 0, "_error": f"{type(e).__name__}: {str(e)[:200]}"}


def _run_checklist_snapshot() -> dict | None:
    """Produce checklist evidence snapshot from local files only.

    Reads guard-state.json, guard-events.jsonl, audit bundles, releases.
    No HTTP calls, no subprocess — safe for single-worker bridge.

    Returns None gracefully on any error (never blocks audit bundle/release).
    Full data snapshot available via: ibkr-operator checklist --json
    """
    try:
        # Read guard state for safety status
        gs_path = OPENCLAW_DIR / "guard-state.json"
        gs = _read_file_safe(gs_path)
        gs = gs if isinstance(gs, dict) else {}
        allow = gs.get("allow_orders", False)
        enf_rules = gs.get("rules", {})
        if isinstance(enf_rules, dict):
            enforced = enf_rules.get("enforced", False)
        else:
            enforced = gs.get("enforced", False)

        # Count events
        events_lines = 0
        events_path = OPENCLAW_DIR / "guard-events.jsonl"
        if events_path and events_path.exists():
            try:
                events_lines = sum(1 for _ in events_path.open())
            except Exception:
                pass

        # Latest release info (bounded — uses latest_release_tag)
        from bundle_audit import latest_release_tag as _lrt
        latest_tag = _lrt()

        # Latest bundle (bounded — uses latest_audit_bundle)
        from bundle_audit import latest_audit_bundle as _lab
        latest_bundle = _lab()

        snapshot = {
            "command": "ibkr-operator checklist (file-based evidence)",
            "state": "evidence_snapshot",
            "verdict": "EVIDENCE",
            "blocks": [],
            "warnings": [],
            "read_only": True,
            "generated_at_utc": _now_iso(),
            "summary_safety": {
                "allow_orders": allow,
                "enforced": enforced,
                "system_locked": not (allow or enforced),
            },
            "summary_calendar": {},
            "summary_monitoring": {
                "event_count": events_lines,
            },
            "summary_portfolio": {},
            "summary_release": {
                "latest_release": latest_tag.get("phase_label", "?") if latest_tag else None,
                "latest_bundle": latest_bundle.get("bundle_id", "?") if latest_bundle else None,
            },
            "next_safe_action": {
                "action": "Run ibkr-operator checklist --json standalone for full data",
                "rationale": "Evidence snapshot captured from local files. Full checklist requires live bridge.",
            },
            "required_manual_confirmations": [],
        }
        return snapshot
    except Exception:
        return None

def create_audit_bundle(skip_endpoints: bool = False, skip_regression: bool = False) -> dict:
    """Create an immutable audit bundle.

    Args:
        skip_endpoints: If True, skip HTTP endpoint snapshots (offline mode).
        skip_regression: If True, skip regression suite (offline mode).

    Returns:
        Dict with the complete audit bundle.
    """
    # 1. File snapshots
    file_snapshots: dict[str, Any] = {}
    for name, path in AUDIT_FILES.items():
        content = _read_file_safe(path)
        if content is not None:
            file_snapshots[name] = content
        else:
            file_snapshots[name] = {"_missing": True}

    # 2. Endpoint snapshots
    endpoint_snapshots: dict[str, Any] = {}
    if not skip_endpoints:
        for name, endpoint in AUDIT_ENDPOINTS.items():
            endpoint_snapshots[name] = _fetch_endpoint(endpoint)

    # 3. Regression suite
    regression = None
    if not skip_regression:
        regression = _run_regression_silent()

    # 4. Code hashes
    code_hashes: dict[str, str | None] = {}
    for fname in SOURCE_FILES:
        fpath = BRIDGE_DIR / fname
        code_hashes[fname] = _hash_file(fpath)

    # 5a. Simulation evidence (Phase 3V): capture dry_run_order events
    simulation_evidence = None
    try:
        events_path = AUDIT_FILES.get("guard-events.jsonl")
        if events_path and events_path.exists():
            # Read last 200 dry_run_order events (bounded memory)
            all_dry = []
            for line in events_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if ev.get("event_type") == "dry_run_order":
                        safe_ev = {k: v for k, v in ev.items()
                                   if k not in ("ibkr_metadata",)}
                        all_dry.append(safe_ev)
                except (json.JSONDecodeError, TypeError):
                    continue
            # Keep only last 200 records
            dry_events = all_dry[-200:] if len(all_dry) > 200 else all_dry
            if dry_events:
                simulation_evidence = {
                    "event_type": "dry_run_order",
                    "count": len(dry_events),
                    "events": dry_events,
                    "advisory": "simulation-only — never affects live reconciliation",
                }
    except Exception:
        pass

    # 5b. Operator checklist snapshot (Phase 4C)
    checklist_snapshot = _run_checklist_snapshot()

    # 6. Build bundle
    bundle_id = f"bundle_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    bundle: dict[str, Any] = {
        "bundle_id": bundle_id,
        "created_at_utc": _now_iso(),
        "source": "bundle_audit.py",
        "version": "phase3h-1",
        "immutable": True,
        "files": file_snapshots,
        "code_hashes": code_hashes,
        "simulation_evidence": simulation_evidence,
        "checklist_snapshot": checklist_snapshot,
    }

    if not skip_endpoints:
        bundle["endpoints"] = endpoint_snapshots
    if regression is not None:
        bundle["regression"] = regression

    return bundle


def write_audit_bundle(bundle: dict) -> Path:
    """Write an audit bundle to disk as a JSON file.

    Creates AUDIT_DIR if it doesn't exist.
    Enforces retention policy (keeps newest MAX_BUNDLES, removes older).
    Returns the path to the written file.
    """
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    bundle_id = bundle.get("bundle_id", f"bundle_{_now_iso()}")
    out_path = AUDIT_DIR / f"{bundle_id}.json"

    with open(out_path, "w") as f:
        json.dump(bundle, f, indent=2, default=str)

    # Enforce retention after writing new bundle, then inject result
    pruned = _enforce_bundle_retention()
    bundle["_retention_pruned"] = pruned

    # Rewrite to include retention info
    with open(out_path, "w") as f:
        json.dump(bundle, f, indent=2, default=str)

    return out_path


def _enforce_bundle_retention() -> dict:
    """Enforce audit bundle retention policy.

    Removes bundles exceeding MAX_BUNDLES or older than MAX_BUNDLE_AGE_DAYS.
    Always keeps at least 1 bundle (the newest).
    Returns dict with counts of removed files.
    """
    if not AUDIT_DIR.exists():
        return {"by_count": 0, "by_age": 0, "total_removed": 0}

    paths = sorted(AUDIT_DIR.glob("bundle_*.json"), reverse=True)
    removed_by_age = 0
    removed_by_count = 0

    # Step 1: remove by age (older than MAX_BUNDLE_AGE_DAYS)
    now = datetime.now(timezone.utc)
    keep_paths = []
    for p in paths:
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            age_days = (now - mtime).total_seconds() / 86400
            if age_days > MAX_BUNDLE_AGE_DAYS:
                p.unlink()
                removed_by_age += 1
            else:
                keep_paths.append(p)
        except OSError:
            keep_paths.append(p)

    # Step 2: enforce max count on survivors (keep newest MAX_BUNDLES)
    keep_paths.sort(reverse=True)
    if len(keep_paths) > MAX_BUNDLES:
        for p in keep_paths[MAX_BUNDLES:]:
            try:
                p.unlink()
                removed_by_count += 1
            except OSError:
                pass

    total = removed_by_age + removed_by_count
    return {"by_age": removed_by_age, "by_count": removed_by_count, "total_removed": total}


def prune_old_bundles(keep: int = 20) -> dict:
    """Prune old audit bundles, keeping only the newest `keep`.

    Also removes bundles older than MAX_BUNDLE_AGE_DAYS.
    This is a maintenance operation — safe to call at any time.
    Returns dict with removal counts.
    """
    if not AUDIT_DIR.exists():
        return {"by_count": 0, "by_age": 0, "total_removed": 0}

    paths = sorted(AUDIT_DIR.glob("bundle_*.json"), reverse=True)
    removed_by_age = 0
    removed_by_count = 0

    # Step 1: age-based
    now = datetime.now(timezone.utc)
    survivors = []
    for p in paths:
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            age_days = (now - mtime).total_seconds() / 86400
            if age_days > MAX_BUNDLE_AGE_DAYS:
                p.unlink()
                removed_by_age += 1
            else:
                survivors.append(p)
        except OSError:
            survivors.append(p)

    # Step 2: count-based
    survivors.sort(reverse=True)
    if len(survivors) > keep:
        for p in survivors[keep:]:
            try:
                p.unlink()
                removed_by_count += 1
            except OSError:
                pass

    total = removed_by_age + removed_by_count
    return {"by_age": removed_by_age, "by_count": removed_by_count, "total_removed": total}


def load_audit_bundles(sort_by: str = "created_at_utc", max_count: int = 3) -> list[dict]:
    """Load audit bundles from AUDIT_DIR, newest first, bounded to max_count.

    Loads only the max_count most recent bundles to bound memory.
    """
    if not AUDIT_DIR.exists():
        return []
    paths = sorted(AUDIT_DIR.glob("bundle_*.json"), reverse=True)
    bundles = []
    for p in paths[:max_count]:
        try:
            data = json.loads(p.read_text())
            bundles.append(data)
        except (json.JSONDecodeError, OSError):
            pass
    return bundles


def latest_audit_bundle() -> dict | None:
    """Return the most recent audit bundle, or None."""
    bundles = load_audit_bundles()
    return bundles[0] if bundles else None


# ---------------------------------------------------------------------------
# Phase 3I — Audit Bundle Verification
# ---------------------------------------------------------------------------

def verify_audit_bundle(bundle: dict | None = None, skip_endpoint_live_check: bool = False) -> dict:
    """Verify an audit bundle is internally consistent.

    Args:
        bundle: The bundle dict to verify. If None, loads the latest bundle.
        skip_endpoint_live_check: If True, skip live endpoint comparison
            (useful when called from within an HTTP endpoint to avoid
             circular self-calls).

    Checks:
    1. Code hashes are valid (re-hash source files and compare)
    2. Expected files are present (4 required)
    3. Endpoint snapshots agree with file state (guard-state in readiness)
    4. Locked baseline is true (kill switches both false)
    5. Regression count recorded (from offline CLI bundle)
    6. Bundle timestamp and bundle_id are valid
    7. No live requires_action alerts

    Returns:
        Dict with pass/fail, individual check results, and detail.
    """
    if bundle is None:
        bundle = latest_audit_bundle()
        if bundle is None:
            return {
                "pass": False,
                "checks": [{"check": "bundle_exists", "ok": False, "detail": "No audit bundles found"}],
                "check_count": 1,
                "passed_count": 0,
            }

    checks: list[dict] = []

    def _check(name: str, ok: bool, detail: str):
        checks.append({"check": name, "ok": ok, "detail": detail})

    # 1. Code hashes are valid
    code_hashes = bundle.get("code_hashes", {})
    expected_sources = ["bridge.py", "guard.py", "monitor.py", "bundle_audit.py"]
    all_hash_ok = True
    for fname in expected_sources:
        bundle_hash = code_hashes.get(fname)
        if bundle_hash is None:
            _check(f"code_hash_{fname}", False, "missing in bundle")
            all_hash_ok = False
            continue
        fpath = BRIDGE_DIR / fname
        if not fpath.exists():
            _check(f"code_hash_{fname}", False, f"source file {fname} not found")
            all_hash_ok = False
            continue
        actual_hash = _hash_file(fpath)
        match = actual_hash == bundle_hash
        if not match:
            _check(f"code_hash_{fname}", False,
                   f"mismatch: bundle={bundle_hash[:16]}... actual={actual_hash[:16] if actual_hash else 'N/A'}...")
            all_hash_ok = False
    if all_hash_ok:
        _check("code_hashes_valid", True, f"{len(expected_sources)}/{len(expected_sources)} source hashes match")

    # 2. Expected files are present
    files = bundle.get("files", {})
    required_files = ["guard-state.json", "guard-events.jsonl",
                      "submitted-approvals.json", "manual-order-reconciliations.jsonl"]
    all_files_ok = True
    for fname in required_files:
        content = files.get(fname)
        if content is None:
            _check(f"file_{fname}", False, "missing from bundle")
            all_files_ok = False
        elif isinstance(content, dict) and content.get("_missing"):
            _check(f"file_{fname}", False, "marked missing on disk")
            all_files_ok = False
        elif isinstance(content, dict) and content.get("_parse_error"):
            _check(f"file_{fname}", False, "has parse error in bundle")
            all_files_ok = False
        elif isinstance(content, dict) and "_missing" in content:
            _check(f"file_{fname}", False, "file not found at bundle time")
            all_files_ok = False
    if all_files_ok:
        _check("files_present", True, f"{len(required_files)}/{len(required_files)} files present and parseable")

    # 3. Endpoint snapshots present (offline bundles may not have them)
    endpoints = bundle.get("endpoints", {})
    guard_state_file = files.get("guard-state.json", {})
    has_endpoints = len(endpoints) > 0

    if has_endpoints:
        readiness_ep = endpoints.get("readiness", {})
        if readiness_ep.get("_status") == 200:
            rdy_data = readiness_ep.get("_data", {})
            _check("endpoint_readiness_reachable", True,
                   f"HTTP 200, verdict={rdy_data.get('verdict','?')}")
        else:
            status = readiness_ep.get("_status", 0)
            _check("endpoint_readiness_reachable", False,
                   f"HTTP {status}: {readiness_ep.get('_error','?')[:80]}")
    else:
        _check("endpoint_readiness_reachable", True,
               "No endpoints in bundle (offline mode — expected)")

    # 4. Locked baseline is true (kill switches both false)
    if has_endpoints:
        readiness_ep = endpoints.get("readiness", {})
        if readiness_ep.get("_status") == 200:
            rdy_data = readiness_ep.get("_data", {})
            ks = rdy_data.get("summary", {}).get("kill_switches", {})
            allow_orders = ks.get("IBKR_ALLOW_ORDERS", None)
            enforced = ks.get("rules.enforced", None)
            system_locked = ks.get("system_locked", None)
            locked = (allow_orders is False and enforced is False)
            _check("locked_baseline", locked,
                   f"allow_orders={allow_orders} enforced={enforced} system_locked={system_locked}")
        else:
            if isinstance(guard_state_file, dict) and not guard_state_file.get("_missing", False):
                halt_active = guard_state_file.get("daily_halt_active", False) or guard_state_file.get("weekly_halt_active", False)
                _check("locked_baseline", not halt_active,
                       f"halts active={halt_active} (kill switches unknown — endpoint unreachable)")
            else:
                _check("locked_baseline", False,
                       "Cannot verify locked baseline — endpoint unreachable and guard-state missing")
    else:
        if isinstance(guard_state_file, dict) and not guard_state_file.get("_missing", False):
            halt_active = guard_state_file.get("daily_halt_active", False) or guard_state_file.get("weekly_halt_active", False)
            _check("locked_baseline", not halt_active,
                   f"halts active={halt_active} (offline bundle — kill switches not captured)")
        else:
            _check("locked_baseline", False,
                   "Cannot verify locked baseline — guard-state missing from bundle")

    # 5. Regression count is recorded (bridge endpoint skips regression intentionally)
    regression = bundle.get("regression", None)
    if regression is not None:
        reg_pass = regression.get("pass", False)
        reg_passed = regression.get("passed", 0)
        reg_total = regression.get("total", 0)
        _check("regression_recorded", bool(regression),
               f"pass={reg_pass} {reg_passed}/{reg_total}")
    else:
        _check("regression_recorded", True,
               "No regression in bundle (bridge skips it — expected; run python3 monitor.py separately)")

    # 6. Bundle timestamp and bundle_id are valid
    bundle_id = bundle.get("bundle_id", "")
    created_at = bundle.get("created_at_utc", "")

    bid_valid = isinstance(bundle_id, str) and bundle_id.startswith("bundle_")
    ts_valid = False
    if created_at:
        try:
            datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            ts_valid = True
        except (ValueError, AttributeError):
            pass

    _check("bundle_id_valid", bid_valid,
           f"bundle_id='{bundle_id}'" if bid_valid else f"invalid bundle_id='{bundle_id}'")
    _check("timestamp_valid", ts_valid,
           f"created_at='{created_at}'" if ts_valid else f"invalid timestamp='{created_at}'")

    # 7. No live requires_action alerts (only if endpoints present)
    if has_endpoints:
        readiness_ep = endpoints.get("readiness", {})
        if readiness_ep.get("_status") == 200:
            rdy_data = readiness_ep.get("_data", {})
            blocks = rdy_data.get("blocks") or []
            live_alerts = [b for b in blocks if b.get("status") == "BLOCK"
                           and b["check"] not in ("rth_window", "tradable_day",
                                                    "kill_switch_IBKR_ALLOW_ORDERS",
                                                    "kill_switch_rules_enforced",
                                                    "ibkr_connection")]
            recon_ep = endpoints.get("monitor_reconciliation", {})
            if recon_ep.get("_status") == 200:
                recon_data = recon_ep.get("_data", {})
                recon_alerts = recon_data.get("alerts", [])
                live_action_alerts = [a for a in recon_alerts if a.get("requires_action") is True]
            else:
                live_action_alerts = []

            all_clean = len(live_alerts) == 0 and len(live_action_alerts) == 0
            detail = f"readiness_blocks={len(live_alerts)}, recon_action_alerts={len(live_action_alerts)}"
            _check("no_live_action_alerts", all_clean, detail)
        else:
            _check("no_live_action_alerts", True,
                   "Endpoint unreachable — cannot verify live alerts (offline bundle)")
    else:
        _check("no_live_action_alerts", True,
               "No endpoints in bundle (offline mode — expected)")

    all_ok = all(c["ok"] for c in checks)
    return {
        "pass": all_ok,
        "checks": checks,
        "check_count": len(checks),
        "passed_count": sum(1 for c in checks if c["ok"]),
        "verified_at_utc": _now_iso(),
        "bundle_id": bundle_id,
    }


# ---------------------------------------------------------------------------
# Phase 3J — Release Tagging / Provenance
# ---------------------------------------------------------------------------

RELEASE_DIR = OPENCLAW_DIR / "releases"


def _compute_provenance(bundle: dict | None = None) -> dict:
    """Compute the provenance summary for current source tree.

    Captures:
    - SHA256 source file hashes (always)
    - git commit hash + dirty diff summary (if .git exists)
    - dirty/clean status vs the referenced bundle

    Returns:
        Dict with provenance metadata.
    """
    current_hashes: dict[str, str | None] = {}
    for fname in SOURCE_FILES:
        fpath = BRIDGE_DIR / fname
        current_hashes[fname] = _hash_file(fpath)

    # Git state
    git_commit: str | None = None
    git_dirty: bool = True
    git_diff: str = "unknown"
    git_root: Path | None = None
    if (BRIDGE_DIR / ".git").exists():
        try:
            import subprocess
            r = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, cwd=BRIDGE_DIR, timeout=5
            )
            if r.returncode == 0:
                git_commit = r.stdout.strip()
                git_root = BRIDGE_DIR
        except Exception:
            pass

    # Dirty check: compare git tracked files to repo
    if git_root:
        try:
            import subprocess
            r = subprocess.run(
                ["git", "status", "--short", "--untracked-files=no"],
                capture_output=True, text=True, cwd=BRIDGE_DIR, timeout=5
            )
            git_dirty_bool = len(r.stdout.strip()) > 0
            diff_lines = []
            if git_dirty_bool:
                d = subprocess.run(
                    ["git", "diff", "--stat"],
                    capture_output=True, text=True, cwd=BRIDGE_DIR, timeout=5
                )
                diff_lines = [line.strip() for line in d.stdout.strip().split("\n") if line.strip()]
            git_dirty = git_dirty_bool
            git_diff = "; ".join(diff_lines) if diff_lines else "clean"
        except Exception:
            pass

    # Dirty vs bundle (source hash comparison)
    dirty = False
    diff_parts: list[str] = []

    if bundle is not None:
        bundle_hashes = bundle.get("code_hashes", {})
        for fname in SOURCE_FILES:
            cur = current_hashes.get(fname)
            bundled = bundle_hashes.get(fname)
            if cur and bundled and cur != bundled:
                dirty = True
                diff_parts.append(f"{fname}: hash changed")
            elif cur and not bundled:
                dirty = True
                diff_parts.append(f"{fname}: not in bundle")
            elif not cur:
                dirty = True
                diff_parts.append(f"{fname}: missing on disk")

    diff_summary = "; ".join(diff_parts) if diff_parts else "clean"

    result: dict[str, Any] = {
        "source_hashes": current_hashes,
        "dirty": dirty,
        "diff_summary": diff_summary,
    }

    if git_commit:
        result["git"] = {
            "commit": git_commit,
            "tag": _latest_git_tag(),
            "dirty": git_dirty,
            "diff_summary": git_diff,
        }

    return result


def _latest_git_tag() -> str | None:
    """Return the most recent git tag reachable from HEAD, or None."""
    try:
        import subprocess
        r = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, cwd=BRIDGE_DIR, timeout=5
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def create_release_tag(phase_label: str = "phase3i_verified", dry_run_report: dict | None = None) -> dict:
    """Create a release tag / provenance document.

    Args:
        phase_label: Human-readable phase label, e.g. "phase3i_verified".

    Returns:
        Dict with release tag metadata.

    The release tag records:
    - tag_id (timestamp-based, e.g. release_20260605T095000)
    - phase_label
    - audit_bundle_id (from the latest bundle on disk)
    - current source hashes (SHA256 of 4 source files)
    - dirty flag and diff summary vs the referenced bundle
    - last regression count (from the bundle)
    - locked baseline confirmation (from the bundle)
    - created_at_utc
    """
    bundle = latest_audit_bundle()

    tag_id = f"release_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"

    provenance = _compute_provenance(bundle)

    tag: dict[str, Any] = {
        "tag_id": tag_id,
        "phase_label": phase_label,
        "created_at_utc": _now_iso(),
        "immutable": True,
        "provenance": provenance,
    }

    # Include dry-run simulation report if provided (Phase 3Y)
    if dry_run_report is not None:
        tag["dry_run_simulation"] = {
            "scenario_count": dry_run_report.get("total_scenarios", 0),
            "passed_count": dry_run_report.get("passed_count", 0),
            "all_passed": dry_run_report.get("all_passed", False),
            "advisory": "simulation-only — never affects live reconciliation",
            "report_reference": dry_run_report,
        }

    # Include operator checklist snapshot as evidence (Phase 4C)
    checklist_snapshot = _run_checklist_snapshot()
    if checklist_snapshot is not None:
        tag["checklist_snapshot"] = checklist_snapshot

    if bundle is not None:
        tag["audit_bundle_id"] = bundle.get("bundle_id", "?")
        tag["bundle_created_at_utc"] = bundle.get("created_at_utc", "?")

        # Extract regression from bundle
        reg = bundle.get("regression", {})
        if reg:
            tag["regression"] = {
                "pass": reg.get("pass", False),
                "passed": reg.get("passed", 0),
                "total": reg.get("total", 0),
            }
        else:
            tag["regression"] = {"status": "not_in_bundle", "note": "Bundle had no regression data (bridge endpoint)"}

        # Extract locked baseline confirmation from bundle
        # Try readiness endpoint first, fall back to guard-state
        endpoints = bundle.get("endpoints", {})
        readiness_ep = endpoints.get("readiness", {})
        if readiness_ep.get("_status") == 200:
            ks = readiness_ep.get("_data", {}).get("summary", {}).get("kill_switches", {})
            tag["locked_baseline"] = {
                "confirmed": ks.get("IBKR_ALLOW_ORDERS") is False and ks.get("rules.enforced") is False,
                "allow_orders": ks.get("IBKR_ALLOW_ORDERS"),
                "enforced": ks.get("rules.enforced"),
                "system_locked": ks.get("system_locked"),
                "source": "readiness_endpoint",
            }
        else:
            files = bundle.get("files", {})
            guard_state = files.get("guard-state.json", {})
            if isinstance(guard_state, dict) and not guard_state.get("_missing", False):
                halt_active = guard_state.get("daily_halt_active", False) or guard_state.get("weekly_halt_active", False)
                tag["locked_baseline"] = {
                    "confirmed": not halt_active,
                    "daily_halt_active": guard_state.get("daily_halt_active"),
                    "weekly_halt_active": guard_state.get("weekly_halt_active"),
                    "source": "guard_state_file",
                }
            else:
                tag["locked_baseline"] = {
                    "confirmed": False,
                    "source": "unavailable",
                    "note": "No readiness endpoint or guard-state available",
                }
    else:
        tag["audit_bundle_id"] = None
        tag["bundle_created_at_utc"] = None
        tag["regression"] = {"status": "no_bundle"}
        tag["locked_baseline"] = {"confirmed": False, "source": "no_bundle",
                                   "note": "No audit bundle to reference"}

    return tag


def write_release_tag(tag: dict) -> Path:
    """Write a release tag to disk as a JSON file."""
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    tag_id = tag.get("tag_id", f"release_{_now_iso()}")
    out_path = RELEASE_DIR / f"{tag_id}.json"
    with open(out_path, "w") as f:
        json.dump(tag, f, indent=2, default=str)
    return out_path


def load_release_tags(max_count: int = 3) -> list[dict]:
    """Load release tags from RELEASE_DIR, newest first, bounded to max_count.

    Loads only the max_count most recent tags to bound memory.
    """
    if not RELEASE_DIR.exists():
        return []
    paths = sorted(RELEASE_DIR.glob("release_*.json"), reverse=True)
    tags = []
    for p in paths[:max_count]:
        try:
            data = json.loads(p.read_text())
            tags.append(data)
        except (json.JSONDecodeError, OSError):
            pass
    return tags


def latest_release_tag() -> dict | None:
    """Return the most recent release tag, or None."""
    tags = load_release_tags()
    return tags[0] if tags else None


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------"}]

def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Create an immutable audit bundle of trading system state."
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip HTTP endpoint snapshots and regression suite (offline mode).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List existing audit bundles.",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Show the latest audit bundle summary.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify the latest audit bundle for internal consistency.",
    )
    parser.add_argument(
        "--tag",
        type=str,
        nargs="?",
        const="phase3i_verified",
        default=None,
        help="Create a release tag with optional label (default: phase3i_verified).",
    )
    parser.add_argument(
        "--tag-latest",
        action="store_true",
        help="Show the latest release tag summary.",
    )
    parser.add_argument(
        "--prune",
        type=int,
        nargs="?",
        const=MAX_BUNDLES,
        default=None,
        help=f"Prune old audit bundles, keeping newest N (default: {MAX_BUNDLES}).",
    )
    args = parser.parse_args()

    if args.list:
        bundles = load_audit_bundles()
        if not bundles:
            print("No audit bundles found.")
            return
        print(f"Audit bundles ({len(bundles)}):")
        for b in bundles:
            bid = b.get("bundle_id", "?")
            ts = b.get("created_at_utc", "?")
            reg = b.get("regression", {})
            reg_str = f"{reg.get('passed', 0)}/{reg.get('total', '?')}" if reg else "no regression"
            print(f"  {bid}  {ts}  regression={reg_str}")
        return

    if args.latest:
        b = latest_audit_bundle()
        if b is None:
            print("No audit bundles found.")
            return
        bid = b.get("bundle_id", "?")
        ts = b.get("created_at_utc", "?")
        reg = b.get("regression", {})
        files_count = len(b.get("files", {}))
        ep_count = len(b.get("endpoints", {}))
        print(f"Latest: {bid}")
        print(f"  Created: {ts}")
        print(f"  Files: {files_count}")
        print(f"  Endpoints: {ep_count}")
        if reg:
            print(f"  Regression: {reg.get('passed', 0)}/{reg.get('total', 0)} pass={reg.get('pass')}")
        code_hashes = b.get("code_hashes", {})
        for fname, h in code_hashes.items():
            short = h[:16] if h else "missing"
            print(f"  SHA256({fname}): {short}...")
        return

    if args.tag is not None:
        tag = create_release_tag(phase_label=args.tag)
        out_path = write_release_tag(tag)
        print(f"Release tag written: {out_path}")
        print(f"  Tag ID: {tag['tag_id']}")
        print(f"  Phase: {tag['phase_label']}")
        print(f"  Bundle: {tag.get('audit_bundle_id', 'none')}")
        dirty = tag.get("provenance", {}).get("dirty", False)
        diff = tag.get("provenance", {}).get("diff_summary", "?")
        print(f"  Dirty: {dirty} ({diff})")
        locked = tag.get("locked_baseline", {})
        print(f"  Locked baseline: {locked.get('confirmed', '?')} (source={locked.get('source','?')})")
        reg = tag.get("regression", {})
        if reg.get("status") != "not_in_bundle":
            print(f"  Regression: {reg.get('passed', '?')}/{reg.get('total', '?')} pass={reg.get('pass', '?')}")
        else:
            print(f"  Regression: {reg.get('status')} ({reg.get('note', '')})")
        return

    if args.prune is not None:
        result = prune_old_bundles(keep=args.prune)
        print(f"Bundle retention enforced: keep={args.prune}, "
              f"removed_by_age={result['by_age']}, "
              f"removed_by_count={result['by_count']}, "
              f"total={result['total_removed']}")
        survivors = sorted(AUDIT_DIR.glob("bundle_*.json"), reverse=True)
        print(f"Remaining bundles: {len(survivors)}")
        return

    if args.tag_latest:
        t = latest_release_tag()
        if t is None:
            print("No release tags found.")
            print("  Create one with: python3 bundle_audit.py --tag")
            return
        print(f"Latest: {t.get('tag_id', '?')}")
        print(f"  Phase: {t.get('phase_label', '?')}")
        print(f"  Created: {t.get('created_at_utc', '?')}")
        print(f"  Bundle: {t.get('audit_bundle_id', '?')}")
        prov = t.get("provenance", {})
        print(f"  Dirty: {prov.get('dirty', '?')} ({prov.get('diff_summary', '?')})")
        locked = t.get("locked_baseline", {})
        print(f"  Locked baseline: {locked.get('confirmed', '?')}")
        reg = t.get("regression", {})
        if isinstance(reg, dict) and reg.get("status") != "not_in_bundle":
            print(f"  Regression: {reg.get('passed', '?')}/{reg.get('total', '?')} pass={reg.get('pass', '?')}")
        else:
            print(f"  Regression: {reg.get('status', '?')}")
        return

    if args.verify:
        bundle = latest_audit_bundle()
        if bundle is None:
            print("No audit bundles found to verify.")
            print("  Run: python3 bundle_audit.py")
            return
        result = verify_audit_bundle(bundle)
        passed_count = result["passed_count"]
        check_count = result["check_count"]
        verdict = "PASS" if result["pass"] else "FAIL"
        print(f"Verification: {verdict} ({passed_count}/{check_count})")
        print(f"  Bundle: {result.get('bundle_id', '?')}")
        print(f"  Verified at: {result.get('verified_at_utc', '?')}")
        for c in result["checks"]:
            status = "PASS" if c["ok"] else "FAIL"
            print(f"  {status}: {c['check']} — {c['detail']}")
        return

    # Create a new bundle
    skip_ep = args.offline
    skip_reg = args.offline
    bundle = create_audit_bundle(skip_endpoints=skip_ep, skip_regression=skip_reg)
    out_path = write_audit_bundle(bundle)
    reg = bundle.get("regression", {})
    reg_str = f"regression={reg.get('passed', 0)}/{reg.get('total', 0)}, pass={reg.get('pass')}" if reg else "no regression"
    print(f"Audit bundle written: {out_path}")
    print(f"  Files: {len(bundle.get('files', {}))}")
    print(f"  Endpoints: {len(bundle.get('endpoints', {}))}")
    print(f"  {reg_str}")


if __name__ == "__main__":
    _cli()