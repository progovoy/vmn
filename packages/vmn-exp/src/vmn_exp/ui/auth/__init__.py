#!/usr/bin/env python3
"""Authentication for vmn-exp ui: an ordered chain of authenticators.

Each authenticator returns a :class:`Principal` for a request it recognises,
else ``None``. Authorization (roles per route) is applied later, from
``request.state.principal``.
"""


class AuthenticatorChain:
    def __init__(self, authenticators):
        self.authenticators = list(authenticators)

    def __bool__(self):
        return bool(self.authenticators)

    def authenticate(self, request):
        for authenticator in self.authenticators:
            principal = authenticator.authenticate(request)
            if principal is not None:
                return principal
        return None

    def routers(self):
        """Login/logout routes the authenticators serve (OIDC)."""
        return [a.router() for a in self.authenticators if hasattr(a, "router")]


def build_chain(token=None, extra=()):
    from vmn_exp.ui.auth.static import StaticTokenAuthenticator

    first = [StaticTokenAuthenticator(token)] if token else []
    return AuthenticatorChain(first + list(extra))
