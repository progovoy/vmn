"""Plan 32 F1: an aggregate over rows whose run overrides the schema's summary
policy says so — ``mixed: true`` and ``policies`` ({override: runs}; the
other runs follow the schema) on group, pivot and job-rollup aggregates — and
compare names each value's policy."""
from leaderboard_fleet import T0
from leaderboard_group_rows import run, snapshot, v
from test_ui_diff_summary import _log_define_metric, _log_metrics, _save_exp
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.ui import leaderboard_cache as lb
from vmn_exp.ui.baseline_compare import rollup_deltas
from vmn_exp.ui.job_rollup_payload import job_payload, job_summary
from vmn_exp.ui.job_tally import RollupSpec, Tally
from vmn_exp.ui.leaderboard_group_summary import Summary
from vmn_exp.ui.pivot import pivot_spec
from vmn_exp.ui.pivot_cache import PivotCache
from vmn_exp.ui.readers import diffs as diff_reader

SCHEMA = {"loss": {"goal": "min"}}


def _row(n, loss, policy=None):
    row = {"verstr": f"v{n:03d}", "status": "succeeded", "metrics": {"loss": loss}}
    if policy:
        row["metric_policy"] = {"loss": policy}
    return row


MIXED = [_row(0, 0.2, "last"), _row(1, 0.5), _row(2, 0.4, "last")]
PLAIN = [_row(0, 0.2), _row(1, 0.5)]


def test_a_group_with_overrides_is_marked():
    loss = Summary.of(MIXED).aggregates(SCHEMA)["loss"]
    assert loss["mixed"] is True and loss["policies"] == {"last": 2}


def test_a_group_following_the_schema_is_not_marked():
    assert "mixed" not in Summary.of(PLAIN).aggregates(SCHEMA)["loss"]


def test_a_group_follows_rows_joining_and_leaving():
    summary = Summary.of(PLAIN)
    assert summary.with_rows([_row(3, 0.9, "max")]).aggregates(SCHEMA)["loss"]["policies"] == {"max": 1}
    assert "mixed" not in summary.aggregates(SCHEMA)["loss"]  # with_rows copies
    summary.add([_row(3, 0.9, "max")]).remove([_row(3, 0.9, "max")])
    assert "mixed" not in summary.aggregates(SCHEMA)["loss"]
    assert summary.policies == {}


def _define_min():
    return [{"timestamp": "t", "type": "define_metric", "name": "loss", "summary": "min"},
            {"timestamp": "t", "type": "metrics", "values": {"loss": 0.9}}]


def test_a_pivot_cell_with_overrides_is_marked():
    snap = snapshot([
        run(1, tags={"kind": "launch"}),
        run(2, parent=1, tags={"date": "d1", "group": "g1"}, metrics={"loss": 0.5},
            log=_define_min()),
        run(3, parent=1, tags={"date": "d1", "group": "g1"}, metrics={"loss": 0.3}),
        run(4, parent=1, tags={"date": "d1", "group": "g2"}, metrics={"loss": 0.3}),
    ])
    spec = pivot_spec("tags.date", "tags.group", cell="agg", metric="loss", scope=v(1))
    body = PivotCache(lb.LeaderboardCache()).pivot(snap, {}, spec)
    mixed, plain = body["cells"][0]
    assert mixed["mixed"] is True and mixed["policies"] == {"min": 1}
    assert "mixed" not in plain


def _job_loss(rows):
    spec = RollupSpec(SCHEMA)
    tally = Tally.of(rows, spec)
    return tally, job_payload({"verstr": "job", "params": {}}, [tally], spec, T0)


def test_a_job_rollup_with_overrides_is_marked():
    _, payload = _job_loss(MIXED)
    loss = payload["metrics"]["loss"]
    assert loss["mixed"] is True and loss["policies"] == {"last": 2}
    tally, _ = _job_loss(PLAIN)
    tally.add(_row(3, 0.3, "max"), RollupSpec(SCHEMA))  # not an extreme: removal stays exact
    tally.add(_row(3, 0.3, "max"), RollupSpec(SCHEMA), by=-1)
    assert "mixed" not in job_payload({"verstr": "job", "params": {}}, [tally],
                                      RollupSpec(SCHEMA), T0)["metrics"]["loss"]


def test_compare_names_each_sides_policy(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path), area="runs")
    v1, v2 = "1.0.0-dev.aaa.bbb", "1.0.0-dev.ccc.ddd"
    _save_exp(storage, "myapp", v1)
    _log_define_metric(storage, "myapp", v1, "loss", "min")
    _save_exp(storage, "myapp", v2, ts="2025-01-02T00:00:00Z")
    for verstr in (v1, v2):
        for loss in (1.0, 0.2, 0.9):
            _log_metrics(storage, "myapp", verstr, {"loss": loss})
    result, err = diff_reader.experiment_diff_from_storage(storage, "myapp", v1, v2)
    assert err is None
    loss = result["metrics_delta"]["loss"]
    assert (loss["from"], loss["to"]) == (0.2, 0.9)
    assert (loss["from_policy"], loss["to_policy"]) == ("min", None)


def test_compare_names_the_schemas_policy_too(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path), area="runs")
    v1, v2 = "1.0.0-dev.aaa.bbb", "1.0.0-dev.ccc.ddd"
    for verstr, losses in ((v1, (1.0, 0.2, 0.9)), (v2, (1.0, 0.3))):
        _save_exp(storage, "myapp", verstr)
        for loss in losses:
            _log_metrics(storage, "myapp", verstr, {"loss": loss})
    result, _ = diff_reader.experiment_diff_from_storage(storage, "myapp", v1, v2, schema=SCHEMA)
    loss = result["metrics_delta"]["loss"]
    assert (loss["from_policy"], loss["to_policy"]) == ("min", "min")


def test_a_jobs_view_summary_with_overrides_is_marked():
    spec = RollupSpec(SCHEMA)
    job = {"verstr": "job", "params": {}}
    summary = job_summary(job, [Tally.of(MIXED, spec)], spec, T0)
    assert summary["mixed"] is True and summary["policies"] == {"last": 2}
    assert "mixed" not in job_summary(job, [Tally.of(PLAIN, spec)], spec, T0)


def _rollup(policies=None):
    loss = {"best": 0.2, "p50": 0.4}
    if policies:
        loss.update(mixed=True, policies=policies)
    return {"metrics": {"loss": loss}, "failed_pct": 0, "duration": {"p90": 1}}


def test_a_baseline_delta_names_each_sides_overrides():
    loss = rollup_deltas(_rollup({"last": 2}), _rollup(), {"loss": "min"})["metrics"]["loss"]
    assert loss["policies"] == {"value": {"last": 2}, "baseline": None}
    assert "policies" not in rollup_deltas(_rollup(), _rollup(), {"loss": "min"})["metrics"]["loss"]
