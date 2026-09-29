"""Lineage of used registry versions: ``reader.get_lineage`` links a run to
the model/dataset versions it used, and ``version_lineage`` answers "who made
version V and which runs used it" (plan 06)."""
import pytest
from test_sdk_usage import FakeRun, _model, _storage

from vmn_exp.registry.lineage import version_lineage
from vmn_exp.registry.log import set_version_status
from vmn_exp.sdk.datasets import register_dataset
from vmn_exp.sdk.reader import get_lineage
from vmn_exp.sdk.usage import use_dataset, use_model

PRODUCER = ("trainer", "0.0.1-dev.aaa")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_EXPERIMENT_DIR", "VMN_EXPERIMENT_STORE"):
        monkeypatch.delenv(key, raising=False)


def _dataset(storage, tmp_path):
    path = tmp_path / "train.csv"
    path.write_bytes(b"a,b\n")
    return register_dataset("ds", str(path), storage=storage)


def _consumer(storage, verstr="0.0.2-dev.ccc", app="serving"):
    return FakeRun(storage, app, verstr)


def _keys(nodes):
    return [(n["app"], n["verstr"], n["found"]) for n in nodes]


def test_get_lineage_annotates_the_used_model_cross_app(tmp_path):
    storage = _storage(tmp_path)
    _model(storage, "clf")
    consumer = _consumer(storage)
    use_model("clf@1", run=consumer, storage=storage)

    lineage = get_lineage("serving", consumer.id, storage=storage)
    assert _keys(lineage["upstream"]) == [(*PRODUCER, True)]
    link = lineage["upstream"][0]["links"][0]
    assert (link["input"], link["model"], link["version"], link["kind"]) == (
        "clf@1", "clf", 1, "model",
    )
    assert lineage["datasets"] == []


def test_get_lineage_lists_a_used_reference_dataset(tmp_path):
    storage = _storage(tmp_path)
    meta = _dataset(storage, tmp_path)
    consumer = _consumer(storage)
    use_dataset("ds", run=consumer, storage=storage)

    lineage = get_lineage("serving", consumer.id, storage=storage)
    assert lineage["upstream"] == []
    assert lineage["datasets"] == [{
        "model": "ds", "version": 1, "kind": "dataset", "input": "ds@1",
        "digest": meta["digest"], "found": True,
    }]


def test_version_lineage_producer_and_consumers(tmp_path):
    storage = _storage(tmp_path)
    _model(storage, "clf")
    first, second = _consumer(storage), _consumer(storage, "0.0.3-dev.ddd")
    use_model("clf@1", run=first, storage=storage)
    use_model("clf", run=second, storage=storage)

    found = version_lineage(storage, "clf", 1)
    assert (found["model"], found["version"], found["kind"], found["status"]) == (
        "clf", 1, "model", "active",
    )
    assert _keys([found["producer"]]) == [(*PRODUCER, True)]
    assert _keys(found["consumers"]) == [
        ("serving", first.id, True), ("serving", second.id, True),
    ]


def test_version_lineage_pruned_consumer_marked_missing(tmp_path):
    storage = _storage(tmp_path)
    _model(storage, "clf")
    consumer = _consumer(storage)
    use_model("clf@1", run=consumer, storage=storage)
    storage.delete("serving", consumer.id)

    assert _keys(version_lineage(storage, "clf", 1)["consumers"]) == [
        ("serving", consumer.id, False)
    ]


def test_version_lineage_deleted_version_status(tmp_path):
    storage = _storage(tmp_path)
    _model(storage, "clf")
    set_version_status(storage, "clf", 1, "deleted")

    found = version_lineage(storage, "clf", 1)
    assert found["status"] == "deleted"
    assert _keys([found["producer"]]) == [(*PRODUCER, True)]


def test_version_lineage_of_a_reference_dataset_has_no_producer(tmp_path):
    storage = _storage(tmp_path)
    _dataset(storage, tmp_path)
    found = version_lineage(storage, "ds", 1)
    assert (found["kind"], found["producer"], found["consumers"]) == ("dataset", None, [])


def test_version_lineage_of_an_unknown_version_raises(tmp_path):
    storage = _storage(tmp_path)
    _model(storage, "clf")
    with pytest.raises(KeyError):
        version_lineage(storage, "clf", 9)
