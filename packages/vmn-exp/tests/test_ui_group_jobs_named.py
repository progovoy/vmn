"""Plan 34 follow-ups: a grouped Outer runs page (``top=jobs`` with ``group``)
names its chosen aggregate in ``job_agg`` even when no group has a unit with
a value (missing is missing, plan 32 §0: the header reads ``—``, never
blank), and a group counts its outer runs' ``lost`` runs apart from the
summed ``run_counts`` (plan 34 §3)."""
from leaderboard_group_rows import run, snapshot
from vmn_exp.ui.job_aggregate import JobAgg
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

SCHEMA = {"best_value": {"goal": "max", "primary": True}, "date.best_value": {"goal": "max"},
          "free": {}}
DATES = JobAgg(agg="median", by="field:params.trade_date", value="own", metric="date.best_value")
CHOICE = ("agg", "by", "source", "metric", "goal", "percentile")


def _page(specs, agg=DATES, **params):
    return LeaderboardCache().groups(snapshot(specs), SCHEMA, "tags.launch_id", top="jobs",
                                     job_agg=agg, **params)


def _unvalued(n, launch="L1"):
    """Outer run *n* whose one child carries no ``date.best_value``."""
    return [run(n, tags={"launch_id": launch}), run(n + 1, parent=n, params={"trade_date": "d1"})]


def test_a_page_with_no_valued_unit_names_its_aggregate():
    page = _page(_unvalued(100) + _unvalued(200, "L2"), rows_per_group=0)
    assert all(g["job_aggregates"] == {} for g in page["groups"])
    assert {k: page["job_agg"][k] for k in CHOICE} == {
        "agg": "median", "by": "field:params.trade_date", "source": "own",
        "metric": "date.best_value", "goal": "max", "percentile": None}


def test_a_tail_names_its_percentile_and_a_goal_less_metric_no_goal():
    tail = _page(_unvalued(100), agg=DATES._replace(agg="best10"))["job_agg"]
    assert (tail["agg"], tail["percentile"]) == ("best10", "p90")
    free = _page(_unvalued(100), agg=DATES._replace(metric="free"))["job_agg"]
    assert (free["metric"], free["goal"]) == ("free", None)


def test_a_page_without_top_names_none():
    page = LeaderboardCache().groups(snapshot(_unvalued(100)), SCHEMA, "tags.launch_id")
    assert "job_agg" not in page


def _lossy(n, launch="L1"):
    """Ended outer run *n*: one child succeeded, one lost (stuck under it)."""
    return [run(n, tags={"launch_id": launch}), run(n + 1, parent=n),
            run(n + 2, parent=n, state="stuck")]


def test_a_group_counts_its_outer_runs_lost_runs():
    (group,) = _page(_lossy(100) + _lossy(200))["groups"]
    assert group["lost"] == 2
    assert group["run_counts"]["stuck"] == 0
    assert group["failed"] == 2


def test_a_group_with_no_lost_run_counts_zero():
    (group,) = _page(_unvalued(100))["groups"]
    assert group["lost"] == 0
