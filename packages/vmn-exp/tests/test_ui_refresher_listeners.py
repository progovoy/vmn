"""The ui refreshers' refresh listeners and :class:`NotingRefresher`: every
listener hears each refresh (none clobbers another), a noting refresher notes
the index it is asked about, and an inline snapshot lists fully without
changing the shared index's sweep interval."""
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.snapshot import open_storage
from vmn_exp.ui.refresher import InlineRefresher, NotingRefresher, Refresher


class _Index:
    def __init__(self):
        self.generation = 0

    def reconcile(self):
        pass

    def refresh(self):
        self.generation += 1
        return self

    def snapshot(self):
        return ("snapshot", self.generation)


def test_every_listener_hears_an_inline_refresh():
    inline, heard = InlineRefresher(), []
    inline.add_listener(lambda index, snap: heard.append(("a", snap)))
    inline.add_listener(lambda index, snap: heard.append(("b", snap)))
    snap = inline.snapshot(_Index())
    assert heard == [("a", snap), ("b", snap)]


def test_every_listener_hears_a_background_refresh():
    refresher, heard = Refresher(interval_sec=60, idle_sec=60), []
    refresher.add_listener(lambda index, snap: heard.append("a"))
    refresher.add_listener(lambda index, snap: heard.append("b"))
    refresher._refresh(_Index(), type("W", (), {"failing": False})())
    assert heard == ["a", "b"]


def test_a_noting_refresher_notes_the_index_then_asks_its_refresher():
    noted, index = [], _Index()
    noting = NotingRefresher(InlineRefresher(), noted.append)
    assert noting.snapshot(index) == ("snapshot", 1)
    assert noted == [index]
    assert noting.background is False  # the rest is its refresher's


def test_an_inline_snapshot_leaves_the_shared_sweep_interval_alone(tmp_path):
    storage = open_storage(root=str(tmp_path / "store"), area="runs")
    index = ExperimentIndex(storage, "app", full_sweep_sec=300)
    InlineRefresher().snapshot(index)
    assert index.full_sweep_sec == 300
