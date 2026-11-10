"""Plan 34 §1: a grouped Outer runs header (``top`` with ``group``, e.g.
``tags.launch_id``) pools the units of every outer run of the group (the
attempts of one training) under the rows' own ``job_agg``. A unit found in
several attempts counts once, from the latest attempt (its outer run's start,
else its creation); ``from_earlier`` counts the units taken from earlier
attempts. A duplicate inside one attempt stays a conflict. ``by=runs`` pools
every run of every attempt."""
import statistics

import pytest
from leaderboard_group_rows import run, snapshot, v
from vmn_exp.ui import job_aggregate
from vmn_exp.ui.job_aggregate import JobAgg
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

SCHEMA = {"best_value": {"goal": "max", "primary": True}, "date.best_value": {"goal": "max"}}
DATES = JobAgg(agg="median", by="field:params.trade_date", value="own", metric="date.best_value")


def _attempt(n, dates, values, launch="L1", state="ok"):
    """Outer run *n* of training *launch* → one date run per date (its own
    ``date.best_value``) → one trial (``best_value``)."""
    specs = [run(n, state=state, tags={"launch_id": launch})]
    for i, (date, value) in enumerate(zip(dates, values)):
        specs.append(run(n + 1 + 2 * i, parent=n, params={"trade_date": date},
                         metrics={"date.best_value": value}))
        specs.append(run(n + 2 + 2 * i, parent=n + 1 + 2 * i, metrics={"best_value": value / 2}))
    return specs


def _header(specs, agg=DATES, metric="date.best_value", cache=None):
    cache = cache or LeaderboardCache()
    (group,) = cache.groups(snapshot(specs), SCHEMA, "tags.launch_id", top="jobs",
                            job_agg=agg)["groups"]
    return group["job_aggregates"][metric]


# Attempt 100 ran d1..d5; attempt 200, created later, reran d4, d5 and ran d6..d8.
EARLY = _attempt(100, ["d1", "d2", "d3", "d4", "d5"], [0.1, 0.2, 0.3, 0.4, 0.5])
LATE = _attempt(200, ["d4", "d5", "d6", "d7", "d8"], [0.9, 0.8, 0.7, 0.6, 0.95])
POOLED = [0.1, 0.2, 0.3, 0.9, 0.8, 0.7, 0.6, 0.95]  # d4, d5 from the later attempt


def test_the_header_pools_the_attempts_units_latest_wins():
    got = _header(EARLY + LATE)
    assert got["value"] == pytest.approx(statistics.median(POOLED))
    assert (got["n"], got["of"], got["conflicts"], got["from_earlier"]) == (8, 8, 0, 3)
    assert (got["agg"], got["by"], got["source"], got["metric"]) == (
        "median", "field:params.trade_date", "own", "date.best_value")
    assert got["approx"] is False


def test_the_header_carries_every_aggregate_of_the_pooled_values():
    got = _header(EARLY + LATE)
    assert got["max"] == 0.95 and got["min"] == 0.1 and got["best"] == 0.95
    assert got["mean"] == pytest.approx(statistics.fmean(POOLED))
    assert got["goal"] == "max"


def test_the_order_of_the_attempts_in_the_index_does_not_matter():
    assert _header(LATE + EARLY)["value"] == pytest.approx(statistics.median(
        [0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 0.6, 0.95]))  # 100 is created later now


def test_a_start_beats_a_creation():
    # 100 is created first but started now; 200, created later, an hour ago.
    early = _attempt(100, ["d1", "d2", "d3", "d4", "d5"], [0.1, 0.2, 0.3, 0.4, 0.5],
                     state="running")
    late = _attempt(200, ["d4", "d5", "d6", "d7", "d8"], [0.9, 0.8, 0.7, 0.6, 0.95],
                    state="stuck")
    got = _header(early + late)
    assert got["from_earlier"] == 3  # d6..d8 from 200, now the earlier attempt
    assert got["value"] == pytest.approx(statistics.median(
        [0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 0.6, 0.95]))


def test_a_duplicate_inside_the_latest_attempt_stays_a_conflict():
    # d5 twice in 200: a conflict, never filled in from 100's d5.
    late = LATE + [run(300, parent=200, params={"trade_date": "d5"},
                       metrics={"date.best_value": 0.05})]
    got = _header(EARLY + late)
    assert (got["n"], got["of"], got["conflicts"], got["from_earlier"]) == (7, 8, 1, 3)
    assert got["value"] == pytest.approx(statistics.median([x for x in POOLED if x != 0.8]))


def test_by_children_pools_every_child_of_every_attempt():
    got = _header(EARLY + LATE, JobAgg(agg="max", value="own", metric="date.best_value"))
    assert (got["n"], got["of"], got["from_earlier"]) == (10, 10, 5)
    assert got["value"] == 0.95


def test_by_runs_pools_the_runs_of_every_attempt():
    got = _header(EARLY + LATE, JobAgg(agg="max", by="runs"), metric="best_value")
    assert (got["n"], got["of"], got["from_earlier"]) == (10, 20, 0)
    assert got["value"] == pytest.approx(0.95 / 2)
    median = _header(EARLY + LATE, JobAgg(agg="median", by="runs"), metric="best_value")
    assert median["approx"] is True


def test_groups_of_other_trainings_do_not_mix():
    other = _attempt(400, ["d1"], [0.99], launch="L2")
    cache = LeaderboardCache()
    groups = cache.groups(snapshot(EARLY + LATE + other), SCHEMA, "tags.launch_id",
                          top="jobs", job_agg=DATES)["groups"]
    by_key = {g["key"]: g["job_aggregates"]["date.best_value"] for g in groups}
    assert by_key["L2"]["n"] == 1 and by_key["L2"]["from_earlier"] == 0
    assert by_key["L1"]["n"] == 8


def test_a_group_sums_its_attempts_run_counts():
    cache = LeaderboardCache()
    (group,) = cache.groups(snapshot(EARLY + LATE), SCHEMA, "tags.launch_id", top="jobs",
                            job_agg=DATES)["groups"]
    summaries = cache.job_rollups(snapshot(EARLY + LATE), SCHEMA)
    want = {k: summaries[v(100)]["counts"][k] + summaries[v(200)]["counts"][k]
            for k in summaries[v(100)]["counts"]}
    assert group["run_counts"] == want


def test_the_pool_reads_the_memoized_unit_lists(monkeypatch):
    calls = []
    real = job_aggregate.carriers_below
    monkeypatch.setattr(job_aggregate, "carriers_below",
                        lambda *a: calls.append(1) or real(*a))
    cache, snap = LeaderboardCache(), snapshot(EARLY + LATE)
    cache.page(snap, SCHEMA, limit=10, top=True, job_agg=DATES)
    first = len(calls)
    assert first == 2  # one walk per outer run
    cache.groups(snap, SCHEMA, "tags.launch_id", top="jobs", job_agg=DATES)
    cache.groups(snap, SCHEMA, "tags.launch_id", top="jobs", job_agg=DATES)
    assert len(calls) == first
