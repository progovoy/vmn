"""Readers resolve the store over the writer's precedence (plan 45): flags,
``VMN_STORE*``, ``VMN_EXPERIMENT_*``, then the app's conf ``store`` and the
legacy ``experiment.storage``. Outside a checkout there is no conf: the
environment alone names the store."""
import pytest

from fakes.clock import FakeClock
from fakes.env import FakeEnv
from vmn_exp.core.app_conf import read_app_conf
from vmn_exp.core.storage_resolve import resolve_experiment_storage
from vmn_exp.storage.local import LocalSnapshotStorage

VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"


def _store_with(tmp_path, name, app):
    """A file:// store under *tmp_path* holding one run of *app*."""
    root = tmp_path / name
    LocalSnapshotStorage(str(root), "runs").save(
        app, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return root.as_uri()


def _apps(conf, env=None, **flags):
    storage = resolve_experiment_storage(repo_root=False, conf=conf, clock=FakeClock(),
                                         env=FakeEnv(env), **flags)
    return storage.list_apps()


def test_conf_store_names_the_store(tmp_path):
    assert _apps({"store": {"uri": _store_with(tmp_path, "conf", "app")}}) == ["app"]


def test_legacy_experiment_storage_names_the_store(tmp_path):
    conf = {"experiment": {"storage": {"uri": _store_with(tmp_path, "legacy", "app")}}}
    assert _apps(conf) == ["app"]


def test_conf_store_beats_legacy_experiment_storage(tmp_path):
    conf = {"store": {"uri": _store_with(tmp_path, "new", "new_app")},
            "experiment": {"storage": {"uri": _store_with(tmp_path, "old", "old_app")}}}
    assert _apps(conf) == ["new_app"]


@pytest.mark.parametrize("name", ["VMN_STORE", "VMN_EXPERIMENT_STORE"])
def test_env_beats_conf(tmp_path, name):
    conf = {"store": {"uri": _store_with(tmp_path, "conf", "conf_app")}}
    env = {name: _store_with(tmp_path, "env", "env_app")}
    assert _apps(conf, env) == ["env_app"]


def test_flag_beats_env_and_conf(tmp_path):
    conf = {"store": {"uri": _store_with(tmp_path, "conf", "conf_app")}}
    env = {"VMN_STORE": _store_with(tmp_path, "env", "env_app")}
    assert _apps(conf, env, store=_store_with(tmp_path, "flag", "flag_app")) == ["flag_app"]


def test_without_conf_the_env_alone_names_the_store(tmp_path):
    env = {"VMN_STORE": _store_with(tmp_path, "env", "env_app")}
    assert _apps({}, env) == ["env_app"]


def test_without_conf_env_or_checkout_there_is_no_store():
    with pytest.raises(ValueError, match="No experiment storage"):
        _apps({})


def test_read_app_conf_is_the_conf_mapping_of_the_apps_conf_yml(tmp_path):
    conf_dir = tmp_path / ".vmn" / "root" / "svc"
    conf_dir.mkdir(parents=True)
    (conf_dir / "conf.yml").write_text("conf:\n  store:\n    uri: s3://b/p\n")
    assert read_app_conf("root/svc", str(tmp_path)) == {"store": {"uri": "s3://b/p"}}


def test_read_app_conf_is_empty_without_a_conf_yml(tmp_path):
    assert read_app_conf("app", str(tmp_path)) == {}
