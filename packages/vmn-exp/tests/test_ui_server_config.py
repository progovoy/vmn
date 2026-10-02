import argparse

import pytest

pytest.importorskip("fastapi")

from vmn_exp.ui.config import ConfigError, load_config, resolve_config

FULL = """
server:
  host: 0.0.0.0
  port: 9000
  public_url: https://vmn.acme.com
  tenancy: single
db: sqlite:///{db}
data_dir: {data}
auth:
  static_token_env: MY_TOKEN
  oidc:
    issuer: https://acme.okta.com
    client_id: vmn-exp
    client_secret_env: MY_SECRET
    groups_claim: groups
  role_mappings:
    - {{group: ml-admins, workspace: "*", role: admin}}
workspaces:
  - name: ml-team
    store: file:///tmp/s
    downloads: redirect
    reconcile_sec: 60
"""


def _write(tmp_path, text):
    p = tmp_path / "server.yml"
    p.write_text(text)
    return str(p)


def _full(tmp_path):
    return _write(tmp_path, FULL.format(db=tmp_path / "x.db", data=tmp_path / "data"))


def _args(**kw):
    base = dict(host="127.0.0.1", port=8265, token=None, data_dir=None, db=None, config=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_parses_every_key(tmp_path):
    cfg = load_config(_full(tmp_path))
    assert cfg.server.host == "0.0.0.0" and cfg.server.port == 9000
    assert cfg.server.public_url == "https://vmn.acme.com"
    assert cfg.server.tenancy == "single"
    assert cfg.db == f"sqlite:///{tmp_path / 'x.db'}"
    assert cfg.data_dir == str(tmp_path / "data")
    assert cfg.auth.static_token_env == "MY_TOKEN"
    assert cfg.auth.oidc.issuer == "https://acme.okta.com"
    assert cfg.auth.oidc.client_secret_env == "MY_SECRET"
    assert cfg.auth.role_mappings[0].group == "ml-admins"
    assert cfg.auth.role_mappings[0].workspace == "*"
    ws = cfg.workspaces[0]
    assert (ws.name, ws.store, ws.downloads, ws.reconcile_sec) == (
        "ml-team", "file:///tmp/s", "redirect", 60)
    with pytest.raises(Exception):
        cfg.db = "x"  # frozen


def test_empty_file_gives_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, ""))
    assert cfg.server.port == 8265 and cfg.db is None and cfg.workspaces == ()


@pytest.mark.parametrize("text", [
    "bogus: 1\n",
    "server: {hots: x}\n",
    "auth: {oidc: {issuer: a, client_id: b, nope: 1}}\n",
    "workspaces: [{name: a, store: file:///x, extra: 1}]\n",
    "auth: {role_mappings: [{group: g, workspace: w, role: r, x: 1}]}\n",
])
def test_unknown_keys_are_errors(tmp_path, text):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, text))


@pytest.mark.parametrize("text", [
    "server: {tenancy: weird}\n",
    "workspaces: [{name: a, store: file:///x, downloads: maybe}]\n",
    "workspaces: [{store: file:///x}]\n",
    "server: {port: notanint}\n",
    "- a list\n",
])
def test_invalid_values_are_errors(tmp_path, text):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, text))


def test_flags_override_file(tmp_path):
    cfg = resolve_config(_args(config=_full(tmp_path), host="10.0.0.1", port=1234,
                               db="sqlite:///other", data_dir="/d"), env={})
    assert cfg.server.host == "10.0.0.1" and cfg.server.port == 1234
    assert cfg.db == "sqlite:///other" and cfg.data_dir == "/d"


def test_default_flags_do_not_override_file(tmp_path):
    cfg = resolve_config(_args(config=_full(tmp_path)), env={})
    assert cfg.server.host == "0.0.0.0" and cfg.server.port == 9000


def test_env_overrides_file_and_flags_beat_env(tmp_path):
    env = {"VMN_UI_DB": "sqlite:///env", "VMN_UI_PUBLIC_URL": "https://env"}
    cfg = resolve_config(_args(config=_full(tmp_path)), env=env)
    assert cfg.db == "sqlite:///env" and cfg.server.public_url == "https://env"
    cfg = resolve_config(_args(config=_full(tmp_path), db="sqlite:///flag"), env=env)
    assert cfg.db == "sqlite:///flag"


def test_token_from_static_token_env(tmp_path):
    cfg = resolve_config(_args(config=_full(tmp_path)), env={})
    assert cfg.token(env={"MY_TOKEN": "s3cret"}) == "s3cret"
    assert cfg.token(env={}) is None
    cfg = resolve_config(_args(config=_full(tmp_path), token="flag"), env={})
    assert cfg.token(env={"MY_TOKEN": "s3cret"}) == "flag"


def test_no_config_no_db_is_none():
    assert resolve_config(_args(), env={}) is None


def test_data_dir_expands_user(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = _write(tmp_path, "data_dir: ~/vmn-data\n")
    cfg = resolve_config(_args(config=path), env={})
    assert cfg.data_dir == str(tmp_path / "vmn-data")
