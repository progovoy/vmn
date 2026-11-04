"""`vmn-exp prune` outside a git checkout: the store comes from the store
flags / ``VMN_EXPERIMENT_*`` variables, the app from the positional name —
no ``--from-snapshot`` needed."""
import pytest
import yaml

from vmn_exp.cli.main import vmn_exp_run
from vmn_exp.storage.open import open_storage

APP = "trainer"
RUNS = [f"1.2.0-dev.abc1234.r{i}" for i in range(3)]


def _finished():
    return {"state": "finished", "exit_code": 0, "heartbeat": "2026-01-01T00:00:00Z",
            "heartbeat_interval_sec": 30}


@pytest.fixture
def store_root(tmp_path, monkeypatch):
    root = tmp_path / "exps"
    storage = open_storage(None, str(root), area="runs")
    for i, verstr in enumerate(RUNS):
        storage.save(APP, verstr, {"verstr": verstr,
                                   "timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
        storage.save_file(APP, verstr, "run_state.yml", yaml.dump(_finished()))
    nogit = tmp_path / "nogit"
    nogit.mkdir()
    monkeypatch.chdir(nogit)
    for var in ("VMN_WORKING_DIR", "VMN_SNAPSHOT_METADATA", "VMN_EXPERIMENT_STORE",
                "VMN_EXPERIMENT_DIR", "VMN_EXPERIMENT_BUCKET"):
        monkeypatch.delenv(var, raising=False)
    return root


def _left(root):
    storage = open_storage(None, str(root), area="runs")
    return [v for v in RUNS if storage.exists(APP, v)]


def test_targeted_prune_without_a_checkout(store_root, monkeypatch, capfd):
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(store_root))
    assert vmn_exp_run(["exp", "prune", APP, "-v", RUNS[1]])[0] == 0
    assert _left(store_root) == [RUNS[0], RUNS[2]]
    assert f"Deleted {RUNS[1]}" in capfd.readouterr().out


def test_policy_prune_without_a_checkout_takes_the_store_flag(store_root, capfd):
    argv = ["exp", "prune", APP, "--keep", "1", "--store", f"file://{store_root}"]
    assert vmn_exp_run(argv)[0] == 0
    assert _left(store_root) == [RUNS[2]]


def test_prune_without_a_checkout_or_store_names_the_flags(store_root, capfd):
    assert vmn_exp_run(["exp", "prune", APP, "-v", RUNS[0]])[0] == 1
    err = capfd.readouterr().err
    assert "--store" in err and "git repository" not in err
    assert _left(store_root) == RUNS


def test_other_actions_still_need_a_checkout(store_root, monkeypatch, capfd):
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(store_root))
    assert vmn_exp_run(["exp", "tag", APP, RUNS[0], "stage=prod"])[0] == 1
    assert "git repository" in capfd.readouterr().err


def test_no_trim_journal_flag_skips_the_journal_trim(store_root, monkeypatch):
    from vmn_exp.cli import prune as prune_mod

    trims = []
    monkeypatch.setattr(prune_mod, "prune_journal", lambda storage: trims.append(storage))
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(store_root))
    assert vmn_exp_run(["exp", "prune", APP, "--keep", "1", "--no-trim-journal"])[0] == 0
    assert trims == []
    assert _left(store_root) == [RUNS[2]]
