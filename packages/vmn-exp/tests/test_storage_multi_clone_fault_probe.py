"""Three clones, one writer id, one S3 store: random one-shot commands (tag,
add metrics, `vmn-exp compact`, a stream's own compaction or seal, index
refresh) while any S3 request may fail before it is sent or after it took
effect (a lost response), the run finishing midway. With *strict* reads, a
failed GET or ranged read raises instead of reading as missing. Once the
network is back and every clone shipped, the remote holds every entry and
point exactly once and every clone reads them all.
"""
import random
from collections import Counter

import pytest
from multi_clone_helpers import (
    APP,
    V,
    block,
    metric_values,
    one_host_bucket,
    quietly,
    remote_metric_values,
    remote_tag_keys,
    stream,
    tag,
    view_tag_keys,
)
from s3_helpers import cached_host, meta
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.metric_compact import compact_record, compact_writer, seal_writer
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage.s3_base import S3Base, error_code
from vmn_exp.storage.s3_metrics import S3Metrics

OPS = ("put_object", "get_object", "list_objects_v2", "delete_objects", "head_object",
       "delete_object")
_WRITES = ("put_object", "delete_objects", "delete_object")
COMMANDS = ("tag", "tag", "metrics", "metrics", "compact", "end", "seal", "list")
FINISHED = "state: finished\nexit_code: 0\n"


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _strict_read_range(self, app_name, verstr, name, offset, length):
    if length <= 0:
        return b""
    key = f"{self._record_prefix(app_name, verstr)}/{name}"
    try:
        return self._s3.get_object(Bucket=self.bucket, Key=key,
                                   Range=f"bytes={offset}-{offset + length - 1}")["Body"].read()
    except Exception as e:
        if error_code(e) in ("416", "InvalidRange"):
            return b""
        if error_code(e) in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def _inject(host, rng, p):
    client = host._remote._s3
    for op in OPS:
        real = getattr(client, op)

        def call(*args, _real=real, _op=op, **kw):
            if "journal" in str(kw.get("Key", kw.get("Prefix", ""))) or rng.random() >= p:
                return _real(*args, **kw)
            if _op in _WRITES and rng.random() < 0.5:
                _real(*args, **kw)
                raise RuntimeError(f"lost response {_op}")
            raise RuntimeError(f"blip {_op}")

        setattr(client, op, call)


def _host(tmp_path, root, rng):
    host = cached_host(tmp_path, root)
    if rng.random() < 0.5:
        _inject(host, rng, 0.25)
    return host


def _command(tmp_path, step, rng, done):
    root = rng.choice("abc")
    host = _host(tmp_path, root, rng)
    command = rng.choice(COMMANDS)
    own = quietly(stream, host)
    if command == "tag":
        text = f"{root}{step}-" + "z" * rng.choice([1, 5, 40])
        if own and quietly(host.append_log_entry, APP, V, own, tag(step, f"k{step:02d}", text)):
            done["tags"].append(f"k{step:02d}")
        quietly(host.sync_log_to_remote, APP, V, own)
    elif command == "metrics":
        values = [float(step * 10 + i) for i in range(rng.choice([1, 2, 3]))]
        if own and quietly(host.append_metric_block, APP, V, own, block(*values, start=step * 10)):
            done["points"] += values
        quietly(host.sync_metrics_to_remote, APP, V, own)
    elif command == "compact":
        quietly(compact_record, host, APP, V)
    elif command == "end":
        quietly(compact_writer, host, APP, V, own)
    elif command == "seal":
        quietly(seal_writer, host, APP, V, own)
    else:
        cache = str(tmp_path / f"idx-{root}.sqlite")
        quietly(lambda: ExperimentIndex(host, APP, cache_path=cache).refresh())


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("seed", range(80))
def test_clones_under_s3_faults_keep_every_entry_and_point_exactly_once(
        tmp_path, monkeypatch, seed, strict):
    if strict:
        monkeypatch.setattr(S3Metrics, "read_range", _strict_read_range)
        monkeypatch.setattr(S3Base, "_get", S3Base._get_or_raise)
    rng = random.Random(seed)
    cached_host(tmp_path, "a").save(APP, V, meta(V), {})
    done = {"tags": [], "points": []}
    for step in range(24):
        _command(tmp_path, step, rng, done)
        if step == 10:
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
    for root in "abc":
        host = cached_host(tmp_path, root)
        assert view_tag_keys(host) == sorted(done["tags"]), root
        assert metric_values(host) == points, root
    compact_record(cached_host(tmp_path, "b"), APP, V)  # a last `vmn-exp compact`
    assert remote_metric_values() == points
