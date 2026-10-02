#!/usr/bin/env python3
"""``vmn-exp ui --config server.yml``: the server's configuration (plan 11 §8).

The file is parsed into frozen dataclasses; unknown keys are an error.
Precedence per key: flag > environment variable > file > default.
"""
import dataclasses
import os
from dataclasses import dataclass
from typing import Optional, Tuple

import yaml

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8265
DEFAULT_DATA_DIR = os.path.join(os.path.expanduser("~"), ".vmn-ui")
TENANCIES = ("single", "multi")
DOWNLOAD_MODES = ("stream", "redirect")

# Environment fallbacks for keys that have no other env var.
ENV_DB = "VMN_UI_DB"
ENV_DATA_DIR = "VMN_UI_DATA_DIR"
ENV_PUBLIC_URL = "VMN_UI_PUBLIC_URL"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ServerSection:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    public_url: Optional[str] = None
    tenancy: str = "single"


@dataclass(frozen=True)
class OIDCSection:
    issuer: str
    client_id: str
    client_secret_env: Optional[str] = None
    groups_claim: str = "groups"


@dataclass(frozen=True)
class RoleMapping:
    group: str
    workspace: str
    role: str


@dataclass(frozen=True)
class AuthSection:
    static_token_env: Optional[str] = None
    oidc: Optional[OIDCSection] = None
    role_mappings: Tuple[RoleMapping, ...] = ()


@dataclass(frozen=True)
class WorkspaceSeed:
    name: str
    store: str
    downloads: str = "stream"
    reconcile_sec: Optional[int] = None


@dataclass(frozen=True)
class ServerConfig:
    server: ServerSection = ServerSection()
    db: Optional[str] = None
    data_dir: str = DEFAULT_DATA_DIR
    auth: AuthSection = AuthSection()
    workspaces: Tuple[WorkspaceSeed, ...] = ()

    def token(self, env=None):
        """The static API token: the ``--token`` flag recorded at resolve
        time, else the env var named by ``auth.static_token_env``."""
        env = os.environ if env is None else env
        if self._flag_token:
            return self._flag_token
        name = self.auth.static_token_env or "VMN_UI_TOKEN"
        return env.get(name) or None

    _flag_token: Optional[str] = dataclasses.field(default=None, repr=False)


def _build(cls, data, where):
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: expected a mapping")
    names = {f.name for f in dataclasses.fields(cls) if not f.name.startswith("_")}
    unknown = sorted(set(data) - names)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(map(str, unknown))}")
    try:
        return cls(**data)
    except TypeError as e:
        raise ConfigError(f"{where}: {e}")


def _int(value, where):
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise ConfigError(f"{where}: expected an integer, got {value!r}")


def _choice(value, choices, where):
    if value not in choices:
        raise ConfigError(f"{where}: expected one of {', '.join(choices)}, got {value!r}")
    return value


def _server(data):
    s = _build(ServerSection, data or {}, "server")
    _int(s.port, "server.port")
    _choice(s.tenancy, TENANCIES, "server.tenancy")
    return s


def _auth(data):
    data = {} if data is None else data
    if not isinstance(data, dict):
        raise ConfigError("auth: expected a mapping")
    data = dict(data)
    if data.get("oidc") is not None:
        data["oidc"] = _build(OIDCSection, data["oidc"], "auth.oidc")
    data["role_mappings"] = tuple(
        _build(RoleMapping, m, f"auth.role_mappings[{i}]")
        for i, m in enumerate(data.get("role_mappings") or ())
    )
    return _build(AuthSection, data, "auth")


def _workspace(data, i):
    ws = _build(WorkspaceSeed, data, f"workspaces[{i}]")
    _choice(ws.downloads, DOWNLOAD_MODES, f"workspaces[{i}].downloads")
    _int(ws.reconcile_sec, f"workspaces[{i}].reconcile_sec")
    return ws


def parse_config(data):
    data = {} if data is None else data
    if not isinstance(data, dict):
        raise ConfigError("config: expected a mapping")
    fields = dict(data)
    fields["server"] = _server(data.get("server"))
    fields["auth"] = _auth(data.get("auth"))
    fields["workspaces"] = tuple(
        _workspace(w, i) for i, w in enumerate(data.get("workspaces") or ())
    )
    if fields.get("data_dir") is None:
        fields.pop("data_dir", None)
    return _build(ServerConfig, fields, "config")


def load_config(path):
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except OSError as e:
        raise ConfigError(f"Cannot read config {path}: {e}")
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}")
    return parse_config(data)


def _flag(args, name, default=None):
    """A flag's value when the user set it (argparse defaults don't count)."""
    value = getattr(args, name, None)
    return None if value == default else value


def resolve_config(args, env=None):
    """The effective config for a ``vmn-exp ui`` invocation, or ``None``
    when neither ``--config`` nor a DB (flag or env) is given — today's
    standalone behaviour."""
    env = os.environ if env is None else env
    path = getattr(args, "config", None)
    db = _flag(args, "db") or env.get(ENV_DB)
    if not path and not db:
        return None
    cfg = load_config(path) if path else ServerConfig()
    server = dataclasses.replace(
        cfg.server,
        host=_flag(args, "host", DEFAULT_HOST) or cfg.server.host,
        port=_flag(args, "port", DEFAULT_PORT) or cfg.server.port,
        public_url=env.get(ENV_PUBLIC_URL) or cfg.server.public_url,
    )
    return dataclasses.replace(
        cfg,
        server=server,
        db=db or cfg.db,
        data_dir=_flag(args, "data_dir") or env.get(ENV_DATA_DIR) or cfg.data_dir,
        _flag_token=getattr(args, "token", None),
    )
