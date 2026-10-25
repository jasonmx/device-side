#!/usr/bin/env python3
"""Print every adapter's fingerprint: the hash a bench record carries to prove which code it tested.

The hash covers the adapter module's AST without docstrings or the `AdapterScope(...)` assignment, so rewording a
docstring or widening scope after a tester report keeps existing records, and any other change resets them.

Usage: scripts/fingerprint.py
"""

import ast
import hashlib
import inspect
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _is_docstring(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _is_scope(node: ast.stmt) -> bool:
    if not isinstance(node, ast.Assign | ast.AnnAssign) or not isinstance(node.value, ast.Call):
        return False
    func = node.value.func
    return (func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)) == "AdapterScope"


_DOCUMENTED = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _strip(node: ast.AST) -> None:
    for child in ast.walk(node):
        body = getattr(child, "body", None)
        if isinstance(body, list):
            if isinstance(child, _DOCUMENTED) and body and _is_docstring(body[0]):
                body.pop(0)
            body[:] = [stmt for stmt in body if not _is_scope(stmt)]


def fingerprint(path: Path) -> str:
    """The first 16 hex digits of the sha256 of the module's stripped AST."""
    tree = ast.parse(path.read_text())
    _strip(tree)
    return hashlib.sha256(ast.dump(tree).encode()).hexdigest()[:16]


def adapter_path(adapter: object) -> Path:
    return Path(inspect.getsourcefile(type(adapter)))


def main() -> int:
    sys.path.insert(0, str(REPO))
    from custom_components.device_side.core.registry import AdapterRegistry

    for action, integration, adapter in AdapterRegistry.discover().matrix():
        if adapter is not None:
            path = adapter_path(adapter)
            print(f"{integration:8} {action:16} {fingerprint(path)}  {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
