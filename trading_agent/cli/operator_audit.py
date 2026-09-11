"""Static checkpoint checks of executable calls, not words in documentation."""

import ast
import textwrap


def readonly_findings(source: str) -> list[str]:
    if not source.strip():
        return ["SOURCE_UNAVAILABLE"]
    tree = ast.parse(textwrap.dedent(source))
    findings = []
    forbidden = {
        "placeOrder",
        "cancelOrder",
        "save_guard_state_atomic",
        "initialize_guard_state",
        "append_guard_event",
        "create_approval_record",
        "run_preflight",
        "_internal_place_order",
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else ""
        )
        if name in forbidden:
            findings.append(name)
        literals = [
            x.value
            for arg in node.args
            for x in ast.walk(arg)
            if isinstance(x, ast.Constant) and isinstance(x.value, str)
        ]
        if name in ("_fetch", "urlopen", "Request", "get", "post", "request"):
            findings.extend(
                value
                for value in literals
                if value.startswith(("/order", "/connect")) or "/order/" in value
            )
        if name in ("open", "read_text", "read_bytes"):
            expression = ast.unparse(node).lower()
            if "h1_token" in expression or "token_file" in expression:
                findings.append("H1_SECRET_READ")
    return sorted(set(findings))
