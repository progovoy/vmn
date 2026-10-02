"""Lineage through the SDK: ``run.use_artifact`` and ``reader.get_lineage``,
on a local experiment dir and on S3 (git-free container mode)."""
import hashlib
import os

import pytest
import yaml

from vmn_exp.core.lineage import artifact_ref_uri
from vmn_exp.sdk import start_run
from vmn_exp.sdk.reader import get_lineage, get_run
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "trainer"


@pytest.fixture(autouse=True)
def _clean_experiment_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_EXPERIMENT_BUCKET"):
        monkeypatch.delenv(key, raising=False)


def _image(tmp_path, monkeypatch):
    image = tmp_path / "image"
    image.mkdir()
    (image / "vmn_metadata.yml").write_text(yaml.safe_dump({
        "verstr": "0.0.1-dev.abc1234.def5678",
        "app_name": APP,
        "base_version": "0.0.1",
        "base_commit": "abc1234" * 5 + "abcde",
        "branch": "main",
    }))
    monkeypatch.chdir(image)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(image / "vmn_metadata.yml"))
    monkeypatch.setenv("VMN_CAPTURE_ENV", "0")
    return image


@pytest.fixture
def store(tmp_path, monkeypatch):
    _image(tmp_path, monkeypatch)
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(tmp_path / "store"))
    return LocalSnapshotStorage(str(tmp_path / "store"), area="runs")


def _file(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    return str(path), hashlib.sha256(content).hexdigest()


def _producer(tmp_path, content=b"weights"):
    path, sha = _file(tmp_path, "model.pkl", content)
    with start_run(name="train") as run:
        run.log_artifact(path)
    return run, sha


def test_use_artifact_records_a_vmn_uri_and_returns_a_local_copy(store, tmp_path):
    producer, sha = _producer(tmp_path)
    with start_run(name="eval") as consumer:
        local = consumer.use_artifact(producer.id, "artifacts/model.pkl")
    with open(local, "rb") as f:
        assert f.read() == b"weights"
    inputs = get_run(APP, consumer.id, storage=store)["inputs"]
    assert inputs == {"model": {
        "uri": artifact_ref_uri(APP, producer.id, "artifacts/model.pkl"),
        "digest": f"sha256:{sha}",
        "kind": "artifact",
    }}


def test_use_artifact_takes_refs_and_a_name(store, tmp_path):
    producer, _ = _producer(tmp_path)
    with start_run() as consumer:
        consumer.use_artifact("@1", "artifacts/model.pkl", name="weights")
    assert set(get_run(APP, consumer.id, storage=store)["inputs"]) == {"weights"}


def test_use_artifact_refuses_an_artifact_the_run_did_not_log(store, tmp_path):
    producer, _ = _producer(tmp_path)
    with start_run() as consumer:
        with pytest.raises(ValueError, match="nope.bin"):
            consumer.use_artifact(producer.id, "nope.bin")


def test_a_non_zero_rank_gets_the_file_and_records_nothing(store, tmp_path):
    from vmn_exp.sdk.ranks import NoOpRun

    producer, _ = _producer(tmp_path)
    before = len(store.list_verstrs(APP))
    local = NoOpRun(APP).use_artifact(producer.id, "artifacts/model.pkl")
    with open(local, "rb") as f:
        assert f.read() == b"weights"
    assert len(store.list_verstrs(APP)) == before


def test_get_lineage_upstream_downstream_and_models(store, tmp_path):
    producer, _ = _producer(tmp_path)
    producer.register_model("clf", artifact_path="artifacts/model.pkl", alias="prod")
    with start_run(name="eval") as consumer:
        consumer.use_artifact(producer.id, "artifacts/model.pkl")

    up = get_lineage(APP, consumer.id, storage=store)
    assert [(n["verstr"], n["name"], n["status"]) for n in up["upstream"]] == [
        (producer.id, "train", "succeeded")
    ]
    assert up["downstream"] == [] and up["models"] == []

    down = get_lineage(APP, producer.id, storage=store)
    assert [n["verstr"] for n in down["downstream"]] == [consumer.id]
    assert down["downstream"][0]["links"][0]["via"] == "uri"
    assert down["models"] == [{
        "model": "clf", "kind": "model", "version": 1, "aliases": ["prod"],
        "status": "active", "artifact_path": "artifacts/model.pkl",
    }]
    assert down["app"] == APP and down["verstr"] == producer.id


def test_get_lineage_matches_by_digest_and_walks_depth(store, tmp_path):
    data, data_sha = _file(tmp_path, "data.csv", b"a,b\n1,2\n")
    with start_run(name="prep") as prep:
        prep.log_artifact(data)
    with start_run(name="train") as train:
        train.log_input("file:///mnt/data.csv", digest=f"sha256:{data_sha}")
        model, _ = _file(tmp_path, "model.pkl", b"m")
        train.log_artifact(model)
    with start_run(name="eval") as evaluate:
        evaluate.use_artifact(train.id, "artifacts/model.pkl")

    one = get_lineage(APP, evaluate.id, storage=store)
    assert [n["verstr"] for n in one["upstream"]] == [train.id]
    two = get_lineage(APP, evaluate.id, depth=2, storage=store)
    assert [(n["verstr"], n["depth"]) for n in two["upstream"]] == [(train.id, 1), (prep.id, 2)]
    assert two["upstream"][1]["links"][0]["via"] == "digest"


def test_get_lineage_no_match_and_unknown_ref(store, tmp_path):
    with start_run() as lone:
        lone.log_metric("x", 1)
    assert get_lineage(APP, lone.id, storage=store)["upstream"] == []
    with pytest.raises(ValueError):
        get_lineage(APP, "0.0.1-dev.nope", storage=store)


def test_lineage_on_s3(tmp_path, monkeypatch):
    s3 = pytest.importorskip("s3_helpers")
    with s3.mocked_bucket(monkeypatch):
        _image(tmp_path, monkeypatch)
        monkeypatch.delenv("VMN_EXPERIMENT_DIR", raising=False)
        monkeypatch.setenv("VMN_EXPERIMENT_BUCKET", s3.BUCKET)
        monkeypatch.setenv("VMN_EXPERIMENT_PREFIX", s3.PREFIX)
        producer, _ = _producer(tmp_path, b"s3 weights")
        with start_run() as consumer:
            local = consumer.use_artifact(producer.id, "artifacts/model.pkl")
        assert os.path.isfile(local)
        lineage = get_lineage(APP, consumer.id, storage=s3.s3_storage())
        assert [n["verstr"] for n in lineage["upstream"]] == [producer.id]
