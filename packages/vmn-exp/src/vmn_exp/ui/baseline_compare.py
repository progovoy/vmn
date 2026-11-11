#!/usr/bin/env python3
"""An outer run against its baseline (plan 28 N3), pure: the deltas of two
rollups (:mod:`~vmn_exp.ui.job_rollup_payload`) and of their ``rolled``
aggregates (plan 31 §2), their direct children paired by a key field with
the delta of their value per pair (a key either side lacks a value for is
unpaired, never filled from another source: plan 32), and the
chip, which counts the finished pairs worse than the baseline's worst
decile (``p10`` of a higher-is-better metric, ``p90`` of a lower-is-better
one) — so a regression shows as soon as the first matched children end. An
outer run holding no key says so (``none``, plan 35 §3), never "no value
finished yet".
"""
from vmn_exp.core.metric_schema import higher_is_better
from vmn_exp.core.settle import row_closes
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.baseline_choice import recency
from vmn_exp.ui.leaderboard_group_fields import NONE, key_of, key_text, value_of
from vmn_exp.ui.leaderboard_group_summary import quantile as interpolated
from vmn_exp.ui.pivot import value_order

WORSE, BETTER, SAME, PENDING, NONE_OWN = "worse", "better", "same", "pending", "none"
MARKS = {WORSE: "▼", BETTER: "▲", SAME: "="}
# A delta's ``better`` as a chip state.
STATES = {True: BETTER, False: WORSE, None: SAME}


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


def _metric_deltas(target, baseline, name, goal):
    up = higher_is_better(goal)
    pair = lambda field: delta(_metric(target, name, field), _metric(baseline, name, field), up)  # noqa: E731
    out = {"goal": goal, "best": pair("best"), "median": pair("p50")}
    sides = {"value": _metric(target, name, "policies"), "baseline": _metric(baseline, name, "policies")}
    if any(sides.values()):
        out["policies"] = sides  # each side's overrides of the schema's summary (plan 32 F1)
    return out


ROLLED_FIELDS = ("agg", "by", "source", "metric", "goal", "percentile")


def rolled_delta(target, baseline):
    """The delta of two ``rolled`` aggregates (the same aggregate), naming it."""
    return {**{k: target[k] for k in ROLLED_FIELDS},
            **delta(target["value"], baseline["value"], higher_is_better(target["goal"]))}


def rollup_deltas(target, baseline, goals, rolled=None):
    """The deltas of two job rollups: per metric of *goals* (``{name: goal,
    None when goal-less}``) its goal, best and median, then ``failed_pct``
    and ``duration_p90`` (lower is better); with *rolled* (both jobs'
    ``rolled``) its delta as ``rolled``."""
    metrics = {name: _metric_deltas(target, baseline, name, goal) for name, goal in goals.items()}
    p90 = lambda rollup: (rollup.get("duration") or {}).get("p90")  # noqa: E731
    out = {"metrics": metrics,
           "failed_pct": delta(target.get("failed_pct"), baseline.get("failed_pct"), False),
           "duration_p90": delta(p90(target), p90(baseline), False)}
    if rolled:
        out["rolled"] = rolled_delta(*rolled)
    return out


def _keyed(rows, field):
    """``{key: (raw value, latest row holding it)}`` of the rows with a value."""
    key_in, value_in, out = key_of(field), value_of(field), {}
    for row in rows:
        key = key_in(row)
        if key == NONE:
            continue
        kept = out.get(key)
        if kept is None or recency(row) > recency(kept[1]):
            out[key] = (value_in(row), row)
    return out


def pair_children(target, baseline, field, value, higher_better):
    """``(pairs, keys)``: the rows of *target* and *baseline* sharing a value
    of *field* and both holding a *value(row)*, in key order, each ``{key,
    label, verstr, idx, baseline_verstr, value, baseline, delta, better,
    done}``, and how many keys *target* holds (the unpaired among them)."""
    ours, theirs = _keyed(target, field), _keyed(baseline, field)
    keys = sorted((k for k in ours if k in theirs), key=lambda k: value_order(k, ours[k][0]))
    pairs = []
    for key in keys:
        row, base = ours[key][1], theirs[key][1]
        mine, other = value(row), value(base)
        if mine is None or other is None:
            continue
        pairs.append({"key": key, "label": key_text(key),
                      "verstr": row["verstr"], "idx": row.get("idx"),
                      "baseline_verstr": base["verstr"],
                      **delta(mine, other, higher_better), "done": row_closes(row)})
    return pairs, len(ours)


def _median(values):
    ordered = sorted(values)
    return interpolated(ordered, 0.5) if ordered else None


def _noun(field):
    return f"{field.partition('.')[2]} values"


def chip(pairs, baseline_values, metric, higher_better, field, total=None, pooled=False):
    """The chip of *pairs* (marking each finished one ``worse`` or not):
    ``{state, text, metric, from, worse, of, quantile, threshold, paired,
    total}`` (*total*: the keys the target holds, paired or not; *pooled*:
    over its training's attempts), None for a goal-less *metric*.
    *baseline_values*: the value of every baseline child holding a key."""
    if higher_better is None or metric is None:
        return None
    ordered = sorted(v for v in baseline_values if is_finite_number(v))
    quantile = "p10" if higher_better else "p90"
    threshold = interpolated(ordered, 0.1 if higher_better else 0.9) if ordered else None
    finished = [p for p in pairs if p["done"] and is_finite_number(p["value"])]
    for p in finished:
        p["worse"] = threshold is not None and (
            p["value"] < threshold if higher_better else p["value"] > threshold)
    worse = [p for p in finished if p["worse"]]
    out = {"metric": metric, "from": worse[0]["label"] if worse else None, "worse": len(worse),
           "of": len(finished), "quantile": quantile, "threshold": threshold,
           "paired": len(pairs), "total": len(pairs) if total is None else total}
    return dict(out, **_state(out, finished, higher_better, field, pooled))


def _state(out, finished, higher_better, field, pooled):
    metric, noun = out["metric"], _noun(field)
    if not out["total"]:
        name = field.partition(".")[2]
        whose = (f"this training has no {name} runs in any attempt" if pooled
                 else f"this attempt has no {name} runs of its own")
        return {"state": NONE_OWN, "text": f"{metric}: {whose}"}
    if not finished:
        return {"state": PENDING, "text": f"{metric}: no {noun[:-1]} finished yet"}
    tail = f"{noun} worse than the baseline's {out['quantile']})"
    if out["worse"]:
        return {"state": WORSE,
                "text": f"{MARKS[WORSE]} {metric} from {out['from']} ({out['worse']} of {out['of']} {tail}"}
    middle = _median([p["delta"] for p in finished if p["delta"] is not None])
    improved = middle is not None and (middle > 0 if higher_better else middle < 0)
    state = BETTER if improved else SAME
    return {"state": state, "text": f"{MARKS[state]} {metric} (none of {out['of']} {tail}"}


def best_chip(rollup_delta):
    """The chip without paired children: the ``rolled`` value's change
    (named by its aggregate unless it is the ``best``)."""
    rolled = rollup_delta.get("rolled")
    if not rolled or rolled["delta"] is None:
        return None
    state, metric = STATES[rolled["better"]], rolled["metric"]
    name = metric if rolled["agg"] == "best" else f"{rolled['agg']} {metric}"
    return dict(dict.fromkeys(("from", "worse", "of", "quantile", "threshold")),
                state=state, metric=metric,
                text=f"{MARKS[state]} {name} {rolled['value']:.4g} "
                     f"(baseline {rolled['baseline']:.4g})")
