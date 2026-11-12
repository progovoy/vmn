"""The per-host dirs resolve from the Env they are given (plan 44 G12 stage C)."""
import os

import pytest

from fakes.clock import FakeClock
from fakes.env import FakeEnv
from vmn_exp.cli.pushing.push_ledger import PushLedger
from vmn_exp.storage import azure, host_dirs, registry, s3_prefix_cap
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.storage.open import open_storage


@pytest.fixture(autouse=True)
def _process_env_says_otherwise(monkeypatch):
    monkeypatch.setenv("VMN_EXP_CACHE_DIR", "/process/cache")
    monkeypatch.setenv("VMN_INDEX_CACHE_DIR", "/process/index")


def test_cache_dir_env_overrides_the_default():
    given = FakeEnv({"VMN_EXP_CACHE_DIR": "/given"})

    assert host_dirs.cache_base(given) == "/given"
    assert host_dirs.state_base(given) == "/given"
    assert host_dirs.log_buffers_dir("store", given).startswith(os.path.join("/given", "log-buffers"))
    assert os.path.join("/given", "log-buffers") in host_dirs.log_buffers_bases(given)


def test_xdg_dirs_come_from_the_given_env():
    env = FakeEnv({"XDG_STATE_HOME": "/xdg-state"})

    assert host_dirs.state_base(env) == os.path.join("/xdg-state", "vmn-exp")
    assert host_dirs.push_ledger_dir("store", "remote", "app", env).startswith(
        os.path.join("/xdg-state", "vmn-exp", "push"))


def test_the_index_cache_dir_env_sets_or_disables_its_root():
    assert host_dirs.index_cache_root(FakeEnv({"VMN_INDEX_CACHE_DIR": "/idx"})) == "/idx"
    assert host_dirs.index_cache_root(FakeEnv({"VMN_INDEX_CACHE_DIR": "none"})) is None
    assert host_dirs.index_cache_path("store", "app", FakeEnv({"VMN_INDEX_CACHE_DIR": "none"})) is None


def test_a_local_store_keeps_its_index_cache_under_the_given_env(tmp_path):
    given = FakeEnv({"VMN_EXP_CACHE_DIR": str(tmp_path / "given")})
    storage = open_storage(root=str(tmp_path / "store"), area="runs", writer=False,
                           clock=FakeClock(), env=given)
    (tmp_path / "store" / "runs" / "app").mkdir(parents=True)

    assert storage.index_cache_path("app").startswith(str(tmp_path / "given"))


class _Remote:
    """Just enough of a remote store for open_storage to front with a log buffer."""

    def is_remote(self):
        return True

    def cache_identity(self):
        return ("fake-remote",)


def test_a_direct_to_bucket_writer_buffers_its_logs_under_the_given_env(tmp_path, monkeypatch):
    monkeypatch.setitem(registry._registered, "fakeremote", lambda uri, area: _Remote())
    given = FakeEnv({"VMN_EXP_CACHE_DIR": str(tmp_path / "given")})
    storage = open_storage("fakeremote://bkt/p", area="runs", buffer_logs=True, writer=False,
                           clock=FakeClock(), env=given)

    assert storage._buffers_dir.startswith(os.path.join(str(tmp_path / "given"), "log-buffers"))


def test_the_push_ledger_lives_under_the_given_env(tmp_path):
    local = LocalSnapshotStorage(str(tmp_path / "store"), "runs")
    ledger = PushLedger(local, "app", "rid", FakeEnv({"VMN_EXP_CACHE_DIR": "/given"}))

    assert ledger.dir.startswith(os.path.join("/given", "push"))


def test_the_s3_prefix_cap_reads_the_given_env():
    assert s3_prefix_cap.limit(FakeEnv({s3_prefix_cap.ENV: "7"})) == 7
    assert s3_prefix_cap.limit(FakeEnv()) == s3_prefix_cap.DEFAULT_PREFIX_CONCURRENCY
    cap = s3_prefix_cap._cap_of("given-env-bucket", "p", FakeEnv({s3_prefix_cap.ENV: "3"}))
    assert cap.limit == 3


class _Container:
    def __init__(self, account_url, name, credential=None):
        self.how = ("account_url", account_url, name)

    @classmethod
    def from_connection_string(cls, conn, name):
        made = cls(None, name)
        made.how = ("connection_string", conn, name)
        return made


def test_the_azure_account_comes_from_the_given_env():
    by_conn = azure._container_client(_Container, "ctr", None,
                                      FakeEnv({"AZURE_STORAGE_CONNECTION_STRING": "cs"}))
    by_url = azure._container_client(_Container, "ctr", None,
                                     FakeEnv({"AZURE_STORAGE_ACCOUNT_URL": "https://acct"}))

    assert by_conn.how == ("connection_string", "cs", "ctr")
    assert by_url.how == ("account_url", "https://acct", "ctr")
    with pytest.raises(ValueError):
        azure._container_client(_Container, "ctr", None, FakeEnv())
