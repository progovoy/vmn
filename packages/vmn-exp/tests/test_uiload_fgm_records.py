"""Plan 28 B0: fgm's planned tree (:mod:`uiload.fgm_tree`) as the records the
SDK would write, folded into an index snapshot: statuses, tags, declared
progress, released runs, settling and the ``tags.kind`` split read as fgm's
store would make them."""
import collections

import pytest
from uiload import fgm_records, fgm_tree
from vmn_exp.ui.job_views import JobViews
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_group_fields import key_text

NOW = 1_800_000_000.0


@pytest.fixture
def tiny(monkeypatch):
    fgm_records.freeze_clock(monkeypatch, NOW)
    snap, specs = fgm_records.snapshot(fgm_tree.get_profile("fgm-tiny"), NOW)
    return snap, {s["verstr"]: s for s in specs}


def test_every_row_derives_its_planned_status_and_keeps_its_tags(tiny):
    snap, specs = tiny
    assert len(snap.rows) == len(specs)
    rows = LeaderboardCache().rows(snap)
    for row in rows:
        spec = specs[row["verstr"]]
        assert row["status"] == fgm_tree.derived_status(spec["fate"]), spec
        assert row["tags"] == spec["tags"]
        assert row["parent"] == spec["parent"]
        assert row["name"] == spec["name"]
        for key, value in spec["metrics"].items():
            assert row["metrics"][key] == value


def test_released_rows_carry_why_and_when(tiny):
    snap, specs = tiny
    released = [r for r in LeaderboardCache().rows(snap)
                if specs[r["verstr"]]["fate"] == "released"]
    assert released
    for row in released:
        assert row["end_reason"] == "released" and row["signal"] == "SIGTERM"
        assert row["released_at"]


def test_the_declared_schema_ranks_value_and_hides_health(tiny):
    snap, _ = tiny
    schema = snap.declared_schema()
    assert schema["value"]["goal"] == "max"
    assert schema["best_value"]["goal"] == "max"
    assert schema["health.*"]["hidden"] is True


def test_a_live_launch_summary_reads_its_declared_progress_split_by_kind(tiny):
    snap, specs = tiny
    live = specs[fgm_tree.launches(specs.values())[0]]
    views = JobViews(LeaderboardCache())
    summary = views.summary(snap, snap.declared_schema(), live["verstr"], split="tags.kind")
    declared = summary["declared_progress"]
    assert (declared["done"], declared["total"], declared["unit"]) == (
        live["metrics"]["progress"], live["metrics"]["progress_total"], "dates")
    by = {entry["key"]: entry for entry in summary["by"]}
    under = collections.Counter(s["tags"]["kind"] for s in specs.values()
                                if s["verstr"] != live["verstr"] and _root(specs, s) == live["verstr"])
    assert {key_text(k) for k in by} == set(under)
    assert sum(e["total"] for e in by.values()) == summary["total"]


def test_an_ended_launch_settles_its_leftovers(tiny):
    snap, specs = tiny
    rows = LeaderboardCache().rows(snap)
    settled = collections.Counter(r.get("settled") for r in rows)
    fates = collections.Counter(specs[r["verstr"]]["fate"] for r in rows if r.get("settled"))
    assert settled["lost"] == fates["released"] + fates["stuck"]
    assert settled["never_started"] == fates["created"]


def _root(specs, spec):
    while spec["parent"]:
        spec = specs[spec["parent"]]
    return spec["verstr"]
