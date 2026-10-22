"""``subtree_rows_direct``: an outer run's rows found through its child
markers — no listing of the app's records, so an outer run's page answers
while the index of a 46k-run store is still loading."""
import threading
import time

import pytest
import yaml

from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.core.subtree_direct import subtree_rows_direct
from vmn_exp.core.tree import annotate_rows
from vmn_exp.core.writer import create_run, save_run_state
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "my_app"
OUTER = "0.0.1-dev.abc.def"


def _meta(verstr, parent=None, ts="2026-01-01T00:00:00Z"):
    meta = {"verstr": verstr, "timestamp": ts, "code_verstr": OUTER, "name": f"n-{verstr}"}
    if parent:
        meta["parent"] = parent
    return meta


class _FakeStore:
    """Records + markers in memory; every read sleeps like a round trip and
    is counted, so tests see how many requests and how many overlapped."""

    LATENCY = 0.02

    def __init__(self):
        self.metas, self.states, self.children = {}, {}, {}
        self.calls = []
        self._lock = threading.Lock()
        self.in_flight = self.peak = 0

    def add(self, verstr, parent=None, state=None, ts="2026-01-01T00:00:00Z"):
        self.metas[verstr] = _meta(verstr, parent, ts)
        if state:
            self.states[verstr] = yaml.dump(state).encode()
        if parent:
            self.children.setdefault(parent, []).append(verstr)

    def _call(self, op, value):
        with self._lock:
            self.calls.append(op)
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
        time.sleep(self.LATENCY)
        with self._lock:
            self.in_flight -= 1
        return value

    def list_children(self, app_name, parent):
        return self._call("LIST", sorted(self.children.get(parent, [])))

    def load_metadata(self, app_name, verstr):
        return self._call("GET", self.metas.get(verstr))

    def load_file(self, app_name, verstr, filename):
        assert filename == RUN_STATE_FILE
        return self._call("GET", self.states.get(verstr))

    def is_remote(self):
        return True

    def __getattr__(self, name):  # any full listing is a failure
        raise AssertionError(f"subtree_rows_direct called {name}")


FINISHED = {"state": "finished", "exit_code": 0}


@pytest.fixture
def outer24():
    store = _FakeStore()
    store.add(OUTER, state={"state": "running", "heartbeat": "2026-01-01T00:00:00Z"})
    for i in range(24):
        store.add(f"{OUTER}.r{i + 2}", parent=OUTER, state=FINISHED,
                  ts=f"2026-01-01T00:00:{i:02d}Z")
    return store


def test_a_24_child_outer_costs_one_list_and_two_reads_per_run(outer24):
    found = subtree_rows_direct(outer24, APP, OUTER, max_depth=1)

    assert [r["verstr"] for r in found.rows] == [OUTER] + [f"{OUTER}.r{i + 2}" for i in range(24)]
    assert outer24.calls.count("LIST") == 1
    assert outer24.calls.count("GET") == 2 * 25
    assert outer24.peak > 8
    assert not found.truncated


def test_by_default_each_child_is_probed_for_children_in_the_same_wave(outer24):
    started = time.monotonic()
    subtree_rows_direct(outer24, APP, OUTER)
    elapsed = time.monotonic() - started

    assert outer24.calls.count("LIST") == 1 + 24
    assert outer24.calls.count("GET") == 2 * 25
    # Two waves of round trips (the outer, then its children), not 75.
    assert elapsed < 10 * _FakeStore.LATENCY


def test_rows_are_the_index_rows_of_the_metadata_and_states_feed_status(outer24):
    found = subtree_rows_direct(outer24, APP, OUTER)
    rows = annotate_rows(found.rows, found.run_states)
    by = {r["verstr"]: r for r in rows}

    outer = by[OUTER]
    assert outer["kind"] == "outer" and len(outer["children"]) == 24
    assert outer["name"] == f"n-{OUTER}" and outer["idx"] is None
    kid = by[f"{OUTER}.r2"]
    assert kid["parent"] == OUTER and kid["kind"] == "inner"
    assert kid["status"] == "succeeded"
    assert kid["params"] == {} and kid["metrics"] == {}


def test_nested_outers_are_followed(outer24):
    mid = f"{OUTER}.r2"
    outer24.add(mid + ".x", parent=mid, state=FINISHED)

    found = subtree_rows_direct(outer24, APP, OUTER)

    assert mid + ".x" in [r["verstr"] for r in found.rows]


def test_max_depth_bounds_the_descent(outer24):
    mid = f"{OUTER}.r2"
    outer24.add(mid + ".x", parent=mid)

    found = subtree_rows_direct(outer24, APP, OUTER, max_depth=1)

    assert mid + ".x" not in [r["verstr"] for r in found.rows]


def test_limit_caps_the_descendants_and_says_so(outer24):
    found = subtree_rows_direct(outer24, APP, OUTER, limit=5)

    assert len(found.rows) == 1 + 5
    assert found.truncated
    assert outer24.calls.count("GET") == 2 * 6


def test_a_stale_marker_is_skipped(outer24):
    outer24.children[OUTER].append("gone")
    outer24.add("elsewhere")
    outer24.children[OUTER].append("elsewhere")  # its parent field says otherwise

    verstrs = [r["verstr"] for r in subtree_rows_direct(outer24, APP, OUTER).rows]

    assert "gone" not in verstrs and "elsewhere" not in verstrs
    assert len(verstrs) == 25


def test_a_missing_outer_has_no_rows(outer24):
    found = subtree_rows_direct(outer24, APP, "nope")

    assert found.rows == [] and found.run_states == {}


def test_a_real_local_store(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path / "root"), area="runs")
    template = {"timestamp": "2026-01-01T00:00:00Z"}
    outer = create_run(storage, APP, OUTER, template, {})
    kids = [create_run(storage, APP, OUTER, template, {}, parent=outer) for _ in range(3)]
    save_run_state(storage, APP, kids[0], {"state": "finished"}, exit_code=1)

    found = subtree_rows_direct(storage, APP, outer)

    assert sorted(r["verstr"] for r in found.rows) == sorted([outer] + kids)
    assert found.run_states[kids[0]]["exit_code"] == 1
