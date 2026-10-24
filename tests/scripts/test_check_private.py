"""scripts/check_private.py: terms from the gitignored files, matched in staged files and messages."""

import importlib.util
from pathlib import Path

REPO = Path(__file__).parents[2]
_spec = importlib.util.spec_from_file_location("check_private", REPO / "scripts" / "check_private.py")
check_private = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_private)


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def terms(tmp_path: Path, inventory: str = "", env: str = "", extra: str = "") -> dict[str, str]:
    return check_private.private_terms(
        write(tmp_path, "inventory.yaml", inventory) if inventory else tmp_path / "missing.yaml",
        write(tmp_path, ".env.rig", env) if env else tmp_path / "missing.env",
        write(tmp_path, ".private-terms", extra) if extra else tmp_path / "missing.terms",
    )


def test_no_private_files_means_no_terms(tmp_path):
    assert terms(tmp_path) == {}


def test_terms_come_from_each_private_file(tmp_path):
    found = terms(
        tmp_path,
        inventory="shelly:\n  - entity_id: light.Kitchen_Relay\n    roles: [light_onoff]\n",
        env="HA_URL=http://ha.example.lan:8123\nHA_TOKEN=abc.def\n",
        extra="# names\nAcme Street\n\n",
    )
    assert found == {
        "light.kitchen_relay": "light.Kitchen_Relay",
        "ha.example.lan": "ha.example.lan",
        "abc.def": "HA_TOKEN from .env.rig",
        "acme street": "Acme Street",
    }


def test_generic_host_is_not_a_term(tmp_path):
    assert terms(tmp_path, env="HA_URL=http://homeassistant.local:8123\n") == {}


def test_find_reports_matches_case_insensitively_by_label(tmp_path):
    staged = write(tmp_path, "doc.md", "fine\nToken ABC.DEF here\n")
    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"\xff\xfe")
    hits = check_private.find([staged, binary], {"abc.def": "HA_TOKEN from .env.rig"})
    assert hits == [f"{staged}:2: HA_TOKEN from .env.rig"]


def test_main_passes_without_terms(tmp_path, monkeypatch):
    monkeypatch.setattr(check_private, "private_terms", dict)
    assert check_private.main([str(write(tmp_path, "doc.md", "anything"))]) == 0


def test_main_fails_on_a_hit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(check_private, "private_terms", lambda: {"acme street": "Acme Street"})
    assert check_private.main([str(write(tmp_path, "msg", "Fix lamp on acme street"))]) == 1
    assert "Acme Street" in capsys.readouterr().out
