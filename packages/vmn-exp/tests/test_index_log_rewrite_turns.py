"""Two clones on one host (one writer id) take turns appending to a run over one
S3 store, some of their remote calls failing, while `vmn-exp list` runs on
either clone now and then. However their streams ship and readers switch
between local and remote copies, each clone's persisted index ends equal to
a full read of its storage.
"""
import random

import pytest
from s3_helpers import cached_host, meta, mocked_bucket
from vmn_exp.core.index import ExperimentIndex, direct_rows
from vmn_exp.core.writer import own_stream
from vmn_exp.storage import buffered

APP = "app"
V = "0.0.1-dev.aaa1111.bbb2222"
W = "h"


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield
        buffered.close_all()


def _flaky(host, rng, p):
    """Each of *host*'s remote log listings, saves and loads fails with *p*."""
    for name in ("log_objects", "log_object_groups", "save_file", "create_log_segment",
                 "load_file"):
        real = getattr(host._remote, name)

        def call(*args, _real=real, **kw):
            if rng.random() < p:
                raise RuntimeError("blip")
            return _real(*args, **kw)

        setattr(host._remote, name, call)


def _tag(step, root, rng):
    text = f"{root}{step}-" + "z" * rng.choice([1, 5, 40, 200])
    return {"timestamp": f"2026-01-01T00:00:{step:02d}Z", "type": "tags",
            "set": {f"k{step}": text}}


def _one_shot_append(tmp_path, root, step, rng):
    host = cached_host(tmp_path, root)
    if rng.random() < 0.4:
        _flaky(host, rng, 0.5)
    try:
        host.append_log_entry(APP, V, own_stream(host, APP, V), _tag(step, root, rng))
        host.sync_log_to_remote(APP, V, own_stream(host, APP, V))
    except Exception:
        pass  # the network is down: the next command ships it


@pytest.mark.parametrize("seed", range(30))
def test_each_clones_persisted_index_equals_a_full_read(tmp_path, seed):
    rng = random.Random(seed)
    cached_host(tmp_path, "a").save(APP, V, meta(V), {})
    caches = {root: str(tmp_path / f"idx-{root}.sqlite") for root in "ab"}
    for step in range(12):
        _one_shot_append(tmp_path, rng.choice("ab"), step, rng)
        if rng.random() < 0.5:
            root = rng.choice("ab")
            ExperimentIndex(cached_host(tmp_path, root), APP,
                            cache_path=caches[root], full_sweep_sec=0).refresh()
    for root in "ab":
        host = cached_host(tmp_path, root)
        host.sync_log_to_remote(APP, V, own_stream(host, APP, V))

    for root in "ab":
        host = cached_host(tmp_path, root)
        # The other clone's lines arrive through the remote, which signs no
        # record: compared at a full listing.
        rows = ExperimentIndex(host, APP, cache_path=caches[root],
                               full_sweep_sec=0).refresh().rows()
        assert rows == direct_rows(host, APP)[0], f"clone {root}"
