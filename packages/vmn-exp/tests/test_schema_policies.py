"""Summary policies resolved once per metric name per schema, not per row.

:class:`~vmn_exp.core.index_views.SchemaRows` summarizes every row of the
index under a schema; metric names repeat across runs, so a name's schema
policy is resolved once and each further metric costs a dict lookup — with
:func:`~vmn_exp.core.step_metric.lookup`'s precedence unchanged.
"""
import time

import pytest

from vmn_exp.core import metric_summary, step_metric
from vmn_exp.core.index_views import SchemaRows


def _seen(last, low, high, first=None, mean=None):
    return {"last": last, "min": low, "max": high,
            "first": last if first is None else first, "mean": mean}


LOSS = _seen(0.5, 0.1, 0.9, first=0.9, mean=0.4)


def _summarized(metrics, schema, defs=None):
    row = {"verstr": "r1", "metrics": {name: s["last"] for name, s in metrics.items()}}
    parts = {"r1": (metrics, defs)}
    return SchemaRows().rows([row], parts, schema)[0]["metrics"]


def test_a_run_definition_beats_the_schema():
    got = _summarized({"loss": LOSS}, {"loss": {"goal": "max"}}, {"loss": {"goal": "min"}})
    assert got["loss"] == 0.1


def test_a_run_glob_beats_an_exact_schema_name():
    got = _summarized({"loss": LOSS}, {"loss": {"goal": "max"}}, {"lo*": {"summary": "first"}})
    assert got["loss"] == 0.9


def test_the_schema_applies_where_the_run_declares_nothing_for_the_metric():
    got = _summarized({"loss": LOSS}, {"loss": {"goal": "min"}}, {"acc": {"goal": "max"}})
    assert got["loss"] == 0.1


def test_an_exact_name_beats_a_glob():
    schema = {"loss": {"summary": "mean"}, "lo*": {"goal": "max"}}
    assert _summarized({"loss": LOSS}, schema)["loss"] == 0.4


def test_the_latest_declared_glob_wins():
    schema = {"l*": {"goal": "min"}, "lo*": {"goal": "max"}, "x*": {"goal": "min"}}
    assert _summarized({"loss": LOSS}, schema)["loss"] == 0.9


def test_a_glob_without_a_policy_is_skipped():
    schema = {"l*": {"goal": "min"}, "lo*": {"step_metric": "epoch"}}
    assert _summarized({"loss": LOSS}, schema)["loss"] == 0.1


def test_no_policy_keeps_the_last_value():
    assert _summarized({"loss": LOSS}, {"acc": {"goal": "max"}})["loss"] == 0.5


def _fleet(count, names):
    rows, parts = [], {}
    for i in range(count):
        verstr = f"r{i}"
        summary = {n: _seen(float(i), 0.0, float(i + 1)) for n in names}
        rows.append({"verstr": verstr, "metrics": {n: float(i) for n in names}})
        parts[verstr] = (summary, None)
    return rows, parts


def _counted(monkeypatch, module, name):
    calls = []
    real = getattr(module, name)

    def counting(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, counting)
    return calls


@pytest.mark.parametrize("count", [10, 200])
def test_each_name_is_resolved_once_whatever_the_row_count(monkeypatch, count):
    names = [f"cv{k}.loss" for k in range(5)] + ["health.cpu", "res.mem"]
    schema = {"health.*": {"goal": "max"}, "res.*": {"goal": "min"}, "cpu*": {"goal": "max"}}
    rows, parts = _fleet(count, names)
    lookups = _counted(monkeypatch, metric_summary, "lookup")
    matches = _counted(monkeypatch, step_metric, "fnmatchcase")
    out = SchemaRows().rows(rows, parts, schema)
    assert len(lookups) == len(names)
    assert len(matches) <= len(names) * len(schema)
    assert out[-1]["metrics"]["health.cpu"] == float(count)
    assert out[-1]["metrics"]["res.mem"] == 0.0


@pytest.mark.serial
def test_50k_rows_of_100_metrics_summarize_in_seconds():
    names = [f"cv{k}.m{j}" for k in range(5) for j in range(16)]
    names += [f"health.h{j}" for j in range(10)] + [f"res.r{j}" for j in range(10)]
    schema = {"health.*": {"goal": "max"}, "res.*": {"goal": "min"},
              "cpu*": {"goal": "max"}, "cv*.m1*": {"summary": "mean"}}
    seen = _seen(1.0, 0.0, 2.0, mean=1.5)
    summary = {n: seen for n in names}
    metrics = {n: 1.0 for n in names}
    rows = [{"verstr": f"r{i}", "metrics": metrics} for i in range(50_000)]
    parts = {row["verstr"]: (summary, None) for row in rows}
    start = time.perf_counter()
    out = SchemaRows().rows(rows, parts, schema)
    took = time.perf_counter() - start
    print(f"\n50k rows x {len(names)} metrics: {took:.2f} s")
    assert out[0]["metrics"]["health.h0"] == 2.0
    assert took < 3.0
