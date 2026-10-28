"""Plan 28 A0: ``vmn-exp settings <app> show|set -f <file>`` (git-free), and
the CLI/SDK readers sorting by the store settings below a checkout's conf."""
import pytest

from exp_helpers import _experiment, _init_app, _run_vmn_init, _stamp_app, extract_dev_verstr
from vmn_exp.cli.main import vmn_exp_run
from vmn_exp.core.app_settings_store import read_settings_text, write_settings
from vmn_exp.sdk.reader import list_runs
from vmn_exp.storage.areas import local_store_root
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "app"
TEXT = "# ours\nmetrics: {loss: {goal: min, primary: true}}\n"


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VMN_EXPERIMENT_DIR", raising=False)
    monkeypatch.delenv("VMN_EXPERIMENT_STORE", raising=False)
    return str(tmp_path / "store")


def _run(*argv):
    code, _ = vmn_exp_run(list(argv))
    return code


def _file(tmp_path, text):
    path = tmp_path / "settings.yml"
    path.write_text(text)
    return str(path)


def test_set_then_show_prints_the_file(store_dir, tmp_path, capsys):
    assert _run("settings", APP, "set", "-f", _file(tmp_path, TEXT), "--dir", store_dir) == 0
    assert read_settings_text(LocalSnapshotStorage(store_dir, "runs"), APP) == TEXT
    capsys.readouterr()
    assert _run("settings", APP, "show", "--dir", store_dir) == 0
    assert capsys.readouterr().out == TEXT


def test_show_is_the_default_and_says_when_there_are_none(store_dir, capsys):
    assert _run("settings", APP, "--dir", store_dir) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and "No settings" in captured.err


def test_set_refuses_invalid_settings(store_dir, tmp_path, capsys):
    bad = _file(tmp_path, "ui: {group_aggregate: sum}\n")
    assert _run("settings", APP, "set", "-f", bad, "--dir", store_dir) == 1
    assert "group_aggregate" in capsys.readouterr().err
    assert read_settings_text(LocalSnapshotStorage(store_dir, "runs"), APP) is None


def test_set_needs_a_file(store_dir, capsys):
    assert _run("settings", APP, "set", "--dir", store_dir) == 1


def _store_run(storage, n, loss):
    verstr = f"0.0.1-dev.abc1234.def5678.r{n}"
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": f"2026-01-01T00:00:0{n}Z"}, {})
    storage.append_log_entry(APP, verstr, "w", {
        "type": "metrics", "values": {"loss": loss}, "timestamp": "t"})
    return verstr


def test_list_runs_sorts_by_the_store_settings(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path / "store"), "runs")
    low, high = _store_run(storage, 1, 0.1), _store_run(storage, 2, 0.9)
    assert [r["verstr"] for r in list_runs(APP, storage=storage)] == [low, high]
    write_settings(storage, APP, "metrics: {loss: {goal: max, primary: true}}\n")
    assert [r["verstr"] for r in list_runs(APP, storage=storage)] == [high, low]


def test_vmn_exp_list_sorts_by_the_checkouts_store_settings(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    for i, loss in enumerate([0.5, 0.3, 0.4]):
        app_layout.write_file_commit_and_push("test_repo_0", f"s{i}.txt", "initial")
        with open(f"{app_layout.repo_path}/s{i}.txt", "w") as f:
            f.write(f"content {i}")
        _experiment(app_layout.app_name, metrics=[f"loss={loss}"])
        assert extract_dev_verstr(capfd.readouterr().out)
    store = LocalSnapshotStorage(local_store_root(app_layout.repo_path), "runs")
    write_settings(store, app_layout.app_name, TEXT)
    assert _experiment(app_layout.app_name, action="list") == 0
    lines = [ln for ln in capfd.readouterr().out.strip().split("\n") if ln.startswith("[")]
    assert "loss=0.3" in lines[0] and "loss=0.5" in lines[-1]
