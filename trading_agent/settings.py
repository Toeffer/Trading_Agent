"""Explicit runtime configuration; constructed during application startup."""

from dataclasses import dataclass
import hashlib
import os
import math
from pathlib import Path
from typing import Mapping

from trading_agent.domain import content_hash


@dataclass(frozen=True, slots=True)
class Settings:
    account: str
    host: str = "127.0.0.1"
    port: int = 4002
    client_id: int = 777
    mode: str = "paper"
    base_currency: str = "EUR"
    state_dir: Path = Path("/var/lib/ibkr-bridge")
    rules_path: Path = Path("/etc/ibkr-bridge/paper-trading-rules.yaml")
    proposal_dir: Path = Path("/var/lib/ibkr-proposals")
    token_hash: str = ""
    allow_orders: bool = False
    release: str = "unverified"
    queue_capacity: int = 32
    read_timeout: float = 8.0
    acknowledgement_timeout: float = 20.0

    def __post_init__(self) -> None:
        if self.mode != "paper" or not self.account.strip():
            raise ValueError(
                "Explicit approved paper account and paper mode are required"
            )
        if not 1 <= self.port <= 65535 or self.client_id < 0:
            raise ValueError("Invalid gateway configuration")
        if self.queue_capacity < 1 or not all(
            math.isfinite(v) and 0 < v <= 60
            for v in (self.read_timeout, self.acknowledgement_timeout)
        ):
            raise ValueError("Invalid broker resource bounds")
        if self.token_hash and (
            len(self.token_hash) != 64
            or any(c not in "0123456789abcdef" for c in self.token_hash)
        ):
            raise ValueError("H1 hash must be SHA-256")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        if env.get("IBKR_ALLOW_ORDERS", "false").lower() not in ("true", "false"):
            raise ValueError("IBKR_ALLOW_ORDERS must be true or false")
        return cls(
            account=env.get("IBKR_ACCOUNT", ""),
            host=env.get("IBKR_HOST", "127.0.0.1"),
            port=int(env.get("IBKR_PORT", "4002")),
            client_id=int(env.get("IBKR_CLIENT_ID", "777")),
            mode=env.get("IBKR_MODE", "paper"),
            base_currency=env.get("IBKR_BASE_CURRENCY", "EUR"),
            state_dir=Path(env.get("IBKR_STATE_DIR", "/var/lib/ibkr-bridge")),
            rules_path=Path(
                env.get("IBKR_RULES_PATH", "/etc/ibkr-bridge/paper-trading-rules.yaml")
            ),
            proposal_dir=Path(env.get("IBKR_PROPOSAL_DIR", "/var/lib/ibkr-proposals")),
            token_hash=env.get("H1_APPROVAL_TOKEN_HASH", ""),
            allow_orders=env.get("IBKR_ALLOW_ORDERS", "false").lower() == "true",
            release=env.get("IBKR_RELEASE", "unverified"),
        )

    def verify_token(self, token: str | None) -> bool:
        import hmac

        return bool(
            self.token_hash
            and token
            and hmac.compare_digest(
                hashlib.sha256(token.strip().encode("utf-8")).hexdigest(),
                self.token_hash,
            )
        )

    def public_identity(self) -> dict[str, object]:
        public = {
            "account": self.account,
            "mode": self.mode,
            "host": self.host,
            "port": self.port,
            "client_id": self.client_id,
            "base_currency": self.base_currency,
            "release": self.release,
            "allow_orders": self.allow_orders,
            "state_dir": str(self.state_dir),
            "rules_path": str(self.rules_path),
            "proposal_dir": str(self.proposal_dir),
            "queue_capacity": self.queue_capacity,
            "read_timeout": self.read_timeout,
            "acknowledgement_timeout": self.acknowledgement_timeout,
        }
        return {**public, "configuration_hash": content_hash(public)}
