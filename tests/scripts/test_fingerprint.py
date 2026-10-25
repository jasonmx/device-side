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


def test_main_prints_every_adapter(capsys):
    assert fp.main() == 0
    lines = capsys.readouterr().out.splitlines()
    adapters = [adapter for _, _, adapter in AdapterRegistry.discover().matrix() if adapter is not None]
    assert len(lines) == len(adapters)
    assert any("turn_on_for" in line and "integrations/shelly/turn_on_for.py" in line for line in lines)
