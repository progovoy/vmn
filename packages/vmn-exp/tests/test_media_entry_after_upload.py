"""A logged image/table is recorded — in the log and as an output — only once
its file has been stored: a slow, failed or killed upload never leaves an
entry claiming a file the store does not have."""
import hashlib
import os
import select
import signal
import subprocess
import sys
import textwrap
import threading
import time

import pytest
import yaml

from vmn_exp.core.png import encode_png
from vmn_exp.sdk import start_run
from vmn_exp.sdk.reader import get_run
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "trainer"
VERSTR = "0.0.1-dev.abc1234.def5678"
PNG = encode_png(bytes(3 * 2 * 2), 2, 2, 3)
PNG_PATH = "outputs/media/pic/3.png"


@pytest.fixture(autouse=True)
def _clean_experiment_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_EXPERIMENT_BUCKET"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def image_dir(tmp_path, monkeypatch):
    image = tmp_path / "image"
    image.mkdir()
    (image / "vmn_metadata.yml").write_text(yaml.safe_dump({
        "verstr": VERSTR,
        "app_name": APP,
        "base_version": "0.0.1",
        "base_commit": "abc1234" * 5 + "abcde",
        "branch": "main",
    }))
    monkeypatch.chdir(image)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(image / "vmn_metadata.yml"))
    monkeypatch.setenv("VMN_CAPTURE_ENV", "0")
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(tmp_path / "store"))
    return image


@pytest.fixture
def store(image_dir, tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "store"), area="runs")


class _GatedStore(LocalSnapshotStorage):
    """Media saves wait for ``gate``; ``fail`` makes them raise instead."""

    def __init__(self, *args, fail=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate, self.stored, self.fail = threading.Event(), threading.Event(), fail

    def save_artifact_file(self, app_name, verstr, src_path, name=None):
        if name and name.startswith(("outputs/media/", "outputs/tables/")):
            self.gate.wait(10)
            if self.fail:
                raise OSError("disk full")
            super().save_artifact_file(app_name, verstr, src_path, name=name)
            self.stored.set()
            return None
        return super().save_artifact_file(app_name, verstr, src_path, name=name)


def _gated(store, **kwargs):
    return _GatedStore(store.root, area="runs", **kwargs)


def _png(tmp_path):
    path = tmp_path / "pic.png"
    path.write_bytes(PNG)
    return str(path)


def _entries(row, etype):
    return [e for e in row["log"] if e.get("type") == etype]


def _wait_for_entry(run, store, etype, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run._log_buffer.flush()
        row = get_run(APP, run.id, storage=store)
        if _entries(row, etype):
            return row
        time.sleep(0.02)
    raise AssertionError(f"no {etype} entry appeared")


def test_the_entry_and_output_appear_only_once_the_file_is_stored(store, tmp_path):
    gated = _gated(store)
    with start_run(storage=gated) as run:
        run.log_image("pic", _png(tmp_path), step=3)
        run.log_note("after the image")
        run._log_buffer.flush()
        row = get_run(APP, run.id, storage=store)
        assert _entries(row, "image") == []
        assert PNG_PATH not in row["outputs"]

        gated.gate.set()
        row = _wait_for_entry(run, store, "image")
    (image,) = _entries(row, "image")
    assert (image["step"], image["path"]) == (3, PNG_PATH)
    assert image["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert image["size"] == len(PNG)
    # Stamped when logged, not when stored: before the note logged after it.
    assert image["timestamp"] <= _entries(row, "note")[0]["timestamp"]
    assert row["outputs"][PNG_PATH]["size"] == len(PNG)
    assert row["media"]["pic"][0]["step"] == 3


def test_a_failed_upload_leaves_no_entry_and_no_output(store, tmp_path):
    gated = _gated(store, fail=True)
    gated.gate.set()
    with start_run(storage=gated) as run:
        run.log_image("pic", _png(tmp_path), step=3)
        run.log_table("t", [{"a": 1}])
    row = get_run(APP, run.id, storage=store)
    assert _entries(row, "image") == [] and _entries(row, "table") == []
    assert _entries(row, "output_failed") == []
    assert row["outputs"] == {}


def test_entries_of_uploads_finishing_in_the_final_drain_are_persisted(store, tmp_path):
    gated = _gated(store)
    with start_run(storage=gated) as run:
        run.log_image("pic", _png(tmp_path), step=3)
        threading.Timer(0.3, gated.gate.set).start()
    row = get_run(APP, run.id, storage=store)
    assert [e["path"] for e in _entries(row, "image")] == [PNG_PATH]
    assert set(row["outputs"]) == {PNG_PATH}


def test_final_drain_entries_reach_the_s3_remote(image_dir, tmp_path, monkeypatch):
    s3 = pytest.importorskip("s3_helpers")
    with s3.mocked_bucket(monkeypatch):
        host = s3.cached_host(tmp_path, "host")
        save, gate = host.save_artifact_file, threading.Event()

        def slow_save(app_name, verstr, src_path, name=None):
            gate.wait(10)
            return save(app_name, verstr, src_path, name=name)

        host.save_artifact_file = slow_save
        with start_run(storage=host) as run:
            run.log_image("pic", _png(tmp_path), step=3)
            threading.Timer(0.3, gate.set).start()
        row = get_run(APP, run.id, storage=s3.s3_storage())
    assert [e["path"] for e in _entries(row, "image")] == [PNG_PATH]
    assert set(row["outputs"]) == {PNG_PATH}


_KILLED_CHILD = textwrap.dedent("""
    import sys, time
    from vmn_exp.sdk import start_run
    from vmn_exp.storage.local import LocalSnapshotStorage

    class Hung(LocalSnapshotStorage):
        def save_artifact_file(self, app_name, verstr, src_path, name=None):
            if name and name.startswith("outputs/media/"):
                time.sleep(600)
            return super().save_artifact_file(app_name, verstr, src_path, name=name)

    run = start_run(storage=Hung(sys.argv[1], area="runs"))
    run.log_image("pic", sys.argv[2], step=3)
    run.log_metric("loss", 0.5)
    run._log_buffer.flush()
    print(run.id, flush=True)
    time.sleep(600)
""")


def test_a_process_killed_mid_upload_leaves_no_dangling_entry(store, tmp_path):
    child = subprocess.Popen(
        [sys.executable, "-c", _KILLED_CHILD, store.root, _png(tmp_path)],
        stdout=subprocess.PIPE, text=True, env=dict(os.environ),
    )
    try:
        ready, _, _ = select.select([child.stdout], [], [], 60)
        verstr = child.stdout.readline().strip() if ready else ""
    finally:
        child.send_signal(signal.SIGKILL)
        child.wait(10)
    assert verstr
    row = get_run(APP, verstr, storage=store)
    assert [e["values"] for e in _entries(row, "metrics")] == [{"loss": 0.5}]
    assert _entries(row, "image") == []
    assert row["outputs"] == {}
