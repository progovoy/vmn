"""Latency samples and the aggregated :class:`Report` the prober returns."""
import dataclasses
import math
from collections import Counter, defaultdict


@dataclasses.dataclass
class Sample:
    """One request: wall *ms*, HTTP *status* (None when it never answered),
    response *nbytes* (as downloaded, i.e. gzipped), whether it carried
    ``If-None-Match`` and the exception text when it failed."""

    route: str
    ms: float
    status: int
    nbytes: int
    conditional: bool = False
    error: str = None

    @property
    def failed(self):
        return self.error is not None or self.status is None or self.status >= 400


def percentile(values, pct):
    """Nearest-rank percentile of *values*, None when empty."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def _summary(values):
    return {
        "count": len(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": max(values) if values else None,
        "mean": sum(values) / len(values) if values else None,
    }


@dataclasses.dataclass
class Report:
    duration_sec: float
    requests: int
    errors: int
    conditional: int
    not_modified: int
    routes: dict
    status_codes: dict
    freshness: dict

    @property
    def rate_304(self):
        """Share of conditional (``If-None-Match``) requests answered 304."""
        return self.not_modified / self.conditional if self.conditional else None

    @property
    def error_rate(self):
        return self.errors / self.requests if self.requests else 0.0

    @property
    def rps(self):
        return self.requests / self.duration_sec if self.duration_sec else 0.0

    def to_dict(self):
        data = dataclasses.asdict(self)
        data.update(rate_304=self.rate_304, error_rate=self.error_rate, rps=self.rps)
        return data


def _route_stats(samples):
    stats = _summary([s.ms for s in samples])
    stats["errors"] = sum(s.failed for s in samples)
    stats["bytes"] = sum(s.nbytes for s in samples)
    stats["not_modified"] = sum(s.status == 304 for s in samples)
    return stats


def build_report(samples, freshness, duration_sec, routes=()):
    """Aggregate *samples* (plus freshness lags in seconds); every name in
    *routes* gets an entry even when it was never hit."""
    by_route = defaultdict(list)
    for name in routes:
        by_route[name]
    for s in samples:
        by_route[s.route].append(s)
    codes = Counter("error" if s.status is None else str(s.status) for s in samples)
    conditional = [s for s in samples if s.conditional]
    return Report(
        duration_sec=duration_sec,
        requests=len(samples),
        errors=sum(s.failed for s in samples),
        conditional=len(conditional),
        not_modified=sum(s.status == 304 for s in conditional),
        routes={name: _route_stats(group) for name, group in by_route.items()},
        status_codes=dict(codes),
        freshness=_summary(list(freshness)),
    )
