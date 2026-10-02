import argparse

import pytest

pytest.importorskip("fastapi")

from vmn_exp.ui.control_plane import SQLiteControlPlane
from vmn_exp.ui.workspaces import (
    DbWorkspaceRegistry,
    WorkspaceManager,
    YamlWorkspaceRegistry,
)


def test_default_registry_is_yaml_file(tmp_path):
    m = WorkspaceManager(str(tmp_path))
    assert isinstance(m.registry, YamlWorkspaceRegistry)
    m.add_store("s", "file:///x")
    assert (tmp_path / "workspaces.yml").exists()


def test_db_registry_persists_across_managers(tmp_path):
    cp = SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    m = WorkspaceManager(str(tmp_path / "d"), registry=DbWorkspaceRegistry(cp))
    m.add_store("s", "file:///x")
    m.add_store("t", "file:///y")
    m.remove("t")
    assert not (tmp_path / "d" / "workspaces.yml").exists()
    cp2 = SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    m2 = WorkspaceManager(str(tmp_path / "d"), registry=DbWorkspaceRegistry(cp2))
    assert [(w.name, w.store) for w in m2.list()] == [("s", "file:///x")]


def _cfg_args(tmp_path, text, **kw):
    p = tmp_path / "server.yml"
    p.write_text(text)
    base = dict(host="127.0.0.1", port=8265, token=None, data_dir=None, db=None,
                config=str(p), repo=None, store=None)
    base.update(kw)
    return argparse.Namespace(**base)


SEED = """
data_dir: {data}
workspaces:
  - {{name: ml-team, store: "file:///tmp/s", downloads: redirect, reconcile_sec: 60}}
"""


def test_config_seeds_workspaces_into_sqlite_under_data_dir(tmp_path):
    from vmn_exp.ui.cli import build_server

    args = _cfg_args(tmp_path, SEED.format(data=tmp_path / "data"))
    manager, cfg, _cp = build_server(args, env={})
    ws = manager.get("ml-team")
    assert (ws.kind, ws.store, ws.downloads, ws.reconcile_sec) == (
        "store", "file:///tmp/s", "redirect", 60)
    assert (tmp_path / "data" / "control_plane.sqlite3").exists()
    assert not (tmp_path / "data" / "workspaces.yml").exists()
    # Re-seeding on restart is a no-op and keeps UI-added workspaces.
    manager.add_store("extra", "file:///e")
    manager2, _, _ = build_server(args, env={})
    assert sorted(w.name for w in manager2.list()) == ["extra", "ml-team"]


def test_db_flag_uses_that_sqlite_file(tmp_path):
    from vmn_exp.ui.cli import build_server

    db = tmp_path / "cp.db"
    args = argparse.Namespace(host="127.0.0.1", port=8265, token=None,
                              data_dir=str(tmp_path / "d"), db=f"sqlite:///{db}",
                              config=None, repo=None, store="file:///z")
    manager, cfg, _ = build_server(args, env={})
    assert db.exists()
    assert [w.store for w in manager.list()] == ["file:///z"]


def test_unsupported_db_scheme_errors(tmp_path):
    from vmn_exp.ui.cli import build_server
    from vmn_exp.ui.config import ConfigError

    args = _cfg_args(tmp_path, f"data_dir: {tmp_path / 'd'}\ndb: mysql://x\n")
    with pytest.raises(ConfigError):
        build_server(args, env={})


def test_no_config_keeps_yaml_registry(tmp_path):
    from vmn_exp.ui.cli import build_server

    args = argparse.Namespace(host="127.0.0.1", port=8265, token=None,
                              data_dir=str(tmp_path / "d"), db=None, config=None,
                              repo=None, store="file:///z")
    manager, cfg, cp = build_server(args, env={})
    assert cfg is None and cp is None
    assert isinstance(manager.registry, YamlWorkspaceRegistry)


def test_oidc_and_role_mappings_wired_on_app_state(tmp_path):
    from vmn_exp.ui.auth.oidc import OIDCAuthenticator
    from vmn_exp.ui.cli import build_server, server_app

    text = f"""
data_dir: {tmp_path / 'data'}
server: {{public_url: "https://vmn.acme.com/"}}
auth:
  oidc: {{issuer: "https://idp", client_id: c, client_secret_env: SEC}}
  role_mappings: [{{group: g, workspace: "*", role: admin}}]
"""
    args = _cfg_args(tmp_path, text, read_only=False, no_index=True, allowed_host=None)
    env = {"SEC": "shh"}
    manager, cfg, cp = build_server(args, env=env)
    app = server_app(manager, cfg, cp, args, env=env)
    assert app.state.role_mappings[0].group == "g"
    oidc = [a for a in app.state.auth_chain.authenticators
            if isinstance(a, OIDCAuthenticator)]
    assert oidc[0].config.redirect_uri == "https://vmn.acme.com/auth/callback"
    assert oidc[0].config.client_secret == "shh"
    assert oidc[0].config.role_mappings == [{"group": "g", "workspace": "*", "role": "admin"}]


def test_ui_parser_accepts_config_and_db():
    from version_stamp.cli.args import parse_user_commands

    args = parse_user_commands(["ui", "--config", "/s.yml", "--db", "sqlite:///x"])
    assert args.config == "/s.yml" and args.db == "sqlite:///x"
    assert parse_user_commands(["ui"]).config is None
