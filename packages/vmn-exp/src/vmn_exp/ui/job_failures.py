#!/usr/bin/env python3
"""A job's failure clusters (plan 23 S3): the rollup's failure-signature
counts, each with what its runs share — when they ended, on which hosts,
and the params overrepresented among them against the whole job (``opt =
big`` in 80% of the cluster vs 20% of the job). Pure: counts and rows in.
"""
from collections import Counter

from vmn_exp.ui.failure_signature import label, signature

TOP_HOSTS = 5
TOP_PARAMS = 5
# A param is reported when this many of the cluster's runs carry it, and it
# is this many times as common in the cluster as in the job.
MIN_SUPPORT = 2
MIN_LIFT = 1.25


def _pairs(row):
    """The row's scalar params as hashable ``(key, value)`` pairs."""
    for key, value in (row.get("params") or {}).items():
        if isinstance(value, (str, int, float)):  # bools are ints
            yield key, type(value) is bool, value


def _ended(row):
    return row.get("finished_at") or row.get("heartbeat")


def _params(members, base, total):
    size = len(members)
    counts = Counter(pair for row in members for pair in _pairs(row))
    found = []
    for pair, count in counts.items():
        share, base_share = count / size, base[pair] / total
        if count >= MIN_SUPPORT and share >= MIN_LIFT * base_share:
            found.append((share / base_share, share, pair))
    found.sort(key=lambda f: (-f[0], -f[1], f[2][0], str(f[2][2])))
    return [{"key": key, "value": value, "share": round(share, 4),
             "base_share": round(base[(key, flag, value)] / total, 4)}
            for _, share, (key, flag, value) in found[:TOP_PARAMS]]


def _cluster(sig, count, total_failed, members, base, total):
    hosts = Counter(row["host"] for row in members if row.get("host"))
    ends = sorted((_ended(row) or "", row["verstr"]) for row in members)
    stamps = [stamp for stamp, _ in ends if stamp]
    return {
        "sig": sig, "label": label(sig), "count": count,
        "share": count / total_failed,
        "first_at": stamps[0] if stamps else None,
        "last_at": stamps[-1] if stamps else None,
        "hosts": [{"host": h, "count": n}
                  for h, n in sorted(hosts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_HOSTS]],
        "params": _params(members, base, total) if members else [],
        "example_verstr": ends[-1][1] if ends else None,
    }


def failure_clusters(counts, rows, limit):
    """``{total_failed, clusters}``: the *limit* largest of *counts*
    (``{signature: runs}``), detailed from the job's *rows*."""
    total_failed = sum(counts.values())
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:max(0, limit)]
    wanted = {sig: [] for sig, _ in top}
    for row in rows:
        sig = signature(row)
        if sig in wanted:
            wanted[sig].append(row)
    base = Counter(pair for row in rows for pair in _pairs(row)) if top else Counter()
    total = len(rows)
    return {"total_failed": total_failed, "clusters": [
        _cluster(sig, count, total_failed, wanted[sig], base, total) for sig, count in top]}
