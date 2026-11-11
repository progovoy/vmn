"""A version registered with an absolute ``artifact_path`` (``s3://…`` or
``/data/…``): a use records that URI as the input (not
``vmn://app/ver/s3://…``), and lineage still links the consumer to the
version's producer run — up from the consumer, down from the producer — read
from the store (``RegistryLinks``) or from the ui's ``RegistrySnapshot``."""
import pytest
from test_sdk_usage import FakeRun, _clean_env, _storage  # noqa: F401 (autouse fixture)

from vmn_exp.registry.lineage import app_indexes, run_lineage
from vmn_exp.registry.store import ensure_model, register_version
from vmn_exp.sdk.usage import use_model

URI = "s3://bucket/models/clf.pt"
DIGEST = "sha256:" + "c" * 64


def _version(storage, verstr, path=URI, app="trainer"):
    FakeRun(storage, app, verstr)
    ensure_model(storage, "clf")
    return register_version(storage, "clf", {"app": app, "verstr": verstr},
                            artifact_path=path, digest=DIGEST)


def _keys(nodes):
    return [(n["app"], n["verstr"]) for n in nodes]


def _snapshot(storage):
    pytest.importorskip("fastapi")
    from vmn_exp.ui.registry_snapshot import RegistrySnapshot

    return RegistrySnapshot.read(storage)


def _lineage(storage, app, verstr, snapshot):
    registry = _snapshot(storage) if snapshot else None
    return run_lineage(storage, app, verstr, app_indexes(storage), registry=registry)


@pytest.mark.parametrize("path", [URI, "/data/models/clf.pt"])
def test_a_use_records_the_absolute_uri(tmp_path, path):
    storage = _storage(tmp_path)
    _version(storage, "0.0.1-dev.aaa", path)
    run = FakeRun(storage, "serving", "1.0.0")
    use_model("clf@1", run=run, storage=storage)
    assert run.inputs() == {"clf@1": {"uri": path, "digest": DIGEST, "kind": "model"}}


@pytest.mark.parametrize("snapshot", [False, True])
def test_the_consumer_links_up_to_the_producer(tmp_path, snapshot):
    storage = _storage(tmp_path)
    _version(storage, "0.0.1-dev.aaa")
    use_model("clf@1", run=FakeRun(storage, "serving", "1.0.0"), storage=storage)
    lineage = _lineage(storage, "serving", "1.0.0", snapshot)
    assert _keys(lineage["upstream"]) == [("trainer", "0.0.1-dev.aaa")]
    link = lineage["upstream"][0]["links"][0]
    assert (link["input"], link["artifact"], link["via"]) == ("clf@1", URI, "uri")
    assert (link["model"], link["version"], link["kind"]) == ("clf", 1, "model")


@pytest.mark.parametrize("snapshot", [False, True])
def test_the_producer_links_down_to_its_consumer(tmp_path, snapshot):
    storage = _storage(tmp_path)
    _version(storage, "0.0.1-dev.aaa")
    use_model("clf@1", run=FakeRun(storage, "trainer", "0.0.2-dev.bbb"), storage=storage)
    lineage = _lineage(storage, "trainer", "0.0.1-dev.aaa", snapshot)
    assert _keys(lineage["downstream"]) == [("trainer", "0.0.2-dev.bbb")]
    assert lineage["downstream"][0]["links"][0]["artifact"] == URI


@pytest.mark.parametrize("snapshot", [False, True])
def test_a_retrained_version_at_the_same_uri_links_only_its_own_run(tmp_path, snapshot):
    storage = _storage(tmp_path)
    _version(storage, "0.0.1-dev.aaa")
    _version(storage, "0.0.1-dev.bbb")
    use_model("clf@2", run=FakeRun(storage, "trainer", "0.0.2-dev.ccc"), storage=storage)
    up = _lineage(storage, "trainer", "0.0.2-dev.ccc", snapshot)["upstream"]
    assert _keys(up) == [("trainer", "0.0.1-dev.bbb")]
    assert _lineage(storage, "trainer", "0.0.1-dev.aaa", snapshot)["downstream"] == []
    down = _lineage(storage, "trainer", "0.0.1-dev.bbb", snapshot)["downstream"]
    assert _keys(down) == [("trainer", "0.0.2-dev.ccc")]


def test_a_plain_input_of_an_unregistered_uri_links_nothing(tmp_path):
    storage = _storage(tmp_path)
    _version(storage, "0.0.1-dev.aaa")
    FakeRun(storage, "serving", "1.0.0").log_input("s3://bucket/other.pt", name="other")
    assert _lineage(storage, "serving", "1.0.0", False)["upstream"] == []
