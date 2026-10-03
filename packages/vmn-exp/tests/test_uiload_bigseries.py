"""uiload ``bigseries`` profile: columnar metric files seeded directly, then
the series SLOs (plan 12 §10 4b) measured against a real in-process server.
The full profile is never run here, only its tiny variant."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402
from uiload import probe_series, scenario, seed_series, slo  # noqa: E402
from uiload.inproc_server import serve_root  # noqa: E402
from vmn_exp.sdk.reader import list_runs  # noqa: E402
from vmn_exp.snapshot import open_storage  # noqa: E402
from vmn_exp.storage.areas import local_store_root  # noqa: E402

APP = "loadapp"


def test_bigseries_profile_is_sized_as_the_plan_says():
    p = scenario.get_series_profile("bigseries")
    assert (p.big_runs, p.big_steps, p.big_keys) == (50, 1_000_000, 50)
    assert (p.wide_runs, p.wide_steps, p.wide_keys) == (1, 10_000, 5000)
    assert p.overlay_runs == 1000
    assert p.series_points == 2000
    budget = slo.SERIES_BUDGETS["bigseries"]
    assert budget["series_p95_ms"] == 150
    assert budget["zoom_p95_ms"] == 150
    assert budget["first_paint_max_bytes"] == 1_000_000
    assert budget["overlay_max_ms"] == 2000


def test_tiny_profile_has_every_part_scaled_down():
    tiny = scenario.get_series_profile("bigseries-tiny")
    full = scenario.get_series_profile("bigseries")
    for field in ("big_runs", "big_steps", "big_keys", "wide_steps", "wide_keys", "overlay_runs"):
        assert 0 < getattr(tiny, field) < getattr(full, field)
    assert tiny.seeded_runs == tiny.big_runs + tiny.wide_runs + tiny.overlay_runs


def _result(series=50.0, zoom=50.0, first_paint=200_000, overlay=500.0):
    return {"series": {"p95": series}, "zoom": {"p95": zoom},
            "first_paint_bytes": first_paint, "overlay_ms": overlay, "errors": 0}


def test_series_slo_passes_a_healthy_result():
    assert slo.series_violations(_result(), slo.SERIES_BUDGETS["bigseries"]) == []


@pytest.mark.parametrize("kwargs, needle", [
    ({"series": 151.0}, "series"), ({"zoom": 151.0}, "zoom"),
    ({"first_paint": 1_000_001}, "first paint"), ({"overlay": 2001.0}, "overlay"),
])
def test_series_slo_flags_each_breach(kwargs, needle):
    out = slo.series_violations(_result(**kwargs), slo.SERIES_BUDGETS["bigseries"])
    assert len(out) == 1 and needle in out[0]


def test_series_slo_flags_errors():
    assert slo.series_violations(dict(_result(), errors=2), slo.SERIES_BUDGETS["bigseries"])


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    root = tmp_path_factory.mktemp("bigseries") / "repo"
    (root / ".git").mkdir(parents=True)
    profile = scenario.get_series_profile("bigseries-tiny")
    counts = seed_series.seed_profile(str(root), profile, app=APP, workers=2)
    return str(root), profile, counts


def _storage(root):
    return open_storage(root=local_store_root(root), area="runs")


def test_tiny_seed_writes_one_vmx_per_run_and_no_metric_log_lines(seeded):
    root, profile, counts = seeded
    assert counts == {"big": profile.big_runs, "wide": profile.wide_runs,
                      "overlay": profile.overlay_runs, "total": profile.seeded_runs}
    storage = _storage(root)
    for row in list_runs(APP, storage=storage):
        objects = storage.metric_objects(APP, row["verstr"])
        names = [n for objs in objects.values() for n, _ in objs]
        assert names == [f"metrics/{seed_series.WRITER}.vmx"]
        log = [e for entries in storage.load_logs_by_writer(APP, row["verstr"]).values()
               for e in entries]
        assert not any(e["type"] == "metrics" for e in log)


def test_tiny_seed_reads_back_through_the_index(seeded):
    root, profile, _ = seeded
    rows = list_runs(APP, storage=_storage(root))
    assert len(rows) == profile.seeded_runs
    assert all(r["status"] == "succeeded" for r in rows)
    wide = [r for r in rows if r["name"].startswith("wide-")]
    assert len(wide) == profile.wide_runs
    assert len(wide[0]["metrics"]) == profile.wide_keys
    big = next(r for r in rows if r["name"].startswith("big-"))
    assert len(big["metrics"]) == profile.big_keys


def test_tiny_profile_meets_its_series_slos(seeded, tmp_path):
    root, profile, _ = seeded
    with serve_root(root, tmp_path / "data", "ws") as (base_url, ws):
        result = probe_series.measure(base_url, ws, APP, profile)
    assert result["series"]["count"] == profile.probe_requests
    assert result["zoom"]["count"] == profile.probe_requests
    assert result["overlay_runs"] == profile.overlay_runs
    assert 0 < result["series_points_max"] <= profile.series_points
    assert slo.series_evaluate(result, "bigseries-tiny") == []
