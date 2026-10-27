"""An ended outer run settles what it left behind (derived, never stored):
a descendant that never started is ``never_started`` and a stuck one is
``lost``, so the tree rollup stops reading ``created``/``stuck`` forever.

A run's own ``status`` stays what :func:`derive_status` says; its
``settled`` field and the rollups change. "Ended" is the nearest started
ancestor's own status: succeeded, failed or stuck (a container that never
ran passes its parent's verdict on).
"""
from vmn_exp.core.query import filter_rows
from vmn_exp.core.status import CREATED, FAILED, RUNNING, STUCK, SUCCEEDED
from vmn_exp.core.tree import annotate_tree, fleet_summary, run_status, subtree_status

LOST, NEVER = "lost", "never_started"


def _row(verstr, status, parent=None, **fields):
    return dict({"verstr": verstr, "status": status, "parent": parent}, **fields)


def _tree(*rows):
    return {r["verstr"]: r for r in annotate_tree(list(rows))}


def _kids(outer_status, *statuses):
    return [_row("o", outer_status)] + [
        _row(f"k{i}", s, parent="o") for i, s in enumerate(statuses)]


class TestAnnotate:
    def test_an_ended_outer_settles_its_never_started_and_stuck_children(self):
        rows = _tree(*_kids(SUCCEEDED, SUCCEEDED, CREATED, STUCK))
        assert [rows[k]["settled"] for k in ("k0", "k1", "k2")] == [None, NEVER, LOST]
        assert [rows[k]["status"] for k in ("k1", "k2")] == [CREATED, STUCK]
        assert rows["o"]["settled"] is None

    def test_lost_children_roll_up_as_failed_and_never_started_ones_not_at_all(self):
        assert _tree(*_kids(SUCCEEDED, SUCCEEDED, CREATED))["o"]["tree_status"] == SUCCEEDED
        assert _tree(*_kids(SUCCEEDED, CREATED, STUCK))["o"]["tree_status"] == FAILED
        rows = _tree(*_kids(SUCCEEDED, CREATED, STUCK))
        assert (rows["k0"]["tree_status"], rows["k1"]["tree_status"]) == (None, FAILED)

    def test_a_failed_or_stuck_outer_ends_too(self):
        assert _tree(*_kids(FAILED, CREATED))["k0"]["settled"] == NEVER
        rows = _tree(*_kids(STUCK, CREATED, SUCCEEDED))
        assert rows["k0"]["settled"] == NEVER
        assert rows["o"]["tree_status"] == STUCK  # its own status is its own

    def test_a_running_outer_settles_nothing(self):
        rows = _tree(*_kids(RUNNING, CREATED, STUCK))
        assert (rows["k0"]["settled"], rows["k1"]["settled"]) == (None, None)
        assert rows["o"]["tree_status"] == STUCK

    def test_a_container_outer_settles_nothing(self):
        rows = _tree(*_kids(CREATED, CREATED, SUCCEEDED))
        assert rows["k0"]["settled"] is None
        assert rows["o"]["tree_status"] == CREATED

    def test_a_running_child_of_an_ended_outer_keeps_running(self):
        rows = _tree(*_kids(SUCCEEDED, RUNNING, CREATED))
        assert rows["k0"]["settled"] is None
        assert rows["o"]["tree_status"] == RUNNING

    def test_a_never_started_container_passes_the_verdict_down(self):
        rows = _tree(_row("top", SUCCEEDED), _row("mid", CREATED, parent="top"),
                     _row("leaf", CREATED, parent="mid"), _row("gone", STUCK, parent="mid"))
        assert [rows[v]["settled"] for v in ("mid", "leaf", "gone")] == [NEVER, NEVER, LOST]
        assert rows["top"]["tree_status"] == FAILED

    def test_a_running_sub_outer_keeps_its_own_children_open(self):
        rows = _tree(_row("top", SUCCEEDED), _row("mid", RUNNING, parent="top"),
                     _row("leaf", CREATED, parent="mid"))
        assert rows["leaf"]["settled"] is None
        assert rows["top"]["tree_status"] == RUNNING

    def test_a_stuck_child_settles_its_own_children(self):
        rows = _tree(_row("top", RUNNING), _row("mid", STUCK, parent="top"),
                     _row("leaf", CREATED, parent="mid"))
        assert (rows["mid"]["settled"], rows["leaf"]["settled"]) == (None, NEVER)

    def test_top_level_runs_are_never_settled(self):
        rows = _tree(_row("a", CREATED), _row("b", STUCK))
        assert (rows["a"]["settled"], rows["b"]["settled"]) == (None, None)

    def test_child_counts_stay_the_childrens_own_statuses(self):
        rows = _tree(*_kids(SUCCEEDED, CREATED, STUCK))
        assert rows["o"]["child_counts"] == {CREATED: 1, STUCK: 1}

    def test_the_cyclic_path_gives_the_same_answer(self):
        loop = [_row("a", SUCCEEDED, parent="b"), _row("b", SUCCEEDED, parent="a")]
        rows = _tree(*_kids(SUCCEEDED, CREATED, STUCK), *loop)
        assert rows["o"]["tree_status"] == FAILED
        assert rows["k0"]["settled"] == NEVER


class TestSweep:
    """An incomplete sweep still running (or never run) reads ``created``;
    one that ended reads its final status — its unclaimed slots never start."""

    def _sweep(self, status):
        outer = _row("s", status, sweep_planned=20)
        trials = [_row(f"t{i}", SUCCEEDED, parent="s", tags={"sweep_trial": str(i)})
                  for i in range(16)]
        return _tree(outer, *trials)["s"]

    def test_an_ended_sweep_short_of_its_plan_reads_its_own_status(self):
        assert self._sweep(SUCCEEDED)["tree_status"] == SUCCEEDED
        assert self._sweep(FAILED)["tree_status"] == FAILED

    def test_an_unfinished_sweep_short_of_its_plan_is_still_created(self):
        assert self._sweep(CREATED)["tree_status"] == CREATED
        assert self._sweep(RUNNING)["tree_status"] == RUNNING


def _finished(code=0):
    return {"state": "finished", "exit_code": code}


def _stale():
    return {"state": "running", "heartbeat": "2020-01-01T00:00:00Z", "heartbeat_interval_sec": 5}


class TestOneRun:
    """``run_status``/``subtree_status`` (run page, ``vmn-exp show``)."""

    PARENT_OF = {"o": None, "a": "o", "b": "o", "c": "o"}
    STATES = {"o": _finished(0), "a": _finished(0), "b": None, "c": _stale()}

    def test_an_ended_outer_settles_its_subtree(self):
        status = run_status("o", self.PARENT_OF, self.STATES.get)
        assert status["tree_status"] == FAILED  # c is lost
        assert status["settled"] is None

    def test_a_child_reads_its_parent_to_know_it_is_settled(self):
        reads = []

        def read(v):
            reads.append(v)
            return self.STATES[v]

        _, tree = subtree_status("b", self.PARENT_OF, read)
        assert tree["settled"] == NEVER and tree["tree_status"] is None
        assert sorted(reads) == ["b", "o"]

    def test_a_started_run_reads_no_ancestor(self):
        reads = []
        subtree_status("a", self.PARENT_OF, lambda v: reads.append(v) or self.STATES[v])
        assert reads == ["a"]

    def test_the_fleet_counts_the_settled_ones_apart(self):
        children_of = {"o": ["a", "b", "c"]}
        fleet = fleet_summary("o", children_of, self.STATES.get, expected=5, closed=True)
        assert (fleet[NEVER], fleet[LOST]) == (3, 1)  # b and the two unclaimed slots
        assert fleet["counts"] == {RUNNING: 0, SUCCEEDED: 1, FAILED: 0, STUCK: 0, CREATED: 0,
                                   "waiting": 0}
        open_fleet = fleet_summary("o", children_of, self.STATES.get, expected=5)
        assert (open_fleet[NEVER], open_fleet[LOST]) == (0, 0)
        assert open_fleet["counts"][CREATED] == 1 and open_fleet["counts"]["waiting"] == 2


def test_the_query_language_filters_on_settled():
    rows = annotate_tree(_kids(SUCCEEDED, SUCCEEDED, CREATED, STUCK))
    assert [r["verstr"] for r in filter_rows(rows, 'settled = "never_started"')] == ["k1"]
    assert [r["verstr"] for r in filter_rows(rows, 'settled = "lost"')] == ["k2"]
    assert len(filter_rows(rows, "settled = null")) == 2
