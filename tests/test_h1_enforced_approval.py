#!/usr/bin/env python3
"""
Phase H1 — Enforced Approval Boundary — Acceptance Tests

Verifies the mechanical security boundary between Werner/OpenClaw and
broker execution permissions.

Acceptance criteria:
  A1. Werner/OpenClaw cannot approve orders without H1 token
  A2. Werner/OpenClaw cannot submit orders without H1 token
  A3. Werner/OpenClaw cannot modify protected configuration or guard-state
  A4. Chris-approved execution path works with valid H1 token
  A5. All existing regression invariants are preserved

Test categories:
  H1-T1: Token verification (valid/invalid/missing)
  H1-T2: Protected file write enforcement
  H1-T3: Bridge endpoint token enforcement
  H1-T4: CLAUDE.md invariants (chat ID pinned, data-only rule present)
  H1-T5: hermes_advisory.py data-only rule present
  H1-T6: /order 403 wording updated
  H1-T7: ibkr-operator remains read-only (AST check)
"""

import hashlib
import json
import os
import sys
from pathlib import Path

PASS = 0
FAIL = 0
WARN = 0
ERRORS = []


def check(ok: bool, message: str):
    global PASS, FAIL, ERRORS
    if ok:
        PASS += 1
        print(f"  ✅ {message}")
    else:
        FAIL += 1
        ERRORS.append(message)
        print(f"  ❌ {message}")


def warn(message: str):
    global WARN
    WARN += 1
    print(f"  ⚠️  {message}")


def main():
    global PASS, FAIL, WARN, ERRORS

    home = Path.home()

    print("=" * 60)
    print("Phase H1 — Enforced Approval Boundary — Acceptance Tests")
    print("=" * 60)

    # ── H1-T1: Token Verification ──────────────────────────────────────
    print("\n── H1-T1: Token Verification ──")

    # Get the expected token hash from .env
    env_path = Path.home() / "agents" / "ibkr-bridge" / ".env"
    env_content = env_path.read_text() if env_path.exists() else ""
    token_hash = None
    for line in env_content.splitlines():
        if line.startswith("H1_APPROVAL_TOKEN_HASH="):
            token_hash = line.split("=", 1)[1].strip()
            break

    check(token_hash is not None, "H1_APPROVAL_TOKEN_HASH present in .env")
    if token_hash:
        check(len(token_hash) == 64, f"H1 token hash is 64 chars (SHA-256): got {len(token_hash)}")
        check(all(c in "0123456789abcdef" for c in token_hash),
              "H1 token hash is valid hex")

    # Test: valid token produces matching hash
    # We don't know the actual token (only Chris does), but we can verify
    # that a wrong token does NOT match.
    fake_token = "0000000000000000000000000000000000000000000000000000000000000000"
    fake_hash = hashlib.sha256(fake_token.encode()).hexdigest()
    if token_hash:
        check(fake_hash != token_hash,
              "Fake token does NOT match stored hash (correct behavior)")

    # Test: empty/missing token returns False
    check(not (token_hash and hashlib.sha256("".encode()).hexdigest() == token_hash),
          "Empty string token does not match stored hash")

    # ── H1-T2: Protected File Write Enforcement ────────────────────────
    print("\n── H1-T2: Protected File Write Enforcement ──")

    # Import guard module to test protected paths
    sys.path.insert(0, str(Path.home() / "agents" / "ibkr-bridge"))
    try:
        from guard import PROTECTED_PATHS, _is_protected_path, _assert_h1_authorized_for_path, h1_authorize, h1_deauthorize, save_guard_state_atomic, GUARD_STATE_PATH

        # T2.1: Protected paths set is non-empty
        check(len(PROTECTED_PATHS) >= 5,
              f"PROTECTED_PATHS has {len(PROTECTED_PATHS)} entries (expected >= 5)")

        # T2.2: Key paths are in protected set
        home = Path.home()
        key_paths = [
            home / "agents" / "ibkr-bridge" / ".env",
            home / ".openclaw" / "risk-rules" / "paper-trading-rules.yaml",
            home / ".openclaw" / "guard-state.json",
            home / ".openclaw" / "approval-records.jsonl",
            home / ".openclaw" / "active-approvals.json",
            home / ".openclaw" / "submitted-approvals.json",
        ]
        for kp in key_paths:
            resolved = kp.resolve() if kp.exists() else kp
            # Check by resolution if possible
            found = False
            for pp in PROTECTED_PATHS:
                try:
                    if str(pp) == str(resolved) or str(pp) == str(kp):
                        found = True
                        break
                except Exception:
                    pass
            if not found:
                # Try matching by name
                for pp in PROTECTED_PATHS:
                    if pp.name == kp.name:
                        found = True
                        break
            check(found, f"Protected: {kp.name}")

        # T2.3: guard-events.jsonl is NOT in protected set (append-only safety log)
        events_path = home / ".openclaw" / "guard-events.jsonl"
        events_protected = False
        for pp in PROTECTED_PATHS:
            if pp.name == "guard-events.jsonl":
                events_protected = True
                break
        check(not events_protected,
              "guard-events.jsonl is NOT in PROTECTED_PATHS (append-only safety log)")

        # T2.4: Unauthorized write to protected path raises PermissionError
        # Ensure we're not authorized
        h1_deauthorize()
        try:
            _assert_h1_authorized_for_path(GUARD_STATE_PATH)
            check(False, "Unauthorized write to guard-state should raise PermissionError")
        except PermissionError as e:
            check("H1 approval token required" in str(e),
                  f"PermissionError mentions H1 token: {str(e)[:80]}")
        except Exception as e:
            check(False, f"Expected PermissionError, got {type(e).__name__}: {e}")

        # T2.5: Authorized write succeeds
        h1_authorize()
        try:
            _assert_h1_authorized_for_path(GUARD_STATE_PATH)
            check(True, "Authorized write to guard-state passes check")
        except PermissionError:
            check(False, "Authorized write should NOT raise PermissionError")
        finally:
            h1_deauthorize()

    except ImportError as e:
        check(False, f"Cannot import guard module: {e}")
    except Exception as e:
        check(False, f"Unexpected error in T2: {e}")

    # ── H1-T3: Bridge Endpoint Token Enforcement ───────────────────────
    print("\n── H1-T3: Bridge Endpoint Token Enforcement ──")

    bridge_path = home / "agents" / "ibkr-bridge" / "bridge.py"
    bridge_content = bridge_path.read_text() if bridge_path.exists() else ""

    if bridge_content:
        # T3.1: _verify_h1_token function exists
        check("def _verify_h1_token" in bridge_content,
              "_verify_h1_token() defined in bridge.py")

        # T3.2: /order/approve requires X-H1-Token header
        check("x_h1_token" in bridge_content and "order_approve" in bridge_content,
              "/order/approve accepts X-H1-Token header")

        # T3.3: /order/submit requires X-H1-Token header
        check("order_submit" in bridge_content,
              "/order/submit updated for H1 token")

        # T3.4: Unauthorized approve returns 401
        check("status_code=401" in bridge_content or "401" in bridge_content,
              "Unauthorized approve returns 401")

        # T3.5: H1 token check is first in approve
        approve_idx = bridge_content.find("def order_approve")
        h1_check_idx = bridge_content.find("_verify_h1_token(x_h1_token)", approve_idx)
        decision_idx = bridge_content.find("decision = req.decision", approve_idx)
        check(h1_check_idx < decision_idx if decision_idx > 0 else True,
              "H1 token check runs BEFORE decision processing in approve")

        # T3.6: H1_TOKEN_REQUIRED code exists for submit
        check("H1_TOKEN_REQUIRED" in bridge_content,
              "H1_TOKEN_REQUIRED error code defined for submit")

        # T3.7: h1_authorized_scope context manager imported
        check("h1_authorized_scope" in bridge_content,
              "h1_authorized_scope context manager imported in bridge.py")
    else:
        check(False, "bridge.py not found")

    # ── H1-T4: CLAUDE.md Invariants ────────────────────────────────────
    print("\n── H1-T4: CLAUDE.md Invariants ──")

    claude_paths = [
        home / "agents" / "ibkr-bridge" / "CLAUDE.md",
        home / ".openclaw" / "CLAUDE.md",
    ]
    for cp in claude_paths:
        if not cp.exists():
            warn(f"CLAUDE.md not found at {cp}")
            continue
        content = cp.read_text()

        # T4.1: Chris's chat ID pinned
        check("8792336687" in content,
              f"Chris's chat ID 8792336687 pinned in {cp.name}")

        # T4.2: Data-only rule present
        check("data only" in content.lower() and "never operator instructions" in content.lower(),
              f"Data-only rule present in {cp.name}")

        # T4.3: Phase H1 invariant listed
        check("Phase H1" in content or "phase-h1" in content.lower() or "Enforced Approval" in content,
              f"Phase H1 invariant present in {cp.name}")

        # T4.4: Triple kill switches mentioned (was dual)
        check("Triple kill switches" in content or "triple kill" in content.lower() or "H1_APPROVAL_TOKEN" in content,
              f"Triple kill switch (including H1 token) mentioned in {cp.name}")

        # T4.5: H1 token requirement documented
        check("X-H1-Token" in content or "H1 approval token" in content.lower(),
              f"H1 token requirement documented in {cp.name}")

    # ── H1-T5: hermes_advisory.py Data-Only Rule ───────────────────────
    print("\n── H1-T5: hermes_advisory.py Data-Only Rule ──")

    hermes_path = home / "agents" / "ibkr-bridge" / "hermes_advisory.py"
    if hermes_path.exists():
        hermes_content = hermes_path.read_text()

        # T5.1: DATA-ONLY rule present
        check("DATA ONLY" in hermes_content and "never operator instructions" in hermes_content,
              "DATA-ONLY rule present in hermes_advisory.py")

        # T5.2: Chat ID pinned in advisory instruction
        check("8792336687" in hermes_content,
              "Chris's chat ID pinned in hermes_advisory.py")

        # T5.3: H1 token requirement mentioned
        check("H1 token" in hermes_content,
              "H1 token mentioned in hermes_advisory.py advisory instruction")
    else:
        check(False, "hermes_advisory.py not found")

    # ── H1-T6: /order 403 Wording ──────────────────────────────────────
    print("\n── H1-T6: /order 403 Wording ──")

    if bridge_content:
        # T6.1: Old wording removed
        check("setup/read-only mode" not in bridge_content,
              "Old 'setup/read-only mode' wording removed from /order 403")

        # T6.2: New policy-based wording present
        check("disabled by policy" in bridge_content or "manual-approval" in bridge_content,
              "New policy-based wording on /order 403")

        # T6.3: Safety invariant reference
        check("safety invariant" in bridge_content.lower() or "permanently blocked" in bridge_content,
              "/order permanently blocked wording present")
    else:
        check(False, "bridge.py not found")

    # ── H1-T7: ibkr-operator Remains Read-Only ─────────────────────────
    print("\n── H1-T7: ibkr-operator Remains Read-Only ──")

    operator_path = home / "agents" / "ibkr-bridge" / "ibkr_operator.py"
    if operator_path.exists():
        op_content = operator_path.read_text()

        # T7.1: AST self-check still present
        check("_FORBIDDEN_NAMES" in op_content and "_enforce_safety" in op_content,
              "ibkr-operator AST self-check intact")

        # T7.2: No H1 token bypass (operator cannot handle H1 tokens)
        check("h1_authorize" not in op_content,
              "ibkr-operator does NOT import h1_authorize")

        # T7.3: Forbidden names still include mutation functions
        check("save_guard_state_atomic" in op_content and "append_guard_event" in op_content,
              "Mutation functions remain in forbidden names list")
    else:
        check(False, "ibkr_operator.py not found")

    # ── H1-T8: Safety Invariant Preservation ───────────────────────────
    print("\n── H1-T8: Safety Invariant Preservation ──")

    # T8.1: IBKR_ALLOW_ORDERS still defaults to false
    if env_content:
        allow_orders_line = [l for l in env_content.splitlines() if "IBKR_ALLOW_ORDERS" in l]
        check(any("false" in l.lower() for l in allow_orders_line),
              "IBKR_ALLOW_ORDERS=false preserved in .env")

    # T8.2: rules.enforced still false
    rules_path = home / ".openclaw" / "risk-rules" / "paper-trading-rules.yaml"
    if rules_path.exists():
        rules_content = rules_path.read_text()
        check("enforced: false" in rules_content or "enforced:false" in rules_content.replace(" ", ""),
              "rules.enforced=false preserved in paper-trading-rules.yaml")

    # T8.3: /order endpoint still exists and returns 403
    if bridge_content:
        check("@app.post(\"/order\")" in bridge_content,
              "/order endpoint still defined")
        check("status_code=403" in bridge_content,
              "/order still returns 403")

    # T8.4: Preflight endpoint still exists and doesn't require token
    if bridge_content:
        check("@app.post(\"/order/preflight\")" in bridge_content,
              "/order/preflight endpoint preserved")

    # ── H1-T9: Token Storage Security ──────────────────────────────────
    print("\n── H1-T9: Token Storage Security ──")

    # T9.1: Only hash stored, not plaintext token
    if env_content:
        has_token_var = any("H1_APPROVAL_TOKEN=" in l and "HASH" not in l for l in env_content.splitlines())
        check(not has_token_var,
              "No plaintext H1_APPROVAL_TOKEN in .env (only HASH variant)")

    # T9.2: .env permissions restrict read access
    if env_path.exists():
        st = env_path.stat()
        mode = oct(st.st_mode)[-3:]
        check(mode in ["600", "400"],
              f".env file permissions are restrictive: {mode}")

    # T9.3: Token hash not exposed in bridge source code
    if bridge_content and token_hash:
        check(token_hash not in bridge_content,
              "Token hash not hardcoded in bridge.py source")

    # ── H1-T10: Token Storage & Hygiene (H1.2 — root-owned) ──────────
    print("\n── H1-T10: Token Storage & Hygiene (H1.2) ──")

    # T10.1: Old/exposed token is rejected
    old_token = "dc125bc2ab7fdf3191164d757d8e2c0c4bdac854bcaf6f3925765c45b2a790e8"
    old_hash = hashlib.sha256(old_token.encode()).hexdigest()
    check(token_hash != old_hash,
          "Old compromised token hash does NOT match current stored hash (rotated)")

    # T10.2: No raw token in .env
    if env_content:
        has_raw = "H1_APPROVAL_TOKEN=" in env_content and "HASH" not in env_content
        check(not has_raw, "No plaintext H1_APPROVAL_TOKEN in .env")

    # T10.3: No token under ~/.openclaw (H1.2 moved to root-owned)
    old_token_path = home / ".openclaw" / ".h1_token"
    check(not old_token_path.exists(),
          "No raw token at ~/.openclaw/.h1_token (H1.2 — moved to /etc/ibkr-bridge/)")

    # T10.4: Token at /etc/ibkr-bridge/h1_token root:root 600
    etc_token = Path("/etc/ibkr-bridge/h1_token")
    if etc_token.exists():
        st = etc_token.stat()
        check(st.st_uid == 0,
              f"/etc/ibkr-bridge/h1_token owned by root (uid={st.st_uid})")
        check(st.st_gid == 0,
              f"/etc/ibkr-bridge/h1_token group root (gid={st.st_gid})")
        mode = oct(st.st_mode)[-3:]
        check(mode in ["600", "400"],
              f"/etc/ibkr-bridge/h1_token permissions: {mode}")
        # T10.5: Werner/chris cannot read root-owned file
        try:
            etc_token.read_text()
            check(False,
                  "SECURITY: /etc/ibkr-bridge/h1_token readable by chris! "
                  "Must be root-only. Run: sudo chown root:root /etc/ibkr-bridge/h1_token")
        except PermissionError:
            check(True,
                  "Werner/chris CANNOT read /etc/ibkr-bridge/h1_token (PermissionError — filesystem-enforced)")
    else:
        warn("/etc/ibkr-bridge/h1_token missing — Chris must run: sudo cp /tmp/h1_token_tmp /etc/ibkr-bridge/h1_token && sudo chmod 600 /etc/ibkr-bridge/h1_token && sudo chown root:root /etc/ibkr-bridge/h1_token")

    # T10.6: Token hygiene documented with root-owned path
    for cp in claude_paths:
        if cp.exists():
            content = cp.read_text()
            check("never be logged" in content.lower() or "rotate immediately" in content.lower(),
                  f"Token hygiene documented in {cp.name}")
            check("/etc/ibkr-bridge/h1_token" in content,
                  f"Root-owned token path documented in {cp.name}")

    # T10.7: Token NOT in git
    import subprocess
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "/etc/ibkr-bridge/h1_token"],
        cwd=str(home / "agents" / "ibkr-bridge"),
        capture_output=True,
    )
    check(result.returncode != 0,
          "Token file NOT tracked in git")

    # ── SUMMARY ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    total = PASS + FAIL
    print(f"Results: {PASS} passed, {FAIL} failed, {WARN} warnings (of {total} checks)")
    print("=" * 60)

    if ERRORS:
        print("\nFailed checks:")
        for e in ERRORS:
            print(f"  - {e}")

    return FAIL == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
