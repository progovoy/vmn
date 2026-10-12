"""A process that keeps a log's sync state in memory (a notebook reusing its
storage, a live run) while other processes — in another clone of the repo or
the same one, under the same writer id — append to the run and its log
compacts on the remote once the run finished. Every line reaches the remote
once and every clone reads them all.
"""
import random

import pytest
from multi_clone_helpers import (
    APP,
    V,
    one_host_bucket,
    quietly,
    remote_tag_keys,
    stream,
    tag,
    view_tag_keys,
)
from s3_helpers import cached_host, meta
from vmn_exp.core.status import RUN_STATE_FILE

FINISHED = "state: finished\nexit_code: 0\n"


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _tag(host, step):
    own = stream(host)
    assert host.append_log_entry(APP, V, own, tag(step, f"k{step:02d}"))
    host.sync_log_to_remote(APP, V, own)


def _views(tmp_path, roots):
    return [view_tag_keys(cached_host(tmp_path, root)) for root in roots]


def test_a_clone_shipping_from_memory_after_another_compacted_loses_nothing(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    _tag(a, 0)
    a.save_file(APP, V, RUN_STATE_FILE, FINISHED)
    b = cached_host(tmp_path, "b")  # long-lived
    _tag(b, 1)
    _tag(cached_host(tmp_path, "a"), 2)  # a `vmn-exp tag`: the finished run's log compacts

    _tag(b, 3)

    keys = ["k00", "k01", "k02", "k03"]
    assert remote_tag_keys() == keys
    assert _views(tmp_path, "ab") == [keys, keys]


def test_a_process_shipping_from_memory_after_its_clone_compacted_loses_nothing(tmp_path):
    live = cached_host(tmp_path, "a")
    assert live.create_exclusive(APP, V, meta(V), {})
    _tag(live, 0)
    live.save_file(APP, V, RUN_STATE_FILE, FINISHED)
    _tag(cached_host(tmp_path, "a"), 1)  # another process of clone a compacts

    _tag(live, 2)

    assert remote_tag_keys() == ["k00", "k01", "k02"]
    assert _views(tmp_path, "a") == [["k00", "k01", "k02"]]


@pytest.mark.parametrize("seed", range(25))
def test_long_lived_and_one_shot_clones_after_the_run_finished_lose_nothing(
    tmp_path, seed
):
    rng = random.Random(seed)
    cached_host(tmp_path, "a").save(APP, V, meta(V), {})
    long_lived = cached_host(tmp_path, "c")
    tags = []
    for step in range(20):
        root = rng.choice("abc")
        host = long_lived if root == "c" else cached_host(tmp_path, root)
        text = f"{root}{step}-" + "z" * rng.choice([1, 5, 40])
        own = stream(host)
        if quietly(host.append_log_entry, APP, V, own, tag(step, f"k{step:02d}", text)):
            tags.append(f"k{step:02d}")
        quietly(host.sync_log_to_remote, APP, V, own)
        if step == 8:
            cached_host(tmp_path, "a").save_file(APP, V, RUN_STATE_FILE, FINISHED)
    long_lived.sync_log_to_remote(APP, V, stream(long_lived))
    for root in "abc":
        host = cached_host(tmp_path, root)
        host.sync_log_to_remote(APP, V, stream(host))

    assert remote_tag_keys() == sorted(tags)
    assert _views(tmp_path, "abc") == [sorted(tags)] * 3
