"""Store-only maintenance commands (``backfill-children``, ``compact``,
``similar-backfill``) outside a git checkout: like ``prune``, they take the
store from the store flags / ``VMN_EXPERIMENT_*`` and the app from the
positional name — no ``--from-snapshot`` needed."""
import pytest
import yaml

from vmn_exp.cli.main import vmn_exp_run
from vmn_exp.core.writer import create_run
from vmn_exp.storage.open import open_storage

APP = "trainer"
CODE = "1.2.0-dev.abc1234.def5678"


def _finished():
    return {"state": "finished", "exit_code": 0, "heartbeat": "2026-01-01T00:00:00Z",
            "heartbeat_interval_sec": 30}


@pytest.fixture
def store_root(tmp_path, monkeypatch):
    """An outer run whose child lost its marker, in a store next to no checkout."""
    root = tmp_path / "exps"
    storage = open_storage(None, str(root), area="runs")
    outer = create_run(storage, APP, CODE, {"timestamp": "2026-01-01T00:00:00Z"}, {})
    kid = create_run(storage, APP, CODE, {"timestamp": "2026-01-01T00:00:01Z"}, {},
                     parent=outer)
    storage.unmark_child(APP, outer, kid)
    for verstr in (outer, kid):
        storage.save_file(APP, verstr, "run_state.yml", yaml.dump(_finished()))
    nogit = tmp_path / "nogit"
    nogit.mkdir()
    monkeypatch.chdir(nogit)
    for var in ("VMN_WORKING_DIR", "VMN_SNAPSHOT_METADATA", "VMN_EXPERIMENT_STORE",
                "VMN_EXPERIMENT_DIR", "VMN_EXPERIMENT_BUCKET"):
        monkeypatch.delenv(var, raising=False)
    return root, outer, kid


def _children(root, outer):
    return open_storage(None, str(root), area="runs").list_children(APP, outer)


def test_backfill_children_without_a_checkout_takes_the_store_flag(store_root, capfd):
    root, outer, kid = store_root
    argv = ["exp", "backfill-children", APP, "--store", f"file://{root}"]
    assert vmn_exp_run(argv)[0] == 0
    assert _children(root, outer) == [kid]
    assert "wrote 1" in capfd.readouterr().out


def test_backfill_children_without_a_checkout_takes_the_env_var(
        store_root, monkeypatch, capfd):
    root, outer, kid = store_root
    monkeypatch.setenv("VMN_EXPERIMENT_STORE", f"file://{root}")
    assert vmn_exp_run(["exp", "backfill-children", APP])[0] == 0
    assert _children(root, outer) == [kid]


def test_backfill_children_without_a_checkout_or_store_names_the_flags(
        store_root, capfd):
    root, outer, _ = store_root
    assert vmn_exp_run(["exp", "backfill-children", APP])[0] == 1
    err = capfd.readouterr().err
    assert "--store" in err and "git repository" not in err
    assert _children(root, outer) == []


@pytest.mark.parametrize("action", ["compact", "similar-backfill"])
def test_other_maintenance_runs_without_a_checkout(store_root, monkeypatch, action):
    root = store_root[0]
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(root))
    extra = ["--all-finished"] if action == "compact" else ["--dry-run"]
    assert vmn_exp_run(["exp", action, APP, *extra])[0] == 0


@pytest.mark.parametrize("action", ["compact", "similar-backfill"])
def test_other_maintenance_without_a_store_names_the_flags(store_root, capfd, action):
    extra = ["--all-finished"] if action == "compact" else ["--dry-run"]
    assert vmn_exp_run(["exp", action, APP, *extra])[0] == 1
    err = capfd.readouterr().err
    assert "--store" in err and "git repository" not in err


def test_a_read_command_still_needs_a_checkout(store_root, monkeypatch, capfd):
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(store_root[0]))
    assert vmn_exp_run(["exp", "export-metrics", APP])[0] == 1
    assert "git repository" in capfd.readouterr().err


def test_a_from_snapshot_refusal_does_not_blame_snapshot_mode(
        store_root, monkeypatch, capfd):
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(store_root[0]))
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", "unused.yml")
    assert vmn_exp_run(["exp", "lineage", APP])[0] == 1
    err = capfd.readouterr().err
    assert "requires a git repository" in err and "--from-snapshot mode" not in err
