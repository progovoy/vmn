"""Service-level budgets for the dashboard API and their evaluation.

A route's budget is picked by its family: the part of its name before the
first dot (``list.deep`` -> ``list``, ``detail.log`` -> ``detail``).
"""

_BASE = {
    "max_error_rate": 0.0,
    # Of the requests that carried If-None-Match, at least this share must 304.
    "min_304_rate": 0.2,
    "report_only": False,
}

BUDGETS = {
    "smoke": dict(
        _BASE, list_p95_ms=100, detail_p95_ms=150, series_p95_ms=300,
        columns_p95_ms=300, facets_p95_ms=300, freshness_p95_sec=3,
    ),
    "load": dict(
        _BASE, list_p95_ms=150, detail_p95_ms=200, series_p95_ms=500,
        columns_p95_ms=500, facets_p95_ms=500, freshness_p95_sec=3,
    ),
}
BUDGETS["soak"] = dict(BUDGETS["load"], report_only=True)


def _family(route):
    return route.split(".", 1)[0]


def _latency_violations(report, budget):
    for route, stats in sorted(report.routes.items()):
        limit = budget.get(f"{_family(route)}_p95_ms")
        p95 = stats.get("p95")
        if limit is not None and p95 is not None and p95 > limit:
            yield f"{route} p95 {p95:.1f}ms > {limit}ms"


def _other_violations(report, budget):
    if report.error_rate > budget["max_error_rate"]:
        yield f"error rate {report.error_rate:.4f} ({report.errors}/{report.requests}) > {budget['max_error_rate']}"
    rate = report.rate_304
    if rate is not None and rate < budget["min_304_rate"]:
        yield f"304 rate {rate:.2f} on {report.conditional} conditional requests < {budget['min_304_rate']}"
    fresh = report.freshness.get("p95")
    if fresh is not None and fresh > budget["freshness_p95_sec"]:
        yield f"freshness p95 {fresh:.2f}s > {budget['freshness_p95_sec']}s"


def violations(report, budget):
    """Every breach of *budget*, whether or not the profile is report-only."""
    return [*_latency_violations(report, budget), *_other_violations(report, budget)]


def evaluate(report, profile_name):
    """Budget breaches of *report* under *profile_name* (empty = pass).
    A report-only profile (soak) never fails."""
    budget = BUDGETS[profile_name]
    return [] if budget["report_only"] else violations(report, budget)


def correctness(api_counts, expected_counts, ambiguous_n, tolerance=0):
    """Statuses whose API count differs from the oracle's by more than the
    *ambiguous_n* jobs it could not decide (plus *tolerance*)."""
    allowed = ambiguous_n + tolerance
    out = []
    for status in sorted(set(api_counts) | set(expected_counts)):
        got, want = api_counts.get(status, 0), expected_counts.get(status, 0)
        if abs(got - want) > allowed:
            out.append(f"{status}: api {got} vs expected {want} (allowed ±{allowed})")
    return out
