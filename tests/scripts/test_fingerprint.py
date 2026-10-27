"""scripts/fingerprint.py: docstrings and the AdapterScope declaration don't count; any other change does."""

from pathlib import Path

import pytest

from custom_components.device_side.core.registry import AdapterRegistry
from scripts import fingerprint as fp

MODULE = '''"""Module docstring."""

from x import AdapterScope

SCOPE = AdapterScope(domains=frozenset({"switch"}))


class Adapter:
    """Class docstring."""

    scope: AdapterScope = AdapterScope(domains=frozenset({"switch"}))

    async def run(self, target):
        """Method docstring."""
        return target.entity_id
'''


@pytest.fixture
def module(tmp_path: Path):
    path = tmp_path / "adapter.py"

    def _fingerprint(text: str) -> str:
        path.write_text(text)
        return fp.fingerprint(path)

    return _fingerprint


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('"""Module docstring."""', '"""Reworded."""'),
        ('"""Method docstring."""', '"""Reworded, at length."""'),
        ('SCOPE = AdapterScope(domains=frozenset({"switch"}))', 'SCOPE = AdapterScope(domains=frozenset({"light"}))'),
        ('scope: AdapterScope = AdapterScope(domains=frozenset({"switch"}))', "scope: AdapterScope = AdapterScope()"),
        ("        return target.entity_id", "        # a comment\n        return target.entity_id"),
    ],
)
def test_docstrings_scope_and_comments_keep_the_fingerprint(module, old, new):
    assert module(MODULE.replace(old, new)) == module(MODULE)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("return target.entity_id", "return target.name"),
        ("from x import AdapterScope", "from y import AdapterScope"),
        ('SCOPE = AdapterScope(domains=frozenset({"switch"}))', 'SCOPE = make(domains=frozenset({"switch"}))'),
    ],
)
def test_a_code_change_resets_the_fingerprint(module, old, new):
    assert module(MODULE.replace(old, new)) != module(MODULE)


def test_a_string_heading_an_if_block_is_code_not_a_docstring(module):
    def guarded(text: str) -> str:
        return MODULE.replace("        return", f'        if target:\n            "{text}"\n        return')

    assert module(guarded("one")) != module(guarded("two"))


@pytest.fixture
def package(tmp_path: Path):
    """An adapter importing helpers, a sibling of a sibling, a name from __init__, and core (outside the package)."""
    root = tmp_path / "integrations" / "x"
    files = {
        "__init__.py": "from .unused import other\n\nNAME = 1\n",
        "adapter.py": "from . import NAME, rpc\nfrom .addressing import address\nfrom ...core import models\n",
        "addressing.py": '"""Addressing."""\n\nfrom .util import clean\n\n\ndef address():\n    return clean()\n',
        "util.py": "from .addressing import address\n\n\ndef clean():\n    return 1\n",
        "rpc.py": "def call():\n    return 2\n",
        "unused.py": "def other():\n    return 3\n",
    }
    (tmp_path / "integrations" / "core.py").parent.mkdir(parents=True)
    root.mkdir()
    for name, text in files.items():
        (root / name).write_text(text)
    (tmp_path / "integrations" / "core.py").write_text("X = 1\n")

    def _edit(name: str, old: str, new: str) -> None:
        path = root / name
        path.write_text(path.read_text().replace(old, new))

    _edit.adapter = root / "adapter.py"
    _edit.root = tmp_path
    return _edit


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        ("addressing.py", "return clean()", "return clean() + 1"),
        ("util.py", "return 1", "return 0"),
        ("rpc.py", "return 2", "return 0"),
        ("__init__.py", "NAME = 1", "NAME = 2"),
    ],
)
def test_a_change_to_a_package_import_resets_the_fingerprint(package, name, old, new):
    before = fp.fingerprint(package.adapter)
    package(name, old, new)
    assert fp.fingerprint(package.adapter) != before


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        ("addressing.py", '"""Addressing."""', '"""Reworded."""'),
        ("unused.py", "return 3", "return 0"),
    ],
)
def test_a_sibling_docstring_or_an_unimported_module_keeps_the_fingerprint(package, name, old, new):
    before = fp.fingerprint(package.adapter)
    package(name, old, new)
    assert fp.fingerprint(package.adapter) == before


def test_an_import_from_outside_the_package_keeps_the_fingerprint(package):
    before = fp.fingerprint(package.adapter)
    (package.root / "integrations" / "core.py").write_text("X = 2\n")
    assert fp.fingerprint(package.adapter) == before


def test_main_prints_every_adapter(capsys):
    assert fp.main() == 0
    lines = capsys.readouterr().out.splitlines()
    adapters = [adapter for _, _, adapter in AdapterRegistry.discover().matrix() if adapter is not None]
    assert len(lines) == len(adapters)
    assert any("turn_on_for" in line and "integrations/shelly/turn_on_for.py" in line for line in lines)
