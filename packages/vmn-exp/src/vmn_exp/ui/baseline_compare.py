#!/usr/bin/env python3
"""An outer run against its baseline (plan 28 N3), pure: the deltas of two
rollups (:mod:`~vmn_exp.ui.job_rollup_payload`), their direct children
paired by a key field with the delta of the main metric per pair, and the
chip, which counts the finished pairs worse than the baseline's worst
decile (``p10`` of a higher-is-better metric, ``p90`` of a lower-is-better
one) — so a regression shows as soon as the first matched children end.
"""
from vmn_exp.core.settle import row_closes
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.leaderboard_group_fields import NONE, NONE_LABEL, key_of, key_text, value_of
from vmn_exp.ui.pivot import value_order

WORSE, BETTER, SAME, PENDING = "worse", "better", "same", "pending"


def _rounded(value):
    """*value* without the float noise a subtraction picks up."""
    return float(f"{value:.12g}")


def delta(value, baseline, higher_better):
    """``{value, baseline, delta, better}``; ``better`` None without a
    direction, a value on either side, or a change."""
    both = is_finite_number(value) and is_finite_number(baseline)
    change = _rounded(value - baseline) if both else None
    better = None
    if change and higher_better is not None:
        better = change > 0 if higher_better else change < 0
    return {"value": value, "baseline": baseline, "delta": change, "better": better}


def _metric(rollup, name, field):
    return ((rollup.get("metrics") or {}).get(name) or {}).get(field)


def rollup_deltas(target, baseline, directions):
    """The deltas of two job rollups: per metric of *directions* (``{name:
    higher is better, None when goal-less}``) its best and median, then
    ``failed_pct`` and ``duration_p90`` (lower is better)."""
    metrics = {
        name: {"best": delta(_metric(target, name, "best"), _metric(baseline, name, "best"), up),
               "median": delta(_metric(target, name, "p50"), _metric(baseline, name, "p50"), up)}
        for name, up in directions.items()}
    p90 = lambda rollup: (rollup.get("duration") or {}).get("p90")  # noqa: E731
    return {"metrics": metrics,
            "failed_pct": delta(target.get("failed_pct"), baseline.get("failed_pct"), False),
            "duration_p90": delta(p90(target), p90(baseline), False)}


def _keyed(rows, field):
    """``{key: (raw value, latest row holding it)}`` of the rows with a value."""
    key_in, value_in, out = key_of(field), value_of(field), {}
    for row in rows:
        key = key_in(row)
        if key == NONE:
            continue
        kept = out.get(key)
        if kept is None or (row.get("timestamp") or "", row["verstr"]) > (
                kept[1].get("timestamp") or "", kept[1]["verstr"]):
            out[key] = (value_in(row), row)
    return out


def pair_children(target, baseline, field, value, higher_better):
    """``(pairs, keyed)``: the rows of *target* and *baseline* sharing a value
    of *field*, in key order, each ``{key, label, verstr, idx,
    baseline_verstr, value, baseline, delta, better, done}`` (*value(row)*
    its main metric), and how many keys *target* holds."""
    ours, theirs = _keyed(target, field), _keyed(baseline, field)
    keys = sorted((k for k in ours if k in theirs), key=lambda k: value_order(k, ours[k][0]))
    pairs = []
    for key in keys:
        row, base = ours[key][1], theirs[key][1]
        pairs.append({"key": key, "label": NONE_LABEL if key == NONE else key_text(key),
                      "verstr": row["verstr"], "idx": row.get("idx"),
                      "baseline_verstr": base["verstr"],
                      **delta(value(row), value(base), higher_better), "done": row_closes(row)})
    return pairs, len(ours)


def _quantile(ordered, q):
    at = q * (len(ordered) - 1)
    low = int(at)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (at - low)


def _median(values):
    ordered = sorted(values)
    return _quantile(ordered, 0.5) if ordered else None


def _noun(field):
    return f"{field.partition('.')[2]} values"


def chip(pairs, baseline_values, metric, higher_better, field):
    """The chip of *pairs* (marking each finished one ``worse`` or not):
    ``{state, text, metric, from, worse, of, quantile, threshold}``, None for
    a goal-less *metric*. *baseline_values*: the main metric of every
    baseline child holding a key."""
    if higher_better is None or metric is None:
        return None
    ordered = sorted(v for v in baseline_values if is_finite_number(v))
    quantile = "p10" if higher_better else "p90"
    threshold = _quantile(ordered, 0.1 if higher_better else 0.9) if ordered else None
    finished = [p for p in pairs if p["done"] and is_finite_number(p["value"])]
    for p in finished:
        p["worse"] = threshold is not None and (
            p["value"] < threshold if higher_better else p["value"] > threshold)
    worse = [p for p in finished if p["worse"]]
    out = {"metric": metric, "from": worse[0]["label"] if worse else None, "worse": len(worse),
           "of": len(finished), "quantile": quantile, "threshold": threshold}
    return dict(out, **_state(out, finished, higher_better, field))


def _state(out, finished, higher_better, field):
    metric, noun = out["metric"], _noun(field)
    if not finished:
        return {"state": PENDING, "text": f"{metric}: no {noun[:-1]} finished yet"}
    tail = f"{noun} worse than the baseline's {out['quantile']})"
    if out["worse"]:
        return {"state": WORSE,
                "text": f"▼ {metric} from {out['from']} ({out['worse']} of {out['of']} {tail}"}
    middle = _median([p["delta"] for p in finished if p["delta"] is not None])
    improved = middle is not None and (middle > 0 if higher_better else middle < 0)
    state, mark = (BETTER, "▲") if improved else (SAME, "=")
    return {"state": state, "text": f"{mark} {metric} (none of {out['of']} {tail}"}


def best_chip(rollup_delta, metric):
    """The chip without paired children: the best value's change."""
    best = rollup_delta["metrics"].get(metric, {}).get("best") if metric else None
    if not best or best["delta"] is None:
        return None
    state, mark = {True: (BETTER, "▲"), False: (WORSE, "▼")}.get(best["better"], (SAME, "="))
    return {"state": state, "metric": metric, "from": None, "worse": None, "of": None,
            "quantile": None, "threshold": None,
            "text": f"{mark} {metric} {best['value']:.4g} (baseline {best['baseline']:.4g})"}
