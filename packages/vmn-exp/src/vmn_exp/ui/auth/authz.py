#!/usr/bin/env python3
"""Authorization: roles ``viewer < editor < admin`` per workspace.

Every API route declares a role with ``dependencies=[require(role)]``. The
check reads ``request.state.principal`` (set by the authenticator chain) and
the workspace from the path (``ws_name``; routes without one need the role in
``*``, except plain reads, which any role allows). The principal's own roles
combine with the group mappings on ``app.state.role_mappings``. With no
authentication configured (``app.state.auth_enabled`` false) everything is
allowed, as before.
"""
from fastapi import Depends, HTTPException, Request

from vmn_exp.ui.auth.oidc import roles_for_groups
from vmn_exp.ui.auth.principal import ADMIN, ALL_WORKSPACES, EDITOR, ROLES, VIEWER, stronger

# Job actions that need more than ``editor``.
ACTION_ROLES = {"prune": ADMIN}


def effective_role(principal, workspace, mappings=()):
    """The strongest role *principal* holds in *workspace* (``None``: none)."""
    mapped = roles_for_groups(principal.groups, mappings)
    keys = (ALL_WORKSPACES,) if workspace is None else (workspace, ALL_WORKSPACES)
    role = None
    for key in keys:
        role = stronger(role, stronger(principal.roles.get(key), mapped.get(key)))
    return role


def _any_role(principal, mappings):
    mapped = roles_for_groups(principal.groups, mappings)
    return bool(principal.roles) or bool(mapped)


def allowed(principal, workspace, role, mappings=()):
    if workspace is None and role == VIEWER:
        return _any_role(principal, mappings)
    held = effective_role(principal, workspace, mappings)
    return held is not None and ROLES.index(held) >= ROLES.index(role)


class RoleCheck:
    """The dependency ``require(role)`` installs; ``role`` is introspectable."""

    def __init__(self, role):
        self.role = role

    def __call__(self, request: Request):
        self.enforce(request, self.role)

    @staticmethod
    def enforce(request, role):
        state = request.app.state
        if not getattr(state, "auth_enabled", False):
            return
        principal = getattr(request.state, "principal", None)
        if principal is None:
            raise HTTPException(401, "Unauthorized")
        workspace = request.path_params.get("ws_name")
        if not allowed(principal, workspace, role, getattr(state, "role_mappings", ())):
            raise HTTPException(403, f"Requires role '{role}'")


class ActionRoleCheck(RoleCheck):
    """Job actions: ``editor``, or the stronger role in :data:`ACTION_ROLES`."""

    def __call__(self, request: Request):
        action = request.path_params.get("action")
        self.enforce(request, ACTION_ROLES.get(action, self.role))


def require(role):
    return Depends(RoleCheck(role))


def require_action():
    return Depends(ActionRoleCheck(EDITOR))


def route_role(route):
    """The role a route declares, or ``None``."""
    for dep in route.dependant.dependencies:
        if isinstance(dep.call, RoleCheck):
            return dep.call.role
    return None
