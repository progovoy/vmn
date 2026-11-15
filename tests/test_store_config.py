"""``version_stamp.store.config``: which store a command uses (plan 45 P4c).

Pure: params, env and conf are plain dicts. Mirrors the SDK's resolution
(``vmn_exp.core.writer.merge_conf_into_params`` + ``storage_resolve.store_uri``):
each store param is filled from the flags, then ``VMN_STORE*``, then
``VMN_EXPERIMENT_*``, then conf ``store``, then conf ``experiment.storage``; a
``store`` URI from any source beats the bucket shorthand.
"""
import pytest
from version_stamp.store.config import (
    drop_remote_if_offline,
    resolve_store,
    resolve_store_uri,
    store_options,
    store_params,
)

NO_CONF = {}


def _uri(params=None, env=None, conf=None):
    return resolve_store_uri(params or {}, env or {}, conf or NO_CONF)


def test_nothing_configured_means_the_repo_local_store():
    assert _uri() is None


def test_local_flag_wins_over_everything():
    env = {"VMN_STORE": "s3://env/p"}
    conf = {"store": {"uri": "s3://conf/p"}}
    assert _uri({"local": True, "store": "s3://flag/p"}, env, conf) is None


def test_store_flag_beats_env():
    assert _uri({"store": "s3://flag/p"}, {"VMN_STORE": "s3://env/p"}) == "s3://flag/p"


def test_vmn_store_beats_vmn_experiment_store():
    env = {"VMN_STORE": "s3://new/p", "VMN_EXPERIMENT_STORE": "s3://old/p"}
    assert _uri(env=env) == "s3://new/p"


def test_vmn_experiment_store_still_works():
    assert _uri(env={"VMN_EXPERIMENT_STORE": "gs://old/p"}) == "gs://old/p"


def test_empty_env_values_are_unset():
    env = {"VMN_STORE": "", "VMN_EXPERIMENT_STORE": "s3://old/p"}
    assert _uri(env=env) == "s3://old/p"


def test_env_store_beats_conf_store():
    conf = {"store": {"uri": "s3://conf/p"}}
    assert _uri(env={"VMN_STORE": "s3://env/p"}, conf=conf) == "s3://env/p"


def test_env_bucket_shorthand_defaults_the_prefix_to_vmn():
    assert _uri(env={"VMN_STORE_BUCKET": "b"}) == "s3://b/vmn"


def test_new_bucket_names_beat_the_old_ones():
    env = {
        "VMN_STORE_BUCKET": "new", "VMN_EXPERIMENT_BUCKET": "old",
        "VMN_STORE_PREFIX": "np", "VMN_EXPERIMENT_PREFIX": "op",
        "VMN_STORE_ENDPOINT_URL": "http://new:9000",
        "VMN_EXPERIMENT_ENDPOINT_URL": "http://old:9000",
    }
    assert _uri(env=env) == "s3://new/np?endpoint_url=http%3A%2F%2Fnew%3A9000"


def test_old_bucket_names_still_work():
    env = {"VMN_EXPERIMENT_BUCKET": "old", "VMN_EXPERIMENT_PREFIX": "op"}
    assert _uri(env=env) == "s3://old/op"


def test_store_uri_from_any_source_beats_the_bucket_shorthand():
    # As in the SDK: params are filled key by key, then ``store`` wins.
    conf = {"store": {"uri": "s3://conf/p"}}
    assert _uri(env={"VMN_STORE_BUCKET": "b"}, conf=conf) == "s3://conf/p"


def test_bucket_flags_beat_env_per_key():
    env = {"VMN_STORE_BUCKET": "envb", "VMN_STORE_PREFIX": "envp"}
    assert _uri({"bucket": "flagb"}, env) == "s3://flagb/envp"


def test_conf_store_uri():
    assert _uri(conf={"store": {"uri": "file:///shared"}}) == "file:///shared"


def test_conf_store_bucket_shorthand():
    conf = {"store": {"bucket": "b", "prefix": "p", "endpoint_url": "http://m"}}
    assert _uri(conf=conf) == "s3://b/p?endpoint_url=http%3A%2F%2Fm"


def test_conf_store_beats_experiment_storage():
    conf = {
        "store": {"uri": "s3://new/p"},
        "experiment": {"storage": {"uri": "s3://old/p"}},
    }
    assert _uri(conf=conf) == "s3://new/p"


def test_experiment_storage_uri_still_works():
    conf = {"experiment": {"storage": {"uri": "s3://old/p"}}}
    assert _uri(conf=conf) == "s3://old/p"


def test_experiment_storage_bucket_shorthand_still_works():
    conf = {"experiment": {"storage": {"bucket": "b"}}}
    assert _uri(conf=conf) == "s3://b/vmn"


def test_env_prefix_applies_to_a_conf_bucket():
    conf = {"store": {"bucket": "b", "prefix": "confp"}}
    assert _uri(env={"VMN_STORE_PREFIX": "envp"}, conf=conf) == "s3://b/envp"


def test_null_conf_sections_are_ignored():
    assert _uri(conf={"store": None, "experiment": None}) is None
    assert _uri(conf={"experiment": {"storage": None}}) is None


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_offline_drops_every_remote_source(value):
    env = {
        "VMN_EXP_OFFLINE": value,
        "VMN_STORE": "s3://env/p", "VMN_STORE_BUCKET": "b",
    }
    conf = {"store": {"uri": "s3://conf/p"},
            "experiment": {"storage": {"bucket": "old"}}}
    assert _uri({"store": "s3://flag/p"}, env, conf) is None


@pytest.mark.parametrize("value", ["", "0", "false", "no"])
def test_offline_falsy_keeps_the_remote(value):
    env = {"VMN_EXP_OFFLINE": value, "VMN_STORE": "s3://env/p"}
    assert _uri(env=env) == "s3://env/p"


def test_drop_remote_if_offline_keeps_other_params():
    params = {"store": "s3://x", "bucket": "b", "prefix": "p",
              "endpoint_url": "http://m", "local": False, "name": "app"}
    assert drop_remote_if_offline(params, {"VMN_EXP_OFFLINE": "1"}) == {
        "local": False, "name": "app",
    }
    assert drop_remote_if_offline(params, {}) is params


def test_store_params_merges_every_source():
    env = {"VMN_STORE_PREFIX": "envp"}
    conf = {"store": {"bucket": "b"},
            "experiment": {"storage": {"endpoint_url": "http://old"}}}
    assert store_params({"name": "app"}, env, conf) == {
        "name": "app", "store": None, "bucket": "b", "prefix": "envp",
        "endpoint_url": "http://old",
    }


def test_store_params_leaves_its_input_alone():
    params = {}
    store_params(params, {"VMN_STORE": "s3://x"}, NO_CONF)
    assert params == {}


def test_resolve_store_returns_the_endpoint_as_options():
    # Like the SDK's lent options: absolute s3:// reads need the endpoint
    # even when the store URI does not carry it.
    uri, options = resolve_store(
        {"store": "s3://b/p"}, {"VMN_STORE_ENDPOINT_URL": "http://m"}, NO_CONF
    )
    assert uri == "s3://b/p"
    assert options == {"s3": {"endpoint_url": "http://m"}}


def test_resolve_store_without_an_endpoint_has_no_options():
    assert resolve_store({}, {"VMN_STORE": "s3://b/p"}, NO_CONF) == ("s3://b/p", None)


def test_resolve_store_local_and_offline_have_no_options():
    env = {"VMN_STORE_ENDPOINT_URL": "http://m"}
    assert resolve_store({"local": True}, env, NO_CONF) == (None, None)
    offline = dict(env, VMN_EXP_OFFLINE="1")
    assert resolve_store({}, offline, NO_CONF) == (None, None)


def test_store_options_carry_a_configured_endpoint():
    assert store_options({"endpoint_url": "http://m"}) == {"s3": {"endpoint_url": "http://m"}}


def test_store_options_are_none_without_an_endpoint():
    assert store_options({"store": "s3://b/p"}) is None
