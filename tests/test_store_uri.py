"""Store URIs (``version_stamp.store.uri``): the parse cases of the vmn-exp
suite's packages/vmn-exp/tests/test_storage_uri_registry.py, against core."""
import pytest

from version_stamp.store.uri import parse_store_uri, s3_uri


def test_s3_uri_splits_bucket_and_prefix():
    uri = parse_store_uri("s3://my-bucket/team/exps/")
    assert (uri.scheme, uri.location, uri.path) == ("s3", "my-bucket", "team/exps")
    assert uri.options == {}


def test_bucket_only_uri_has_an_empty_path():
    assert parse_store_uri("gs://b").path == ""


def test_scheme_is_case_insensitive():
    assert parse_store_uri("S3://b/p").scheme == "s3"


def test_query_string_becomes_options():
    uri = parse_store_uri("s3://b/p?endpoint_url=http%3A%2F%2Flocalhost%3A9000")
    assert uri.options == {"endpoint_url": "http://localhost:9000"}


def test_file_uri_keeps_the_absolute_path():
    uri = parse_store_uri("file:///srv/nfs/exps")
    assert (uri.scheme, uri.path) == ("file", "/srv/nfs/exps")


def test_a_bare_path_is_a_file_store(tmp_path):
    uri = parse_store_uri(str(tmp_path))
    assert (uri.scheme, uri.path) == ("file", str(tmp_path))


@pytest.mark.parametrize("bad", ["s3://", "s3:///prefix", "file://host/x", ""])
def test_malformed_uris_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_store_uri(bad)


def test_s3_uri_builds_the_bucket_shorthand():
    assert s3_uri("b", "p") == "s3://b/p"
    uri = parse_store_uri(s3_uri("b", "p", endpoint_url="http://m:9000"))
    assert (uri.location, uri.path) == ("b", "p")
    assert uri.options == {"endpoint_url": "http://m:9000"}
