"""The lineage route's per-snapshot :class:`LineageIndex`: built once however
many requests race for it, moved along from the previous generation's by the
row delta, and never keeping a snapshot alive."""
import gc
import threading
import time
import weakref

import pytest

from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.lineage import LineageIndex

pytest.importorskip("fastapi")
from vmn_exp.ui import routes_lineage  # noqa: E402

SHA = "a" * 64


def _row(verstr, idx, digest=SHA):
    return {"verstr": verstr, "idx": idx, "inputs": {"d": {"uri": "s3://b/k", "digest": digest}}}


def _snapshot(app, rows, generation=1, outputs=None):
    return IndexSnapshot.build(app, generation, rows, {}, outputs=outputs)


def _maps(index):
    return index.rows, index.producers, index.digest_consumers, index.uri_consumers


class _Counting(LineageIndex):
    builds = 0

    def __init__(self, rows, outputs_of=None):
        type(self).builds += 1
        time.sleep(0.2)
        super().__init__(rows, outputs_of)


@pytest.fixture
def counting(monkeypatch):
    _Counting.builds = 0
    monkeypatch.setattr(routes_lineage, "LineageIndex", _Counting)
    return _Counting


def test_racing_requests_build_one_index(counting):
    snap = _snapshot("race", [_row(f"t{i}", i + 1) for i in range(10)])
    got = []
    threads = [threading.Thread(target=lambda: got.append(routes_lineage.lineage_index(snap)))
               for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert counting.builds == 1
    assert all(index is got[0] for index in got)


def test_next_generation_is_moved_not_rebuilt(counting):
    rows = [_row(f"t{i}", i + 1) for i in range(40)]
    outputs = {"t0": {"d.csv": {"path": "d.csv", "digest": SHA}}}
    routes_lineage.lineage_index(_snapshot("moved", rows, 1, outputs))
    rows[3] = _row("t3", 4, digest="b" * 64)
    rows.append(_row("t40", 41))
    newer = _snapshot("moved", rows, 2, outputs)
    index = routes_lineage.lineage_index(newer)
    assert counting.builds == 1
    assert _maps(index) == _maps(LineageIndex(newer.rows, newer.outputs_of))


def test_an_index_never_keeps_its_snapshot_alive():
    snap = _snapshot("alive", [_row("t0", 1)], outputs={"t0": {"x": {"path": "x", "digest": SHA}}})
    assert routes_lineage.lineage_index(snap).producers[SHA] == [("t0", "x")]
    ref = weakref.ref(snap)
    del snap
    gc.collect()
    assert ref() is None
