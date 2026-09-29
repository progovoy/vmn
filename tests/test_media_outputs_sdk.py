"""Logged images and tables are run outputs: they fold into ``outputs`` with
the sha256/size of the stored bytes, ``use_artifact`` fetches them, lineage
links their consumers, and a file that never got stored is never recorded."""
import hashlib
import threading

import pytest
import yaml

from vmn_exp.core.lineage import artifact_ref_uri
from vmn_exp.core.png import encode_png
from vmn_exp.sdk import start_run
from vmn_exp.sdk.media_uploads import MediaUploads
from vmn_exp.sdk.reader import get_lineage, get_run, list_runs
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
    return LocalSnapshotStorage(str(tmp_path / "store"), subdir="experiments")


def _png(tmp_path):
    path = tmp_path / "pic.png"
    path.write_bytes(PNG)
    return str(path)


def _stored(store, verstr, name):
    with open(store.artifact_local_path(APP, verstr, name), "rb") as f:
        return f.read()


def _expected(data):
    return {"digest": f"sha256:{hashlib.sha256(data).hexdigest()}", "size": len(data)}


def test_log_image_and_log_table_are_outputs_with_the_stored_digest(store, tmp_path):
    with start_run(name="media") as run:
        run.log_image("pic", _png(tmp_path), step=0)
        run.log_table("preds", [{"y": 1}], step=2)
    outputs = get_run(APP, run.id, storage=store)["outputs"]
    assert set(outputs) == {"media/pic/0.png", "tables/preds/2.json"}
    for path, out in outputs.items():
        assert out == dict(_expected(_stored(store, run.id, path)), path=path)


def test_use_artifact_fetches_a_logged_image_of_another_run(store, tmp_path):
    with start_run(name="gen") as producer:
        producer.log_image("pic", _png(tmp_path))
    with start_run(name="judge") as consumer:
        local = consumer.use_artifact(producer.id, "media/pic/0.png")
    with open(local, "rb") as f:
        assert f.read() == PNG
    inp = get_run(APP, consumer.id, storage=store)["inputs"]["0"]
    assert inp["uri"] == artifact_ref_uri(APP, producer.id, "media/pic/0.png")
    assert inp["digest"] == _expected(PNG)["digest"]


def test_use_artifact_fetches_a_logged_table(store):
    with start_run() as producer:
        producer.log_table("t", [{"a": 1}])
    with start_run() as consumer:
        local = consumer.use_artifact(producer.id, "tables/t/0.json", name="t")
    assert open(local).read() == _stored(store, producer.id, "tables/t/0.json").decode()


def test_lineage_links_a_media_consumer_by_uri_and_by_digest(store, tmp_path):
    with start_run(name="gen") as producer:
        producer.log_image("pic", _png(tmp_path))
    with start_run(name="by_uri") as by_uri:
        by_uri.use_artifact(producer.id, "media/pic/0.png")
    with start_run(name="by_digest") as by_digest:
        by_digest.log_input("file:///copy.png", digest=_expected(PNG)["digest"])

    down = get_lineage(APP, producer.id, storage=store)["downstream"]
    vias = {n["verstr"]: n["links"][0]["via"] for n in down}
    assert vias == {by_uri.id: "uri", by_digest.id: "digest"}
    up = get_lineage(APP, by_digest.id, storage=store)["upstream"]
    assert [(n["verstr"], n["links"][0]["artifact"]) for n in up] == [
        (producer.id, "media/pic/0.png")
    ]


def test_list_runs_query_reaches_media_outputs(store, tmp_path):
    with start_run() as with_image:
        with_image.log_image("x", _png(tmp_path))
    with start_run() as without:
        without.log_metric("m", 1)
    rows = list_runs(APP, storage=store, query='outputs."media/x/0.png".size > 0')
    assert [r["verstr"] for r in rows] == [with_image.id]
    by_verstr = {r["verstr"]: r for r in list_runs(APP, storage=store)}
    assert set(by_verstr[with_image.id]["outputs"]) == {"media/x/0.png"}
    assert by_verstr[without.id]["outputs"] == {}


class _FailingStore(LocalSnapshotStorage):
    def save_artifact_file(self, app_name, verstr, src_path, name=None):
        if name and name.startswith("media/"):
            raise OSError("disk full")
        return super().save_artifact_file(app_name, verstr, src_path, name=name)


def test_a_media_file_that_failed_to_store_is_never_recorded(store, tmp_path):
    with start_run(storage=_FailingStore(store.vmn_root_path, subdir="experiments")) as run:
        run.log_image("pic", _png(tmp_path))
        run.log_table("t", [{"a": 1}])
    row = get_run(APP, run.id, storage=store)
    assert set(row["outputs"]) == {"tables/t/0.json"}
    assert [e["path"] for e in row["log"] if e["type"] == "image"] == []


def test_uploads_still_queued_at_the_close_deadline_are_never_recorded(tmp_path):
    gate, recorded = threading.Event(), []

    def save(path, name):
        gate.wait(5)

    uploads = MediaUploads(save)
    for name in ("a", "b", "c"):
        staged = tmp_path / name
        staged.mkdir()
        (staged / "f").write_bytes(b"x")
        uploads.submit(str(staged), str(staged / "f"), name, lambda n=name: recorded.append(n))
    assert uploads.close(0.2) is False
    gate.set()
    uploads._thread.join(5)
    # "a" was being stored when the deadline passed; the rest never started.
    assert recorded == ["a"]
    assert not (tmp_path / "b").exists() and not (tmp_path / "c").exists()
