"""Storage: ``update_metadata`` (archiving) and nested artifact paths.

``update_metadata`` rewrites ``metadata.yml`` the way ``update_note`` always
has — atomically on disk, under the ETag on S3 — for any field; a None value
drops the field. Stored files are named by record-relative path under
``artifacts/`` or ``outputs/``, nested (``artifacts/a/b/c.txt``), never absolute,
``..``, backslashed, NUL-carrying or with empty components.
"""
import os

import pytest
from s3_helpers import cached_host, meta, mocked_bucket, record_calls, s3_storage

from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.files import valid_artifact_path
from version_stamp.core.logging import init_stamp_logger

V = "1.0.0-dev.aaa.bbb"

BAD_PATHS = [
    "",
    "/etc/passwd",
    "../x",
    "a/../b",
    "a/..",
    "a\\b",
    "a\0b",
    "a//b",
    "a/",
    ".",
    "./a",
    "a/./b",
    "c.txt",
    "a/b/c.txt",
    "log/w.jsonl",
    "artifacts",
    "artifacts/",
    "artifacts/../x",
]


@pytest.fixture(autouse=True)
def _logger():
    try:
        init_stamp_logger()
    except Exception:
        pass


@pytest.fixture
def local(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path), area="runs")
    st.save("app", V, meta(V, note="keep me"), {})
    return st


@pytest.fixture
def bucket(monkeypatch):
    monkeypatch.delenv("VMN_EXPERIMENT_DIR", raising=False)
    with mocked_bucket(monkeypatch):
        yield


def _src(tmp_path, name="c.txt", data=b"hello"):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


# -- update_metadata -----------------------------------------------------------


def test_local_update_metadata_merges_fields(local):
    assert local.update_metadata("app", V, {"archived": True}) is True
    stored = local.load_metadata("app", V)
    assert stored["archived"] is True
    assert stored["note"] == "keep me"


def test_a_none_value_drops_the_field(local):
    local.update_metadata("app", V, {"archived": True})
    local.update_metadata("app", V, {"archived": None})
    assert "archived" not in local.load_metadata("app", V)


def test_update_metadata_of_a_missing_record_is_false(local):
    assert local.update_metadata("app", "9.9.9-dev.gone", {"archived": True}) is False


def test_s3_update_metadata_is_conditional(bucket):
    storage = s3_storage()
    storage.save("app", V, meta(V), {})
    calls = record_calls(storage._s3)

    assert storage.update_metadata("app", V, {"archived": True}) is True

    puts = [p for op, p in calls if op == "PutObject"]
    assert puts and all(p.get("IfMatch") for p in puts)
    assert storage.load_metadata("app", V)["archived"] is True


def test_cached_update_reaches_a_remote_only_record(bucket, tmp_path):
    s3_storage().save("app", V, meta(V), {})
    host = cached_host(tmp_path, "h")

    assert host.update_metadata("app", V, {"archived": True}) is True
    assert s3_storage().load_metadata("app", V)["archived"] is True


# -- nested artifact paths -------------------------------------------------------


@pytest.mark.parametrize("bad", BAD_PATHS)
def test_unsafe_artifact_paths_are_rejected(bad):
    assert not valid_artifact_path(bad)


@pytest.mark.parametrize(
    "good", ["artifacts/c.txt", "outputs/a/b/c.txt", "artifacts/plots/loss curve.png"]
)
def test_relative_artifact_paths_are_accepted(good):
    assert valid_artifact_path(good)


def test_local_nested_artifact_round_trip(local, tmp_path):
    assert local.save_artifact_file("app", V, _src(tmp_path), name="artifacts/a/b/c.txt")
    local.save_artifact_file("app", V, _src(tmp_path, "top.txt"))
    local.save_artifact_file("app", V, _src(tmp_path), name="outputs/output.log")

    names = [a["name"] for a in local.list_artifacts("app", V)]
    assert names == ["artifacts/a/b/c.txt", "artifacts/top.txt", "outputs/output.log"]
    with open(local.artifact_local_path("app", V, "artifacts/a/b/c.txt"), "rb") as f:
        assert f.read() == b"hello"


@pytest.mark.parametrize("bad", ["../escape.txt", "/abs.txt", "a/../../x"])
def test_local_refuses_to_store_outside_the_run(local, tmp_path, bad):
    with pytest.raises(ValueError):
        local.save_artifact_file("app", V, _src(tmp_path), name=bad)
    assert local.artifact_local_path("app", V, bad) is None


def test_cached_nested_artifacts_list_through(tmp_path):
    cached = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path), "runs"))
    cached.save("app", V, meta(V), {})
    cached.save_artifact_file("app", V, _src(tmp_path), name="artifacts/x/y.txt")
    assert [a["name"] for a in cached.list_artifacts("app", V)] == ["artifacts/x/y.txt"]


def test_s3_nested_artifact_round_trip(bucket, tmp_path):
    storage = s3_storage()
    storage.save("app", V, meta(V), {})
    storage.save_artifact_file("app", V, _src(tmp_path), name="artifacts/a/b/c.txt")
    storage.save_artifact_file("app", V, _src(tmp_path), name="outputs/media/x/0.png")

    assert [a["name"] for a in storage.list_artifacts("app", V)] == [
        "artifacts/a/b/c.txt", "outputs/media/x/0.png",
    ]
    chunks, size = storage.open_artifact("app", V, "artifacts/a/b/c.txt")
    assert (b"".join(chunks), size) == (b"hello", 5)
    path = storage.artifact_local_path("app", V, "artifacts/a/b/c.txt")
    assert open(path, "rb").read() == b"hello"
    assert storage.open_artifact("app", V, "../c.txt") is None


def test_s3_refuses_an_unsafe_name(bucket, tmp_path):
    storage = s3_storage()
    storage.save("app", V, meta(V), {})
    with pytest.raises(ValueError):
        storage.save_artifact_file("app", V, _src(tmp_path), name="../c.txt")


def test_default_name_is_the_basename_under_artifacts(local, tmp_path):
    local.save_artifact_file("app", V, _src(tmp_path, "w.bin"))
    path = local.artifact_local_path("app", V, "artifacts/w.bin")
    assert path.endswith(os.path.join("artifacts", "w.bin"))
