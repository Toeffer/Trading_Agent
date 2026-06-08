#!/usr/bin/env python3
"""
Phase 5B.0 — Hermes Advisory Guard Policy Validation

Verifies:
1. Policy file exists and is non-empty
2. Mandatory proposal fields are documented
3. Forbidden actions are documented
4. Risk rails are documented
5. No order/IBKR mutation paths are added
6. ibkr-operator remains read-only
7. Doctor check hermes_policy_exists is present
"""

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
    print(f"  \u26a0\ufe0f  {message}")


def main():
    global PASS, FAIL, WARN, ERRORS

    print("=" * 60)
    print("Phase 5B.0 \u2014 Hermes Advisory Guard Validation")
    print("=" * 60)

    policy_path = Path.home() / ".openclaw" / "memory" / "hermes-advisory-guard-policy.md"
    claude_path = Path.home() / ".openclaw" / "CLAUDE.md"
    runbook_path = Path.home() / "agents" / "ibkr-bridge" / "RUNBOOK.md"
    operator_path = Path.home() / "agents" / "ibkr-bridge" / "ibkr_operator.py"

    # ---- 1. Policy file exists ----
    print("\n\U0001f4c4 Policy File Existence")
    check(policy_path.exists(), "Policy file exists")
    if policy_path.exists():
        content = policy_path.read_text()
        check(len(content) > 1000, "Policy file non-empty (%d bytes)" % len(content))

        # ---- 2. Mandatory proposal fields ----
        print("\n\U0001f4cb Mandatory Proposal Fields")
        required_fields = [
            "symbol", "side", "quantity", "entry reference",
            "stop-loss", "invalidation", "max loss",
            "position notional", "portfolio exposure",
            "daily", "weekly drawdown", "reason to trade",
            "reason not to trade", "preflight",
            "Awaiting Chris approval", "Advisory only"
        ]
        for field in required_fields:
            found = field.lower() in content.lower()
            check(found, "Field documented: '%s'" % field)

        # ---- 3. Forbidden actions ----
        print("\n\U0001f6ab Forbidden Actions")
        forbidden_checks = [
            ("must not / must NOT", lambda c: "must not" in c.lower()),
            ("forbidden", lambda c: "forbidden" in c.lower()),
            ("never", lambda c: "never" in c),
            ("/order/submit", lambda c: "/order/submit" in c),
            ("/order/approve", lambda c: "/order/approve" in c),
            ("guard-state", lambda c: "guard-state" in c),
            ("paper-trading-rules.yaml", lambda c: "paper-trading-rules.yaml" in c),
        ]
        for label, fn in forbidden_checks:
            found = fn(content)
            check(found, "Forbidden action mentioned: '%s'" % label)

        # ---- 4. Risk rails ----
        print("\n\U0001f4ca Risk Rails")
        rail_terms = [
            "Max single position", "5%", "0.25%",
            "Max daily", "Max weekly",
            "NO TRADE", "stop", "drift",
        ]
        for term in rail_terms:
            found = term in content
            check(found, "Risk rail documented: '%s'" % term)

        # ---- 5. Human confirmation ladder ----
        print("\n\U0001f464 Human Confirmation Ladder")
        ladder_terms = [
            "Chris approval", "Phase 5", "\u20ac0",
        ]
        for term in ladder_terms:
            found = term in content
            check(found, "Confirmation ladder: '%s'" % term)

    # ---- 6. CLAUDE.md reference ----
    print("\n\U0001f4d8 CLAUDE.md Reference")
    if claude_path.exists():
        claude = claude_path.read_text()
        check("Hermes Advisory Guard" in claude,
              "CLAUDE.md contains Hermes Advisory section")
        check("hermes-advisory-guard-policy.md" in claude,
              "CLAUDE.md references policy file path")
    else:
        check(False, "CLAUDE.md file exists")

    # ---- 7. RUNBOOK.md reference ----
    print("\n\U0001f4d5 RUNBOOK.md Reference")
    if runbook_path.exists():
        runbook = runbook_path.read_text()
        check("Hermes Advisory Guard" in runbook,
              "RUNBOOK.md contains Hermes Advisory section")
        check("hermes-advisory-guard-policy.md" in runbook,
              "RUNBOOK.md references policy file path")
    else:
        check(False, "RUNBOOK.md file exists")

    # ---- 8. Doctor check exists ----
    print("\n\U0001f52c ibkr-operator Doctor Check")
    if operator_path.exists():
        operator = operator_path.read_text()
        check("hermes_policy_exists" in operator,
              "ibkr_operator.py has hermes_policy_exists doctor check")
        check("hermes-advisory-guard-policy.md" in operator,
              "Doctor check references policy file path")
    else:
        check(False, "ibkr_operator.py file exists")

    # ---- 9. No mutation paths added ----
    print("\n\U0001f512 No Mutation / Bypass Paths")
    if operator_path.exists():
        operator = operator_path.read_text()
        lines = operator.split("\n")
        # Track whether we are inside a triple-quoted docstring
        in_docstring = False
        new_mutation_calls = 0
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped:
                continue
            # Toggle docstring state for triple-quoted blocks
            if stripped.startswith('"""') or stripped.startswith("'''"):
                in_docstring = not in_docstring
                continue
            if in_docstring or stripped.startswith("#"):
                continue
            # Skip known safe references (negations, safety checks, forbidden-name lists)
            safe_patterns = ["never", "blocked", "forbidden", "no_op", "safety",
                             "guard", "check", "forbidden_names"]
            lower = stripped.lower()
            if any(p in lower for p in safe_patterns):
                continue
            # Skip lines that reference placeOrder/cancelOrder as string literals (safety lists)
            if lower.strip().startswith('"placeorder"') or lower.strip().startswith("'placeorder'"):
                continue
            if lower.strip().startswith('"cancelorder"') or lower.strip().startswith("'cancelorder'"):
                continue
            # Also skip if line says "No placeOrder" or "no cancelOrder"
            if lower.startswith("no ") or lower.startswith("- no "):
                continue
            if "placeOrder" in stripped or "cancelOrder" in stripped:
                new_mutation_calls += 1
                warn("Line %d: possible unguarded mutation: %s" % (i, stripped[:80]))
        check(new_mutation_calls == 0,
              "No new unguarded mutation paths (%d found)" % new_mutation_calls)
    else:
        check(False, "ibkr_operator.py file exists")

    # ---- Summary ----
    print("\n" + "=" * 60)
    print("Results:  \u2705 %d passed  \u274c %d failed  \u26a0\ufe0f  %d warnings" % (PASS, FAIL, WARN))
    print("=" * 60)

    if ERRORS:
        print("\nFailed checks:")
        for err in ERRORS:
            print("  \u2022 %s" % err)
        print("\n\u274c VALIDATION FAILED")
        return 1
    else:
        print("\n\u2705 ALL CHECKS PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main())
