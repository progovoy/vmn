"""Parameter importance: which params drive a metric across runs.

For a target metric over a set of leaderboard rows, every param with at least
two distinct values gets:

* ``importance`` — its share of a small random forest's impurity decrease
  (:mod:`vmn_exp.core.forest`), so the column sums to 1;
* ``correlation`` / ``spearman`` — Pearson and rank correlation with the
  metric, for numeric and bool params (``None`` for categorical ones, whose
  values have no order);
* ``kind`` — ``numeric``, ``bool`` (scored as 0/1) or ``categorical``;
* ``n`` — the runs that carry both the param and the metric.

Rows are ordered by verstr first and, past *max_rows*, sampled with a fixed
seed, so the answer depends on the set of runs only. Missing numeric values
are imputed with the median; a missing categorical value is its own category.
"""
import json
import math
import random
from bisect import bisect_right
from collections import Counter
from itertools import groupby
from operator import mul

from vmn_exp.core.forest import forest_importance
from vmn_exp.core.log import _sortable

MAX_ROWS = 5000
MAX_BINS = 16
SEED = 0


def require_metric(rows, metric):
    """ValueError unless some row carries *metric* as a finite number."""
    if not any(_sortable(row["metrics"].get(metric)) for row in rows):
        raise ValueError(f"Unknown metric '{metric}': no run carries it")


def param_importance(rows, metric, universe=None, max_rows=MAX_ROWS, seed=SEED):
    """``[{param, importance, correlation, spearman, kind, n}]``, most important first.

    With *universe* (the rows before filtering), a *metric* none of them
    carries is a ValueError, while a filter leaving no run with it gives ``[]``.
    """
    if universe is not None:
        require_metric(universe, metric)
    rows = _sample(_scored(rows, metric), max_rows, seed)
    y = [row["metrics"][metric] for row in rows]
    params = [row.get("params") or {} for row in rows]
    features = [
        feature
        for feature in (_feature(name, params) for name in _param_names(params, metric))
        if feature
    ]
    if not features:
        return []
    scores = forest_importance(
        [feature["bins"] for feature in features],
        y,
        [feature["kind"] == "categorical" for feature in features],
        seed=seed,
    )
    y_ranks = _ranks(y)
    result = [_entry(feature, score, y, y_ranks) for feature, score in zip(features, scores)]
    return sorted(result, key=lambda entry: (-entry["importance"], entry["param"]))


def _scored(rows, metric):
    carrying = [row for row in rows if _sortable(row["metrics"].get(metric))]
    return sorted(carrying, key=lambda row: row["verstr"])


def _sample(rows, max_rows, seed):
    if len(rows) <= max_rows:
        return rows
    keep = sorted(random.Random(seed).sample(range(len(rows)), max_rows))
    return [rows[i] for i in keep]


def _param_names(params, metric):
    names = {name for row_params in params for name in row_params}
    names.discard(metric)
    return sorted(names)


def _present(value):
    if value is None:
        return False
    return not (isinstance(value, float) and not math.isfinite(value))


def _kind(values):
    types = set(map(type, values))
    if types == {bool}:
        return "bool"
    if types <= {int, float}:
        return "numeric"
    return "categorical"


def _feature(name, params):
    """The param's kind, bin codes (one per row) and present values by row; None
    when it has fewer than two distinct values."""
    raw = [row_params.get(name) for row_params in params]
    present = [i for i, v in enumerate(raw) if _present(v)]
    if not present:
        return None
    kind = _kind([raw[i] for i in present])
    if kind == "categorical":
        labels = [_label(v) if _present(v) else None for v in raw]
        if len(set(labels[i] for i in present)) < 2:
            return None
        return {"name": name, "kind": kind, "bins": _category_bins(labels), "n": len(present)}
    values = {i: float(raw[i]) for i in present}
    if len(set(values.values())) < 2:
        return None
    return {
        "name": name,
        "kind": kind,
        "bins": _numeric_bins(values, len(raw)),
        "n": len(present),
        "values": values,
    }


def _label(value):
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)


def _category_bins(labels):
    """Codes for the most common categories; the rest share the last bin."""
    common = sorted(Counter(labels).items(), key=lambda kv: (-kv[1], str(kv[0])))
    codes = {label: code for code, (label, _) in enumerate(common[: MAX_BINS - 1])}
    return [codes.get(label, MAX_BINS - 1) for label in labels]


def _numeric_bins(values, size):
    """Quantile bin codes (rank order kept); missing rows take the median's."""
    ordered = sorted(values.values())
    distinct = sorted(set(ordered))
    if len(distinct) <= MAX_BINS:
        edges = distinct[1:]
    else:
        edges = sorted({ordered[j * len(ordered) // MAX_BINS] for j in range(1, MAX_BINS)})
    median = bisect_right(edges, ordered[len(ordered) // 2])
    xs = map(values.get, range(size))
    return [median if x is None else bisect_right(edges, x) for x in xs]


def _entry(feature, score, y, y_ranks):
    """The result row; *y_ranks* are the ranks of *y*, reused when every row
    carries the param."""
    correlation = spearman = None
    if feature["kind"] != "categorical":
        xs = list(feature["values"].values())
        ys = [y[i] for i in feature["values"]]
        correlation = _pearson(xs, ys)
        ys_ranks = y_ranks if len(ys) == len(y) else _ranks(ys)
        spearman = _pearson(_ranks(xs), ys_ranks)
    return {
        "param": feature["name"],
        "importance": score,
        "correlation": correlation,
        "spearman": spearman,
        "kind": feature["kind"],
        "n": feature["n"],
    }


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    sxy, sxx, syy = sum(map(mul, dx, dy)), sum(map(mul, dx, dx)), sum(map(mul, dy, dy))
    if sxx <= 0 or syy <= 0:
        return None
    return max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))


def _ranks(values):
    """Ranks with ties averaged."""
    rank_of, start = {}, 0
    for value, ties in groupby(sorted(values)):
        count = len(list(ties))
        rank_of[value] = start + (count - 1) / 2.0
        start += count
    return list(map(rank_of.__getitem__, values))
