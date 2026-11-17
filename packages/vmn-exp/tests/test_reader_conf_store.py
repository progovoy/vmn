"""Readers find the store the writer records to: in a checkout, conf.yml's
``store:`` (else the legacy ``experiment.storage``) after the environment
(plan 45, one precedence table)."""
import os
import shutil

import pytest
import yaml
from exp_helpers import _init_app, _run_vmn_init, _stamp_app

from vmn_exp.sdk import start_run
from vmn_exp.sdk.models import get_model_version, list_models, register_model
from vmn_exp.sdk.reader import get_run, list_runs

_STORE_ENV = ("VMN_STORE", "VMN_STORE_BUCKET", "VMN_EXPERIMENT_STORE",
              "VMN_EXPERIMENT_BUCKET", "VMN_EXPERIMENT_DIR", "VMN_EXPERIMENT_ID",
              "VMN_APP_NAME")


@pytest.fixture(autouse=True)
def _no_store_env(monkeypatch):
    for key in _STORE_ENV:
        monkeypatch.delenv(key, raising=False)


def _commit_conf(app_layout, path, conf):
    with open(path, "w") as f:
        yaml.safe_dump({"conf": conf}, f)
    app_layout._app_backend.add_conf_file(path)


def _app_with_conf(app_layout, conf, after_stamp=False):
    """A stamped app whose conf.yml holds *conf*; *after_stamp* commits it
    after the stamp, which would move a legacy ``experiment.storage``."""
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    if not after_stamp:
        _commit_conf(app_layout, params["app_conf_path"], conf)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    if after_stamp:
        _commit_conf(app_layout, params["app_conf_path"], conf)


def _drop_local_runs(app_layout):
    """Leave the run only in the conf store, so a reader that ignores conf
    finds nothing (a file:// store is the root: none are written)."""
    shutil.rmtree(os.path.join(app_layout.repo_path, ".vmn", "store", "runs"),
                  ignore_errors=True)


def _record_one_run(app_layout):
    with start_run(app_layout.app_name, name="conf-store") as run:
        run.log_metric("loss", 0.5)
    _drop_local_runs(app_layout)
    return run.id


def test_reader_finds_a_run_written_to_the_conf_store(app_layout, tmp_path):
    _app_with_conf(app_layout, {"store": {"uri": (tmp_path / "shared").as_uri()}})
    verstr = _record_one_run(app_layout)

    rows = list_runs(app_layout.app_name, use_index=False)
    assert [r["verstr"] for r in rows] == [verstr]
    assert get_run(app_layout.app_name, verstr)["verstr"] == verstr


def test_reader_finds_a_run_written_to_the_legacy_experiment_storage(app_layout, tmp_path):
    shared = (tmp_path / "legacy").as_uri()
    _app_with_conf(app_layout, {"experiment": {"storage": {"uri": shared}}}, after_stamp=True)
    verstr = _record_one_run(app_layout)

    assert [r["verstr"] for r in list_runs(app_layout.app_name, use_index=False)] == [verstr]


def test_reader_without_an_app_name_reads_vmn_app_names_conf_store(app_layout, tmp_path,
                                                                    monkeypatch):
    _app_with_conf(app_layout, {"store": {"uri": (tmp_path / "shared").as_uri()}})
    verstr = _record_one_run(app_layout)
    monkeypatch.setenv("VMN_APP_NAME", app_layout.app_name)

    assert [r["verstr"] for r in list_runs(use_index=False)] == [verstr]


def test_reader_naming_no_app_reads_the_sole_stamped_apps_conf_store(app_layout, tmp_path):
    _app_with_conf(app_layout, {"store": {"uri": (tmp_path / "shared").as_uri()}})
    verstr = _record_one_run(app_layout)

    assert [r["verstr"] for r in list_runs(use_index=False)] == [verstr]


def test_model_readers_find_a_model_registered_in_the_conf_store(app_layout, tmp_path,
                                                                 monkeypatch):
    _app_with_conf(app_layout, {"store": {"uri": (tmp_path / "shared").as_uri()}})
    with start_run(app_layout.app_name) as run:
        register_model("clf", run)
    _drop_local_runs(app_layout)
    monkeypatch.setenv("VMN_APP_NAME", app_layout.app_name)

    assert list_models() == ["clf"]
    assert get_model_version("clf@latest")["n"] == 1


def test_env_beats_the_conf_store_for_readers(app_layout, tmp_path, monkeypatch):
    _app_with_conf(app_layout, {"store": {"uri": (tmp_path / "shared").as_uri()}})
    _record_one_run(app_layout)
    monkeypatch.setenv("VMN_STORE", (tmp_path / "elsewhere").as_uri())
    in_env_store = _record_one_run(app_layout)

    rows = list_runs(app_layout.app_name, use_index=False)
    assert [r["verstr"] for r in rows] == [in_env_store]


def test_a_non_zero_rank_reads_artifacts_from_the_store_rank_zero_does(app_layout, tmp_path,
                                                                       monkeypatch):
    _app_with_conf(app_layout, {"store": {"uri": (tmp_path / "shared").as_uri()}})
    weights = tmp_path / "model.pkl"
    weights.write_bytes(b"weights")
    with start_run(app_layout.app_name, name="train") as producer:
        producer.log_artifact(str(weights))
    _drop_local_runs(app_layout)

    with start_run(app_layout.app_name) as rank_zero:
        zero_path = rank_zero.use_artifact(producer.id, "artifacts/model.pkl")
    monkeypatch.setenv("RANK", "1")
    with start_run(app_layout.app_name) as rank_one:
        one_path = rank_one.use_artifact(producer.id, "artifacts/model.pkl")

    assert rank_one.rank == 1
    with open(zero_path, "rb") as f0, open(one_path, "rb") as f1:
        assert f0.read() == f1.read() == b"weights"
