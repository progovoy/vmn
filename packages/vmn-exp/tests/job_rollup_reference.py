"""A brute-force job rollup (plan 23 S1): every job's subtree walked from
scratch over freshly annotated rows, for the cache's incremental answer to
be checked against."""
import math

from vmn_exp.core import status as status_mod
from vmn_exp.core.log import primary_metric, sort_descending
from vmn_exp.core.metric_schema import metric_goal
from vmn_exp.core.status import parse_iso
from vmn_exp.core.tree import annotate_rows, children_by_parent
from vmn_exp.ui.failure_signature import signature

STATES = {"running": "running", "created": "waiting", "succeeded": "succeeded",
          "failed": "failed", "stuck": "stuck"}


def annotated(snapshot):
    return annotate_rows(snapshot.rows, snapshot.run_states, snapshot.run_state_observed_at)


def subtree(verstr, children_of):
    out, stack, seen = [], list(children_of.get(verstr, ())), {verstr}
    while stack:
        kid = stack.pop()
        if kid in seen:
            continue
        seen.add(kid)
        out.append(kid)
        stack.extend(children_of.get(kid, ()))
    return out


def jobs(rows):
    present = {row["verstr"] for row in rows}
    return sorted(v for v in children_by_parent(rows) if v in present)


def goal_metrics(schema):
    names = {m for m in (schema or {}) if metric_goal(schema, m) and not set(m) & set("*?[")}
    if primary_metric(schema):
        names.add(primary_metric(schema))
    return sorted(names)


def common_metrics(rows, count=5):
    """The app's *count* metrics most runs carry (archived ones left out)."""
    counts = {}
    for row in rows:
        if not row.get("archived"):
            for name in row.get("metrics") or {}:
                counts[name] = counts.get(name, 0) + 1
    return sorted(counts, key=lambda m: (-counts[m], m))[:count]


def tracked_metrics(schema, rows):
    """``(metrics, main, ranked)``: the goal metrics, else the most common
    ones, goal-less (never crowned)."""
    goals = goal_metrics(schema)
    if goals:
        return goals, primary_metric(schema) or goals[0], True
    common = common_metrics(rows)
    return common, (common[0] if common else None), False


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def exact_quantile(values, q):
    ordered = sorted(values)
    return ordered[round(q * (len(ordered) - 1))] if ordered else None


def _metric(rows, name, schema, ranked=True):
    pairs = [(row["metrics"][name], row["verstr"]) for row in rows
             if _finite(row["metrics"].get(name))]
    if not pairs:
        return None
    low = min(pairs)
    high = min(pairs, key=lambda p: (-p[0], p[1]))
    best = (high if sort_descending(schema, name) else low) if ranked else (None, None)
    values = [v for v, _ in pairs]
    return {"n": len(values), "min": low[0], "max": high[0], "mean": sum(values) / len(values),
            "best": best[0], "best_verstr": best[1], "values": values}


def _expected(job, total):
    planned = job.get("sweep_planned")
    pods = (job.get("params") or {}).get("expected_pods")
    if planned is not None:
        return planned
    if _finite(pods) and pods > 0:
        return int(pods)
    return total


def rollup(rows, verstr, schema):
    by_verstr = {row["verstr"]: row for row in rows}
    members = [by_verstr[v] for v in subtree(verstr, children_by_parent(rows))
               if v in by_verstr and not by_verstr[v].get("archived")]
    counts = {state: 0 for state in STATES.values()}
    for row in members:
        counts[STATES[row["status"]]] += 1
    done = counts["succeeded"] + counts["failed"]
    now_minute = int(status_mod._now().timestamp() // 60)
    recent = sum(1 for row in members if row["status"] in ("succeeded", "failed")
                 and row.get("finished_at")
                 and now_minute - 10 < parse_iso(row["finished_at"]).timestamp() // 60 <= now_minute)
    failures = {}
    for row in members:
        sig = signature(row)
        if sig:
            failures[sig] = failures.get(sig, 0) + 1
    durations = [row["duration_sec"] for row in members
                 if row["status"] in ("succeeded", "failed") and row.get("finished_at")
                 and _finite(row.get("duration_sec"))]
    started = [row["started_at"] for row in members if row.get("started_at")]
    events = [("started", _minute(row["started_at"])) for row in members if row.get("started_at")]
    events += [(row["status"], _minute(row["finished_at"])) for row in members
               if row["status"] in ("succeeded", "failed") and row.get("finished_at")]
    finished = [row["finished_at"] for row in members if row.get("finished_at")]
    metrics, main, ranked = tracked_metrics(schema, rows)
    return {
        "metric": main, "ranked": ranked,
        "total": len(members), "counts": counts, "done": done,
        "expected": _expected(by_verstr[verstr], len(members)),
        "throughput_per_min": recent / 10,
        "started_at": min(started, default=None), "finished_at": max(finished, default=None),
        "metrics": {m: _metric(members, m, schema, ranked) for m in metrics},
        "durations": durations,
        "failures": sorted(failures.items(), key=lambda kv: (-kv[1], kv[0]))[:10],
        "events": events,
    }


def _minute(stamp):
    return int(parse_iso(stamp).timestamp() // 60)


def timeline(events, minutes):
    """``{bucket start sec: (started, succeeded, failed)}`` of *events* per *minutes*."""
    out = {}
    for kind, minute in events:
        t = minute // minutes * minutes * 60
        counts = list(out.get(t, (0, 0, 0)))
        counts[("started", "succeeded", "failed").index(kind)] += 1
        out[t] = tuple(counts)
    return out
