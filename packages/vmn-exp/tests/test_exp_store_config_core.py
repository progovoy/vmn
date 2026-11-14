"""The SDK resolves the store through ``version_stamp.store.config`` (plan 37 P7).

One precedence table for core and vmn-exp: the flags, then ``VMN_STORE*``,
then ``VMN_EXPERIMENT_*``, then conf ``store``, then the legacy conf
``experiment.storage``. A ``vmn stamp`` moves ``experiment.storage``'s store
keys to ``store`` (``writer_id``/``experiment_dir`` stay), so vmn-exp must
read both. The SDK reads ``os.environ`` itself, hence ``monkeypatch``.
"""
from types import SimpleNamespace

import pytest
from version_stamp.store.config import resolve_store_uri

from vmn_exp.core.storage_resolve import drop_remote_if_offline, store_uri
from vmn_exp.core.writer import merge_conf_into_params, merge_env_into_params
from vmn_exp.storage.uri import s3_uri

ENV_KEYS = (
    "VMN_STORE", "VMN_STORE_BUCKET", "VMN_STORE_PREFIX", "VMN_STORE_ENDPOINT_URL",
    "VMN_EXPERIMENT_STORE", "VMN_EXPERIMENT_BUCKET", "VMN_EXPERIMENT_PREFIX",
    "VMN_EXPERIMENT_ENDPOINT_URL", "VMN_EXP_OFFLINE",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _set_env(monkeypatch, env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def _vcs(conf):
    """A vcs as core loads it: conf ``store`` and ``experiment`` attributes."""
    return SimpleNamespace(store=conf.get("store") or {},
                           experiment=conf.get("experiment") or {})


def _sdk_uri(params, conf, root="/local/root"):
    params = dict(params)
    merge_conf_into_params(_vcs(conf), params)
    return store_uri(drop_remote_if_offline(params, root))


def test_conf_store_uri_alone_names_the_store():
    params = {}
    merge_conf_into_params(_vcs({"store": {"uri": "s3://b/p"}}), params)
    assert store_uri(params) == "s3://b/p"


def test_conf_store_bucket_shorthand():
    conf = {"store": {"bucket": "b", "prefix": "team", "endpoint_url": "http://m"}}
    assert _sdk_uri({}, conf) == s3_uri("b", "team", "http://m")


def test_conf_store_beats_legacy_experiment_storage():
    conf = {"store": {"uri": "s3://new/p"},
            "experiment": {"storage": {"uri": "s3://old/p"}}}
    assert _sdk_uri({}, conf) == "s3://new/p"


def test_legacy_experiment_storage_still_names_the_store():
    assert _sdk_uri({}, {"experiment": {"storage": {"uri": "gs://old/p"}}}) == "gs://old/p"


def test_a_vcs_without_a_store_attribute_reads_experiment_storage():
    params = {}
    merge_conf_into_params(SimpleNamespace(experiment={"storage": {"uri": "gs://x"}}), params)
    assert params["store"] == "gs://x"


def test_writer_id_and_experiment_dir_still_come_from_experiment_storage():
    conf = {"store": {"uri": "s3://b/p"},
            "experiment": {"storage": {"writer_id": "ci", "experiment_dir": "/d"}}}
    params = {}
    merge_conf_into_params(_vcs(conf), params)
    assert (params["writer_id"], params["experiment_dir"]) == ("ci", "/d")


def test_writer_id_is_not_read_from_the_store_section():
    params = {}
    merge_conf_into_params(_vcs({"store": {"uri": "s3://b/p", "writer_id": "x"}}), params)
    assert not params.get("writer_id")


def test_vmn_store_beats_vmn_experiment_store(monkeypatch):
    _set_env(monkeypatch, {"VMN_STORE": "s3://new/p", "VMN_EXPERIMENT_STORE": "s3://old/p"})
    params = {}
    merge_env_into_params(params)
    assert params["store"] == "s3://new/p"


def test_vmn_store_bucket_shorthand(monkeypatch):
    _set_env(monkeypatch, {"VMN_STORE_BUCKET": "b", "VMN_STORE_PREFIX": "team",
                           "VMN_STORE_ENDPOINT_URL": "http://m"})
    params = {}
    merge_env_into_params(params)
    assert store_uri(params) == s3_uri("b", "team", "http://m")


def test_vmn_store_bucket_beats_vmn_experiment_bucket(monkeypatch):
    _set_env(monkeypatch, {"VMN_STORE_BUCKET": "new", "VMN_EXPERIMENT_BUCKET": "old"})
    params = {}
    merge_env_into_params(params)
    assert params["bucket"] == "new"


def test_vmn_store_beats_conf_store(monkeypatch):
    _set_env(monkeypatch, {"VMN_STORE": "s3://env/p"})
    assert _sdk_uri({}, {"store": {"uri": "s3://conf/p"}}) == "s3://env/p"


def test_merge_env_adds_no_unset_keys(monkeypatch):
    _set_env(monkeypatch, {"VMN_STORE_BUCKET": "b"})
    params = {"prefix": "custom"}
    merge_env_into_params(params)
    assert params == {"prefix": "custom", "bucket": "b"}


def test_offline_drops_a_vmn_store(monkeypatch):
    _set_env(monkeypatch, {"VMN_STORE": "s3://b/p", "VMN_EXP_OFFLINE": "1"})
    assert _sdk_uri({}, {"store": {"uri": "s3://c/p"}}) is None


def test_offline_without_a_local_root_still_raises(monkeypatch):
    _set_env(monkeypatch, {"VMN_EXP_OFFLINE": "yes"})
    with pytest.raises(ValueError, match="VMN_EXP_OFFLINE"):
        drop_remote_if_offline({"store": "s3://b/p"}, None)


# (flags, env, conf): installing vmn-exp never moves snapshots — the SDK
# resolves the store core's ``vmn snapshot`` does.
CASES = [
    ({}, {}, {}),
    ({"store": "s3://flag/p"}, {"VMN_STORE": "s3://env/p"}, {}),
    ({}, {"VMN_EXPERIMENT_STORE": "s3://old/p"}, {"store": {"uri": "s3://conf/p"}}),
    ({}, {}, {"store": {"uri": "file:///shared"}}),
    ({}, {}, {"experiment": {"storage": {"uri": "gs://legacy"}}}),
    ({}, {}, {"store": {"bucket": "b"}, "experiment": {"storage": {"uri": "s3://x/y"}}}),
    ({}, {"VMN_STORE_PREFIX": "team"}, {"experiment": {"storage": {"bucket": "b"}}}),
    ({"bucket": "flag"},
     {"VMN_STORE_BUCKET": "env", "VMN_EXPERIMENT_ENDPOINT_URL": "http://m"}, {}),
    ({}, {"VMN_STORE_BUCKET": "new", "VMN_EXPERIMENT_BUCKET": "old"}, {}),
    ({}, {"VMN_STORE": "", "VMN_EXPERIMENT_STORE": "s3://old/p"}, {}),
    ({}, {"VMN_STORE": "s3://b/p", "VMN_EXP_OFFLINE": "on"}, {"store": {"uri": "s3://c/p"}}),
    ({}, {"VMN_EXP_OFFLINE": "0"}, {"store": {"uri": "s3://c/p"}}),
    ({}, {}, {"store": None, "experiment": {"storage": None}}),
]


@pytest.mark.parametrize("params,env,conf", CASES)
def test_sdk_resolves_the_store_core_does(monkeypatch, params, env, conf):
    _set_env(monkeypatch, env)
    assert _sdk_uri(params, conf) == resolve_store_uri(params, env, conf)
