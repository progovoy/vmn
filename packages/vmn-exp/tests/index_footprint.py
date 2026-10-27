"""What one run costs a ``vmn-exp ui`` server in memory: a store of realistic
runs (10 user metrics logged per step, 10 ``sys_*`` metrics logged per
heartbeat, 20 params, 15 tags of which a few are 200-byte values repeated
across runs), indexed, restarted warm from the index file, and warmed the way
the server warms a board.

:func:`footprint` walks every part once (an object shared between parts
counts for the first one only) and gives each part's bytes per run.
"""
import random
import sys

from vmn_exp.core.index import ExperimentIndex
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

APP = "app"
SYS = ("sys_cpu_percent", "sys_rss_mb", "sys_gpu_mem_mb", "sys_gpu_node_mem_mb",
       "sys_gpu_node_util_percent", "sys_gpu0_util", "sys_gpu1_util", "sys_disk_mb",
       "sys_net_rx_mb", "sys_net_tx_mb")
USER = ("loss", "val_loss", "acc", "val_acc", "lr_now", "grad_norm", "f1", "precision",
        "recall", "epoch_time")
IMAGE = "registry.example.com/team/ml/train@sha256:" + "ab" * 32 + "/" + "x" * 70
STATE = ("state: finished\nexit_code: 0\ncommand: [python, train.py, --lr, '0.1']\n"
         "pid: 1000\nhost: node-{node}\n")
SNAPSHOT_PARTS = (
    "rows", "metric_parts", "outputs", "declared_defs", "features", "intents", "hypotheses",
    "system_metrics", "_by_verstr", "run_states", "edges", "create_notes",
    "run_state_observed_at",
)


def verstr(i):
    return f"0.0.1-dev.abc{i:06d}.r0"


def _ts(i, sub):
    return f"2026-01-01T{i // 3600 % 24:02d}:{i // 60 % 60:02d}:{i % 60:02d}.{sub:06d}Z"


def _tags(i, v):
    return {
        "pod.image": IMAGE, "container.image": IMAGE,
        "profile": "gpu-large-" + "p" * 190, "nodeSelector": "pool=a100," + "n" * 190,
        "log_uri": f"s3://bucket/logs/{v}/" + "l" * 150,
        "node.name": f"node-{i % 50}.cluster.local", "team": "ml", "owner": "alice",
        "queue": "default", "priority": "5", "zone": "us-east-1a", "job": f"job-{i}",
        "attempt": "1", "kind": "train", "dataset": "imagenet",
    }


def _entries(i, v, rnd):
    params = {f"p{k}": rnd.random() for k in range(12)}
    params.update({f"s{k}": f"value-{k}-{i % 7}" for k in range(8)})
    entries = [{"timestamp": _ts(i, 1), "type": "create", "params": params,
                "tags": _tags(i, v)}]
    entries += [{"timestamp": _ts(i, 10 + step), "type": "metrics", "step": step,
                 "values": {m: rnd.random() for m in USER}} for step in range(5)]
    entries += [{"timestamp": _ts(i, 100 + beat), "type": "metrics",
                 "values": {m: rnd.random() * 2000 for m in SYS}} for beat in range(10)]
    return entries


def seed(st, n):
    rnd = random.Random(1)
    for i in range(n):
        v = verstr(i)
        st.save(APP, v, {
            "verstr": v, "code_verstr": "0.0.1-dev.abc", "timestamp": _ts(i, 0),
            "branch": "main", "base_version": "0.0.1",
            "env": {"python": "3.12.1", "platform": "Linux/x86_64", "packages_count": 312,
                    "packages_sha": "f" * 64, "key_packages": {"torch": "2.4.0"}},
        }, {})
        st.save_file(APP, v, "run_state.yml", STATE.format(node=i % 50))
        for entry in _entries(i, v, rnd):
            st.append_log_entry(APP, v, "w", entry)


def warm_server(tmp_path, n):
    """``(index, snapshot, cache)`` of *n* seeded runs after a warm restart,
    the board warmed."""
    st = LocalSnapshotStorage(str(tmp_path / "repo"), area="runs")
    seed(st, n)
    db = str(tmp_path / "idx.sqlite")
    first = ExperimentIndex(st, APP, cache_path=db)
    first.refresh()
    first.close()
    index = ExperimentIndex(st, APP, cache_path=db)
    index.refresh()
    snap = index.snapshot()
    cache = LeaderboardCache()
    cache.warm(snap)
    return index, snap, cache


class _Sizer:
    """Deep ``sys.getsizeof``; an object is counted the first time it is met."""

    def __init__(self, *shared):
        self.seen = {id(o) for o in shared}

    def size(self, obj):
        total, stack = 0, [obj]
        while stack:
            o = stack.pop()
            if id(o) in self.seen or isinstance(o, (type, bool)) or o is None:
                continue
            self.seen.add(id(o))
            if callable(o) and not isinstance(o, (dict, list, tuple)):
                continue
            total += sys.getsizeof(o)
            stack.extend(_referents(o))
        return total


def _referents(o):
    if isinstance(o, dict):
        return list(dict.keys(o)) + list(dict.values(o)) + _slots(o)
    if isinstance(o, (list, tuple, set, frozenset)):
        return list(o)
    if isinstance(o, (str, bytes, int, float)):
        return []
    return ([o.__dict__] if hasattr(o, "__dict__") else []) + _slots(o)


def _slots(o):
    # dict.keys: a LazyRecord's own keys() would decode it.
    return [getattr(o, slot) for slot in getattr(type(o), "__slots__", ())
            if hasattr(o, slot)]


def footprint(index, snap, cache, n):
    """``{part: bytes per run}`` of what the warm server holds."""
    sizer = _Sizer(snap.app_name, index._lock if hasattr(index, "_lock") else None)
    parts = {name: sizer.size(getattr(snap, name, {})) for name in SNAPSHOT_PARTS}
    parts["index (records, row cache)"] = sizer.size(index.__dict__)
    parts["board base"] = sizer.size(cache._base(snap)[0].__dict__)
    parts["facets"] = sizer.size(cache._facets.__dict__)
    parts["search index"] = sizer.size(cache._search.__dict__)
    parts["rest of the board cache"] = sizer.size(cache.__dict__)
    return {name: size / n for name, size in parts.items()}


def report(parts):
    lines = [f"{name:28s} {size:8.0f} B/run" for name, size in parts.items()]
    return "\n".join(lines + [f"{'total':28s} {sum(parts.values()):8.0f} B/run"])
