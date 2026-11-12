"""The per-host dirs resolve from the Env they are given (plan 44 G12 stage C)."""
import os

import pytest

from fakes.env import FakeEnv
from vmn_exp.storage import host_dirs


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
