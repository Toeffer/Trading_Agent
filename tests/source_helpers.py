"""Resolve implementation source for retained architectural assertions.

Behavioral tests must import and execute the real public contracts instead.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def implementation_source(entry: str, *, historical: bool = False) -> str:
    if entry == "ibkr_operator.py":
        return "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "trading_agent/cli").glob("operator_*.py")))
    target = {"bridge.py": "http_compat.py", "guard.py": "legacy_guard.py"}[entry]
    source = (ROOT / "trading_agent" / target).read_text(encoding="utf-8")
    if historical and entry == "guard.py":
        import ast
        tree = ast.parse(source)
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_preflight")
        previous = (ROOT / "tests/historical/preflight.py").read_text(encoding="utf-8")
        prior_node = next(n for n in ast.parse(previous).body if isinstance(n, ast.FunctionDef) and n.name == "run_preflight")
        lines = source.splitlines(keepends=True)
        lines[node.lineno - 1:node.end_lineno] = previous.splitlines(keepends=True)[prior_node.lineno - 1:prior_node.end_lineno]
        return "".join(lines)
    return source
