#!/usr/bin/env python3
"""What the dashboard shell knows about the server: versions, deployment,
the sign-in methods and the caller's role (``/meta``, ``/workspaces``, the
401 body). Methods only, never a secret."""
import functools
from importlib import metadata

from vmn_exp.ui.auth.authz import effective_role
from vmn_exp.ui.auth.static import StaticTokenAuthenticator

LOGIN_URL = "/auth/login"


def auth_hints(chain):
    """``{token, oidc, login_url}``: how a client may sign in to *chain*."""
    authenticators = chain.authenticators
    oidc = any(hasattr(a, "router") for a in authenticators)
    return {
        "token": any(isinstance(a, StaticTokenAuthenticator) for a in authenticators),
        "oidc": oidc,
        "login_url": LOGIN_URL if oidc else None,
    }


@functools.cache
def _vmn_exp_version():
    try:
        return metadata.version("vmn-exp")
    except metadata.PackageNotFoundError:
        return None


def workspace_role(app_state, principal, ws_name):
    """*principal*'s role in *ws_name* (``*`` included); None with auth off."""
    if not app_state.auth_enabled or principal is None:
        return None
    return effective_role(principal, ws_name, app_state.role_mappings)


def meta_payload(app_state, principal, read_only):
    """The ``/meta`` body. *app_state* is read now: ``server_app`` sets
    ``config`` after ``create_app``."""
    from version_stamp.api import version as version_mod

    control_plane = app_state.control_plane is not None
    configured = getattr(app_state, "config", None) is not None or control_plane
    return {
        "version": version_mod.version,
        "vmn_exp_version": _vmn_exp_version(),
        "read_only": read_only,
        "mode": "configured" if configured else "standalone",
        "control_plane": control_plane,
        "auth": {
            "enabled": app_state.auth_enabled,
            **auth_hints(app_state.auth_chain),
        },
        "principal": principal and {"id": principal.id, "name": principal.name},
        "role": workspace_role(app_state, principal, None),
    }
