"""A Postgres-backed server's index (ElectedIndex) never waits for a cold
first load either: it answers its current index's snapshot_now()."""
from vmn_exp.ui.elected_index import ElectedIndex
from vmn_exp.ui.refresher import Refresher


class _Index:
    def __init__(self, name):
        self.name = name

    def snapshot_now(self):
        return f"{self.name} now"

    def snapshot(self):
        raise AssertionError("a request waited for the first load")


def _elected(leading):
    index = ElectedIndex.__new__(ElectedIndex)
    index._leader, index._follower, index.leading = _Index("leader"), _Index("follower"), leading
    return index


def test_it_answers_the_current_index_snapshot_now():
    assert _elected(True).snapshot_now() == "leader now"
    assert _elected(False).snapshot_now() == "follower now"


def test_the_refresher_serves_it_without_waiting(monkeypatch):
    refresher = Refresher.__new__(Refresher)
    monkeypatch.setattr(Refresher, "_watch", lambda self, index: None)
    assert refresher.snapshot(_elected(False)) == "follower now"
