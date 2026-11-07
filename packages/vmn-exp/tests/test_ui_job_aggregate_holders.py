"""Plan 31 §2 follow-ups: a ``by`` is normalized once (``kind: date`` is
``kind:date``, from the settings and the URL alike); ``rolled.verstr`` links
a unit only when it holds the shown value (``runs`` min/max too, never an
interpolated quantile); a nested job's ``rolled`` reads only its own."""
import pytest
from leaderboard_group_rows import run, snapshot, v
from test_ui_job_aggregate import SCHEMA, _fgm, _rolled, _training
from vmn_exp.ui.job_aggregate import JobAgg, JobAggregates, job_agg_of
from vmn_exp.ui.leaderboard_cache import LeaderboardCache


@pytest.mark.parametrize("raw,want", [("kind: date", "kind:date"), ("kind:date  ", "kind:date"),
                                      ("field: params.trade_date ", "field:params.trade_date")])
def test_a_by_is_normalized_from_the_url_and_the_settings(raw, want):
    assert job_agg_of({}, by=raw).by == want
    assert job_agg_of({"job_aggregate": {"by": raw}}).by == want


@pytest.mark.parametrize("by", ["kind: date", "field: params.trade_date"])
def test_a_spaced_by_finds_the_units(by):
    agg = job_agg_of({}, agg="median", by=by, value="own", metric="date.best_value")
    got, _ = _rolled(_fgm(), agg)
    assert (got["n"], got["of"]) == (16, 16)


def test_a_spaced_url_by_behaves_as_the_plain_one(tmp_path):
    pytest.importorskip("fastapi")
    from test_ui_job_aggregate_route import _rolled as served_rolled
    from test_ui_job_aggregate_route import _served
    client, runs = _served(tmp_path)
    assert served_rolled(client, job_agg_by="kind: x")[runs[1]]["by"] == "kind:x"


@pytest.mark.parametrize("name", ["min", "max"])
def test_runs_min_and_max_link_the_run_holding_them(name):
    specs = _training()
    got, _ = _rolled(specs, JobAgg(agg=name, by="runs"))
    values = {v(s["n"]): s["metrics"].get("best_value") for s in specs}
    assert got["verstr"] is not None
    assert values[got["verstr"]] == got["value"]


def _two(*values):
    return [run(1)] + [run(2 + i, parent=1, metrics={"best_value": x})
                       for i, x in enumerate(values)]


@pytest.mark.parametrize("name", ["median", "best10", "worst10"])
def test_an_interpolated_value_links_no_unit(name):
    got, _ = _rolled(_two(0.1, 0.9), JobAgg(agg=name))
    assert 0.1 < got["value"] < 0.9
    assert got["verstr"] is None


def test_a_quantile_a_unit_holds_links_it():
    got, _ = _rolled(_two(0.1, 0.5, 0.9), JobAgg(agg="median"))
    assert (got["value"], got["verstr"]) == (0.5, v(3))


def test_a_nested_jobs_rolled_reads_only_its_own(monkeypatch):
    calls = {"all": 0, "payload": 0}
    all_of, payload_of = JobAggregates._all, JobAggregates._payload_of

    def counted(name, real):
        def wrapper(*args):
            calls[name] += 1
            return real(*args)
        return wrapper

    monkeypatch.setattr(JobAggregates, "_all", counted("all", all_of))
    monkeypatch.setattr(JobAggregates, "_payload_of", counted("payload", payload_of))
    specs = _training()
    date = next(s["n"] for s in specs if s["params"].get("trade_date"))
    got = LeaderboardCache().job_aggregates.one(snapshot(specs), SCHEMA, v(date), JobAgg())
    trials = [s["metrics"]["best_value"] for s in specs if s["meta"].get("parent") == v(date)]
    assert got["value"] == max(trials)
    assert calls == {"all": 0, "payload": 1}
