"""How fresh an index's snapshot is (:meth:`ExperimentIndex.freshness`):
``as_of``, the wall time its last completed refresh started, persists in the
index file, so a restarted server knows how old the rows it serves are; while
a refresh runs, its ``phase`` and ``progress`` say what it is doing."""
import threading

import pytest

moto = pytest.importorskip("moto")
import boto3  # noqa: E402

import vmn_exp.core.index as index_module  # noqa: E402
import vmn_exp.core.index_freshness as freshness_module  # noqa: E402
from vmn_exp.core.index import ExperimentIndex  # noqa: E402
from vmn_exp.core.index_freshness import listing_progress  # noqa: E402
from vmn_exp.storage.s3 import S3SnapshotStorage  # noqa: E402

APP = "myapp"
BUCKET = "vmn-bucket"
N = 12
OCT_22 = 1792698240.0  # 2026-10-22T19:44:00Z


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        storage = _storage()
        for i in range(N):
            v = f"0.0.{i:02d}"
            storage.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}, {})
        yield


@pytest.fixture
def wall(monkeypatch):
    now = [OCT_22]
    monkeypatch.setattr(freshness_module, "_wall", lambda: now[0])
    return now


def _storage():
    return S3SnapshotStorage(BUCKET, prefix="exps")


def test_listing_progress_is_the_walks_place_among_the_known_keys():
    keys = [f"k{i}" for i in range(10)]
    assert listing_progress(keys, "k4") == 0.5
    assert listing_progress(keys, "k9") == 1.0
    assert listing_progress(keys, "a") == 0.0
    assert listing_progress(keys, None) is None
    assert listing_progress([], "k4") is None


def test_an_index_never_refreshed_is_idle_and_has_no_as_of(s3, tmp_path):
    index = ExperimentIndex(_storage(), APP, str(tmp_path / "i.sqlite"))
    assert index.freshness() == {
        "as_of": None, "refreshing": False, "phase": "idle", "progress": None,
    }


def test_as_of_is_when_the_last_refresh_started(s3, tmp_path, wall):
    index = ExperimentIndex(_storage(), APP, str(tmp_path / "i.sqlite")).refresh()
    assert index.freshness()["as_of"] == OCT_22
    wall[0] += 30
    index.refresh()
    assert index.freshness()["as_of"] == OCT_22 + 30


def test_as_of_survives_a_restart(s3, tmp_path, wall):
    cache = str(tmp_path / "i.sqlite")
    ExperimentIndex(_storage(), APP, cache).refresh()
    wall[0] += 4 * 86400

    reopened = ExperimentIndex(_storage(), APP, cache)

    assert reopened.freshness()["as_of"] == OCT_22


def test_as_of_is_persisted_at_most_once_a_minute(s3, tmp_path, wall):
    cache = str(tmp_path / "i.sqlite")
    index = ExperimentIndex(_storage(), APP, cache).refresh()
    wall[0] += 30
    index.refresh()
    assert ExperimentIndex(_storage(), APP, cache).freshness()["as_of"] == OCT_22
    wall[0] += 31
    index.refresh()
    assert ExperimentIndex(_storage(), APP, cache).freshness()["as_of"] == OCT_22 + 61


def test_a_failed_refresh_leaves_as_of_alone(s3, tmp_path, wall, monkeypatch):
    index = ExperimentIndex(_storage(), APP, str(tmp_path / "i.sqlite")).refresh()
    wall[0] += 600

    def broken(*args, **kwargs):
        raise OSError("connection reset")

    monkeypatch.setattr(index._sweep, "listing", broken)
    with pytest.raises(OSError):
        index.refresh()

    assert index.freshness()["as_of"] == OCT_22
    assert index.freshness()["phase"] == "idle"


def _paged(storage, on_page, page_size=3):
    """List *storage*'s objects *page_size* at a time, calling ``on_page(n)``
    before the n-th page of a full walk (the app prefix's)."""
    client, count = storage._s3, [0]
    real = client.list_objects_v2

    def list_objects_v2(**params):
        if params.get("Prefix", "").endswith(f"{APP}/") and "Delimiter" not in params:
            count[0] += 1
            on_page(count[0])
            params["MaxKeys"] = page_size
        return real(**params)

    client.list_objects_v2 = list_objects_v2


def test_a_full_listing_reports_how_far_its_walk_is(s3, tmp_path):
    storage = _storage()
    index = ExperimentIndex(storage, APP, str(tmp_path / "i.sqlite")).refresh()
    seen = []
    _paged(storage, lambda n: n > 1 and seen.append(index.freshness()))
    index.reconcile()

    index.refresh()

    assert seen and all(s["refreshing"] and s["phase"] == "full_listing" for s in seen)
    progress = [s["progress"] for s in seen]
    assert progress == sorted(progress) and 0 < progress[0] < progress[-1] <= 1
    assert index.freshness()["phase"] == "idle"


def test_loading_new_records_reports_the_share_read(s3, tmp_path, monkeypatch):
    monkeypatch.setattr(index_module, "_REMOTE_CHUNK", 4)
    storage, seen, lock = _storage(), [], threading.Lock()
    index = ExperimentIndex(storage, APP, str(tmp_path / "i.sqlite"))
    load, count = storage.load_file, [0]

    def load_file(app_name, verstr, filename):
        if filename == "metadata.yml":
            with lock:
                count[0] += 1
                if count[0] in (5, 9):  # the first record of the 2nd and 3rd chunks
                    seen.append(index.freshness())
        return load(app_name, verstr, filename)

    storage.load_file = load_file
    index.refresh()

    assert [s["phase"] for s in seen] == ["loading_new", "loading_new"]
    assert [s["progress"] for s in seen] == [round(4 / N, 3), round(8 / N, 3)]
