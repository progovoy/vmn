"""Two clones on one host (one writer id) take turns running one-shot commands
that append to a run over one S3 store — each a new process — while their
remote calls fail now and then, an upload sometimes landing with its response
lost, `vmn-exp list` runs on either clone, and at some point the run finishes
(its log then compacts on the remote). Once the network is back and each
clone shipped, the remote holds every appended entry exactly once, each clone
reads them all, and each clone's persisted index equals a full read.
"""
import random

import pytest
from multi_clone_helpers import (
    APP,
    LOG_CALLS,
    V,
    flaky,
    one_host_bucket,
    quietly,
    remote_tag_keys,
    stream,
    tag,
    view_tag_keys,
)
from s3_helpers import cached_host, meta
from vmn_exp.core.index import ExperimentIndex, direct_rows
from vmn_exp.core.status import RUN_STATE_FILE

FINISHED = "state: finished\nexit_code: 0\n"


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _command(tmp_path, root, step, rng):
    """A one-shot command in *root* appending one entry; True if it was logged."""
    host = cached_host(tmp_path, root)
    if rng.random() < 0.4:
        flaky(host, rng, 0.5, LOG_CALLS)
    text = f"{root}{step}-" + "z" * rng.choice([1, 5, 40, 200])
    own = quietly(stream, host)
    logged = own and quietly(host.append_log_entry, APP, V, own,
                             tag(step, f"k{step:02d}", text))
    quietly(host.sync_log_to_remote, APP, V, own)
    return logged


def _list(tmp_path, root):
    host = cached_host(tmp_path, root)
    return ExperimentIndex(host, APP, cache_path=str(tmp_path / f"idx-{root}.sqlite"))


@pytest.mark.parametrize("seed", range(60))
def test_clones_taking_turns_keep_every_entry_exactly_once(tmp_path, seed):
    rng = random.Random(seed)
    cached_host(tmp_path, "a").save(APP, V, meta(V), {})
    finish_at = rng.randrange(4, 16)
    appended = []
    for step in range(16):
        if _command(tmp_path, rng.choice("ab"), step, rng):
            appended.append(f"k{step:02d}")
        if rng.random() < 0.4:
            quietly(lambda: _list(tmp_path, rng.choice("ab")).refresh())
        if step == finish_at:
            cached_host(tmp_path, "a").save_file(APP, V, RUN_STATE_FILE, FINISHED)

    for root in "ab":  # the network is back: each clone ships once more
        host = cached_host(tmp_path, root)
        host.sync_log_to_remote(APP, V, stream(host))

    assert remote_tag_keys() == appended, "the remote keeps each entry once"
    for root in "ab":
        host = cached_host(tmp_path, root)
        assert view_tag_keys(host) == appended, f"clone {root} reads every entry"
        rows = _list(tmp_path, root).refresh().rows()
        assert rows == direct_rows(host, APP)[0], f"clone {root}'s index"
