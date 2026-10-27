"""The rig's journal: what a run changed and has not yet put back, kept on disk."""

from tests.rig.journal import Journal


def test_a_journal_survives_a_new_reader_and_goes_once_empty(tmp_path):
    path = tmp_path / "journal.json"
    journal = Journal(path)
    assert not journal
    assert not path.exists()

    journal.update(paused=["automation.motion"], options={"opt": True})
    reread = Journal(path)
    assert reread.get("paused") == ["automation.motion"]
    assert reread.get("taken", {}) == {}

    journal.clear("paused")
    assert Journal(path).get("paused") is None
    assert Journal(path).get("options") == {"opt": True}

    journal.clear("options", "taken")
    assert not journal
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []  # nor a temp file
