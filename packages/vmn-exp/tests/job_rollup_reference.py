"""A brute-force job rollup (plan 23 S1): every job's subtree walked from
scratch over freshly annotated rows, for the cache's incremental answer to
be checked against."""
import math

from vmn_exp.core.log import primary_metric
from vmn_exp.core.metric_schema import metric_goal
from vmn_exp.core.status import parse_iso
from vmn_exp.core.tree import annotate_rows, children_by_parent
from vmn_exp.ui.failure_signature import signature

from vmn_exp.core import status as status_mod

STATES = {"running": "running", "created": "waiting", "succeeded": "succeeded",
          "failed": "failed", "stuck": "stuck"}


def annotated(snapshot):
    return annotate_rows(snapshot.rows, snapshot.run_states, snapshot.run_state_observed_at)


def subtree(verstr, children_of, pruned=()):
    """The runs below *verstr*, not walking below any run in *pruned*."""
    out, stack, seen = [], list(children_of.get(verstr, ())), {verstr}
    while stack:
        kid = stack.pop()
        if kid in seen:
            continue
        seen.add(kid)
        out.append(kid)
        if kid not in pruned:
            stack.extend(children_of.get(kid, ()))
    return out


def members_of(rows, verstr):
    """Brute force: the runs a job's rollup counts — present, unarchived and
    under no archived run below *verstr*."""
    by_verstr = {row["verstr"]: row for row in rows}
    archived = {v for v, row in by_verstr.items() if row.get("archived")}
    return [by_verstr[v] for v in subtree(verstr, children_by_parent(rows), archived)
            if v in by_verstr and v not in archived]


def jobs(rows):
    present = {row["verstr"] for row in rows}
    return sorted(v for v in children_by_parent(rows) if v in present)


def goal_metrics(schema):
    names = {m for m in (schema or {}) if metric_goal(schema, m) and not set(m) & set("*?[")}
    if primary_metric(schema):
        names.add(primary_metric(schema))
    return sorted(names)


def common_metrics(rows, count=5):
    """The app's *count* metrics most runs carry (archived ones left out),
    never a param folded into ``metrics``."""
    counts, folded = {}, set()
    for row in rows:
        if not row.get("archived"):
            for name in row.get("metrics") or {}:
                counts[name] = counts.get(name, 0) + 1
                if name in (row.get("params") or {}):
                    folded.add(name)
    counts = {m: n for m, n in counts.items() if m not in folded}
    return sorted(counts, key=lambda m: (-counts[m], m))[:count]


def tracked_metrics(schema, rows):
    """``(metrics, main, ranked)``: the goal metrics (and the primary),
    else the most common ones; ranked when *main* has a goal (plan 32 F5)."""
    goals = goal_metrics(schema)
    if goals:
        main = primary_metric(schema) or goals[0]
    else:
        goals = common_metrics(rows)
        main = goals[0] if goals else None
    return goals, main, bool(main and metric_goal(schema, main))


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def exact_quantile(values, q):
    ordered = sorted(values)
    return ordered[round(q * (len(ordered) - 1))] if ordered else None


def _metric(rows, name, schema):
    pairs = [(row["metrics"][name], row["verstr"]) for row in rows
             if _finite(row["metrics"].get(name))]
    if not pairs:
        return None
    low = min(pairs)
    high = min(pairs, key=lambda p: (-p[0], p[1]))
    best = {"max": high, "min": low}.get(metric_goal(schema, name), (None, None))
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


ENDED = ("succeeded", "failed", "stuck")


def closes_children(row, by_verstr):
    """Brute force: the nearest started run at or above *row* has ended (a
    never-started run passes its parent's verdict on; a loop stays open)."""
    seen = set()
    while row is not None and row["verstr"] not in seen:
        seen.add(row["verstr"])
        if row["status"] != "created":
            return row["status"] in ENDED
        parent = row.get("parent")
        row = by_verstr.get(parent) if parent != row["verstr"] else None
    return False


def settled_of(row, by_verstr):
    """``never_started``/``lost`` for a created/stuck run under a parent that
    closes its children, else None."""
    parent = by_verstr.get(row.get("parent")) if row.get("parent") != row["verstr"] else None
    if row["status"] not in ("created", "stuck") or parent is None:
        return None
    if not closes_children(parent, by_verstr):
        return None
    return "never_started" if row["status"] == "created" else "lost"


def rollup(rows, verstr, schema):
    by_verstr = {row["verstr"]: row for row in rows}
    members = members_of(rows, verstr)
    counts = {state: 0 for state in STATES.values()}
    settled = {"never_started": 0, "lost": 0}
    for row in members:
        kind = settled_of(row, by_verstr)
        if kind:
            settled[kind] += 1
        else:
            counts[STATES[row["status"]]] += 1
    done = counts["succeeded"] + counts["failed"] + settled["lost"]
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
        "total": len(members), "counts": counts, "done": done, **settled,
        "ended": closes_children(by_verstr[verstr], by_verstr),
        "expected": _expected(by_verstr[verstr], len(members)),
        "throughput_per_min": recent / 10,
        "started_at": min(started, default=None), "finished_at": max(finished, default=None),
        "metrics": {m: _metric(members, m, schema) for m in metrics},
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


# -- plan 31 §2: a chosen aggregate over a job's units ----------------------

def _quantile(ordered, q):
    at = q * (len(ordered) - 1)
    low = int(at)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (at - low)


TAILS = {("best10", True): 0.9, ("best10", False): 0.1,
         ("worst10", True): 0.1, ("worst10", False): 0.9}


def aggregate(values, agg, up, rank=False):
    """*agg* of the finite *values* (``best``/tails by *up*; None without
    one); a quantile interpolated, or with *rank* the value at its rank (a
    sketch's)."""
    ordered = sorted(values)
    if not ordered or up is None:
        return None
    if agg == "mean":
        return math.fsum(ordered) / len(ordered)
    if agg == "min":
        return ordered[0]
    if agg == "max":
        return ordered[-1]
    if agg == "best":
        return ordered[-1] if up else ordered[0]
    q = 0.5 if agg == "median" else TAILS[(agg, up)]
    return exact_quantile(ordered, q) if rank else _quantile(ordered, q)


def _carries(row, by):
    kind, _, field = by.partition(":")
    if kind == "kind":
        return str((row.get("tags") or {}).get("kind")) == field
    prefix, _, name = field.partition(".")
    return (row.get(prefix) or {}).get(name) is not None


def units_of(rows, verstr, by):
    """Brute force: ``[(unit row, key)]`` of job *verstr*: its direct
    children, or the nearest descendants carrying the field/kind per branch."""
    shown = [row for row in rows if not row.get("archived")]
    by_verstr, children = {row["verstr"]: row for row in shown}, children_by_parent(shown)
    if by == "children":
        return [(by_verstr[k], None) for k in children.get(verstr, ())
                if k in by_verstr and k != verstr]
    prefix, _, name = by.partition(":")[2].partition(".")
    out, stack, seen = [], list(children.get(verstr, ())), {verstr}
    while stack:
        kid = stack.pop()
        if kid in seen or kid not in by_verstr:
            continue
        seen.add(kid)
        row = by_verstr[kid]
        if _carries(row, by):
            key = None if by.startswith("kind:") else str((row.get(prefix) or {}).get(name))
            out.append((row, key))
        else:
            stack.extend(children.get(kid, ()))
    return out


def unit_value(rows, unit, metric, source, up):
    """A unit's own *metric*, or (``best``) the best over it and its subtree."""
    own = (unit.get("metrics") or {}).get(metric)
    if source == "own":
        return own if _finite(own) else None
    below = [r["metrics"][metric] for r in members_of(rows, unit["verstr"])
             if _finite((r.get("metrics") or {}).get(metric))]
    values = below + ([own] if _finite(own) else [])
    if up is None:  # only a lone value is its own best
        return None if below else (own if _finite(own) else None)
    return (max(values) if up else min(values)) if values else None


def rolled(rows, verstr, by, source, metric, agg, up):
    """``{value, n, of, conflicts}`` of job *verstr* (``runs``: every run below it)."""
    if by == "runs":
        members = members_of(rows, verstr)
        values = [r["metrics"][metric] for r in members if _finite(r["metrics"].get(metric))]
        return {"value": aggregate(values, agg, up, rank=True), "n": len(values),
                "of": len(members),
                "conflicts": 0}
    keyed = {}
    for row, key in units_of(rows, verstr, by):
        keyed.setdefault(row["verstr"] if key is None else key, []).append(row)
    conflicts = sum(1 for kept in keyed.values() if len(kept) > 1)
    values = [unit_value(rows, kept[0], metric, source, up) for kept in keyed.values()
              if len(kept) == 1]
    values = [x for x in values if x is not None]
    return {"value": aggregate(values, agg, up), "n": len(values), "of": len(keyed),
            "conflicts": conflicts}
