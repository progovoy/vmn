"""Workspace store URI allowlist in multi tenancy (plan 11 §6.3, SSRF guard)."""
import pytest

from vmn_exp.ui.config import parse_config
from vmn_exp.ui.workspaces import WorkspaceError, WorkspaceManager


def _multi(tmp_path, endpoints=()):
    return WorkspaceManager(str(tmp_path), tenancy="multi", endpoint_allowlist=endpoints)


@pytest.mark.parametrize("uri", ["s3://b/p", "gs://b/p", "az://acct/c/p"])
def test_cloud_schemes_are_allowed(tmp_path, uri):
    assert _multi(tmp_path).add_store("w", uri).store == uri


@pytest.mark.parametrize("uri", ["file:///etc", "myplugin://x/y", "http://169.254.169.254/"])
def test_other_schemes_are_refused(tmp_path, uri):
    manager = _multi(tmp_path)
    with pytest.raises(WorkspaceError):
        manager.add_store("w", uri)
    assert manager.get("w") is None


def test_endpoint_url_must_be_allowlisted(tmp_path):
    manager = _multi(tmp_path, endpoints=("https://minio.example",))
    manager.add_store("ok", "s3://b/p?endpoint_url=https://minio.example")
    with pytest.raises(WorkspaceError):
        manager.add_store("bad", "s3://b/p?endpoint_url=http://10.0.0.1:9000")


def test_single_tenancy_keeps_any_scheme(tmp_path):
    manager = WorkspaceManager(str(tmp_path))
    assert manager.add_store("w", f"file://{tmp_path}/s").kind == "store"


def test_server_config_carries_the_endpoint_allowlist():
    cfg = parse_config({"server": {"tenancy": "multi",
                                   "endpoint_allowlist": ["https://minio.example"]}})
    assert cfg.server.endpoint_allowlist == ("https://minio.example",)
