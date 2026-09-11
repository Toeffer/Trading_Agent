#!/usr/bin/env python3
"""Privileged human-only client. Never pass the H1 secret in argv or env."""
import argparse
import json
from pathlib import Path
import re
import sys
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

TOKEN_FILE = Path("/etc/ibkr-bridge/h1_token")
BASE_URL = "http://127.0.0.1:8790"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_for(action, identity, token):
    prefix = "exec" if action == "reconcile" else "aprv"
    pattern = r"[A-Z][A-Z0-9.]{0,9}" if action == "reconcile-account" else r"[a-f0-9]{64}" if action == "reconcile-legacy" else prefix + r"_[a-f0-9]{32}"
    if not re.fullmatch(pattern, identity):
        raise ValueError("Invalid identifier")
    if action in ("approve", "deny"):
        path = "/order/approve"
        payload = {"approval_id": identity, "decision": action}
    elif action == "submit":
        path, payload = "/order/submit", {"approval_id": identity}
    elif action == "reconcile":
        path, payload = "/order/executions/" + identity + "/reconcile", {}
    elif action == "reconcile-legacy":
        path, payload = "/order/legacy-quarantine/" + identity + "/reconcile", {}
    elif action == "reconcile-account":
        path, payload = "/order/account/reconcile", {"symbol": identity}
    else:
        raise ValueError("Invalid action")
    return Request(BASE_URL + path, data=json.dumps(payload).encode("utf-8"), method="POST",
                   headers={"Content-Type": "application/json", "X-H1-Token": token})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("approve", "deny", "submit", "reconcile", "reconcile-legacy", "reconcile-account"))
    parser.add_argument("identity")
    args = parser.parse_args()
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
            raise ValueError("Invalid credential")
        request = request_for(args.action, args.identity, token)
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=40) as response:
            body = json.loads(response.read(1024 * 1024).decode("utf-8"))
        # No exception, request, headers or raw response is printed. Even an
        # unexpected echo from an HTTP service cannot disclose the credential.
        output = json.dumps(body, sort_keys=True)
        print(output.replace(token, "[REDACTED]"))
        return 0
    except Exception:
        print("Action response unavailable. Check execution status; do not retry submission.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
