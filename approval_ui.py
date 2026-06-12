#!/usr/bin/env python3
"""
R1 Tailnet Approval UI.

Safety rules:
- Advisory/approval helper only.
- Does not read /etc/ibkr-bridge/h1_token.
- Does not store, prefill, print, or log H1 tokens.
- Forwards token only as X-H1-Token to local bridge.
- Bind this app ONLY to the Tailscale IP, never 0.0.0.0.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

BRIDGE_BASE = "http://127.0.0.1:8790"

app = FastAPI(title="IBKR R1 Tailnet Approval UI")


HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>IBKR R1 Approval UI</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 760px; margin: 40px auto; padding: 0 16px; }
    input, select, button { font-size: 16px; padding: 10px; width: 100%; margin: 8px 0; box-sizing: border-box; }
    button { cursor: pointer; }
    .danger { color: #b00020; font-weight: 700; }
    pre { background: #111; color: #eee; padding: 12px; overflow: auto; white-space: pre-wrap; }
  </style>
</head>
<body>
  <h1>IBKR R1 Approval UI</h1>

  <p class="danger">
    Token is never stored or prefilled. Use only on Tailscale.
    Do not use unless Chris intentionally opened a trade window.
  </p>

  <label>Approval ID</label>
  <input id="approval_id" placeholder="aprv_..." autocomplete="off">

  <label>H1 Token</label>
  <input id="h1_token" type="password" placeholder="paste H1 token from password manager" autocomplete="off">

  <label>Action</label>
  <select id="action">
    <option value="approve">approve</option>
    <option value="deny">deny</option>
    <option value="submit">submit</option>
    <option value="approve-submit">approve-submit</option>
  </select>

  <button onclick="send()">Send</button>

  <h2>Result</h2>
  <pre id="result">No request yet.</pre>

<script>
async function send() {
  const approval_id = document.getElementById("approval_id").value.trim();
  const h1_token = document.getElementById("h1_token").value.trim();
  const action = document.getElementById("action").value;
  const result = document.getElementById("result");

  result.textContent = "Sending...";

  const resp = await fetch("/api/action", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({approval_id, h1_token, action})
  });

  const text = await resp.text();
  try {
    result.textContent = JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    result.textContent = text;
  }

  document.getElementById("h1_token").value = "";
}
</script>
</body>
</html>
"""


def _bridge_post(path: str, payload: Dict[str, Any], token: str) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BRIDGE_BASE}{path}",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-H1-Token": token,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode("utf-8", errors="replace")
            try:
                return {"http_status": r.status, "body": json.loads(raw)}
            except json.JSONDecodeError:
                return {"http_status": r.status, "body_text": raw}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            body_json = json.loads(raw)
            return {"http_status": e.code, "body": body_json}
        except json.JSONDecodeError:
            return {"http_status": e.code, "body_text": raw}
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "service": "ibkr-r1-approval-ui", "bridge": BRIDGE_BASE}


@app.post("/api/action")
async def action(request: Request) -> JSONResponse:
    data = await request.json()

    approval_id = str(data.get("approval_id", "")).strip()
    token = str(data.get("h1_token", "")).strip()
    action_name = str(data.get("action", "")).strip()

    if not approval_id:
        return JSONResponse({"ok": False, "error": "missing approval_id"}, status_code=400)
    if not token:
        return JSONResponse({"ok": False, "error": "missing h1_token"}, status_code=400)

    if action_name == "approve":
        out = _bridge_post("/order/approve", {"approval_id": approval_id, "decision": "approve"}, token)
    elif action_name == "deny":
        out = _bridge_post("/order/approve", {"approval_id": approval_id, "decision": "deny"}, token)
    elif action_name == "submit":
        out = _bridge_post("/order/submit", {"approval_id": approval_id}, token)
    elif action_name == "approve-submit":
        first = _bridge_post("/order/approve", {"approval_id": approval_id, "decision": "approve"}, token)
        if first.get("http_status") not in (200, 201):
            out = {"approve": first, "submit_skipped": True}
        else:
            second = _bridge_post("/order/submit", {"approval_id": approval_id}, token)
            out = {"approve": first, "submit": second}
    else:
        return JSONResponse({"ok": False, "error": f"unknown action {action_name!r}"}, status_code=400)

    return JSONResponse({"ok": True, "approval_id": approval_id, "action": action_name, "result": out})
