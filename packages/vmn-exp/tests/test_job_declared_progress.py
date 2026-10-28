"""Plan 28 P2: an outer run's declared progress (``progress`` /
``progress_total`` on its own row, other names by app settings) drives its
rollup's progress, rate and ETA; the run counts stay beside it."""
import datetime

from leaderboard_fleet import T0, iso
from vmn_exp.core.progress import DEFAULT_NAMES, declared_progress, progress_names
from vmn_exp.ui.job_rollup_payload import job_payload, job_summary
from vmn_exp.ui.job_tally import RollupSpec, Tally

SPEC = RollupSpec({"loss": {"goal": "min"}})
HOUR_AGO = iso(T0 - datetime.timedelta(hours=1))


def _rows(n, status="succeeded"):
    return [{"verstr": f"v{i:03d}", "parent": "job", "status": status, "metrics": {},
             "exit_code": 0 if status == "succeeded" else None} for i in range(n)]


def _job(metrics=None, params=None, **fields):
    return {"verstr": "job", "status": "running", "started_at": HOUR_AGO,
            "metrics": metrics or {}, "params": params or {}, **fields}


def _payload(job, rows=None, spec=SPEC):
    return job_payload(job, [Tally.of(_rows(30) if rows is None else rows, spec)], spec, T0)


def test_the_default_names_are_progress_and_progress_total():
    assert DEFAULT_NAMES == ("progress", "progress_total", None)
    assert progress_names(None) == DEFAULT_NAMES


def test_a_settings_mapping_names_other_metrics_and_a_unit():
    names = progress_names({"done": "wf.dates_done", "total": "wf.dates_total", "unit": "dates"})
    assert names == ("wf.dates_done", "wf.dates_total", "dates")
    assert progress_names({"done": "trials"}) == ("trials", "progress_total", None)


def test_declared_progress_needs_both_finite_and_a_positive_total():
    assert declared_progress(_job({"progress": 41, "progress_total": 60})) == (41, 60, None)
    assert declared_progress(_job({"progress": 41})) is None
    assert declared_progress(_job({"progress": 41, "progress_total": 0})) is None
    assert declared_progress(_job({"progress": float("nan"), "progress_total": 60})) is None
    assert declared_progress(_job({"progress": True, "progress_total": 60})) is None
    assert declared_progress({"verstr": "job"}) is None


def test_the_unit_comes_from_the_mapping_else_the_runs_progress_unit_param():
    job = _job({"progress": 1, "progress_total": 2}, {"progress_unit": "dates"})
    assert declared_progress(job) == (1, 2, "dates")
    names = progress_names({"unit": "days"})
    assert declared_progress(job, names) == (1, 2, "days")


def test_a_declared_progress_drives_progress_and_eta_from_the_outer_runs_start():
    payload = _payload(_job({"progress": 20, "progress_total": 60}))
    assert payload["declared_progress"] == {"done": 20, "total": 60, "unit": None,
                                            "rate_per_min": round(20 / 60, 4)}
    assert payload["progress"] == round(20 / 60, 4)
    # 40 left at 20 an hour.
    assert payload["eta_sec"] == 2 * 3600


def test_the_run_counts_stay_the_runs():
    payload = _payload(_job({"progress": 20, "progress_total": 60}))
    assert (payload["done"], payload["total"], payload["expected"]) == (30, 30, 30)
    assert payload["counts"]["succeeded"] == 30


def test_without_a_declared_progress_the_rollup_reads_as_before():
    payload = _payload(_job({"progress": 20}))
    assert payload["declared_progress"] is None
    assert payload["progress"] == 1.0


def test_nothing_done_yet_has_no_eta_and_all_done_or_ended_has_none_left():
    assert _payload(_job({"progress": 0, "progress_total": 60}))["eta_sec"] is None
    assert _payload(_job({"progress": 60, "progress_total": 60}))["eta_sec"] == 0
    ended = _job({"progress": 41, "progress_total": 60}, status="succeeded", exit_code=0)
    assert _payload(ended)["eta_sec"] == 0
    assert _payload(_job({"progress": 70, "progress_total": 60}))["progress"] == 1.0


def test_the_rate_falls_back_to_the_subtrees_first_start():
    rows = [dict(r, started_at=HOUR_AGO) for r in _rows(3)]
    job = _job({"progress": 30, "progress_total": 60}, started_at=None)
    assert _payload(job, rows)["declared_progress"]["rate_per_min"] == 0.5


def test_mapped_names_are_read_through_the_spec():
    spec = RollupSpec({}, progress=progress_names({"done": "wf.dates_done",
                                                    "total": "wf.dates_total", "unit": "dates"}))
    job = _job({"wf.dates_done": 41, "wf.dates_total": 60, "progress": 1, "progress_total": 2})
    declared = _payload(job, spec=spec)["declared_progress"]
    assert (declared["done"], declared["total"], declared["unit"]) == (41, 60, "dates")


def test_the_compact_summary_carries_it_so_the_jobs_view_sorts_on_it():
    summary = job_summary(_job({"progress": 15, "progress_total": 60}),
                          [Tally.of(_rows(5), SPEC)], SPEC, T0)
    assert summary["declared_progress"]["done"] == 15
    assert summary["progress"] == 0.25


def test_the_jobs_view_and_the_page_read_it_off_the_cache_and_follow_new_values(monkeypatch):
    from leaderboard_fleet import Fleet
    from vmn_exp.core import status as status_mod
    from vmn_exp.ui.job_views import JobViews
    from vmn_exp.ui.leaderboard_cache import LeaderboardCache

    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = Fleet(7)
    root = fleet.seed_jobs(1, 20, T0)[0]
    views = JobViews(LeaderboardCache())
    for done in (5, 41):
        fleet.edit(fleet.index(root), values={"progress": done, "progress_total": 60})
        snap = fleet.snapshot()
        summary = views.cache.job_rollups(snap, {})[root]
        assert summary["declared_progress"]["done"] == done
        assert summary["total"] == 20
        assert views.summary(snap, {}, root)["progress"] == round(done / 60, 4)
