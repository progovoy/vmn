"""A sweep whose trials all finished but number fewer than planned is not done
(plan 20 A7/D12): its tree rolls up to ``created`` and the UI says
``16/20 · incomplete``.

The planned size comes from the sweep spec (:func:`planned_trials`: grid size,
else ``run_cap``; None for an uncapped random/bayes sweep). The index puts it on
the sweep outer's row as ``sweep_planned`` (from the metadata's ``sweep`` spec),
and :mod:`vmn_exp.core.tree` stays pure: it reads only the rows.
"""
from vmn_exp.core.log import experiment_row
from vmn_exp.core.status import CREATED, FAILED, RUNNING, SUCCEEDED
from vmn_exp.core.sweep.spec import parse_spec, planned_trials
from vmn_exp.core.tree import annotate_rows, annotate_tree, run_status, subtree_status

SWEEP = "1.0.0-dev.sweep"


def _grid(n, run_cap=None):
    data = {
        "method": "grid",
        "metric": {"name": "loss", "goal": "min"},
        "parameters": {"x": {"values": list(range(n))}},
    }
    if run_cap:
        data["run_cap"] = run_cap
    return parse_spec(data)


def _random(run_cap=None):
    data = {
        "method": "random",
        "metric": {"name": "loss", "goal": "min"},
        "parameters": {"lr": {"distribution": "uniform", "min": 0.0, "max": 1.0}},
    }
    if run_cap:
        data["run_cap"] = run_cap
    return parse_spec(data)


def _trial(n, status=SUCCEEDED, attempt=0):
    return {
        "verstr": f"1.0.0-dev.t{n}.a{attempt}",
        "parent": SWEEP,
        "status": status,
        "tags": {"sweep": SWEEP, "sweep_trial": str(n), "sweep_attempt": str(attempt)},
    }


def _sweep(planned, trials):
    outer = {"verstr": SWEEP, "status": CREATED, "tags": {"sweep": "grid"}}
    if planned is not None:
        outer["sweep_planned"] = planned
    rows = annotate_tree([outer] + trials)
    return next(r for r in rows if r["verstr"] == SWEEP)


class TestPlannedTrials:
    def test_a_grid_plans_its_size(self):
        assert planned_trials(_grid(20)) == 20

    def test_a_capped_grid_plans_its_cap(self):
        assert planned_trials(_grid(20, run_cap=5)) == 5

    def test_a_random_sweep_plans_its_run_cap(self):
        assert planned_trials(_random(run_cap=8)) == 8

    def test_an_uncapped_random_sweep_has_no_plan(self):
        assert planned_trials(_random()) is None

    def test_no_or_a_broken_spec_has_no_plan(self):
        assert planned_trials(None) is None
        assert planned_trials({"method": "hill-climb"}) is None
        assert planned_trials("grid") is None


class TestIndexRow:
    def test_a_sweep_outer_row_carries_its_planned_size(self):
        row = experiment_row(1, {"verstr": SWEEP, "sweep": _grid(20)}, [])
        assert row["sweep_planned"] == 20

    def test_other_rows_carry_none(self):
        row = experiment_row(1, {"verstr": "1.0.0-dev.x"}, [])
        assert "sweep_planned" not in row
        uncapped = experiment_row(1, {"verstr": SWEEP, "sweep": _random()}, [])
        assert "sweep_planned" not in uncapped


class TestRollup:
    def test_a_grid_of_20_with_16_finished_trials_is_created(self):
        outer = _sweep(20, [_trial(i) for i in range(16)])
        assert outer["tree_status"] == CREATED
        assert outer["sweep_trials"] == 16

    def test_a_grid_of_20_with_20_finished_trials_succeeded(self):
        outer = _sweep(20, [_trial(i) for i in range(20)])
        assert outer["tree_status"] == SUCCEEDED
        assert outer["sweep_trials"] == 20

    def test_an_uncapped_random_sweep_follows_its_trials(self):
        outer = _sweep(None, [_trial(i) for i in range(16)])
        assert outer["tree_status"] == SUCCEEDED
        assert "sweep_trials" not in outer

    def test_running_and_failed_trials_still_lead(self):
        running = _sweep(20, [_trial(i) for i in range(15)] + [_trial(15, RUNNING)])
        assert running["tree_status"] == RUNNING
        failed = _sweep(20, [_trial(i) for i in range(15)] + [_trial(15, FAILED)])
        assert failed["tree_status"] == FAILED

    def test_a_retried_trial_counts_once(self):
        trials = [_trial(i) for i in range(4)] + [_trial(3, attempt=1)]
        outer = _sweep(5, trials)
        assert outer["sweep_trials"] == 4
        assert outer["tree_status"] == CREATED

    def test_an_incomplete_sweep_makes_its_ancestors_created(self):
        top = {"verstr": "1.0.0-dev.top", "status": CREATED}
        outer = {"verstr": SWEEP, "status": CREATED, "parent": top["verstr"], "sweep_planned": 3}
        rows = annotate_tree([top, outer, _trial(0), _trial(1)])
        assert {r["verstr"]: r["tree_status"] for r in rows}[top["verstr"]] == CREATED

    def test_the_cyclic_path_gives_the_same_answer(self):
        # A cycle elsewhere in the forest switches annotate_tree to its
        # per-subtree walk; the sweep must roll up the same there.
        loop = [{"verstr": "a", "parent": "b", "status": SUCCEEDED},
                {"verstr": "b", "parent": "a", "status": SUCCEEDED}]
        outer = {"verstr": SWEEP, "status": CREATED, "sweep_planned": 20}
        trials = [_trial(i) for i in range(16)]
        rows = {r["verstr"]: r for r in annotate_tree([outer] + trials + loop)}
        assert rows[SWEEP]["tree_status"] == CREATED
        full = {r["verstr"]: r for r in annotate_tree(
            [outer] + [_trial(i) for i in range(20)] + loop)}
        assert full[SWEEP]["tree_status"] == SUCCEEDED

    def test_annotate_rows_reads_the_planned_size_off_the_row(self):
        outer = experiment_row(1, {"verstr": SWEEP, "sweep": _grid(3)}, [])
        trials = [dict(_trial(i)) for i in range(2)]
        for t in trials:
            del t["status"]
        states = {t["verstr"]: {"state": "finished", "exit_code": 0} for t in trials}
        rows = {r["verstr"]: r for r in annotate_rows([outer] + trials, states)}
        assert rows[SWEEP]["tree_status"] == CREATED
        assert rows[SWEEP]["sweep_planned"] == 3
        assert rows[SWEEP]["sweep_trials"] == 2


class TestOneRun:
    """``subtree_status``/``run_status`` (run page, ``vmn-exp show``) read the
    planned size and trial slots from the index rows *row_of* gives."""

    def _rows(self, planned, n):
        outer = {"verstr": SWEEP, "sweep_planned": planned}
        return {r["verstr"]: r for r in [outer] + [_trial(i) for i in range(n)]}

    def _status(self, planned, n):
        rows = self._rows(planned, n)
        parent_of = {v: r.get("parent") for v, r in rows.items()}
        finished = {"state": "finished", "exit_code": 0}
        return run_status(SWEEP, parent_of, lambda v: None if v == SWEEP else finished,
                          row_of=rows.get)

    def test_16_of_20_is_created_and_says_so(self):
        status = self._status(20, 16)
        assert status["tree_status"] == CREATED
        assert (status["sweep_planned"], status["sweep_trials"]) == (20, 16)

    def test_20_of_20_succeeded(self):
        assert self._status(20, 20)["tree_status"] == SUCCEEDED

    def test_without_rows_nothing_changes(self):
        rows = self._rows(20, 16)
        parent_of = {v: r.get("parent") for v, r in rows.items()}
        finished = {"state": "finished", "exit_code": 0}
        _, tree = subtree_status(SWEEP, parent_of, lambda v: None if v == SWEEP else finished)
        assert tree["tree_status"] == SUCCEEDED
        assert "sweep_planned" not in tree
