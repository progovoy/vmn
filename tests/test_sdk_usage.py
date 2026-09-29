"""Recorded model/dataset usage from the SDK (plan 06).

A use is an ordinary ``input`` entry on the consuming run (named
``<name>@<N>``, URI ``vmn://`` of the producer artifact) plus a ``use`` entry
in the registry's ``<name>-uses`` record.
"""
import hashlib
import logging

import pytest

from vmn_exp._base import now_iso
from vmn_exp.core.fold import fold_inputs_dict, fold_log
from vmn_exp.core.inputs import create_input_entry
from vmn_exp.core.lineage import artifact_ref_uri
from vmn_exp.core.log import load_log
from vmn_exp.core.writer import create_log_entry
from vmn_exp.registry.log import read_entries, read_uses, set_alias
from vmn_exp.registry.names import REGISTRY_APP, uses_record_name
from vmn_exp.registry.store import ensure_model, register_version
from vmn_exp.sdk.models import get_model_version, register_model
from vmn_exp.sdk.usage import use_dataset, use_model
from vmn_exp.storage.local import LocalSnapshotStorage


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID"):
        monkeypatch.delenv(key, raising=False)


class FakeRun:
    """Duck-typed run: a real record whose inputs land in its storage log."""

    def __init__(self, storage, app_name, verstr):
        storage.create_exclusive(app_name, verstr, {"app": app_name, "verstr": verstr}, {})
        self._storage, self.app_name, self.id = storage, app_name, verstr

    def log_input(self, uri, name=None, digest=None, kind=None):
        entry = create_input_entry(uri, name=name, digest=digest, kind=kind, ts=now_iso())
        self._storage.append_log_entry(self.app_name, self.id, "w", entry)

    def inputs(self):
        return fold_inputs_dict(fold_log(load_log(self._storage, self.app_name, self.id)))


def _storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), subdir="experiments")


def _producer(storage, app="trainer", verstr="0.0.1-dev.aaa", path="model.pkl", data=b"w"):
    storage.create_exclusive(app, verstr, {"app": app, "verstr": verstr}, {})
    sha = hashlib.sha256(data).hexdigest()
    entry = create_log_entry("artifact", path=path, size=len(data), sha256=sha)
    storage.append_log_entry(app, verstr, "w", entry)
    return f"sha256:{sha}"


def _model(storage, name="resnet", verstr="0.0.1-dev.aaa", data=b"w"):
    digest = _producer(storage, verstr=verstr, data=data)
    meta = register_model(name, run=verstr, app_name="trainer",
                          artifact_path="model.pkl", storage=storage)
    return meta["n"], digest


def test_use_model_logs_vmn_artifact_uri_with_producer_digest(tmp_path):
    storage = _storage(tmp_path)
    n, digest = _model(storage)
    run = FakeRun(storage, "serving", "1.0.0")
    meta = use_model("resnet", run=run, storage=storage)
    assert meta["n"] == n
    (entry,) = run.inputs().values()
    assert entry == {
        "uri": artifact_ref_uri("trainer", "0.0.1-dev.aaa", "model.pkl"),
        "digest": digest,
        "kind": "model",
    }


def test_use_model_input_name_is_pinned_name_at_n(tmp_path):
    storage = _storage(tmp_path)
    _model(storage)
    run = FakeRun(storage, "serving", "1.0.0")
    use_model("resnet@1", run=run, storage=storage)
    assert list(run.inputs()) == ["resnet@1"]


def test_use_model_alias_is_pinned_to_number(tmp_path):
    storage = _storage(tmp_path)
    _model(storage)
    set_alias(storage, "resnet", "prod", 1)
    run = FakeRun(storage, "serving", "1.0.0")
    use_model("resnet@prod", run=run, storage=storage)
    assert list(run.inputs()) == ["resnet@1"]


def test_use_two_versions_both_survive_input_fold(tmp_path):
    storage = _storage(tmp_path)
    _model(storage, verstr="0.0.1-dev.aaa", data=b"one")
    _model(storage, verstr="0.0.1-dev.bbb", data=b"two")
    run = FakeRun(storage, "serving", "1.0.0")
    use_model("resnet@1", run=run, storage=storage)
    use_model("resnet@2", run=run, storage=storage)
    assert sorted(run.inputs()) == ["resnet@1", "resnet@2"]


def test_use_model_appends_use_entry_to_uses_record(tmp_path):
    storage = _storage(tmp_path)
    n, _ = _model(storage)
    run = FakeRun(storage, "serving", "1.0.0")
    use_model("resnet", run=run, storage=storage)
    (entry,) = read_entries(storage, uses_record_name("resnet"))
    assert entry["type"] == "use"
    assert entry["version"] == n
    assert entry["run"] == {"app": "serving", "verstr": "1.0.0"}
    assert {"ts", "writer", "pos", "actor"} <= set(entry)


def test_use_model_twice_records_once(tmp_path):
    storage = _storage(tmp_path)
    _model(storage)
    run = FakeRun(storage, "serving", "1.0.0")
    use_model("resnet", run=run, storage=storage)
    use_model("resnet@1", run=run, storage=storage)
    assert len(read_entries(storage, uses_record_name("resnet"))) == 1
    log = load_log(storage, "serving", "1.0.0")
    assert len([e for e in log if e.get("type") == "input"]) == 1


def test_use_model_without_run_resolves_and_records_nothing(tmp_path):
    storage = _storage(tmp_path)
    n, _ = _model(storage)
    assert use_model("resnet", storage=storage)["n"] == n
    assert read_uses(storage, "resnet") == {}


def test_register_model_never_records_self_use(tmp_path):
    storage = _storage(tmp_path)
    _model(storage)
    assert not storage.exists(REGISTRY_APP, uses_record_name("resnet"))


def test_get_model_version_never_records(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    _model(storage)
    run = FakeRun(storage, "serving", "1.0.0")
    monkeypatch.setattr("vmn_exp.sdk.context.current_run", lambda: run)
    get_model_version("resnet@1", storage=storage)
    assert read_uses(storage, "resnet") == {}
    assert run.inputs() == {}


def test_registry_write_failure_is_warned_not_raised(tmp_path, monkeypatch, caplog):
    storage = _storage(tmp_path)
    _model(storage)
    run = FakeRun(storage, "serving", "1.0.0")

    def boom(*args, **kwargs):
        raise OSError("registry is read-only")

    monkeypatch.setattr("vmn_exp.sdk.usage.record_use", boom)
    with caplog.at_level(logging.WARNING, logger="vmn_exp.sdk"):
        assert use_model("resnet", run=run, storage=storage)["n"] == 1
    assert "registry is read-only" in caplog.text
    assert list(run.inputs()) == ["resnet@1"]


def test_use_dataset_on_model_raises(tmp_path):
    storage = _storage(tmp_path)
    _model(storage)
    run = FakeRun(storage, "serving", "1.0.0")
    with pytest.raises(ValueError, match="model"):
        use_dataset("resnet", run=run, storage=storage)
    assert run.inputs() == {}


def test_use_model_on_dataset_raises(tmp_path):
    storage = _storage(tmp_path)
    ensure_model(storage, "imagenet", kind="dataset")
    register_version(storage, "imagenet", uri="s3://b/x", digest="sha256:ab")
    with pytest.raises(ValueError, match="dataset"):
        use_model("imagenet", run=FakeRun(storage, "serving", "1.0.0"), storage=storage)
