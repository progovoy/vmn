"""Run trees stay iterative however deep, and a run page's tree lookup costs a
dict lookup when its edges provider is cheap."""
from collections.abc import Mapping

from version_stamp.core import experiment_status as st
from version_stamp.core.experiment_tree import annotate_tree, subtree_status
from version_stamp.ui.readers import experiment_detail

DEPTH = 5000


def _chain(n):
    return {f"r{i}": (f"r{i - 1}" if i else None) for i in range(n)}


def _state(status):
    if status == st.FAILED:
        return {"state": "finished", "exit_code": 1}
    return {"state": "finished", "exit_code": 0}


def test_subtree_status_of_a_5000_deep_chain():
    parent_of = _chain(DEPTH)
    failed = f"r{DEPTH - 1}"
    state, tree = subtree_status(
        "r0", parent_of, lambda v: _state(st.FAILED if v == failed else st.SUCCEEDED)
    )
    assert tree["tree_status"] == st.FAILED
    assert tree["children"] == ["r1"] and tree["kind"] == "outer"

    _, leaf = subtree_status(failed, parent_of, lambda v: _state(st.SUCCEEDED))
    assert leaf["depth"] == DEPTH - 1
    assert leaf["kind"] == "inner" and leaf["children"] == []


def test_annotate_tree_of_a_5000_deep_chain():
    rows = [
        {"verstr": v, "parent": p, "status": st.FAILED if v == f"r{DEPTH - 1}" else st.SUCCEEDED}
        for v, p in _chain(DEPTH).items()
    ]
    by_verstr = {r["verstr"]: r for r in annotate_tree(rows)}
    assert by_verstr["r0"]["tree_status"] == st.FAILED
    assert by_verstr[f"r{DEPTH - 1}"]["depth"] == DEPTH - 1
    assert by_verstr[f"r{DEPTH - 2}"]["tree_status"] == st.FAILED


def test_annotate_tree_with_a_cycle_still_rolls_up_reachable_runs():
    rows = [
        {"verstr": "a", "parent": "b", "status": st.SUCCEEDED},
        {"verstr": "b", "parent": "a", "status": st.RUNNING},
        {"verstr": "c", "parent": "b", "status": st.FAILED},
    ]
    by_verstr = {r["verstr"]: r for r in annotate_tree(rows)}
    assert by_verstr["a"]["tree_status"] == st.FAILED
    assert by_verstr["b"]["tree_status"] == st.FAILED
    assert by_verstr["c"]["tree_status"] == st.FAILED


class _CountingEdges(Mapping):
    """A read-only edges mapping that counts full scans."""

    scans = 0

    def __init__(self, edges):
        self._edges = edges

    def __getitem__(self, key):
        return self._edges[key]

    def __len__(self):
        return len(self._edges)

    def __iter__(self):
        type(self).scans += 1
        return iter(self._edges)


def test_status_detail_does_not_rescan_an_unchanged_edges_mapping():
    edges = _CountingEdges(dict({f"r{i}": "root" for i in range(1000)}, root=None))
    _CountingEdges.scans = 0

    def provider(storage, app_name):
        return edges

    for _ in range(3):
        status = experiment_detail.status_detail(
            None, "app", "r5", {"parent": "root"}, [], provider,
            read_run_state=lambda s, a, v: None,
        )
    assert status["parent"] == "root" and status["kind"] == "inner"
    assert _CountingEdges.scans <= 1
