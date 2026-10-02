#!/usr/bin/env python3
"""Who a request acts as: an id, a display name and a role per workspace."""
from dataclasses import dataclass, field

VIEWER = "viewer"
EDITOR = "editor"
ADMIN = "admin"
ROLES = (VIEWER, EDITOR, ADMIN)
ALL_WORKSPACES = "*"


def check_roles(roles):
    """*roles* as a plain dict, refusing role names vmn does not know."""
    for role in roles.values():
        if role not in ROLES:
            raise ValueError(f"Unknown role '{role}' (expected one of {ROLES})")
    return dict(roles)


def stronger(a, b):
    """The higher of two roles (``None`` is no role)."""
    rank = {None: -1, **{r: i for i, r in enumerate(ROLES)}}
    return a if rank[a] >= rank[b] else b


@dataclass(frozen=True)
class Principal:
    id: str
    name: str
    roles: dict = field(default_factory=dict)
    groups: tuple = ()

    def role_in(self, workspace):
        """The role in *workspace*: its own entry, else the ``*`` one."""
        return stronger(self.roles.get(workspace), self.roles.get(ALL_WORKSPACES))
