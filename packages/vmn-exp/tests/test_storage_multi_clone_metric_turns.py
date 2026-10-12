"""Two clones on one host (one writer id) take turns adding metric points to a
run over one S3 store — each command a new process — while their remote calls
fail now and then (an upload sometimes landing with its response lost),
`vmn-exp list` runs on either clone and, in the second test, either clone
compacts the run's metrics (`vmn-exp compact`) or the run's own stream (its
end). Once the network is back and each clone shipped, the remote holds every
point exactly once and each clone reads them all; an index over either clone
equals a full read once the record next changes in its listing (S3 listings
carry no metric objects, so a clone's index learns of points only another
clone shipped then, as it does of another host's).
"""
import random

import pytest
from multi_clone_helpers import (
    APP,
    METRIC_CALLS,
    V,
    block,
    flaky,
    metric_values,
    one_host_bucket,
    quietly,
    remote_metric_values,
    stream,
)
from s3_helpers import cached_host, meta
from vmn_exp.core.index import ExperimentIndex, direct_rows
from vmn_exp.core.metric_compact import compact_record, compact_writer


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _host(tmp_path, root, rng):
    host = cached_host(tmp_path, root)
    if rng.random() < 0.4:
        flaky(host, rng, 0.5, METRIC_CALLS)
    return host


def _add(tmp_path, root, step, rng):
    """A one-shot `add --metrics` in *root*; its values if it recorded them."""
    host = _host(tmp_path, root, rng)
    values = [float(step * 10 + i) for i in range(rng.choice([1, 2, 5]))]
    own = quietly(stream, host)
    added = own and quietly(host.append_metric_block, APP, V, own,
                            block(*values, start=step * 10))
    quietly(host.sync_metrics_to_remote, APP, V, own)
    return values if added else []


def _compact(host, rng):
    if rng.random() < 0.5:
        quietly(compact_record, host, APP, V)
    else:
        quietly(lambda: compact_writer(host, APP, V, stream(host)))


def _index(tmp_path, root):
    return ExperimentIndex(cached_host(tmp_path, root), APP,
                           cache_path=str(tmp_path / f"idx-{root}.sqlite"))


def _take_turns(tmp_path, seed, compactions):
    rng = random.Random(seed)
    cached_host(tmp_path, "a").save(APP, V, meta(V), {})
    added = []
    for step in range(14):
        added += _add(tmp_path, rng.choice("ab"), step, rng)
        if rng.random() < 0.4:
            quietly(lambda: _index(tmp_path, rng.choice("ab")).refresh())
        if rng.random() < compactions:
            _compact(_host(tmp_path, rng.choice("ab"), rng), rng)
    for root in "ab":  # the network is back: each clone ships once more
        host = cached_host(tmp_path, root)
        host.sync_metrics_to_remote(APP, V, stream(host))
    return sorted(added)


def _assert_converged(tmp_path, added):
    assert remote_metric_values() == added, "the remote keeps each point once"
    for root in "ab":
        assert metric_values(cached_host(tmp_path, root)) == added, f"clone {root} reads all"
    for step, root in enumerate("ab", start=100):  # the record changes in its listing
        host = cached_host(tmp_path, root)
        assert host.append_metric_block(APP, V, stream(host), block(float(step), start=step * 10))
        host.sync_metrics_to_remote(APP, V, stream(host))
        rows = _index(tmp_path, root).refresh().rows()
        assert rows == direct_rows(host, APP)[0], f"clone {root}'s index"


@pytest.mark.parametrize("seed", range(40))
def test_clones_taking_turns_ship_every_point_exactly_once(tmp_path, seed):
    added = _take_turns(tmp_path, seed, compactions=0)
    _assert_converged(tmp_path, added)


@pytest.mark.parametrize("seed", range(40))
def test_clones_compacting_in_turns_keep_every_point_exactly_once(tmp_path, seed):
    added = _take_turns(tmp_path, seed, compactions=0.25)
    _assert_converged(tmp_path, added)
