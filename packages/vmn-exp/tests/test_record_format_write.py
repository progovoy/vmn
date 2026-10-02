"""Every new run record — whichever path creates it — is stamped with the
record format version this code writes, so a later format can be detected."""
import sys
from pathlib import Path

import yaml
from exp_helpers import _bootstrap, _experiment, _PY, _storage

sys.path.insert(0, str(Path(__file__).parent))

from vmn_exp.core.record_format import RECORD_FORMAT_VERSION
from vmn_exp.core.writer import create_run
from vmn_exp.storage.local import LocalSnapshotStorage


def _local(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), area="runs")


def _format(storage, app, verstr):
    return storage.load(app, verstr)[0].get("format_version")


def test_the_format_version_is_a_positive_int():
    assert isinstance(RECORD_FORMAT_VERSION, int) and RECORD_FORMAT_VERSION >= 1


def test_create_run_stamps_the_format_version(tmp_path):
    storage = _local(tmp_path)
    verstr = create_run(storage, "app", "0.0.1", {"timestamp": "t"}, {})
    assert _format(storage, "app", verstr) == RECORD_FORMAT_VERSION


def test_a_run_created_straight_on_s3_is_stamped(monkeypatch):
    from s3_helpers import mocked_bucket, s3_storage

    with mocked_bucket(monkeypatch):
        storage = s3_storage()
        verstr = create_run(storage, "app", "0.0.1", {"timestamp": "t"}, {})
        assert _format(storage, "app", verstr) == RECORD_FORMAT_VERSION


def test_cli_create_stamps_the_format_version(app_layout):
    _bootstrap(app_layout)
    assert _experiment(app_layout.app_name) == 0
    storage = _storage(app_layout)
    (verstr,) = storage.list_verstrs(app_layout.app_name)
    assert _format(storage, app_layout.app_name, verstr) == RECORD_FORMAT_VERSION


def test_cli_run_stamps_the_format_version(app_layout):
    _bootstrap(app_layout)
    assert _experiment(app_layout.app_name, action="run", run_cmd=[_PY, "-c", "0"]) == 0
    storage = _storage(app_layout)
    (verstr,) = storage.list_verstrs(app_layout.app_name)
    assert _format(storage, app_layout.app_name, verstr) == RECORD_FORMAT_VERSION


def test_sdk_start_run_stamps_the_format_version(app_layout):
    from vmn_exp.sdk import start_run

    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        pass
    storage = _storage(app_layout)
    assert _format(storage, app_layout.app_name, run.id) == RECORD_FORMAT_VERSION


def test_a_git_free_from_snapshot_run_is_stamped(tmp_path):
    from vmn_exp.core.from_snapshot import create_from_snapshot

    meta_path = tmp_path / "vmn_metadata.yml"
    meta_path.write_text(
        yaml.dump({"verstr": "0.0.1-dev.abc.def", "app_name": "app",
                   "base_version": "0.0.1", "branch": "main"})
    )
    storage = _local(tmp_path / "exp")
    verstr, err = create_from_snapshot(storage, "app", str(meta_path))
    assert err is None
    assert _format(storage, "app", verstr) == RECORD_FORMAT_VERSION


def test_an_mlflow_import_is_stamped(tmp_path):
    from mlflow_fixtures import MlflowFixtureBuilder
    from vmn_exp.importers.import_records import import_run, run_verstr
    from vmn_exp.importers.mlflow_filestore import iter_runs

    run_id = "a" * 32
    builder = MlflowFixtureBuilder(tmp_path / "mlruns")
    builder.add_experiment("1", "exp_one")
    builder.add_run("1", run_id, start_time=1700000000000, status="FINISHED")
    storage = _local(tmp_path)
    assert import_run(storage, "app", next(iter_runs(tmp_path / "mlruns"))) == "created"
    assert _format(storage, "app", run_verstr(run_id)) == RECORD_FORMAT_VERSION


def test_model_registry_records_are_stamped(tmp_path):
    from vmn_exp.registry.names import REGISTRY_APP, version_record_name
    from vmn_exp.registry.store import ensure_model, register_version

    storage = _local(tmp_path)
    ensure_model(storage, "resnet")
    n = register_version(storage, "resnet", {"app": "app", "verstr": "0.0.1"})
    assert _format(storage, REGISTRY_APP, "resnet") == RECORD_FORMAT_VERSION
    assert _format(storage, REGISTRY_APP, version_record_name("resnet", n)) == RECORD_FORMAT_VERSION
