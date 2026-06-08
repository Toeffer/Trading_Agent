#!/usr/bin/env python3
"""
Hermes Advisory Adapter — Phase 5B.1

Invokes Hermes CLI for advisory-only trade proposals.
Hermes must never enable, submit, approve, or mutate trading state.
This adapter enforces that boundary.

Usage:
    python3 hermes_advisory.py --baseline baseline.json --output proposal.json
    python3 hermes_advisory.py --canary   # test invocation

Output includes Hermes Evidence Block for attribution tracking.
"""

import argparse
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── Hard-coded safety constraints ──────────────────────────────────────────
FORBIDDEN_COMMANDS = [
    "/order/submit", "/order/approve", "/order",
    "placeOrder", "cancelOrder", "ibkr_order",
    "IBKR_ALLOW_ORDERS=true", "enforced=true",
    "guard-state", "guard-events",
    "submitted-approvals", "manual-order-reconciliations",
    ".env", "paper-trading-rules.yaml",
]

ADVISORY_INSTRUCTION = """
You are Hermes, an advisory-only trading research engine.
You are generating a trade proposal for Chris to review.

IMPORTANT RULES:
- Advisory only. No order enabled or submitted.
- You must NOT call any trading endpoints.
- You must NOT suggest that orders are already approved.
- You must NOT mutate any files except designated research notes.
- Your proposal is a DRAFT for Chris to review.

RISK RAILS (Phase 5 Pilot):
- Max single position: 5% of Net Liq
- Max total exposure: 25% of Net Liq
- Max risk per trade: 0.25% of Net Liq
- Max daily trades: 2
- Max weekly trades: 5
- No trade without stop/invalidation
- No trade if drift detected, open order unresolved, or live requires_action alert
- No trade if daily loss >= 1% or weekly loss >= 3% Net Liq

HUMAN CONFIRMATION LADDER:
- Every trade > EUR 0 requires Chris approval
- Any order enablement requires Chris approval
- Any order submit requires Chris approval
"""

PROPOSAL_TEMPLATE = """
Generate a trade proposal using the following mandatory 14-field template.
Base the proposal on the baseline data provided.

Fields:
1. symbol
2. side (BUY or SELL)
3. quantity
4. entry reference (price level, order type, rationale)
5. stop-loss / invalidation (price level)
6. max loss in EUR and %
7. position notional in EUR and %
8. portfolio exposure after trade (as % of Net Liq)
9. daily/weekly drawdown status
10. reason to trade
11. reason not to trade
12. exact bridge preflight command (curl for POST /order/preflight)
13. "Awaiting Chris approval"
14. "Advisory only — no order enabled or submitted"

Also include:
- Facts (from baseline data)
- Assumptions
- Estimates
- Unknowns
- Why not wait?

Output ONLY valid JSON, no other text.
Use this exact JSON structure:
{
  "symbol": "...",
  "side": "...",
  "quantity": N,
  "entry_reference": "...",
  "stop_loss_invalidation": "...",
  "max_loss_eur": N.N,
  "max_loss_pct": N.N,
  "position_notional_eur": N.N,
  "position_notional_pct": N.N,
  "portfolio_exposure_after_pct": N.N,
  "daily_drawdown_status": "...",
  "weekly_drawdown_status": "...",
  "reason_to_trade": "...",
  "reason_not_to_trade": "...",
  "preflight_command": "...",
  "facts": ["...", "..."],
  "assumptions": ["...", "..."],
  "estimates": ["...", "..."],
  "unknowns": ["...", "..."],
  "why_not_wait": "...",
  "awaiting_chris_approval": true,
  "advisory_only": true
}
"""


def build_prompt(baseline: dict, user_request: str) -> str:
    """Build the Hermes prompt from baseline data + user request."""
    parts = [
        ADVISORY_INSTRUCTION,
        "\n## Current Baseline Data\n",
        json.dumps(baseline, indent=2),
        "\n## User Request\n",
        user_request,
        "\n## Proposal Template\n",
        PROPOSAL_TEMPLATE,
    ]
    return "\n".join(parts)


def invoke_hermes(prompt: str, model: str = "gpt-5.5",
                  provider: str = "openai-codex",
                  timeout: int = 180) -> dict:
    """Invoke Hermes CLI and return the response with evidence.

    Returns:
        dict with 'response' (str), 'evidence' (dict)
    """
    request_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    request_id = str(uuid.uuid4())[:8]

    cmd = [
        "hermes", "chat",
        "-q", prompt,
        "-m", model,
        "--provider", provider,
        "-Q",  # quiet mode
    ]

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed_s = round(time.time() - start_time, 2)
        response_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        returncode = result.returncode

        # Extract session_id from stderr if present
        session_id = None
        for line in (stdout + "\n" + stderr).split("\n"):
            if "session_id:" in line.lower() or "session_id" in line.lower():
                session_id = line.split(":", 1)[-1].strip()
                break

        if returncode != 0:
            return {
                "ok": False,
                "error": f"Hermes CLI exited with code {returncode}: {stderr[:500]}",
                "evidence": {
                    "hermes_invoked": True,
                    "hermes_command_or_adapter": "hermes_advisory.py -> hermes chat -q",
                    "hermes_provider": provider,
                    "hermes_model": model,
                    "hermes_request_timestamp_utc": request_ts,
                    "hermes_response_timestamp_utc": response_ts,
                    "hermes_session_id": session_id or request_id,
                    "hermes_request_id": request_id,
                    "hermes_usage_observed": None,
                    "hermes_log_reference": f"hermes session {session_id or request_id}",
                    "fallback_used": False,
                    "final_proposal_source": "unknown",
                    "elapsed_seconds": elapsed_s,
                },
            }

        # Attempt to parse JSON from response
        evidence = {
            "hermes_invoked": True,
            "hermes_command_or_adapter": "hermes_advisory.py -> hermes chat -q",
            "hermes_provider": provider,
            "hermes_model": model,
            "hermes_request_timestamp_utc": request_ts,
            "hermes_response_timestamp_utc": response_ts,
            "hermes_session_id": session_id or request_id,
            "hermes_request_id": request_id,
            "hermes_usage_observed": None,
            "hermes_log_reference": f"hermes session {session_id or request_id}",
            "fallback_used": False,
            "final_proposal_source": "Hermes",
            "elapsed_seconds": elapsed_s,
        }

        return {
            "ok": True,
            "raw_response": stdout,
            "evidence": evidence,
        }

    except subprocess.TimeoutExpired:
        response_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "ok": False,
            "error": f"Hermes CLI timed out after {timeout}s",
            "evidence": {
                "hermes_invoked": True,
                "hermes_command_or_adapter": "hermes_advisory.py -> hermes chat -q",
                "hermes_provider": provider,
                "hermes_model": model,
                "hermes_request_timestamp_utc": request_ts,
                "hermes_response_timestamp_utc": response_ts,
                "hermes_session_id": None,
                "hermes_request_id": request_id,
                "hermes_usage_observed": None,
                "hermes_log_reference": f"hermes request {request_id} (timeout)",
                "fallback_used": False,
                "final_proposal_source": "unknown",
                "elapsed_seconds": round(time.time() - start_time, 2),
            },
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "error": "hermes CLI not found. Install hermes or check PATH.",
            "evidence": {
                "hermes_invoked": False,
                "hermes_command_or_adapter": "N/A — hermes CLI not found",
                "hermes_provider": None,
                "hermes_model": None,
                "hermes_request_timestamp_utc": request_ts,
                "hermes_response_timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "hermes_session_id": None,
                "hermes_request_id": request_id,
                "hermes_usage_observed": None,
                "hermes_log_reference": "N/A",
                "fallback_used": False,
                "final_proposal_source": "unknown",
                "elapsed_seconds": 0,
            },
        }


def run_canary() -> dict:
    """Run a canary test to prove Hermes invocation works."""
    prompt = "Reply with exactly: HERMES_CANARY_OK. No other text."
    return invoke_hermes(prompt, timeout=60)


def check_forbidden(response_text: str) -> list:
    """Check if Hermes response contains forbidden patterns."""
    violations = []
    for pat in FORBIDDEN_COMMANDS:
        if pat.lower() in response_text.lower():
            violations.append(pat)
    return violations


def main():
    parser = argparse.ArgumentParser(
        description="Hermes Advisory Adapter — Phase 5B.1"
    )
    parser.add_argument("--canary", action="store_true",
                        help="Run canary test only")
    parser.add_argument("--baseline", type=str,
                        help="Path to baseline JSON file")
    parser.add_argument("--request", type=str, default="",
                        help="User request / trade idea")
    parser.add_argument("--output", type=str,
                        help="Output JSON file path")
    parser.add_argument("--model", type=str, default="gpt-5.5",
                        help="Hermes model (default: gpt-5.5)")
    parser.add_argument("--provider", type=str, default="openai-codex",
                        help="Hermes provider (default: openai-codex)")
    parser.add_argument("--timeout", type=int, default=180,
                        help="Hermes invocation timeout in seconds")

    args = parser.parse_args()

    if args.canary:
        print("Running Hermes canary...")
        result = run_canary()
        if result.get("ok"):
            print(f"  ✅ Canary OK")
            print(f"  Session: {result['evidence']['hermes_session_id']}")
            print(f"  Response: {result.get('raw_response', '')[:100]}")
        else:
            print(f"  ❌ Canary failed: {result.get('error', 'unknown')}")
        print("\nEvidence block:")
        print(json.dumps(result.get("evidence", {}), indent=2))
        return 0 if result.get("ok") else 1

    # Load baseline data
    if args.baseline:
        try:
            with open(args.baseline) as f:
                baseline = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading baseline: {e}", file=sys.stderr)
            return 1
    else:
        baseline = {"note": "No baseline provided"}

    user_request = args.request or "Generate one minimal controlled paper trade proposal for Phase 5B."

    # Build prompt
    prompt = build_prompt(baseline, user_request)

    # Invoke Hermes
    print(f"Invoking Hermes (model={args.model}, provider={args.provider})...",
          file=sys.stderr)
    result = invoke_hermes(prompt, model=args.model,
                           provider=args.provider, timeout=args.timeout)

    if not result.get("ok"):
        print(f"Hermes invocation failed: {result.get('error')}", file=sys.stderr)
        # Still output evidence
        print("\nEvidence block:")
        print(json.dumps(result.get("evidence", {}), indent=2))
        return 1

    # Parse proposal JSON from response
    raw = result.get("raw_response", "")
    proposal = None
    try:
        # Try to extract JSON block from response
        # Look for { ... } block
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            proposal = json.loads(raw[start:end+1])
    except (json.JSONDecodeError, ValueError):
        proposal = None

    # Check for forbidden patterns
    violations = check_forbidden(raw)

    output = {
        "proposal": proposal,
        "raw_response": raw,
        "violations": violations,
        "evidence": result["evidence"],
        "forbidden_action_detected": len(violations) > 0,
    }

    # If forbidden patterns found, override source
    if violations:
        output["evidence"]["final_proposal_source"] = "unknown (forbidden content)"

    # Output
    output_json = json.dumps(output, indent=2, default=str)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Output written to {args.output}", file=sys.stderr)

    print(output_json)
    return 0 if (proposal is not None and not violations) else 1


if __name__ == "__main__":
    sys.exit(main())
