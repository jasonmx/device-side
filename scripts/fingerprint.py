#!/usr/bin/env python3
"""Print every adapter's fingerprint: the hash a bench record carries to prove which code it tested.

The hash covers the adapter module's AST without docstrings or the `AdapterScope(...)` assignment, so rewording a
docstring or widening scope after a tester report keeps existing records, and any other change resets them. It also
covers, stripped the same way, every module the adapter imports from its own integration package (`from .x import`,
`from . import x`), and theirs in turn: a change to a shared helper changes the code the adapter runs.

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


def _module(package: Path, name: str) -> Path | None:
    for path in (package / f"{name}.py", package / name / "__init__.py"):
        if path.is_file():
            return path
    return None


def _siblings(path: Path, tree: ast.Module) -> set[Path]:
    """The modules this one imports from its own package, by a single-dot relative import."""
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 1:
            continue
        if node.module:
            found.add(_module(path.parent, node.module.replace(".", "/")))
        else:
            # `from . import x`: x is a module, or a name the package's __init__ defines.
            found |= {_module(path.parent, alias.name) or path.parent / "__init__.py" for alias in node.names}
    return found - {None, path}


def fingerprint(path: Path) -> str:
    """The first 16 hex digits of the sha256 of the stripped ASTs of the module and its package siblings."""
    dumps, pending = {}, [path]
    while pending:
        module = pending.pop()
        if module in dumps:
            continue
        tree = ast.parse(module.read_text())
        # A package __init__ imports every adapter it registers; following it would tie them all together.
        if module.name != "__init__.py":
            pending += _siblings(module, tree)
        _strip(tree)
        dumps[module] = ast.dump(tree)
    parts = [dumps.pop(path)] + [f"{module.relative_to(path.parent)}\n{dump}" for module, dump in sorted(dumps.items())]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


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
