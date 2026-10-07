"""Explicit composition root for the deployed bridge."""

from dataclasses import replace
from pathlib import Path
import threading
from typing import Any

from trading_agent.application import ExecutionService
from trading_agent.broker_adapter import IBKRBroker
from trading_agent.broker_loop import BrokerLoop
from trading_agent.domain import PortfolioSnapshot, money
from trading_agent.persistence import ExecutionStore
from trading_agent.risk import RiskPolicy
from trading_agent.settings import Settings
from trading_agent.ownership import ServiceLock
from trading_agent.domain import ApprovedOrderPlan


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = ServiceLock(settings.state_dir / "service.lock")
        self._stop = threading.Event()
        self._exporter: threading.Thread | None = None
        self.export_failure = False
        # Validate configuration before creating the client or touching state.
        rules = self.load_rules()
        RiskPolicy.from_rules(rules)
        self.store = ExecutionStore(settings.state_dir / "execution.sqlite3")
        from ib_insync import IB

        self.owner = BrokerLoop(IB, settings.queue_capacity)
        self.broker = IBKRBroker(self.owner, settings, rules["symbol_sectors"])
        self.service = ExecutionService(
            self.store,
            self.broker,
            rules_provider=self.load_rules,
            account=settings.account,
            orders_enabled=lambda: settings.allow_orders,
            release=settings.release,
            stop_provider=self.broker.stop_price,
            account_risk_provider=self.account_risk,
        )

    def load_rules(self) -> dict[str, Any]:
        from trading_agent import legacy_guard as guard

        return guard.load_rules(self.settings.rules_path)

    def account_risk(
        self, snapshot: PortfolioSnapshot, policy: RiskPolicy
    ) -> PortfolioSnapshot:
        if snapshot.base_currency != "EUR":
            raise ValueError("CURRENT_RISK_POLICY_REQUIRES_EUR_BASE")
        state = self.store.risk_state(snapshot.account, snapshot.net_liquidation)
        daily = (money(state["day_start_nl_eur"]) - snapshot.net_liquidation) / money(
            state["day_start_nl_eur"]
        )
        weekly = (money(state["week_start_nl_eur"]) - snapshot.net_liquidation) / money(
            state["week_start_nl_eur"]
        )
        if daily >= policy.daily_loss_pct or weekly >= policy.weekly_loss_pct:
            self.store.latch_halts(
                snapshot.account,
                daily >= policy.daily_loss_pct,
                weekly >= policy.weekly_loss_pct,
            )
        return replace(
            snapshot,
            daily_loss_halt=state.get("daily_halt_active", False)
            or daily >= policy.daily_loss_pct,
            weekly_loss_halt=state.get("weekly_halt_active", False)
            or weekly >= policy.weekly_loss_pct,
        )

    def start(self) -> None:
        self.lock.acquire()
        try:
            self.store.startup()
            self.owner.start()

            def lookup(reference: str) -> ApprovedOrderPlan:
                execution = self.store.execution(reference)
                return ApprovedOrderPlan.from_dict(
                    self.store.approval(execution["approval_id"])["plan"]
                )

            self.broker.observe(lookup, self.store.record_result)
        except BaseException:
            self.owner.close()
            self.lock.close()
            raise

        def export() -> None:
            while not self._stop.wait(2):
                try:
                    self.store.export(self.settings.state_dir / "events")
                    self.export_failure = False
                except Exception:
                    self.export_failure = True

        self._exporter = threading.Thread(
            target=export, name="execution-export", daemon=True
        )
        self._exporter.start()
        from trading_agent import legacy_guard as guard

        guard._execution_service = self.service
        guard._proposal_loader = self.proposal

    def close(self) -> None:
        from trading_agent import legacy_guard as guard

        if guard._execution_service is self.service:
            guard._execution_service = None
            guard._proposal_loader = None
        self._stop.set()
        if self._exporter:
            self._exporter.join(timeout=10)
        try:
            self.owner.close()
            self.store.export(self.settings.state_dir / "events")
        finally:
            self.lock.close()

    def proposal(self, path: str | None) -> dict[str, Any]:
        import json
        from trading_agent import legacy_guard as guard

        if not path:
            raise ValueError("PROPOSAL_REQUIRED")
        root = self.settings.proposal_dir.resolve()
        target = Path(path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError("PROPOSAL_PATH_NOT_ALLOWED")
        if target.stat().st_size > 1024 * 1024:
            raise ValueError("PROPOSAL_TOO_LARGE")
        proposal = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(proposal, dict):
            raise ValueError("INVALID_PROPOSAL")
        # Validate the exact in-memory content that will be hashed and bound.
        ok, _, detail = guard.gate_proposal_discipline(
            str(target), proposal_data=proposal
        )
        if not ok:
            raise ValueError(
                "PROPOSAL_INVALID:" + str(detail.get("error", "incomplete"))
            )
        return proposal

    def reconcile_legacy(self, record_hash: str, *, authorized: bool) -> dict[str, Any]:
        import json
        from trading_agent.domain import canonical
        from trading_agent.legacy_reconciliation import identity

        if authorized is not True:
            raise PermissionError("H1_TOKEN_REQUIRED")
        with self.service._account_lock:
            with self.store.connection() as db:
                row = db.execute(
                    "SELECT * FROM legacy_quarantine WHERE record_hash=? AND account=?",
                    (record_hash, self.settings.account),
                ).fetchone()
            if row is None:
                raise ValueError("LEGACY_RECORD_NOT_FOUND")
            if row["resolved"]:
                return {"resolved": True, "record_hash": record_hash}
            expected = identity(json.loads(row["payload"]))
            evidence = self.broker.reconcile_legacy(expected)
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE legacy_quarantine SET resolved=1,evidence=? WHERE record_hash=?",
                    (canonical(evidence), record_hash),
                )
                self.store._event(
                    db,
                    "legacy_reconciled",
                    {"record_hash": record_hash, "evidence": evidence},
                )
            return {"resolved": True, "record_hash": record_hash, "evidence": evidence}
