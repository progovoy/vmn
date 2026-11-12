"""The SDK's app-name default, snapshot mode, sweep params, visible GPUs,
adoption offer, opt-outs and final-upload timeouts read the Env they are
given (plan 44 G12)."""
from types import SimpleNamespace

import pytest

from fakes.clock import FakeClock
from fakes.env import FakeEnv
from fakes.host import FakeHost
from fakes.random import FakeRandom
from vmn_exp.sdk import _resolve_app_name, guest_run, reader, resume, sweep, sysmetrics
from vmn_exp.sdk import run as run_module
from vmn_exp.sdk.adoption import ADOPT_PID_ENV, ADOPT_RUN_ID_ENV
from vmn_exp.sdk.create import SNAPSHOT_METADATA_ENV
from vmn_exp.sdk.sysmetrics_gpu import _visible_handles
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"


@pytest.fixture(autouse=True)
def _process_env_says_otherwise(monkeypatch):
    for name, value in {"VMN_APP_NAME": "process_app", "VMN_SWEEP_PARAMS": '{"lr": 9}',
                        "CUDA_VISIBLE_DEVICES": "0", "VMN_SYSTEM_METRICS": "0",
                        run_module.FINAL_UPLOAD_TIMEOUT_ENV: "99"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(SNAPSHOT_METADATA_ENV, raising=False)


def _snapshot_meta(tmp_path):
    path = tmp_path / "vmn_metadata.yml"
    path.write_text(f"app_name: {APP}\n")
    return str(path)


def _storage(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path / "s"), "runs")
    storage.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return storage


def test_app_name_defaults_to_the_given_envs_VMN_APP_NAME():
    assert _resolve_app_name(None, lambda: [], FakeEnv({"VMN_APP_NAME": "given"})) == "given"
    assert _resolve_app_name(None, lambda: ["only"], FakeEnv()) == "only"


def test_reader_app_candidates_come_from_the_given_envs_snapshot(tmp_path):
    storage = SimpleNamespace(list_apps=lambda: ["stored"])
    env = FakeEnv({SNAPSHOT_METADATA_ENV: _snapshot_meta(tmp_path)})

    assert reader._app_candidates(storage, env) == [APP]
    assert reader._app_candidates(storage, FakeEnv()) == ["stored"]


def test_locate_takes_snapshot_mode_from_the_given_env(tmp_path):
    env = FakeEnv({SNAPSHOT_METADATA_ENV: _snapshot_meta(tmp_path)})

    app_name, _, verstr, _, exp_conf = resume.locate(None, VERSTR, _storage(tmp_path), env=env)

    assert (app_name, verstr, exp_conf) == (APP, VERSTR, {})


def test_sweep_params_come_from_the_given_env():
    assert sweep.params_from(FakeEnv({sweep.SWEEP_PARAMS_ENV: '{"lr": 1}'})) == {"lr": 1}
    assert sweep.params_from(FakeEnv()) == {}


def test_visible_gpus_come_from_the_given_env():
    pynvml = SimpleNamespace(nvmlDeviceGetCount=lambda: 2,
                             nvmlDeviceGetHandleByIndex=lambda i: f"gpu{i}")

    assert _visible_handles(pynvml, FakeEnv({"CUDA_VISIBLE_DEVICES": "1"})) == ["gpu1"]
    assert _visible_handles(pynvml, FakeEnv()) == ["gpu0", "gpu1"]


def test_system_metrics_opt_out_reads_the_given_env():
    assert sysmetrics.enabled(None, {}, env=FakeEnv()) is True
    assert sysmetrics.enabled(None, {}, env=FakeEnv({sysmetrics.SYSTEM_METRICS_ENV: "0"})) is False


def test_the_adoption_offer_is_read_from_the_given_env_and_consumed_through_consume():
    env = FakeEnv({ADOPT_RUN_ID_ENV: VERSTR, ADOPT_PID_ENV: "7"})
    consumed, located = [], []

    def locate(app_name, ref, storage, action, env):
        located.append(env)
        return app_name, storage, ref, {}, {"k": 1}

    got = guest_run.adopted_record(APP, "storage", None, False, None, None, env, lambda: 7,
                                   locate, consumed.extend)

    assert got == (APP, "storage", VERSTR, {"k": 1})
    assert consumed == [ADOPT_RUN_ID_ENV, ADOPT_PID_ENV] and located == [env]


def test_a_snapshot_run_has_no_checkout_relative_cwd():
    assert run_module._checkout_relative_cwd(FakeEnv({SNAPSHOT_METADATA_ENV: "meta.yml"})) is None


def test_final_upload_timeouts_read_the_given_env():
    env = FakeEnv({run_module.FINAL_UPLOAD_TIMEOUT_ENV: "7"})

    assert run_module.final_upload_timeout_sec(env) == 7
    assert run_module.sigterm_timeout_sec(env) == 7
    assert run_module.final_upload_timeout_sec(FakeEnv()) == run_module.FINAL_REMOTE_TIMEOUT_SEC


def test_a_runs_final_deadline_uses_the_runs_env(tmp_path):
    clock = FakeClock(monotonic=1000.0)
    run = run_module.Run(_storage(tmp_path), APP, VERSTR, 3600,
                         env=FakeEnv({run_module.FINAL_UPLOAD_TIMEOUT_ENV: "7"}),
                         install_hooks=None, clock=clock, host=FakeHost(), random=FakeRandom())

    assert run._final_deadline() == 1007.0
