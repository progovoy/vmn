"""``vmn-exp run`` (at child exit) and the MLflow importer (at the end of a
run) leave their metrics compacted as ``metrics/<w>.vmx`` (plan 12 §6)."""
from exp_helpers import _PY, _bootstrap, _exec_script, _experiment, _storage, extract_dev_verstr

from vmn_exp.core.metric_files import is_indexed_file
from vmn_exp.snapshot import LocalSnapshotStorage


def _all_indexed(storage, app_name, verstr):
    objects = storage.metric_objects(app_name, verstr)
    return bool(objects) and all(
        len(objs) == 1 and is_indexed_file(objs[0][0]) for objs in objects.values())


def test_exp_run_compacts_the_metrics_at_child_exit(app_layout, capfd):
    _bootstrap(app_layout)
    script = _exec_script(
        app_layout, "emit.py",
        'import os\nf = os.environ["VMN_METRICS_FILE"]\n'
        'open(f, "a").write("step=1 loss=0.5\\nstep=2 loss=0.25\\n")\n')
    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="run", run_cmd=[_PY, script]) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    storage = _storage(app_layout)
    assert _all_indexed(storage, app_layout.app_name, verstr)
    log = storage.load_merged_log(app_layout.app_name, verstr)
    assert [e["step"] for e in log if e.get("type") == "metrics"] == [1, 2]


def test_mlflow_import_compacts_each_run(tmp_path):
    from mlflow_fixtures import MlflowFixtureBuilder

    from vmn_exp.importers.import_records import import_run, run_verstr
    from vmn_exp.importers.mlflow_filestore import iter_runs

    builder = MlflowFixtureBuilder(tmp_path / "mlruns")
    builder.add_experiment("1", "exp_one")
    run_id = "b" * 36
    builder.add_run("1", run_id, metrics={"loss": [(1700000001000, 0.5, 0),
                                                   (1700000002000, 0.25, 1)]})
    storage = LocalSnapshotStorage(str(tmp_path / "store"), "runs")
    import_run(storage, "app", next(iter_runs(tmp_path / "mlruns")))
    assert _all_indexed(storage, "app", run_verstr(run_id))
