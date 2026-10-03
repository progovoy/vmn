"""auth.role_mappings from server.yml reach role checks intact (no 500)."""
import argparse

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402
from vmn_exp.ui.auth.oidc import SESSION_COOKIE, OIDCAuthenticator  # noqa: E402
from vmn_exp.ui.auth.principal import Principal  # noqa: E402
from vmn_exp.ui.cli import build_server, server_app  # noqa: E402


def _app(tmp_path):
    storage = open_storage(f"file://{tmp_path / 'store'}", area=RUNS)
    storage.save("app", "0.0.1-dev.abc.r1", {"verstr": "0.0.1-dev.abc.r1"}, {})
    p = tmp_path / "server.yml"
    p.write_text(f"""
data_dir: {tmp_path / 'data'}
server: {{public_url: "https://vmn.acme.com/"}}
workspaces:
  - {{name: ml, store: "file://{tmp_path / 'store'}"}}
auth:
  oidc: {{issuer: "https://idp", client_id: c}}
  role_mappings: [{{group: g, workspace: ml, role: viewer}}]
""")
    args = argparse.Namespace(host="127.0.0.1", port=8265, token=None, data_dir=None,
                              db=None, config=str(p), repo=None, store=None,
                              read_only=False, no_index=True, allowed_host=None)
    manager, cfg, cp = build_server(args, env={})
    return server_app(manager, cfg, cp, args, env={}, token="t")


def test_static_token_on_viewer_route_with_role_mappings(tmp_path):
    client = TestClient(_app(tmp_path))
    resp = client.get("/api/v1/workspaces/ml/apps", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200


def test_group_mapped_oidc_principal_gets_its_role(tmp_path):
    app = _app(tmp_path)
    oidc = [a for a in app.state.auth_chain.authenticators
            if isinstance(a, OIDCAuthenticator)][0]
    sid = oidc.sessions.open(Principal("u", "u", {}, groups=("g",)))
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, sid)
    assert client.get("/api/v1/workspaces/ml/apps").status_code == 200
    assert client.get("/api/v1/workspaces/other/apps").status_code == 403
