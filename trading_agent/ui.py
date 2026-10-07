"""Human approval UI; broker access and token storage are intentionally absent."""

import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import httpx

app = FastAPI(title="IBKR paper approval")
BRIDGE_BASE = os.environ.get("IBKR_BRIDGE_URL", "http://127.0.0.1:8790")

HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Paper order approval</title><style>
body{font-family:system-ui;max-width:760px;margin:40px auto;padding:0 20px;color:#172033}
input,select,button{box-sizing:border-box;font:inherit;padding:10px;margin:8px 0;width:100%}
pre{background:#eef1f5;padding:16px;white-space:pre-wrap;overflow-wrap:anywhere}
button:disabled{opacity:.5}label{display:block;margin-top:14px}
</style></head><body><h1>Paper order approval</h1>
<p>Review the order below before approving. Each order requires human approval and expires after five minutes.</p>
<label for="approval_id">Approval ID</label><input id="approval_id" autocomplete="off" oninput="resetPlan()">
<button onclick="loadPlan()">Load order details</button><pre id="plan">No order loaded.</pre>
<label for="h1_token">Approval token</label><input id="h1_token" type="password" autocomplete="off">
<label for="action">Action</label><select id="action"><option value="approve">Approve</option>
<option value="deny">Deny</option><option value="submit">Submit approved order</option>
<option value="approve-submit">Approve and submit</option></select>
<button id="send" onclick="send()" disabled>Confirm action</button>
<pre id="result" aria-live="polite"></pre>
<script>
let loaded=null;
function resetPlan(){loaded=null;document.getElementById('send').disabled=true;document.getElementById('plan').textContent='No order loaded.';}
async function loadPlan(){
  resetPlan();
  const id=document.getElementById('approval_id').value.trim();
  try{
    const response=await fetch('/api/approval/'+encodeURIComponent(id),{cache:'no-store'});
    const record=await response.json();if(!response.ok)throw new Error(record.error||'Order unavailable');
    if(id!==document.getElementById('approval_id').value.trim())return;
    const p=record.plan;
    const age=Math.max(0,Math.floor((Date.now()-Date.parse(p.market_observed_at))/1000));
    document.getElementById('plan').textContent=[
      'Account: '+p.account,'Order: '+p.side+' '+p.quantity+' '+p.symbol+' ('+p.order_type+')',
      'Entry reference: '+p.entry_price+' '+p.currency,'Protective stop: '+(p.stop_price||'Not applicable'),
      'Contract ID: '+p.contract_id,'Created: '+p.created_at,
      'Observed market data: '+age+' seconds ago','Expires: '+p.expires_at,'Status: '+record.status,
      'Proposal ID: '+(p.proposal_id||'Not supplied'),'Proposal hash: '+p.proposal_hash,
      'Policy hash: '+p.policy_hash,'Stop basis: '+p.stop_basis,'Schema: '+p.schema_version
      ,'Maximum entry: '+(p.max_entry_price||'Not specified'),'Minimum exit: '+(p.min_exit_price||'Not specified')
    ].join('\\n');
    loaded=record;document.getElementById('send').disabled=Date.parse(p.expires_at)<=Date.now();
  }catch(error){document.getElementById('result').textContent=error.message;}
}
async function send(){
  const tokenField=document.getElementById('h1_token');
  const button=document.getElementById('send');
  try{
    const id=document.getElementById('approval_id').value.trim();
    if(!loaded||loaded.approval_id!==id)throw new Error('Load the order details first.');
    if(Date.parse(loaded.plan.expires_at)<=Date.now())throw new Error('Approval expired. Create a fresh preflight.');
    button.disabled=true;
    const response=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({approval_id:id,h1_token:tokenField.value.trim(),action:document.getElementById('action').value})});
    const result=await response.json();document.getElementById('result').textContent=JSON.stringify(result,null,2);
    if(result.execution_state==='unknown'||result.execution_state==='submitting'){
      document.getElementById('result').textContent+='\\nUse execution status/reconciliation. Do not resubmit.';
    }
  }catch(error){document.getElementById('result').textContent=error.message;}
  finally{tokenField.value='';button.disabled=true;}
}
</script></body></html>"""


async def bridge_request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = {"X-H1-Token": token} if token else {}
    transport = getattr(app.state, "bridge_transport", None)
    try:
        async with httpx.AsyncClient(
            base_url=BRIDGE_BASE,
            timeout=35,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.request(method, path, headers=headers, json=payload)
            body = response.json()
            if not isinstance(body, dict):
                return 502, {"error": "Invalid bridge response"}
            return response.status_code, body
    except (httpx.HTTPError, ValueError):
        return 502, {
            "error": "Bridge response unavailable; check execution status before any further action"
        }


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(HTML, headers={"Cache-Control": "no-store"})


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/approval/{approval_id}")
async def approval(approval_id: str) -> JSONResponse:
    if (
        not approval_id.startswith("aprv_")
        or not approval_id.replace("_", "").isalnum()
    ):
        return JSONResponse({"error": "Invalid approval ID"}, status_code=400)
    code, body = await bridge_request("GET", "/order/approvals/" + approval_id)
    return JSONResponse(body, status_code=code, headers={"Cache-Control": "no-store"})


@app.post("/api/action")
async def action(request: Request) -> JSONResponse:
    try:
        data = await request.json()
        aid = data["approval_id"]
        token = data["h1_token"]
        selected = data["action"]
        if (
            not all(isinstance(value, str) for value in (aid, token, selected))
            or not token.strip()
        ):
            raise ValueError()
        if not aid.startswith("aprv_") or not aid.replace("_", "").isalnum():
            raise ValueError()
        if selected not in ("approve", "deny", "submit", "approve-submit"):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        return JSONResponse(
            {"error": "Valid approval ID, action and token required"}, status_code=400
        )
    if selected in ("approve", "deny", "approve-submit"):
        code, body = await bridge_request(
            "POST",
            "/order/approve",
            token=token,
            payload={
                "approval_id": aid,
                "decision": "deny" if selected == "deny" else "approve",
            },
        )
        if (
            selected != "approve-submit"
            or code >= 400
            or body.get("approved") is not True
        ):
            return JSONResponse(body, status_code=code)
    code, body = await bridge_request(
        "POST", "/order/submit", token=token, payload={"approval_id": aid}
    )
    return JSONResponse(body, status_code=code, headers={"Cache-Control": "no-store"})
