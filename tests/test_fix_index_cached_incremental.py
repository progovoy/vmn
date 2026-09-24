"""The experiment index over local+remote storage folds incrementally: a poll
reads only new local bytes and new remote segments, and always folds to what a
full re-read would."""
import random

import pytest
import yaml
from s3_helpers import cached_host, entry, meta, mocked_bucket, s3_storage

from version_stamp.core.experiment_index import ExperimentIndex, direct_rows

APP = "app"


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield


def _log_gets(host):
    keys = []
    client = host._remote._s3
    real = client.get_object

    def get_object(**kwargs):
        if "/log." in kwargs["Key"]:
            keys.append(kwargs["Key"].rsplit("/", 1)[1])
        return real(**kwargs)

    client.get_object = get_object
    return keys


def _local_reads(host):
    reads = []
    local = host._local
    real_from, real_load = local.read_file_from, local.load_file

    def read_file_from(app, verstr, name, offset):
        reads.append((name, offset))
        return real_from(app, verstr, name, offset)

    def load_file(app, verstr, name):
        if name.startswith("log."):
            reads.append((name, 0))
        return real_load(app, verstr, name)

    local.read_file_from, local.load_file = read_file_from, load_file
    return reads


def _two_hosts_one_record(tmp_path):
    a, b = cached_host(tmp_path, "a"), cached_host(tmp_path, "b")
    a.save(APP, "v", meta("v"), {})
    a.append_log_entry(APP, "v", "wa", entry(0))
    b.append_log_entry(APP, "v", "wb", entry(1))
    b.sync_log_to_remote(APP, "v", "wb")
    return a, b


def test_a_cached_storage_with_a_remote_is_read_per_file(tmp_path):
    a, _ = _two_hosts_one_record(tmp_path)
    assert a.direct_files() is not None


def test_a_new_remote_segment_is_the_only_remote_log_read(tmp_path):
    a, b = _two_hosts_one_record(tmp_path)
    index = ExperimentIndex(a, APP).refresh()
    gets = _log_gets(a)
    b.append_log_entry(APP, "v", "wb", entry(2))
    b.sync_log_to_remote(APP, "v", "wb")
    index.refresh()
    assert gets == ["log.wb@000001.jsonl"]
    assert index.rows()[0]["metrics"] == {"i": 2}


def test_local_growth_reads_only_the_new_bytes(tmp_path):
    a, _ = _two_hosts_one_record(tmp_path)
    index = ExperimentIndex(a, APP).refresh()
    gets, reads = _log_gets(a), _local_reads(a)
    a.append_log_entry(APP, "v", "wa", entry(3))
    index.refresh()
    assert gets == []
    assert len(reads) == 1 and reads[0][0] == "log.wa.jsonl" and reads[0][1] > 0
    assert index.rows()[0]["metrics"] == {"i": 3}


def test_an_idle_poll_reads_no_log(tmp_path):
    a, _ = _two_hosts_one_record(tmp_path)
    index = ExperimentIndex(a, APP).refresh()
    gets, reads = _log_gets(a), _local_reads(a)
    index.refresh()
    assert gets == [] and reads == []


def test_listing_by_keys_matches_the_full_listing(tmp_path):
    a, _ = _two_hosts_one_record(tmp_path)
    a.sync_log_to_remote(APP, "v", "wa")
    assert a.list_files(APP, keys=["v"]) == a.list_files(APP)


# -- property: incremental == full refold, whatever happens -----------------


def _ops(a, b, verstrs, rng, step):
    host, writer = rng.choice([(a, "wa"), (b, "wb"), (a, "wa2")])
    verstr = rng.choice(verstrs)
    op = rng.choice(["append", "append", "sync", "compact", "new", "finish"])
    if op == "append":
        host.append_log_entry(APP, verstr, writer, entry(step % 60, step=step))
    elif op == "sync":
        host.sync_log_to_remote(APP, verstr, writer)
    elif op == "compact":
        s3_storage().compact_log_segments(APP, verstr, writer)
    elif op == "new":
        v = f"v{step}"
        host.save(APP, v, meta(v, timestamp=f"2026-01-02T00:00:{step % 60:02d}Z"), {})
        verstrs.append(v)
    else:
        host.save_file(APP, verstr, "run_state.yml", yaml.dump({"state": "finished"}))
        host.sync_log_to_remote(APP, verstr, writer)


@pytest.mark.parametrize("seed", range(6))
def test_incremental_fold_equals_a_full_refold(tmp_path, seed):
    rng = random.Random(seed)
    a, b = cached_host(tmp_path, "a"), cached_host(tmp_path, "b")
    a.save(APP, "v0", meta("v0"), {})
    verstrs = ["v0"]
    index = ExperimentIndex(a, APP)
    for step in range(40):
        _ops(a, b, verstrs, rng, step)
        rows = index.refresh().rows()
        assert rows == ExperimentIndex(a, APP).refresh().rows(), f"step {step}"
        assert rows == direct_rows(a, APP)[0], f"step {step}"
