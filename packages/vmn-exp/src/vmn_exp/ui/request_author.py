"""Who a report/comment write is attributed to, and the author-or-admin rule."""
from fastapi import HTTPException

from vmn_exp.registry.log import actor_identity
from vmn_exp.ui.auth.authz import effective_role
from vmn_exp.ui.auth.principal import ADMIN


def _principal(request):
    return getattr(request.state, "principal", None)


def author_of(request):
    """The request principal as ``{id, name}``, else the server's identity."""
    principal = _principal(request)
    if principal is None:
        return actor_identity()
    return {"id": principal.id, "name": principal.name}


def require_author_or_admin(request, ws_name, author):
    """Refuse (403) a principal that neither wrote *author*'s item nor is admin.
    Without authentication nothing is enforced (plan 13 decision 2)."""
    principal = _principal(request)
    if principal is None or not getattr(request.app.state, "auth_enabled", False):
        return
    if (author or {}).get("id") == principal.id:
        return
    mappings = getattr(request.app.state, "role_mappings", ())
    if effective_role(principal, ws_name, mappings) != ADMIN:
        raise HTTPException(403, "Only the author or an admin may change this")
