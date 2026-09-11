"""HTTP contracts for the durable application, separate from broker code."""

from typing import Any, cast
from decimal import Decimal

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictInt

from trading_agent.application import ExecutionService
from trading_agent.domain import content_hash
from trading_agent.persistence import StateConflict
from trading_agent.runtime import Runtime


class PreflightRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    symbol: str
    action: str = "BUY"
    totalQuantity: StrictInt
    orderType: str = "MKT"
    limitPrice: Decimal | None = None
    stopPrice: Decimal | None = None
    mode: str | None = None
    proposal_path: str | None = None


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str
    decision: str
    ruled_by: str = "human"


class SubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str


class AccountReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str


def install(app: FastAPI) -> None:
    router = APIRouter()

    def runtime(request: Request) -> Runtime:
        value = getattr(request.app.state, "runtime", None)
        if value is None:
            raise HTTPException(503, "EXECUTION_RUNTIME_NOT_READY")
        return cast(Runtime, value)

    def authorize(value: Runtime, token: str | None) -> None:
        if not value.settings.verify_token(token):
            raise HTTPException(403, "H1_TOKEN_REQUIRED")

    @router.post("/connect")
    @router.post("/connect-light")
    def connect(
        request: Request, x_h1_token: str | None = Header(default=None)
    ) -> dict[str, Any]:
        value = runtime(request)
        authorize(value, x_h1_token)
        try:
            return value.broker.connect()
        except Exception:
            raise HTTPException(503, "BROKER_CONNECTION_REVIEW_REQUIRED") from None

    @router.post("/disconnect")
    def disconnect(
        request: Request, x_h1_token: str | None = Header(default=None)
    ) -> dict[str, Any]:
        value = runtime(request)
        authorize(value, x_h1_token)

        async def operation(ib: Any) -> None:
            ib.disconnect()

        value.owner.run(operation)
        return {"connected": False, "manual_review_required": True}

    @router.post("/order/preflight")
    def preflight(body: PreflightRequest, request: Request) -> dict[str, Any]:
        value = runtime(request)
        payload = body.model_dump(exclude_none=True)
        path = payload.pop("proposal_path", None)
        try:
            proposal = value.proposal(path)
        except (ValueError, OSError):
            return {
                "passed": False,
                "code": "PROPOSAL_INVALID",
                "error": "Valid persisted proposal required",
            }
        return value.service.preflight(payload, proposal=proposal)

    @router.post("/order/approve")
    def approve(
        body: ApproveRequest,
        request: Request,
        x_h1_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        value = runtime(request)
        authorize(value, x_h1_token)
        try:
            record = value.service.rule(
                body.approval_id, body.decision, authorized=True
            )
            return {
                "approved": body.decision == "approve",
                "approval_id": body.approval_id,
                "record": record,
            }
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @router.post("/order/submit")
    def submit(
        body: SubmitRequest,
        request: Request,
        x_h1_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        value = runtime(request)
        authorize(value, x_h1_token)
        return value.service.submit(body.approval_id, authorized=True)

    @router.get("/order/approvals")
    def approvals(request: Request) -> dict[str, Any]:
        return {"schema_version": 1, "approvals": runtime(request).store.approvals()}

    @router.get("/order/approvals/{approval_id}")
    def approval(approval_id: str, request: Request) -> dict[str, Any]:
        try:
            return {"schema_version": 1, **runtime(request).store.approval(approval_id)}
        except StateConflict:
            raise HTTPException(404, "APPROVAL_NOT_FOUND") from None

    @router.get("/order/executions/{execution_id}")
    def execution(execution_id: str, request: Request) -> dict[str, Any]:
        try:
            return runtime(request).store.execution(execution_id)
        except StateConflict:
            raise HTTPException(404, "EXECUTION_NOT_FOUND") from None

    @router.post("/order/executions/{execution_id}/reconcile")
    def reconcile(
        execution_id: str,
        request: Request,
        x_h1_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        value = runtime(request)
        authorize(value, x_h1_token)
        try:
            return value.service.reconcile(execution_id, authorized=True)
        except StateConflict as exc:
            raise HTTPException(409, str(exc)) from None

    @router.get("/execution/readiness")
    @router.get("/readiness")
    def readiness(request: Request) -> dict[str, Any]:
        value = runtime(request)
        blockers = []
        rules = value.load_rules()
        try:
            value.store.risk_state(value.settings.account)
        except StateConflict as exc:
            blockers.append(str(exc))
        with value.store.connection() as db:
            if db.execute(
                "SELECT 1 FROM executions WHERE execution_state IN ('unknown','submitting') OR protection_state='unknown' LIMIT 1"
            ).fetchone():
                blockers.append("UNRESOLVED_EXECUTION")
            if db.execute(
                "SELECT 1 FROM legacy_quarantine WHERE resolved=0 LIMIT 1"
            ).fetchone():
                blockers.append("UNRESOLVED_LEGACY_EXECUTION")
        if not value.settings.allow_orders or rules.get("enforced") is not True:
            blockers.append("ORDERS_BLOCKED")
        if not value.settings.token_hash:
            blockers.append("H1_NOT_CONFIGURED")
        if value.settings.release == "unverified":
            blockers.append("RELEASE_NOT_VERIFIED")
        try:

            async def identity(ib: Any) -> bool:
                return bool(
                    ib.isConnected() and value.settings.account in ib.managedAccounts()
                )

            if not value.owner.run(identity, timeout=2):
                blockers.append("PAPER_ACCOUNT_NOT_CONNECTED")
        except (RuntimeError, TimeoutError):
            blockers.append("PAPER_ACCOUNT_NOT_CONNECTED")
        if value.broker.event_failure:
            blockers.append("BROKER_EVENT_REVIEW_REQUIRED")
        return {
            **value.settings.public_identity(),
            "rules_hash": content_hash(rules),
            "blockers": blockers,
            "service_ready_for_preflight": not blockers,
            "paper_order_ready": False,
            "order_specific_preflight_required": True,
            "live_ready": False,
            "human_approval_required": True,
            "export_backlog": value.export_failure,
        }

    @router.post("/order/account/reconcile")
    def reconcile_account(
        body: AccountReconcileRequest,
        request: Request,
        x_h1_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        value = runtime(request)
        authorize(value, x_h1_token)
        try:
            return value.service.reconcile_account(body.symbol, authorized=True)
        except (ValueError, RuntimeError):
            raise HTTPException(409, "ACCOUNT_RECONCILIATION_UNAVAILABLE") from None

    @router.get("/health")
    def health(request: Request) -> dict[str, Any]:
        value = runtime(request)
        connected: bool | None = None
        try:

            async def identity(ib: Any) -> bool:
                return bool(
                    ib.isConnected() and value.settings.account in ib.managedAccounts()
                )

            connected = value.owner.run(identity, timeout=2)
        except (RuntimeError, TimeoutError):
            pass
        return {
            "ok": True,
            "connected": connected,
            "read_only": False,
            **value.settings.public_identity(),
            "human_approval_required": True,
            "broker_event_review_required": value.broker.event_failure,
            "execution_readiness_url": "/execution/readiness",
        }

    @router.get("/status")
    def status(request: Request) -> dict[str, Any]:
        return {
            "health": health(request),
            "execution": readiness(request),
            "approvals_url": "/order/approvals",
            "legacy_quarantine_url": "/order/legacy-quarantine",
        }

    @router.get("/order/legacy-quarantine")
    def legacy_records(request: Request) -> dict[str, Any]:
        import json

        value = runtime(request)
        with value.store.connection() as db:
            rows = db.execute(
                "SELECT * FROM legacy_quarantine WHERE account=? AND resolved=0",
                (value.settings.account,),
            ).fetchall()
        return {
            "records": [
                {"record_hash": r["record_hash"], "payload": json.loads(r["payload"])}
                for r in rows
            ]
        }

    @router.post("/order/legacy-quarantine/{record_hash}/reconcile")
    def reconcile_legacy(
        record_hash: str,
        request: Request,
        x_h1_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        value = runtime(request)
        authorize(value, x_h1_token)
        try:
            return value.reconcile_legacy(record_hash, authorized=True)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    paths = {getattr(route, "path", None) for route in router.routes}
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) not in paths
    ]
    app.include_router(router)
