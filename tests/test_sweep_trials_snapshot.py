"""A sweep's trials read off an index snapshot touch the sweep's subtree only:
the rest of the app's runs are neither copied nor status-annotated, and the
parent -> children map is built once per snapshot."""
from vmn_exp.core import tree
from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.sweep import summary
from vmn_exp.core.sweep.spec import parse_spec

SPEC = parse_spec({
    "method": "random",
    "metric": {"name": "loss", "goal": "min"},
    "parameters": {"lr": {"distribution": "uniform", "min": 0.0, "max": 1.0}},
})
FINISHED = {"state": "finished", "exit_code": 0}


def _run(verstr, parent=None, loss=None, trial=None):
    tags = {} if trial is None else {"sweep_trial": str(trial), "sweep_attempt": "0"}
    return {"verstr": verstr, "parent": parent, "tags": tags, "params": {},
            "metrics": {} if loss is None else {"loss": loss}}


def _snapshot(unrelated=200):
    rows = [_run("sweep"), _run("t0", "sweep", trial=0), _run("t0.sdk", "t0", 0.4),
            _run("t1", "sweep", 0.7, trial=1)]
    rows += [_run(f"other{i}", "sweep-not" if i % 2 else None) for i in range(unrelated)]
    states = {r["verstr"]: FINISHED for r in rows}
    return IndexSnapshot.build("app", 1, rows, states)


def test_trials_are_attributed_from_the_snapshot():
    trials = summary.snapshot_trials(SPEC, "sweep", _snapshot())
    by_verstr = {t["verstr"]: t for t in trials}
    assert sorted(by_verstr) == ["t0", "t1"]
    assert by_verstr["t0"]["metric_source"] == "t0.sdk"
    assert by_verstr["t0"]["metrics"]["loss"] == 0.4
    assert by_verstr["t1"]["status"] == "succeeded"


def test_only_the_sweeps_subtree_is_annotated(monkeypatch):
    sizes = []
    real = summary.annotate_rows

    def counting(rows, *args, **kwargs):
        rows = list(rows)
        sizes.append(len(rows))
        return real(rows, *args, **kwargs)

    monkeypatch.setattr(summary, "annotate_rows", counting)
    summary.snapshot_trials(SPEC, "sweep", _snapshot())
    assert sizes and max(sizes) <= 4


def test_the_children_map_is_built_once_per_snapshot(monkeypatch):
    calls = []
    real = tree.children_by_parent

    def counting(nodes):
        nodes = list(nodes)
        calls.append(len(nodes))
        return real(nodes)

    monkeypatch.setattr(summary, "children_by_parent", counting)
    snap = _snapshot()
    summary.snapshot_trials(SPEC, "sweep", snap)
    summary.snapshot_trials(SPEC, "sweep", snap)
    assert sum(1 for n in calls if n > 4) == 1
