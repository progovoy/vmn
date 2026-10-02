"""Usage recording through a real ``start_run()`` run (plan 06)."""
import os

import pytest
from exp_helpers import _bootstrap, _storage

from vmn_exp.core.fold import fold_inputs_dict, fold_log
from vmn_exp.core.log import load_log
from vmn_exp.registry.log import read_uses
from vmn_exp.sdk import NoOpRun, start_run
from vmn_exp.sdk.models import download_model, register_model


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID"):
        monkeypatch.delenv(key, raising=False)


def _trained(app_layout, tmp_path):
    _bootstrap(app_layout)
    storage = _storage(app_layout)
    weights = tmp_path / "weights.pkl"
    weights.write_text("w")
    with start_run(app_layout.app_name) as run:
        run.log_artifact(str(weights), name="weights.pkl")
    register_model("gpt", run=run, artifact_path="artifacts/weights.pkl", storage=storage)
    return storage, run


def _inputs(storage, run):
    return fold_inputs_dict(fold_log(load_log(storage, run.app_name, run.id)))


def _users(storage):
    return [(u["app"], u["verstr"]) for u in read_uses(storage, "gpt").get(1, [])]


def test_download_model_in_run_records_use(app_layout, tmp_path):
    storage, _ = _trained(app_layout, tmp_path)
    with start_run(app_layout.app_name) as consumer:
        path = download_model("gpt", storage=storage)
    assert open(path).read() == "w"
    assert list(_inputs(storage, consumer)) == ["gpt@1"]
    assert _users(storage) == [(consumer.app_name, consumer.id)]


def test_download_model_outside_run_records_nothing(app_layout, tmp_path):
    storage, _ = _trained(app_layout, tmp_path)
    assert os.path.isfile(download_model("gpt", storage=storage))
    assert _users(storage) == []


def test_download_model_record_false_records_nothing(app_layout, tmp_path):
    storage, _ = _trained(app_layout, tmp_path)
    with start_run(app_layout.app_name) as consumer:
        download_model("gpt", storage=storage, record=False)
    assert _inputs(storage, consumer) == {}
    assert _users(storage) == []


def test_run_use_model_delegates(app_layout, tmp_path):
    storage, _ = _trained(app_layout, tmp_path)
    with start_run(app_layout.app_name) as consumer:
        meta = consumer.use_model("gpt@latest", storage=storage)
    assert meta["n"] == 1
    assert list(_inputs(storage, consumer)) == ["gpt@1"]
    assert _users(storage) == [(consumer.app_name, consumer.id)]


def test_noop_run_use_model_returns_meta_without_writes(app_layout, tmp_path):
    storage, _ = _trained(app_layout, tmp_path)
    noop = NoOpRun(app_layout.app_name)
    assert noop.use_model("gpt", storage=storage)["n"] == 1
    assert _users(storage) == []
    with pytest.raises(ValueError):
        noop.use_dataset("gpt", storage=storage)
