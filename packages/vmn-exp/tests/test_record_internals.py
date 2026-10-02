"""Plan 14 §2.4: inside a run record, logs live under ``log/``, vmn's own
outputs under ``outputs/`` and user artifacts alone under ``artifacts/`` — so
a user artifact may be named anything, and lineage paths say which is which."""
import os

import pytest
import yaml

from vmn_exp.core.lineage import artifact_ref_uri
from vmn_exp.core.png import encode_png
from vmn_exp.sdk import start_run
from vmn_exp.sdk.reader import get_run
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "trainer"
PNG = encode_png(bytes(3 * 2 * 2), 2, 2, 3)


@pytest.fixture(autouse=True)
def _clean_experiment_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_EXPERIMENT_BUCKET"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def store(tmp_path, monkeypatch):
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
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(tmp_path / "store"))
    return LocalSnapshotStorage(str(tmp_path / "store"), area="runs")


def _record_dir(store, verstr):
    return store._snapshot_dir(APP, verstr)


def _read(store, verstr, path):
    with open(store.artifact_local_path(APP, verstr, path), "rb") as f:
        return f.read()


def _png(tmp_path):
    pic = tmp_path / "pic.png"
    pic.write_bytes(PNG)
    return str(pic)


def test_logs_are_written_and_listed_under_log(store):
    with start_run() as run:
        run.log_metric("loss", 1.0)
    record = _record_dir(store, run.id)
    assert not [n for n in os.listdir(record) if n.endswith(".jsonl")]
    assert any(n.endswith(".jsonl") for n in os.listdir(os.path.join(record, "log")))
    logs = [n for n in store.record_files(APP, run.id) if n.startswith("log/")]
    assert logs and all(n.endswith(".jsonl") for n in logs)
    assert get_run(APP, run.id, storage=store)["metrics"]["loss"] == 1.0


def test_media_and_tables_live_under_outputs(store, tmp_path):
    with start_run() as run:
        run.log_image("sample", _png(tmp_path), step=1)
        run.log_table("preds", [{"a": 1}], step=2)
    record = _record_dir(store, run.id)
    assert os.path.isfile(os.path.join(record, "outputs", "media", "sample", "1.png"))
    assert os.path.isfile(os.path.join(record, "outputs", "tables", "preds", "2.json"))
    assert not os.path.exists(os.path.join(record, "artifacts"))
    outputs = get_run(APP, run.id, storage=store)["outputs"]
    assert set(outputs) == {"outputs/media/sample/1.png", "outputs/tables/preds/2.json"}


def test_user_artifacts_named_like_vmn_outputs_do_not_collide(store, tmp_path):
    mine = tmp_path / "mine.bin"
    mine.write_bytes(b"user bytes")
    with start_run() as run:
        run.log_image("x", _png(tmp_path), step=0)
        run.log_artifact(str(mine), name="media/x/0.png")
        run.log_artifact(str(mine), name="output.log")
    assert _read(store, run.id, "outputs/media/x/0.png") == PNG
    assert _read(store, run.id, "artifacts/media/x/0.png") == b"user bytes"
    assert _read(store, run.id, "artifacts/output.log") == b"user bytes"
    names = {a["name"] for a in store.list_artifacts(APP, run.id)}
    assert {"outputs/media/x/0.png", "artifacts/media/x/0.png",
            "artifacts/output.log"} <= names


def test_use_artifact_resolves_an_outputs_media_uri(store, tmp_path):
    with start_run() as producer:
        producer.log_image("x", _png(tmp_path), step=3)
    with start_run() as consumer:
        local = consumer.use_artifact(producer.id, "outputs/media/x/3.png")
    with open(local, "rb") as f:
        assert f.read() == PNG
    (entry,) = get_run(APP, consumer.id, storage=store)["inputs"].values()
    assert entry["uri"] == artifact_ref_uri(APP, producer.id, "outputs/media/x/3.png")
    assert entry["uri"].endswith("/outputs/media/x/3.png")


def test_user_artifact_paths_are_explicit(store, tmp_path):
    model = tmp_path / "model.pkl"
    model.write_bytes(b"weights")
    with start_run() as run:
        run.log_artifact(str(model))
    assert set(get_run(APP, run.id, storage=store)["outputs"]) == {"artifacts/model.pkl"}
    with start_run() as consumer:
        local = consumer.use_artifact(run.id, "artifacts/model.pkl")
    with open(local, "rb") as f:
        assert f.read() == b"weights"


def test_console_output_is_stored_under_outputs(store, tmp_path):
    from vmn_exp.core.output_log import OutputArtifact

    with start_run() as run:
        output = OutputArtifact(store, APP, run.id, cap_bytes=1024)
        output.write(b"hello\n")
        output.seal()
        assert output.upload()
    path = os.path.join(_record_dir(store, run.id), "outputs", "output.log")
    with open(path, "rb") as f:
        assert f.read() == b"hello\n"


def test_an_s3_record_keeps_logs_outputs_and_artifacts_apart(monkeypatch, tmp_path):
    from s3_helpers import entry, mocked_bucket, raw_keys, s3_storage
    from s3_helpers import meta as s3_meta

    src = tmp_path / "f.bin"
    src.write_bytes(b"x")
    with mocked_bucket(monkeypatch):
        s3 = s3_storage()
        s3.save("app", "v", s3_meta("v"), {})
        s3.append_log_entry("app", "v", "w", entry(1))
        s3.save_artifact_file("app", "v", str(src), name="artifacts/output.log")
        s3.save_artifact_file("app", "v", str(src), name="outputs/output.log")
        keys = {k.split("/v/", 1)[1] for k in raw_keys()}
        files = s3.record_files("app", "v")
        names = [a["name"] for a in s3.list_artifacts("app", "v")]
    assert {"log/w.jsonl", "artifacts/output.log", "outputs/output.log"} <= keys
    assert "log/w.jsonl" in files
    assert not any(n.startswith(("artifacts/", "outputs/")) for n in files)
    assert names == ["artifacts/output.log", "outputs/output.log"]
