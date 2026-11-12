"""The stuck floor, the run cadences, the local experiment dir, offline mode
and the alert config read the Env they are given (plan 44 G12 stage C); the
stuck floor reaches status derivation as a value the roots resolve from it."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fakes.clock import FakeClock
from fakes.console import FakeConsole
from fakes.env import FakeEnv
from fakes.host import FakeHost
from fakes.processes import FakeProcesses
from fakes.random import FakeRandom
from similar_seed import seed, verstr
from version_stamp.cli.args import parse_user_commands
from version_stamp.core.logging import init_stamp_logger
from vmn_exp.cli import experiment
from vmn_exp.core import run_intervals, status, storage_resolve
from vmn_exp.core.alerts.config import load_alert_config
from vmn_exp.core.ports import IO
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.ui.app_deps import real_deps
from vmn_exp.ui.server import build_app
from vmn_exp.ui.workspaces import WorkspaceManager

APP = "app"
LATER = datetime(2099, 1, 1, tzinfo=timezone.utc)  # past any store write time
BEAT_SEC = 10  # 3 beats are 30 s: the floor decides the stale window
SILENT_SEC = 120  # past the default 60 s floor, inside a 600 s one
WIDE = FakeEnv({"VMN_EXP_MIN_STALE_SEC": "600"})


@pytest.fixture(autouse=True)
def _process_env_says_otherwise(monkeypatch):
    for name, value in {
        "VMN_EXP_MIN_STALE_SEC": "5", "VMN_EXP_HEARTBEAT_SEC": "7", "VMN_EXP_SYNC_SEC": "9",
        "VMN_EXPERIMENT_DIR": "/process/dir", "VMN_EXP_OFFLINE": "1",
        "VMN_EXP_ALERT_ON": "failed", "VMN_EXP_ALERT_COMMAND": "./process.sh",
    }.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("value, expected", [
    (None, status.MIN_STALE_SEC),
    ("8", 8.0),
    ("-1", status.MIN_STALE_SEC),
    ("nan", status.MIN_STALE_SEC),
    ("soon", status.MIN_STALE_SEC),
])
def test_min_stale_sec_from_the_given_env_and_default(value, expected):
    env = FakeEnv({} if value is None else {"VMN_EXP_MIN_STALE_SEC": value})

    assert status.min_stale_sec(env) == expected


def test_run_cadences_come_from_the_given_env_before_the_conf():
    env = FakeEnv({"VMN_EXP_HEARTBEAT_SEC": "3", "VMN_EXP_SYNC_SEC": "4"})
    conf = {"heartbeat_interval_sec": 11, "sync_interval_sec": 12}

    assert run_intervals.resolve_heartbeat_sec(None, env, conf) == 3
    assert run_intervals.resolve_sync_sec(None, env, conf) == 4
    assert run_intervals.resolve_heartbeat_sec(None, FakeEnv(), conf) == 11
    assert run_intervals.resolve_sync_sec(None, FakeEnv(), conf) == 12


def test_experiment_dir_falls_back_to_the_given_envs_dir():
    assert storage_resolve.experiment_dir(None, {}, FakeEnv({"VMN_EXPERIMENT_DIR": "/env/dir"})) == "/env/dir"
    assert storage_resolve.experiment_dir(None, {}, FakeEnv()) is None


def test_only_the_given_envs_offline_mode_drops_the_remote():
    params = {"store": "s3://b/root", "experiment_dir": "/d"}

    assert storage_resolve.drop_remote_if_offline(params, "/d", FakeEnv()) == params
    assert storage_resolve.drop_remote_if_offline(
        params, "/d", FakeEnv({"VMN_EXP_OFFLINE": "1"})) == {"experiment_dir": "/d"}


def test_alert_sinks_and_triggers_come_from_the_given_env():
    env = FakeEnv({"VMN_EXP_ALERT_ON": "stuck,alert", "VMN_EXP_ALERT_WEBHOOK_URL": "https://hook"})

    config = load_alert_config("app", exp_conf={}, env=env)
    bare = load_alert_config("app", exp_conf={}, env=FakeEnv())

    assert config.on == {"stuck", "alert"} and len(config.sinks) == 1
    assert bare.on == {"alert"} and bare.sinks == []


def _running_state(beat):
    return {"state": "running", "started_at": beat.isoformat(), "heartbeat": beat.isoformat(),
            "heartbeat_interval_sec": BEAT_SEC}


def test_derivation_takes_the_floor_as_a_value_not_from_the_process_env():
    state = _running_state(LATER)
    later = LATER + timedelta(seconds=SILENT_SEC)

    assert status.stale_after_sec(state) == status.MIN_STALE_SEC
    assert status.stale_after_sec(state, min_stale_sec=600) == 600
    assert status.derive_status(state, now=later) == status.STUCK
    assert status.derive_status(state, now=later, min_stale_sec=600) == status.RUNNING
    assert status.status_fields(state, now=later, min_stale_sec=600)["status"] == status.RUNNING


def _io(env, clock):
    return IO(clock=clock, env=env, processes=FakeProcesses(), random=FakeRandom(),
              host=FakeHost(), console=FakeConsole())


def _live_store(tmp_path, clock):
    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    v = seed(storage, APP, verstr(1))
    storage.save_file(APP, v, "run_state.yml", "".join(
        f"{key}: '{value}'\n" for key, value in _running_state(clock.now()).items()))
    return storage


def _board_statuses_after_silence(tmp_path, env):
    init_stamp_logger()
    clock = FakeClock(start=LATER)
    _live_store(tmp_path, clock)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("st", f"file://{tmp_path / 'store'}")
    deps = real_deps(_io(env, clock), control_plane=None, background_refresh=False,
                     read_only=False, keep_warm=None)
    client = TestClient(build_app(manager, deps))
    clock.advance(SILENT_SEC)
    rows = client.get(f"/api/v1/workspaces/st/apps/{APP}/experiments",
                      params={"limit": 10}).json()["rows"]
    return {row["status"] for row in rows}


def test_a_board_row_turns_stuck_at_the_given_envs_floor(tmp_path):
    assert _board_statuses_after_silence(tmp_path / "default", FakeEnv()) == {status.STUCK}
    assert _board_statuses_after_silence(tmp_path / "wide", WIDE) == {status.RUNNING}


def _cli_listed_status_after_silence(tmp_path, env, monkeypatch):
    init_stamp_logger()
    clock = FakeClock(start=LATER)
    storage = _live_store(tmp_path, clock)
    monkeypatch.setattr(experiment, "_open_checked_storage", lambda *a, **k: storage)
    io = _io(env, clock)
    clock.advance(SILENT_SEC)
    args = parse_user_commands(["exp", "list", APP])
    assert experiment.handle_experiment(SimpleNamespace(vcs=None, args=args), io) == 0
    return io.console.stdout.split()[2]


def test_a_cli_list_turns_stuck_at_the_given_envs_floor(tmp_path, monkeypatch):
    listed = lambda env, sub: _cli_listed_status_after_silence(  # noqa: E731
        tmp_path / sub, env, monkeypatch)

    assert listed(FakeEnv(), "default") == status.STUCK
    assert listed(WIDE, "wide") == status.RUNNING


def test_an_elected_index_answers_its_current_indexs_floor():
    """A Postgres replica's resync builds its fresh index on the floor of the
    live (elected) one, so that index tells its floor like ExperimentIndex does."""
    from vmn_exp.ui.elected_index import ElectedIndex
    elected = ElectedIndex.__new__(ElectedIndex)
    elected._leader = SimpleNamespace(min_stale_sec=600.0)
    elected._follower = SimpleNamespace(min_stale_sec=600.0)
    elected.leading = False
    assert elected.min_stale_sec == 600.0
