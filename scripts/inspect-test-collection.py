"""Print import-time operational calls without importing any tests."""
import ast
from pathlib import Path

root = Path(__file__).resolve().parent.parent
for path in sorted((root / "tests").glob("test_*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            continue
        if isinstance(statement, ast.If) and "__name__" in ast.unparse(statement.test):
            continue
        for node in ast.walk(statement):
            if isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                if any(term in name for term in ("urlopen", "requests.", "httpx.", "subprocess.", "sys.exit", "write_text", "mkdir", "unlink", "rmtree")):
                    print(f"{path.name}:{node.lineno}: {name}")
