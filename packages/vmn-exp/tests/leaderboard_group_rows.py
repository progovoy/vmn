"""Small index snapshots for the grouped leaderboard tests (plan 22 S1): runs
described by a few keyword fields, folded the way the index folds them."""
import datetime

from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.log import experiment_row

APP = "app"
NOW = datetime.datetime.now(datetime.timezone.utc)


def v(n):
    """The verstr of run *n*."""
    return f"1.0.0-dev.r{n:04d}"


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(kind):
    if kind is None:
        return None
    if kind == "running":
        return {"state": "running", "exit_code": None, "started_at": _iso(NOW),
                "heartbeat": _iso(NOW), "heartbeat_interval_sec": 30}
    if kind == "stuck":  # running, its heartbeat an hour stale
        old = _iso(NOW - datetime.timedelta(hours=1))
        return {"state": "running", "exit_code": None, "started_at": old,
                "heartbeat": old, "heartbeat_interval_sec": 30}
    return {"state": "finished", "exit_code": 0 if kind == "ok" else 1,
            "started_at": _iso(NOW), "finished_at": _iso(NOW), "heartbeat": _iso(NOW)}


def run(n, state="ok", metrics=None, params=None, tags=None, log=(), **meta):
    """A run spec: *meta* fields go to its metadata (``parent=3`` and
    ``rerun_of=3`` name run 3, ``forked_from=3`` too)."""
    for link in ("parent", "rerun_of"):
        if isinstance(meta.get(link), int):
            meta[link] = v(meta[link])
    if isinstance(meta.get("forked_from"), int):
        meta["forked_from"] = {"verstr": v(meta["forked_from"]), "step": 1}
    return {"n": n, "state": state, "metrics": metrics or {}, "params": params or {},
            "tags": tags or {}, "log": list(log), "meta": meta}


def snapshot(specs, generation=1, schema=None):
    rows, states = [], {}
    for i, spec in enumerate(specs):
        meta = {"verstr": v(spec["n"]), "timestamp": f"2026-01-01T00:00:{i % 60:02d}.{i:06d}Z",
                "branch": "main", **spec["meta"]}
        log = [{"timestamp": "t", "type": "create", "params": spec["params"],
                "tags": spec["tags"]}]
        log += [{"timestamp": "t", "type": "metrics", "values": {k: x}}
                for k, x in spec["metrics"].items()]
        log += spec["log"]
        rows.append(experiment_row(i + 1, meta, log, schema=schema))
        states[meta["verstr"]] = _state(spec["state"])
    return IndexSnapshot.build(APP, generation, rows, states)


def keys(payload):
    return [g["key"] for g in payload["groups"]]


def members(group):
    return [row["verstr"] for row in group["rows"]]


def group_of(payload, key):
    return next(g for g in payload["groups"] if g["key"] == key)
