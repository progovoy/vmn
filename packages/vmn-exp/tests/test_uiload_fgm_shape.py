"""Plan 28 B0: the uiload ``fgm`` profiles plan fgm's run tree — launch → date
→ study → trial / refit / assembler → pod (5 levels), ~20k runs a launch,
~10^4 live runs at the full 588k-run scale, Phase 0 tags on every run,
``health``/``state`` on some trials, declared progress on the launch and the
studies, released runs and a cost report per finished launch. Pure planning,
no store."""
import collections

import pytest
from uiload import fgm_tree

NOW = 1_800_000_000.0
LEVELS = {"launch": 0, "date": 1, "cost_report": 1, "study": 2, "trial": 3, "refit": 3,
          "refit_single": 3, "refit_expansion": 3, "assembler": 3}


@pytest.fixture(scope="module")
def full():
    return fgm_tree.get_profile("fgm")


@pytest.fixture(scope="module")
def finished(full):
    return fgm_tree.launch_runs(full, 0, NOW)


@pytest.fixture(scope="module")
def live(full):
    return fgm_tree.launch_runs(full, full.launches - 1, NOW)


def _kind(spec):
    return spec["tags"]["kind"]


def _by_kind(specs):
    return collections.Counter(_kind(s).split("/")[0] for s in specs)


def test_the_full_profile_is_588k_runs_with_about_ten_thousand_live(full, finished):
    live_launches = [fgm_tree.launch_runs(full, n, NOW)
                     for n in range(full.launches - full.live_launches, full.launches)]
    total = (full.launches - full.live_launches) * len(finished) + sum(map(len, live_launches))
    running = sum(s["fate"] == "running" for specs in live_launches for s in specs)
    assert 19_000 <= len(finished) <= 21_000
    assert 570_000 <= total <= 610_000, total
    assert 8_000 <= running <= 13_000, running
    assert not any(s["fate"] == "running" for s in finished)


def test_a_launch_is_five_levels_deep_parents_first(finished):
    level_of = {}
    for spec in finished:
        parent = spec["parent"]
        assert (parent is None) == (_kind(spec) == "launch")
        assert parent is None or parent in level_of  # parents come first
        level = 0 if parent is None else level_of[parent] + 1
        level_of[spec["verstr"]] = level
        assert spec["level"] == level
        assert level == (4 if _kind(spec).startswith("pod/") else LEVELS[_kind(spec)])
    assert max(level_of.values()) == 4
    assert len(level_of) == len(finished)  # verstrs are unique


def test_a_finished_launch_has_the_planned_counts_per_level(full, finished):
    kinds = _by_kind(finished)
    studies = full.dates * full.targets * full.groups
    assert kinds["launch"] == kinds["cost_report"] == 1
    assert kinds["date"] == full.dates
    assert kinds["study"] == studies
    assert kinds["trial"] == studies * full.trials
    assert kinds["assembler"] == studies
    assert kinds["refit"] + kinds["refit_single"] + kinds["refit_expansion"] == 3 * studies
    started = sum(1 for s in finished if s["level"] == 3 and s["fate"] != "created")
    assert kinds["pod"] == started  # one pod per child that ever ran


def test_every_run_carries_the_phase_0_tags_of_its_study(finished):
    by_verstr = {s["verstr"]: s for s in finished}
    for spec in finished:
        assert _kind(spec)
        if spec["level"] >= 2:
            study = spec
            while _kind(study) != "study":
                study = by_verstr[study["parent"]]
            for key in ("trade_date", "group", "target"):
                assert spec["tags"][key] == study["params"][key]
    dates = {s["tags"]["trade_date"] for s in finished if _kind(s) == "date"}
    assert len(dates) == 60


def test_health_and_state_tags_sit_on_some_trials_only(finished):
    health = collections.Counter(s["tags"]["health"] for s in finished if "health" in s["tags"])
    assert {_kind(s) for s in finished if "health" in s["tags"]} == {"trial", "refit_single"}
    assert set(health) == {"ok", "warn", "unstable"}
    assert health["ok"] > health["warn"] > 0 and health["unstable"] > 0
    states = [s for s in finished if "state" in s["tags"]]
    assert {_kind(s) for s in states} <= {"trial", "assembler", "refit_single"}
    assert {s["tags"]["state"] for s in states} == {"nonfinite", "collapsed", "degenerate"}
    assert 0 < len(states) < 0.05 * len(finished)


def test_one_group_collapses_more_as_the_trade_date_grows(full, finished):
    """Incident 1: BCA's unstable share grows with ``trade_date``."""
    dates = sorted({s["tags"]["trade_date"] for s in finished if _kind(s) == "date"})
    third = len(dates) // 3

    def unstable_share(group, window):
        rows = [s for s in finished if s["tags"].get("group") == group and "health" in s["tags"]
                and s["tags"]["trade_date"] in window]
        return sum(s["tags"]["health"] == "unstable" for s in rows) / len(rows)

    early, late = set(dates[:third]), set(dates[-third:])
    assert unstable_share("BCA", late) > 2 * unstable_share("BCA", early)
    assert unstable_share("BCA", late) > 2 * unstable_share("BCAFX", late)


def test_the_launch_and_its_studies_declare_progress(full, finished, live):
    launch = finished[0]
    assert launch["metrics"]["progress"] == launch["metrics"]["progress_total"] == full.dates
    assert launch["metrics"]["wf.dates_total"] == full.dates
    head = live[0]
    done = sum(1 for s in live if _kind(s) == "date" and s["fate"] == "succeeded")
    assert head["metrics"]["progress"] == head["metrics"]["wf.dates_done"] == done
    assert head["metrics"]["progress_total"] == full.dates > done > 0
    studies = [s for s in live if _kind(s) == "study"]
    assert all(s["metrics"]["progress_total"] == full.trials for s in studies)
    assert any(s["metrics"]["progress"] < full.trials for s in studies)


def test_live_launches_hold_released_waiting_and_running_runs(live):
    fates = collections.Counter(s["fate"] for s in live)
    assert fates["running"] and fates["created"] and fates["released"]
    for spec in (s for s in live if s["fate"] == "released"):
        assert spec["signal"] == "SIGTERM"
        assert NOW - 2 * 3600 <= spec["released_at"] <= NOW


def test_finished_launches_hold_retries_that_ended_done_and_a_few_lost_runs(finished):
    fates = collections.Counter(s["fate"] for s in finished)
    assert fates["succeeded"] > 0.9 * len(finished)
    assert fates["failed"] and fates["released"] and fates["created"] and fates["stuck"]
    assert any(s["resume_count"] and s["fate"] == "succeeded" for s in finished)
    failed = [s for s in finished if s["fate"] == "failed" and s["level"] == 3]
    assert all(s["error"] for s in failed)


def test_a_finished_launch_has_its_cost_report(finished):
    (report,) = [s for s in finished if _kind(s) == "cost_report"]
    launch = finished[0]
    assert report["parent"] == launch["verstr"]
    assert report["name"] == f"cost_report/{launch['tags']['launch_id']}"
    assert report["metrics"]["total_cost_usd"] > 0
    assert any(k.startswith("stage_") and k.endswith("_cost_usd") for k in report["metrics"])
    assert report["tags"]["coverage"] in ("complete", "partial", "unknown")


def test_the_plan_is_deterministic_and_launches_never_share_a_verstr(full, finished):
    assert fgm_tree.launch_runs(full, 0, NOW) == finished
    other = {s["verstr"] for s in fgm_tree.launch_runs(full, 1, NOW)}
    assert not other & {s["verstr"] for s in finished}


def test_smaller_profiles_keep_the_shape(full):
    tiny = fgm_tree.get_profile("fgm-tiny")
    specs = list(fgm_tree.plan_runs(tiny, NOW))
    assert 100 <= len(specs) <= 1000
    assert {s["level"] for s in specs} == {0, 1, 2, 3, 4}
    small = fgm_tree.get_profile("fgm-small")
    assert (small.dates, small.trials) == (full.dates, full.trials)
    assert small.launches < full.launches and small.live_launches >= 1
