"""uiload SLO budgets and their evaluation, on synthetic reports."""
import pytest
from uiload import slo
from uiload.probe_stats import Report, Sample, build_report, percentile


def _route(p95, count=100, errors=0):
    return {"count": count, "errors": errors, "p50": p95 / 2, "p95": p95,
            "p99": p95 * 1.1, "max": p95 * 1.2, "mean": p95 / 2, "bytes": 1000}


def _report(list_ms=50, detail_ms=80, series_ms=100, columns_ms=100, facets_ms=100,
            fresh_p95=1.0, errors=0, conditional=100, not_modified=60):
    routes = {
        "list.first": _route(list_ms), "list.deep": _route(list_ms),
        "detail": _route(detail_ms), "detail.log": _route(detail_ms),
        "series": _route(series_ms), "columns": _route(columns_ms), "facets": _route(facets_ms),
    }
    return Report(
        duration_sec=10, requests=700, errors=errors, conditional=conditional,
        not_modified=not_modified, routes=routes, status_codes={200: 640, 304: 60},
        freshness={"count": 20, "p50": fresh_p95 / 2, "p95": fresh_p95, "max": fresh_p95},
    )


def test_budgets_are_data_per_profile():
    assert set(slo.BUDGETS) == {"smoke", "load", "soak"}
    assert slo.BUDGETS["smoke"]["list_p95_ms"] == 100
    assert slo.BUDGETS["load"]["list_p95_ms"] == 150
    assert slo.BUDGETS["smoke"]["detail_p95_ms"] == 150
    assert slo.BUDGETS["load"]["series_p95_ms"] == 500
    assert slo.BUDGETS["load"]["freshness_p95_sec"] == 3
    assert slo.BUDGETS["soak"]["report_only"] is True


def test_healthy_report_passes():
    assert slo.evaluate(_report(), "smoke") == []
    assert slo.evaluate(_report(), "load") == []


@pytest.mark.parametrize(
    "kwargs, needle",
    [
        ({"list_ms": 120}, "list.first"),
        ({"detail_ms": 160}, "detail.log"),
        ({"series_ms": 301}, "series"),
        ({"columns_ms": 400}, "columns"),
        ({"facets_ms": 400}, "facets"),
        ({"fresh_p95": 4.0}, "freshness"),
        ({"errors": 1}, "error"),
        ({"not_modified": 1}, "304"),
    ],
)
def test_each_budget_breach_is_reported(kwargs, needle):
    violations = slo.evaluate(_report(**kwargs), "smoke")
    assert any(needle in v for v in violations), violations


def test_load_profile_is_looser_than_smoke():
    report = _report(list_ms=120)
    assert slo.evaluate(report, "smoke")
    assert slo.evaluate(report, "load") == []


def test_soak_is_report_only():
    assert slo.evaluate(_report(list_ms=10_000, errors=5, fresh_p95=60), "soak") == []


def test_no_conditional_requests_or_freshness_samples_are_not_violations():
    report = _report(conditional=0, not_modified=0)
    report.freshness = {"count": 0, "p50": None, "p95": None, "max": None}
    assert slo.evaluate(report, "smoke") == []


def test_unknown_profile_raises():
    with pytest.raises(KeyError):
        slo.evaluate(_report(), "nope")


def test_correctness_within_ambiguity_passes():
    api = {"running": 10, "succeeded": 50, "stuck": 3}
    expected = {"running": 12, "succeeded": 50, "stuck": 2}
    assert slo.correctness(api, expected, ambiguous_n=2) == []


def test_correctness_flags_status_off_by_more_than_ambiguous():
    api = {"running": 10, "succeeded": 50, "failed": 4}
    expected = {"running": 10, "succeeded": 45}
    violations = slo.correctness(api, expected, ambiguous_n=1)
    assert any("succeeded" in v for v in violations)
    assert any("failed" in v for v in violations)
    assert not any("running" in v for v in violations)


def test_correctness_tolerance_widens_the_window():
    assert slo.correctness({"failed": 5}, {"failed": 2}, ambiguous_n=1, tolerance=2) == []


def test_percentile_nearest_rank():
    values = list(range(1, 101))
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile(values, 100) == 100
    assert percentile([], 50) is None


def test_build_report_aggregates_samples():
    samples = [Sample("list.first", 10.0, 200, 100), Sample("list.first", 30.0, 304, 0, conditional=True),
               Sample("detail", 20.0, 500, 10), Sample("detail", 5.0, None, 0, error="boom", conditional=True)]
    report = build_report(samples, freshness=[0.5, 1.5], duration_sec=2.0)
    assert report.requests == 4
    assert report.errors == 2
    assert report.conditional == 2 and report.not_modified == 1
    assert report.rate_304 == 0.5
    assert report.routes["list.first"]["count"] == 2
    assert report.routes["list.first"]["max"] == 30.0
    assert report.routes["detail"]["errors"] == 2
    assert report.freshness["max"] == 1.5
    assert report.status_codes == {"200": 1, "304": 1, "500": 1, "error": 1}
    assert report.to_dict()["rate_304"] == 0.5
