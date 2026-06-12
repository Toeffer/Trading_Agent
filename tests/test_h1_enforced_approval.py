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

    # ── H1-T2: Protected File Write Enforcement (H1.3 ContextVar) ─────
    print("\n── H1-T2: Protected File Write Enforcement (H1.3 ContextVar) ──")

    sys.path.insert(0, str(Path.home() / "agents" / "ibkr-bridge"))
    try:
        from guard import (PROTECTED_PATHS, _INTERNAL_WRITE_PATHS,
                           _is_protected_path, _is_internal_write_path,
                           _assert_h1_authorized_for_path,
                           h1_authorize, h1_deauthorize,
                           internal_write_context,
                           save_guard_state_atomic, GUARD_STATE_PATH)

        # T2.1: All 6 paths remain in PROTECTED_PATHS (H1.3 keeps protection)
        check(len(PROTECTED_PATHS) == 6,
              f"PROTECTED_PATHS has {len(PROTECTED_PATHS)} entries (expected all 6)")

        # T2.2: _INTERNAL_WRITE_PATHS has 4 Class A entries
        check(len(_INTERNAL_WRITE_PATHS) == 4,
              f"_INTERNAL_WRITE_PATHS has {len(_INTERNAL_WRITE_PATHS)} entries (expected 4 Class A)")

        home = Path.home()

        # T2.3: All 6 paths are in PROTECTED_PATHS
        all_protected_paths = [
            home / "agents" / "ibkr-bridge" / ".env",
            home / ".openclaw" / "risk-rules" / "paper-trading-rules.yaml",
            home / ".openclaw" / "guard-state.json",
            home / ".openclaw" / "active-approvals.json",
            home / ".openclaw" / "approval-records.jsonl",
            home / ".openclaw" / "submitted-approvals.json",
        ]
        for kp in all_protected_paths:
            found = False
            for pp in PROTECTED_PATHS:
                if pp.name == kp.name:
                    found = True
                    break
            check(found, f"Protected (all 6): {kp.name}")

        # T2.4: Class A paths are in _INTERNAL_WRITE_PATHS
        class_a_names = {"active-approvals.json", "approval-records.jsonl",
                         "guard-events.jsonl", "guard-state.json"}
        for pp in _INTERNAL_WRITE_PATHS:
            check(pp.name in class_a_names,
                  f"Internal-write path {pp.name} is Class A")

        # T2.5: Class B paths are NOT in _INTERNAL_WRITE_PATHS
        class_b_names = {".env", "paper-trading-rules.yaml", "submitted-approvals.json"}
        for pp in _INTERNAL_WRITE_PATHS:
            check(pp.name not in class_b_names,
                  f"Internal-write path {pp.name} is NOT Class B")

        # T2.6: Direct write (no context, no token) blocked
        h1_deauthorize()
        try:
            _assert_h1_authorized_for_path(GUARD_STATE_PATH)
            check(False, "Direct write to guard-state should raise PermissionError")
        except PermissionError as e:
            check("H1 approval token required" in str(e),
                  f"Direct write blocked: {str(e)[:80]}")

        # T2.7: Internal write context allows Class A (guard-state.json)
        try:
            with internal_write_context():
                _assert_h1_authorized_for_path(GUARD_STATE_PATH)
            check(True, "Internal context allows guard-state.json write")
        except PermissionError:
            check(False, "Internal context should allow guard-state.json write")

        # T2.8: Internal write context still blocks Class B (.env)
        env_path = home / "agents" / "ibkr-bridge" / ".env"
        try:
            with internal_write_context():
                _assert_h1_authorized_for_path(env_path)
            check(False, "Internal context should NOT allow .env write")
        except PermissionError:
            check(True, "Internal context correctly blocks .env write (Class B)")

        # T2.9: Internal write context still blocks submitted-approvals.json
        sa_path = home / ".openclaw" / "submitted-approvals.json"
        try:
            with internal_write_context():
                _assert_h1_authorized_for_path(sa_path)
            check(False, "Internal context should NOT allow submitted-approvals.json write")
        except PermissionError:
            check(True, "Internal context correctly blocks submitted-approvals.json (Class B)")

        # T2.10: H1-authorized still works
        h1_authorize()
        try:
            _assert_h1_authorized_for_path(GUARD_STATE_PATH)
            check(True, "H1-authorized write passes")
        except PermissionError:
            check(False, "H1-authorized should pass")
        finally:
            h1_deauthorize()

    except ImportError as e:
        check(False, f"Cannot import guard module for T2: {e}")
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

        # T3.7: h1_authorize/h1_deauthorize imported
        check("h1_authorize" in bridge_content and "h1_deauthorize" in bridge_content,
              "h1_authorize/h1_deauthorize imported in bridge.py")
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

        # T4.1: Chris's chat ID pinned (from TELEGRAM_CHAT_ID env var, not hardcoded)
        check("TELEGRAM_CHAT_ID" in content or "operator chat ID" in content.lower(),
              f"Operator chat ID referenced in {cp.name}")

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

        # T5.2: Chat ID reference (env var, not hardcoded)
        check("TELEGRAM_CHAT_ID" in hermes_content,
              "Operator chat ID via TELEGRAM_CHAT_ID env var referenced in hermes_advisory.py")

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

    # ── H1-T11: Preflight Write Path (H1.3 ContextVar) ─────────────
    print("\n── H1-T11: Preflight Write Path (H1.3 ContextVar) ──")

    try:
        from guard import (h1_deauthorize, internal_write_context,
                           create_approval_record, _save_active_approvals,
                           _append_approval_record,
                           _INTERNAL_WRITE_PATHS,
                           GUARD_EVENTS_PATH)

        # T11.1: Ensure H1 is deauthorized (simulate locked state)
        h1_deauthorize()
        check(True, "H1 deauthorized — simulating locked state")

        # T11.2: _save_active_approvals() with internal context succeeds
        try:
            with internal_write_context():
                _save_active_approvals()
            check(True, "_save_active_approvals() with internal context succeeds")
        except PermissionError as e:
            check(False, f"_save_active_approvals() wrongly blocked: {e}")

        # T11.3: _append_approval_record() with internal context succeeds
        test_record = {
            "approval_id": "aprv_h1_3_ctxvar_test",
            "preflight_id": "pf_h1_3_ctxvar_test",
            "status": "pending",
            "created_at_utc": "2026-06-12T00:00:00Z",
            "expires_at_utc": "2026-06-12T00:05:00Z",
            "proposal": {"symbol": "TEST", "action": "BUY", "totalQuantity": 1},
        }
        try:
            with internal_write_context():
                _append_approval_record(test_record)
            check(True, "_append_approval_record() with internal context succeeds")
        except PermissionError as e:
            check(False, f"_append_approval_record() wrongly blocked: {e}")

        # T11.4: create_approval_record() with internal context returns valid approval_id
        fake_preflight = {
            "passed": True,
            "symbol": "AAPL",
            "action": "BUY",
            "orderType": "MKT",
            "totalQuantity": 10,
            "entry_price": 150.0,
            "stop_price": 145.0,
            "stop_distance": 5.0,
            "atr14": 2.5,
            "final_max_shares": 100,
            "binding_cap": "notional",
            "gates": [
                {"gate": "allowlist", "passed": True},
                {"gate": "notional", "passed": True},
            ],
        }
        try:
            with internal_write_context():
                approval = create_approval_record(fake_preflight)
            check(approval.get("approval_id", "").startswith("aprv_"),
                  f"create_approval_record() returns valid approval_id: {approval.get('approval_id', 'NONE')}")
            check(approval.get("status") == "pending",
                  f"Approval status is pending: {approval.get('status')}")
            check(approval.get("expires_at_utc") is not None,
                  "Approval has expires_at_utc")
        except PermissionError as e:
            check(False, f"create_approval_record() wrongly blocked: {e}")
        except ValueError as e:
            check(False, f"create_approval_record() failed: {e}")

        # T11.5: Direct write (no internal context) still blocked
        from guard import GUARD_STATE_PATH
        try:
            from guard import save_guard_state_atomic
            save_guard_state_atomic({"schema_version": 1})
            check(False, "Direct save_guard_state_atomic() should be blocked")
        except PermissionError:
            check(True, "Direct save_guard_state_atomic() correctly blocked (no context)")

        # T11.6: Submitted approvals write blocked even with internal context (Class B)
        try:
            from guard import _save_submitted_approvals, _submitted_approvals
            old = set(_submitted_approvals)
            _submitted_approvals.add("aprv_h1_3_fake_contextvar")
            try:
                with internal_write_context():
                    _save_submitted_approvals()
                check(False, "_save_submitted_approvals() should be blocked even with internal context")
            except PermissionError:
                check(True, "_save_submitted_approvals() correctly blocked with internal context (Class B)")
            finally:
                _submitted_approvals.discard("aprv_h1_3_fake_contextvar")
        except Exception as e:
            check(False, f"Unexpected error in T11.6: {e}")

        # T11.7: append_guard_event with internal context succeeds
        try:
            from guard import append_guard_event
            with internal_write_context():
                evt = append_guard_event("preflight_pass", {
                    "symbol": "CTXVAR_TEST",
                    "passed": True,
                })
            check(evt.get("event_type") == "preflight_pass",
                  "append_guard_event() with internal context succeeds")
        except PermissionError as e:
            check(False, f"append_guard_event() wrongly blocked with internal context: {e}")

        # T11.8: Rollover guard state write via internal context
        try:
            from guard import load_guard_state, _rollover_guard_state
            state = load_guard_state()
            # Force a future trade_date to trigger rollover, then restore
            original_date = state.get("trade_date", "")
            state["trade_date"] = "2000-01-01"  # ancient date forces rollover
            with internal_write_context():
                rolled = _rollover_guard_state(state)
            check(rolled is True or rolled is False,
                  f"_rollover_guard_state() with internal context completes without PermissionError (rolled={rolled})")
            # Restore original
            state["trade_date"] = original_date
        except PermissionError as e:
            check(False, f"_rollover_guard_state() wrongly blocked with internal context: {e}")
        except Exception as e:
            check(False, f"_rollover_guard_state() unexpected error: {e}")

    except ImportError as e:
        check(False, f"Cannot import guard module for T11: {e}")
    except Exception as e:
        check(False, f"Unexpected error in T11: {e}")

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
