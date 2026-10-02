"""Storage URIs and the scheme registry: ``s3://``, ``file://``, ``gs://``,
``az://`` and third-party schemes declared under the ``vmn_exp.storage``
entry-point group."""
import builtins
import sys
from importlib.metadata import EntryPoint

import pytest

from vmn_exp.storage import registry
from vmn_exp.storage.uri import parse_store_uri, s3_uri


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    monkeypatch.setattr(registry, "_registered", {})
    monkeypatch.setattr(registry, "_entry_points_loaded", False)
    monkeypatch.setattr(registry, "_storage_entry_points", lambda: [])


# -- parsing ------------------------------------------------------------------


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


# -- the registry -------------------------------------------------------------


def test_file_store_opens_a_local_storage(tmp_path):
    from vmn_exp.storage.local import LocalSnapshotStorage

    store = registry.open_store(f"file://{tmp_path}", area="runs")
    assert isinstance(store, LocalSnapshotStorage)
    assert store.create_exclusive("app", "1.0.0-dev.a.b", {"verstr": "x"}, {})
    assert not store.create_exclusive("app", "1.0.0-dev.a.b", {"verstr": "x"}, {})


def test_unknown_scheme_names_the_known_ones():
    with pytest.raises(ValueError) as err:
        registry.open_store("nope://b/p")
    msg = str(err.value)
    assert "nope" in msg and "s3" in msg and "vmn_exp.storage" in msg


def test_register_store_adds_a_scheme():
    seen = []

    def factory(uri, area):
        seen.append((uri.location, uri.path, area))
        return "store"

    registry.register_store("mem", factory)
    assert registry.open_store("mem://x/y", area="snapshots") == "store"
    assert seen == [("x", "y", "snapshots")]


def test_entry_point_declares_a_scheme(monkeypatch):
    module = type(sys)("fake_vmn_store_plugin")
    module.make = lambda uri, area: ("plugin", uri.location)
    monkeypatch.setitem(sys.modules, "fake_vmn_store_plugin", module)
    ep = EntryPoint("mem", "fake_vmn_store_plugin:make", registry.ENTRY_POINT_GROUP)
    monkeypatch.setattr(registry, "_storage_entry_points", lambda: [ep])

    assert registry.open_store("mem://bkt") == ("plugin", "bkt")
    assert "mem" in registry.known_schemes()


def test_broken_entry_point_is_reported_with_its_target(monkeypatch):
    ep = EntryPoint("mem", "no.such.module_xyz:make", registry.ENTRY_POINT_GROUP)
    monkeypatch.setattr(registry, "_storage_entry_points", lambda: [ep])
    with pytest.raises(ImportError) as err:
        registry.open_store("mem://bkt")
    assert "no.such.module_xyz:make" in str(err.value)


def _hide_modules(monkeypatch, *prefixes):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith(prefixes):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


@pytest.mark.parametrize(
    "uri, extra, package",
    [
        ("gs://b/p", "gcs", "google-cloud-storage"),
        ("az://c/p", "azure", "azure-storage-blob"),
        ("s3://b/p", "s3", "boto3"),
    ],
)
def test_missing_sdk_names_the_extra(monkeypatch, uri, extra, package):
    _hide_modules(monkeypatch, "google.cloud", "azure", "boto3")
    with pytest.raises(ImportError) as err:
        registry.open_store(uri)
    assert f"vmn-exp-sdk[{extra}]" in str(err.value)
    assert package in str(err.value)
