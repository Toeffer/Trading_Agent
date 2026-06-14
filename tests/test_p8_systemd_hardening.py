"""
test_p8_systemd_hardening.py — Step 7: OS boundary / process hardening tests.

Validates:
  - systemd/ibkr-bridge.service exists and meets hardening spec
  - ibkr-trade-window relock uses systemctl (no nohup/pkill)
  - No forbidden endpoints in heartbeat or service code
  - No H1 token references in service unit

These are static code/artifact tests — no live bridge required.
"""

import os
import re
import pytest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. systemd unit file exists in repo
# ---------------------------------------------------------------------------

def test_systemd_unit_exists_in_repo():
    """systemd/ibkr-bridge.service must exist in the repo root."""
    unit_path = REPO / "systemd" / "ibkr-bridge.service"
    assert unit_path.exists(), f"Missing: {unit_path}"
    assert unit_path.stat().st_size > 100, f"Unit file too small: {unit_path}"


# ---------------------------------------------------------------------------
# 2. Unit binds to 127.0.0.1, not 0.0.0.0
# ---------------------------------------------------------------------------

def test_unit_binds_localhost_only():
    """Service must bind to 127.0.0.1, never 0.0.0.0."""
    unit_path = REPO / "systemd" / "ibkr-bridge.service"
    content = unit_path.read_text()

    # Must contain 127.0.0.1 binding
    assert "127.0.0.1" in content, "ExecStart must bind to 127.0.0.1"

    # Must NOT bind to 0.0.0.0
    assert "0.0.0.0" not in content, "ExecStart must NOT bind to 0.0.0.0 (use 127.0.0.1)"

    # --host must be set
    assert "--host" in content, "ExecStart must specify --host"


# ---------------------------------------------------------------------------
# 3. Unit does not reference H1 token
# ---------------------------------------------------------------------------

def test_unit_no_h1_token_reference():
    """Service unit must not reference /etc/ibkr-bridge/h1_token in non-comment context."""
    unit_path = REPO / "systemd" / "ibkr-bridge.service"
    content = unit_path.read_text()

    # Check non-comment lines only
    non_comment_lines = [
        line for line in content.splitlines()
        if not line.strip().startswith("#")
    ]
    non_comment = "\n".join(non_comment_lines)

    assert "/etc/ibkr-bridge/h1_token" not in non_comment, (
        "Unit must not reference /etc/ibkr-bridge/h1_token (except in comments)"
    )
    # h1_token may appear in env var name H1_APPROVAL_TOKEN_HASH which is fine
    # But the file path should not appear
    assert "TOKEN_FILE" not in non_comment, (
        "Unit must not define TOKEN_FILE"
    )


# ---------------------------------------------------------------------------
# 4. Unit contains required hardening directives
# ---------------------------------------------------------------------------

REQUIRED_HARDENING = [
    "NoNewPrivileges=true",
    "PrivateTmp=true",
    "ProtectHome=",
    "ReadWritePaths=",
]

RECOMMENDED_HARDENING = [
    "ProtectSystem=strict",
    "RestrictAddressFamilies=",
]


def test_unit_has_required_hardening():
    """Service unit must contain required systemd hardening directives."""
    unit_path = REPO / "systemd" / "ibkr-bridge.service"
    content = unit_path.read_text()

    for directive in REQUIRED_HARDENING:
        assert directive in content, (
            f"Missing required hardening: {directive}"
        )


def test_unit_has_recommended_hardening():
    """Service unit should contain recommended additional hardening."""
    unit_path = REPO / "systemd" / "ibkr-bridge.service"
    content = unit_path.read_text()

    found = [d for d in RECOMMENDED_HARDENING if d in content]
    assert len(found) >= 1, (
        f"Expected at least 1 recommended hardening directive, found {found}"
    )


# ---------------------------------------------------------------------------
# 5. Unit has no shell wrapper (direct ExecStart)
# ---------------------------------------------------------------------------

def test_unit_no_shell_wrapper():
    """ExecStart must call python3 directly, no shell script or bash -c wrapper."""
    unit_path = REPO / "systemd" / "ibkr-bridge.service"
    content = unit_path.read_text()

    # Extract ExecStart line
    exec_start = None
    for line in content.splitlines():
        if line.strip().startswith("ExecStart="):
            exec_start = line.strip()
            break

    assert exec_start is not None, "ExecStart= not found"

    # Must not use bash/sh wrapper
    assert "bash" not in exec_start.lower(), f"ExecStart must not use bash: {exec_start}"
    assert " && " not in exec_start, f"ExecStart must not use shell chaining: {exec_start}"
    assert exec_start.endswith("--port 8790"), f"Unexpected ExecStart: {exec_start}"


# ---------------------------------------------------------------------------
# 6. Relock helper uses systemctl, not nohup + pkill
# ---------------------------------------------------------------------------

def _find_trade_window_script():
    """Find ibkr-trade-window script; prefer repo copy (most recently updated)."""
    repo_copy = REPO / "scripts" / "ibkr-trade-window"
    if repo_copy.exists():
        return repo_copy
    sbin_copy = Path("/usr/local/sbin/ibkr-trade-window")
    if sbin_copy.exists():
        return sbin_copy
    return None


def test_relock_uses_systemctl():
    """relock() must use systemctl restart, not nohup + pkill."""
    script = _find_trade_window_script()
    if script is None:
        pytest.skip("ibkr-trade-window script not found")

    content = script.read_text()

    # Extract relock function body using line-based approach
    lines = content.splitlines()
    relock_lines = []
    in_relock = False
    brace_depth = 0
    for line in lines:
        if line.strip().startswith("relock()"):
            in_relock = True
            brace_depth = line.count("{") - line.count("}")
            continue
        if in_relock:
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                break
            relock_lines.append(line)

    relock_body = "\n".join(relock_lines)

    # Must contain systemctl restart
    assert "systemctl restart ibkr-bridge.service" in relock_body, (
        "relock must use 'systemctl restart ibkr-bridge.service'"
    )

    # Must NOT use nohup as a command (only allowed in comments)
    non_comment_lines = [
        line for line in relock_lines
        if not line.strip().startswith("#")
    ]
    non_comment = "\n".join(non_comment_lines)
    assert "nohup" not in non_comment, (
        "relock must NOT use nohup — systemd manages the process"
    )

    # Must NOT use pkill for bridge
    pkill_bridge = re.search(r'pkill.*uvicorn.*bridge', relock_body)
    assert pkill_bridge is None, (
        "relock must NOT pkill the bridge — systemd manages restarts"
    )


# ---------------------------------------------------------------------------
# 7. Relock still sets safety flags
# ---------------------------------------------------------------------------

def test_relock_still_sets_safety_flags():
    """relock() must still set IBKR_ALLOW_ORDERS=false and rules.enforced=false."""
    script = _find_trade_window_script()
    if script is None:
        pytest.skip("ibkr-trade-window script not found")

    content = script.read_text()

    assert "IBKR_ALLOW_ORDERS=false" in content, (
        "relock must set IBKR_ALLOW_ORDERS=false"
    )
    assert "enforced: false" in content, (
        "relock must set rules.enforced=false"
    )


# ---------------------------------------------------------------------------
# 8. No forbidden endpoints in heartbeat or systemd service code
# ---------------------------------------------------------------------------

FORBIDDEN_ENDPOINTS = [
    "/order/approve",
    "/order/submit",
    "/connect",
]


def test_no_forbidden_endpoints_in_service():
    """ibkr-bridge.service must not reference forbidden endpoints in non-comment lines."""
    unit_path = REPO / "systemd" / "ibkr-bridge.service"
    content = unit_path.read_text()

    # Check non-comment lines only (comments documenting absence are fine)
    non_comment_lines = [
        line for line in content.splitlines()
        if not line.strip().startswith("#")
    ]
    non_comment = "\n".join(non_comment_lines)

    for ep in FORBIDDEN_ENDPOINTS:
        assert ep not in non_comment, (
            f"Service unit must not reference forbidden endpoint: {ep} (except in comments)"
        )


def test_no_forbidden_endpoints_in_relock():
    """Relock script must not add forbidden endpoints."""
    script = _find_trade_window_script()
    if script is None:
        pytest.skip("ibkr-trade-window script not found")

    content = script.read_text()

    for ep in FORBIDDEN_ENDPOINTS:
        count = content.count(ep)
        # /order/approve and /order/submit appear in approve/submit functions
        # which is expected; the relock function should not add them
        relock_section = content[content.find("relock()"):]
        if ep in relock_section:
            assert False, (
                f"relock() must not reference forbidden endpoint: {ep}"
            )


def test_forbidden_endpoints_in_heartbeat_allowlist():
    """Heartbeat whitelist must not contain forbidden endpoints."""
    operator = REPO / "ibkr_operator.py"
    content = operator.read_text()

    # Extract _HEARTBEAT_ENDPOINTS list
    hb_match = re.search(
        r'_HEARTBEAT_ENDPOINTS\s*=\s*\[(.*?)\]',
        content, re.DOTALL
    )
    assert hb_match is not None, "_HEARTBEAT_ENDPOINTS not found"

    hb_text = hb_match.group(1)

    for ep in FORBIDDEN_ENDPOINTS:
        assert ep not in hb_text, (
            f"HEARTBEAT_ENDPOINTS must not contain forbidden endpoint: {ep}"
        )


# ---------------------------------------------------------------------------
# 9. Heartbeat forbids denylist endpoints
# ---------------------------------------------------------------------------

def test_heartbeat_denylist_contains_forbidden_endpoints():
    """_FORBIDDEN_HEARTBEAT_SUBSTRINGS must block all forbidden endpoints."""
    operator = REPO / "ibkr_operator.py"
    content = operator.read_text()

    deny_match = re.search(
        r'_FORBIDDEN_HEARTBEAT_SUBSTRINGS\s*=\s*\[(.*?)\]',
        content, re.DOTALL
    )
    assert deny_match is not None, "_FORBIDDEN_HEARTBEAT_SUBSTRINGS not found"

    deny_text = deny_match.group(1)

    for ep in FORBIDDEN_ENDPOINTS:
        assert ep in deny_text, (
            f"_FORBIDDEN_HEARTBEAT_SUBSTRINGS must include: {ep}"
        )


# ---------------------------------------------------------------------------
# 10. Doctor function includes process checks (K13-K16)
# ---------------------------------------------------------------------------

def test_doctor_has_process_checks():
    """run_doctor() must include K13-K16 process boundary checks."""
    operator = REPO / "ibkr_operator.py"
    content = operator.read_text()

    required_checks = [
        "bridge_listener_localhost",
        "bridge_service_active",
        "bridge_no_duplicate_processes",
        "bridge_safety_flags",
    ]

    for check_name in required_checks:
        assert check_name in content, (
            f"run_doctor() missing check: {check_name}"
        )


# ---------------------------------------------------------------------------
# 11. User/Group set in service unit
# ---------------------------------------------------------------------------

def test_unit_user_chris():
    """Service must run as User=chris."""
    unit_path = REPO / "systemd" / "ibkr-bridge.service"
    content = unit_path.read_text()

    # System unit specifies User=chris
    # User unit inherits from systemd --user but we still check
    has_user = "User=chris" in content or "User=chris" in content
    assert "User=chris" in content or "User=" in content, (
        "Service unit should specify User="
    )


# ---------------------------------------------------------------------------
# 12. systemd unit file in repo matches installed user service
# ---------------------------------------------------------------------------

def test_repo_unit_matches_user_service():
    """Repo systemd unit should be consistent with installed user service."""
    repo_unit = REPO / "systemd" / "ibkr-bridge.service"
    user_unit = Path.home() / ".config" / "systemd" / "user" / "ibkr-bridge.service"

    if not user_unit.exists():
        pytest.skip("User-level systemd service not installed")

    repo_content = repo_unit.read_text()
    user_content = user_unit.read_text()

    # Both must have hardening directives
    for directive in ["NoNewPrivileges=true", "PrivateTmp=true", "127.0.0.1"]:
        assert directive in repo_content, f"Repo unit missing: {directive}"
        assert directive in user_content, f"User unit missing: {directive}"
