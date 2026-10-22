#!/usr/bin/env python3
"""A short human summary of a ``vmn-exp ui`` diagnostic dump: top thread
stacks, the slowest in-flight requests, pool saturation, index loading,
S3 latency, and the newer sections' parts (:mod:`diag_summary_more`).
Every section is optional and may be shaped differently or hold
an ``error``; a part that cannot be read is skipped, never fatal."""
from collections import Counter

from vmn_exp.ui import diag_summary_more

TOP_STACKS = 5
STACK_FRAMES = 4
THREAD_NAMES = 4
SLOWEST = 5


def summarize(dump):
    dump = dump if isinstance(dump, dict) else {}
    sections = dump.get("sections")
    sections = sections if isinstance(sections, dict) else {}
    lines = [f"vmn-exp ui diag: pid {dump.get('pid', '?')} at {dump.get('taken_at', '?')}"
             f" ({len(sections)} sections)"]
    for name, value in sections.items():
        if isinstance(value, dict) and value.get("error"):
            lines.append(f"section {name} failed: {value['error']}")
    for part in (_stacks, _requests, _pools, _index, _s3, *diag_summary_more.PARTS):
        try:
            lines += part(sections)
        except Exception:  # an odd shape skips its part, never the summary
            pass
    return "\n".join(lines)


def _frames(stack):
    if isinstance(stack, str):
        return stack.splitlines()
    return [line for frame in stack for line in str(frame).rstrip("\n").splitlines()]


def _is_stdlib(line):
    return "/lib/python3" in line and "site-packages" not in line


def _shown_frames(stack):
    """The innermost :data:`STACK_FRAMES` frames outside the stdlib (its
    waits say only that a thread waits), each its ``File`` line + code."""
    frames = []
    for line in stack:
        if line.lstrip().startswith("File ") or not frames:
            frames.append([line])
        else:
            frames[-1].append(line)
    ours = [f for f in frames if not _is_stdlib(f[0])] or frames
    return [line for frame in ours[-STACK_FRAMES:] for line in frame]


def _names(threads):
    names = [t.get("name") for t in threads or [] if isinstance(t, dict) and t.get("name")]
    more = f", +{len(names) - THREAD_NAMES}" if len(names) > THREAD_NAMES else ""
    return f" ({', '.join(names[:THREAD_NAMES])}{more})" if names else ""


def _stacks(sections):
    counts, names = Counter(), {}
    threads = sections.get("threads")
    groups = threads.get("groups") if isinstance(threads, dict) else None
    for g in _items(groups):
        key = tuple(_frames(g["stack"]))
        counts[key] += int(g.get("count", 1))
        names.setdefault(key, []).extend(g.get("threads") or [])
    for t in _items(threads):
        key = tuple(_frames(t["stack"]))
        counts[key] += 1
        names.setdefault(key, []).append(t)
    for s in _items(sections.get("stacks")):
        counts[tuple(_frames(s["stack"]))] += int(s.get("count", 1))
    if not counts:
        return []
    lines = ["Top stacks:"]
    for stack, n in counts.most_common(TOP_STACKS):
        lines.append(f"  {n} threads{_names(names.get(stack))}")
        lines += [f"      {frame}" for frame in _shown_frames(stack)]
    return lines


def _items(value):
    return [v for v in value if isinstance(v, dict) and "stack" in v] if isinstance(
        value, list) else []


def _age_ms(request):
    for key, scale in (("age_ms", 1), ("elapsed_ms", 1), ("age_sec", 1000), ("age_s", 1000),
                       ("elapsed_s", 1000)):
        if isinstance(request.get(key), (int, float)):
            return request[key] * scale
    return 0


def _requests(sections):
    value = sections.get("requests")
    rows = value.get("in_flight") if isinstance(value, dict) else value
    rows = [r for r in rows or [] if isinstance(r, dict)]
    if not rows:
        return []
    rows.sort(key=_age_ms, reverse=True)
    lines = [f"Slowest in-flight requests ({len(rows)} in flight):"]
    for r in rows[:SLOWEST]:
        wait = r.get("queue_wait_sec")
        queued = f"  (queued {wait:.1f}s)" if isinstance(wait, (int, float)) else ""
        lines.append(f"  {_age_ms(r) / 1000:.1f}s  {r.get('method', '')} "
                     f"{r.get('route') or r.get('path', '')}{queued}")
    return lines


def _first(entry, *keys):
    return next((entry[k] for k in keys if isinstance(entry.get(k), (int, float))), None)


def _pools(sections):
    value = sections.get("pools")
    if isinstance(value, list):
        value = {p.get("name", str(i)): p for i, p in enumerate(value) if isinstance(p, dict)}
    if not isinstance(value, dict):
        return []
    lines = []
    for name, pool in value.items():
        if not isinstance(pool, dict):
            continue
        size = _first(pool, "total", "max_workers", "max", "size", "max_size")
        busy = _first(pool, "borrowed", "active", "busy", "in_use", "running")
        queued = _first(pool, "waiting", "queued", "pending")
        flag = "  SATURATED" if size and busy is not None and busy >= size else ""
        lines.append(f"  {name}: {busy if busy is not None else '?'}/{size or '?'} busy"
                     f", {queued if queued is not None else '?'} waiting{flag}")
    return ["Pools:"] + lines if lines else []


def _loading(value, path=""):
    if isinstance(value, dict):
        if value.get("loading"):
            yield path or "index", value["loading"]
        for key, inner in value.items():
            if key != "loading":
                yield from _loading(inner, f"{path}/{key}" if path else str(key))


def _loading_text(loading):
    if isinstance(loading, dict):
        loading = (loading.get("loaded"), loading.get("total"))
    if isinstance(loading, (list, tuple)) and len(loading) == 2:
        return f"{loading[0]}/{loading[1]} loaded"
    return str(loading)


def _index(sections):
    indexes = sections.get("indexes")
    watched = indexes.get("watched") if isinstance(indexes, dict) else None
    found = [(w.get("app") or "index", w["loading"]) for w in watched or []
             if isinstance(w, dict) and w.get("loading")]
    found += list(_loading(sections.get("index")))
    if not found:
        return []
    return ["Index loading:"] + [f"  {name}: {_loading_text(v)}" for name, v in found]


def _s3(sections):
    s3 = sections.get("s3")
    if not isinstance(s3, dict) or not isinstance(s3.get("operations"), dict):
        return []
    ops = sorted(s3["operations"].items(),
                 key=lambda kv: -(kv[1].get("latency_ms") or {}).get("p95", 0))
    lines = [f"S3 ({s3.get('clients_created', '?')} clients, pool "
             f"{s3.get('max_pool_connections', '?')}):"]
    for name, op in ops:
        lat = op.get("latency_ms") or {}
        errors = ", ".join(f"{k}={v}" for k, v in (op.get("errors") or {}).items())
        lines.append(f"  {name}: {op.get('count', 0)} calls, p50 {lat.get('p50', '?')}ms"
                     f" p95 {lat.get('p95', '?')}ms max {lat.get('max', '?')}ms,"
                     f" {op.get('in_flight', 0)} in flight, {op.get('retries', 0)} retries"
                     + (f", errors {errors}" if errors else ""))
    for c in (s3.get("clients") or [])[:SLOWEST]:
        if c.get("in_flight"):
            lines.append(f"  client {c.get('client')}: {c['in_flight']}/"
                         f"{c.get('max_pool_connections', '?')} connections in flight")
    for r in (s3.get("in_flight") or [])[:SLOWEST]:
        lines.append(f"  in flight {r.get('age_ms', 0) / 1000:.1f}s  "
                     f"{r.get('operation', '')} {r.get('key') or r.get('path', '')}")
    return lines
