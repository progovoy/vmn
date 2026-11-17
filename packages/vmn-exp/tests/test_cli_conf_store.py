"""``vmn-exp model`` and ``vmn-exp import-mlflow`` in a checkout open the
store the app's conf.yml names (``store:``) when no flag or env var does, as
``start_run`` and the other ``vmn-exp`` commands do (plan 45)."""
import json

from test_cli_exp_import_mlflow import _build_mlruns, _call as _import_mlflow
from test_cli_exp_import_mlflow import _make_args as _import_args
from test_cli_model import _make_args as _model_args
from test_reader_conf_store import _app_with_conf, _drop_local_runs, _no_store_env  # noqa: F401
from vmn_exp.cli.checkout_store import CwdCheckout
from vmn_exp.core.real_io import real_io
from vmn_exp.sdk import start_run
from vmn_exp.sdk.models import register_model
from vmn_exp.storage.local import LocalSnapshotStorage


def _conf_store(app_layout, tmp_path):
    shared = tmp_path / "shared"
    _app_with_conf(app_layout, {"store": {"uri": shared.as_uri()}})
    return LocalSnapshotStorage(str(shared), area="runs")


def _model_cli(**kwargs):
    from vmn_exp.cli.model_cmd import model_run_without_repo

    return model_run_without_repo(_model_args(prefix=None, **kwargs), real_io(), CwdCheckout())


def test_model_list_sees_a_model_registered_in_the_conf_store(app_layout, tmp_path, capsys):
    _conf_store(app_layout, tmp_path)
    with start_run(app_layout.app_name) as run:
        register_model("clf", run)
    _drop_local_runs(app_layout)
    capsys.readouterr()

    assert _model_cli(action="list", json=True) == 0
    assert "clf" in json.dumps(json.loads(capsys.readouterr().out))


def test_model_register_resolves_a_run_in_the_conf_store(app_layout, tmp_path):
    _conf_store(app_layout, tmp_path)
    with start_run(app_layout.app_name) as run:
        pass
    _drop_local_runs(app_layout)

    assert _model_cli(action="register", model_name="clf", version_ref=run.id,
                      app=app_layout.app_name) == 0


def test_import_mlflow_writes_to_the_conf_store(app_layout, tmp_path):
    store = _conf_store(app_layout, tmp_path)
    mlruns = _build_mlruns(tmp_path)

    args = _import_args(mlruns=mlruns, name=app_layout.app_name, prefix=None)
    assert _import_mlflow(args) == 0
    assert len(store.list_verstrs(app_layout.app_name)) == 2
