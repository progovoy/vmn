"""``vmn-exp buffers ship`` finds its store in the environment the way the
rest of vmn-exp does (``VMN_STORE*`` first, then the legacy twins)."""
from vmn_exp.cli.buffers_cmd import store_from_env


def test_vmn_store_names_the_store():
    assert store_from_env({"VMN_STORE": "s3://b/p"}) == "s3://b/p"


def test_vmn_store_wins_over_the_legacy_name():
    env = {"VMN_STORE": "s3://new", "VMN_EXPERIMENT_STORE": "s3://old"}
    assert store_from_env(env) == "s3://new"


def test_the_legacy_name_still_works():
    assert store_from_env({"VMN_EXPERIMENT_STORE": "s3://old"}) == "s3://old"


def test_the_bucket_shorthand_names_an_s3_store():
    assert store_from_env({"VMN_STORE_BUCKET": "b", "VMN_STORE_PREFIX": "p"}) == "s3://b/p"


def test_no_store_in_the_environment():
    assert store_from_env({}) is None
