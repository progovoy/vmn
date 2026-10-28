"""A request watching an index for the first time never waits on its
refresh lock: when a load already holds it (a concurrent first request's,
a server edit's), the request answers the loading snapshot at once instead
of waiting out the load, for hours at 588k S3 runs."""
import threading
import time

import pytest

moto = pytest.importorskip("moto")
import boto3  # noqa: E402

from vmn_exp.core.index import ExperimentIndex  # noqa: E402
from vmn_exp.storage.s3 import S3SnapshotStorage  # noqa: E402
from vmn_exp.ui.refresher import Refresher  # noqa: E402

APP = "app"


@pytest.fixture
def held_store(monkeypatch):
    """A 3-run S3 store whose ``metadata.yml`` loads wait for the event."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    release = threading.Event()
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="vmn-bucket")
        storage = S3SnapshotStorage("vmn-bucket", prefix="st/runs")
        for i in range(3):
            v = f"0.0.{i}"
            storage.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
        real = S3SnapshotStorage.load_file

        def load_file(self, app_name, verstr, filename):
            if filename == "metadata.yml":
                release.wait(30)
            return real(self, app_name, verstr, filename)

        monkeypatch.setattr(S3SnapshotStorage, "load_file", load_file)
        try:
            yield storage, release
        finally:
            release.set()


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def test_the_first_watch_of_a_loading_index_answers_at_once(held_store, tmp_path):
    storage, release = held_store
    index = ExperimentIndex(storage, APP, str(tmp_path / "i.sqlite"))
    load = threading.Thread(target=index.refresh, daemon=True)
    load.start()
    _wait_for(lambda: index.refreshing)
    refresher = Refresher(interval_sec=0.02, idle_sec=60)
    answer = []
    try:
        request = threading.Thread(target=lambda: answer.append(refresher.snapshot(index)),
                                   daemon=True)
        request.start()
        request.join(3)

        assert answer and not answer[0].rows and answer[0].loading is not None
    finally:
        release.set()
        load.join(10)
        refresher.stop()
