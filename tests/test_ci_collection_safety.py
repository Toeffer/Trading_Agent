#!/usr/bin/env python3
"""
CI Collection-Time Safety Tests

Validates that no test file causes import-time side effects that would
break pytest collection.  Specifically:

  T1  No test file calls sys.exit() at module/import level
  T2  No test file calls raise SystemExit at module/import level
  T3  Both are allowed only inside "if __name__ == '__main__':"

These enforce that acceptance-script patterns (e.g. the old
"raise SystemExit(main())" style) do not regress into files
that pytest imports during collection.
"""

import ast
import sys
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent


def _is_module_level(node: ast.AST) -> bool:
    """Return True if node is at module level (not inside a function/class)."""
    # We walk the tree; if a node is a direct child of Module, it's module-level.
    # This function is used after we've already identified suspicious nodes.
    return True  # The caller already filtered by checking the parent


def _has_module_level_sys_exit(filepath: Path) -> list[str]:
    """Return list of errors for module-level sys.exit/SystemExit in a file."""
    errors: list[str] = []
    try:
        source = filepath.read_text()
    except Exception:
        return errors

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        errors.append(f"{filepath.name}: syntax error: {e}")
        return errors

    # Walk the AST looking for sys.exit() or raise SystemExit()
    for node in ast.walk(tree):
        # Check for sys.exit() call
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                if (isinstance(func.value, ast.Name)
                        and func.value.id == "sys"
                        and func.attr == "exit"):
                    errors.append(
                        f"{filepath.name}:{node.lineno}: sys.exit() call — "
                        f"must be inside 'if __name__ == \"__main__\":'"
                    )

        # Check for raise SystemExit(...)
        if isinstance(node, ast.Raise):
            exc = node.exc
            if exc is not None and isinstance(exc, ast.Call):
                exc_func = exc.func
                if isinstance(exc_func, ast.Name) and exc_func.id == "SystemExit":
                    errors.append(
                        f"{filepath.name}:{node.lineno}: raise SystemExit() — "
                        f"must be inside 'if __name__ == \"__main__\":'"
                    )

    # Now filter: only flag if NOT inside __main__ guard
    # Re-parse to find __main__ blocks
    filtered: list[str] = []
    try:
        tree2 = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return errors

    for node in ast.walk(tree2):
        if isinstance(node, ast.If):
            # Check if it's 'if __name__ == "__main__":'
            test = node.test
            if (isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Name)
                    and test.left.id == "__name__"
                    and len(test.ops) == 1
                    and isinstance(test.ops[0], ast.Eq)
                    and len(test.comparators) == 1
                    and isinstance(test.comparators[0], ast.Constant)
                    and test.comparators[0].value == "__main__"):
                # This is a __main__ block — remove errors within its line range
                block_start = node.lineno
                block_end = node.end_lineno or 99999
                filtered = [
                    e for e in errors
                    if not (
                        block_start <= int(e.split(":")[1]) <= block_end
                    )
                ]
                errors = filtered[:]  # update the working list

    return errors


def _python_test_files() -> list[Path]:
    """Return all .py test files in tests/ (excluding __pycache__)."""
    return sorted([
        p for p in TESTS_DIR.glob("*.py")
        if p.name != "__init__.py"
        and "__pycache__" not in str(p)
    ])


# ============================================================================
# T1–T3: No module-level sys.exit / SystemExit
# ============================================================================

class TestCollectionSafety:
    """CI collection safety: no import-time side effects."""

    def test_no_module_level_sys_exit(self):
        """T1: No test file calls sys.exit() at module level."""
        all_errors: list[str] = []
        for fp in _python_test_files():
            errs = _has_module_level_sys_exit(fp)
            all_errors.extend(errs)

        if all_errors:
            raise AssertionError(
                "Module-level sys.exit() / SystemExit found:\n" +
                "\n".join(f"  - {e}" for e in all_errors) +
                "\n\nThese must be inside 'if __name__ == \"__main__\":' blocks."
            )

    def test_no_module_level_raise_systemexit(self):
        """T2: No test file raises SystemExit at module level."""
        # Same check; the helper covers both patterns.
        # This test is a semantic duplicate for clarity in CI logs.
        for fp in _python_test_files():
            source = fp.read_text()
            # Quick grep to fail fast
            if "raise SystemExit" not in source and "SystemExit" not in source:
                continue
            errs = _has_module_level_sys_exit(fp)
            if errs:
                raise AssertionError(
                    f"Module-level SystemExit in {fp.name}:\n" +
                    "\n".join(f"  - {e}" for e in errs)
                )

    def test_all_test_files_parseable(self):
        """All test files parse as valid Python without import errors."""
        for fp in _python_test_files():
            try:
                ast.parse(fp.read_text(), filename=str(fp))
            except SyntaxError as e:
                raise AssertionError(
                    f"{fp.name} has syntax error: {e}"
                )
