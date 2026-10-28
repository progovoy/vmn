#!/usr/bin/env python3
"""The summary parts of the dump's newer sections (:mod:`diag_summary` calls
them): held locks and their waiters, long or failing background work, S3 by
object kind and by caller, S3 prefixes that waited for a slot, request S3
cost, recent errors and lag. Same rules: a part that cannot read its section
is skipped."""
SHOWN = 8
# Background work running longer than this is worth a line.
LONG_RUNNING_SEC = 5
# Lag past this means the loop or the interpreter stalled.
STALL_MS = 1000


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def locks(sections):
    held = _list(_dict(sections.get("locks")).get("held"))
    lines = []
    for lock in held[:SHOWN]:
        waiters = _list(lock.get("waiters"))
        longest = max((w.get("waiting_sec") or 0 for w in waiters), default=0)
        wait = f"; {len(waiters)} waiting, longest {longest:.1f}s" if waiters else ""
        lines.append(f"  {lock.get('name')} held {lock.get('held_sec', 0):.1f}s by "
                     f"{lock.get('holder')}{wait}")
    return ["Locks held:"] + lines if lines else []


def background(sections):
    lines = []
    for act in _list(_dict(sections.get("background")).get("activities")):
        label = act.get("name", "?") + (f" [{act['key']}]" if act.get("key") else "")
        for run in _list(act.get("running")):
            if (run.get("running_sec") or 0) >= LONG_RUNNING_SEC:
                lines.append(f"  {label}: running {run['running_sec']:.1f}s on "
                             f"{run.get('thread')}")
        error = _dict(act.get("last_error"))
        if error:
            lines.append(f"  {label}: last error {error.get('ago_sec', '?')}s ago: "
                         f"{error.get('error')}")
    return ["Background work:"] + lines if lines else []


def s3_kinds(sections):
    s3 = _dict(sections.get("s3"))
    kinds = sorted(_dict(s3.get("by_kind")).items(),
                   key=lambda kv: -_dict(kv[1]).get("count", 0))
    lines = []
    for name, kind in kinds[:SHOWN]:
        lat = _dict(kind.get("latency_ms"))
        errors = ", ".join(f"{k}={v}" for k, v in _dict(kind.get("errors")).items())
        lines.append(f"  {name}: {kind.get('count', 0)} calls, p95 {lat.get('p95', '?')}ms"
                     f" max {lat.get('max', '?')}ms" + (f", errors {errors}" if errors else ""))
    for f in _list(s3.get("recent_other_failures"))[:SHOWN]:
        lines.append(f"  failed {f.get('age_sec', '?')}s ago: {f.get('operation')} "
                     f"{f.get('key')} {f.get('error')} ({f.get('status')})")
    callers = sorted(_dict(s3.get("by_thread")).items(), key=lambda kv: -_calls(kv[1]))
    for name, ops in callers[:SHOWN]:
        lines.append(f"  by {name}: {_ops_text(ops)}")
    return ["S3 by object kind and caller:"] + lines if lines else []


def s3_prefix_caps(sections):
    caps = _dict(_dict(sections.get("s3")).get("prefix_caps"))
    lines = [f"  {p.get('bucket')}/{p.get('prefix')}: {p.get('in_flight', 0)} in flight, "
             f"{p.get('waiting', 0)} waiting; {p.get('waits', 0)} waits, "
             f"max {(p.get('wait_ms_max') or 0) / 1000:.1f}s"
             for p in _list(caps.get("prefixes"))[:SHOWN] if p.get("waiting") or p.get("waits")]
    head = f"S3 prefix caps ({caps.get('limit', '?')} calls in flight a prefix):"
    return [head] + lines if lines else []


def _calls(ops):
    return sum(_dict(op).get("n", 0) for op in _dict(ops).values())


def _ops_text(ops):
    return ", ".join(f"{op} {_dict(v).get('n', 0)} ({_dict(v).get('ms', 0) / 1000:.1f}s"
                     + (f", {v['err']} failed" if _dict(v).get("err") else "") + ")"
                     for op, v in _dict(ops).items())


def request_s3(sections):
    rows = _list(_dict(sections.get("requests")).get("in_flight"))
    lines = []
    for r in sorted(rows, key=lambda r: -(r.get("age_sec") or 0))[:SHOWN]:
        keys = r.get("query_keys") or []
        query = f" ?{','.join(keys)}" if keys else ""
        if r.get("s3") or query:
            lines.append(f"  {r.get('route')}{query}: {_ops_text(r.get('s3')) or 'no S3 calls'}")
    return ["In-flight requests' S3 calls:"] + lines if lines else []


def logs(sections):
    value = _dict(sections.get("logs"))
    lines = [f"  {c.get('count')} {c.get('level')} {c.get('logger')}"
             for c in _list(value.get("counts"))[:SHOWN]]
    for rec in _list(value.get("recent"))[-SHOWN:]:
        exc = f" ({rec['exc_type']})" if rec.get("exc_type") else ""
        lines.append(f"  {rec.get('level')} {rec.get('logger')}: {rec.get('message')}{exc}")
    return ["Logged warnings/errors:"] + lines if lines else []


def latency(sections):
    lines = []
    for key, label in (("event_loop", "event loop"), ("thread", "thread scheduling (GIL)")):
        probe = _dict(_dict(sections.get("latency")).get(key))
        if probe:
            stalled = "  STALLED" if (probe.get("max_ms") or 0) >= STALL_MS else ""
            lines.append(f"  {label} lag p95 {probe.get('p95_ms')}ms "
                         f"max {probe.get('max_ms')}ms{stalled}")
    return ["Responsiveness:"] + lines if lines else []


PARTS = (locks, background, request_s3, s3_kinds, s3_prefix_caps, logs, latency)
