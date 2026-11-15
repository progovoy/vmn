"""The writer id, offline mode and the storage params a pod sets come from the
Env and host they are given (plan 44 G12 stage C): a value only in the
process environment is never read."""
import pytest

from fakes.env import FakeEnv
from fakes.host import FakeHost
from vmn_exp.core import writer


@pytest.fixture(autouse=True)
def _process_env_says_otherwise(monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "process-writer")
    monkeypatch.setenv("HOSTNAME", "process-host")
    monkeypatch.setenv("VMN_EXP_OFFLINE", "1")
    monkeypatch.setenv("VMN_EXPERIMENT_BUCKET", "process-bucket")
    writer._WRITER_ID = None


@pytest.mark.parametrize("env, conf, expected", [
    (FakeEnv({"VMN_WRITER_ID": "pod-1", "HOSTNAME": "env-host"}), "conf-writer", "pod-1"),
    (FakeEnv({"HOSTNAME": "env-host"}), "conf-writer", "conf-writer"),
    (FakeEnv({"HOSTNAME": "env-host"}), None, "env-host"),
    (FakeEnv(), None, "fake-host"),
])
def test_writer_id_priority_env_then_conf_then_hostname(env, conf, expected):
    assert writer.get_writer_id(env, FakeHost(hostname="fake-host"), conf) == expected


def test_writer_id_is_resolved_once_then_cached():
    first = writer.get_writer_id(FakeEnv({"VMN_WRITER_ID": "first"}), FakeHost())
    later = writer.get_writer_id(FakeEnv({"VMN_WRITER_ID": "later"}), FakeHost())

    assert (first, later) == ("first", "first")


def test_a_default_writer_id_yields_only_to_the_given_envs_writer_id():
    assert writer.set_default_writer_id(FakeEnv(), "server") == "server"
    assert writer.set_default_writer_id(FakeEnv({"VMN_WRITER_ID": "pod-1"}), "server") == "pod-1"


def test_offline_mode_reads_the_given_env():
    assert writer.offline_mode(FakeEnv()) is False
    assert writer.offline_mode(FakeEnv({"VMN_EXP_OFFLINE": "yes"})) is True


def test_env_params_fill_only_missing_keys():
    params = {"store": "s3://flag/root", "bucket": None}
    env = FakeEnv({"VMN_EXPERIMENT_STORE": "s3://env/root", "VMN_EXPERIMENT_PREFIX": "runs"})

    writer.merge_env_into_params(params, env)

    assert params == {"store": "s3://flag/root", "bucket": None, "prefix": "runs"}


@pytest.mark.parametrize("env, expected", [
    (FakeEnv({"VMN_WRITER_ID": "pod-1"}), "pod-1"),
    (FakeEnv({"VMN_EXP_OFFLINE": "1"}), "fake-host"),
    (FakeEnv(), None),
])
def test_run_suffix_reads_the_given_env(env, expected):
    assert writer.default_run_suffix(env, FakeHost(hostname="fake-host")) == expected
