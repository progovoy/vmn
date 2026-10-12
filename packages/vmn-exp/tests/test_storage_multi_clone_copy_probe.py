"""Three roots of one host over a finished run (so every log ship compacts
too), random ``cp -r`` copies, ``prune --local-only``, a straight-to-bucket
log buffer, flaky S3 with lost responses and compaction from any root. Once
every root shipped, the remote holds each entry and point once and every
root reads them all."""
import random
import shutil

import pytest
from multi_clone_helpers import (
    APP,
    LOG_CALLS,
    METRIC_CALLS,
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
    tag_keys,
)
from s3_helpers import cached_host, meta, s3_storage
from vmn_exp.core.metric_compact import compact_record, compact_writer
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage.buffered import BufferedRemoteStorage

FINISHED = "state: finished\nexit_code: 0\n"


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _ship(host):
    own = stream(host)
    host.sync_log_to_remote(APP, V, own)
    host.sync_metrics_to_remote(APP, V, own)


class _Probe:
    def __init__(self, tmp_path, rng):
        self.tmp, self.rng = tmp_path, rng
        self.roots, self.live, self.keys, self.values = ["a", "b", "c"], {}, [], []
        self.buf = BufferedRemoteStorage(s3_storage())

    def step(self, step):
        op, root = self.rng.random(), self.rng.choice(self.roots)
        if op < 0.08 and root in self.live:
            self.live.pop(root)  # its process ends
        elif op < 0.13:
            _ship(cached_host(self.tmp, root))  # then prune --local-only
            self.live.pop(root, None)
            shutil.rmtree(self.tmp / root, ignore_errors=True)
        elif op < 0.17 and (self.tmp / root).exists():
            shutil.copytree(self.tmp / root, self.tmp / f"{root}{step}")
            self.roots.append(f"{root}{step}")
        elif op < 0.24:
            self.compact(root)
        elif op < 0.30:
            self.append(self.buf, step, f"buf{step}", 1)
        else:
            self.record(root, step)

    def compact(self, root):
        host = cached_host(self.tmp, root)
        if self.rng.random() < 0.5:
            flaky(host, self.rng, 0.4, METRIC_CALLS)
        if self.rng.random() < 0.5:
            quietly(compact_record, host, APP, V)
        else:
            quietly(lambda: compact_writer(host, APP, V, stream(host)))

    def record(self, root, step):
        if root in self.live and self.rng.random() < 0.7:
            host = self.live[root]
        else:
            host = cached_host(self.tmp, root)
            if self.rng.random() < 0.5:
                flaky(host, self.rng, 0.4, LOG_CALLS + METRIC_CALLS)
            if self.rng.random() < 0.5:
                self.live[root] = host
        if self.append(host, step, f"k{step}", self.rng.choice([1, 3])) and \
                self.rng.random() < 0.6:
            quietly(_ship, host)

    def append(self, host, step, key, n):
        own = quietly(stream, host)
        if not own:
            return False
        if quietly(host.append_log_entry, APP, V, own, tag(step, key)):
            self.keys.append(key)
        values = [float(step * 10 + i) for i in range(n)]
        if quietly(host.append_metric_block, APP, V, own, block(*values, start=step * 10)):
            self.values += values
        return True

    def existing(self):
        return [r for r in self.roots if (self.tmp / r).exists()]


@pytest.mark.parametrize("seed", range(60))
def test_every_entry_and_point_lands_once_from_copies_of_finished_roots(tmp_path, seed):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    a.save_file(APP, V, RUN_STATE_FILE, FINISHED)
    probe = _Probe(tmp_path, random.Random(seed))
    for step in range(30):
        probe.step(step)
    probe.buf.close()
    for root in probe.existing():
        _ship(cached_host(tmp_path, root))

    assert remote_tag_keys() == sorted(probe.keys)
    assert remote_metric_values() == sorted(probe.values)
    for root in probe.existing():
        host = cached_host(tmp_path, root)
        assert tag_keys(host.load_merged_log(APP, V)) == sorted(probe.keys), root
        assert metric_values(host) == sorted(probe.values), root
