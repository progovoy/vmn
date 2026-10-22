"""Plan 25 F2 on S3: with the listing baseline persisted, a warm cold start
lists one page of record names instead of every record's files."""
import pytest
from s3_helpers import cached_host, mocked_bucket, op_counts, record_calls, s3_storage

moto = pytest.importorskip("moto")

from vmn_exp.core.index import ExperimentIndex  # noqa: E402

APP = "myapp"
FINISHED = "state: succeeded\nexit_code: 0\n"


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield


def _seed(storage, first, n):
    verstrs = []
    for i in range(first, first + n):
        v = f"0.0.{i}"
        storage.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}, {})
        storage.append_log_entry(APP, v, "w0", {"timestamp": "2026-01-01T00:01:00Z",
                                                "type": "metrics", "values": {"loss": 1.0}})
        storage.save_file(APP, v, "run_state.yml", FINISHED)
        verstrs.append(v)
    return verstrs


def _cold_refresh(storage, client, cache):
    calls = record_calls(client)
    index = ExperimentIndex(storage, APP, cache_path=cache).refresh()
    return index, op_counts(calls)


def test_a_warm_cold_start_on_s3_lists_one_page_of_names(tmp_path):
    cache = str(tmp_path / "idx.sqlite")
    _seed(s3_storage(), 0, 20)
    ExperimentIndex(s3_storage(), APP, cache_path=cache).refresh()

    storage = s3_storage()
    index, counts = _cold_refresh(storage, storage._s3, cache)
    assert counts == {"ListObjectsV2": 1}
    assert len(index.rows()) == 20


def test_a_new_record_on_s3_costs_its_own_listing_only(tmp_path):
    cache = str(tmp_path / "idx.sqlite")
    _seed(s3_storage(), 0, 20)
    ExperimentIndex(s3_storage(), APP, cache_path=cache).refresh()
    new = _seed(s3_storage(), 30, 1)[0]

    storage = s3_storage()
    index, counts = _cold_refresh(storage, storage._s3, cache)
    # The names, then the new record's own files, log/ and metrics/.
    assert counts["ListObjectsV2"] == 1 + 3
    assert index.rows()[-1]["verstr"] == new


def test_a_record_deleted_on_s3_is_gone_from_a_cold_start(tmp_path):
    cache = str(tmp_path / "idx.sqlite")
    verstrs = _seed(s3_storage(), 0, 3)
    ExperimentIndex(s3_storage(), APP, cache_path=cache).refresh()
    s3_storage().delete(APP, verstrs[1])

    storage = s3_storage()
    index, counts = _cold_refresh(storage, storage._s3, cache)
    assert counts == {"ListObjectsV2": 1}
    assert [r["verstr"] for r in index.rows()] == [verstrs[0], verstrs[2]]


def test_a_warm_cold_start_of_a_cached_host_lists_one_remote_page(tmp_path):
    cache = str(tmp_path / "idx.sqlite")
    _seed(cached_host(tmp_path, "a"), 0, 20)
    ExperimentIndex(cached_host(tmp_path, "a"), APP, cache_path=cache).refresh()

    host = cached_host(tmp_path, "a")
    index, counts = _cold_refresh(host, host._remote._s3, cache)
    assert counts == {"ListObjectsV2": 1}
    assert len(index.rows()) == 20
