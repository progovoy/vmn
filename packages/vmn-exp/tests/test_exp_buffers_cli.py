"""Plan 40 C6: ``vmn-exp buffers list|ship`` over fakes (a tmp_path buffers
base and bucket, a fake owner lock)."""
import io
import json
import os

import pytest
from buffer_recover_fakes import APP, V, FakeHost, RecordingBucket, down, kept_buffer, remote_steps
from s3_helpers import meta

from vmn_exp.cli import main as main_module
from vmn_exp.cli.buffers_cmd import buffers_main
from vmn_exp.core.status import parse_iso
from vmn_exp.storage import buffer_owner, buffered
from vmn_exp.core.real_io import real_io


@pytest.fixture(autouse=True)
def _flush_at_end():
    yield
    buffered.close_all()


@pytest.fixture
def events():
    return []


def _bucket(tmp_path, name, events):
    remote = RecordingBucket(str(tmp_path / name), events)
    remote.save(APP, V, meta(V), {})
    return remote


@pytest.fixture
def bucket(tmp_path, events):
    return _bucket(tmp_path, "bucket", events)


@pytest.fixture
def base(tmp_path):
    return str(tmp_path / "log-buffers")


def _run(argv, base, host, stores=None, store_env=None, now=0.0):
    """``(exit code, output)`` of ``vmn-exp buffers <argv>``; *stores* maps a
    URI to the storage it opens."""
    out = io.StringIO()
    code = buffers_main(
        argv, host=host, bases=[base], store_env=store_env,
        open_remote=lambda uri, area: (stores or {})[uri], out=out, now=now)
    return code, out.getvalue()


def _started_at(root):
    with open(os.path.join(root, buffer_owner.MARKER_FILE)) as f:
        return parse_iso(json.load(f)["started_at"]).timestamp()


def test_buffers_list_prints_kept_buffers(monkeypatch, bucket, base, events):
    root = kept_buffer(monkeypatch, bucket, base)

    code, out = _run(["list"], base, FakeHost(events), now=_started_at(root) + 7200)

    assert code == 0
    (line,) = out.splitlines()
    assert root in line
    for part in ("orphaned", "age 2h", f"runs {APP}/{V}", repr(bucket.cache_identity())):
        assert part in line


def test_buffers_list_marks_a_live_buffer(monkeypatch, bucket, base, events):
    kept_buffer(monkeypatch, bucket, base)
    code, out = _run(["list"], base, FakeHost(events, refuse=True))
    assert code == 0 and " live " in out


def test_buffers_ship_ships_an_orphaned_buffer(monkeypatch, bucket, base, events):
    root = kept_buffer(monkeypatch, bucket, base)

    code, out = _run(["ship", "--store", "s3://b"], base, FakeHost(events), {"s3://b": bucket})

    assert code == 0
    assert f"{root}: shipped" in out
    assert remote_steps(bucket) == [0, 1]


def test_buffers_ship_reads_the_store_from_the_environment(monkeypatch, bucket, base, events):
    kept_buffer(monkeypatch, bucket, base)
    code, out = _run(["ship"], base, FakeHost(events), {"s3://b": bucket}, store_env="s3://b")
    assert code == 0 and "shipped" in out


def test_buffers_ship_skips_a_live_buffer_and_exits_zero(monkeypatch, bucket, base, events):
    root = kept_buffer(monkeypatch, bucket, base)

    code, out = _run(["ship", "--store", "s3://b"], base, FakeHost(events, refuse=True),
                     {"s3://b": bucket})

    assert code == 0
    assert f"{root}: live: skipped" in out
    assert remote_steps(bucket) == [0]


def test_buffers_ship_skips_a_buffer_of_another_store(monkeypatch, tmp_path, bucket, base,
                                                       events):
    root = kept_buffer(monkeypatch, bucket, base)
    other = _bucket(tmp_path, "other", events)

    code, out = _run(["ship", "--store", "s3://o"], base, FakeHost(events), {"s3://o": other})

    assert code == 0
    assert f"{root}: another store: skipped" in out
    assert remote_steps(bucket) == [0]


def test_buffers_ship_exits_nonzero_when_a_locked_buffer_could_not_be_shipped(
        monkeypatch, bucket, base, events):
    root = kept_buffer(monkeypatch, bucket, base)
    monkeypatch.setattr(bucket, "create_log_segment", down)

    code, out = _run(["ship", "--store", "s3://b"], base, FakeHost(events), {"s3://b": bucket})

    assert code == 1
    assert f"{root}: failed: " in out and "out of reach" in out


def test_buffers_ship_without_a_store_is_a_usage_error(monkeypatch, bucket, base, events):
    kept_buffer(monkeypatch, bucket, base)
    code, out = _run(["ship"], base, FakeHost(events))
    assert code == 2 and "--store" in out


def test_buffers_list_takes_no_repo_lock(monkeypatch):
    def no_vmn_run(*args, **kwargs):
        raise AssertionError("buffers went through vmn's command machinery (repo lock)")

    monkeypatch.setattr(main_module, "vmn_run", no_vmn_run)

    code, _ = main_module.run_argv(["buffers", "list"], lambda: "0", real_io())

    assert code == 0
