"""Resolve implementation source for retained architectural assertions.

Behavioral tests must import and execute the real public contracts instead.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def implementation_source(entry: str) -> str:
    if entry == "ibkr_operator.py":
        return "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "trading_agent/cli").glob("operator_*.py")))
    target = {"bridge.py": "http_compat.py", "guard.py": "legacy_guard.py"}[entry]
    return (ROOT / "trading_agent" / target).read_text(encoding="utf-8")
