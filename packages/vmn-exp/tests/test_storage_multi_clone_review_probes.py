"""The reviewers' probes of the shared-stream fixes, kept as regressions: a
same-length line after a failed ship, one-shot turns of two clones with a
persisted index each, mixed reader kinds over one clone's index, and seals or
compactions whose drop of what they replaced fails, followed by a compaction
from a fresh clone — with a long-lived (UI-like) reader converging too."""
import random
from collections import Counter

import pytest
from multi_clone_helpers import (
    APP,
    LOG_CALLS,
    V,
    block,
    flaky,
    metric_values,
    one_host_bucket,
    quietly,
    remote_metric_values,
    remote_tag_keys,
    stream,
    tag,
    view_tag_keys,
)
from s3_helpers import cached_host, meta, s3_storage
from vmn_exp.core.index import ExperimentIndex, direct_rows
from vmn_exp.core.log import load_log
from vmn_exp.core.metric_compact import compact_record, compact_writer, seal_writer
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.snapshot import open_storage
from vmn_exp.ui.readers.parsed_logs import ParsedLogs

FINISHED = "state: finished\nexit_code: 0\n"


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _down(host):
    def fail(*a, **kw):
        raise RuntimeError("network down")

    for name in ("log_objects", "log_object_groups"):
        if hasattr(host._remote, name):
            setattr(host._remote, name, fail)


def test_same_length_lines_after_a_failed_ship_lose_no_entry(tmp_path):
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    assert a.append_log_entry(APP, V, stream(a), tag(1, "ka"))
    a.sync_log_to_remote(APP, V, stream(a))

    b = cached_host(tmp_path, "b")  # process 1: network down for the whole command
    _down(b)
    assert b.append_log_entry(APP, V, stream(b), tag(2, "kb"))  # as long as a's line
    with pytest.raises(RuntimeError):
        b.sync_log_to_remote(APP, V, stream(b))

    b = cached_host(tmp_path, "b")  # process 2: network back
    assert b.append_log_entry(APP, V, stream(b), tag(3, "kc"))
    b.sync_log_to_remote(APP, V, stream(b))

    assert remote_tag_keys() == ["ka", "kb", "kc"]


@pytest.mark.parametrize("seed", range(40))
def test_one_shot_turns_keep_each_entry_once_and_each_index_exact(tmp_path, seed):
    rng = random.Random(seed)
    cached_host(tmp_path, "a").save(APP, V, meta(V), {})
    appended = []
    caches = {r: str(tmp_path / f"idx-{r}.sqlite") for r in "ab"}
    for step in range(12):
        root = rng.choice("ab")
        host = cached_host(tmp_path, root)
        if rng.random() < 0.4:
            flaky(host, rng, 0.5, LOG_CALLS, lost_responses=False)
        text = f"{root}{step}-" + "z" * rng.choice([1, 5, 40, 200])
        own = quietly(stream, host)
        if own and quietly(host.append_log_entry, APP, V, own, tag(step, f"k{step:02d}", text)):
            appended.append(f"k{step:02d}")
        quietly(host.sync_log_to_remote, APP, V, own)
        if rng.random() < 0.5:  # a `vmn-exp list` on some root
            r = rng.choice("ab")
            quietly(lambda r=r: ExperimentIndex(cached_host(tmp_path, r), APP,
                                                cache_path=caches[r]).refresh())
    for r in "ab":  # the network is back: each clone ships once more
        host = cached_host(tmp_path, r)
        host.sync_log_to_remote(APP, V, stream(host))
    assert remote_tag_keys() == sorted(appended), "remote keeps each entry once"
    for r in "ab":
        host = cached_host(tmp_path, r)
        rows = ExperimentIndex(host, APP, cache_path=caches[r]).refresh().rows()
        assert rows == direct_rows(host, APP)[0], f"root {r} index"


def _offline(tmp_path):
    return open_storage(None, root=str(tmp_path / "b"), area="runs")


def _read(kind, tmp_path, cache):
    storage = cached_host(tmp_path, "b") if kind == "online" else _offline(tmp_path)
    index = ExperimentIndex(storage, APP, cache_path=cache)
    try:
        if kind == "helper":
            assert index.use_io_process()
        rows = index.refresh().rows()
    finally:
        index.close()
    return rows, direct_rows(storage, APP)[0]


@pytest.mark.parametrize("seed", range(40))
def test_every_reader_kind_over_one_clone_matches_a_direct_read(tmp_path, seed):
    rng = random.Random(seed)
    cached_host(tmp_path, "a").save(APP, V, meta(V), {})
    cache = str(tmp_path / "idx-b.sqlite")
    logs = ParsedLogs()
    for step in range(14):
        root = rng.choice("ab")
        host = cached_host(tmp_path, root)
        if rng.random() < 0.4:
            flaky(host, rng, 0.5, LOG_CALLS)
        own = quietly(stream, host)
        if own:
            quietly(host.append_log_entry, APP, V, own, tag(step, f"k{step:02d}", root))
            quietly(host.sync_log_to_remote, APP, V, own)
        if rng.random() < 0.6:
            kind = rng.choice(["online", "offline", "helper"])
            try:
                rows, truth = _read(kind, tmp_path, cache)
            except Exception:
                continue
            assert rows == truth, f"step {step} {kind}"
        if rng.random() < 0.5:
            off = _offline(tmp_path)
            if off.exists(APP, V):
                snap = logs.get(off, APP, V, load_log)
                assert snap.log() == load_log(off, APP, V), f"parsed logs step {step}"
    for kind in ("offline", "helper", "online"):
        rows, truth = _read(kind, tmp_path, cache)
        assert rows == truth, kind


def _fail_after_vmx_put(host, op, times):
    """*host*'s next *times* S3 *op* calls after a ``.vmx`` PUT fail."""
    client = host._remote._s3
    put, real = client.put_object, getattr(client, op)
    state = {"after": False, "n": 0}

    def put_object(*args, **kw):
        result = put(*args, **kw)
        if kw["Key"].endswith(".vmx"):
            state["after"] = True
        return result

    def failing(*args, **kw):
        if state["after"] and state["n"] < times:
            state["n"] += 1
            raise RuntimeError(f"blip {op}")
        return real(*args, **kw)

    client.put_object = put_object
    setattr(client, op, failing)


@pytest.mark.parametrize("compactor", ["b", "a"])
def test_a_seal_whose_drop_failed_then_a_compaction_reads_each_point_once(
        tmp_path, compactor):
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    a.append_metric_block(APP, V, stream(a), block(1.0))
    a.sync_metrics_to_remote(APP, V, stream(a))
    a = cached_host(tmp_path, "a")
    _fail_after_vmx_put(a, "list_objects_v2", 2)
    quietly(seal_writer, a, APP, V, stream(a))
    assert remote_metric_values() == [1.0]

    compact_record(cached_host(tmp_path, compactor), APP, V)

    assert remote_metric_values() == [1.0]
    assert metric_values(cached_host(tmp_path, "a")) == [1.0]
    assert metric_values(cached_host(tmp_path, "b")) == [1.0]


def _two_clones_shipped(tmp_path):
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    a.append_metric_block(APP, V, stream(a), block(1.0))
    a.sync_metrics_to_remote(APP, V, stream(a))
    b = cached_host(tmp_path, "b")
    b.append_metric_block(APP, V, stream(b), block(2.0, start=10))
    b.sync_metrics_to_remote(APP, V, stream(b))
    return cached_host(tmp_path, "b")


@pytest.mark.parametrize("op", ["list_objects_v2", "delete_objects"])
def test_an_end_of_run_compaction_whose_drop_failed_then_a_fresh_clones_reads_once(
        tmp_path, op):
    b = _two_clones_shipped(tmp_path)
    _fail_after_vmx_put(b, op, 2)
    quietly(compact_writer, b, APP, V, stream(b))
    assert remote_metric_values() == [1.0, 2.0]

    compact_record(cached_host(tmp_path, "c"), APP, V)  # vmn-exp compact, a fresh clone

    assert remote_metric_values() == [1.0, 2.0]
    assert metric_values(cached_host(tmp_path, "a")) == [1.0, 2.0]


SEAL_OPS = ("tag", "metrics", "metrics", "seal", "seal", "compact", "end", "list")


def _inject(host, rng, p):
    client = host._remote._s3
    for op in ("put_object", "get_object", "list_objects_v2", "delete_objects"):
        real = getattr(client, op)

        def call(*args, _real=real, _op=op, **kw):
            if "journal" in str(kw.get("Key", kw.get("Prefix", ""))) or rng.random() >= p:
                return _real(*args, **kw)
            if _op != "get_object" and _op != "list_objects_v2" and rng.random() < 0.5:
                _real(*args, **kw)
                raise RuntimeError(f"lost response {_op}")
            raise RuntimeError(f"blip {_op}")

        setattr(client, op, call)


def _seal_turn(tmp_path, step, rng, done):
    root = rng.choice("abc")
    host = cached_host(tmp_path, root)
    if rng.random() < 0.5:
        _inject(host, rng, 0.25)
    op = rng.choice(SEAL_OPS)
    own = quietly(stream, host)
    if op == "tag":
        if own and quietly(host.append_log_entry, APP, V, own, tag(step, f"k{step:02d}")):
            done["tags"].append(f"k{step:02d}")
        quietly(host.sync_log_to_remote, APP, V, own)
    elif op == "metrics":
        values = [float(step * 10 + i) for i in range(rng.choice([1, 2, 3]))]
        if own and quietly(host.append_metric_block, APP, V, own, block(*values, start=step * 10)):
            done["points"] += values
        quietly(host.sync_metrics_to_remote, APP, V, own)
    elif op == "seal":
        quietly(seal_writer, host, APP, V, own)
    elif op == "compact":
        quietly(compact_record, host, APP, V)
    elif op == "end":
        quietly(compact_writer, host, APP, V, own)
    else:
        cache = str(tmp_path / f"i{root}.sqlite")
        quietly(lambda: ExperimentIndex(host, APP, cache_path=cache).refresh())


@pytest.mark.parametrize("seed", range(40))
def test_seals_and_compactions_in_turns_with_a_long_lived_reader_converge(tmp_path, seed):
    rng = random.Random(seed)
    cached_host(tmp_path, "a").save(APP, V, meta(V), {})
    ui = s3_storage()
    done = {"tags": [], "points": []}
    for step in range(28):
        _seal_turn(tmp_path, step, rng, done)
        quietly(metric_values, ui)
        if step == 12:
            cached_host(tmp_path, "a").save_file(APP, V, RUN_STATE_FILE, FINISHED)
    for root in "abc":
        host = cached_host(tmp_path, root)
        host.sync_log_to_remote(APP, V, stream(host))
        host.sync_metrics_to_remote(APP, V, stream(host))
    points = sorted(done["points"])
    assert remote_tag_keys() == sorted(done["tags"])
    remote = remote_metric_values()
    assert remote == points, (sorted((Counter(remote) - Counter(points)).elements()),
                              sorted((Counter(points) - Counter(remote)).elements()))
    assert metric_values(ui) == points, "the long-lived reader"
    for root in "abc":
        host = cached_host(tmp_path, root)
        assert view_tag_keys(host) == sorted(done["tags"]), root
        assert metric_values(host) == points, root
    compact_record(cached_host(tmp_path, "b"), APP, V)
    assert remote_metric_values() == points, "after a last compaction"
